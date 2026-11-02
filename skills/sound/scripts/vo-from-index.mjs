#!/usr/bin/env node
// vo-from-index.mjs — the voiceover lines of a finished HyperFrames film, as score-video `vo` entries.
//
// A narrated recipe (faceless-explainer, pr-to-video, general-video, website-to-video) mounts
// each voice line in its index.html as
// <audio src="assets/voice/<id>.wav" data-start="<seconds>">. Scoring that film replaces its audio
// track, so the lines go back in as `vo` entries at the same starts: this copies each voice file
// into <jobDir>/sound-assets/vo/ and writes <jobDir>/vo-from-film.json. Merge that array into
// plan.json as its `vo`.
//
// Usage:  node vo-from-index.mjs <hyperframesDir> <jobDir> [voicePattern]
//   voicePattern: a regular expression over each <audio> src that marks a voice line; default
//   "(^|/)assets/voice/". website-to-video mounts one narration.wav: pass "(^|/)narration\.(wav|mp3)$".
// Security: reads only files under <hyperframesDir>; writes only under <jobDir>. No network.

import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, extname, join, resolve, sep } from "node:path";
import { spawnSync } from "node:child_process";

const [hfArg, jobArg, patternArg] = process.argv.slice(2);
if (!hfArg || !jobArg) {
  console.error("usage: node vo-from-index.mjs <hyperframesDir> <jobDir> [voicePattern]");
  process.exit(2);
}
let voicePattern;
try {
  voicePattern = new RegExp(patternArg || "(^|/)assets/voice/");
} catch {
  console.error(`vo-from-index: invalid voicePattern ${patternArg}`);
  process.exit(2);
}
const hf = resolve(hfArg);
const job = resolve(jobArg);
const indexPath = join(hf, "index.html");
if (!existsSync(indexPath)) {
  console.error(`vo-from-index: no index.html in ${hf}`);
  process.exit(2);
}

const inside = (root, p) => p === root || p.startsWith(root + sep);
const duration = (file) => {
  const r = spawnSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", file], { encoding: "utf8" });
  const d = parseFloat(String(r.stdout || "").trim());
  return Number.isFinite(d) ? d : null;
};
// What a line says, and who spoke it, from the timing file beside it. generate_voiceover writes
// <stem>.words.json with a voice_id, so its lines are ElevenLabs; anything else is supplied.
const lineInfo = (file) => {
  const stem = file.slice(0, -extname(file).length);
  for (const candidate of [`${stem}.words.json`, `${stem}_words.json`]) {
    if (!existsSync(candidate)) continue;
    try {
      const data = JSON.parse(readFileSync(candidate, "utf8"));
      const source = data && !Array.isArray(data) && data.voice_id ? "elevenlabs" : "supplied";
      if (typeof data.text === "string") return { text: data.text, source };
      const words = Array.isArray(data) ? data : data.words || [];
      return { text: words.map((w) => w.word ?? w.text ?? "").join(" ").replace(/\s+/g, " ").trim(), source };
    } catch {}
  }
  return { text: "", source: "supplied" };
};

const html = readFileSync(indexPath, "utf8");
const vo = [];
const skipped = [];
for (const tag of html.match(/<audio\b[^>]*>/gi) || []) {
  const src = (tag.match(/\bsrc\s*=\s*"([^"]+)"/i) || [])[1];
  const start = (tag.match(/\bdata-start\s*=\s*"([^"]+)"/i) || [])[1];
  if (!src || !voicePattern.test(src)) continue;
  const at = Number(start);
  const file = resolve(hf, src);
  if (!inside(hf, file) || !existsSync(file)) { skipped.push(`${src}: file not found`); continue; }
  if (!Number.isFinite(at)) { skipped.push(`${src}: data-start "${start}" is not a number of seconds`); continue; }
  const name = basename(file).replace(/[^A-Za-z0-9_-]/g, "-").replace(/-+(mp3|wav)$/i, "");
  const ext = extname(file).toLowerCase() === ".mp3" ? ".mp3" : ".wav";
  const dest = join(job, "sound-assets", "vo", `${name.slice(0, 120)}${ext}`);
  if (!inside(job, dest)) { skipped.push(`${src}: unsafe name`); continue; }
  mkdirSync(join(job, "sound-assets", "vo"), { recursive: true });
  copyFileSync(file, dest);
  const dur = duration(dest);
  const { text, source } = lineInfo(file);
  vo.push({ start_s: +at.toFixed(3), dur_s: dur == null ? null : +dur.toFixed(3), file: `vo/${basename(dest)}`, text, source });
}
vo.sort((a, b) => a.start_s - b.start_s);
writeFileSync(join(job, "vo-from-film.json"), JSON.stringify(vo, null, 2) + "\n");
console.log(`vo-from-index: ${vo.length} voice line(s) → ${join(job, "vo-from-film.json")}`);
for (const s of skipped) console.log(`  skipped ${s}`);
