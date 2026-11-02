#!/usr/bin/env node
// video-score.mjs — the correctness gate for a composition. Pass/fail on real defects; the axis numbers
// are a diagnostic you read, never a target to beat.
//
// It runs the hard gates (video-gate's seek-breaking scan, and brand-lint against the active brand
// pack) and then LOADS THE COMPOSITION IN THE REAL RENDERER and measures the artifact: what is on
// screen at every sampled frame, what changes, and what the rendered pixels look like. It fails on a
// failed hard gate and on the defects a film must not have — a blank frame, cuts that carry nothing, a
// shot that never develops, content the stage silently crops (film-analysis.mjs) — and exits 2 when
// the probe could not run.
//
// There is no passing score. Any cheap proxy for taste gets optimised once it is named as the target:
// scored on the source string, a black rectangle with two font sizes and brand tokens scores 100/100.
// So the axes print (Coherence · Color · Hierarchy · Layout · Motion · Copy) as a reading aid, and
// Hierarchy, Layout and Motion are measured on the rendered artifact, not on declarations.
//
// Usage:
//   node /workspace/tools/video-score.mjs <composition.html> [--tokens <tokens.json>] [--no-brand]
//        [--step 0.1] [--json] [--no-probe] [--root <dir>]
// --no-probe skips the render (source-only axes, and the verdict says the artifact was not measured).
// Exit: 0 pass · 1 a hard gate or the artifact failed · 2 a gate or the probe could not run.

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { analyseFilm } from "./film-analysis.mjs";
import { probeFilm } from "./film-probe.mjs";
import { EXIT, TOOLS_DIR, ToolingError, WORKSPACE, confined, parseFlags, requireFile, runCli } from "./toolchain.mjs";

const MAX = { Coherence: 20, Color: 16, Hierarchy: 20, Layout: 16, Motion: 16, Copy: 12 };

/** Run a sibling gate with --json; exit 2 from it means this gate cannot run either. */
function gate(tool, args) {
  const result = spawnSync(process.execPath, [join(TOOLS_DIR, tool), ...args, "--json"], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  if (result.status === EXIT.TOOLING || result.status === null) {
    throw new ToolingError(`${tool} could not run: ${(result.stderr || result.error?.message || "").trim().split("\n").at(-1)}`);
  }
  try {
    return { status: result.status, report: JSON.parse(result.stdout) };
  } catch {
    throw new ToolingError(`${tool} printed no JSON report`);
  }
}

await runCli("video-score", async () => {
  const { flags, positionals } = parseFlags(process.argv.slice(2), {
    values: ["tokens", "step", "root"],
    booleans: ["json", "no-probe", "no-brand"],
  });
  if (positionals.length !== 1) throw new ToolingError("usage: video-score.mjs <composition.html> [--tokens <tokens.json>] [--json] [--no-probe]");
  const root = resolve(flags.root || WORKSPACE);
  const file = requireFile(confined(root, positionals[0], "composition"), "composition");
  const rel = relative(root, file);
  // Comments are stripped for the structural reads so documentation text cannot skew them.
  const code = readFileSync(file, "utf8").replace(/<!--[\s\S]*?-->/g, "").replace(/\/\*[\s\S]*?\*\//g, "");

  // ── the hard gates ──────────────────────────────────────────────────────────
  const common = ["--root", root, rel];
  const video = gate("video-gate.mjs", common);
  const brand = flags["no-brand"] ? null : gate("brand-lint.mjs", [...(flags.tokens ? ["--tokens", resolve(root, flags.tokens)] : []), ...common]);
  const brandFindings = brand?.report.findings || [];
  const hardGateOk = video.status === EXIT.PASS && (!brand || brand.status === EXIT.PASS);

  // ── the artifact probe ──────────────────────────────────────────────────────
  // A probe that cannot run is a tooling failure (exit 2), never a quiet partial score.
  const film = flags["no-probe"] ? null : analyseFilm(await probeFilm(file, { root, step: Number(flags.step ?? 0.1) }));

  const score = { ...MAX };
  const fixes = [];
  const take = (axis, cost, msg) => {
    const applied = Math.min(cost, score[axis]);
    score[axis] -= applied;
    fixes.push({ axis, cost: applied, msg });
  };
  const count = (prefix, severity) => brandFindings.filter((f) => f.rule?.startsWith(prefix) && f.severity === severity).length;

  // Color: brand-lint is the source of truth.
  const colorErrors = count("color.", "ERROR") + count("contrast.", "ERROR");
  if (colorErrors) take("Color", 16, `${colorErrors} brand-lint color/contrast error(s) — must be 0.`);
  else if (count("color.", "WARN")) take("Color", Math.min(8, count("color.", "WARN") * 2), `${count("color.", "WARN")} extended-palette color(s) — confirm the use.`);

  // Coherence: styled from the brand tokens, and every font-family resolving through a token.
  if (!/var\(\s*--brand-/.test(code)) take("Coherence", 8, "not token-driven — style from var(--brand-*) so it cannot drift from the pack.");
  const fontDecls = [...code.matchAll(/(?<![\w-])font-family\s*:\s*([^;}\n]+)/g)];
  const hardcoded = fontDecls.filter((m) => !/var\(\s*--brand-font-/.test(m[1]));
  if (!fontDecls.length) take("Coherence", 4, "no font-family declared — type falls back to the browser default in the render.");
  else if (hardcoded.length) take("Coherence", Math.min(7, 3 + hardcoded.length), `${hardcoded.length} font-family declaration(s) name a face directly (e.g. ${hardcoded[0][1].trim().slice(0, 40)}) instead of var(--brand-font-display|text|mono).`);
  const fontErrors = count("font.", "ERROR");
  if (fontErrors) take("Coherence", Math.min(5, fontErrors * 2), `${fontErrors} brand-lint font error(s).`);

  // Copy: brand-lint's copy and casing rules on the words in the frame.
  const copyErrors = count("copy.", "ERROR") + count("case.", "ERROR");
  if (copyErrors) take("Copy", Math.min(12, copyErrors * 3), `${copyErrors} brand-lint copy/casing error(s) in on-screen text.`);

  const seekErrors = video.report.findings.filter((f) => f.severity === "ERROR");
  if (seekErrors.length) take("Motion", 16, `${seekErrors.length} seek-breaking pattern(s) — the render will not be deterministic.`);
  if (film) {
    const crops = film.layout.findings.filter((f) => f.sev === "ERROR" && f.code !== "layout.collision").length;
    if (crops) take("Layout", Math.min(9, crops * 3), `${crops} element(s) are silently cropped.`);
    const smudged = film.layout.collisions.filter((c) => !c.excused).length;
    if (smudged) take("Layout", Math.min(9, smudged * 3), `${smudged} pair(s) of elements paint the same pixels.`);
    if (film.layout.findings.some((f) => f.code === "layout.off-stage")) take("Layout", 2, "content reaches outside the stage.");

    // Bands calibrated so a well-paced film with real holds is not punished for holding.
    const changing = film.frames.changeRatio;
    if (changing < 0.15) take("Motion", 16, `only ${Math.round(changing * 100)}% of rendered frames differ from the one before — the artifact barely moves.`);
    else if (changing < 0.25) take("Motion", 8, `only ${Math.round(changing * 100)}% of rendered frames differ from the one before.`);
    if (film.frames.findings.some((f) => f.code === "motion.static-run")) take("Motion", 3, `${film.frames.longestStaticS}s of pixel-identical frames mid-film — dead air.`);
    if (film.frames.findings.some((f) => f.code === "motion.one-transition")) take("Motion", 2, "every cut lands the same way — vary the transition with the beat.");
    const flat = film.development.findings.filter((f) => f.code === "development.static-scene").length;
    if (flat) take("Motion", Math.min(8, flat * 4), `${flat} shot(s) never develop — every element enters and nothing changes again.`);

    const h = film.hierarchy;
    if (h.findings.some((f) => f.code === "hierarchy.no-text")) take("Hierarchy", 16, "no element renders visible text at any frame.");
    else {
      if (h.distinct < 2) take("Hierarchy", 12, "every rendered string is the same size — establish eyebrow / headline / body.");
      else if (h.ratio < 1.8) take("Hierarchy", 6, `largest rendered type is only ${h.ratio}x the median — no element is clearly focal.`);
      else if (h.distinct < 3) take("Hierarchy", 3, `only ${h.distinct} rendered type sizes.`);
      if (h.findings.some((f) => f.code === "hierarchy.no-focus")) take("Hierarchy", 4, "most rendered characters are set at the largest size — nothing reads as focal.");
      // hierarchy.illegible costs nothing: small type may be a faithful product surface, which is the
      // model's judgment, not a fact this gate can settle.
    }
  }

  const total = Object.values(score).reduce((a, b) => a + b, 0);
  fixes.sort((a, b) => b.cost - a.cost);
  const filmErrors = film ? film.findings.filter((f) => f.sev === "ERROR") : [];
  const pass = hardGateOk && filmErrors.length === 0;

  if (flags.json) {
    console.log(JSON.stringify({ file: rel, pass, measured: Boolean(film), hardGates: { video: video.report, brand: brand?.report ?? null }, score, total, fixes, film }));
  } else {
    console.log(`video-score: ${rel}\n`);
    for (const k of Object.keys(MAX)) console.log(`  ${String(score[k]).padStart(2)} / ${MAX[k]}   ${k}`);
    console.log("  ────────");
    console.log(`  ${total} / 100   (diagnostic — nothing gates on this number)`);
    if (!film) console.log("\n  ⚠ artifact not measured (--no-probe): motion, continuity, blank frames and rendered type are unchecked.");
    else {
      const c = film.continuity;
      console.log(
        `\n  artifact: ${film.sceneCount} shot(s) · ${film.cutCount} cut(s)` +
          (c.skipped ? ` · continuity n/a (${c.skipped})` : ` · ${c.bare}/${c.boundaries.length} cuts carry nothing`) +
          ` · frames changing ${Math.round(film.frames.changeRatio * 100)}% · longest still ${film.frames.longestStaticS}s`,
      );
      if (film.findings.length) {
        console.log("\n  artifact findings:");
        for (const f of film.findings) console.log(`   ${f.sev === "ERROR" ? "✗" : "⚠"} [${f.code}]${f.at != null ? ` @${f.at}s` : ""} ${f.msg}`);
      }
    }
    for (const f of [...video.report.findings, ...brandFindings].filter((x) => x.severity === "ERROR")) console.log(`   ✗ ${f.message}`);
    if (fixes.length) {
      console.log("\n  fix-list (heaviest first):");
      for (const f of fixes) console.log(`   +${f.cost} [${f.axis}] ${f.msg}`);
    }
    console.log(`\n  ${pass ? "✅ pass" : "❌ FAIL"} — hard gates ${hardGateOk ? "pass" : "FAIL"} · artifact errors ${filmErrors.length}${film ? "" : " (not measured)"} · diagnostic score ${total}/100`);
  }
  return pass ? EXIT.PASS : EXIT.FINDINGS;
});
