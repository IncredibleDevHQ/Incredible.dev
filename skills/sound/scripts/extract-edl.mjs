#!/usr/bin/env node
// extract-edl.mjs — the native "sound-as-you-build" extractor. Reads a HyperFrames composition's
// sound-cue annotations (data-sfx-intent / data-sfx-start / data-sfx-dur, placed on elements while
// the agent builds the scene) and emits a sound-edl cue list. Because the agent owns the timeline,
// placement is exact and free — no reverse-engineering from a rendered video.
//
// Usage:  node extract-edl.mjs <composition.html> [out.json]
// Security: static ATTRIBUTE parse of a local HTML file (path-guarded to repo root). Never
// executes the HTML, no eval, no network.

import { readFileSync, writeFileSync, existsSync, statSync } from "node:fs";
import { resolve, relative, join, dirname } from "node:path";
import { repoRoot } from "./repo-root.mjs";

const ROOT = repoRoot(import.meta.url);
const arg = process.argv.slice(2).find((a) => !a.startsWith("--"));
if (!arg) { console.error("usage: node extract-edl.mjs <composition.html> [out.json]"); process.exit(2); }
const file = resolve(ROOT, arg);
if (file !== ROOT && !file.startsWith(ROOT + "/")) { console.error("extract-edl: path escapes repo root"); process.exit(2); }
if (!existsSync(file) || !statSync(file).isFile()) { console.error(`extract-edl: not a file: ${arg}`); process.exit(2); }

const html = readFileSync(file, "utf8");
const attr = (tag, name) => { const m = tag.match(new RegExp(`${name}\\s*=\\s*"([^"]*)"`, "i")); return m ? m[1] : null; };

const cues = [];
for (const m of html.matchAll(/<[a-zA-Z][^>]*\bdata-sfx-intent\s*=\s*"[^"]*"[^>]*>/g)) {
  const tag = m[0];
  const intent = attr(tag, "data-sfx-intent");
  const t = parseFloat(attr(tag, "data-sfx-start"));
  const dur = parseFloat(attr(tag, "data-sfx-dur"));
  if (!intent || Number.isNaN(t)) continue;
  cues.push({ id: attr(tag, "id") || intent, intent, t_start_s: t, dur_s: Number.isNaN(dur) ? 0.5 : dur });
}
cues.sort((a, b) => a.t_start_s - b.t_start_s);

const edl = {
  composition: (html.match(/data-composition-id\s*=\s*"([^"]*)"/) || [])[1] || null,
  source: relative(ROOT, file),
  extractor: "attribute (sound-as-you-build)",
  cues,
};
const out = process.argv.slice(2).filter((a) => !a.startsWith("--"))[1];
const outPath = out ? resolve(ROOT, out) : join(dirname(file), "sound-edl.json");
if (outPath !== ROOT && !outPath.startsWith(ROOT + "/")) { console.error("extract-edl: out path escapes repo root"); process.exit(2); }
writeFileSync(outPath, JSON.stringify(edl, null, 2) + "\n");
console.log(`extract-edl: ${cues.length} cues -> ${relative(ROOT, outPath)}`);
for (const c of cues) console.log(`  ${c.t_start_s.toFixed(2)}s  ${c.intent.padEnd(22)} (${c.dur_s}s)  #${c.id}`);
