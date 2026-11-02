#!/usr/bin/env node
/**
 * html2pdf.mjs — the one path from an HTML page to a deliverable PDF (static decks, one-pagers).
 *
 * A per-project `page.pdf()` call is how the glyph-advance defect (text-fidelity.mjs) keeps coming
 * back, so every PDF goes through here. It guarantees:
 *   - Chrome launches with CHROMIUM_EXPORT_ARGS, so glyph advances stay subpixel;
 *   - the families the page must be set in actually resolved (--require-font, or --brand-fonts for
 *     the lead face of each brand font stack) before anything is printed; nothing names a family
 *     here, the page's CSS and the brand pack do;
 *   - the produced PDF is audited before it is written: a quantized export fails the command instead
 *     of reaching a person.
 *
 * Usage:
 *   node /workspace/tools/html2pdf.mjs --html deck.html --out out/deck.pdf [--size 8.5x11in] [--zoom N]
 *        [--require-font "Geist" ...] [--brand-fonts [--tokens <tokens.json>]]
 *
 * --zoom is an opt-in fallback, off by default: it lays the page out N x larger and prints at 1/N,
 * which also shrinks the rounding step but reflows anything sized in vw/vh. Use it only if the audit
 * still fails on a Chromium that ignores the launch flag.
 * Prints `__HTML2PDF_OK__` and the output path. Relative paths resolve against the workspace.
 * Exit: 0 written · 1 a required font did not resolve, the page errored, or the export is quantized
 * (nothing is written) · 2 bad arguments or the render toolchain is unavailable.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { auditPdfGlyphAdvances } from "./text-fidelity.mjs";
import {
  DEFAULT_TOKENS,
  EXIT,
  ToolingError,
  WORKSPACE,
  brandLeadFonts,
  isMain,
  launchBrowser,
  loadTokens,
  parseFlags,
  requireFile,
  runCli,
  unresolvedFonts,
  watchPage,
} from "./toolchain.mjs";

/**
 * Print options for a true-trim-size page. The box stays at the trim size; `scale` is what shrinks
 * the zoom-x-larger layout back into it. Multiplying the box by zoom as well would ship a page
 * zoom-x oversized -- kept pure so a test can hold the invariant without launching a browser.
 */
export function printOptions(pageWidthIn, pageHeightIn, zoom = 1) {
  if (!(zoom >= 1 && zoom <= 10)) throw new ToolingError("zoom must be between 1 and 10");
  return {
    width: `${pageWidthIn}in`,
    height: `${pageHeightIn}in`,
    scale: 1 / zoom,
    printBackground: true,
    margin: { top: "0", right: "0", bottom: "0", left: "0" },
    preferCSSPageSize: false,
  };
}

function options(argv) {
  const { flags, positionals } = parseFlags(argv, {
    values: ["html", "out", "size", "zoom", "tokens", "timeout"],
    multi: ["require-font"],
    booleans: ["brand-fonts"],
  });
  const html = flags.html ?? positionals[0];
  if (!html || !flags.out) {
    throw new ToolingError("usage: html2pdf.mjs --html <file> --out <file.pdf> [--size 8.5x11in] [--zoom N] [--require-font F]");
  }
  const size = /^(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)in$/.exec(String(flags.size || "8.5x11in"));
  if (!size) throw new ToolingError(`--size must look like 8.5x11in, got "${flags.size}"`);
  const zoom = Number(flags.zoom || 1);
  printOptions(Number(size[1]), Number(size[2]), zoom); // validates zoom
  const fonts = [...flags["require-font"]];
  if (flags["brand-fonts"]) fonts.push(...brandLeadFonts(loadTokens(path.resolve(WORKSPACE, flags.tokens || DEFAULT_TOKENS))));
  return {
    html: requireFile(path.resolve(WORKSPACE, html), "page"),
    out: path.resolve(WORKSPACE, flags.out),
    widthIn: Number(size[1]),
    heightIn: Number(size[2]),
    zoom,
    fonts: [...new Set(fonts)],
    timeout: Number(flags.timeout || 30000),
  };
}

if (isMain(import.meta.url)) {
  await runCli("html2pdf", async () => {
    const opts = options(process.argv.slice(2));
    const browser = await launchBrowser(["--allow-file-access-from-files"]);
    let pdf;
    const problems = [];
    try {
      const page = await browser.newPage();
      const watched = watchPage(page);
      try {
        await page.goto(pathToFileURL(opts.html).href, { waitUntil: "networkidle0", timeout: opts.timeout });
      } catch (error) {
        throw new ToolingError(`could not load ${opts.html}: ${error.message}`);
      }
      // A missing face substitutes silently and the PDF would embed the fallback, so check first.
      for (const { family, renderedWith } of await unresolvedFonts(page, opts.fonts)) {
        problems.push(`font "${family}" did not resolve (rendered with ${renderedWith}) — the PDF would embed a substitute`);
      }
      problems.push(...watched.pageErrors.map((e) => `page error: ${e}`), ...watched.failedRequests.map((r) => `asset failed to load: ${r}`));
      if (!problems.length) {
        if (opts.zoom !== 1) await page.evaluate((z) => { document.documentElement.style.zoom = String(z); }, opts.zoom);
        pdf = Buffer.from(await page.pdf(printOptions(opts.widthIn, opts.heightIn, opts.zoom)));
      }
    } finally {
      await browser.close().catch(() => {});
    }
    if (!problems.length) {
      // The gate: a quantized export is a failed export and must not reach a person as a file.
      const audit = auditPdfGlyphAdvances(pdf);
      for (const run of audit.offenders) {
        problems.push(`quantized glyph advances: ${run.fontSize}pt text on a whole-unit grid (+/-${run.worstErrorPctEm}% of an em); see text-fidelity.mjs`);
      }
    }
    if (problems.length) {
      for (const problem of problems) console.error(`html2pdf: ${problem}`);
      return EXIT.FINDINGS;
    }
    mkdirSync(path.dirname(opts.out), { recursive: true });
    writeFileSync(opts.out, pdf);
    console.log("__HTML2PDF_OK__");
    console.log(opts.out);
    return EXIT.PASS;
  });
}
