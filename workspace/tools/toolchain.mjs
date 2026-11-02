// toolchain.mjs — what every gate shares: the exit-code contract, flag parsing, workspace
// confinement, brand tokens, and the sandbox render toolchain (puppeteer-core, sharp, Chrome).
//
// Node packages resolve from the sandbox's pinned install (sandbox/render/, baked into
// /opt/design-agent/render), never from a copy under /workspace: the stager refreshes the workspace
// every run, so a node_modules there would drift from the pinned lock. The browser is the one Chrome
// Headless Shell the recipe installs. A missing package or browser is a tooling failure (exit 2),
// never a pass.
//
//   DESIGN_AGENT_RENDER_DIR   directory holding the render package.json (default /opt/design-agent/render)
//   DESIGN_AGENT_BROWSER      Chrome executable (default /usr/local/bin/chrome-headless-shell)

import { existsSync, readFileSync, realpathSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

// Headless Chromium turns off subpixel glyph positioning below device scale factor 1.5, and always
// for page.pdf(), then rounds every glyph advance to a whole pixel: at 12px that is +/-4% of an em,
// so tracked type clumps in the export while the authored HTML measures perfect.
// `enable-font-subpixel-positioning` keeps advances fractional; `font-render-hinting=none` keeps the
// outlines from being grid-fit (a separate stage, so both are needed). Text-only on purpose: a
// colour-management flag here would silently shift every export already delivered.
export const CHROMIUM_TEXT_ARGS = Object.freeze([
  "--font-render-hinting=none",
  "--enable-font-subpixel-positioning",
]);
/** Every browser export launches with exactly these; a divergent list is how the defect returns. */
export const CHROMIUM_EXPORT_ARGS = Object.freeze([
  "--no-sandbox",
  "--disable-dev-shm-usage",
  ...CHROMIUM_TEXT_ARGS,
]);

export const TOOLS_DIR = dirname(fileURLToPath(import.meta.url));
/** The workspace the tools sit in: /workspace in the sandbox. */
export const WORKSPACE = resolve(TOOLS_DIR, "..");
export const DEFAULT_TOKENS = join(WORKSPACE, "brand", "tokens.json");
export const RENDER_DIR = process.env.DESIGN_AGENT_RENDER_DIR || "/opt/design-agent/render";
export const BROWSER = process.env.DESIGN_AGENT_BROWSER || "/usr/local/bin/chrome-headless-shell";

/** 0 pass · 1 findings (ERROR) · 2 the probe could not run. */
export const EXIT = Object.freeze({ PASS: 0, FINDINGS: 1, TOOLING: 2 });

/** A failure of the tool, its arguments or its environment. Always exit 2, never a pass. */
export class ToolingError extends Error {}

/** True when `moduleUrl` is the script node was started with. */
export function isMain(moduleUrl) {
  if (!process.argv[1]) return false;
  try {
    return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(moduleUrl));
  } catch {
    return resolve(process.argv[1]) === fileURLToPath(moduleUrl);
  }
}

/**
 * Run a CLI body that returns an exit code. Any thrown error is a tooling failure (exit 2): a gate
 * that crashed did not check anything. Sets `process.exitCode` instead of calling `process.exit`, so
 * piped stdout finishes flushing.
 */
export async function runCli(name, body) {
  try {
    process.exitCode = (await body()) ?? EXIT.PASS;
  } catch (error) {
    const message = error instanceof ToolingError ? error.message : error?.stack || String(error);
    console.error(`${name}: ${message}`);
    process.exitCode = EXIT.TOOLING;
  }
}

/**
 * `--name value`, repeatable `multi` flags and `booleans`. An unknown flag or a missing value is a
 * tooling failure, so a typo never turns into a silently skipped check.
 */
export function parseFlags(argv, { values = [], multi = [], booleans = [] } = {}) {
  const flags = Object.fromEntries(multi.map((name) => [name, []]));
  const positionals = [];
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (!arg.startsWith("--")) {
      positionals.push(arg);
      continue;
    }
    const name = arg.slice(2);
    if (booleans.includes(name)) {
      flags[name] = true;
      continue;
    }
    if (!values.includes(name) && !multi.includes(name)) throw new ToolingError(`unknown flag ${arg}`);
    const value = argv[i + 1];
    if (value === undefined || value.startsWith("--")) throw new ToolingError(`${arg} needs a value`);
    i++;
    if (multi.includes(name)) flags[name].push(value);
    else flags[name] = value;
  }
  return { flags, positionals };
}

/** Resolve `input` against `root` and refuse anything that lands outside it. */
export function confined(root, input, label = "path") {
  if (typeof input !== "string" || !input || input.includes("\0")) {
    throw new ToolingError(`${label} must be a non-empty path`);
  }
  const base = resolve(root);
  const abs = resolve(base, input);
  const rel = relative(base, abs);
  if (rel === ".." || rel.startsWith(`..${sep}`) || isAbsolute(rel)) {
    throw new ToolingError(`${label} escapes the workspace root ${base}: ${input}`);
  }
  return abs;
}

/** `abs` must be an existing regular file; otherwise the probe cannot run. */
export function requireFile(abs, label = "file") {
  if (!existsSync(abs) || !statSync(abs).isFile()) throw new ToolingError(`${label} is not a file: ${abs}`);
  return abs;
}

/** Parse brand tokens.json. A missing or unreadable pack is a tooling failure. */
export function loadTokens(path) {
  let text;
  try {
    text = readFileSync(path, "utf8");
  } catch (error) {
    throw new ToolingError(`cannot read brand tokens ${path} (${error.code || error.message})`);
  }
  try {
    const tokens = JSON.parse(text);
    if (!tokens?.design || !tokens?.copy) throw new Error("missing design or copy section");
    return tokens;
  } catch (error) {
    throw new ToolingError(`brand tokens ${path} are invalid: ${error.message}`);
  }
}

/** The lead face of each brand font stack (display, text, mono), deduplicated. */
export function brandLeadFonts(tokens) {
  const stacks = tokens.design.fontStacks || {};
  return [...new Set(["display", "text", "mono"].map((role) => stacks[role]?.[0]).filter(Boolean))];
}

/** `require` a package from the pinned render toolchain. */
export function renderRequire(name) {
  try {
    return createRequire(join(RENDER_DIR, "package.json"))(name);
  } catch (error) {
    throw new ToolingError(
      `${name} is not installed in ${RENDER_DIR} (${error.code || error.message}); run inside the ` +
        "sandbox image or set DESIGN_AGENT_RENDER_DIR to a directory with the pinned render toolchain",
    );
  }
}

/** Launch the sandbox Chrome with the shared export flags. */
export async function launchBrowser(extraArgs = []) {
  const puppeteer = renderRequire("puppeteer-core");
  if (!existsSync(BROWSER)) {
    throw new ToolingError(`no browser at ${BROWSER}; set DESIGN_AGENT_BROWSER or run inside the sandbox image`);
  }
  try {
    return await puppeteer.launch({
      executablePath: BROWSER,
      headless: "shell",
      args: [...CHROMIUM_EXPORT_ARGS, ...extraArgs],
    });
  } catch (error) {
    throw new ToolingError(`could not launch ${BROWSER}: ${error.message}`);
  }
}

/** Collect page errors and failed requests while a page loads. */
export function watchPage(page) {
  const problems = { pageErrors: [], failedRequests: [] };
  page.on("pageerror", (error) => problems.pageErrors.push(String(error?.message || error).slice(0, 300)));
  page.on("requestfailed", (request) =>
    problems.failedRequests.push(`${request.url().slice(0, 200)} (${request.failure()?.errorText || "failed"})`),
  );
  return problems;
}

const PROBE_ATTR = "data-design-agent-font-probe";

/**
 * Families that did not actually render. `document.fonts.check()` alone cannot prove a family
 * resolved: Chromium answers true for any family no @font-face declares, installed or not. So each
 * family must pass `check()` (which fails a declared face that did not load) AND paint a probe span
 * that CDP attributes to that platform font. A missing font never fails loudly in a browser; this is
 * what makes it fail.
 * @returns {Promise<{family: string, renderedWith: string}[]>}
 */
export async function unresolvedFonts(page, families) {
  if (!families.length) return [];
  await page.evaluate(() => document.fonts?.ready);
  const cdp = await page.createCDPSession();
  const missing = [];
  try {
    await cdp.send("DOM.enable");
    await cdp.send("CSS.enable");
    for (const family of families) {
      const checked = await page.evaluate(
        async (name, attr) => {
          const spec = `16px ${JSON.stringify(name)}`;
          try {
            await document.fonts.load(spec);
          } catch {
            /* check() below reports it */
          }
          const probe = document.createElement("span");
          probe.setAttribute(attr, "");
          probe.textContent = "Hamburgefonstiv 0123456789";
          probe.style.setProperty("position", "absolute", "important");
          probe.style.setProperty("left", "-10000px", "important");
          probe.style.setProperty("top", "0", "important");
          probe.style.setProperty("font-family", `${JSON.stringify(name)}, monospace`, "important");
          document.body.appendChild(probe);
          // CDP reports platform fonts from layout, so lay the probe out and let a frame paint.
          void probe.getBoundingClientRect();
          await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
          return document.fonts.check(spec);
        },
        family,
        PROBE_ATTR,
      );
      const { root } = await cdp.send("DOM.getDocument", { depth: 1 });
      const { nodeId } = await cdp.send("DOM.querySelector", { nodeId: root.nodeId, selector: `[${PROBE_ATTR}]` });
      const { fonts } = await cdp.send("CSS.getPlatformFontsForNode", { nodeId });
      await page.evaluate((attr) => document.querySelectorAll(`[${attr}]`).forEach((el) => el.remove()), PROBE_ATTR);
      const used = fonts.map((font) => font.familyName);
      // A system font reports its family; a web font (an @font-face rule, as woff2 faces must be)
      // reports the name inside its file ("Brand Sans 250"), so it counts when a face registered
      // under the requested family loaded and a web font painted the probe.
      const webFace = await page.evaluate(
        (name) =>
          [...document.fonts].some(
            (face) => face.status === "loaded" && face.family.replace(/^["']|["']$/g, "").toLowerCase() === name.toLowerCase(),
          ),
        family,
      );
      const painted =
        used.some((name) => name.toLowerCase() === family.toLowerCase()) || (webFace && fonts.some((font) => font.isCustomFont));
      if (!checked || !painted) {
        missing.push({ family, renderedWith: used.join(", ") || "nothing" });
      }
    }
  } finally {
    await cdp.detach().catch(() => {});
  }
  return missing;
}
