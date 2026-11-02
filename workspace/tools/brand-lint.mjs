#!/usr/bin/env node
// brand-lint.mjs — check a composition or a piece of copy against the active brand pack.
//
// Every brand fact comes from the pack's tokens.json (validated by src/design_agent/brand/schema.py);
// CSS custom properties resolve through the tokens.css beside it. Nothing about any particular brand
// is written in this file.
//
// Design mode (default): an HTML/CSS file, with the local stylesheets it links, for colors outside
// the palette, banned colors (with the token to use instead), off-brand fonts and stacks that do not
// lead with a brand face, radii over the maximum, decorative bullets and markers, generic motif
// classes, shouted or all-lowercase copy, canonical spellings, banned copy on the graphic, WCAG text
// contrast, pixel-grid snapping and the construction of diagram connectors.
// Copy mode (--copy): a text file for banned phrases and characters, review words, canonical
// spellings and the hashtag limit.
//
// Usage:
//   node /workspace/tools/brand-lint.mjs <composition.html|style.css> [--tokens <tokens.json>] [--json]
//   node /workspace/tools/brand-lint.mjs --copy <post.txt> [--tokens <tokens.json>] [--json]
// --tokens defaults to <root>/brand/tokens.json; --root (default: the folder holding tools/, i.e.
// /workspace) is the workspace every path resolves against and nothing outside it is read.
//
// Exit: 0 clean or warnings only · 1 any ERROR · 2 the lint could not run (bad arguments, missing or
// binary target, unreadable brand pack).

import { existsSync, readFileSync, realpathSync, statSync } from "node:fs";
import { dirname, extname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { EXIT, ToolingError, WORKSPACE, confined, loadTokens, parseFlags, requireFile } from "./toolchain.mjs";

// A crash is not a verdict: anything unexpected is a tooling failure, never "findings".
process.on("uncaughtException", (error) => {
  console.error(`brand-lint: internal error: ${error?.stack || error}`);
  process.exit(EXIT.TOOLING);
});

// A text scan of a compressed raster or font finds hex-shaped byte coincidences and reports colors
// the image does not contain. Lint the composition that produced the file, never the file.
const RASTER = new Set([".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".tif", ".tiff", ".ico", ".mp4", ".mov", ".webm", ".pdf", ".woff", ".woff2", ".ttf", ".otf"]);

function setup(argv) {
  const { flags, positionals } = parseFlags(argv, { values: ["tokens", "root"], booleans: ["copy", "json"] });
  if (positionals.length !== 1) {
    throw new ToolingError("usage: brand-lint.mjs [--copy] [--tokens <tokens.json>] [--root <dir>] [--json] <file>");
  }
  const root = resolve(flags.root || WORKSPACE);
  const target = positionals[0];
  const file = requireFile(confined(root, target, "target"), "target");
  if (RASTER.has(extname(file).toLowerCase())) {
    throw new ToolingError(
      `refusing a binary/raster target (${extname(file)}): a text scan of compressed data reads byte ` +
        "coincidences as colors. Lint the composition that produced it and look at the pixels yourself.",
    );
  }
  const tokensPath = resolve(root, flags.tokens || join("brand", "tokens.json"));
  const spec = loadTokens(tokensPath);
  // tokens.css is generated from tokens.json; read it when present so a hand-added variable
  // resolves too, and fall back to the JSON token map so contrast never runs without the tokens.
  const tokenVars = new Map(Object.entries(spec.design.tokens || {}));
  const stacks = spec.design.fontStacks || {};
  for (const role of ["display", "text", "mono"]) {
    if (stacks[role]?.length) {
      tokenVars.set(`--brand-font-${role}`, stacks[role].map((f) => (/[\s\d]/.test(f) || /^[A-Z]/.test(f) ? `"${f}"` : f)).join(", "));
    }
  }
  const cssPath = join(dirname(tokensPath), "tokens.css");
  if (existsSync(cssPath)) {
    for (const m of readFileSync(cssPath, "utf8").matchAll(/(--[\w-]+)\s*:\s*([^;}]+)/g)) tokenVars.set(m[1], m[2].trim());
  }
  return { root, target, file, spec, tokenVars, copyMode: Boolean(flags.copy), json: Boolean(flags.json) };
}

let CONFIG;
try {
  CONFIG = setup(process.argv.slice(2));
} catch (error) {
  console.error(`brand-lint: ${error instanceof ToolingError ? error.message : error?.stack || error}`);
  process.exit(EXIT.TOOLING);
}
const { root: ROOT, target, file, spec: SPEC, tokenVars: TOKEN_VARS, copyMode, json } = CONFIG;

const findings = []; // {sev, line, msg, rule}
const add = (sev, line, msg, rule) => findings.push({ sev, line, msg, rule });

// A comp is linted WITH the local stylesheets it links: each <link rel=stylesheet> to a .css file
// inside the workspace is spliced in as a <style> block where the link sits, so the cascade order
// holds, and `origins` maps every line back to its own file. Remote, templated and commented-out
// links are skipped; nothing outside the workspace is read.
const origins = [{ from: 1, file: target, shift: 0 }];
const lineCount = (text) => text.split("\n").length;
function withLinkedSheets(html) {
  const realRoot = realpathSync(ROOT);
  const comments = [...html.matchAll(/<!--[\s\S]*?-->/g)].map((c) => [c.index, c.index + c[0].length]);
  let out = "";
  let cursor = 0;
  for (const m of html.matchAll(/<link\b[^>]*>/gi)) {
    const ref = m[0].match(/\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i);
    const href = (ref?.[1] ?? ref?.[2] ?? ref?.[3] ?? "").split(/[?#]/)[0];
    if (!/\brel\s*=\s*["']?stylesheet\b/i.test(m[0]) || !href || /^(?:[a-z][\w+.-]*:|\/\/)|\$\{|\{\{/i.test(href)) continue;
    if (comments.some(([start, end]) => m.index > start && m.index < end)) continue;
    const at = lineCount(out + html.slice(cursor, m.index));
    let sheet = null;
    try { sheet = realpathSync(resolve(dirname(file), href)); } catch { /* reported below */ }
    const inRoot = sheet && relative(realRoot, sheet);
    if (sheet && (inRoot.startsWith(`..${sep}`) || isAbsolute(inRoot))) {
      add("WARN", at, `linked stylesheet "${href}" resolves outside the workspace — not read or linted`, "stylesheet.outside");
      continue;
    }
    if (!sheet || extname(sheet).toLowerCase() !== ".css" || !statSync(sheet).isFile()) {
      add("WARN", at, `linked stylesheet "${href}" is not a local .css file — not linted`, "stylesheet.not-local");
      continue;
    }
    const css = readFileSync(sheet, "utf8");
    const cssEnd = at + lineCount(css) + 1; // the line holding </style> and the rest of the link's line
    out += `${html.slice(cursor, m.index)}<style>\n${css}\n</style>`;
    origins.push({ from: at + 1, file: inRoot, shift: at });
    origins.push({ from: cssEnd, file: target, shift: cssEnd - lineCount(html.slice(0, m.index)) });
    cursor = m.index + m[0].length;
  }
  return out + html.slice(cursor);
}
const authored = readFileSync(file, "utf8");
const source = copyMode ? authored : withLinkedSheets(authored);
const lines = source.split("\n");

// ---------- brand facts, all from tokens.json ----------
/** #abc, #abcd, #aabbcc, #aabbccdd -> #aabbcc (alpha is not a different color). */
const normHex = (hex) => {
  const raw = hex.replace(/^#/, "").toLowerCase();
  const rgb = raw.length <= 4 ? raw.slice(0, 3).split("").map((c) => c + c).join("") : raw.slice(0, 6);
  return `#${rgb}`;
};
const design = SPEC.design;
const copyRules = SPEC.copy;
const allow = new Set((design.allowedColors || []).map(normHex));
const ext = new Set((design.extendedPalette?.colors || []).map(normHex));
// Colors that exist only inside the official marks. The lint polices generated creative, not the
// brand's own artwork: without this, inlining an official logo would fail its own brand check.
const officialAsset = new Set((design.officialAssetColors?.colors || []).map(normHex));
const banned = new Set((design.bannedColors?.colors || []).map(normHex));
const replacement = new Map(Object.entries(design.replacementColors || {}).map(([hex, token]) => [normHex(hex), token]));
const lower = (values) => (values || []).map((v) => String(v).toLowerCase());
const offFonts = new Set(lower(design.knownOffBrandFonts));
const stacks = design.fontStacks || {};
const okFonts = new Set([...lower(design.allowedFontTokens), ...lower(stacks.display), ...lower(stacks.text), ...lower(stacks.mono)]);
const leadFaces = { display: stacks.display?.[0], text: stacks.text?.[0], mono: stacks.mono?.[0] };
const GENERIC_FAMILIES = new Set([
  "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif", "ui-sans-serif",
  "ui-monospace", "ui-rounded", "emoji", "math", "fangsong",
]);
const CSS_WIDE = new Set(["inherit", "initial", "unset", "revert", "revert-layer"]);
// Monospace families: the brand's own mono stack plus the generics and common system faces.
const monoFamilies = new Set([...lower(stacks.mono), "monospace", "ui-monospace", "menlo", "monaco", "consolas", "sf mono", "courier", "courier new"]);
const MONO_TOKEN = /var\(\s*--brand-font-mono\s*\)/i;
const BRAND_FONT_TOKEN = /var\(\s*--brand-font-(?:display|text|mono)\s*\)/i;
/** `"Fragment Mono", Fira Code, monospace` -> ["Fragment Mono", "Fira Code", "monospace"]. */
const fontFamilies = (value) =>
  value
    .replace(/!important/gi, "")
    .split(",")
    .map((part) => part.trim().replace(/^["']|["']$/g, "").trim())
    .filter(Boolean);
const isMonoStack = (value) => MONO_TOKEN.test(value) || fontFamilies(value).some((f) => monoFamilies.has(f.toLowerCase()));
const maxRadius = design.maxRectRadiusPx;
// Fully rounded ends read as a pill or a circle, not a rounded rectangle.
const PILL_RADIUS_PX = 100;
const creativeType = design.creativeTypography || {};
const bannedCreativeChars = creativeType.bannedDecorativeChars || ["•"];
const bannedDecorativeMarkerClasses =
  creativeType.bannedDecorativeMarkerClasses || ["bullet", "dot", "tick", "marker"];
const bannedGenericMotifClasses = new Set(
  creativeType.bannedGenericMotifClasses || ["dot-grid", "dot-field", "node-cloud", "node-network", "network-lattice"],
);
const diagramSpec = design.diagramConstruction || {};
const connectorTags = new Set(diagramSpec.connectorElements || ["path", "line", "polyline"]);
const strokeToken = (diagramSpec.strokeTokens || ["--brand-stroke"])[0];
const gridUnitPx = diagramSpec.baseGridUnitPx ?? 8;
const strokeRatio = diagramSpec.strokeToGridRatio ?? 0.25;
const maxArrowheadMarkers = diagramSpec.maxArrowheadMarkers ?? 1;
// "Corners on shared coordinates" is exact authoring, not a proximity band — this only absorbs the
// rounding of a hand-written decimal, so two anchors 3px apart still read as two separate anchors.
const JOIN_EPSILON = 0.5;
const allowedAllCaps = new Set(
  (creativeType.allowedAllCapsTerms || []).map((term) => term.toUpperCase()),
);
// Lowercased term -> its one correct spelling, from both places the pack can declare one.
const canonical = new Map(
  [...Object.entries(creativeType.canonicalCasing || {}), ...Object.entries(copyRules.casingRules?.canonical || {})].map(
    ([term, spelling]) => [term.toLowerCase(), spelling],
  ),
);
// Words whose canonical spelling is itself lowercase (a product named in lowercase) are not
// all-lowercase copy.
const lowercaseCanonicalWords = new Set(
  [...canonical.values()].filter((s) => s === s.toLowerCase()).flatMap((s) => s.split(/\s+/)),
);
const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const canonicalPatterns = [...canonical].map(([term, spelling]) => ({
  spelling,
  re: new RegExp(`(?<![\\p{L}\\p{N}])${term.split(/\s+/).map(escapeRegExp).join("\\s+")}(?![\\p{L}\\p{N}])`, "giu"),
}));
// "sentence" and "title" headlines both rule out shouted and all-lowercase copy; "any" opts out.
const casingEnforced = (copyRules.casingRules?.headlines || "sentence") !== "any";
// A shouted run is 2+ ordinary words in a row, or one long word — short enough that "API key" and a
// "NEW" badge stay clean while "TECHNICAL GUIDE" does not.
const ALL_CAPS_RUN_LETTERS = 6;
const ALL_CAPS_SOLO_LETTERS = 7;
const ROMAN_NUMERAL = /^M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$/;
const LITERAL_TEXT_TAGS = ["code", "pre", "kbd", "samp"];
// WCAG 2.1 text contrast. Large text = >=24px, or >=18.66px at weight >=700 (SC 1.4.3).
const WCAG_NORMAL = 4.5;
const WCAG_LARGE = 3;
const LARGE_PX = 24;
const LARGE_BOLD_PX = 18.66;
const BOLD_WEIGHT = 700;
const NAMED_COLORS = new Map([
  ["white", "#ffffff"],
  ["black", "#000000"],
  ["transparent", "rgba(0,0,0,0)"],
]);
const VOID_TAGS = new Set([
  "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr",
]);
const decorativeBulletPattern = new RegExp(
  `(?:${bannedCreativeChars.map(escapeRegExp).join("|")}|&bull;|&#8226;|&#x2022;)`,
  "i",
);

const lineAt = (index) => source.slice(0, index).split("\n").length;
const mask = (text) => text.replace(/[^\n]/g, " ");

function declarations(body, sourceOffset) {
  const out = new Map();
  for (const m of body.matchAll(/([\w-]+)\s*:\s*([^;{}]+)/g)) {
    const property = m[1].toLowerCase();
    out.set(property, {
      value: m[2].trim(),
      line: lineAt(sourceOffset + m.index),
    });
  }
  return out;
}

function cssRules() {
  const chunks = [];
  if (extname(file).toLowerCase() === ".css") chunks.push({ text: source, offset: 0 });
  for (const m of source.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style\b[^>]*>/gi)) {
    const bodyOffset = m.index + m[0].indexOf(m[1]);
    chunks.push({ text: m[1], offset: bodyOffset });
  }

  const rules = new Map();
  for (const chunk of chunks) {
    const clean = chunk.text.replace(/\/\*[\s\S]*?\*\//g, mask);
    for (const m of clean.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const selectorText = m[1].trim();
      if (!selectorText || selectorText.startsWith("@")) continue;
      const bodyOffset = chunk.offset + m.index + m[0].indexOf(m[2]);
      const parsed = declarations(m[2], bodyOffset);
      for (const rawSelector of selectorText.split(",")) {
        const selector = rawSelector.trim();
        if (!selector) continue;
        const rule = rules.get(selector) || {
          declarations: new Map(),
          line: lineAt(chunk.offset + m.index),
        };
        for (const [property, value] of parsed) rule.declarations.set(property, value);
        rules.set(selector, rule);
      }
    }
  }
  return rules;
}

function isZeroSpacing(value) {
  const clean = value.replace(/\s*!important\s*$/i, "").trim();
  return /^[+-]?0+(?:\.0+)?(?:[a-z%]+)?$/i.test(clean);
}

// The brand's mono stack is ordered: its first face is the brand face and the rest are fallbacks, so
// a stack that leads with a fallback renders the fallback on every machine that has it.
function lintMonoDeclarations(label, parsed, line) {
  const family = parsed.get("font-family");
  if (!family || !isMonoStack(family.value)) return;

  const first = fontFamilies(family.value)[0]?.toLowerCase();
  if (
    leadFaces.mono &&
    !MONO_TOKEN.test(family.value) &&
    !CSS_WIDE.has(first) &&
    first !== leadFaces.mono.toLowerCase()
  ) {
    add(
      "ERROR",
      family.line || line,
      `${label} mono stack must lead with "${leadFaces.mono}" or use var(--brand-font-mono)`,
      "font.mono-lead",
    );
  }

  // The pack's required tracking for mono (schema default "0"); a stack inherits tracking from its
  // parent otherwise.
  const required = String(creativeType.monoLetterSpacing ?? "0");
  const spacing = parsed.get("letter-spacing");
  const spacingMatches = (value) =>
    isZeroSpacing(required) ? isZeroSpacing(value) : value.replace(/\s*!important\s*$/i, "").trim() === required.trim();
  if (!spacing) {
    add("ERROR", line, `${label} uses a mono font without explicit letter-spacing: ${required}`, "font.mono-spacing");
  } else if (!spacingMatches(spacing.value)) {
    add(
      "ERROR",
      spacing.line,
      `${label} uses mono letter-spacing "${spacing.value}" — the brand sets mono at ${required}`,
      "font.mono-spacing",
    );
  }

  const transform = parsed.get("text-transform");
  if (
    creativeType.allowMonoUppercaseTransform !== true &&
    transform &&
    /\buppercase\b/i.test(transform.value)
  ) {
    add(
      "ERROR",
      transform.line,
      `${label} forces uppercase mono text — use sentence case or title case`,
      "font.mono-uppercase",
    );
  }
}

// CSS `text-transform: uppercase` is only half of the uppercase failure: an eyebrow authored literally
// as "TECHNICAL GUIDE" renders identically and clears every style-level gate. Acronyms, roman numerals,
// and single capitals are legitimately uppercase, so they neither start nor break a shouted run.
function literalAllCapsRun(words) {
  let run = [];
  let shouted = null;
  const settle = () => {
    const letters = run.join("").length;
    if (!shouted && letters >= (run.length > 1 ? ALL_CAPS_RUN_LETTERS : ALL_CAPS_SOLO_LETTERS)) {
      shouted = run;
    }
    run = [];
  };
  for (const word of words) {
    const clean = word.replace(/[^A-Za-z]/g, "");
    if (clean.length >= 2 && clean === clean.toUpperCase()) {
      if (!allowedAllCaps.has(clean) && !ROMAN_NUMERAL.test(clean)) run.push(clean);
      continue;
    }
    if (/[a-z]/.test(clean)) settle();
  }
  settle();
  return shouted;
}

function selectorMatches(selector, tag, attrs) {
  const compound = selector
    .split(/[\s>+~]+/)
    .filter(Boolean)
    .at(-1)
    ?.replace(/::?[\w-]+(?:\([^)]*\))?/g, "")
    .replace(/\[[^\]]+\]/g, "");
  if (!compound) return false;

  const tagMatch = compound.match(/^[a-z][\w-]*/i);
  if (tagMatch && tagMatch[0].toLowerCase() !== tag) return false;

  const id = attrs.match(/\bid\s*=\s*["']([^"']+)["']/i)?.[1] || "";
  const classes = new Set(
    (attrs.match(/\bclass\s*=\s*["']([^"']+)["']/i)?.[1] || "").split(/\s+/).filter(Boolean),
  );
  const requiredIds = [...compound.matchAll(/#([\w-]+)/g)].map((m) => m[1]);
  const requiredClasses = [...compound.matchAll(/\.([\w-]+)/g)].map((m) => m[1]);
  if (requiredIds.some((required) => required !== id)) return false;
  if (requiredClasses.some((required) => !classes.has(required))) return false;
  return Boolean(tagMatch || requiredIds.length || requiredClasses.length);
}

// Which of several matching rules the browser actually applies: specificity first, source order only as
// the tie-break. Reading the first match instead would report a low-specificity reset as the winner.
function specificity(selector) {
  const attributes = selector.replace(/\[[^\]]*\]/g, "[]");
  const ids = attributes.match(/#[\w-]+/g)?.length || 0;
  const classes = attributes.match(/\.[\w-]+|\[\]|:(?!:)[\w-]+/g)?.length || 0;
  const types = attributes.replace(/[.#:][\w-]+|\[\]/g, "").match(/[a-z][\w-]*/gi)?.length || 0;
  return ids * 1e4 + classes * 1e2 + types;
}

function winningRule(rules, tag, attrs) {
  return rules
    .filter(([selector]) => selectorMatches(selector, tag, attrs))
    .sort((a, b) => specificity(a[0]) - specificity(b[0]))
    .at(-1);
}
// The suggested rewrite must not teach a new brand error, so canonical spelling wins over sentence case.
const withCanonical = (text) => canonicalPatterns.reduce((out, { re, spelling }) => out.replace(re, spelling), text);
const sentenceCase = (run) =>
  withCanonical(run.map((word, i) => (i ? word.toLowerCase() : word[0] + word.slice(1).toLowerCase())).join(" "));

function hasExplicitCaseOverride(attrs) {
  return /(?:^|\s)data-brand-case\s*=\s*(["'])explicit\1(?:\s|$)/i.test(attrs);
}

function hasLowercaseCaseOverride(attrs) {
  return /(?:^|\s)data-brand-case\s*=\s*(["'])(?:explicit|continuation)\1(?:\s|$)/i.test(attrs);
}

function hasSemanticMotifRole(attrs) {
  return /(?:^|\s)data-brand-role\s*=\s*(["'])(?:diagram|data|source)\1(?:\s|$)/i.test(attrs);
}

function hasDiagramRole(attrs) {
  return /(?:^|\s)data-brand-role\s*=\s*(["'])diagram\1(?:\s|$)/i.test(attrs);
}

// "computed" = audited renderer geometry (data-viz emits its own stroke system and topology receipt);
// "vendored" = official artwork embedded verbatim. Neither is hand-authored, so neither is gated.
function hasConnectorSourceOverride(attrs) {
  return /(?:^|\s)data-brand-connector\s*=\s*(["'])(?:computed|vendored)\1(?:\s|$)/i.test(attrs);
}

// A diagram is full of strokes that are not edges — lane dividers, axes, brackets, rules, embedded brand
// artwork. The stroke rule binds connectors, so a connector has to say it is one: it points at the
// shared arrowhead, or it carries the `.connector` class the stroke token is bound on.
function isConnector(attrs) {
  return (
    /\bmarker-(?:end|start)\s*=/i.test(attrs) ||
    (attrs.match(/\bclass\s*=\s*["']([^"']+)["']/i)?.[1] || "").split(/\s+/).includes("connector")
  );
}

function motifClass(name) {
  const clean = name.toLowerCase();
  return [...bannedGenericMotifClasses].find(
    (bannedName) =>
      clean === bannedName ||
      clean.startsWith(`${bannedName}-`) ||
      clean.endsWith(`-${bannedName}`) ||
      clean.includes(`-${bannedName}-`),
  );
}

function lintLowercaseTransform(label, parsed, line) {
  if (!casingEnforced) return;
  const transform = parsed.get("text-transform");
  if (transform && /\blowercase\b/i.test(transform.value)) {
    add(
      "ERROR",
      transform.line || line,
      `${label} forces lowercase visual copy — author intentional code/source casing literally`,
      "case.lowercase-transform",
    );
  }
}

// --- pixel grid -----------------------------------------------------------------------------------
// Chromium snaps painted box edges to whole DEVICE pixels. A fractional CSS length therefore lands
// on different device pixels down a repeated stack, so one rule in a set of twelve renders a pixel
// thicker than its neighbours and the set reads uneven. This is paint-time snapping, a different
// stage from the glyph-advance quantization in text-fidelity.mjs -- the export flags there do
// nothing for it, and it has to be fixed in the authored comp.
//
// Measured in headless Chromium, 12 stacked rules per column:
//   height        DSF 1        DSF 2        DSF 3
//   1px           1px          2px          3px        uniform everywhere  <- the rule
//   0.5px         1px          1px          1-2px      breaks only at DSF 3
//   1.3px         1-2px        2-3px        3-4px      breaks everywhere
//   1.6667px      1-2px        3-4px        5px        breaks at our scales
// Severity follows that table: a non-half fraction is already broken at the 1-2x scales stills render
// at (html2png --scale), so it errors. An exact half survives both, so it warns.
const GRID_LENGTH_PROPS = new Set([
  "height",
  "min-height",
  "border-width",
  "border-top-width",
  "border-bottom-width",
  "border-left-width",
  "border-right-width",
]);

function fractionalPx(value) {
  // Single bare px length only. A calc(), a var(), a percentage or a multi-value shorthand is not
  // something this lint can resolve, and guessing at one would cost more in false alarms than the
  // defect costs in rework.
  const m = /^(-?\d*\.?\d+)px$/.exec(value.trim());
  if (!m) return null;
  const px = Number(m[1]);
  return Number.isInteger(px) ? null : px;
}

function lintPixelGrid() {
  for (const [selector, rule] of cssRules()) {
    for (const [property, decl] of rule.declarations) {
      if (!GRID_LENGTH_PROPS.has(property)) continue;
      const px = fractionalPx(decl.value);
      if (px === null) continue;
      const isHalf = Math.abs(px * 2 - Math.round(px * 2)) < 1e-9;
      add(
        isHalf ? "WARN" : "ERROR",
        decl.line || rule.line,
        `selector "${selector}" sets ${property}: ${decl.value} — a fractional length snaps to ` +
          `different device pixels down a repeated stack, so rules/hairlines render unevenly` +
          (isHalf
            ? ` (an exact half holds at scale 1-2 but breaks at 3; prefer a whole pixel)`
            : ` at the scales we render. Use a whole pixel.`),
        "grid.fractional",
      );
    }

    // A fractional COMPUTED line-height moves every line box off the pixel grid, which shows up as
    // uneven pitch for absolutely-positioned children and repeated rows -- measured at 17/18px
    // alternating for `line-height: 1.45` on 12px type. Only flagged when both halves sit in the
    // same rule, because resolving the cascade is out of scope for a text linter. WARN, not ERROR:
    // unitless line-height is normal practice and only bites when something repeats against it.
    const lh = rule.declarations.get("line-height");
    const fs = rule.declarations.get("font-size");
    if (!lh || !fs) continue;
    const fsPx = /^(-?\d*\.?\d+)px$/.exec(fs.value.trim());
    if (!fsPx) continue;
    const unitless = /^(-?\d*\.?\d+)$/.exec(lh.value.trim());
    const computed = unitless
      ? Number(unitless[1]) * Number(fsPx[1])
      : Number(/^(-?\d*\.?\d+)px$/.exec(lh.value.trim())?.[1] ?? NaN);
    if (!Number.isFinite(computed) || Number.isInteger(computed)) continue;
    add(
      "WARN",
      lh.line || rule.line,
      `selector "${selector}" computes line-height to ${Number(computed.toFixed(4))}px ` +
        `(${lh.value} x ${fs.value}) — a fractional line box puts repeated rows and absolutely ` +
        `positioned children on uneven pitch. Use a line-height that lands on a whole pixel.`,
      "grid.line-height",
    );
  }
}

function lintCreativeTypography() {
  const rules = cssRules();
  for (const [selector, rule] of rules) {
    lintLowercaseTransform(`selector "${selector}"`, rule.declarations, rule.line);
    lintMonoDeclarations(`selector "${selector}"`, rule.declarations, rule.line);

    const markerContainer = [...selector.matchAll(/\.([\w-]+)/g)].some((match) =>
      /^(?:chip|feature|item|pill|tag)(?:[-_]|$)/i.test(match[1]),
    );
    const content = rule.declarations.get("content")?.value || "";
    const drawsRoundMarker =
      rule.declarations.has("width") &&
      rule.declarations.has("height") &&
      (rule.declarations.has("background") || rule.declarations.has("background-color")) &&
      /^(?:50%|100px)(?:\s*!important)?$/i.test(
        rule.declarations.get("border-radius")?.value || "",
      );
    if (
      /::before\b/i.test(selector) &&
      markerContainer &&
      (decorativeBulletPattern.test(content) || drawsRoundMarker)
    ) {
      add(
        "ERROR",
        rule.line,
        `selector "${selector}" draws a decorative marker before feature copy — keep chips text-only`,
        "type.decorative-marker",
      );
    }
  }

  for (const m of source.matchAll(/<[a-z][^>]*\sstyle\s*=\s*(["'])([\s\S]*?)\1[^>]*>/gi)) {
    const bodyOffset = m.index + m[0].indexOf(m[2]);
    const parsed = declarations(m[2], bodyOffset);
    lintLowercaseTransform("inline style", parsed, lineAt(m.index));
    lintMonoDeclarations("inline style", parsed, lineAt(m.index));
  }

  // <title> (document or SVG) names a tab or a tooltip and never paints, so it is not visual copy.
  let visible = source
    .replace(/<!--[\s\S]*?-->/g, mask)
    .replace(/<style\b[^>]*>[\s\S]*?<\/style\b[^>]*>/gi, mask)
    .replace(/<script\b[^>]*>[\s\S]*?<\/script\b[^>]*>/gi, mask)
    .replace(/<title\b[^>]*>[\s\S]*?<\/title\b[^>]*>/gi, mask);

  const visibleLines = visible.replace(/<[^>]*>/g, mask).split("\n");
  visibleLines.forEach((raw, i) => {
    if (decorativeBulletPattern.test(raw)) {
      add(
        "ERROR",
        i + 1,
        "decorative bullet glyph in image copy — use spacing, dividers, numbers, or approved icons",
        "type.decorative-bullet",
      );
    }
  });

  for (const m of visible.matchAll(/<([a-z][\w-]*)([^>]*)>/gi)) {
    const attrs = m[2];
    if (hasSemanticMotifRole(attrs)) continue;
    const names = [
      attrs.match(/\bid\s*=\s*["']([^"']+)["']/i)?.[1] || "",
      ...(attrs.match(/\bclass\s*=\s*["']([^"']+)["']/i)?.[1].split(/\s+/).filter(Boolean) || []),
    ];
    const bannedName = names.map(motifClass).find(Boolean);
    if (bannedName) {
      add(
        "ERROR",
        lineAt(m.index),
        `generic dot/network motif "${bannedName}" — remove AI wallpaper or mark a real diagram/data/source role`,
        "motif.generic",
      );
    }
  }

  for (const m of visible.matchAll(
    /<([a-z][\w-]{0,63})\b([^>\n]{0,2000})>\s{0,80}<\/\1\s{0,20}>(?=\s{0,80}(?:[A-Za-z0-9]|&(?:#\d{1,8}|#x[\da-f]{1,8}|[a-z]{1,32});))/gi,
  )) {
    const classes =
      m[2].match(/\bclass\s*=\s*["']([^"'\n]{0,1000})["']/i)?.[1].split(/\s+/).filter(Boolean) ||
      [];
    if (classes.some((name) => bannedDecorativeMarkerClasses.includes(name.toLowerCase()))) {
      add(
        "ERROR",
        lineAt(m.index),
        `empty "${classes.join(" ")}" element prefixes visible copy — keep feature chips text-only`,
        "type.decorative-marker",
      );
    }
  }

  for (const m of visible.matchAll(/<([a-z][\w-]*)([^>]*)>([^<]+)<\/\1\s*>/gi)) {
    const tag = m[1].toLowerCase();
    const attrs = m[2];
    const words =
      m[3]
        // a `{{SLOT}}` is a template slot, not authored copy — its casing is the substituted value's
        .replace(/\{\{[^{}]{0,120}\}\}|\$\{[^{}]{0,120}\}/g, " ")
        .replace(/&(?:#\d+|#x[\da-f]+|\w+);/gi, " ")
        .match(/[A-Za-z][A-Za-z'-]*/g) || [];
    const letters = words.join("").replace(/[^A-Za-z]/g, "");
    const onlyLowercaseCanonical =
      words.length > 0 && words.every((word) => lowercaseCanonicalWords.has(word));
    if (!casingEnforced) continue;
    if (
      !LITERAL_TEXT_TAGS.includes(tag) &&
      !hasLowercaseCaseOverride(attrs) &&
      !onlyLowercaseCanonical &&
      words.length >= 1 &&
      letters.length >= 4 &&
      letters === letters.toLowerCase() &&
      letters !== letters.toUpperCase()
    ) {
      add(
        "ERROR",
        lineAt(m.index),
        `all-lowercase visual copy "${words.join(" ").slice(0, 48)}" — use sentence case or mark exact source casing`,
        "case.all-lowercase",
      );
    }
    if (LITERAL_TEXT_TAGS.includes(tag) || hasExplicitCaseOverride(attrs)) continue;
    const shouted = literalAllCapsRun(words);
    if (shouted) {
      add(
        "ERROR",
        lineAt(m.index),
        `literal all-caps copy "${shouted.join(" ").slice(0, 48)}" — author it as "${sentenceCase(shouted)}" or mark an explicit user/reference casing request`,
        "case.all-caps",
      );
    }
  }

  // Words on the graphic follow the same copy rules as a drafted post. Literal code is exempt, and
  // an all-caps spelling the shouted-copy rule already reported is not reported twice.
  const literal = new Set();
  for (const m of visible.matchAll(/<(code|pre|kbd|samp)\b[^>]*>[\s\S]*?<\/\1\s*>/gi)) {
    for (let at = lineAt(m.index), end = lineAt(m.index + m[0].length); at <= end; at++) literal.add(at);
  }
  const shoutedLines = new Set(findings.filter((f) => f.rule === "case.all-caps").map((f) => f.line));
  if (extname(file).toLowerCase() === ".css") return; // a stylesheet carries no copy
  visibleLines.forEach((raw, i) => {
    if (!literal.has(i + 1)) lintCopyLine(raw, i + 1, { skipUppercase: shoutedLines.has(i + 1) });
  });
}

// ---------- WCAG 2.1 text contrast (design mode) ----------
// Token-legal is not the same as legible: two approved palette colors can sit at well under 2:1.
// This resolves each text node's effective foreground and background by walking the layered
// backgrounds above it (alpha-compositing as it goes) and fails the pair that cannot be read.
function parseColor(raw) {
  const value = (raw || "").replace(/\s*!important\s*$/i, "").trim();
  if (!value || /gradient\(|\bcurrentcolor\b|\binherit\b|var\(/i.test(value)) return null;
  const named = value.match(/\b(white|black|transparent)\b/i);
  const source = named ? NAMED_COLORS.get(named[1].toLowerCase()) : value;
  const hex = source.match(/#([0-9a-f]{3}|[0-9a-f]{6})\b/i);
  if (hex) {
    const h = normHex(hex[1]).slice(1);
    return { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16), a: 1 };
  }
  const rgb = source.match(/rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)\s*(?:[,/]\s*([\d.]+%?))?\s*\)/i);
  if (!rgb) return null;
  const alpha = rgb[4] === undefined ? 1 : rgb[4].endsWith("%") ? parseFloat(rgb[4]) / 100 : Number(rgb[4]);
  return { r: Number(rgb[1]), g: Number(rgb[2]), b: Number(rgb[3]), a: alpha };
}

const overlay = (top, bottom) =>
  top.a >= 1
    ? top
    : {
        r: top.r * top.a + bottom.r * (1 - top.a),
        g: top.g * top.a + bottom.g * (1 - top.a),
        b: top.b * top.a + bottom.b * (1 - top.a),
        a: bottom.a,
      };
const channelLuminance = (v) => (v / 255 <= 0.03928 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4);
const luminance = (c) =>
  0.2126 * channelLuminance(c.r) + 0.7152 * channelLuminance(c.g) + 0.0722 * channelLuminance(c.b);
const contrast = (a, b) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
const hexOf = (c) =>
  "#" + [c.r, c.g, c.b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("").toUpperCase();

function elementNodes({ keepSvg = false } = {}) {
  const stripped = source
    .replace(/<!--[\s\S]*?-->/g, mask)
    .replace(/<style\b[^>]*>[\s\S]*?<\/style\b[^>]*>/gi, mask)
    .replace(/<script\b[^>]*>[\s\S]*?<\/script\b[^>]*>/gi, mask);
  // SVG paints with fill/stroke, not color, so the contrast pass drops it; the connector pass needs it.
  const visible = keepSvg ? stripped : stripped.replace(/<svg\b[^>]*>[\s\S]*?<\/svg\b[^>]*>/gi, mask);
  const nodes = [];
  const open = [];
  let cursor = 0;
  for (const m of visible.matchAll(/<(\/?)([a-z][\w-]*)([^>]*)>/gi)) {
    const between = visible.slice(cursor, m.index).trim();
    if (open.length && between) nodes[open.at(-1)].text += ` ${between}`;
    cursor = m.index + m[0].length;
    const tag = m[2].toLowerCase();
    if (m[1]) {
      const at = open.findLastIndex((index) => nodes[index].tag === tag);
      if (at >= 0) open.length = at;
      continue;
    }
    nodes.push({ tag, attrs: m[3], line: lineAt(m.index), parent: open.length ? open.at(-1) : -1, text: "" });
    if (!VOID_TAGS.has(tag) && !/\/\s*$/.test(m[3])) open.push(nodes.length - 1);
  }
  return nodes;
}

// Attribute- and ancestor-aware match, used only here. A themed component carries its ground on
// `#root[data-theme="light"]` and a two-scene block scopes its type with `.scene-b .title`, so a
// matcher that drops attribute selectors or ancestor context reads dark blocks as light and invents
// contrast failures. Pseudo-class / pseudo-element rules are not the default state.
function compoundMatches(compound, node) {
  if (/::?[a-z]/i.test(compound.replace(/\[[^\]]*\]/g, ""))) return false;
  for (const attribute of compound.matchAll(/\[([\w-]+)(?:\s*([~^$*|]?=)\s*["']?([^\]"']*)["']?)?\]/g)) {
    const actual = node.attrs.match(new RegExp(`\\b${attribute[1]}\\s*=\\s*["']([^"']*)["']`, "i"))?.[1];
    if (actual === undefined) return false;
    if (attribute[2] === "=" && actual !== attribute[3]) return false;
    if (attribute[2] === "~=" && !actual.split(/\s+/).includes(attribute[3])) return false;
  }
  const stripped = compound.replace(/\[[^\]]*\]/g, "");
  const id = stripped.match(/#([\w-]+)/)?.[1];
  if (id && id !== (node.attrs.match(/\bid\s*=\s*["']([^"']+)["']/i)?.[1] || "")) return false;
  const classes = new Set(
    (node.attrs.match(/\bclass\s*=\s*["']([^"']+)["']/i)?.[1] || "").split(/\s+/).filter(Boolean),
  );
  if ([...stripped.matchAll(/\.([\w-]+)/g)].some((m) => !classes.has(m[1]))) return false;
  const tag = stripped.match(/^[a-z][\w-]*/i)?.[0];
  if (tag && tag.toLowerCase() !== node.tag) return false;
  return Boolean(tag || id || classes.size > 0 || compound.includes("["));
}

// Right-to-left descendant matching. Sibling combinators cannot be resolved from this shallow tree,
// so a rule that uses one is skipped rather than guessed at.
function matchesNode(selector, index, nodes) {
  if (/[+~]/.test(selector)) return false;
  const compounds = selector.split(/[\s>]+/).filter(Boolean);
  if (!compounds.length) return false;
  if (!compoundMatches(compounds.at(-1), nodes[index])) return false;
  let at = nodes[index].parent;
  for (let i = compounds.length - 2; i >= 0; i--) {
    while (at >= 0 && !compoundMatches(compounds[i], nodes[at])) at = nodes[at].parent;
    if (at < 0) return false;
    at = nodes[at].parent;
  }
  return true;
}

function lintTextContrast() {
  const rules = cssRules();
  const rootVars = new Map();
  for (const [selector, rule] of rules) {
    if (selector !== ":root" && selector !== "html") continue;
    for (const [property, declared] of rule.declarations) rootVars.set(property, declared.value);
  }

  const nodes = elementNodes();
  const styles = nodes.map((node, index) => {
    const merged = new Map();
    for (const [selector, rule] of rules) {
      if (!matchesNode(selector, index, nodes)) continue;
      for (const [property, declared] of rule.declarations) merged.set(property, declared.value);
    }
    const inline = node.attrs.match(/\bstyle\s*=\s*(["'])([\s\S]*?)\1/i)?.[2] || "";
    for (const [property, declared] of declarations(inline, 0)) merged.set(property, declared.value);
    return merged;
  });

  const chain = (index) => {
    const path = [];
    for (let at = index; at >= 0; at = nodes[at].parent) path.push(at);
    return path;
  };
  // Custom properties inherit, so resolve them from the node's own chain before the brand defaults —
  // that is what keeps a dark theme block reading as dark.
  const resolveAt = (index, value, depth = 0) => {
    if (depth > 4 || !value.includes("var(")) return value;
    const next = value.replace(/var\(\s*(--[\w-]+)\s*(?:,\s*([^()]{0,120}))?\)/g, (_, name, fallback) => {
      for (const at of chain(index)) {
        const declared = styles[at].get(name);
        if (declared) return declared;
      }
      return rootVars.get(name) ?? TOKEN_VARS.get(name) ?? (fallback || "").trim();
    });
    return next === value ? value : resolveAt(index, next, depth + 1);
  };
  const declared = (index, property) => {
    for (const at of chain(index)) {
      const value = styles[at].get(property);
      if (value) return { at, value: resolveAt(index, value) };
    }
    return null;
  };

  const fontSizeAt = (index) => {
    const found = declared(index, "font-size");
    if (!found) return 16;
    const px = /^([\d.]+)px/.exec(found.value);
    if (px) return Number(px[1]);
    const rem = /^([\d.]+)rem/.exec(found.value);
    if (rem) return Number(rem[1]) * 16;
    const em = /^([\d.]+)em/.exec(found.value);
    if (em && nodes[found.at].parent >= 0) return Number(em[1]) * fontSizeAt(nodes[found.at].parent);
    return null; // vmin / % / clamp — a responsive comp; judged as large text below
  };
  const fontWeightAt = (index) => {
    const found = declared(index, "font-weight");
    if (!found) return 400;
    if (/\bbold\b/i.test(found.value)) return 700;
    return Number.parseInt(found.value, 10) || 400;
  };
  const backgroundAt = (index) => {
    let stacked = null;
    for (const at of chain(index)) {
      const raw = styles[at].get("background-color") || styles[at].get("background");
      if (!raw) continue;
      const color = parseColor(resolveAt(index, raw));
      if (!color) return null; // gradient or image ground — a static read cannot prove a violation
      if (color.a === 0) continue;
      stacked = stacked ? overlay(stacked, color) : color;
      if (stacked.a >= 1) return stacked;
    }
    return null;
  };

  nodes.forEach((node, index) => {
    const text = node.text.replace(/&(?:#\d{1,8}|#x[\da-f]{1,8}|[a-z]{1,32});/gi, " ").trim();
    if (!text || !/[A-Za-z0-9]/.test(text)) return;
    const background = backgroundAt(index);
    const foreground = declared(index, "color") && parseColor(declared(index, "color").value);
    // `color: transparent` + background-clip:text paints the glyphs from a gradient; the readable
    // color is not in the cascade, so a static read cannot prove anything about it.
    if (!background || !foreground || foreground.a === 0) return;
    const ink = foreground.a < 1 ? overlay(foreground, background) : foreground;
    const ratio = contrast(luminance(ink), luminance(background));

    const size = fontSizeAt(index);
    const large = size === null || size >= LARGE_PX || (size >= LARGE_BOLD_PX && fontWeightAt(index) >= BOLD_WEIGHT);
    const floor = large ? WCAG_LARGE : WCAG_NORMAL;
    if (ratio >= floor) return;
    add(
      "ERROR",
      node.line,
      `text "${text.slice(0, 40)}" reads ${ratio.toFixed(2)}:1 — ${hexOf(ink)} on ${hexOf(background)} needs ${floor}:1 (WCAG 2.1, ${large ? "large" : "normal"} text${size === null ? ", size not stated in px" : ` at ${size}px`})`,
      "contrast.wcag",
    );
  });
}

// ---------- diagram connectors (design mode) ----------
// A hand-authored diagram inside an HTML comp keeps producing the same three defects: literal stroke
// widths that stop scaling with the rest of the system, an arrowhead redrawn per line, and elbows glued
// from separate segments that leave a gap at the join. The rules come from the pack's
// diagramConstruction. Scope is explicit in the markup so decorative SVG (patterns, logos, icons)
// stays out — a `data-brand-role="diagram"` subtree, or
// any inline <svg> that draws a directed connector, since an arrowhead is evidence of a real diagram.
// Inside that region the rules still only reach the connector layer: a declared connector for the stroke
// token, a triangle standing on a line end for the arrowhead, a chained corner for the assembly.
const PATH_ARITY = { m: 2, l: 2, h: 1, v: 1, c: 6, s: 4, q: 4, t: 2, a: 7, z: 0 };

function lineage(nodes, index) {
  const path = [];
  for (let at = index; at >= 0; at = nodes[at].parent) path.push(at);
  return path;
}

function attrValue(attrs, name) {
  return attrs.match(new RegExp(`\\b${name}\\s*=\\s*["']([^"']*)["']`, "i"))?.[1];
}

// Current-point walk over `d`. Only the two terminals matter, so control points are stepped over, and an
// unparseable command abandons the read rather than guessing a coordinate.
function pathTerminals(d) {
  const tokens = d.match(/[a-z]|[+-]?(?:\d*\.\d+|\d+)(?:e[+-]?\d+)?/gi) || [];
  let command = "";
  let x = 0;
  let y = 0;
  let subpathX = 0;
  let subpathY = 0;
  let start = null;
  for (let i = 0; i < tokens.length; ) {
    if (/^[a-z]$/i.test(tokens[i])) command = tokens[i++];
    const key = command.toLowerCase();
    const arity = PATH_ARITY[key];
    if (arity === undefined) return null;
    const args = tokens.slice(i, i + arity).map(Number);
    if (args.length < arity || args.some((value) => !Number.isFinite(value))) return null;
    i += arity;
    if (arity === 0 && i < tokens.length && !/^[a-z]$/i.test(tokens[i])) return null;
    const relative = command === key;
    if (key === "z") {
      x = subpathX;
      y = subpathY;
    } else if (key === "h") {
      x = relative ? x + args[0] : args[0];
    } else if (key === "v") {
      y = relative ? y + args[0] : args[0];
    } else {
      x = relative ? x + args[arity - 2] : args[arity - 2];
      y = relative ? y + args[arity - 1] : args[arity - 1];
    }
    if (key === "m") {
      subpathX = x;
      subpathY = y;
      command = relative ? "l" : "L"; // extra coordinate pairs after a moveto are implicit linetos
    }
    if (!start) start = [x, y];
  }
  return start ? { start, end: [x, y] } : null;
}

function connectorTerminals(node) {
  if (node.tag === "line") {
    const ends = ["x1", "y1", "x2", "y2"].map((name) => Number(attrValue(node.attrs, name)));
    if (ends.some((value) => !Number.isFinite(value))) return null;
    return { start: [ends[0], ends[1]], end: [ends[2], ends[3]] };
  }
  if (node.tag === "path") {
    const d = attrValue(node.attrs, "d");
    return d ? pathTerminals(d) : null;
  }
  return null;
}

function lintDiagramConnectors() {
  const nodes = elementNodes({ keepSvg: true });
  const svgRoot = nodes.map(
    (_, index) => lineage(nodes, index).find((at) => nodes[at].tag === "svg") ?? -1,
  );
  const directed = new Set();
  nodes.forEach((node, index) => {
    if (svgRoot[index] < 0) return;
    if (node.tag === "marker" || /\bmarker-(?:end|start)\s*=/i.test(node.attrs)) {
      directed.add(svgRoot[index]);
    }
  });
  const gated = nodes.map(
    (_, index) =>
      svgRoot[index] >= 0 &&
      (directed.has(svgRoot[index]) ||
        lineage(nodes, index).some((at) => hasDiagramRole(nodes[at].attrs))) &&
      !lineage(nodes, index).some((at) => hasConnectorSourceOverride(nodes[at].attrs)),
  );
  const inside = (index, tag) =>
    lineage(nodes, index)
      .slice(1)
      .some((at) => nodes[at].tag === tag);

  // A custom property is substituted in CSS only, so `stroke-width="var(--brand-stroke)"` written as a
  // presentation attribute silently renders at the 1px default — that is a hard-code too, not a bind.
  const strokeRules = [...cssRules()].filter(([, rule]) => rule.declarations.has("stroke-width"));
  const bindHint = `var(${strokeToken}) (${strokeRatio} × the ${gridUnitPx}px grid = ${gridUnitPx * strokeRatio}px at reference scale), or declare renderer/vendored geometry with data-brand-connector`;

  nodes.forEach((node, index) => {
    if (!gated[index] || !connectorTags.has(node.tag) || !isConnector(node.attrs)) return;
    if (inside(index, "marker") || inside(index, "defs")) return;
    const inline = attrValue(node.attrs, "style") || "";
    const styled =
      inline.match(/(?:^|;)\s*stroke-width\s*:\s*([^;]+)/i)?.[1] ??
      winningRule(strokeRules, node.tag, node.attrs)?.[1].declarations.get("stroke-width").value;
    if (styled !== undefined) {
      const declared = styled.trim();
      if (/var\(/i.test(declared) || /^inherit$/i.test(declared)) return;
      add("ERROR", node.line, `<${node.tag}> hard-codes stroke-width "${declared}" — bind it to ${bindHint}`, "diagram.stroke-width");
      return;
    }
    const attribute = attrValue(node.attrs, "stroke-width");
    if (attribute === undefined) return;
    add(
      "ERROR",
      node.line,
      `<${node.tag}> sets stroke-width="${attribute}" as a presentation attribute, where var() never resolves — bind it in CSS with stroke-width: ${bindHint}`,
      "diagram.stroke-width",
    );
  });

  const markersBySvg = new Map();
  nodes.forEach((node, index) => {
    if (!gated[index] || node.tag !== "marker") return;
    const id = attrValue(node.attrs, "id") || "(unnamed)";
    markersBySvg.set(svgRoot[index], [
      ...(markersBySvg.get(svgRoot[index]) || []),
      { id, line: node.line },
    ]);
    if (!inside(index, "defs")) {
      add(
        "ERROR",
        node.line,
        `arrowhead <marker id="${id}"> is not in <defs> — define the one shared arrowhead in <defs> and point every connector at it with marker-end`,
        "diagram.marker-defs",
      );
    }
  });
  for (const markers of markersBySvg.values()) {
    if (markers.length <= maxArrowheadMarkers) continue;
    const extra = markers.slice(maxArrowheadMarkers);
    add(
      "ERROR",
      extra[0].line,
      `${markers.length} arrowhead <marker> definitions (${markers.map((m) => m.id).join(", ")}) — every head references ONE shared marker: keep "${markers[0].id}" and delete ${extra.map((m) => `"${m.id}"`).join(", ")}`,
      "diagram.marker-count",
    );
  }

  const segments = [];
  nodes.forEach((node, index) => {
    if (!gated[index] || !connectorTags.has(node.tag)) return;
    if (inside(index, "marker") || inside(index, "defs")) return;
    const terminals = connectorTerminals(node);
    if (!terminals) return;
    segments.push({
      index,
      tag: node.tag,
      line: node.line,
      terminals,
      heads: {
        start: /\bmarker-start\s*=/i.test(node.attrs),
        end: /\bmarker-end\s*=/i.test(node.attrs),
      },
    });
  });

  // Three points and a fill also describe a chevron, a wedge, a caret, a play glyph, and a legend marker.
  // What makes one an arrowhead is where it stands: over the end of a line it is a head redrawn by hand,
  // anywhere else in the frame it is a shape the diagram is entitled to.
  const standsOnALineEnd = (self, points) => {
    const bound = (axis) => [
      Math.min(...points.map((p) => p[axis])) - JOIN_EPSILON,
      Math.max(...points.map((p) => p[axis])) + JOIN_EPSILON,
    ];
    const [left, right] = bound(0);
    const [top, bottom] = bound(1);
    return segments.some(
      (segment) =>
        segment.index !== self &&
        [segment.terminals.start, segment.terminals.end].some(
          ([x, y]) => x >= left && x <= right && y >= top && y <= bottom,
        ),
    );
  };
  const pairs = (numbers) =>
    numbers.reduce((out, n, at) => (at % 2 ? out : [...out, [n, numbers[at + 1]]]), []);

  nodes.forEach((node, index) => {
    if (!gated[index] || inside(index, "marker")) return;
    if (node.tag === "polygon") {
      const points = attrValue(node.attrs, "points") || "";
      const numbers = points.trim().split(/[\s,]+/).filter(Boolean).map(Number);
      if (numbers.length !== 6 || numbers.some((n) => !Number.isFinite(n))) return;
      if (!standsOnALineEnd(index, pairs(numbers))) return;
      add(
        "ERROR",
        node.line,
        `hand-drawn arrowhead <polygon points="${points}"> — every head references one shared <marker> in <defs> via marker-end`,
        "diagram.hand-drawn-arrowhead",
      );
      return;
    }
    if (node.tag !== "path") return;
    const d = attrValue(node.attrs, "d")?.trim();
    if (!d || !/^M[\d.,\s+-]+(?:L[\d.,\s+-]+){2}Z$/i.test(d)) return;
    const numbers = (d.match(/[+-]?(?:\d*\.\d+|\d+)/g) || []).map(Number);
    if (numbers.length !== 6 || !standsOnALineEnd(index, pairs(numbers))) return;
    add(
      "ERROR",
      node.line,
      `hand-drawn arrowhead <path d="${d}"> — every head references one shared <marker> in <defs> via marker-end`,
      "diagram.hand-drawn-arrowhead",
    );
  });

  const meets = (a, b) =>
    Math.abs(a[0] - b[0]) <= JOIN_EPSILON && Math.abs(a[1] - b[1]) <= JOIN_EPSILON;
  const terminalsOf = (segment) =>
    ["start", "end"].map((side) => ({
      side,
      point: segment.terminals[side],
      head: segment.heads[side],
    }));
  for (let i = 0; i < segments.length; i++) {
    for (let j = i + 1; j < segments.length; j++) {
      // Two <path>s sharing an anchor is a legitimate fan-out. A <line> cannot hold a corner, so a
      // <line> that terminates where another connector terminates is one connector split in two —
      // unless the point is a node anchor rather than a corner, which the terminals say themselves:
      // fan-in ends where another ends, fan-out starts where another starts, and an arrowhead only
      // ever lands on the node it points at.
      if (segments[i].tag !== "line" && segments[j].tag !== "line") continue;
      const join = terminalsOf(segments[i]).find((a) =>
        terminalsOf(segments[j]).some(
          (b) => a.side !== b.side && !a.head && !b.head && meets(a.point, b.point),
        ),
      );
      if (!join) continue;
      add(
        "ERROR",
        segments[j].line,
        `connector assembled from separate segments: <${segments[i].tag}> on line ${segments[i].line} and <${segments[j].tag}> meet at ${join.point[0]},${join.point[1]} — draw the whole connector as ONE continuous <path> so the corner stays on shared coordinates`,
        "diagram.split-connector",
      );
    }
  }
}

// ---------- line-scoped design checks ----------
// A CSS value, allowing quoted family names but never running past the end of an attribute.
const CSS_VALUE = `((?:"[^"<>;{}]*"|'[^'<>;{}]*'|[^;{}"'<>])+)`;
const FONT_FAMILY_DECL = new RegExp(`font-family\\s*:\\s*${CSS_VALUE}`, "gi");
const FONT_SHORTHAND_DECL = new RegExp(`(?<![\\w-])font\\s*:\\s*${CSS_VALUE}`, "gi");
// In the `font` shorthand the family list follows the size (and optional /line-height).
const SHORTHAND_FAMILIES =
  /(?:^|\s)(?:\d*\.?\d+(?:px|em|rem|pt|pc|%|vw|vh|vmin|vmax|ch|ex)|xx-small|x-small|small|medium|large|x-large|xx-large)(?:\s*\/\s*\S+)?\s+(.+)$/i;
const RADIUS_DECL = new RegExp(`border(?:-(?:top|bottom)-(?:left|right)|-(?:start|end)-(?:start|end))?-radius\\s*:\\s*${CSS_VALUE}`, "gi");
const quote = (name) => `"${name}"`;

function lintFontStack(value, ln) {
  const families = fontFamilies(value);
  if (!families.length || CSS_WIDE.has(families[0].toLowerCase())) return;
  let offBrand = false;
  for (const family of families) {
    const name = family.toLowerCase();
    if (offFonts.has(name)) {
      offBrand = true;
      add("ERROR", ln, `off-brand font "${family}" — set type with the brand stacks (var(--brand-font-display), var(--brand-font-text), var(--brand-font-mono))`, "font.off-brand");
    } else if (!/^var\(/i.test(family) && !GENERIC_FAMILIES.has(name) && !okFonts.has(name)) {
      add("WARN", ln, `unrecognized font "${family}" — confirm it is a brand typeface`, "font.unrecognized");
    }
  }
  // Mono stacks are checked per declaration (lintMonoDeclarations); a custom property cannot be
  // resolved from one line, so only literal stacks are held to the lead-face rule here.
  if (offBrand || BRAND_FONT_TOKEN.test(value) || isMonoStack(value) || /^var\(/i.test(families[0])) return;
  const leads = [leadFaces.display, leadFaces.text].filter(Boolean);
  if (!leads.some((face) => face.toLowerCase() === families[0].toLowerCase())) {
    add(
      "ERROR",
      ln,
      `font stack leads with "${families[0]}" — brand stacks lead with ${leads.map(quote).join(" or ")}; the rest are fallbacks. Use var(--brand-font-display) or var(--brand-font-text)`,
      "font.lead",
    );
  }
}

function lintRadius(px, ln, where) {
  if (maxRadius === undefined || !(px > maxRadius)) return;
  if (px >= PILL_RADIUS_PX) {
    add("WARN", ln, `${where} ${px}px draws a pill or circle — confirm the brand uses fully rounded shapes (rectangles stop at ${maxRadius}px)`, "radius.pill");
  } else {
    add("ERROR", ln, `${where} ${px}px is rounder than the brand's ${maxRadius}px maximum — use a var(--brand-radius-*) token`, "radius.max");
  }
}

function lintDesign() {
  lines.forEach((raw, i) => {
    const ln = i + 1;

    // hex colors — skip SVG url(#id) refs, fragment links and JS selector strings like ("#id")
    for (const m of raw.matchAll(/#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b/g)) {
      const i0 = m.index;
      const p1 = raw[i0 - 1], p2 = raw[i0 - 2];
      if (p1 === "(" || (p2 === "(" && (p1 === '"' || p1 === "'"))) continue; // url(#id) / fn("#sel")
      if (/href\s*=\s*["']?$/i.test(raw.slice(Math.max(0, i0 - 16), i0))) continue; // href="#id"
      const hx = m[0];
      const h = normHex(hx);
      if (banned.has(h)) {
        const token = replacement.get(h);
        add(
          "ERROR",
          ln,
          token
            ? `banned color "${hx}" — use var(${token})${TOKEN_VARS.has(token) ? ` (${TOKEN_VARS.get(token)})` : ""}`
            : `banned color "${hx}" — use a palette color through a var(--brand-color-*) token`,
          "color.banned",
        );
      } else if (allow.has(h) || officialAsset.has(h)) {
        /* palette, or inside an official mark — not ours to restyle */
      } else if (ext.has(h)) {
        add("WARN", ln, `extended-palette color "${hx}" — for charts and diagrams; confirm the use`, "color.extended");
      } else {
        add("ERROR", ln, `off-palette color "${hx}" — not in the brand palette; use a var(--brand-color-*) token`, "color.off-palette");
      }
    }

    for (const m of raw.matchAll(FONT_FAMILY_DECL)) lintFontStack(m[1], ln);
    for (const m of raw.matchAll(FONT_SHORTHAND_DECL)) {
      const families = SHORTHAND_FAMILIES.exec(m[1].trim())?.[1];
      if (families) lintFontStack(families, ln);
    }

    for (const m of raw.matchAll(RADIUS_DECL)) {
      const values = [...m[1].matchAll(/(\d*\.?\d+)(px|rem)\b/gi)].map((v) => Number(v[1]) * (v[2].toLowerCase() === "rem" ? 16 : 1));
      if (values.length) lintRadius(Math.max(...values), ln, "border-radius");
    }
    for (const m of raw.matchAll(/<rect\b[^>]*?\br[xy]\s*=\s*["']?(\d*\.?\d+)/gi)) lintRadius(Number(m[1]), ln, "<rect> corner radius");
  });
  lintCreativeTypography();
  lintPixelGrid();
  lintTextContrast();
  lintDiagramConnectors();
}

// ---------- copy rules (copy mode, and the words on a graphic) ----------
const humanize = (name) => name.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();
const warnPatterns = (copyRules.warnPhrases || []).map((word) => ({
  word,
  re: new RegExp(`(?<![\\p{L}\\p{N}])${escapeRegExp(word)}(?![\\p{L}\\p{N}])`, "iu"),
}));

function lintCopyLine(raw, ln, { skipUppercase = false } = {}) {
  const text = raw.toLowerCase();
  for (const phrase of copyRules.bannedPhrases || []) {
    if (text.includes(phrase.toLowerCase())) add("ERROR", ln, `banned phrase "${phrase}"`, "copy.banned-phrase");
  }
  for (const { word, re } of warnPatterns) {
    if (re.test(raw)) add("WARN", ln, `review word "${word}" — ground it in a specific or cut it`, "copy.warn-phrase");
  }
  for (const [name, char] of Object.entries(copyRules.bannedChars || {})) {
    if (char && raw.includes(char)) add("ERROR", ln, `banned character "${char}" (${humanize(name)})`, "copy.banned-char");
  }
  for (const { re, spelling } of canonicalPatterns) {
    for (const m of raw.matchAll(re)) {
      if (m[0] === spelling || (skipUppercase && m[0] === m[0].toUpperCase())) continue;
      add("ERROR", ln, `"${m[0]}" — the canonical spelling is "${spelling}"`, "case.canonical");
    }
  }
}

function lintCopy() {
  let hashtags = 0;
  lines.forEach((raw, i) => {
    lintCopyLine(raw, i + 1);
    hashtags += (raw.match(/(?<![\p{L}\p{N}_&/#])#[\p{L}_][\p{L}\p{N}_]*/gu) || []).length;
  });
  const max = copyRules.maxHashtags ?? 3;
  if (hashtags > max) add("ERROR", 0, `${hashtags} hashtags — the brand allows at most ${max}`, "copy.hashtags");
}

copyMode ? lintCopy() : lintDesign();

// ---------- report ----------
const mode = copyMode ? "copy" : "design";
const located = findings
  .slice()
  .sort((a, b) => a.line - b.line)
  .map((f) => {
    const at = origins.findLast((o) => o.from <= f.line) ?? origins[0];
    return { severity: f.sev, file: at.file, line: f.line ? f.line - at.shift : 0, rule: f.rule, message: f.msg };
  });
const errors = located.filter((f) => f.severity === "ERROR").length;
const warnings = located.length - errors;
if (json) {
  console.log(JSON.stringify({ ok: errors === 0, mode, file: target, errors, warnings, findings: located }));
} else if (!located.length) {
  console.log(`✓ brand-lint (${mode}): ${target} — clean`);
} else {
  for (const f of located) console.log(`${f.severity === "ERROR" ? "✗" : "⚠"} ${f.file}:${f.line}  [${f.severity}] ${f.message}`);
  console.log(`\n${errors} error(s), ${warnings} warning(s) — ${mode} lint`);
}
process.exitCode = errors > 0 ? EXIT.FINDINGS : EXIT.PASS;
