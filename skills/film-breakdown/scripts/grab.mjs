#!/usr/bin/env node
// Frame-exact stills at given times, on the file's own rational frame grid.
//
//   node grab.mjs <video> <t1,t2,...> <outdir> [--scale w] [--jpg] [--sheet]
//
// A time picks the nearest frame, n = round(t * num / den) (30000/1001 is exact, not 29.97), the
// same frame a renderer draws for time t at that fps; "f223" picks frame 223.
// Files are named t007.441_f00223.png (the frame's own time and index). --scale w sets the output
// width (full resolution by default, PNG unless --jpg); --sheet also tiles them into a labelled
// review sheet (<= 1500 px). Prints [{ requested, n, t, file }] as JSON.
import path from 'node:path';
import { probe, extractFrames, makeSheets, labelFont, frameAt, fmtT, arg, flag, positional, fitDims } from './lib/media.mjs';

const fail = (e) => { console.error(`grab: ${(e && e.message) || e}`); process.exit(1); };
process.on('uncaughtException', fail); process.on('unhandledRejection', fail);
const argv = process.argv.slice(2);
const [video, list, out] = positional(argv, ['scale']);
if (!video || !list || !out) { console.error('usage: node grab.mjs <video> <t1,t2,...|f123,...> <outdir> [--scale w] [--jpg] [--sheet]'); process.exit(2); }
const info = probe(video), v = info.video;
if (!v) { console.error(`grab: no video stream in ${video}`); process.exit(1); }
const req = String(list).split(',').map((s) => s.trim()).filter(Boolean).map((s) => (s.startsWith('f') ? { requested: s, n: +s.slice(1) } : { requested: +s, n: frameAt(+s, v) }));
const bad = req.filter((r) => !Number.isFinite(r.n) || r.n < 0 || (v.nbFrames && r.n >= v.nbFrames));
if (bad.length) { console.error(`grab: outside the film (${v.nbFrames} frames, ${v.duration} s): ${bad.map((b) => b.requested).join(', ')}`); process.exit(1); }
const w = +arg(argv, 'scale', 0);
const [dw, dh] = fitDims(v, Math.max(v.width, v.height));
const long = w ? Math.round(dw >= dh ? w : (w * dh) / dw) : 0;
const got = await extractFrames(path.resolve(video), v, req.map((r) => r.n), { dir: path.resolve(out), fmt: flag(argv, 'jpg') ? 'jpg' : 'png', long });
const byN = new Map(got.map((g) => [g.n, g]));
const res = req.map((r) => ({ requested: r.requested, n: r.n, t: byN.get(r.n)?.t ?? null, file: byN.get(r.n)?.file ?? null }));
if (flag(argv, 'sheet')) {
  const sheets = await makeSheets(got.map((g) => ({ file: g.file, label: `${fmtT(g.t)} f${g.n}` })), (k, K) => path.join(path.resolve(out), K > 1 ? `sheet-${k}.jpg` : 'sheet.jpg'),
    dw / dh, { font: labelFont(path.resolve(out)) });
  console.error(`grab: sheet ${sheets.join(', ')}`);
}
if (res.some((r) => !r.file)) { console.error('grab: some frames could not be extracted'); process.exitCode = 1; }
console.log(JSON.stringify(res, null, 1));
