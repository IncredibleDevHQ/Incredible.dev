// Hard cuts vs everything else, from the per-frame features of scan.mjs. A hard cut is one frame
// where the picture is replaced:
//   magnitude  ffmpeg's scene score is high (scene)
//   isolation  the frame difference is a spike against the 5 frames either side (spike)
//   no blend   the frame is not halfway between its neighbours: |f[i]-f[i-1]| is about |f[i+1]-f[i-1]|
//              (a fade or dissolve frame scores ~0.5, a cut ~1) (blend)
// confidence = smoothstep(magnitude) * smoothstep(isolation) * smoothstep(no blend). A cut between two
// dark pictures has a small scene score, so when the change is extremely isolated (spike 6-10+) and
// the picture's structure is replaced (luma correlation with the previous frame below 0.4-0.7, which
// an element popping onto a still frame does not do), the magnitude floor drops by up to 45%.
// Isolation and blend have wide margins; the magnitude floor (--cut-threshold, then --scene-floor)
// is the one to move for unusual material.
import { timeOf, r3, r2 } from './media.mjs';

const ss = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
const median = (a) => { if (!a.length) return 0; const s = [...a].sort((x, y) => x - y); return s[s.length >> 1]; };

export const CUT_DEFAULTS = { threshold: 0.25, minShot: 0.2, sceneLo: 0.12, sceneHi: 0.3, spikeLo: 2, spikeHi: 5, blendLo: 0.55, blendHi: 0.8 };

export function frameFeatures(F, i) {
  const n = F.d.length, nb = [];
  for (let j = i - 5; j <= i + 5; j++) if (j !== i && j >= 1 && j < n) nb.push(F.d[j]);
  const spike = F.d[i] / Math.max(0.5, median(nb));
  const brF = i + 1 < n ? F.d[i] / Math.max(0.5, F.d2[i + 1]) : 1;
  const brB = F.d[i] / Math.max(0.5, F.d2[i]);
  return { spike, blend: Math.min(brF, brB, 1.5), scene: F.scene[i], d: F.d[i], hist: F.hd[i], shift: F.mc[i] / Math.max(0.5, F.d[i]), rho: F.rho ? F.rho[i] : 1 };
}

export function detectCuts(F, v, opts = {}) {
  const o = { ...CUT_DEFAULTS, ...opts };
  const n = F.d.length, cands = [];
  for (let i = 1; i < n; i++) {
    if (F.scene[i] < 0.08 && !(F.d[i] >= 10 && F.scene[i] >= 0.04)) continue;
    const f = frameFeatures(F, i);
    const relax = ss(6, 10, f.spike) * ss(0.7, 0.4, f.rho);
    const mag = ss(o.sceneLo * (1 - 0.45 * relax), o.sceneHi, f.scene), iso = ss(o.spikeLo, o.spikeHi, f.spike), nob = ss(o.blendLo, o.blendHi, f.blend);
    cands.push({ i, ...f, conf: mag * iso * nob, mag, iso, nob });
  }
  // At most one cut per minShot. In a burst of cut-like frames (a cut, then a flash decay, a whip or
  // a word bursting apart) the cut is the first frame that is nearly as strong as the burst's
  // strongest (>= 70%); the rest are its tail.
  const minF = Math.max(1, Math.round(o.minShot * v.fpsValue));
  const accepted = [], rejected = cands.filter((c) => c.conf < o.threshold);
  const strong = cands.filter((c) => c.conf >= o.threshold).sort((a, b) => a.i - b.i);
  for (let k = 0; k < strong.length;) {
    const win = strong.filter((c) => c.i >= strong[k].i && c.i < strong[k].i + minF);
    const top = Math.max(...win.map((c) => c.conf)), pick = win.find((c) => c.conf >= 0.7 * top);
    accepted.push(pick);
    let j = k; while (j < strong.length && strong[j].i < pick.i + minF) { if (strong[j] !== pick) rejected.push({ ...strong[j], suppressedBy: pick.i }); j++; }
    k = j;
  }
  const y = F.y;
  const cuts = accepted.sort((a, b) => a.i - b.i).map((c) => {
    const y0 = y[c.i - 1], y1 = y[c.i];
    const kind = y1 >= 200 && y0 < 160 ? 'to-white' : y1 <= 14 && y0 > 24 ? 'to-black' : y0 >= 200 && y1 < 160 ? 'from-white' : 'cut';
    return { n: c.i, t: r3(timeOf(c.i, v)), at: r3(timeOf(c.i - 0.5, v)), confidence: r2(c.conf), kind,
      scene: r3(c.scene), spike: +c.spike.toFixed(1), blend: r2(c.blend), structure: r2(c.rho), luma: [Math.round(y0), Math.round(y1)] };
  });
  // Everything that looked like a cut but is not one, with the reason, for review.
  // The limiting factor names the reason.
  const REASON = {
    tail: (c) => `within ${o.minShot}s of the cut at frame ${c.suppressedBy} (flash or move tail)`,
    blend: () => 'the frame sits halfway between its neighbours (fade, dissolve, flash decay)',
    continuous: () => 'its neighbours change as much (part of a move or a whip)',
    step: () => 'an isolated one-frame change too small for a cut (in-scene switch, ground lift, hit)',
  };
  const transitions = rejected.filter((c) => c.scene >= 0.12 || c.conf >= 0.01).sort((a, b) => a.i - b.i).slice(0, 80).map((c) => {
    const kind = c.suppressedBy != null ? 'tail' : c.nob <= Math.min(c.mag, c.iso) ? 'blend' : c.iso <= c.mag && c.iso < 0.2 ? 'continuous' : 'step';
    return { n: c.i, t: r3(timeOf(c.i, v)), kind, confidence: r2(c.conf), scene: r3(c.scene), spike: +c.spike.toFixed(1), blend: r2(c.blend), reason: REASON[kind](c) };
  });
  return { cuts, transitions, params: o };
}

// Continuous moves: runs of high motion energy (YAVG of the frame difference) that are not cuts.
// shift = share of the difference a global shift of the previous frame explains (pan/truck ~1,
// zoom/rotate/morph ~0); it only sees shifts up to ~90 px per frame at 1080p, so whips read low.
export function detectMoves(motion, F, v, cuts, { thr } = {}) {
  const sorted = [...motion].sort((a, b) => a - b);
  const p90 = sorted[Math.floor(0.9 * (sorted.length - 1))] || 0;
  const T = thr ?? Math.max(6, p90);
  const cutSet = new Set(); for (const c of cuts) for (let k = -1; k <= 2; k++) cutSet.add(c.n + k);
  const hot = motion.map((m, j) => m >= T && !cutSet.has(j + 1));
  const segs = []; let s = null, gap = 0;
  hot.forEach((h, j) => {
    if (h) { if (s == null) s = j; gap = 0; }
    else if (s != null && ++gap > 2) { segs.push([s, j - gap]); s = null; gap = 0; }
  });
  if (s != null) segs.push([s, hot.length - 1]);
  return { threshold: r2(T), moves: segs.filter(([a, b]) => b - a >= 2).map(([a, b]) => {
    let peak = 0, pj = a, sum = 0, sh = 0, cnt = 0;
    for (let j = a; j <= b; j++) {
      sum += motion[j]; if (motion[j] > peak) { peak = motion[j]; pj = j; }
      const i = j + 1; if (F && F.d[i] > 1) { sh += 1 - Math.min(1, F.mc[i] / F.d[i]); cnt++; }
    }
    const t0 = timeOf(a + 1, v), t1 = timeOf(b + 1, v);
    return { t0: r2(t0), t1: r2(t1), dur: r2(t1 - t0), peakT: r2(timeOf(pj + 1, v)), peakN: pj + 1, peak: +peak.toFixed(1), mean: +(sum / (b - a + 1)).toFixed(1),
      shift: cnt ? r2(sh / cnt) : null, kind: t1 - t0 <= 0.6 && peak >= 2 * T ? 'whip' : 'move' };
  }) };
}

// Still-frame audit of a finished film, at the film's own frame rate. Values are parsed as floats:
// signalstats prints tiny values in exponent form (6.9e-05), which a [0-9.]+ pattern misreads as 6.9.
export function motionReport(motion, v, { maxStillPercent = 25, maxHoldSeconds = 0.6, finalHoldSeconds = 1.5, requireAudio = true, hasAudio = true, duration } = {}) {
  const fps = v.fpsValue, dur = duration ?? v.duration;
  const still = motion.map((x) => x < 0.25), tail = Math.round((dur - finalHoldSeconds) * fps);
  let run = 0, start = 0, longest = 0; const holds = [];
  still.concat([false]).forEach((s, i) => {
    if (s) { if (!run) start = i; run++; }
    else { if (run / fps > maxHoldSeconds && start < tail) holds.push({ at: r2(start / fps), seconds: r2(run / fps) }); longest = Math.max(longest, run); run = 0; }
  });
  const stillPercent = +(100 * still.filter(Boolean).length / Math.max(1, still.length)).toFixed(1);
  const problems = [];
  if (stillPercent > maxStillPercent) problems.push(`still ${stillPercent}% of the time (limit ${maxStillPercent}%)`);
  if (holds.length) problems.push(`${holds.length} hold(s) over ${maxHoldSeconds}s before the final ${finalHoldSeconds}s: ${holds.map((h) => `${h.at}s`).join(', ')}`);
  if (!hasAudio && requireAudio) problems.push('no audio');
  // Per-second energy: the mean of the pair differences that end inside each second.
  const perSecond = [];
  motion.forEach((m, j) => { const s = Math.floor(timeOf(j + 1, v) + 1e-9); (perSecond[s] ||= [0, 0]); perSecond[s][0] += m; perSecond[s][1]++; });
  return {
    perSecond: Array.from({ length: perSecond.length }, (_, s) => (perSecond[s] ? r2(perSecond[s][0] / perSecond[s][1]) : 0)),
    audit: { stillPercent, holds, longestStill: r2(longest / fps), hasAudio, thresholds: { maxStillPercent, maxHoldSeconds, finalHoldSeconds, requireAudio },
      verdict: problems.length ? `FAIL: ${problems.join('; ')}` : 'PASS' },
  };
}
