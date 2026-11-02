#!/usr/bin/env node
// img.mjs: the image menu in code (sharp). Chainable ops applied left to right, each to the result of
// the one before.
//
//   node img.mjs <input> <output> [ops...] [--tokens <tokens.json>]
//   node img.mjs <input> --info
//
// Colours are `#rrggbb` or a brand token name (`--brand-color-paper`), resolved from the active brand
// pack (/workspace/brand/tokens.json, or --tokens). sharp resolves from the pinned render toolchain
// (DESIGN_AGENT_RENDER_DIR, default /opt/design-agent/render), never from a copy in the workspace.
//
// Prints one JSON line: {"ok":true,"output","format","width","height","bytes"} or, with --info,
// {"format","width","height","channels","hasAlpha","space","pages","bytes"}.
// Exit: 0 done · 1 sharp could not process this input with these ops · 2 bad arguments, a missing
// file, an unknown token, or the render toolchain is unavailable.
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';

const RENDER_DIR = process.env.DESIGN_AGENT_RENDER_DIR || '/opt/design-agent/render';
const DEFAULT_TOKENS = '/workspace/brand/tokens.json';

class UsageError extends Error {}

const HELP = `image-ops: process, edit, resize or convert an image (sharp)
Usage: node img.mjs <input> <output> [ops...] [--tokens tokens.json]   |   node img.mjs <input> --info

Ops (applied strictly left to right, each on the result of the one before):
  --resize WxH[:fit]      W or H optional (800x, x600); fit=cover|contain|fill|inside|outside (default inside)
  --crop L,T,W,H          extract a region
  --rotate DEG            0 = auto-orient from EXIF
  --flip | --flop         flip vertical | horizontal
  --extend T,R,B,L[:col]  pad with a colour (default transparent)
  --modulate b,s,h        brightness,saturation,hue, e.g. 1.1,1.3,20 (a field may be blank)
  --tint COL              tint / duotone base     --greyscale  --negate  --gamma G
  --blur SIGMA  --sharpen [SIGMA]  --trim  --flatten COL (drop alpha over a colour)
  --composite FILE@L,T[:blend]   overlay an image (repeatable; blend=over|multiply|screen|overlay|...)
  --to png|jpeg|webp|avif|tiff   --quality N (jpeg/webp/avif)
  --pipe '[["method",arg,...],...]'   a raw sharp chain (allowlisted methods only)
COL is #rrggbb or a brand token such as --brand-color-ink.`;

// --pipe dispatches by name on a sharp instance, restricted to sharp's own image operations: no eval,
// no dynamic import, and a name outside this set is refused.
const PIPE_ALLOW = new Set([
  'resize', 'extract', 'rotate', 'flip', 'flop', 'extend', 'modulate', 'tint', 'greyscale', 'grayscale',
  'negate', 'gamma', 'blur', 'sharpen', 'median', 'trim', 'flatten', 'composite', 'linear', 'normalise',
  'normalize', 'threshold', 'clahe', 'toColourspace', 'toColorspace', 'ensureAlpha', 'removeAlpha',
  'withMetadata', 'png', 'jpeg', 'webp', 'avif', 'tiff', 'affine',
]);
const FORMATS = { jpg: 'jpeg', jpeg: 'jpeg', png: 'png', webp: 'webp', avif: 'avif', tiff: 'tiff', tif: 'tiff' };

function loadSharp() {
  try {
    return createRequire(path.join(RENDER_DIR, 'package.json'))('sharp');
  } catch (error) {
    throw new UsageError(`sharp is not installed in ${RENDER_DIR} (${error.code || error.message}); run inside the sandbox or set DESIGN_AGENT_RENDER_DIR`);
  }
}

function brandColours(tokensPath) {
  let tokens;
  try {
    tokens = JSON.parse(fs.readFileSync(tokensPath, 'utf8'));
  } catch (error) {
    throw new UsageError(`cannot read brand tokens ${tokensPath} (${error.code || error.message})`);
  }
  return tokens?.design?.tokens || {};
}

function colourResolver(tokensPath) {
  let table = null;
  return (spec) => {
    let hex = String(spec || '');
    if (hex.startsWith('--brand-')) {
      table ??= brandColours(tokensPath);
      if (!(hex in table)) throw new UsageError(`unknown brand token ${hex} in ${tokensPath}`);
      hex = String(table[hex]).trim();
    }
    const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex);
    if (!m) throw new UsageError(`not a colour: ${spec} (use #rrggbb or a --brand-color-* token)`);
    const h = m[1].length === 3 ? [...m[1]].map((c) => c + c).join('') : m[1];
    return { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16) };
  };
}

const num = (s) => (s === '' || s == null ? undefined : Number(s));
const ints = (s, n, label) => {
  const parts = String(s || '').split(',').map(Number);
  if (parts.length !== n || parts.some((x) => !Number.isFinite(x))) throw new UsageError(`${label} needs ${n} comma-separated numbers, got "${s}"`);
  return parts;
};

async function main(argv) {
  const at = argv.indexOf('--tokens');
  const tokensPath = at >= 0 ? argv[at + 1] : DEFAULT_TOKENS;
  if (at >= 0) {
    if (!tokensPath) throw new UsageError('--tokens needs a path');
    argv = [...argv.slice(0, at), ...argv.slice(at + 2)];
  }
  const [input, output, ...ops] = argv;
  if (!input || input === '-h' || input === '--help') {
    console.log(HELP);
    return input ? 0 : 2;
  }
  if (!fs.existsSync(input)) throw new UsageError(`input not found: ${input}`);
  const sharp = loadSharp();
  const colour = colourResolver(tokensPath);

  if (output === '--info' || ops.includes('--info')) {
    const m = await sharp(input, { failOn: 'none' }).metadata();
    console.log(JSON.stringify({ format: m.format, width: m.width, height: m.pageHeight || m.height, channels: m.channels,
      hasAlpha: !!m.hasAlpha, space: m.space, pages: m.pages || 1, bytes: fs.statSync(input).size }));
    return 0;
  }
  if (!output || output.startsWith('--')) throw new UsageError('need <output> (or --info)');

  const steps = [];
  const step = (fn) => steps.push(fn);
  let toFmt = null;
  let quality = null;
  for (let i = 0; i < ops.length; i++) {
    const op = ops[i];
    const v = () => {
      const value = ops[++i];
      if (value === undefined) throw new UsageError(`${op} needs a value`);
      return value;
    };
    switch (op) {
      case '--resize': {
        const [wh, fit] = v().split(':');
        const [w, h] = wh.split('x');
        if (!num(w) && !num(h)) throw new UsageError(`--resize needs WxH, Wx or xH, got "${wh}"`);
        step((q) => q.resize({ width: num(w) || null, height: num(h) || null, fit: fit || 'inside' }));
        break;
      }
      case '--crop': case '--extract': {
        const [left, top, width, height] = ints(v(), 4, op);
        step((q) => q.extract({ left, top, width, height }));
        break;
      }
      case '--rotate': { const degrees = Number(v()); step((q) => q.rotate(degrees)); break; }
      case '--flip': step((q) => q.flip()); break;
      case '--flop': step((q) => q.flop()); break;
      case '--extend': {
        const [spec, col] = v().split(':');
        const [top, right, bottom, left] = ints(spec, 4, op);
        step((q) => q.extend({ top, right, bottom, left, background: col ? colour(col) : { r: 0, g: 0, b: 0, alpha: 0 } }));
        break;
      }
      case '--modulate': {
        const [b, s, h] = v().split(',');
        step((q) => q.modulate({ brightness: num(b), saturation: num(s), hue: num(h) }));
        break;
      }
      case '--tint': { const rgb = colour(v()); step((q) => q.tint(rgb)); break; }
      case '--greyscale': case '--grayscale': step((q) => q.greyscale()); break;
      case '--negate': step((q) => q.negate()); break;
      case '--gamma': { const g = Number(v()); step((q) => q.gamma(g)); break; }
      case '--blur': { const sigma = Number(v()); step((q) => q.blur(sigma)); break; }
      case '--sharpen': {
        const next = ops[i + 1];
        const sigma = next && !next.startsWith('--') ? Number(v()) : 1;
        step((q) => q.sharpen({ sigma }));
        break;
      }
      case '--trim': step((q) => q.trim()); break;
      case '--flatten': { const background = colour(v()); step((q) => q.flatten({ background })); break; }
      case '--composite': {
        const [file, rest] = v().split('@');
        if (!fs.existsSync(file)) throw new UsageError(`composite input not found: ${file}`);
        const [pos, blend] = (rest || '0,0').split(':');
        const [left, top] = ints(pos, 2, '--composite position');
        step((q) => q.composite([{ input: file, left, top, blend: blend || 'over' }]));
        break;
      }
      case '--to': case '--format': toFmt = FORMATS[v().toLowerCase()] || null; if (!toFmt) throw new UsageError(`unknown format ${ops[i]}`); break;
      case '--quality': quality = Number(v()); break;
      case '--pipe': {
        let chain;
        try {
          chain = JSON.parse(v());
        } catch (error) {
          throw new UsageError(`--pipe is not JSON: ${error.message}`);
        }
        for (const [method] of chain) if (!PIPE_ALLOW.has(method)) throw new UsageError(`--pipe method not allowed: ${method}`);
        step((q) => chain.reduce((acc, [method, ...args]) => acc[method](...args), q));
        break;
      }
      default: throw new UsageError(`unknown op: ${op}`);
    }
  }
  // sharp runs one pipeline's operations in its own fixed order (extend before a post-resize extract,
  // composite after resize), so each op runs on the settled result of the one before: left to right.
  let p = sharp(input, { failOn: 'none', animated: false });
  try {
    for (const [index, fn] of steps.entries()) {
      p = fn(p);
      if (index < steps.length - 1) {
        const { data, info } = await p.raw().toBuffer({ resolveWithObject: true });
        p = sharp(data, { raw: { width: info.width, height: info.height, channels: info.channels } });
      }
    }
  } catch (error) {
    console.error(`image-ops: ${error.message}`);
    return 1;
  }
  const ext = path.extname(output).slice(1).toLowerCase();
  const fmt = toFmt || FORMATS[ext];
  if (fmt && (toFmt || quality != null)) p = p[fmt](quality != null ? { quality } : {});
  fs.mkdirSync(path.dirname(path.resolve(output)), { recursive: true });
  let info;
  try {
    info = await p.toFile(output);
  } catch (error) {
    console.error(`image-ops: ${error.message}`);
    return 1;
  }
  console.log(JSON.stringify({ ok: true, output, format: info.format, width: info.width, height: info.height, bytes: info.size || fs.statSync(output).size }));
  return 0;
}

main(process.argv.slice(2)).then(
  (code) => { process.exitCode = code; },
  (error) => {
    console.error(`image-ops: ${error.message}`);
    process.exitCode = error instanceof UsageError ? 2 : 1;
  },
);
