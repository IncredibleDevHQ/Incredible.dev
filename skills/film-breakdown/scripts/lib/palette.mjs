// Dominant colours of a set of small RGB frames: k-means in OKLab (deterministic seeding), then a
// second pass over only the bright or saturated pixels, so a thin accent line or white copy is
// reported even when the ground covers 95% of the frame.
const lin = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
const LIN = Float64Array.from({ length: 256 }, (_, i) => lin(i));

function oklab(r, g, b) {
  const R = LIN[r], G = LIN[g], B = LIN[b];
  const l = Math.cbrt(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B);
  const m = Math.cbrt(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B);
  const s = Math.cbrt(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}
const hex = (r, g, b) => '#' + [r, g, b].map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('').toUpperCase();

function mulberry(a) { return () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

function kmeans(pts, k, iters = 14, seed = 7) {
  const n = pts.length; if (!n) return [];
  k = Math.min(k, n); const rnd = mulberry(seed), C = [pts[Math.floor(rnd() * n)].lab.slice()];
  const d2 = new Float64Array(n).fill(Infinity);
  const dist = (a, b) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2;
  while (C.length < k) { // k-means++
    let sum = 0; for (let i = 0; i < n; i++) { d2[i] = Math.min(d2[i], dist(pts[i].lab, C[C.length - 1])); sum += d2[i]; }
    if (!sum) break; let r = rnd() * sum, i = 0; while (i < n - 1 && (r -= d2[i]) > 0) i++; C.push(pts[i].lab.slice());
  }
  const lab = new Int32Array(n);
  for (let it = 0; it < iters; it++) {
    for (let i = 0; i < n; i++) { let bj = 0, bd = Infinity; for (let j = 0; j < C.length; j++) { const d = dist(pts[i].lab, C[j]); if (d < bd) { bd = d; bj = j; } } lab[i] = bj; }
    const acc = C.map(() => [0, 0, 0, 0]);
    for (let i = 0; i < n; i++) { const a = acc[lab[i]], p = pts[i].lab; a[0] += p[0]; a[1] += p[1]; a[2] += p[2]; a[3]++; }
    acc.forEach((a, j) => { if (a[3]) C[j] = [a[0] / a[3], a[1] / a[3], a[2] / a[3]]; });
  }
  const out = C.map(() => ({ n: 0, rgb: [0, 0, 0], lab: [0, 0, 0] }));
  for (let i = 0; i < n; i++) { const o = out[lab[i]], p = pts[i]; o.n++; o.rgb[0] += p.rgb[0]; o.rgb[1] += p.rgb[1]; o.rgb[2] += p.rgb[2]; }
  return out.filter((o) => o.n).map((o, j) => ({ n: o.n, rgb: o.rgb.map((v) => v / o.n), lab: C[j] }));
}

// frames: array of Uint8Array/Buffer (RGB24). Returns { dominant: [{hex, share}], accents: [{hex, share}] }.
export function palette(frames, { k = 5, accents = 3, maxPixels = 12000, seed = 7 } = {}) {
  let total = 0; for (const f of frames) total += f.length / 3;
  if (!total) return { dominant: [], accents: [] };
  const stride = Math.max(1, Math.floor(total / maxPixels)), pts = [];
  let idx = 0;
  for (const f of frames) for (let q = 0; q < f.length; q += 3, idx++) {
    if (idx % stride) continue;
    const rgb = [f[q], f[q + 1], f[q + 2]]; pts.push({ rgb, lab: oklab(...rgb) });
  }
  const fmt = (cs, denom, min = 0.005) => cs.sort((a, b) => b.n - a.n).map((c) => ({ hex: hex(...c.rgb), share: +(c.n / denom).toFixed(4) }))
    .filter((c) => c.share >= min);
  const dominant = fmt(kmeans(pts, k, 14, seed), pts.length);
  const bright = pts.filter((p) => p.lab[0] > 0.8 || Math.hypot(p.lab[1], p.lab[2]) > 0.09);
  const acc = bright.length >= Math.max(8, pts.length * 0.002) ? fmt(kmeans(bright, accents, 12, seed + 1), pts.length, 0.0005) : [];
  return { dominant, accents: acc.filter((a) => !dominant.slice(0, 2).some((d) => d.hex === a.hex)) };
}
