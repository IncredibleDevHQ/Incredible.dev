// ffmpeg/ffprobe helpers shared by the film-breakdown scripts: probing (rational fps), frame-exact
// extraction, labelled contact sheets. Node 22 and ffmpeg only; no npm dependencies.
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs'; import path from 'node:path'; import os from 'node:os';
import { fileURLToPath } from 'node:url';

export const LIB = path.dirname(fileURLToPath(import.meta.url));
export const SKILL = path.resolve(LIB, '..', '..');
export const MAX_EDGE = 1500; // review images: the model's image input is clamped to a 1500 px long edge

// ------------------------------------------------------------------ processes
export function sh(cmd, args, { cwd, input, allowFail = false, maxBuffer = 1 << 28 } = {}) {
  const r = spawnSync(cmd, args, { cwd, input, encoding: 'utf8', maxBuffer });
  if (r.error) throw new Error(`${cmd}: ${r.error.message}`);
  if (r.status !== 0 && !allowFail) throw new Error(`${cmd} failed (${r.status}): ${(r.stderr || r.stdout || '').trim().slice(-1500)}`);
  return r;
}

// Async spawn; resolves { code, stdout, stderr }. onStdout(chunk) streams stdout instead of buffering it.
export function runAsync(cmd, args, { cwd, onStdout, allowFail = false, env } = {}) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { cwd, env: env || process.env, stdio: ['ignore', 'pipe', 'pipe'] });
    const out = []; let err = '';
    p.stdout.on('data', (d) => (onStdout ? onStdout(d) : out.push(d)));
    p.stderr.on('data', (d) => { err += d; if (err.length > 200000) err = err.slice(-100000); });
    p.on('error', (e) => reject(new Error(`${cmd}: ${e.message}`)));
    p.on('close', (code) => {
      const res = { code, stdout: onStdout ? '' : Buffer.concat(out).toString('utf8'), stderr: err };
      if (code !== 0 && !allowFail) reject(new Error(`${cmd} failed (${code}): ${err.trim().slice(-1500)}`));
      else resolve(res);
    });
  });
}

export async function pool(items, limit, fn) {
  const results = new Array(items.length); let next = 0;
  const worker = async () => { while (next < items.length) { const i = next++; results[i] = await fn(items[i], i); } };
  await Promise.all(Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, worker));
  return results;
}

export const cpus = () => (os.availableParallelism ? os.availableParallelism() : os.cpus().length);
export const now = () => performance.now() / 1000;

// ------------------------------------------------------------------ ffmpeg capabilities
let caps = null;
export function ffmpegCaps() {
  if (caps) return caps;
  const r = spawnSync('ffmpeg', ['-hide_banner', '-version'], { encoding: 'utf8' });
  if (r.error || r.status !== 0) throw new Error('ffmpeg not found on PATH');
  const m = /ffmpeg version n?(\d+)\.(\d+)/.exec(r.stdout || '');
  const [maj, min] = m ? [+m[1], +m[2]] : [99, 0]; // git builds ("N-12345-g...") are recent
  caps = { version: m ? `${maj}.${min}` : 'git', fpsMode: maj > 5 || (maj === 5 && min >= 1) ? '-fps_mode' : '-vsync' };
  return caps;
}
// Pass frames through exactly as selected (no duplication or dropping by the muxer).
export const passthrough = () => [ffmpegCaps().fpsMode, 'passthrough'];

// ------------------------------------------------------------------ probing and frame math
export function parseRate(s) {
  if (s == null) return null;
  const m = /^(\d+)(?:\/(\d+))?$/.exec(String(s).trim());
  if (!m) { const v = +s; return v > 0 ? { num: v, den: 1, value: v, str: String(v) } : null; }
  const num = +m[1], den = m[2] ? +m[2] : 1;
  if (!num || !den) return null;
  return { num, den, value: num / den, str: den === 1 ? String(num) : `${num}/${den}` };
}

export function probe(file) {
  if (!fs.existsSync(file)) throw new Error(`not found: ${file}`);
  const r = sh('ffprobe', ['-v', 'error', '-show_entries',
    'stream=index,codec_type,codec_name,width,height,pix_fmt,r_frame_rate,avg_frame_rate,nb_frames,duration,start_time,sample_rate,channels,color_space,color_range:stream_side_data=rotation:stream_tags=rotate:format=duration,start_time,size,bit_rate,format_name',
    '-of', 'json', file]);
  const j = JSON.parse(r.stdout);
  const fmt = j.format || {};
  const vs = (j.streams || []).find((s) => s.codec_type === 'video' && s.width > 0);
  const as = (j.streams || []).find((s) => s.codec_type === 'audio');
  const out = { path: path.resolve(file), container: fmt.format_name, size: +fmt.size || null, bitRate: +fmt.bit_rate || null,
    duration: +fmt.duration || null, start: +fmt.start_time || 0, video: null, audio: null };
  if (vs) {
    const r = parseRate(vs.r_frame_rate), a = parseRate(vs.avg_frame_rate);
    // r_frame_rate is the stream's base rate; avg differs for variable-rate sources (screen and phone recordings).
    const vfr = !!(r && a && Math.abs(r.value - a.value) / a.value > 0.01);
    const fps = vfr ? a : (r || a);
    let rotation = 0;
    for (const sd of vs.side_data_list || []) if (sd.rotation != null) rotation = +sd.rotation;
    if (vs.tags && vs.tags.rotate) rotation = +vs.tags.rotate;
    const duration = +vs.duration || out.duration;
    out.video = { index: vs.index, codec: vs.codec_name, width: vs.width, height: vs.height, pixFmt: vs.pix_fmt,
      fps: fps ? fps.str : null, fpsValue: fps ? fps.value : null, num: fps ? fps.num : null, den: fps ? fps.den : null,
      rFrameRate: vs.r_frame_rate, avgFrameRate: vs.avg_frame_rate, vfr, nbFrames: +vs.nb_frames || null,
      duration, start: +vs.start_time || 0, colorSpace: vs.color_space || null, colorRange: vs.color_range || null, rotation };
    if (!out.video.nbFrames && fps && duration) out.video.nbFrames = Math.round(duration * fps.value);
  }
  if (as) out.audio = { index: as.index, codec: as.codec_name, sampleRate: +as.sample_rate, channels: +as.channels, duration: +as.duration || out.duration };
  return out;
}

// Frame n is displayed at n * den / num seconds (film time: zero at the first video frame).
export const timeOf = (n, v) => (n * v.den) / v.num;
export const frameAt = (t, v) => Math.max(0, Math.round((t * v.num) / v.den));
export const fmtT = (t, d = 2) => (t == null || !isFinite(t) ? '-' : (+t).toFixed(d));
export const r3 = (x) => Math.round(x * 1000) / 1000;
export const r2 = (x) => Math.round(x * 100) / 100;

// YUV->RGB with the matrix the file declares (HD defaults to BT.709), so every ffmpeg version samples
// the same colours: older builds otherwise assume BT.601 for untagged frames.
export function rgbScale(v, w, h, flags = 'area') {
  const cs = String(v.colorSpace || '').toLowerCase();
  const m = cs.includes('709') ? 'bt709' : cs.includes('2020') ? 'bt2020' : cs.includes('601') || cs.includes('170') || cs.includes('470') ? 'bt601'
    : v.height >= 720 ? 'bt709' : 'bt601';
  const range = v.colorRange === 'pc' ? 'pc' : 'tv';
  const yuv = /^yuv|^nv|^p0|^y2|^uyvy|^yuyv/.test(v.pixFmt || 'yuv');
  return `scale=${w}:${h}:flags=${flags}${yuv ? `:in_color_matrix=${m}:in_range=${range}` : ''}`;
}

// Sizes that keep the display aspect (rotation-aware) with a given long edge, even dimensions.
export function fitDims(v, long) {
  let w = v.width, h = v.height;
  if (Math.abs(v.rotation) % 180 === 90) [w, h] = [h, w];
  const k = long / Math.max(w, h);
  const ev = (x) => Math.max(2, 2 * Math.round((x * k) / 2));
  return w >= h ? [long, ev(h)] : [ev(w), long];
}

// ------------------------------------------------------------------ label font
let fontCache;
export function labelFont(cacheDir) {
  if (fontCache !== undefined) return fontCache;
  const cands = [process.env.FB_FONT,
    '/usr/local/share/fonts/design-agent/IBMPlexMono-Medium.ttf',
    path.resolve(SKILL, '../../fonts/IBMPlexMono-Medium.ttf'), '/workspace/fonts/IBMPlexMono-Medium.ttf',
    path.resolve(SKILL, '../../fonts/IBMPlexMono-Regular.ttf'),
    '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf',
    '/System/Library/Fonts/Menlo.ttc', '/System/Library/Fonts/Monaco.ttf', '/Library/Fonts/Arial.ttf'].filter(Boolean);
  let f = cands.find((c) => { try { return fs.statSync(c).isFile(); } catch { return false; } }) || null;
  if (f && !/^[\w./-]+$/.test(f) && cacheDir) { // a path the filtergraph would need escaping for
    const dst = path.join(cacheDir, `label-font${path.extname(f)}`);
    fs.copyFileSync(f, dst); f = dst;
  }
  fontCache = f;
  return f;
}

// drawtext for a static label. In some ffmpeg builds `text=` must come first, so it always does.
export function drawLabel(text, { size = 14, color = 'white', x = 4, y = 4, box = 'black@0.62', font } = {}) {
  const safe = String(text).replace(/[^A-Za-z0-9 .+\-#/()=_<>|~]/g, ' ');
  const face = font ? `fontfile=${font}` : 'font=monospace';
  return `drawtext=text='${safe}':${face}:fontsize=${size}:fontcolor=${color}:box=1:boxcolor=${box}:boxborderw=3:x=${x}:y=${y}`;
}

// ------------------------------------------------------------------ frame-exact extraction
let extractCalls = 0;
// Extracts frames (indices on the file's own rational frame grid) with one decode per cluster of
// nearby frames: seek just before the cluster, keep original timestamps, select each frame by the
// half-frame window around its nominal presentation time. Returns [{ n, t, file }].
export async function extractFrames(file, v, frames, {
  dir, name = (n, t) => `t${fmtT(t, 3).padStart(7, '0')}_f${String(n).padStart(5, '0')}`, long = 0, fmt = 'png', q = 2,
  concurrency = Math.max(2, Math.min(6, Math.floor(cpus() / 2))), gap = 2.5, filter = '',
} = {}) {
  fs.mkdirSync(dir, { recursive: true });
  const last = Math.max(0, (v.nbFrames || Infinity) - 1);
  const uniq = [...new Set(frames.map((n) => Math.min(last, Math.max(0, Math.round(n)))))].sort((a, b) => a - b);
  const groups = [];
  for (const n of uniq) {
    const g = groups[groups.length - 1];
    if (g && timeOf(n - g[g.length - 1], v) <= gap && g.length < 60) g.push(n); else groups.push([n]);
  }
  // Always through RGB with the declared matrix; a JPEG is then re-encoded as BT.601 full range,
  // which is what every JPEG decoder assumes, so colours sampled from either format agree.
  const ext = fmt === 'jpg' ? 'jpg' : 'png';
  const [W, H] = fitDims(v, long || Math.max(v.width, v.height));
  const scale = `${rgbScale(v, W, H, 'lanczos')},format=rgb24,`;
  const pix = ext === 'jpg' ? 'format=yuvj444p' : 'format=rgb24';
  if (filter && !filter.endsWith(',')) filter += ',';
  const results = [], call = ++extractCalls;
  await pool(groups, concurrency, async (g, gi) => {
    const t0 = timeOf(g[0], v), t1 = timeOf(g[g.length - 1], v);
    const ss = Math.max(0, t0 - 0.25);
    const win = (n) => { const c = v.start + timeOf(n, v), h = 0.5 * timeOf(1, v); return `between(t,${(c - h).toFixed(6)},${(c + h - 1e-6).toFixed(6)})`; };
    const tmp = path.join(dir, `.grab-${process.pid}-${call}-${gi}`);
    fs.mkdirSync(tmp, { recursive: true });
    const args = ['-hide_banner', '-nostats', '-loglevel', 'error', '-ss', ss.toFixed(6), '-t', (t1 - ss + 0.6).toFixed(6), '-copyts',
      '-i', file, '-map', `0:${v.index}`, '-vf', `select='${g.map(win).join('+')}',${scale}${filter}${pix}`, ...passthrough(),
      ...(ext === 'jpg' ? ['-q:v', String(q)] : []), '-y', path.join(tmp, `%04d.${ext}`)];
    await runAsync('ffmpeg', args);
    const got = fs.readdirSync(tmp).filter((f) => f.endsWith(`.${ext}`)).sort();
    if (got.length !== g.length) { // variable-rate or odd timestamps: fall back to one seek per frame
      for (const f of got) fs.rmSync(path.join(tmp, f));
      for (const n of g) {
        const c = v.start + timeOf(n, v) - 0.5 * timeOf(1, v);
        await runAsync('ffmpeg', ['-hide_banner', '-nostats', '-loglevel', 'error', '-ss', Math.max(0, timeOf(n, v) - 0.25).toFixed(6), '-copyts', '-i', file,
          '-map', `0:${v.index}`, '-vf', `select='gte(t,${c.toFixed(6)})',${scale}${filter}${pix}`, '-frames:v', '1', ...passthrough(),
          ...(ext === 'jpg' ? ['-q:v', String(q)] : []), path.join(tmp, `x${String(n).padStart(6, '0')}.${ext}`)]);
      }
    }
    const files = fs.readdirSync(tmp).filter((f) => f.endsWith(`.${ext}`)).sort();
    files.forEach((f, i) => {
      const n = g[i]; if (n == null) return;
      const t = timeOf(n, v), out = path.join(dir, `${name(n, t)}.${ext}`);
      fs.renameSync(path.join(tmp, f), out); results.push({ n, t: r3(t), file: out });
    });
    fs.rmSync(tmp, { recursive: true, force: true });
  });
  return results.sort((a, b) => a.n - b.n);
}

// ------------------------------------------------------------------ contact sheets
// Grid layout for n tiles of aspect w/h that fits a maxEdge square (review clamp).
export function sheetLayout(n, aspect, { maxEdge = MAX_EDGE, pad = 4, cols: want, maxRows = 99 } = {}) {
  let best = null;
  const colsList = want ? [want] : Array.from({ length: 12 }, (_, i) => i + 1);
  for (const cols of colsList) {
    const tileW = Math.floor((maxEdge - (cols + 1) * pad) / cols / 2) * 2;
    const tileH = Math.round(tileW / aspect / 2) * 2;
    if (tileW < 64) continue;
    const rowsFit = Math.max(1, Math.min(maxRows, Math.floor((maxEdge - pad) / (tileH + pad))));
    const rows = Math.min(rowsFit, Math.ceil(n / cols));
    const per = cols * rows, sheets = Math.ceil(n / per);
    const score = tileW * tileH * Math.min(n, per) / sheets ** 1.5; // big tiles, few sheets
    if (!best || score > best.score) best = { cols, rows, tileW, tileH, per, sheets, score, pad };
  }
  return best;
}

// tiles: [{ file, label, mark: 'cut' | 'pre' | 'hit' | undefined, color }]. One ffmpeg call per sheet.
export async function makeSheet(tiles, out, { cols, tileW, tileH, pad = 4, bg = '0x1A1D24', font, labelSize } = {}) {
  const n = tiles.length; if (!n) return null;
  const size = labelSize || Math.max(11, Math.min(18, Math.round(tileW / 17)));
  const inputs = [], chains = [], layout = [];
  tiles.forEach((tile, i) => {
    inputs.push('-i', tile.file);
    const border = tile.mark === 'cut' ? `,drawbox=x=0:y=0:w=iw:h=ih:color=0xFF3B30:t=${Math.max(3, Math.round(tileW / 60))}`
      : tile.mark === 'pre' ? `,drawbox=x=0:y=0:w=iw:h=ih:color=0xFF9F0A:t=${Math.max(2, Math.round(tileW / 90))}`
      : tile.mark === 'hit' ? `,drawbox=x=0:y=0:w=iw:h=ih:color=0x64D2FF:t=2` : '';
    const color = tile.color || (tile.mark === 'cut' ? '0xFFD60A' : 'white');
    chains.push(`[${i}:v]scale=${tileW}:${tileH}:force_original_aspect_ratio=decrease:flags=lanczos,pad=${tileW}:${tileH}:(ow-iw)/2:(oh-ih)/2:color=${bg},format=rgb24${border},${drawLabel(tile.label, { size, color, font })}[v${i}]`);
    layout.push(`${pad + (i % cols) * (tileW + pad)}_${pad + Math.floor(i / cols) * (tileH + pad)}`);
  });
  const rows = Math.ceil(n / cols);
  const W = pad + cols * (tileW + pad), H = pad + rows * (tileH + pad);
  const graph = n === 1 ? `${chains[0]};[v0]pad=${W}:${H}:${pad}:${pad}:color=${bg}[o]`
    : `${chains.join(';')};${tiles.map((_, i) => `[v${i}]`).join('')}xstack=inputs=${n}:layout=${layout.join('|')}:fill=${bg},pad=${W}:${H}:0:0:color=${bg}[o]`;
  fs.mkdirSync(path.dirname(out), { recursive: true });
  await runAsync('ffmpeg', ['-hide_banner', '-nostats', '-loglevel', 'error', '-y', ...inputs, '-filter_complex', graph, '-map', '[o]', '-frames:v', '1',
    ...(out.endsWith('.jpg') ? ['-q:v', '3'] : []), out]);
  return out;
}

// Lays tiles out over as many sheets as needed; names out(k) -> path. Returns the sheet paths.
export async function makeSheets(tiles, outFn, aspect, opts = {}) {
  if (!tiles.length) return [];
  const L = sheetLayout(tiles.length, aspect, opts);
  const jobs = [];
  for (let k = 0; k * L.per < tiles.length; k++) jobs.push([tiles.slice(k * L.per, (k + 1) * L.per), outFn(k + 1, Math.ceil(tiles.length / L.per))]);
  return pool(jobs, opts.concurrency || 4, ([t, o]) => makeSheet(t, o, { ...L, font: opts.font, bg: opts.bg }));
}

export function arg(argv, k, d) { const i = argv.indexOf(`--${k}`); return i >= 0 && argv[i + 1] != null && !argv[i + 1].startsWith('--') ? argv[i + 1] : d; }
export const flag = (argv, k) => argv.includes(`--${k}`);
export const positional = (argv, withValue = []) => {
  const out = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith('--')) { if (withValue.includes(argv[i].slice(2))) i++; continue; }
    out.push(argv[i]);
  }
  return out;
};
