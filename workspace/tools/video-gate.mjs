#!/usr/bin/env node
// video-gate.mjs — the cheap pre-render gate for a HyperFrames composition: a line-scoped scan for the
// patterns that break a seek-driven render while nothing in the render complains. No render, no
// network, no brand: brand-lint is its own gate.
//
// The renderer seeks a paused timeline frame by frame, so the same source must produce the same frame
// at the same time, every render, in any order. Anything that reads the wall clock, randomness or the
// network, or animates outside the timeline, breaks that. The rules are grouped by mechanism:
//   - non-determinism: Math.random, Date.now, new Date(), Date(), performance.now, crypto randomness,
//     timers, requestAnimationFrame;
//   - playback the renderer does not own: an unpaused timeline, a standalone gsap tween, CSS
//     transitions and animations;
//   - the renderer seeks: callbacks re-fire on every seek, a zero-position tl.set does not render at
//     frame 0, offset-path never repaints on capture, left/top tweens judder;
//   - render-time reads: remote assets and network calls (the sandbox renders offline);
//   - frame-index arithmetic in build and probe scripts: toFixed() on a time, ffprobe pts CSV.
//
// Usage:  node /workspace/tools/video-gate.mjs <composition.html | build.mjs> [--root <dir>] [--json]
// Point it at build and probe scripts too: a corrupted frame index makes every pixel assertion
// downstream meaningless.
// Exit: 0 pass (warnings allowed) · 1 any ERROR · 2 the gate could not run.

import { readFileSync } from "node:fs";
import { relative, resolve } from "node:path";
import { EXIT, ToolingError, WORKSPACE, confined, isMain, parseFlags, requireFile, runCli } from "./toolchain.mjs";

// Each rule: a hard determinism breaker (ERROR) or a likely-bad heuristic (WARN).
//   re      line-scoped pattern (bounded, no nested quantifiers)
//   span    widen the match window to N lines (a callback body straddles lines)
//   and     a same-window qualifier that must also match
//   once + absent   fire at most once, when the anchor exists but `absent` appears nowhere
const REMOTE = String.raw`["']?(?:https?:)?\/\/`;
export const RULES = [
  // --- non-determinism: the same source must produce the same frames every render ---
  { id: "random", sev: "ERROR", re: /Math\.random\s*\(/, msg: "Math.random() — non-deterministic; seed or precompute" },
  { id: "random", sev: "ERROR", re: /crypto\s*\.\s*(?:getRandomValues|randomUUID)\s*\(/, msg: "crypto randomness — non-deterministic; precompute the values" },
  { id: "clock", sev: "ERROR", re: /Date\.now\s*\(/, msg: "Date.now() — non-deterministic; use the timeline clock" },
  { id: "clock", sev: "ERROR", re: /new Date\s*\(\s*\)/, msg: "new Date() with no args — reads the wall clock; pass a fixed date" },
  { id: "clock", sev: "ERROR", re: /(?<!new\s{1,8})(?<![\w.$])Date\s*\(\s*\)/, msg: "Date() — returns the wall-clock time as a string; pass a fixed date" },
  { id: "clock", sev: "ERROR", re: /performance\s*\.\s*now\s*\(/, msg: "performance.now() — reads the wall clock; derive time from the timeline position" },
  { id: "timer", sev: "ERROR", re: /\bset(?:Timeout|Interval)\s*\(/, msg: "setTimeout/setInterval — non-deterministic timing; drive motion from the GSAP timeline" },
  { id: "raf", sev: "ERROR", re: /requestAnimationFrame\s*\(/, msg: "requestAnimationFrame — self-running loop; render seeks frames, it won't be captured deterministically" },

  // --- playback the renderer does not own ---
  { id: "standalone-tween", sev: "ERROR", re: /\bgsap\s*\.\s*(?:to|from|fromTo)\s*\(/, msg: "standalone gsap.to/from/fromTo — plays on the wall clock, outside the timeline the renderer seeks; add it to the paused, registered timeline" },
  { id: "css-motion", sev: "WARN", re: /(?<![\w-])transition\s*:(?!\s*none\b)\s*[^;}{\s]/, msg: "CSS transition — runs on the wall clock, so a seeked frame lands at an arbitrary point of it; tween the property on the timeline instead" },
  { id: "css-motion", sev: "WARN", re: /@keyframes\b|(?<![\w-])animation(?:-name)?\s*:(?!\s*none\b)\s*[^;}{\s]/, msg: "CSS animation — runs on the wall clock, not the seeked timeline; animate it with the timeline instead" },

  // --- the renderer SEEKS, and callbacks re-fire on every seek ---
  // The capture path seeks with suppressEvents:false, so a callback runs on every seek, including
  // rewinds, in whatever order a cold render worker seeks. A callback is fine when its effect is a
  // pure function of its time, so these warn rather than fail.
  { id: "callback", sev: "WARN", re: /\btl\s*\.\s*call\s*\(/, msg: "tl.call() — fires on every seek, including rewinds and out of order in a cold render worker. Its effect must be a pure function of the time it sits at: set absolute state, never toggle, increment or measure the DOM. For continuous change prefer a tween or an attr: set." },
  { id: "callback", sev: "WARN", span: 6, re: /onUpdate[\s\S]{0,200}?\b(?:textContent|innerHTML|setAttribute|classList|\.style\.)\s*[.=[]/, msg: "onUpdate writing the DOM — runs on every seek, so derive what it writes from this tween's own value (a counter writes Math.round(obj.v)); never accumulate across calls or read layout inside it." },
  // A zero-duration set at position 0 does not render while the playhead sits at 0.
  { id: "initial-set", sev: "ERROR", re: /\btl\s*\.\s*set\s*\([^;]*,\s*0\s*\)\s*;/, msg: "tl.set(..., 0) — a zero-duration set at position 0 does NOT render while the playhead sits at 0, so frame 0 ships un-hidden (hyperframes lint: gsap_timeline_set_initial_hide). Use a plain gsap.set() in setup." },
  // The property computes in the DOM but is never repainted on the screenshot-capture path.
  { id: "offset-path", sev: "ERROR", re: /\boffset-(?:distance|path)\b|\boffsetDistance\b|<animateMotion\b/, msg: "offset-path / offset-distance / <animateMotion> — computes but never repaints on the screenshot-capture path; sample cx/cy (or x/y) yourself" },
  { id: "left-top-tween", sev: "WARN", re: /\btl\s*\.\s*(?:to|from|fromTo)\s*\([^;]*\{[^;{}]*\b(?:left|top)\s*:/, msg: "tweening left/top — snaps to integer device pixels under seek-by-frame capture and judders; tween x/y instead (hyperframes lint: gsap_non_transform_motion)" },
  { id: "inset", sev: "WARN", re: /(?<![\w-])inset\s*:\s*0(?:px)?\b/, msg: "inset:0 — prefer explicit top/left/width/height so layout inspection and overflow checks see concrete box geometry" },

  // --- render-time reads: the sandbox renders offline ---
  { id: "remote-asset", sev: "ERROR", re: new RegExp(String.raw`\bsrc\s*=\s*${REMOTE}|<link\b[^>]*\bhref\s*=\s*${REMOTE}|url\(\s*${REMOTE}|@import\s+(?:url\(\s*)?${REMOTE}`, "i"), msg: "remote asset loaded at render time — the render has no network, so it will be missing; fetch it into the project first (fetch-asset.mjs) and reference the local file" },
  { id: "network", sev: "WARN", re: /(?<![\w.$])fetch\s*\(|\bXMLHttpRequest\b|\bnew\s+WebSocket\s*\(|\bnew\s+EventSource\s*\(/, msg: "network call in the composition — the render has no network and cannot wait for one; inline the data or load a local file" },

  // --- frame-index arithmetic: a time that rounds past its own frame ---
  // (317/30).toFixed(4) = 10.5667 > 10.56666..., so a state change placed there lands one frame late,
  // and tips differently between two renders of identical source.
  { id: "time-rounding", sev: "ERROR", re: /toFixed\s*\(\s*[1-4]\s*\)/, and: /\bfps\b|\bFPS\b|\bframe|\btl\s*\.|\bseek\b|\bduration\b|\btime\b|\/\s*30\b|\/\s*60\b/i, msg: "toFixed(<=4) on a TIME — a rounded timeline position can land PAST its own frame, so the state change renders one frame late, and it tips differently between two renders of identical source. Snap first: (Math.round(t*FPS)/FPS - 0.0005).toFixed(5)" },
  // ffprobe's CSV output adds a field and a blank line for any frame carrying side_data.
  { id: "ffprobe-csv", sev: "ERROR", re: /frame=pts_time(?![^\n]*split\s*\(\s*["'],["']\s*\)\s*\[\s*0\s*\])/, msg: "ffprobe frame=pts_time CSV — side_data adds an extra field and an extra blank line, so line number stops equalling frame number and every frame lookup after it is garbage. Take split(',')[0], filter(Boolean), then assert length == frame count and strict monotonicity." },
  { id: "ffmpeg-seek", sev: "WARN", re: /ffmpeg[^\n]*-ss\s+[^\n]*-frames:v\s+1/, msg: "-ss to grab one frame — keyframe-inaccurate. Select the frame by index instead (select=not(n-N), which needs no comma escaping)." },

  // --- sub-pixel quantisation ---
  // Chromium rounds every glyph advance to a whole CSS pixel unless told otherwise, and the video
  // renderer launches its own browser, so the export flags in text-fidelity.mjs do not reach it.
  { id: "text-rendering", sev: "WARN", re: /<body\b|:root\s*\{|^\s*html\s*,?\s*body\s*\{/, once: true, absent: /text-rendering\s*:\s*geometricPrecision/, msg: "no `text-rendering: geometricPrecision` anywhere — Chromium rounds every glyph advance to a whole CSS pixel and redistributes the error unevenly between glyphs. Set it on :root/body (and on the root <svg> for an SVG deliverable)." },

  { id: "text-content", sev: "WARN", re: /\.textContent\s*=/, msg: "textContent assignment — fine at setup, but never inside a timeline callback (animate opacity/position instead)" },
];

// A timeline the renderer does not own plays on the wall clock. The options object can span lines,
// so read the whole call rather than one line of it.
function unpausedTimelines(source) {
  const out = [];
  for (const m of source.matchAll(/\bgsap\s*\.\s*timeline\s*\(/g)) {
    let depth = 1;
    let end = m.index + m[0].length;
    const limit = Math.min(source.length, end + 2000);
    while (end < limit && depth > 0) {
      if (source[end] === "(") depth++;
      else if (source[end] === ")") depth--;
      end++;
    }
    const args = source.slice(m.index + m[0].length, end - 1);
    if (!/\bpaused\s*:\s*true\b/.test(args)) out.push(source.slice(0, m.index).split("\n").length);
  }
  return out;
}

export function scan(source) {
  const lines = source.split("\n");
  const findings = [];
  const seen = new Set();
  const add = (rule, line) => {
    const key = `${rule.msg}:${line}`;
    if (seen.has(key)) return;
    seen.add(key);
    findings.push({ severity: rule.sev, line, rule: rule.id, message: rule.msg });
  };
  for (const rule of RULES) {
    if (rule.once) {
      const anchored = lines.findIndex((l) => rule.re.test(l));
      if (anchored >= 0 && !rule.absent.test(source)) add(rule, anchored + 1);
      continue;
    }
    lines.forEach((line, i) => {
      const hay = rule.span ? lines.slice(i, i + rule.span).join("\n") : line;
      if (!rule.re.test(hay)) return;
      // `and` keeps `toFixed(1)` on an SVG coordinate out of a rule about timeline TIMES.
      if (rule.and && !rule.and.test(hay)) return;
      add(rule, i + 1);
    });
  }
  const unpaused = {
    id: "unpaused-timeline",
    sev: "ERROR",
    msg: "gsap.timeline() without { paused: true } — it plays on the wall clock while the renderer seeks; create it paused and register it on window.__timelines",
  };
  for (const line of unpausedTimelines(source)) add(unpaused, line);
  return findings.sort((a, b) => a.line - b.line);
}

if (isMain(import.meta.url)) await runCli("video-gate", async () => {
  const { flags, positionals } = parseFlags(process.argv.slice(2), { values: ["root"], booleans: ["json"] });
  if (positionals.length !== 1) throw new ToolingError("usage: video-gate.mjs <composition.html | script.mjs> [--root <dir>] [--json]");
  const root = resolve(flags.root || WORKSPACE);
  const file = requireFile(confined(root, positionals[0], "target"), "target");
  const rel = relative(root, file);
  let source;
  try {
    source = readFileSync(file, "utf8");
  } catch (error) {
    throw new ToolingError(`cannot read ${rel} (${error.code || error.message})`);
  }
  const findings = scan(source);
  const errors = findings.filter((f) => f.severity === "ERROR").length;
  const warnings = findings.length - errors;
  if (flags.json) {
    console.log(JSON.stringify({ ok: errors === 0, file: rel, errors, warnings, findings }));
  } else {
    console.log(`video-gate: ${rel}`);
    if (!findings.length) console.log("  ✅ no seek-breaking patterns found");
    for (const f of findings) console.log(`  ${f.severity === "ERROR" ? "❌" : "⚠️ "} ${rel}:${f.line} — ${f.message}`);
    console.log(`\nvideo-gate: ${errors} error(s), ${warnings} warning(s)`);
    console.log(
      errors
        ? "✋ gate FAILED — fix the above before rendering."
        : "✅ gate passed — render, then look at full-resolution frames (film-probe / video-score).",
    );
  }
  return errors ? EXIT.FINDINGS : EXIT.PASS;
});
