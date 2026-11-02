#!/usr/bin/env node
// The verification loop: a recreation (MINE) against its reference (REF), after every change.
//
//   node compare.mjs --ref <video> --mine <video> [--times t1,t2,... | --every s] [--from s] [--to s]
//                    [--out dir] [--no-video] [--audio mine|ref|none]
//
// MINE is a rendered video (a HyperFrames draft render is enough). Writes to --out (default: compare/
// next to MINE):
//   pairs-N.jpg        REF above MINE at the same instants (6 pairs a sheet, <= 1500 px), SSIM on each
//   stills/            the pairs at 960 px (ref_t…png, mine_t…png)
//   side-by-side.mp4   REF left, MINE right, 1920x540 on REF's frame grid, with timecode and frame number
//   compare.json       per-second motion energy of both (the motion chain in lib/scan.mjs), correlation,
//                      the largest energy and timing deltas, hard cuts matched frame by frame, both audits
// --from/--to restrict everything to one act.
import fs from 'node:fs'; import path from 'node:path';
import { probe, extractFrames, makeSheet, sheetLayout, labelFont, runAsync, timeOf, frameAt, fmtT, r2, r3, now, arg, flag, pool, cpus, fitDims } from './lib/media.mjs';
import { scan, MOTION_CHAIN, readMotion } from './lib/scan.mjs';
import { detectCuts, motionReport } from './lib/cuts.mjs';

const fail = (e) => { console.error(`compare: ${(e && e.message) || e}`); process.exit(1); };
process.on('uncaughtException', fail); process.on('unhandledRejection', fail);
const argv = process.argv.slice(2);
const refPath = arg(argv, 'ref'), minePath = arg(argv, 'mine');
if (!refPath || !minePath || flag(argv, 'help')) {
  console.error('usage: node compare.mjs --ref <video> --mine <video> [--times t1,t2,...|--every s] [--from s] [--to s] [--out dir] [--no-video] [--audio mine|ref|none]');
  process.exit(2);
}
const T0 = now(), timings = {}, notes = [];
const OUT = path.resolve(arg(argv, 'out', path.join(path.dirname(path.resolve(minePath)), 'compare')));
const R = probe(refPath), rv = R.video;
const M = probe(minePath), mv = M.video;
if (!rv || !mv) { console.error('compare: both inputs need a video stream'); process.exit(1); }
const CACHE = path.join(OUT, '.cache'), STILLS = path.join(OUT, 'stills');
for (const d of [CACHE, STILLS]) { fs.rmSync(d, { recursive: true, force: true }); fs.mkdirSync(d, { recursive: true }); }
const font = labelFont(CACHE);
const refDur = timeOf(rv.nbFrames, rv), mineDur = timeOf(mv.nbFrames, mv);
if (Math.abs(refDur - mineDur) > 0.05) notes.push(`durations differ: REF ${r3(refDur)} s, MINE ${r3(mineDur)} s`);
const sameRate = Math.abs(rv.fpsValue - mv.fpsValue) < 1e-6;
if (!sameRate) notes.push(`frame rates differ (REF ${rv.fps}, MINE ${mv.fps}): MINE's curves are resampled to REF's grid; its audit uses its own rate`);
const from = Math.max(0, +arg(argv, 'from', 0)), to = Math.min(+arg(argv, 'to', Infinity), refDur, mineDur);
const refStart = frameAt(from, rv), mineStart = frameAt(from, mv);
const full = refStart === 0 && to >= Math.min(refDur, mineDur) - 0.05;

// Instants, snapped to REF's frame grid so both sides show the same moment.
let times;
if (arg(argv, 'times')) times = arg(argv, 'times').split(',').map(Number).filter((t) => t >= from && t < to);
else { const every = +arg(argv, 'every', 0), k = every ? Math.max(1, Math.floor((to - from) / every)) : 12, span = (to - from) / k; times = Array.from({ length: k }, (_, i) => from + (i + 0.5) * span); }
const frames = [...new Set(times.map((t) => frameAt(t, rv)))].filter((n) => n < rv.nbFrames);
times = frames.map((n) => timeOf(n, rv));
const tName = (t) => `t${fmtT(t, 3).padStart(7, '0')}`;

// ---------------------------------------------------------------- 1. stills: REF and MINE at the same instants
async function refStills() {
  const got = await extractFrames(path.resolve(refPath), rv, frames, { dir: STILLS, fmt: 'png', long: 960, name: (n, t) => `ref_${tName(t)}_f${n}` });
  const m = new Map(got.map((g) => [g.n, g.file])); return frames.map((n) => m.get(n) || null);
}
async function mineStills() {
  const want = times.map((t) => frameAt(t, mv));
  const got = await extractFrames(path.resolve(minePath), mv, want, { dir: STILLS, fmt: 'png', long: 960, name: (n, t) => `mine_${tName(t)}_f${n}` });
  const m = new Map(got.map((g) => [g.n, g.file])); return want.map((n) => m.get(n) || null);
}

// ---------------------------------------------------------------- 2. motion and cuts of both, the side-by-side
const seekArgs = (v, start) => (start ? ['-ss', timeOf(start - 0.25, v).toFixed(6)] : []);
const lenArgs = () => (to < refDur - 1e-6 ? ['-t', String(to - from)] : []);
const scanOf = (file, v, start, tag) => scan(path.resolve(file), v, { cache: path.join(CACHE, tag), tiles: false,
  from: start ? timeOf(start - 0.25, v) : 0, to: to < refDur - 1e-6 ? (start ? timeOf(start - 0.25, v) : 0) + (to - from) : null });
async function resampledMotion() { // MINE through the motion chain on REF's frame grid
  const dir = path.join(CACHE, 'resampled'); fs.mkdirSync(dir, { recursive: true });
  await runAsync('ffmpeg', ['-hide_banner', '-nostats', '-loglevel', 'error', ...seekArgs(mv, mineStart), ...lenArgs(), '-i', path.resolve(minePath), '-an',
    '-vf', `fps=${rv.fps},${MOTION_CHAIN},metadata=print:key=lavfi.signalstats.YAVG:file=motion.txt`, '-f', 'null', '-'], { cwd: dir });
  return readMotion(path.join(dir, 'motion.txt'));
}
async function sideBySide(out) {
  const t = now(), X = from, D = to - from, face = font ? `fontfile=${font}` : 'font=monospace';
  const cell = (i, name) => `[${i}:v]fps=${rv.fps},scale=960:540:force_original_aspect_ratio=decrease:flags=lanczos,pad=960:540:(ow-iw)/2:(oh-ih)/2:color=0x101010,format=yuv420p,` +
    `drawtext=text='${name}':${face}:x=12:y=10:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=4[${name}]`;
  const audio = arg(argv, 'audio', 'mine'), amap = audio === 'none' ? [] : ['-map', `${audio === 'ref' ? 0 : 1}:a:0?`, '-c:a', 'aac', '-b:a', '160k'];
  const graph = `${cell(0, 'REF')};${cell(1, 'MINE')};[REF][MINE]hstack=inputs=2,` +
    `drawtext=text='%{pts\\:hms\\:${X.toFixed(3)}}  f%{eif\\:n+${refStart}\\:d}':${face}:x=w-tw-12:y=10:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=4[v]`;
  await runAsync('ffmpeg', ['-hide_banner', '-nostats', '-loglevel', 'error', '-y', ...seekArgs(rv, refStart), '-t', String(D), '-i', path.resolve(refPath),
    ...seekArgs(mv, mineStart), '-t', String(D), '-i', path.resolve(minePath), '-filter_complex', graph, '-map', '[v]', ...amap,
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out]);
  timings.video = r2(now() - t);
}
const wantVideo = !flag(argv, 'no-video');
let t0 = now();
const P = {
  refStills: refStills(), mineStills: mineStills(),
  scanRef: scanOf(refPath, rv, refStart, 'scan-ref'),
  scanMine: scanOf(minePath, mv, mineStart, 'scan-mine'),
  resampled: sameRate ? null : resampledMotion(),
  video: wantVideo ? sideBySide(path.join(OUT, 'side-by-side.mp4')) : null,
};
const refSt = await P.refStills, mineSt = await P.mineStills; timings.stills = r2(now() - t0);
const SR = await P.scanRef, SM = await P.scanMine, resampled = await P.resampled; timings.analysis = r2(now() - t0);

// ---------------------------------------------------------------- 3. SSIM per pair and the pair sheets
let t1 = now();
const ssim = await pool(times.map((_, i) => i), Math.max(2, Math.min(8, cpus())), async (i) => {
  if (!refSt[i] || !mineSt[i]) return null;
  const r = await runAsync('ffmpeg', ['-hide_banner', '-nostats', '-i', refSt[i], '-i', mineSt[i], '-filter_complex',
    '[0:v]scale=480:270,format=gray[a];[1:v]scale=480:270,format=gray[b];[a][b]ssim', '-f', 'null', '-'], { allowFail: true });
  const m = /All:([0-9.]+)/.exec(r.stderr); return m ? r3(+m[1]) : null;
});
const blank = path.join(CACHE, 'blank.png');
await runAsync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x1A1D24:s=64x36', '-frames:v', '1', blank]);
const [dw, dh] = fitDims(rv, 1000), L = sheetLayout(12, dw / dh, { cols: 3 });
const pairs = [];
for (let k = 0; k * 6 < times.length; k++) {
  const group = times.map((_, i) => i).slice(k * 6, k * 6 + 6), tiles = [];
  for (const row of [group.slice(0, 3), group.slice(3, 6)]) {
    if (!row.length) continue;
    const pad = (arr) => [...arr, ...Array.from({ length: 3 - arr.length }, () => ({ file: blank, label: ' ' }))];
    tiles.push(...pad(row.map((i) => ({ file: refSt[i] || blank, label: `REF ${fmtT(times[i])} f${frames[i]}`, color: '0xFFD60A' }))));
    tiles.push(...pad(row.map((i) => ({ file: mineSt[i] || blank, label: mineSt[i] ? `MINE  ssim ${ssim[i] ?? '-'}` : 'MINE missing', color: '0x64D2FF' }))));
  }
  const out = path.join(OUT, `pairs-${k + 1}.jpg`);
  await makeSheet(tiles, out, { ...L, cols: 3, font });
  pairs.push(path.relative(OUT, out));
}
timings.sheets = r2(now() - t1);
await P.video;

// ---------------------------------------------------------------- 4. the numbers
const result = { tool: 'film-breakdown/compare.mjs', created: new Date().toISOString(), range: { from: r3(from), to: r3(to), wholeFilm: full },
  ref: { path: R.path, fps: rv.fps, frames: rv.nbFrames, duration: r3(refDur) },
  mine: { path: M.path, fps: mv.fps, frames: mv.nbFrames, duration: r3(mineDur) },
  outputs: { pairs, stills: 'stills', sideBySide: wantVideo ? 'side-by-side.mp4' : null },
  stills: times.map((t, i) => ({ t: r3(t), n: frames[i], ssim: ssim[i] })), notes };
const okS = result.stills.filter((s) => s.ssim != null);
result.stillsSummary = { meanSsim: okS.length ? r3(okS.reduce((a, s) => a + s.ssim, 0) / okS.length) : null, worst: [...okS].sort((a, b) => a.ssim - b.ssim).slice(0, 4) };
if (SR && SM) {
  const fr = rv.fpsValue, refM = SR.motion, mineM = resampled || SM.motion;
  const perSec = (m) => { const b = []; m.forEach((x, j) => { const s = Math.floor(timeOf(refStart + j + 1, rv) + 1e-9); (b[s] ||= [0, 0]); b[s][0] += x; b[s][1]++; }); return b; };
  const a = perSec(refM), b = perSec(mineM), secs = [];
  for (let s = Math.floor(from); s < Math.ceil(to - 1e-6); s++) if (a[s] && b[s]) secs.push(s);
  const A1 = secs.map((s) => r2(a[s][0] / a[s][1])), B1 = secs.map((s) => r2(b[s][0] / b[s][1]));
  const la = refM.map((x) => Math.log1p(x)), lb = mineM.map((x) => Math.log1p(x));
  const glob = bestLag(la, lb, 0, la.length, 30), W = Math.round(2 * fr), H = Math.round(fr), wins = [];
  for (let s = 0; s + W <= la.length; s += H) {
    const w = bestLag(la, lb, s, s + W, 12);
    if (w && w.corr >= 0.5 && w.sd > 0.05 && Math.abs(w.lag) >= 2 && w.corr - w.corr0 >= 0.05) wins.push({ t0: r2(timeOf(refStart + s, rv)), t1: r2(timeOf(refStart + s + W, rv)), lagFrames: w.lag, corr: r2(w.corr), corrAtZero: r2(w.corr0) });
  }
  const feats = (S) => ({ scene: S.scene, d: S.d, d2: S.d2, hd: S.hd, mc: S.mc, rho: S.rho, y: S.y });
  const abs = (cuts, v, start) => cuts.map((c) => ({ n: c.n + start, t: r3(timeOf(c.n + start, v)), confidence: c.confidence }));
  const refCuts = abs(detectCuts(feats(SR), rv).cuts, rv, refStart), mineCuts = abs(detectCuts(feats(SM), mv).cuts, mv, mineStart);
  const matched = [], used = new Set();
  for (const c of refCuts) {
    const best = mineCuts.filter((m) => !used.has(m.n)).sort((x, y) => Math.abs(x.t - c.t) - Math.abs(y.t - c.t))[0];
    if (best && Math.abs(best.t - c.t) <= 0.5) { used.add(best.n); matched.push({ ref: c.t, mine: best.t, refFrame: c.n, deltaFrames: Math.round((best.t - c.t) * fr) }); }
  }
  result.motion = {
    chain: "motion chain (YAVG of the frame difference at 160 px, blurred), per second on REF's clock",
    perSecond: { seconds: secs, ref: A1, mine: B1 },
    correlation: { perSecond: r3(pearson(A1, B1)), perFrameLog: r3(pearson(la, lb.slice(0, la.length))) },
    globalLagFrames: glob ? glob.lag : null,
    energyDeltas: secs.map((s, i) => ({ second: s, ref: A1[i], mine: B1[i], delta: r2(B1[i] - A1[i]) })).sort((x, y) => Math.abs(y.delta) - Math.abs(x.delta)).slice(0, 8),
    timingDeltas: wins.sort((x, y) => Math.abs(y.lagFrames) - Math.abs(x.lagFrames)).slice(0, 8),
  };
  result.cuts = { ref: refCuts.length, mine: mineCuts.length, exact: matched.filter((m) => m.deltaFrames === 0).length, matched,
    missingInMine: refCuts.filter((c) => !matched.some((m) => m.refFrame === c.n)).map((c) => c.t), extraInMine: mineCuts.filter((c) => !used.has(c.n)).map((c) => c.t) };
  const aud = (m, v, p) => motionReport(m, v, { hasAudio: !!p.audio, duration: to - from }).audit;
  result.audits = { scope: full ? 'whole film' : `range ${r2(from)}-${r2(to)} s only (holds and still% of this range)`, ref: aud(SR.motion, rv, R), mine: aud(SM.motion, mv, M) };
}
fs.rmSync(CACHE, { recursive: true, force: true });
timings.total = r2(now() - T0); result.timings = timings;
fs.writeFileSync(path.join(OUT, 'compare.json'), JSON.stringify(result, null, 1));
const m = result.motion, c = result.cuts;
console.log(JSON.stringify({ out: OUT, pairs, sideBySide: result.outputs.sideBySide, meanSsim: result.stillsSummary.meanSsim, worstStills: result.stillsSummary.worst,
  ...(m ? { motionCorrelation: m.correlation, globalLagFrames: m.globalLagFrames, energyDeltas: m.energyDeltas.slice(0, 5), timingDeltas: m.timingDeltas.slice(0, 5),
    cuts: { ref: c.ref, mine: c.mine, exact: c.exact, off: c.matched.filter((x) => x.deltaFrames).map((x) => `${x.ref} ${x.deltaFrames > 0 ? '+' : ''}${x.deltaFrames}f`), missingInMine: c.missingInMine, extraInMine: c.extraInMine },
    audits: { scope: result.audits.scope, ref: result.audits.ref.verdict.slice(0, 70), mine: result.audits.mine.verdict.slice(0, 70) } } : {}), timings, notes }, null, 1));

function pearson(a, b) {
  const n = Math.min(a.length, b.length); if (n < 3) return null;
  let ma = 0, mb = 0; for (let i = 0; i < n; i++) { ma += a[i]; mb += b[i]; } ma /= n; mb /= n;
  let sab = 0, saa = 0, sbb = 0; for (let i = 0; i < n; i++) { const x = a[i] - ma, y = b[i] - mb; sab += x * y; saa += x * x; sbb += y * y; }
  return saa && sbb ? sab / Math.sqrt(saa * sbb) : null;
}
// Lag in frames of MINE against REF that best correlates REF's window [s, e); + means MINE is late.
function bestLag(a, b, s, e, maxLag) {
  const seg = a.slice(s, e), mu = seg.reduce((x, y) => x + y, 0) / seg.length;
  const sd = Math.sqrt(seg.reduce((x, y) => x + (y - mu) ** 2, 0) / seg.length);
  let best = null, c0 = null;
  for (let L = -maxLag; L <= maxLag; L++) {
    if (s + L < 0 || e + L > b.length) continue;
    const c = pearson(seg, b.slice(s + L, e + L)); if (c == null) continue;
    if (L === 0) c0 = c;
    if (!best || c > best.corr) best = { lag: L, corr: c };
  }
  return best && { ...best, corr0: c0 ?? 0, sd };
}
