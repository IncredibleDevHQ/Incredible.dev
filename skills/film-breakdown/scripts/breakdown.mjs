#!/usr/bin/env node
// Break a reference film down into measurements: hard cuts (with confidence) vs continuous moves,
// labelled contact sheets, full-resolution stills around every cut, per-second motion energy and
// a still-frame audit, the soundtrack (tempo, a beat grid fitted to the onsets, drift, downbeats, hits,
// loudness, voice-over words), dominant colours per shot, and a SHOTLIST.draft.md to finish by eye.
//
//   node breakdown.mjs <video> <outdir> [options]
//
// Options: --no-audio, --no-vo, --python <exe> (the interpreter for the optional faster-whisper
// voice-over pass), --whisper-model small.en, --bpm <hint>, --cut-threshold 0.25,
// --min-shot 0.2, --scene-floor 0.12, --split 1 (split hard-cut segments at fast continuous moves into
// sub-shots at least this long; 0 = off), --png (full-res stills as PNG), --keep-cache.
import fs from 'node:fs'; import path from 'node:path';
import { probe, extractFrames, makeSheets, makeSheet, sheetLayout, labelFont, timeOf, fmtT, r2, r3, now, arg, flag, positional, pool, cpus, fitDims, ffmpegCaps } from './lib/media.mjs';
import { scan } from './lib/scan.mjs';
import { detectCuts, detectMoves, motionReport } from './lib/cuts.mjs';
import { analyzeTrack, timelineBlock } from './lib/audio.mjs';
import { palette } from './lib/palette.mjs';

const fail = (e) => { console.error(`breakdown: ${(e && e.message) || e}`); process.exit(1); };
process.on('uncaughtException', fail); process.on('unhandledRejection', fail);
const argv = process.argv.slice(2);
const VALUED = ['python', 'whisper-model', 'bpm', 'cut-threshold', 'min-shot', 'scene-floor', 'split'];
const [video, outArg] = positional(argv, VALUED);
if (!video || !outArg || flag(argv, 'help')) {
  console.error('usage: node breakdown.mjs <video> <outdir> [--no-audio] [--no-vo] [--python exe] [--whisper-model small.en] [--bpm hint]\n' +
    '       [--cut-threshold 0.25] [--min-shot 0.2] [--scene-floor 0.12] [--split 1] [--png] [--keep-cache]');
  process.exit(2);
}
const OUT = path.resolve(outArg), CACHE = path.join(OUT, '.cache');
const T = { start: now() }; const tick = (k, t0) => { T[k] = r2(now() - t0); };
fs.mkdirSync(CACHE, { recursive: true });
ffmpegCaps();
const info = probe(video), v = info.video;
if (!v) { console.error(`breakdown: no video stream in ${video}`); process.exit(1); }
if (v.vfr) console.error(`breakdown: variable frame rate (r ${v.rFrameRate}, avg ${v.avgFrameRate}); frame maths use the average`);
const notes = [];
const font = labelFont(CACHE);
if (!font) notes.push('no label font file found; labels use fontconfig "monospace"');

// ---------------------------------------------------------------- 1. one video pass and the audio, in parallel
let t0 = now();
// Section sheets hold 20 tiles: 4 fps (5 s a sheet) up to 3 min, 2 fps up to 10 min, then 1 fps.
const tps = (v.duration || 0) <= 180 ? 4 : (v.duration || 0) <= 600 ? 2 : 1;
if (tps < 4) notes.push(`long film: section sheets at ${tps} fps (${20 / tps} s a sheet) instead of 4 fps`);
const scanP = scan(path.resolve(video), v, { cache: path.join(CACHE, 'scan'), tilePerSec: tps }).then((r) => { tick('scan', t0); return r; });
const wantAudio = info.audio && !flag(argv, 'no-audio');
if (!info.audio) notes.push('no audio stream: tempo, grid, hits and voice-over skipped');
const audioP = wantAudio ? analyzeTrack(path.resolve(video), { cache: path.join(CACHE, 'audio'), vo: !flag(argv, 'no-vo'), python: arg(argv, 'python'),
  whisperModel: arg(argv, 'whisper-model'), bpmHint: arg(argv, 'bpm') ? +arg(argv, 'bpm') : null }).then((r) => { tick('audio', t0); return r; }) : null;
const S = await scanP;
const nFrames = S.n, fps = v.fpsValue, dur = r3(timeOf(nFrames, v));
const F = { scene: S.scene, d: S.d, d2: S.d2, hd: S.hd, mc: S.mc, rho: S.rho, y: S.y };

// ---------------------------------------------------------------- 2. cuts, moves, motion
const cutOpts = { threshold: +arg(argv, 'cut-threshold', 0.25), minShot: +arg(argv, 'min-shot', 0.2), sceneLo: +arg(argv, 'scene-floor', 0.12) };
const { cuts, transitions, params } = detectCuts(F, v, cutOpts);
const { moves, threshold: moveThr } = detectMoves(S.motion, F, v, cuts);
const motion = motionReport(S.motion, v, { hasAudio: !!info.audio, duration: dur });
const A = audioP ? await audioP : null;
if (A) notes.push(...A.notes);

// ---------------------------------------------------------------- 3. shots: hard-cut segments, split at fast continuous moves
// A one-shot film changes idea on its camera moves (whips, swirls, pushes): splitting segments at the
// peaks of fast moves (motion energy >= max(4, its 85th percentile)) suggests boundaries close to the
// ones a person picks by eye. They are suggestions: confirm each on the sheets.
const minSub = +arg(argv, 'split', 1);
const sortedM = [...S.motion].sort((a, b) => a - b);
const splitThr = Math.max(4, sortedM[Math.floor(0.85 * (sortedM.length - 1))] || 0);
const splitMoves = minSub > 0 ? detectMoves(S.motion, F, v, cuts, { thr: splitThr }).moves : [];
const bounds = [0, ...cuts.map((c) => c.n), nFrames];
const shots = [];
for (let k = 0; k + 1 < bounds.length; k++) {
  const a = bounds[k], b = bounds[k + 1], edge = Math.round(minSub * fps), picked = [];
  for (const m of splitMoves.filter((m) => m.peakN - a >= edge && b - m.peakN >= edge).sort((x, y) => y.peak - x.peak)) {
    if (picked.every((p) => Math.abs(p.n - m.peakN) >= edge)) picked.push({ n: m.peakN, move: m });
  }
  picked.sort((x, y) => x.n - y.n);
  const edges = [a, ...picked.map((p) => p.n), b];
  for (let i = 0; i + 1 < edges.length; i++) {
    shots.push({ n0: edges[i], n1: edges[i + 1], segment: k + 1, in: i === 0 ? (k === 0 ? 'start' : 'cut') : 'continuous',
      out: i + 2 < edges.length ? 'continuous' : (k + 2 < bounds.length ? 'cut' : 'end'), via: i > 0 ? `${picked[i - 1].move.kind} ${fmtT(picked[i - 1].move.t0)}-${fmtT(picked[i - 1].move.t1)}` : null });
  }
}
shots.forEach((s, i) => { s.id = i + 1; s.t0 = r3(timeOf(s.n0, v)); s.t1 = r3(timeOf(s.n1, v)); s.dur = r2(s.t1 - s.t0); });
const shotOf = (n) => shots.find((s) => n >= s.n0 && n < s.n1) || shots[shots.length - 1];

// ---------------------------------------------------------------- 4. per-shot measurements
const G = A && A.tempo;
const words = A && A.vo && A.vo.words ? A.vo.words : [];
for (const s of shots) {
  let sum = 0, pk = 0, pj = s.n0, cnt = 0;
  for (let j = s.n0; j <= s.n1 - 2 && j < S.motion.length; j++) { sum += S.motion[j]; cnt++; if (S.motion[j] > pk) { pk = S.motion[j]; pj = j; } }
  s.motion = { mean: r2(cnt ? sum / cnt : 0), peak: r2(pk), peakT: r2(timeOf(pj + 1, v)) };
  s.moves = moves.filter((m) => m.peakT >= s.t0 && m.peakT < s.t1).map((m) => `${m.kind} ${fmtT(m.t0)}-${fmtT(m.t1)}`);
  const kept = S.kept.filter((k) => k.n >= s.n0 && k.n < s.n1);
  const pickK = kept.length > 16 ? Array.from({ length: 16 }, (_, i) => kept[Math.floor((i * kept.length) / 16)]) : kept;
  s.palette = palette(pickK.map((k) => k.px));
  if (A) {
    s.hits = A.hits.filter((h) => h.t >= s.t0 && h.t < s.t1).map((h) => [h.t, h.s]);
    const on = A.onsets.filter((o) => o.t >= s.t0 && o.t < s.t1); s.onsets = on.length;
    s.onsetRate = r2(on.length / Math.max(0.01, s.dur));
    s.vo = words.filter((w) => w.s >= s.t0 && w.s < s.t1).map((w) => [w.s, w.w]);
  }
}
// Cuts against the grid and the sound.
for (const c of cuts) {
  const sh = shotOf(c.n); c.shot = sh.id;
  if (G) {
    const b = (c.t - G.grid0) / G.beat, k = Math.round(b), e = Math.round(b * 2) / 2, tol = Math.max(0.034, 1.01 / fps);
    const dB = (b - k) * G.beat, d8 = (b - e) * G.beat;
    c.grid = { beat: r2(b), nearest: Math.abs(dB) <= Math.abs(d8) ? k : e, offsetMs: Math.round((Math.abs(dB) <= Math.abs(d8) ? dB : d8) * 1000),
      on: Math.abs(dB) <= tol ? 'beat' : Math.abs(d8) <= tol ? '8th' : null };
  }
  if (A) {
    const h = A.hits.reduce((best, x) => (Math.abs(x.t - c.t) < Math.abs((best?.t ?? 1e9) - c.t) ? x : best), null);
    c.hit = h && Math.abs(h.t - c.t) <= 0.1 ? { t: h.t, s: h.s, offsetMs: Math.round((h.t - c.t) * 1000) } : null;
    const w = words.find((x) => Math.abs(x.s - c.t) <= 0.25); c.vo = w ? { word: w.w, t: w.s } : null;
  }
}

// ---------------------------------------------------------------- 5. stills (full resolution) and dense cut frames
t0 = now();
const stillDir = path.join(OUT, 'stills'); fs.rmSync(stillDir, { recursive: true, force: true });
const fmt = flag(argv, 'png') ? 'png' : 'jpg';
const cutFrames = cuts.flatMap((c) => [c.n - 1, c.n, c.n + 3, c.n + 10]);
const shotFrames = shots.flatMap((s) => [s.n0, Math.floor((s.n0 + s.n1 - 1) / 2)]);
const stills = await extractFrames(path.resolve(video), v, [...cutFrames, ...shotFrames, nFrames - 1].filter((n) => n >= 0 && n < nFrames), { dir: stillDir, fmt, q: 2 });
const stillByN = new Map(stills.map((s) => [s.n, path.relative(OUT, s.file)]));
for (const c of cuts) c.stills = { lastBefore: stillByN.get(c.n - 1), first: stillByN.get(c.n), plus3: stillByN.get(c.n + 3), plus10: stillByN.get(c.n + 10) };
for (const s of shots) s.stills = { first: stillByN.get(s.n0), mid: stillByN.get(Math.floor((s.n0 + s.n1 - 1) / 2)) };
const step = Math.max(1, Math.round(fps / 10));
const denseFor = (c) => [...Array.from({ length: 12 }, (_, k) => c.n - 1 - step * (11 - k)), ...Array.from({ length: 12 }, (_, k) => c.n + step * k)].filter((n) => n >= 0 && n < nFrames);
const denseDir = path.join(CACHE, 'dense');
const dense = await extractFrames(path.resolve(video), v, cuts.slice(0, 80).flatMap(denseFor), { dir: denseDir, fmt: 'jpg', q: 3, long: 320 });
const denseByN = new Map(dense.map((d) => [d.n, d.file]));
tick('stills', t0);

// ---------------------------------------------------------------- 6. contact sheets (<= 1500 px, every tile labelled)
t0 = now();
const sheetDir = path.join(OUT, 'sheets'); fs.rmSync(sheetDir, { recursive: true, force: true }); fs.mkdirSync(sheetDir, { recursive: true });
const [dw, dh] = fitDims(v, 1000), aspect = dw / dh;
const cutSet = new Set(cuts.map((c) => c.n));
const label = (n, extra = '') => `${fmtT(timeOf(n, v))} f${n}${extra}`;
const firstAfterCut = (tiles) => tiles.map((t, i) => (i > 0 && cuts.some((c) => c.n > tiles[i - 1].n && c.n <= t.n) ? 'cut' : undefined));
// 1 fps overview
const perSecTiles = S.tiles.filter((t) => Math.round(timeOf(t.n, v) * tps) % tps === 0);
const ovMarks = firstAfterCut(perSecTiles);
const overview = await makeSheets(perSecTiles.map((t, i) => ({ file: t.file, label: label(t.n, ` #${shotOf(t.n).id}`), mark: ovMarks[i] })),
  (k, K) => path.join(sheetDir, K > 1 ? `overview-1fps-${k}.jpg` : 'overview-1fps.jpg'), aspect, { font, cols: aspect >= 1 ? 8 : 12 });
// Sections: 20 tiles each (5 s windows at 4 fps)
const sections = [];
const winS = 20 / tps;
for (let w0 = 0; w0 < dur - 1e-6; w0 += winS) {
  const tiles = S.tiles.filter((t) => t.t >= w0 - 1e-6 && t.t < w0 + winS - 1e-6);
  if (tiles.length) sections.push({ w0, w1: Math.min(dur, w0 + winS), tiles });
}
const L4 = sheetLayout(20, aspect, { cols: aspect >= 1 ? 5 : 10 });
const sectionSheets = await pool(sections, Math.max(2, Math.min(8, cpus())), async (sec, i) => {
  const marks = firstAfterCut(sec.tiles);
  const out = path.join(sheetDir, `section-${String(i + 1).padStart(sections.length > 99 ? 3 : 2, '0')}_${fmtT(sec.w0, 1)}-${fmtT(sec.w1, 1)}s.jpg`);
  await makeSheet(sec.tiles.map((t, j) => ({ file: t.file, label: label(t.n, ` #${shotOf(t.n).id}`), mark: marks[j] })), out, { ...L4, font });
  return { t0: r2(sec.w0), t1: r2(sec.w1), file: path.relative(OUT, out) };
});
// 10 fps around every cut: 12 frames before (ending on the last frame), 12 from the first frame on
const LC = sheetLayout(24, aspect, { cols: aspect >= 1 ? 6 : 12 });
const MAX_CUT_SHEETS = 80;
if (cuts.length > MAX_CUT_SHEETS) notes.push(`${cuts.length} cuts: dense sheets for the first ${MAX_CUT_SHEETS} only (grab.mjs for the rest)`);
const cutSheets = await pool(cuts.slice(0, MAX_CUT_SHEETS), Math.max(2, Math.min(8, cpus())), async (c, i) => {
  const ns = denseFor(c).filter((n) => denseByN.has(n));
  const out = path.join(sheetDir, `cut-${String(i + 1).padStart(2, '0')}_${fmtT(c.t)}s.jpg`);
  const marks = firstAfterCut(ns.map((n) => ({ n })));
  await makeSheet(ns.map((n, j) => ({ file: denseByN.get(n), label: label(n, cutSet.has(n) ? ' CUT' : ''), mark: cutSet.has(n) || marks[j] ? 'cut' : cutSet.has(n + 1) ? 'pre' : undefined })), out, { ...LC, font });
  c.sheet = path.relative(OUT, out);
  return c.sheet;
});
tick('sheets', t0);

// ---------------------------------------------------------------- 7. write breakdown.json, SHOTLIST.draft.md, timeline.draft.js
const film = { ...palette(pickEven(S.kept, 48).map((k) => k.px)) };
const TL = { FPS: v.fps, DUR: dur, ...(A ? timelineBlock(A, { dur }) : {}), CUT_FRAMES: cuts.map((c) => c.n) };
const result = {
  tool: 'film-breakdown/breakdown.mjs', created: new Date().toISOString(), ffmpeg: ffmpegCaps().version,
  video: { path: info.path, container: info.container, size: info.size, codec: v.codec, width: v.width, height: v.height, pixFmt: v.pixFmt,
    fps: v.fps, fpsValue: +fps.toFixed(6), vfr: v.vfr, frames: nFrames, duration: dur, colorSpace: v.colorSpace, rotation: v.rotation,
    audio: info.audio ? { codec: info.audio.codec, sampleRate: info.audio.sampleRate, channels: info.audio.channels } : null },
  summary: {
    hardCuts: cuts.length, shots: shots.length, suggestedSplits: shots.filter((s) => s.in === 'continuous').length,
    averageShot: r2(dur / Math.max(1, cuts.length + 1)), bpm: G ? G.bpm : null, grid0: G ? G.grid0 : null,
    cutsOnGrid: G ? cuts.filter((c) => c.grid && c.grid.on).length : null, cutsOnHits: A ? cuts.filter((c) => c.hit).length : null,
    loudness: A && A.loudness ? A.loudness.integrated : null, stillPercent: motion.audit.stillPercent, voWords: words.length || null,
  },
  timeline: TL,
  cuts, transitions, moves: { threshold: moveThr, list: moves },
  shots: shots.map(({ n0, n1, ...s }) => ({ ...s, frames: [n0, n1 - 1] })),
  palette: film,
  motion: { chain: 'scale=160:-1,gblur=sigma=1.5,format=gray,tblend=all_mode=difference,signalstats (YAVG per frame pair)',
    perSecond: motion.perSecond, audit: motion.audit, perFrame: S.motion.map((x) => +x.toFixed(3)) },
  audio: A ? { duration: A.duration, envelope: A.envelope, tempo: A.tempo, drift: A.drift, downbeat: A.downbeat, loudness: A.loudness,
    hits: A.hits, onsets: A.onsets, vo: A.vo } : null,
  outputs: { shotlist: 'SHOTLIST.draft.md', timeline: 'timeline.draft.js', sheets: { overview: overview.map((f) => path.relative(OUT, f)), sections: sectionSheets, cuts: cutSheets },
    stills: stills.length, stillsDir: 'stills' },
  cutDetection: params, notes, timings: null,
};
fs.writeFileSync(path.join(OUT, 'timeline.draft.js'), timelineFile(TL, shots));
fs.writeFileSync(path.join(OUT, 'SHOTLIST.draft.md'), shotlist(result, shots));
if (!flag(argv, 'keep-cache')) fs.rmSync(CACHE, { recursive: true, force: true });
T.total = r2(now() - T.start); delete T.start; result.timings = T;
fs.writeFileSync(path.join(OUT, 'breakdown.json'), JSON.stringify(result, null, 1));
console.log(JSON.stringify({ out: OUT, ...result.summary, sheets: overview.length + sectionSheets.length + cutSheets.length, stills: stills.length, timings: T, notes }, null, 1));

function pickEven(a, n) { return a.length <= n ? a : Array.from({ length: n }, (_, i) => a[Math.floor((i * a.length) / n)]); }

function timelineFile(TL, shots) {
  const fpsExpr = String(TL.FPS).includes('/') ? TL.FPS.replace('/', ' / ') : TL.FPS;
  const L = [`// Measured by film-breakdown from ${path.basename(info.path)}. Seconds on the source clock; pure data, no imports.`,
    `export const FPS = ${fpsExpr}; // render at this rate (hyperframes render --fps ${TL.FPS})`, `export const DUR = ${TL.DUR};`,
    `export const frame = (n) => n / FPS;`];
  if (TL.BPM) L.push(`export const BPM = ${TL.BPM};`, `export const BEAT = ${TL.BEAT}; // 60 / BPM`, `export const GRID0 = ${TL.GRID0}; // first beat`,
    `export const beat = (k) => GRID0 + k * BEAT;`, ...(TL.DOWNBEAT != null ? [`export const DOWNBEAT = ${TL.DOWNBEAT}; // bars start on beats k % 4 === DOWNBEAT${A.downbeat.ambiguous ? ' (ambiguous: check by ear)' : ''}`] : []));
  L.push(`// First frame of the new shot at every hard cut; a cut sits half a frame earlier so the shutter never straddles it.`,
    `export const CUT_FRAMES = ${JSON.stringify(TL.CUT_FRAMES)};`, `export const CUTS = CUT_FRAMES.map((n) => (n - 0.5) / FPS);`,
    `// Shots [id, in, out] (hard cuts, plus suggested continuous splits: confirm them on the sheets).`,
    `export const SHOTS = ${JSON.stringify(shots.map((s) => [s.id, s.t0, s.t1]))};`);
  if (TL.HITS) L.push(`export const HITS = ${JSON.stringify(TL.HITS)}; // [seconds, strength 0..1]`);
  if (TL.VO) L.push(`export const VO = ${JSON.stringify(TL.VO)}; // [start, word]`);
  return L.join('\n') + '\n';
}

function shotlist(R, shots) {
  const V = R.video, a = R.audio, g = a && a.tempo;
  const lines = [];
  const pal = (p) => [...p.dominant.slice(0, 4).map((c) => `${c.hex} ${Math.round(c.share * 100)}%`), ...(p.accents.length ? [`accents ${p.accents.map((c) => c.hex).join(' ')}`] : [])].join(', ');
  const link = (p, txt) => (p ? `[${txt}](${p})` : '');
  lines.push(`# Shot list (draft): "${path.basename(V.path)}"`, '',
    `Reference: \`${V.path}\`, ${V.codec} ${V.width}x${V.height}, ${V.fps} fps (${V.fpsValue.toFixed(3)}), ${V.duration} s (${V.frames} frames)` +
    (V.audio ? `, audio ${V.audio.channels} ch ${V.audio.sampleRate} Hz.` : ', no audio.'),
    `Measured by film-breakdown: ${R.cuts.length} hard cuts, ${shots.length} shots (${R.summary.suggestedSplits} of them suggested splits at continuous changes: confirm on the sheets).` +
    ` Sheets \`sheets/\` (1 fps overview, 4 fps per 5 s, 10 fps around every cut), full-resolution stills \`stills/\`, every number in \`breakdown.json\`.`,
    'Replace every ____ by looking at the sheets and stills; measure positions and sizes on the full-resolution stills, not on sheets.', '');
  lines.push('## Sound', '');
  if (!a) lines.push('- No audio analysed.');
  else {
    const d = a.downbeat, drift = a.drift && a.drift.shifted.length ? a.drift.shifted.map((s) => `${s.t0}-${s.t1} s ${s.offsetMs > 0 ? '+' : ''}${s.offsetMs} ms`).join('; ') : 'none (the grid holds over the whole track)';
    if (g) lines.push(`- **Music grid**: **${g.bpm} BPM** (beat ${g.beat} s), grid origin **${g.grid0} s** (beats at ${g.grid0} + k x ${g.beat}); grid strength ${g.strength}x the mean onset. ` +
      `Downbeats: beats k = ${d.beatIndex} mod 4 (confidence ${d.confidence}${d.ambiguous ? ', ambiguous: check by ear' : ''}). Local shifts: ${drift}. ____ (what the music is: genre, instruments, where it builds and drops)`);
    const L = a.loudness || {};
    lines.push(`- **Loudness**: ${L.integrated} LUFS integrated, LRA ${L.lra} LU, true peak ${L.truePeak} dBTP. Momentary loudness per second: ${(L.momentaryPerSecond || []).map((x) => Math.round(x)).join(' ')}.`);
    const top = [...a.hits].sort((x, y) => y.s - x.s).slice(0, 14).sort((x, y) => x.t - y.t);
    lines.push(`- **Strongest hits** (strength, beat on the grid): ${top.map((h) => `${fmtT(h.t)} (${h.s}${h.beat != null ? `, beat ${h.beat}` : ''}${h.on ? `, on ${h.on}` : ''})`).join(', ')}. All ${a.hits.length} hits and ${a.onsets.length} onsets are in breakdown.json. ____ (which are designed hits, which are music)`);
    if (a.vo && a.vo.words) {
      const segs = (a.vo.segments || []).map((s) => {
        const ws = a.vo.words.filter((w) => w.s >= s.start - 0.01 && w.s < s.end + 0.01);
        return ws.length ? `${ws[0].w} ${fmtT(ws[0].s)}${ws.length > 1 ? ` ... ${ws[ws.length - 1].w} ${fmtT(ws[ws.length - 1].s)}` : ''}` : null;
      }).filter(Boolean);
      lines.push(`- **Voice-over** (${a.vo.model}, ${a.vo.words.length} words; the sync spec for copy): ${segs.join(' | ')}. Every word start is in timeline.draft.js (VO).`);
    } else lines.push(`- **Voice-over**: ${a.vo && a.vo.skipped ? a.vo.skipped : 'not transcribed'}. ____ (is there a voice-over? transcribe the copy it speaks)`);

  }
  lines.push('', `## Hard cuts (confidence; grid; sound)`, '');
  lines.push(R.cuts.length ? R.cuts.map((c) => `${fmtT(c.t)} (f${c.n}, ${c.confidence}${c.kind !== 'cut' ? `, ${c.kind}` : ''}${c.grid && c.grid.on ? `, on ${c.grid.on} ${c.grid.nearest}` : ''}${c.hit ? `, hit ${fmtT(c.hit.t)}` : ''}${c.vo ? `, VO "${c.vo.word}"` : ''})`).join(', ') + '.' : 'None: the film is one continuous shot.');
  const whips = R.moves.list.filter((m) => m.kind === 'whip');
  lines.push('', `Everything else is continuous: ${R.moves.list.length} fast moves over motion energy ${R.moves.threshold}${whips.length ? ` (whips at ${whips.map((m) => fmtT(m.peakT)).join(', ')})` : ''}.` +
    (R.transitions.length ? ` Looked like cuts but are not (see breakdown.json transitions): ${R.transitions.filter((t) => t.kind !== 'tail').slice(0, 12).map((t) => `${fmtT(t.t)} ${t.kind}`).join(', ')}.` : ''), '');
  lines.push('## Look (applies throughout)', '',
    `- Colours measured across the film: ${pal(R.palette)}. ____ (grounds, accent family, where the palette changes)`,
    '- Light and texture: ____ (bloom, flares, grain, depth of field, chromatic aberration)',
    '- Type: ____ (face, weight, case, size in px on the stills, how words enter)',
    '- Recurring systems: ____ (motifs, layouts, camera rigs that come back)', '');
  lines.push('## Shots', '',
    '| # | In-out (s) | Copy (verbatim) | Layout / content | Camera / motion | Transition out | Sound it lands on |', '|---|---|---|---|---|---|---|');
  shots.forEach((s, i) => {
    const next = shots[i + 1], cut = R.cuts.find((c) => next && c.n === next.n0);
    const tOut = s.out === 'end' ? 'end' : s.out === 'cut' ? `hard cut ${fmtT(cut.t)} (${cut.confidence}${cut.kind !== 'cut' ? `, ${cut.kind}` : ''}) ${link(cut.sheet, 'sheet')} ____` : `continuous: ${next.via} (suggested split at ${fmtT(next.t0)}) ____`;
    const sound = s.vo === undefined ? '' : [s.vo.length ? `VO ${s.vo.map(([t, w]) => `${w.replace(/[.,!?;:]+$/, '')} ${fmtT(t)}`).join(', ')}` : '', s.hits.length ? `hits ${s.hits.map(([t, x]) => `${fmtT(t)} (${x})`).join(', ')}` : '', `${s.onsets} onsets`].filter(Boolean).join('; ');
    lines.push(`| ${s.id} | ${fmtT(s.t0)}-${fmtT(s.t1)} (${fmtT(s.dur)} s) | ____ | ____ <br> ${pal(s.palette)} <br> ${link(s.stills.first, 'first')} ${link(s.stills.mid, 'mid')} | ____ <br> energy ${s.motion.mean} mean, ${s.motion.peak} peak at ${fmtT(s.motion.peakT)}${s.moves.length ? `; ${s.moves.join(', ')}` : ''} | ${tOut} | ${sound} ____ |`);
  });
  lines.push('', '## Measured, not eyeballed', '', '- Positions and sizes: ____ (px on full-resolution stills: `node grab.mjs <video> <t,...> <dir>`)',
    '- Camera fits: ____ (look-at / orbit parameters per keyframe)', '- Colours sampled: ____ (hex at named points)', '');
  return lines.join('\n');
}
