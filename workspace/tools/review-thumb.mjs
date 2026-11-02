#!/usr/bin/env node
// review-thumb.mjs — a review-safe copy of rendered images, so the agent can look at them to judge the
// design. Model APIs cap the size of each image in a many-image turn (2000 px on either side), and a
// --scale 2 render is over it (a 1080x1350 still at 2x is 2160x2700), so reading raw renders can fail
// the whole request. To look at a render, run this and read its output.
//
// Usage:
//   node /workspace/tools/review-thumb.mjs <img> [<img> ...]            # one <=1600px .thumb.jpg each
//   node /workspace/tools/review-thumb.mjs --sheet <img> [<img> ...]    # tile them into ONE sheet
//   node /workspace/tools/review-thumb.mjs --out <dir> ...              # write into <dir> (default: beside the first input)
// Reviewing many frames? Use --sheet and read the one sheet.
// Paths resolve against --root (default: the folder holding tools/, i.e. /workspace); nothing outside
// it is read or written.
// Exit: 0 written · 2 bad arguments, an unreadable image, or the render toolchain is unavailable.

import fs from "node:fs";
import path from "node:path";
import { EXIT, ToolingError, WORKSPACE, confined, parseFlags, renderRequire, requireFile, runCli } from "./toolchain.mjs";

const MAX = 1600; // long-edge cap, safely under the 2000px many-image limit
const GAP = 8;
const SHEET_GROUND = { r: 20, g: 22, b: 26 };

await runCli("review-thumb", async () => {
  const { flags, positionals } = parseFlags(process.argv.slice(2), { values: ["out", "root"], booleans: ["sheet"] });
  if (!positionals.length) throw new ToolingError("usage: review-thumb.mjs [--sheet] [--out <dir>] <img> [<img> ...]");
  const root = path.resolve(flags.root || WORKSPACE);
  const inputs = positionals.map((p) => requireFile(confined(root, p, "image"), "image"));
  const dir = flags.out ? confined(root, flags.out, "--out") : path.dirname(inputs[0]);
  const sharp = renderRequire("sharp");
  fs.mkdirSync(dir, { recursive: true });

  const written = [];
  try {
    if (!flags.sheet || inputs.length === 1) {
      for (const src of inputs) {
        const out = path.join(dir, `${path.basename(src).replace(/\.[^.]+$/, "")}.thumb.jpg`);
        await sharp(src).resize(MAX, MAX, { fit: "inside", withoutEnlargement: true }).jpeg({ quality: 82 }).toFile(out);
        written.push(out);
      }
    } else {
      // Cells take the frames' own shape (the median aspect), and the column count is the one that
      // makes them largest inside MAX, so a row of 16:9 frames is not boxed into squares.
      const sizes = await Promise.all(inputs.map((src) => sharp(src).metadata()));
      const ratios = sizes.map((m) => m.width / m.height).sort((a, b) => a - b);
      const aspect = ratios[Math.floor(ratios.length / 2)];
      let layout = null;
      for (let cols = 1; cols <= inputs.length; cols++) {
        const rows = Math.ceil(inputs.length / cols);
        const width = Math.floor(Math.min((MAX - (cols + 1) * GAP) / cols, ((MAX - (rows + 1) * GAP) / rows) * aspect));
        if (!layout || width > layout.width) layout = { cols, rows, width };
      }
      const { cols, rows } = layout;
      const cellW = layout.width;
      const cellH = Math.floor(cellW / aspect);
      const tiles = [];
      for (let i = 0; i < inputs.length; i++) {
        const buf = await sharp(inputs[i]).resize(cellW, cellH, { fit: "inside", withoutEnlargement: true }).toBuffer();
        const meta = await sharp(buf).metadata();
        tiles.push({
          input: buf,
          left: GAP + (i % cols) * (cellW + GAP) + Math.floor((cellW - meta.width) / 2),
          top: GAP + Math.floor(i / cols) * (cellH + GAP) + Math.floor((cellH - meta.height) / 2),
        });
      }
      const out = path.join(dir, "review-sheet.jpg");
      await sharp({ create: { width: cols * cellW + (cols + 1) * GAP, height: rows * cellH + (rows + 1) * GAP, channels: 3, background: SHEET_GROUND } })
        .composite(tiles)
        .jpeg({ quality: 82 })
        .toFile(out);
      written.push(out);
    }
  } catch (error) {
    throw new ToolingError(`could not make the review copy: ${error.message}`);
  }
  console.log("REVIEW_THUMBS (read these, not the raw renders):");
  for (const out of written) console.log(out);
  return EXIT.PASS;
});
