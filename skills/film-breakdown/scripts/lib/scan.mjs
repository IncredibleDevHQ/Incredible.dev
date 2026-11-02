// One decode of the whole film feeds every per-frame measurement:
//   motion   the motion chain (160 px, gblur 1.5, gray, tblend difference, signalstats YAVG)
//   scene    ffmpeg's scene score (resolution independent within 0.005, so it runs on a 320 px copy)
//   tiny     64 px RGB frames streamed into Node: frame difference, colour-histogram distance,
//            motion-compensated difference (best global shift) and mean luma, frame by frame
//   palette  128 px RGB frames at ~8 fps for colours and the content-change curve
//   tiles    labelled-sheet tiles on the 4 fps grid (exact source frames)
import fs from 'node:fs'; import path from 'node:path';
import { runAsync, rgbScale, fitDims, timeOf, passthrough } from './media.mjs';

export const MOTION_CHAIN = 'scale=160:-1,gblur=sigma=1.5,format=gray,tblend=all_mode=difference,signalstats';

// Frames on a k-per-second grid: frame round(j / k * fps) for j = 0, 1, ... (same arithmetic as the
// select expression below, so the i-th written tile is the i-th frame of this list).
export function gridFrames(v, perSec, nFrames) {
  const out = [];
  for (let n = 0; n < nFrames; n++) {
    const k = Math.round((n * perSec * v.den) / v.num);
    if (Math.round((k * v.num) / (perSec * v.den)) === n) out.push(n);
  }
  return out;
}
const gridExpr = (v, perSec) => `eq(round(round(n*${perSec * v.den}/${v.num})*${v.num}/${perSec * v.den}),n)`;

export function parseMeta(file, key) {
  const out = new Map(); if (!fs.existsSync(file)) return out;
  let n = null;
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (line.startsWith('frame:')) { const m = /pts_time:([-0-9.e]+)/.exec(line); n = m ? +m[1] : null; }
    else if (n != null && line.startsWith(key + '=')) out.set(n, +line.slice(key.length + 1));
  }
  return out; // pts_time -> value
}

// Motion values in frame order: entry j is |frame j+1 - frame j| (one fewer than frames).
export function readMotion(file) {
  return [...parseMeta(file, 'lavfi.signalstats.YAVG').entries()].sort((a, b) => a[0] - b[0]).map((e) => e[1]);
}

export async function scan(file, v, { cache, tiles = true, tileLong = 288, tilePerSec = 4, tinyLong = 64, paletteLong = 128,
  from = 0, to = null, mcShift = 3 } = {}) {
  fs.mkdirSync(cache, { recursive: true });
  const tileDir = path.join(cache, 'tiles');
  if (tiles) { fs.rmSync(tileDir, { recursive: true, force: true }); fs.mkdirSync(tileDir, { recursive: true }); }
  const dur = (to ?? v.duration) - from;
  const nFramesEst = Math.round(dur * v.fpsValue) + 2;
  const keepPerSec = Math.max(1, Math.min(8, Math.floor(1500 / Math.max(1, dur)))); // <= ~1500 palette frames
  const [tw, th] = fitDims(v, tinyLong), [pw, ph] = fitDims(v, paletteLong), [xw, xh] = fitDims(v, tileLong);
  const branches = tiles ? 4 : 3;
  const graph = [
    `[0:${v.index}]split=${branches}[m][s][p]${tiles ? '[k]' : ''}`,
    `[m]${MOTION_CHAIN},metadata=print:key=lavfi.signalstats.YAVG:file=motion.txt[mo]`,
    `[s]scale=320:-2:flags=area,format=yuv420p,select='gte(scene,0)',metadata=print:key=lavfi.scene_score:file=scene.txt,${rgbScale(v, tw, th, 'area')},format=rgb24[so]`,
    `[p]select='${gridExpr(v, keepPerSec)}',${rgbScale(v, pw, ph, 'area')},format=rgb24[po]`,
    ...(tiles ? [`[k]select='${gridExpr(v, tilePerSec)}',${rgbScale(v, xw, xh, 'lanczos')},format=rgb24,format=yuvj444p[ko]`] : []),
  ].join(';');
  const args = ['-hide_banner', '-nostats', '-loglevel', 'error', ...(from ? ['-ss', String(from)] : []), ...(to != null ? ['-t', String(to - from)] : []),
    '-i', file, '-an', '-sn', '-dn', '-filter_complex', graph,
    '-map', '[mo]', '-f', 'null', '-',
    '-map', '[po]', ...passthrough(), '-f', 'rawvideo', '-y', 'palette.rgb', // passthrough: rawvideo defaults to CFR and would pad the selection with duplicates
    ...(tiles ? ['-map', '[ko]', ...passthrough(), '-q:v', '3', '-y', 'tiles/%05d.jpg'] : []),
    '-map', '[so]', '-f', 'rawvideo', 'pipe:1'];

  // Per-frame features from the tiny stream, computed while ffmpeg decodes.
  const FB = tw * th * 3, npx = tw * th;
  let buf = Buffer.alloc(0), n = 0, prevRGB = null, prev2RGB = null, prevY = null, prevH = null;
  const D = [], D2 = [], HD = [], MC = [], Y = [], SAT = [], RHO = [];
  const lum = new Float32Array(npx), hist = new Float32Array(64);
  const onFrame = (f) => {
    let ysum = 0, ssum = 0; hist.fill(0);
    for (let p = 0, q = 0; p < npx; p++, q += 3) {
      const r = f[q], g = f[q + 1], b = f[q + 2];
      const y = 0.2126 * r + 0.7152 * g + 0.0722 * b; lum[p] = y; ysum += y;
      ssum += Math.max(r, g, b) - Math.min(r, g, b);
      hist[((r >> 6) << 4) | ((g >> 6) << 2) | (b >> 6)] += 1;
    }
    Y.push(ysum / npx); SAT.push(ssum / npx);
    if (prevRGB) {
      let s = 0; for (let q = 0; q < FB; q++) s += Math.abs(f[q] - prevRGB[q]);
      const d = s / FB; D.push(d);
      // Skip-one difference |frame i - frame i-2|: across a hard cut it is about as large as the cut
      // itself; across a one-frame blend (fade, dissolve) the blend frame sits halfway, so ~2x.
      if (prev2RGB) { let s2 = 0; for (let q = 0; q < FB; q++) s2 += Math.abs(f[q] - prev2RGB[q]); D2.push(s2 / FB); } else D2.push(d);
      let h = 0; for (let k = 0; k < 64; k++) h += Math.abs(hist[k] - prevH[k]); HD.push(h / (2 * npx));
      // Structure kept from the previous frame: luma correlation (~1 for the same picture, even when it
      // brightens or shifts a little; low when the picture is replaced, however dark both frames are).
      let ma = 0, mb = 0; for (let p = 0; p < npx; p++) { ma += lum[p]; mb += prevY[p]; } ma /= npx; mb /= npx;
      let sab = 0, saa = 0, sbb = 0; for (let p = 0; p < npx; p++) { const a = lum[p] - ma, b = prevY[p] - mb; sab += a * b; saa += a * a; sbb += b * b; }
      RHO.push(saa > 1e-3 * npx && sbb > 1e-3 * npx ? sab / Math.sqrt(saa * sbb) : (Math.abs(ma - mb) < 2 ? 1 : 0));
      // Best global shift of the previous frame (a pan within +-mcShift tiny pixels scores ~0).
      let best = Infinity;
      if (d > 1) {
        for (let sy = -mcShift; sy <= mcShift; sy++) for (let sx = -mcShift; sx <= mcShift; sx++) {
          let e = 0, c = 0;
          const x0 = Math.max(0, sx), x1 = Math.min(tw, tw + sx), y0 = Math.max(0, sy), y1 = Math.min(th, th + sy);
          for (let yy = y0; yy < y1; yy++) {
            const row = yy * tw, prow = (yy - sy) * tw - sx;
            for (let xx = x0; xx < x1; xx++) e += Math.abs(lum[row + xx] - prevY[prow + xx]);
            c += x1 - x0;
          }
          if (c) best = Math.min(best, e / c);
          if (best < 0.5) break;
        }
      } else best = d;
      MC.push(best);
    } else { D.push(0); D2.push(0); HD.push(0); MC.push(0); RHO.push(1); }
    prev2RGB = prevRGB; prevRGB = Buffer.from(f); prevY = Float32Array.from(lum); prevH = Float32Array.from(hist);
    n++;
  };
  await runAsync('ffmpeg', args, {
    cwd: cache,
    onStdout: (chunk) => {
      buf = buf.length ? Buffer.concat([buf, chunk]) : chunk;
      let off = 0;
      while (buf.length - off >= FB) { onFrame(buf.subarray(off, off + FB)); off += FB; }
      buf = buf.subarray(off);
    },
  });

  // Scene scores and motion by frame index (pts relative to the first decoded frame).
  const t0 = from ? from : 0;
  const scene = new Float32Array(n);
  for (const [t, s] of parseMeta(path.join(cache, 'scene.txt'), 'lavfi.scene_score')) {
    const i = Math.round((t * v.num) / v.den); if (i >= 0 && i < n) scene[i] = s;
  }
  const motion = readMotion(path.join(cache, 'motion.txt'));
  // Palette frames: every frame on the keepPerSec grid.
  const palFrames = gridFrames(v, keepPerSec, n);
  const pal = fs.readFileSync(path.join(cache, 'palette.rgb')); const PB = pw * ph * 3;
  if (Math.abs(pal.length / PB - palFrames.length) > 1) throw new Error(`scan: ${pal.length / PB} palette frames for ${palFrames.length} selected`);
  const kept = palFrames.slice(0, Math.floor(pal.length / PB)).map((fi, j) => ({ n: fi, px: pal.subarray(j * PB, (j + 1) * PB) }));
  fs.rmSync(path.join(cache, 'palette.rgb'), { force: true });
  let tileList = [];
  if (tiles) {
    const files = fs.readdirSync(tileDir).filter((f) => f.endsWith('.jpg')).sort();
    const want = gridFrames(v, tilePerSec, n);
    if (Math.abs(files.length - want.length) > 1) throw new Error(`scan: ${files.length} tiles for ${want.length} selected frames`);
    tileList = files.map((f, j) => ({ n: want[j], t: timeOf(want[j] ?? 0, v) + t0, file: path.join(tileDir, f) })).filter((x) => x.n != null);
  }
  return { n, from: t0, scene, motion, d: Float32Array.from(D), d2: Float32Array.from(D2), hd: Float32Array.from(HD), mc: Float32Array.from(MC), rho: Float32Array.from(RHO), y: Float32Array.from(Y),
    sat: Float32Array.from(SAT), kept, keepPerSec, palDims: [pw, ph], tiles: tileList, tiny: [tw, th], nFramesEst };
}
