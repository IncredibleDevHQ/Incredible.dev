// Soundtrack analysis in plain Node: onset envelope, tempo, a beat grid fitted to the onsets, grid
// drift, downbeats, onsets and hits with strength, loudness. The onset envelope follows librosa's
// onset_strength (22.05 kHz mono, 2048-point centred STFT, hop 128, 128 Slaney mel bands, power in dB
// with an 80 dB floor, positive flux averaged over bands, shifted by lag + n_fft/2 hops), so times
// line up with a librosa analysis of the same track. Voice-over words run through Python when
// faster-whisper is importable.
import fs from 'node:fs'; import path from 'node:path'; import { spawnSync } from 'node:child_process';
import { runAsync, LIB, r2, r3 } from './media.mjs';

export const SR = 22050;

// ------------------------------------------------------------------ decode (+ EBU R128 in the same pass)
export async function decodeAudio(file, { cache, sr = SR, streamIndex = null } = {}) {
  fs.mkdirSync(cache, { recursive: true });
  const src = streamIndex != null ? `0:${streamIndex}` : '0:a:0';
  const graph = [`[${src}]asplit=2[a][b]`, `[a]ebur128=metadata=1:peak=true,ametadata=print:file=r128.txt,anullsink`,
    `[b]aresample=${sr},aformat=sample_fmts=flt:channel_layouts=mono[pcm]`].join(';');
  const chunks = [];
  await runAsync('ffmpeg', ['-hide_banner', '-nostats', '-loglevel', 'error', '-i', file, '-vn', '-sn', '-dn', '-filter_complex', graph,
    '-map', '[pcm]', '-f', 'f32le', 'pipe:1'],
  { cwd: cache, onStdout: (d) => chunks.push(d) });
  const buf = Buffer.concat(chunks);
  const x = new Float32Array(buf.buffer, buf.byteOffset, Math.floor(buf.length / 4)).slice();
  return { sr, x, duration: x.length / sr, loudness: readR128(path.join(cache, 'r128.txt')) };
}

function readR128(file) {
  if (!fs.existsSync(file)) return null;
  const rows = []; let cur = null;
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (line.startsWith('frame:')) { const m = /pts_time:([-0-9.e]+)/.exec(line); cur = { t: m ? +m[1] : 0 }; rows.push(cur); }
    else if (cur) { const m = /^lavfi\.r128\.([A-Za-z_.0-9]+)=(.*)$/.exec(line); if (m) cur[m[1]] = +m[2]; }
  }
  if (!rows.length) return null;
  const last = rows[rows.length - 1];
  let tp = 0; for (const r of rows) for (const k in r) if (k.startsWith('true_peaks_ch')) tp = Math.max(tp, r[k]);
  // Momentary loudness (400 ms) averaged per second, and short-term (3 s) at each second.
  const per = [], st = [];
  for (const r of rows) {
    const s = Math.floor(r.t - 1e-6); if (s < 0) continue;
    (per[s] ||= []).push(isFinite(r.M) ? Math.max(-70, r.M) : -70);
    if (Math.abs(r.t - Math.round(r.t)) < 0.051 && Math.round(r.t) >= 1) st[Math.round(r.t) - 1] = isFinite(r.S) ? Math.max(-70, r.S) : -70;
  }
  return { integrated: r2(last.I), lra: r2(last.LRA), truePeak: tp > 0 ? r2(20 * Math.log10(tp)) : null,
    momentaryPerSecond: Array.from({ length: per.length }, (_, s) => (per[s] ? r2(per[s].reduce((a, b) => a + b, 0) / per[s].length) : -70)),
    shortTermPerSecond: Array.from({ length: st.length }, (_, s) => (st[s] != null ? r2(st[s]) : null)) };
}

// ------------------------------------------------------------------ FFT and onset envelope
function makeFFT(N) {
  const levels = Math.round(Math.log2(N));
  const cos = new Float64Array(N / 2), sin = new Float64Array(N / 2);
  for (let i = 0; i < N / 2; i++) { cos[i] = Math.cos((2 * Math.PI * i) / N); sin[i] = Math.sin((2 * Math.PI * i) / N); }
  const rev = new Uint32Array(N);
  for (let i = 0; i < N; i++) { let r = 0, x = i; for (let j = 0; j < levels; j++) { r = (r << 1) | (x & 1); x >>= 1; } rev[i] = r; }
  return (re, im) => {
    for (let i = 0; i < N; i++) { const j = rev[i]; if (j > i) { let t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; } }
    for (let size = 2; size <= N; size <<= 1) {
      const half = size >> 1, step = N / size;
      for (let i = 0; i < N; i += size) {
        for (let j = i, k = 0; j < i + half; j++, k += step) {
          const l = j + half, tr = re[l] * cos[k] + im[l] * sin[k], ti = im[l] * cos[k] - re[l] * sin[k];
          re[l] = re[j] - tr; im[l] = im[j] - ti; re[j] += tr; im[j] += ti;
        }
      }
    }
  };
}

const hz2mel = (f) => (f < 1000 ? (3 * f) / 200 : 15 + (27 * Math.log(f / 1000)) / Math.log(6.4));
const mel2hz = (m) => (m < 15 ? (200 * m) / 3 : 1000 * Math.exp(((m - 15) * Math.log(6.4)) / 27));

function melBank(sr, nfft, nMels) {
  const nb = nfft / 2 + 1, mMax = hz2mel(sr / 2);
  const pts = Array.from({ length: nMels + 2 }, (_, i) => mel2hz((mMax * i) / (nMels + 1)));
  const bank = [];
  for (let m = 0; m < nMels; m++) {
    const [f0, f1, f2] = [pts[m], pts[m + 1], pts[m + 2]], norm = 2 / (f2 - f0), w = [];
    for (let k = 0; k < nb; k++) {
      const f = (k * sr) / nfft, v = Math.max(0, Math.min((f - f0) / (f1 - f0), (f2 - f) / (f2 - f1)));
      if (v > 0) w.push([k, v * norm]);
    }
    bank.push({ w, centre: f1 });
  }
  return bank;
}

// Returns { fr (frames/s), env, low, high } envelopes aligned so index t is time t / fr.
export function onsetEnvelopes(x, sr = SR, { nfft = 2048, hop = 128, nMels = 128 } = {}) {
  const pad = nfft / 2, len = x.length, nFrames = 1 + Math.floor(len / hop);
  const win = new Float64Array(nfft); for (let i = 0; i < nfft; i++) win[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / nfft);
  const fft = makeFFT(nfft), bank = melBank(sr, nfft, nMels), nb = nfft / 2 + 1;
  const S = new Float32Array(nFrames * nMels); // mel power in dB
  const re = new Float64Array(nfft), im = new Float64Array(nfft), p1 = new Float64Array(nb), p2 = new Float64Array(nb);
  const sample = (i) => (i >= 0 && i < len ? x[i] : 0);
  for (let t = 0; t < nFrames; t += 2) { // two real frames per complex FFT
    const a0 = t * hop - pad, b0 = (t + 1) * hop - pad, hasB = t + 1 < nFrames;
    for (let i = 0; i < nfft; i++) { re[i] = sample(a0 + i) * win[i]; im[i] = hasB ? sample(b0 + i) * win[i] : 0; }
    fft(re, im);
    for (let k = 0; k < nb; k++) {
      const j = (nfft - k) % nfft;
      const ar = 0.5 * (re[k] + re[j]), ai = 0.5 * (im[k] - im[j]), br = 0.5 * (im[k] + im[j]), bi = -0.5 * (re[k] - re[j]);
      p1[k] = ar * ar + ai * ai; p2[k] = br * br + bi * bi;
    }
    for (const [tt, p] of hasB ? [[t, p1], [t + 1, p2]] : [[t, p1]]) {
      for (let m = 0; m < nMels; m++) { let e = 0; for (const [k, w] of bank[m].w) e += w * p[k]; S[tt * nMels + m] = 10 * Math.log10(Math.max(1e-10, e)); }
    }
  }
  let top = -Infinity; for (let i = 0; i < S.length; i++) if (S[i] > top) top = S[i];
  for (let i = 0; i < S.length; i++) if (S[i] < top - 80) S[i] = top - 80;
  const lowB = [], highB = [];
  bank.forEach((b, m) => { if (b.centre >= 30 && b.centre <= 150) lowB.push(m); if (b.centre >= 5000) highB.push(m); });
  const shift = 1 + Math.floor(nfft / (2 * hop));
  const env = new Float32Array(nFrames), low = new Float32Array(nFrames), high = new Float32Array(nFrames);
  for (let u = 1; u < nFrames; u++) {
    const t = u - 1 + shift; if (t >= nFrames) break;
    let a = 0, l = 0, h = 0;
    for (let m = 0; m < nMels; m++) { const d = S[u * nMels + m] - S[(u - 1) * nMels + m]; if (d > 0) a += d; }
    for (const m of lowB) { const d = S[u * nMels + m] - S[(u - 1) * nMels + m]; if (d > 0) l += d; }
    for (const m of highB) { const d = S[u * nMels + m] - S[(u - 1) * nMels + m]; if (d > 0) h += d; }
    env[t] = a / nMels; low[t] = l / Math.max(1, lowB.length); high[t] = h / Math.max(1, highB.length);
  }
  return { fr: sr / hop, hop, env, low, high };
}

// ------------------------------------------------------------------ tempo and grid
const at = (e, fr, t) => { const x = t * fr, i = Math.floor(x); if (i < 0 || i + 1 >= e.length) return 0; const f = x - i; return e[i] * (1 - f) + e[i + 1] * f; };
const peakNear = (e, fr, t, w = 0.03) => { let m = 0; const a = Math.max(0, Math.floor((t - w) * fr)), b = Math.min(e.length - 1, Math.ceil((t + w) * fr)); for (let i = a; i <= b; i++) m = Math.max(m, e[i]); return m; };
const meanOf = (e) => { let s = 0; for (const v of e) s += v; return s / Math.max(1, e.length); };

function combScore(e, fr, P, phi, t0, t1) {
  let s = 0, c = 0; for (let t = phi + Math.ceil((t0 - phi) / P) * P; t < t1; t += P) { s += at(e, fr, t); c++; }
  return c ? s / c : 0;
}

export function fitGrid(E, duration, { minBpm = 60, maxBpm = 200, bpmHint = null } = {}) {
  const { env, fr } = E, mu = meanOf(env) || 1;
  // Coarse tempo: autocorrelation of the envelope under a log-normal prior at 120 BPM (as librosa).
  const x = Float64Array.from(env, (v) => v - mu), lags = [];
  for (let L = Math.floor((60 / maxBpm) * fr); L <= Math.ceil((60 / minBpm) * fr); L++) {
    let s = 0; for (let i = L; i < x.length; i++) s += x[i] * x[i - L];
    const bpm = (60 * fr) / L, prior = Math.exp(-0.5 * Math.log2(bpm / (bpmHint || 120)) ** 2 / (bpmHint ? 0.1 : 1));
    lags.push({ L, bpm, ac: s / (x.length - L), w: (s / (x.length - L)) * prior });
  }
  const peaks = lags.filter((l, i) => i > 0 && i < lags.length - 1 && l.ac >= lags[i - 1].ac && l.ac >= lags[i + 1].ac && l.ac > 0).sort((a, b) => b.w - a.w);
  if (!peaks.length) return null;
  const P0 = 60 / peaks[0].bpm, t1 = duration;
  // Comb fit: period and phase that put the grid on the strongest onsets.
  let best = { s: -1 };
  for (let P = P0 * 0.97; P <= P0 * 1.03; P += 0.0002) for (let phi = 0; phi < P; phi += 0.002) {
    const s = combScore(env, fr, P, phi, 0, t1); if (s > best.s) best = { s, P, phi };
  }
  for (const [dp, sp, dq, sq] of [[0.0005, 0.00002, 0.004, 0.0002], [0.00003, 0.000002, 0.0003, 0.00002]]) {
    const b0 = { ...best };
    for (let P = b0.P - dp; P <= b0.P + dp; P += sp) for (let phi = b0.phi - dq; phi <= b0.phi + dq; phi += sq) {
      const s = combScore(env, fr, P, ((phi % P) + P) % P, 0, t1); if (s > best.s) best = { s, P, phi: ((phi % P) + P) % P };
    }
  }
  const alt = [0.5, 2, 2 / 3, 1.5].map((k) => ({ bpm: r2((60 / best.P) * k), score: r2(combScore(env, fr, best.P / k, best.phi, 0, t1) / mu) }));
  return { bpm: r2(60 / best.P), beat: +best.P.toFixed(5), grid0: r3(best.phi), strength: r2(best.s / mu),
    candidates: peaks.slice(0, 4).map((p) => ({ bpm: r2(p.bpm), weight: r3(p.w / peaks[0].w) })), metrical: alt };
}

// Local phase against the global grid in sliding windows: where the music was edited or drifts.
// A window's best phase is noisy under a sparse, voice-led arrangement (one designed hit can pull it),
// so a shift is reported only where two overlapping windows agree on it.
export function gridDrift(E, g, duration, { win = 8, hop = 4 } = {}) {
  const { env, fr } = E, P = g.beat, out = [];
  for (let a = 0; a + win / 2 < duration; a += hop) {
    const b = Math.min(duration, a + win); let best = { s: -1, d: 0 };
    const s0 = combScore(env, fr, P, g.grid0, a, b);
    for (let d = -0.3 * P; d <= 0.3 * P; d += 0.002) { const s = combScore(env, fr, P, g.grid0 + d, a, b); if (s > best.s) best = { s, d }; }
    out.push({ t0: r2(a), t1: r2(b), offsetMs: Math.round(best.d * 1000), gain: r2(best.s / Math.max(1e-9, s0)) });
  }
  const off = (w) => Math.abs(w.offsetMs) >= 25 && w.gain >= 1.2;
  const flagged = out.map((w, i) => off(w) && [out[i - 1], out[i + 1]].some((u) => u && off(u) && Math.abs(u.offsetMs - w.offsetMs) <= 25));
  const shifted = [];
  flagged.forEach((f, i) => {
    if (!f) return;
    const last = shifted[shifted.length - 1];
    if (last && flagged[i - 1]) { last.t1 = out[i].t1; last.n++; last.offsetMs = Math.round(last.offsetMs + (out[i].offsetMs - last.offsetMs) / last.n); }
    else shifted.push({ t0: out[i].t0, t1: out[i].t1, offsetMs: out[i].offsetMs, n: 1 });
  });
  return { windows: out, shifted: shifted.map(({ n, ...r }) => ({ ...r, note: `grid ${r.offsetMs > 0 ? 'late' : 'early'} by ${Math.abs(r.offsetMs)} ms (${r2(Math.abs(r.offsetMs) / 1000 / (P / 4))} sixteenths): an edit in the music or a tempo drift` })) };
}

export function downbeats(E, g, duration, { meter = 4 } = {}) {
  const mu = meanOf(E.low) || 1, low = Float32Array.from(E.low, (v) => Math.log1p(v / mu)), fr = E.fr;
  const P = g.beat, prof = new Array(meter).fill(0), cnt = new Array(meter).fill(0), segs = [];
  const segLen = P * meter * 8; // 8 bars
  for (let k = 0; g.grid0 + k * P < duration; k++) {
    const t = g.grid0 + k * P, a = peakNear(low, fr, t);
    prof[k % meter] += a; cnt[k % meter]++;
    const s = Math.floor(t / segLen); (segs[s] ||= new Array(meter).fill(0))[k % meter] += a;
  }
  const norm = (p) => { const m = Math.max(...p) || 1; return p.map((v) => r2(v / m)); };
  const avg = prof.map((v, i) => v / Math.max(1, cnt[i])), p = norm(avg), order = [...p.keys()].sort((a, b) => p[b] - p[a]);
  const confidence = r2(1 - p[order[1]]);
  return { beatIndex: order[0], time: r3(g.grid0 + order[0] * P), confidence, ambiguous: confidence < 0.15, profile: p,
    bySegment: segs.map((s, i) => ({ t0: r2(i * segLen), t1: r2(Math.min(duration, (i + 1) * segLen)), strongest: s.indexOf(Math.max(...s)), profile: norm(s) })) };
}

// librosa.util.peak_pick on an envelope (window sizes in frames).
function peakPick(x, { preMax, postMax, preAvg, postAvg, delta, wait }) {
  const out = []; let last = -Infinity;
  for (let n = 0; n < x.length; n++) {
    let mx = -Infinity; for (let i = Math.max(0, n - preMax); i < Math.min(x.length, n + postMax); i++) mx = Math.max(mx, x[i]);
    if (x[n] !== mx) continue;
    let s = 0, c = 0; for (let i = Math.max(0, n - preAvg); i < Math.min(x.length, n + postAvg); i++) { s += x[i]; c++; }
    if (x[n] < s / c + delta) continue;
    if (n - last > wait) { out.push(n); last = n; }
  }
  return out;
}

export function onsetsAndHits(E, g, { hitFloor = 0.33 } = {}) {
  const { env, fr } = E; let mx = 0, mn = Infinity; for (const v of env) { mx = Math.max(mx, v); mn = Math.min(mn, v); }
  const norm = Float32Array.from(env, (v) => (v - mn) / Math.max(1e-9, mx - mn)), f = (s) => Math.max(1, Math.floor(s * fr));
  const pos = (t) => (g ? r2((t - g.grid0) / g.beat) : null);
  const onGrid = (t) => {
    if (!g) return null; const b = (t - g.grid0) / g.beat, e8 = Math.round(b * 2) / 2, d = (b - e8) * g.beat;
    return Math.abs(d) <= 0.025 ? (Number.isInteger(e8) ? 'beat' : '8th') : null;
  };
  // Onsets: librosa.onset.onset_detect defaults (normalised envelope, delta 0.07).
  const onsets = peakPick(norm, { preMax: f(0.03), postMax: 1, preAvg: f(0.1), postAvg: f(0.1) + 1, delta: 0.07, wait: f(0.03) })
    .map((n) => ({ t: r3(n / fr), s: r2(norm[n]), beat: pos(n / fr) }));
  // Hits: sparse strong transients (+-116 ms peaks above the local mean + 0.5 sd, >= 0.33 of the max).
  const sd = Math.sqrt(meanOf(Array.from(env, (v) => v * v)) - meanOf(env) ** 2);
  const hits = peakPick(env, { preMax: f(0.116), postMax: f(0.116), preAvg: f(0.232), postAvg: f(0.232), delta: 0.5 * sd, wait: f(0.116) })
    .filter((n) => env[n] / mx >= hitFloor).map((n) => ({ t: r3(n / fr), s: r2(env[n] / mx), beat: pos(n / fr), on: onGrid(n / fr) }));
  return { onsets, hits };
}

// Loudness arc: RMS on 46 ms hops, normalised, averaged per second.
export function rmsArc(x, sr = SR) {
  const hop = Math.round(sr * 0.046), env = [];
  for (let i = 0; i + hop <= x.length; i += hop) { let s = 0; for (let j = i; j < i + hop; j++) s += x[j] * x[j]; env.push(Math.sqrt(s / hop)); }
  const mx = Math.max(...env, 1e-9), step = Math.max(1, Math.round(sr / hop)), out = [], db = [];
  for (let i = 0; i < env.length; i += step) {
    const w = env.slice(i, i + step), m = w.reduce((a, b) => a + b, 0) / w.length; out.push(r2(m / mx));
    const p = w.reduce((a, b) => a + b * b, 0) / w.length; db.push(r2(p > 0 ? 10 * Math.log10(p) : -90));
  }
  return { normalised: out, dbfs: db };
}

// ------------------------------------------------------------------ optional Python extras
export function pythonFor(argvPython) {
  const cands = [argvPython, process.env.FB_PYTHON, 'python3', 'python'].filter(Boolean);
  for (const c of cands) { const r = spawnSync(c, ['-c', 'import sys; print(sys.version.split()[0])'], { encoding: 'utf8' }); if (!r.error && r.status === 0) return c; }
  return null;
}
export function hasModule(py, mod) {
  if (!py) return false;
  const r = spawnSync(py, ['-c', `import ${mod}`], { encoding: 'utf8', timeout: 60000 });
  return !r.error && r.status === 0;
}

export async function transcribe(py, wav, { model = process.env.FB_WHISPER_MODEL || 'small.en' } = {}) {
  const r = await runAsync(py, [path.join(LIB, 'whisper_words.py'), wav, model], { allowFail: true });
  if (r.code !== 0) return { skipped: `faster-whisper failed: ${r.stderr.trim().split('\n').slice(-2).join(' ').slice(0, 300)}` };
  const j = JSON.parse(r.stdout);
  return { model, language: j.language, words: j.words.map((w) => ({ w: w.w.trim(), s: r2(w.s), e: r2(w.e), p: r2(w.p) })), segments: j.segments };
}

// ------------------------------------------------------------------ everything, for one track
export async function analyzeTrack(file, { cache, vo = true, python, whisperModel, bpmHint, minBpm, maxBpm } = {}) {
  const notes = [], timings = {};
  let t = performance.now();
  const py = pythonFor(python);
  const wantVo = vo && py && hasModule(py, 'faster_whisper');
  if (vo && !wantVo) notes.push(py ? `voice-over words skipped: faster_whisper is not importable by ${py} (pip install faster-whisper, or pass --python <venv python>)` : 'voice-over words skipped: no python3');
  // faster-whisper decodes the source itself (PyAV, resampled to 16 kHz mono); a WAV that ffmpeg
  // resampled first can change what it hears enough to drop a phrase.
  const voP = wantVo ? transcribe(py, file, { model: whisperModel }) : null;
  const A = await decodeAudio(file, { cache });
  timings.decode = r2((performance.now() - t) / 1000); t = performance.now();
  const hop = A.duration > 240 ? 256 : 128;
  const E = onsetEnvelopes(A.x, A.sr, { hop });
  timings.envelope = r2((performance.now() - t) / 1000); t = performance.now();
  const grid = fitGrid(E, A.duration, { bpmHint, minBpm, maxBpm });
  const drift = grid ? gridDrift(E, grid, A.duration) : null;
  const down = grid ? downbeats(E, grid, A.duration) : null;
  const { onsets, hits } = onsetsAndHits(E, grid);
  const rms = rmsArc(A.x, A.sr);
  timings.analysis = r2((performance.now() - t) / 1000); t = performance.now();
  let words = null;
  if (voP) { words = await voP; timings.vo = r2((performance.now() - t) / 1000); if (words.skipped) notes.push(words.skipped); }
  return { duration: r3(A.duration), sampleRate: A.sr, envelope: { hop, fps: r2(E.fr), convention: 'librosa onset_strength (n_fft 2048, 128 mel, lag 1, centred)' },
    tempo: grid, drift, downbeat: down, onsets, hits, loudness: { ...(A.loudness || {}), rms },
    vo: words && !words.skipped ? words : { skipped: words?.skipped || notes.find((n) => n.startsWith('voice-over')) || 'not requested' },
    notes, timings, E };
}

// The block a composition's timeline.js pastes in: the timing constants every scene imports.
export function timelineBlock(a, { dur } = {}) {
  const g = a.tempo;
  const out = { BPM: g ? g.bpm : null, BEAT: g ? g.beat : null, GRID0: g ? g.grid0 : null, DOWNBEAT: a.downbeat ? a.downbeat.beatIndex : null,
    DUR: dur ?? a.duration, HITS: a.hits.map((h) => [h.t, h.s]) };
  if (a.vo && a.vo.words) out.VO = a.vo.words.map((w) => [w.s, w.w]);
  return out;
}

export function timelineJs(T, { cuts } = {}) {
  const L = ['// Measured by film-breakdown (analyze-audio.mjs). Seconds on the source clock.'];
  if (T.FPS) L.push(`export const FPS = ${T.FPS}; // render with --fps ${T.FPS}`);
  L.push(`export const DUR = ${T.DUR};`);
  if (T.BPM) {
    L.push(`export const BPM = ${T.BPM};`, `export const BEAT = ${T.BEAT}; // 60 / BPM`, `export const GRID0 = ${T.GRID0}; // first beat`,
      `export const beat = (k) => GRID0 + k * BEAT;`);
    if (T.DOWNBEAT != null) L.push(`export const DOWNBEAT = ${T.DOWNBEAT}; // beats k with k % 4 === DOWNBEAT start a bar`);
  }
  if (cuts) L.push(`export const CUT_FRAMES = ${JSON.stringify(cuts)}; // first frame of each new shot`);
  L.push(`export const HITS = ${JSON.stringify(T.HITS)}; // [seconds, strength 0..1]`);
  if (T.VO) L.push(`export const VO = ${JSON.stringify(T.VO)}; // [start, word]`);
  return L.join('\n') + '\n';
}
