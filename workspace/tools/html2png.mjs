#!/usr/bin/env node
// html2png.mjs — the stills renderer: one HTML page to PNG, JPEG or WebP at one or more sizes.
//
//   node /workspace/tools/html2png.mjs <page.html> --out <dir> [--name <stem>] --size 1080x1350
//        [--size 1080x1080 ...] [--format png|jpeg|webp] [--quality 90] [--scale 1]
//        [--require-font "Geist" ...] [--brand-fonts [--tokens <tokens.json>]] [--timeout 30000]
//
// Writes <dir>/<stem>-<W>x<H>.<ext> per size (stem defaults to the page's file name) and prints one
// JSON line: {"ok", "outputs": [{path, width, height, bytes}], "fonts": {family: bool}, ...}.
//
// Each size is a fresh load with the viewport set to that size, so the layout recomposes per format
// (media queries, vw/vh, container queries); it is never a scaled copy of one render. --scale sets the
// device scale factor, so a --scale 2 output is 2W x 2H pixels.
//
// Fonts: a missing family silently falls back in a browser, so every --require-font family (and,
// with --brand-fonts, the lead face of each brand font stack) must actually paint before anything is
// written. A required font that does not resolve, a page error or a failed asset request writes
// nothing and exits 1. Exit 2: bad arguments, missing page, or the render toolchain is unavailable.
//
// Relative paths resolve against the workspace (the folder holding tools/).

import { mkdirSync, statSync } from "node:fs";
import { basename, extname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import {
  DEFAULT_TOKENS,
  EXIT,
  ToolingError,
  WORKSPACE,
  brandLeadFonts,
  launchBrowser,
  loadTokens,
  parseFlags,
  renderRequire,
  requireFile,
  runCli,
  unresolvedFonts,
  watchPage,
} from "./toolchain.mjs";

const FORMATS = { png: "png", jpeg: "jpeg", jpg: "jpeg", webp: "webp" };
const EXTENSION = { png: "png", jpeg: "jpg", webp: "webp" };
const MAX_SIDE = 8192;

function parseSize(spec) {
  const match = /^(\d{1,5})x(\d{1,5})$/.exec(spec);
  const width = Number(match?.[1]);
  const height = Number(match?.[2]);
  if (!match || !(width > 0 && height > 0 && width <= MAX_SIDE && height <= MAX_SIDE)) {
    throw new ToolingError(`--size must look like 1080x1350 (each side 1-${MAX_SIDE}), got "${spec}"`);
  }
  return { width, height };
}

function options(argv) {
  const { flags, positionals } = parseFlags(argv, {
    values: ["out", "name", "format", "quality", "scale", "tokens", "timeout", "html"],
    multi: ["size", "require-font"],
    booleans: ["brand-fonts"],
  });
  const page = flags.html ?? positionals[0];
  if (!page || positionals.length > (flags.html ? 0 : 1)) {
    throw new ToolingError("usage: html2png.mjs <page.html> --out <dir> [--name <stem>] --size WxH [--size WxH ...]");
  }
  if (!flags.out) throw new ToolingError("--out <dir> is required");
  if (!flags.size.length) throw new ToolingError("at least one --size WxH is required");
  const format = FORMATS[(flags.format || "png").toLowerCase()];
  if (!format) throw new ToolingError(`--format must be png, jpeg or webp, got "${flags.format}"`);
  const quality = Number(flags.quality ?? 90);
  if (!(Number.isInteger(quality) && quality >= 1 && quality <= 100)) throw new ToolingError("--quality must be 1-100");
  const scale = Number(flags.scale ?? 1);
  if (!(scale >= 1 && scale <= 4)) throw new ToolingError("--scale must be between 1 and 4");
  const timeout = Number(flags.timeout ?? 30000);
  if (!(timeout > 0)) throw new ToolingError("--timeout must be a positive number of milliseconds");
  const html = requireFile(resolve(WORKSPACE, page), "page");
  const name = flags.name || basename(html, extname(html));
  if (!/^[\w.-]{1,120}$/.test(name)) throw new ToolingError(`--name must be a plain file stem, got "${name}"`);
  const fonts = [...flags["require-font"]];
  if (flags["brand-fonts"]) fonts.push(...brandLeadFonts(loadTokens(resolve(WORKSPACE, flags.tokens || DEFAULT_TOKENS))));
  return {
    html,
    outDir: resolve(WORKSPACE, flags.out),
    name,
    sizes: flags.size.map(parseSize),
    format,
    quality,
    scale,
    timeout,
    fonts: [...new Set(fonts)],
  };
}

async function render(opts) {
  const sharp = renderRequire("sharp");
  const browser = await launchBrowser(["--allow-file-access-from-files"]);
  const shots = [];
  const report = { ok: true, outputs: [], fonts: {}, problems: [] };
  try {
    for (const { width, height } of opts.sizes) {
      const page = await browser.newPage();
      const problems = watchPage(page);
      await page.setViewport({ width, height, deviceScaleFactor: opts.scale });
      try {
        await page.goto(pathToFileURL(opts.html).href, { waitUntil: "networkidle0", timeout: opts.timeout });
      } catch (error) {
        throw new ToolingError(`could not load ${opts.html} at ${width}x${height}: ${error.message}`);
      }
      await page.evaluate(() => document.fonts?.ready);
      for (const { family, renderedWith } of await unresolvedFonts(page, opts.fonts)) {
        report.problems.push(`font "${family}" did not resolve at ${width}x${height} (rendered with ${renderedWith})`);
      }
      report.problems.push(
        ...problems.pageErrors.map((e) => `page error at ${width}x${height}: ${e}`),
        ...problems.failedRequests.map((r) => `asset failed to load at ${width}x${height}: ${r}`),
      );
      shots.push({ width, height, png: Buffer.from(await page.screenshot({ type: "png" })) });
      await page.close();
    }
  } finally {
    await browser.close().catch(() => {});
  }
  for (const family of opts.fonts) report.fonts[family] = !report.problems.some((p) => p.startsWith(`font "${family}"`));
  if (report.problems.length) {
    report.ok = false;
    return report;
  }
  mkdirSync(opts.outDir, { recursive: true });
  for (const { width, height, png } of shots) {
    const path = join(opts.outDir, `${opts.name}-${width}x${height}.${EXTENSION[opts.format]}`);
    const encoder = sharp(png);
    if (opts.format === "png") encoder.png();
    else encoder[opts.format]({ quality: opts.quality });
    const info = await encoder.toFile(path);
    if (info.width !== width * opts.scale || info.height !== height * opts.scale) {
      throw new ToolingError(`${path} came out ${info.width}x${info.height}, expected ${width * opts.scale}x${height * opts.scale}`);
    }
    report.outputs.push({ path, width: info.width, height: info.height, bytes: statSync(path).size });
  }
  return report;
}

await runCli("html2png", async () => {
  const report = await render(options(process.argv.slice(2)));
  if (!report.problems.length) delete report.problems;
  console.log(JSON.stringify(report));
  return report.ok ? EXIT.PASS : EXIT.FINDINGS;
});
