#!/usr/bin/env node
// text-fidelity.mjs — the rendered text must be the requested text, set the way it was authored.
//
// Two checks, both about what the export actually contains rather than what the HTML says:
//
//   1. Glyph advances (pure Node, no browser): decode a produced PDF and fail if its glyph advances
//      came out on a whole-unit grid. Headless Chromium rounds advances to whole pixels unless it
//      launches with CHROMIUM_TEXT_ARGS; flags can be dropped, overridden or ignored by a future
//      Chromium, so the audit is what holds the invariant at the delivery boundary.
//   2. Copy (needs the sandbox browser): load a page, read the text it actually renders (after CSS
//      text-transform, hidden elements excluded) and fail if any requested line is missing or came
//      out cased differently.
//
// Usage:
//   node /workspace/tools/text-fidelity.mjs <file.pdf> [--json]
//   node /workspace/tools/text-fidelity.mjs --html <page.html> --expect <copy.txt> [--size 1080x1350] [--json]
//
// Exit: 0 pass · 1 findings · 2 the check could not run (missing file, bad arguments, no browser).
// Import: `import { CHROMIUM_EXPORT_ARGS, auditPdfGlyphAdvances } from "./text-fidelity.mjs";`

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { inflateSync } from "node:zlib";
import {
  CHROMIUM_EXPORT_ARGS,
  CHROMIUM_TEXT_ARGS,
  EXIT,
  ToolingError,
  WORKSPACE,
  isMain,
  launchBrowser,
  parseFlags,
  requireFile,
  runCli,
} from "./toolchain.mjs";

export { CHROMIUM_EXPORT_ARGS, CHROMIUM_TEXT_ARGS };

// --- glyph-advance audit --------------------------------------------------------------------------
// A healthy proportional run has a different fractional carry on nearly every advance, because each
// glyph's true width lands wherever it lands. A quantized run has integer advances plus one constant
// letter-spacing delta, so the integer part moves and the fraction never does (7.87468, 3.87468,
// 10.87468 ...).
//
// Monospace is the trap: there every advance is legitimately identical, giving one fractional part
// too. It is separated by requiring the integer parts to VARY -- a mono run has one of those as well,
// a quantized proportional run has many.

const MIN_GLYPHS = 20;      // below this, a shared fraction is plausible coincidence
const MAX_FRACTIONS = 2;    // a real proportional run blows past this immediately
const MIN_INTEGERS = 3;     // separates quantized-proportional from genuine monospace

function inflateStreams(bytes) {
  const out = [];
  const marker = Buffer.from("stream");
  let i = bytes.indexOf(marker);
  while (i !== -1) {
    let s = i + marker.length;
    if (bytes[s] === 0x0d) s++;
    if (bytes[s] === 0x0a) s++;
    const e = bytes.indexOf(Buffer.from("endstream"), s);
    if (e === -1) break;
    try { out.push(inflateSync(bytes.subarray(s, e)).toString("latin1")); } catch { /* not flate, skip */ }
    i = bytes.indexOf(marker, e);
  }
  return out;
}

// Split a content stream into BT..ET text objects, each carrying the font size its Tf declared.
function textRuns(content) {
  const runs = [];
  for (const block of content.split(/\bBT\b/).slice(1)) {
    const body = block.split(/\bET\b/)[0];
    const tf = /\/[A-Za-z0-9_.-]+\s+(-?\d+\.?\d*)\s+Tf/.exec(body);
    if (!tf) continue;
    const size = Math.abs(Number(tf[1]));
    if (!(size > 0)) continue;
    const advances = [...body.matchAll(/(-?\d+\.?\d*)\s+(-?\d+\.?\d*)\s+Td\b/g)]
      .map((m) => Number(m[1]))
      .filter((x) => Number.isFinite(x) && Math.abs(x) > 1e-9);
    const glyphOps = (body.match(/\bTj\b/g) || []).length;
    const kernedOps = (body.match(/\bTJ\b/g) || []).length;
    runs.push({ size, advances, glyphOps, kernedOps });
  }
  return runs;
}

function classify(run) {
  const { advances, size } = run;
  if (advances.length < MIN_GLYPHS) return { verdict: "skipped", reason: "run too short to judge" };
  const key = (x) => Math.round(x * 1e4) / 1e4;
  const fractions = new Set(advances.map((x) => key(Math.abs(x) - Math.floor(Math.abs(x)))));
  const integers = new Set(advances.map((x) => Math.floor(Math.abs(x))));
  const quantized = fractions.size <= MAX_FRACTIONS && integers.size >= MIN_INTEGERS;
  return {
    verdict: quantized ? "quantized" : "subpixel",
    fontSize: size,
    glyphs: advances.length,
    distinctFractions: fractions.size,
    distinctIntegers: integers.size,
    // The rounding step is one whole unit; worst-case placement error is half of it.
    worstErrorPctEm: quantized ? Number(((0.5 / size) * 100).toFixed(2)) : null,
  };
}

/**
 * Audit a PDF's glyph advances.
 * @param {Buffer|Uint8Array} bytes raw PDF
 * @returns {{ok: boolean, runs: object[], offenders: object[], perGlyphPlacement: boolean}}
 */
export function auditPdfGlyphAdvances(bytes) {
  const buf = Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes);
  const runs = inflateStreams(buf).flatMap(textRuns).map((run) => ({ ...run, ...classify(run) }));
  const offenders = runs.filter((r) => r.verdict === "quantized");
  const judged = runs.filter((r) => r.verdict !== "skipped");
  return {
    ok: offenders.length === 0,
    perGlyphPlacement: runs.some((r) => r.glyphOps > 1 && r.kernedOps === 0),
    runsJudged: judged.length,
    runs,
    offenders,
  };
}

/** Throw with an actionable message if any run came out quantized. */
export function assertPdfGlyphAdvances(bytes, label = "export") {
  const report = auditPdfGlyphAdvances(bytes);
  if (report.ok) return report;
  const worst = report.offenders.reduce((a, b) => (b.worstErrorPctEm > a.worstErrorPctEm ? b : a));
  throw new Error(
    `text-fidelity: ${label} shipped quantized glyph advances in ${report.offenders.length} run(s). ` +
      `Worst: ${worst.fontSize}pt text placed on a whole-unit grid = +/-${worst.worstErrorPctEm}% of an em. ` +
      `Launch Chromium with CHROMIUM_TEXT_ARGS, or lay the page out at N x zoom and print at scale 1/N.`,
  );
}

// --- copy check -----------------------------------------------------------------------------------
const collapse = (text) => text.normalize("NFC").replace(/[\s\u00a0\u2007\u202f]+/g, " ").trim();

/**
 * Compare requested copy with the text a page renders. Every non-empty line of `expected` must
 * appear verbatim (whitespace-collapsed) in the rendered text. A line that only matches ignoring
 * case was re-cased by CSS or retyped; it is reported as such.
 */
export function compareCopy(expected, rendered) {
  const haystack = collapse(rendered);
  const lower = haystack.toLowerCase();
  const lines = expected.split(/\r?\n/).map(collapse).filter(Boolean);
  const problems = [];
  for (const line of lines) {
    if (haystack.includes(line)) continue;
    const at = lower.indexOf(line.toLowerCase());
    problems.push(
      at >= 0
        ? { line, problem: "casing", rendered: haystack.slice(at, at + line.length) }
        : { line, problem: "missing" },
    );
  }
  return { ok: problems.length === 0, lines: lines.length, problems };
}

async function renderedText(html, size) {
  const browser = await launchBrowser(["--allow-file-access-from-files"]);
  try {
    const page = await browser.newPage();
    await page.setViewport(size);
    await page.goto(pathToFileURL(html).href, { waitUntil: "networkidle0", timeout: 30000 });
    await page.evaluate(() => document.fonts?.ready);
    return await page.evaluate(() => document.body?.innerText || "");
  } finally {
    await browser.close().catch(() => {});
  }
}

// --- CLI ------------------------------------------------------------------------------------------
function printAudit(report, target) {
  for (const r of report.runs.filter((x) => x.verdict !== "skipped")) {
    const detail = `${r.fontSize}pt  ${r.glyphs} glyphs  ${r.distinctFractions} distinct fractional carries`;
    console.log(
      r.verdict === "quantized"
        ? `  ERROR  ${detail}  -> whole-unit grid, +/-${r.worstErrorPctEm}% of an em`
        : `  ok     ${detail}`,
    );
  }
  console.log(
    report.ok
      ? `__TEXT_FIDELITY_OK__ ${report.runsJudged} run(s) judged, advances subpixel`
      : `text-fidelity: ${report.offenders.length} quantized run(s) in ${target}`,
  );
}

function printCopy(report, html) {
  for (const p of report.problems) {
    console.log(
      p.problem === "casing"
        ? `  ERROR  "${p.line}" renders as "${p.rendered}" (re-cased by CSS or retyped)`
        : `  ERROR  "${p.line}" is not in the rendered text`,
    );
  }
  console.log(
    report.ok
      ? `__TEXT_FIDELITY_OK__ ${report.lines} requested line(s) render verbatim`
      : `text-fidelity: ${report.problems.length} of ${report.lines} requested line(s) differ in ${html}`,
  );
}

if (isMain(import.meta.url)) {
  await runCli("text-fidelity", async () => {
    const { flags, positionals } = parseFlags(process.argv.slice(2), {
      values: ["html", "expect", "size"],
      booleans: ["json"],
    });
    if (flags.html || flags.expect) {
      if (!flags.html || !flags.expect || positionals.length) {
        throw new ToolingError("usage: text-fidelity.mjs --html <page.html> --expect <copy.txt> [--size WxH] [--json]");
      }
      const size = /^(\d{1,5})x(\d{1,5})$/.exec(flags.size || "1920x1080");
      if (!size) throw new ToolingError(`--size must look like 1080x1350, got "${flags.size}"`);
      const html = requireFile(resolve(WORKSPACE, flags.html), "page");
      const expected = readFileSync(requireFile(resolve(WORKSPACE, flags.expect), "expected copy"), "utf8");
      const report = compareCopy(expected, await renderedText(html, { width: Number(size[1]), height: Number(size[2]) }));
      if (!report.lines) throw new ToolingError(`${flags.expect} holds no copy to compare`);
      if (flags.json) console.log(JSON.stringify(report));
      else printCopy(report, flags.html);
      return report.ok ? EXIT.PASS : EXIT.FINDINGS;
    }
    if (positionals.length !== 1) throw new ToolingError("usage: text-fidelity.mjs <file.pdf> [--json]");
    const bytes = readFileSync(requireFile(resolve(WORKSPACE, positionals[0]), "PDF"));
    if (bytes.subarray(0, 5).toString("latin1") !== "%PDF-") throw new ToolingError(`${positionals[0]} is not a PDF`);
    const report = auditPdfGlyphAdvances(bytes);
    if (flags.json) console.log(JSON.stringify(report));
    else printAudit(report, positionals[0]);
    return report.ok ? EXIT.PASS : EXIT.FINDINGS;
  });
}
