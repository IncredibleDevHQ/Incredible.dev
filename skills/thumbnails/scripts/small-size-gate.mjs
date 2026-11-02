#!/usr/bin/env node
// small-size-gate.mjs — look at the thumbnail at the sizes a viewer actually gets. Nobody sees the
// full frame in a feed: youtube.com renders it about 375×210 full-bleed on a phone and about 215×121
// in the watch page's "up next" rail, its smallest standard desktop size (layouts drift; re-measure
// when it matters). This really resamples the delivered image down to both, re-upscales each
// nearest-neighbour so the loss stays visible, paints the player chrome (rounded corners, duration
// pill, progress bar) over the full-size tile, adds a grayscale pass, and writes ONE labelled sheet to
// read. It decides nothing; it shows what survives.
//
// Each tile sits on the feed ground it is judged against (#0f0f0f dark feed, #ffffff light feed), so
// a frame that dissolves into its card is visible on the sheet itself.
//
// Usage:
//   node /workspace/skills/thumbnails/scripts/small-size-gate.mjs projects/<slug>/renders/a.png [--out <dir>]
//
// Writes <stem>.smallsize-sheet.jpg next to the input (or into --out) and prints its path. Confined to
// the workspace (/workspace, or DESIGN_AGENT_WORKSPACE); sharp resolves from the pinned render
// toolchain (DESIGN_AGENT_RENDER_DIR). Exit 0 written · 2 bad arguments, an unreadable image or no
// toolchain.

import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";

const RENDER_DIR = process.env.DESIGN_AGENT_RENDER_DIR || "/opt/design-agent/render";
let sharp;
try {
  sharp = createRequire(path.join(RENDER_DIR, "package.json"))("sharp");
} catch (error) {
  console.error(`small-size-gate: sharp is not installed in ${RENDER_DIR} (${error.code || error.message})`);
  process.exit(2);
}

const WORKSPACE = path.resolve(process.env.DESIGN_AGENT_WORKSPACE || "/workspace");
const TILE = { width: 640, height: 360 }; // every tile is shown at one size so the loss is comparable
const PAD = 24; // feed ground visible around each tile — this is what edge separation is judged on
const LABEL = 26;
const GAP = 16;
// Platform chrome, not brand: the feed grounds a thumbnail is judged against.
const DARK_FEED = "#0f0f0f";
const LIGHT_FEED = "#ffffff";
const GRAY_CARD = "#7f7f7f";

const escapeXml = (text) =>
  text.replace(/[<>&"']/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&apos;" })[c]);

function confine(p) {
  const abs = path.resolve(p);
  if (abs !== WORKSPACE && !abs.startsWith(WORKSPACE + path.sep)) {
    throw new Error(`refusing path outside ${WORKSPACE}: ${p}`);
  }
  return abs;
}

// YouTube's own chrome, drawn rather than shipped as an overlay PNG so it scales with the tile:
// 12px rounded corners, the duration pill in the bottom-right, and the watched-progress bar.
function chromeSvg(width, height) {
  const radius = width * 0.009;
  const pill = { w: width * 0.088, h: height * 0.061, inset: width * 0.0125 };
  const bar = height * 0.014;
  return Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
  <path fill="${DARK_FEED}" fill-rule="evenodd" d="M0 0H${width}V${height}H0Z M${radius} 0 h${width - 2 * radius} a${radius} ${radius} 0 0 1 ${radius} ${radius} v${height - 2 * radius} a${radius} ${radius} 0 0 1 -${radius} ${radius} h-${width - 2 * radius} a${radius} ${radius} 0 0 1 -${radius} -${radius} v-${height - 2 * radius} a${radius} ${radius} 0 0 1 ${radius} -${radius} z"/>
  <rect x="0" y="${height - bar}" width="${width}" height="${bar}" fill="rgba(0,0,0,0.45)"/>
  <rect x="0" y="${height - bar}" width="${width * 0.38}" height="${bar}" fill="#ff0000"/>
  <rect x="${width - pill.inset - pill.w}" y="${height - pill.inset - pill.h - bar}" width="${pill.w}" height="${pill.h}" rx="${radius}" fill="rgba(0,0,0,0.8)"/>
  <text x="${width - pill.inset - pill.w / 2}" y="${height - pill.inset - pill.h / 2 - bar + pill.h * 0.32}" text-anchor="middle" font-family="sans-serif" font-size="${pill.h * 0.62}" fill="#ffffff">12:34</text>
</svg>`);
}

function labelSvg(width, height, text) {
  return Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
  <text x="0" y="${height - 8}" font-family="sans-serif" font-size="15" fill="${LIGHT_FEED}">${escapeXml(text)}</text>
</svg>`);
}

// One tile: resample to the real feed size, then nearest-neighbour back up so the judge sees exactly
// the detail that survived — a lanczos upscale would quietly re-smooth the loss away.
async function tile(src, { width, height, grayscale = false, chrome = false }) {
  let pipeline = sharp(src).resize(width, height, { fit: "fill", kernel: "lanczos3" });
  if (grayscale) pipeline = pipeline.greyscale();
  const shrunk = await pipeline.toBuffer();
  const upscaled = sharp(shrunk).resize(TILE.width, TILE.height, { fit: "fill", kernel: "nearest" });
  if (chrome) upscaled.composite([{ input: chromeSvg(TILE.width, TILE.height), top: 0, left: 0 }]);
  return upscaled.png().toBuffer();
}

export async function buildContactSheet(src, outPath) {
  const meta = await sharp(src).metadata();
  const tiles = [
    { label: `delivered ${meta.width}×${meta.height}, ${path.basename(src)}, with player chrome`, card: DARK_FEED, opts: { width: 1280, height: 720, chrome: true } },
    { label: "375×210 — phone feed, light mode", card: LIGHT_FEED, opts: { width: 375, height: 210 } },
    { label: "215×121 — watch-page rail, dark mode (smallest desktop)", card: DARK_FEED, opts: { width: 215, height: 121 } },
    { label: "375×210 grayscale — contrast without colour", card: GRAY_CARD, opts: { width: 375, height: 210, grayscale: true } },
  ];

  const cardW = TILE.width + 2 * PAD;
  const cardH = TILE.height + 2 * PAD;
  const cellH = LABEL + cardH;
  const sheetW = 2 * cardW + 3 * GAP;
  const sheetH = 2 * cellH + 3 * GAP;

  const layers = [];
  for (const [i, spec] of tiles.entries()) {
    const left = GAP + (i % 2) * (cardW + GAP);
    const top = GAP + Math.floor(i / 2) * (cellH + GAP);
    const card = await sharp({
      create: { width: cardW, height: cardH, channels: 3, background: spec.card },
    })
      .composite([{ input: await tile(src, spec.opts), top: PAD, left: PAD }])
      .png()
      .toBuffer();
    layers.push({ input: labelSvg(cardW, LABEL, spec.label), top, left });
    layers.push({ input: card, top: top + LABEL, left });
  }

  await sharp({ create: { width: sheetW, height: sheetH, channels: 3, background: { r: 10, g: 14, b: 22 } } })
    .composite(layers)
    // 92 rather than review-thumb's 82: this sheet IS the legibility evidence, so JPEG softening
    // would be read as the thumbnail failing at small size.
    .jpeg({ quality: 92 })
    .toFile(outPath);
  return { outPath, source: `${meta.width}×${meta.height}` };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const argv = process.argv.slice(2);
  let outDir = null;
  const inputs = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--out") outDir = argv[++i];
    else inputs.push(argv[i]);
  }
  if (!inputs.length) {
    console.error("usage: small-size-gate.mjs <thumbnail.png> [--out <dir>]");
    process.exit(2);
  }
  try {
    const src = confine(inputs[0]);
    const dir = outDir ? confine(outDir) : path.dirname(src);
    fs.mkdirSync(dir, { recursive: true });
    const out = path.join(dir, path.basename(src).replace(/\.[^.]+$/, "") + ".smallsize-sheet.jpg");
    const { source } = await buildContactSheet(src, out);
    console.log(`SMALLSIZE_SHEET (look at this, not the raw ${source} render):`);
    console.log(out);
  } catch (error) {
    console.error(`small-size-gate: ${error.message}`);
    process.exit(2);
  }
}
