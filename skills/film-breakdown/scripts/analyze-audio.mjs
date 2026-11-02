#!/usr/bin/env node
// A soundtrack measured into the timing constants a composition is built on. Works on a reference
// film's audio or on an operator-supplied music track (any file ffmpeg reads).
//
//   node analyze-audio.mjs <audio|video> [--out analysis.json] [--js timeline.snippet.js] [--no-vo]
//                          [--python exe] [--whisper-model small.en] [--bpm hint] [--min-bpm 60] [--max-bpm 200]
//
// Prints (and writes to --out) JSON whose top level pastes into timeline.js: BPM, BEAT, GRID0 (the first
// beat), DOWNBEAT (beats k with k % 4 === DOWNBEAT start a bar), DUR, HITS [[t, strength]], VO [[t, word]]
// when faster-whisper is importable. Underneath: the tempo candidates, grid drift (edits in the music),
// the downbeat profile, every onset with strength and grid position, and EBU R128 loudness per second.
// --js writes the same as an ES module.
import fs from 'node:fs'; import path from 'node:path'; import os from 'node:os';
import { probe, arg, flag, positional, r2, now } from './lib/media.mjs';
import { analyzeTrack, timelineBlock, timelineJs } from './lib/audio.mjs';

const fail = (e) => { console.error(`analyze-audio: ${(e && e.message) || e}`); process.exit(1); };
process.on('uncaughtException', fail); process.on('unhandledRejection', fail);
const argv = process.argv.slice(2);
const [file] = positional(argv, ['out', 'js', 'python', 'whisper-model', 'bpm', 'min-bpm', 'max-bpm']);
if (!file || flag(argv, 'help')) {
  console.error('usage: node analyze-audio.mjs <audio|video> [--out analysis.json] [--js timeline.snippet.js] [--no-vo] [--python exe] [--whisper-model small.en] [--bpm hint] [--min-bpm 60] [--max-bpm 200]');
  process.exit(2);
}
const t0 = now();
const info = probe(file);
if (!info.audio) { console.error(`analyze-audio: no audio stream in ${file}`); process.exit(1); }
const cache = fs.mkdtempSync(path.join(os.tmpdir(), 'analyze-audio-'));
try {
  const a = await analyzeTrack(path.resolve(file), { cache, vo: !flag(argv, 'no-vo'), python: arg(argv, 'python'), whisperModel: arg(argv, 'whisper-model'),
    bpmHint: arg(argv, 'bpm') ? +arg(argv, 'bpm') : null, minBpm: +arg(argv, 'min-bpm', 60), maxBpm: +arg(argv, 'max-bpm', 200) });
  const T = timelineBlock(a);
  const out = {
    ...T,
    source: { path: info.path, codec: info.audio.codec, sampleRate: info.audio.sampleRate, channels: info.audio.channels, duration: a.duration },
    tempo: a.tempo, drift: a.drift && { shifted: a.drift.shifted, windows: a.drift.windows }, downbeat: a.downbeat,
    loudness: a.loudness, hits: a.hits, onsets: a.onsets, vo: a.vo, envelope: a.envelope,
    notes: a.notes, timings: { ...a.timings, total: r2(now() - t0) },
  };
  const json = JSON.stringify(out, null, 1);
  if (arg(argv, 'out')) fs.writeFileSync(path.resolve(arg(argv, 'out')), json);
  if (arg(argv, 'js')) fs.writeFileSync(path.resolve(arg(argv, 'js')), timelineJs(T));
  console.log(json);
  const g = a.tempo;
  console.error(`analyze-audio: ${g ? `${g.bpm} BPM, grid origin ${g.grid0} s, downbeat k%4=${a.downbeat.beatIndex}${a.downbeat.ambiguous ? ' (ambiguous)' : ''}` : 'no tempo'}; ` +
    `${a.hits.length} hits, ${a.onsets.length} onsets; ${a.loudness.integrated} LUFS; ${a.vo && a.vo.words ? `${a.vo.words.length} VO words` : 'no VO words'}` +
    `${a.drift && a.drift.shifted.length ? `; grid shifts: ${a.drift.shifted.map((s) => `${s.t0}-${s.t1} s ${s.offsetMs} ms`).join(', ')}` : ''} (${r2(now() - t0)} s)`);
} finally { fs.rmSync(cache, { recursive: true, force: true }); }
