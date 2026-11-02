#!/usr/bin/env node
// viz.mjs: one JSON spec in, an on-brand SVG and PNG out, with a receipt of every number and check.
//
//   node viz.mjs --spec <spec.json|-> [--out <png>] [--svg-out <svg>] [--tokens <tokens.json>] [--validate-only]
//   node viz.mjs --list-kinds | --list-transforms
//
// Charts and stat cards render through ECharts on the server (SVG, no browser); diagrams lay out with
// D2; a cycle (flywheel) is computed geometry. sharp rasterises the SVG. Brand roles come from the
// active brand pack (/workspace/brand/tokens.json, or --tokens). Code computes every value; the spec
// names fields and supplies words.
//
// Before anything is written: dataset gates (zero baseline, units, percent totals, type floor), the
// graph contract (pinned topology hash, then an inverse audit of what was drawn), a palette audit
// (every colour in the SVG is a brand colour), a text audit (no label silently dropped) and a font
// check (the brand families resolve, so nothing renders in a fallback face).
//
// Prints one JSON line. Exit 0 written · 1 the spec, a gate or an audit failed (the message says which;
// fix the spec) · 2 the tool could not run (toolchain, d2, fontconfig or brand pack missing).

import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, relative, resolve, sep, isAbsolute } from "node:path";
import { BrandError, brandTheme, loadTokens, normalizeHex } from "./lib/brand-theme.mjs";
import { runChartGates, MIN_FONT_PX } from "./lib/chart-gates.mjs";
import { CHARTS, SpecError, frame, metrics } from "./lib/charts.mjs";
import { buildCycle } from "./lib/cycle.mjs";
import { LAYOUTS, ToolError, brandSvg, d2Size, d2Source, drawnGraph, fontFile, runD2 } from "./lib/d2.mjs";
import { auditRenderedGraph, graphTopology, normalizeGraphContract } from "./lib/graph-contract.mjs";
import { measureFont } from "./lib/measure.mjs";
import { transformCatalog } from "./lib/transforms.mjs";

const RENDER_DIR = process.env.DESIGN_AGENT_RENDER_DIR || "/opt/design-agent/render";
const DEFAULT_TOKENS = "/workspace/brand/tokens.json";
const COMMON = ["kind", "title", "caption", "theme", "colors", "data", "out", "svgOut", "width", "height", "pixelRatio"];

const KINDS = {
  bar: "dataset, transforms?, x, y, series?, stack?, orient?, highlight?, annotate?{at,text}, valueAxis?{min,max}, partToWhole?",
  line: "dataset, transforms?, x, y, series?, highlight?, valueAxis?",
  scatter: "dataset, transforms?, x, y, label?, size?, highlight?, xLabel?, yLabel?",
  heatmap: "dataset, transforms?, x, y, value, valueAxis?",
  waterfall: "dataset, transforms?, label, value, total?, totalLabel?, valueAxis?, partToWhole?",
  histogram: "dataset, transforms?, value, binCount?",
  sankey: "dataset, transforms?, source, target, value",
  "stat-card": "value, unit?, precision?, label, baseline?{value,label}, change?(ratio|percent|delta|none)",
  cycle: "contract, expectedTopologyHash?, highlight?, center?",
  diagram: `contract, expectedTopologyHash?, layout?(${LAYOUTS.join("|")}), direction?(right|down|left|up), groups?[{id,label,nodes}], highlight?`,
};

function toolchain(name) {
  try {
    return createRequire(join(RENDER_DIR, "package.json"))(name);
  } catch (error) {
    throw new ToolError(`${name} is not installed in ${RENDER_DIR} (${error.code || error.message}); run inside the sandbox or set DESIGN_AGENT_RENDER_DIR`);
  }
}

function args(argv) {
  const flags = {};
  const values = new Set(["spec", "out", "svg-out", "tokens"]);
  const booleans = new Set(["validate-only", "list-kinds", "list-transforms"]);
  for (let i = 0; i < argv.length; i++) {
    const name = argv[i].replace(/^--/, "");
    if (!argv[i].startsWith("--") || (!values.has(name) && !booleans.has(name))) throw new ToolError(`unknown argument ${argv[i]}`);
    if (booleans.has(name)) flags[name] = true;
    else {
      if (argv[i + 1] === undefined) throw new ToolError(`${argv[i]} needs a value`);
      flags[name] = argv[++i];
    }
  }
  return flags;
}

function confine(path, label) {
  const root = process.cwd();
  const abs = resolve(root, path);
  const rel = relative(root, abs);
  if (rel.startsWith(`..${sep}`) || rel === ".." || isAbsolute(rel)) throw new SpecError(`${label} must stay under ${root}: ${path}`);
  return abs;
}

// ---------------------------------------------------------------------------------------- audits

function cssColour(value) {
  const v = value.trim().toLowerCase();
  if (!v || ["none", "transparent", "currentcolor", "inherit"].includes(v) || v.startsWith("url(") || v === "source") return null;
  const hex = normalizeHex(v);
  if (hex) return hex;
  const m = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/.exec(v);
  if (m) {
    if (m[4] !== undefined && Number(m[4]) === 0) return null;
    return `#${[m[1], m[2], m[3]].map((x) => Number(x).toString(16).padStart(2, "0")).join("")}`;
  }
  return v;
}

/** Every colour an element paints with, mapped to the first element that uses it. */
export function coloursIn(svg) {
  // Mask luminance (white shows, black hides) and clip geometry are not paint.
  svg = svg.replace(/<mask\b[\s\S]*?<\/mask>/g, "").replace(/<clipPath\b[\s\S]*?<\/clipPath>/g, "");
  const found = new Map();
  const add = (v, where) => {
    const c = cssColour(v);
    if (c && !found.has(c)) found.set(c, where.replace(/\s+/g, " ").slice(0, 160));
  };
  for (const [tag, , attrs] of svg.matchAll(/<([a-zA-Z]+)\b([^>]*)>/g)) {
    const props = Object.fromEntries([...attrs.matchAll(/([\w-]+)="([^"]*)"/g)].map(([, k, v]) => [k, v]));
    for (const [, k, v] of (props.style || "").matchAll(/([\w-]+)\s*:\s*([^;]+)/g)) props[k] = v.trim();
    const zero = (k) => props[k] !== undefined && Number(props[k]) === 0;
    if (zero("opacity")) continue;
    if (props.fill && !zero("fill-opacity")) add(props.fill, tag);
    if (props.stroke && !zero("stroke-opacity") && !zero("stroke-width")) add(props.stroke, tag);
    for (const k of ["stop-color", "flood-color"]) if (props[k]) add(props[k], tag);
  }
  for (const [, css] of svg.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/g)) {
    for (const m of css.matchAll(/(?:^|[;{\s])(?:fill|stroke|stop-color)\s*:\s*([^;}]+)/g)) add(m[1], m[0]);
  }
  return found;
}

const entities = (s) => s.replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n))).replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
  .replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");

function textsIn(svg) {
  return [...svg.matchAll(/<text\b[^>]*>([\s\S]*?)<\/text>/g)].map((m) => entities(m[1].replace(/<[^>]+>/g, "")).trim());
}

function audit(svg, theme, expectedTexts) {
  const colours = coloursIn(svg);
  const offPalette = [...colours.keys()].filter((c) => !theme.palette.has(c));
  if (offPalette.length) {
    throw new SpecError(`off-palette colours in the render: ${offPalette.map((c) => `${c} (in ${colours.get(c)})`).join("; ")}`);
  }
  const drawn = textsIn(svg);
  const missing = expectedTexts.filter((t) => t && !drawn.some((d) => d === t || d.includes(t)));
  if (missing.length) throw new SpecError(`labels missing from the render: ${missing.slice(0, 6).map((t) => JSON.stringify(t)).join(", ")}`);
  return { colours: [...colours.keys()].sort(), texts: drawn.length };
}

function checkFonts(families) {
  const checked = {};
  for (const family of families) {
    const run = spawnSync("fc-match", ["-f", "%{family[0]}", family], { encoding: "utf8", timeout: 15000 });
    if (run.error) throw new ToolError(`fc-match is not available (${run.error.code || run.error.message})`);
    if (run.stdout.trim().toLowerCase() !== family.toLowerCase()) {
      throw new SpecError(`brand font ${family} is not installed (it would render as ${run.stdout.trim() || "nothing"}); stage the brand fonts`);
    }
    checked[family] = true;
  }
  return checked;
}

function typeFloor(fontSizes) {
  const smallest = Math.min(...fontSizes);
  if (smallest < MIN_FONT_PX) throw new SpecError(`typographyFloor: smallest type renders at ${smallest.toFixed(1)}px, below ${MIN_FONT_PX}px; use a bigger canvas or fewer, shorter labels`);
  return { name: "typographyFloor", ok: true, detail: `smallest type renders at ${smallest.toFixed(1)}px` };
}

function contractFor(data) {
  const contract = normalizeGraphContract(data.contract);
  const topology = graphTopology(contract);
  if (data.expectedTopologyHash !== undefined && data.expectedTopologyHash !== topology.hash) {
    throw new SpecError(`topology changed: expected ${data.expectedTopologyHash}, the contract hashes to ${topology.hash}. A label, id, endpoint, direction or kind moved; drop the pin only if that was the intent`);
  }
  return { contract, topology };
}

// ---------------------------------------------------------------------------------------- render

function echartsSvg(echarts, option, theme, width, height) {
  const chart = echarts.init(null, null, { renderer: "svg", ssr: true, width, height });
  try {
    chart.setOption({ animation: false, backgroundColor: theme.ground, color: theme.series,
      textStyle: { fontFamily: theme.fonts.text, color: theme.ink }, ...option });
    // The server renderer adds :hover rules (lifted fills) for interactive embeds; a delivered still
    // has no pointer, and the palette audit should see only what is painted.
    return chart.renderToSVGString().replace(/[.#][\w-]+:hover\s*\{[^}]*\}/g, "");
  } finally {
    chart.dispose();
  }
}

function diagram(spec, theme, m, box, width, height, echarts, frameGraphics) {
  const d = spec.data || {};
  const allowed = ["contract", "expectedTopologyHash", "layout", "direction", "groups", "highlight"];
  const unknown = Object.keys(d).filter((k) => !allowed.includes(k));
  if (unknown.length) throw new SpecError(`data has unsupported fields: ${unknown.join(", ")}`);
  const { contract, topology } = contractFor(d);
  const layout = d.layout ?? "elk";
  const aw = width - box.left - box.right;
  const ah = height - box.top - box.bottom;
  const font = fontFile(theme.leadFamilies.text, theme.weights.text);
  if (font.matched.toLowerCase() !== theme.leadFamilies.text.toLowerCase()) {
    throw new SpecError(`brand font ${theme.leadFamilies.text} is not installed (fontconfig offers ${font.matched}); stage the brand fonts`);
  }
  let fontSize = Math.max(14, Math.round(26 * m.k));
  let svg = runD2(d2Source(contract, d, theme, { fontSize, layout }), { layout, fontPath: font.file });
  let size = d2Size(svg);
  const fit = (s) => Math.min(aw / s.w, ah / s.h);
  if (fit(size) < 0.9 || fit(size) > 1.15) {
    fontSize = Math.min(40, Math.max(12, Math.round(fontSize * Math.min(fit(size), 1.8))));
    svg = runD2(d2Source(contract, d, theme, { fontSize, layout }), { layout, fontPath: font.file });
    size = d2Size(svg);
  }
  const scale = Math.min(1, fit(size));
  const groupIds = new Set((d.groups || []).map((g) => g.id));
  const topologyAudit = auditRenderedGraph(drawnGraph(svg, groupIds), contract);
  const w = size.w * scale;
  const h = size.h * scale;
  const x = box.left + (aw - w) / 2;
  const y = box.top + (ah - h) / 2;
  const inner = brandSvg(svg, theme).replace(/<svg\b/, `<svg x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${w.toFixed(2)}" height="${h.toFixed(2)}"`);
  const framed = echartsSvg(echarts, { graphic: frameGraphics }, theme, width, height);
  const composed = framed.replace(/<\/svg>\s*$/, `${inner}</svg>`);
  const small = Math.max(12, Math.round(fontSize * 0.8));
  const texts = [...contract.nodes.map((n) => n.label), ...contract.edges.map((e) => e.label).filter(Boolean), ...(d.groups || []).map((g) => g.label)];
  return {
    svg: composed, texts, fontSizes: [fontSize * scale, small * scale],
    topology: { ...topologyAudit, layout, scale: Number(scale.toFixed(3)), strokePx: Number((theme.stroke * scale).toFixed(2)) },
    hash: topology.hash,
  };
}

async function main() {
  const flags = args(process.argv.slice(2));
  if (flags["list-kinds"]) return console.log(JSON.stringify({ ok: true, common: COMMON, kinds: KINDS }));
  if (flags["list-transforms"]) return console.log(JSON.stringify({ ok: true, transforms: transformCatalog() }));
  if (!flags.spec) throw new ToolError("usage: viz.mjs --spec <spec.json|-> [--out png] [--svg-out svg] [--tokens tokens.json] [--validate-only]");
  let spec;
  try {
    spec = JSON.parse(flags.spec === "-" ? readFileSync(0, "utf8") : readFileSync(flags.spec, "utf8"));
  } catch (error) {
    throw error.code ? new ToolError(`cannot read spec ${flags.spec}: ${error.code}`) : new SpecError(`spec is not JSON: ${error.message}`);
  }
  if (!spec || typeof spec !== "object" || Array.isArray(spec)) throw new SpecError("spec must be an object");
  const unknown = Object.keys(spec).filter((k) => !COMMON.includes(k));
  if (unknown.length) throw new SpecError(`spec has unsupported fields: ${unknown.join(", ")}`);
  if (!Object.hasOwn(KINDS, spec.kind)) throw new SpecError(`kind must be one of: ${Object.keys(KINDS).join(", ")}`);
  const width = spec.width ?? 1600;
  const height = spec.height ?? 900;
  if (![width, height].every((v) => Number.isInteger(v) && v >= 200 && v <= 4096)) throw new SpecError("width and height must be integers from 200 to 4096");
  const pixelRatio = spec.pixelRatio ?? 2;
  if (![1, 2].includes(pixelRatio)) throw new SpecError("pixelRatio must be 1 or 2");
  const validateOnly = Boolean(flags["validate-only"]);
  const out = validateOnly ? null : confine(flags.out ?? spec.out ?? "viz.png", "out");
  const svgOutPath = flags["svg-out"] ?? spec.svgOut;
  const svgOut = validateOnly || !svgOutPath ? null : confine(svgOutPath, "svgOut");

  const tokensPath = flags.tokens ?? DEFAULT_TOKENS;
  const theme = brandTheme(loadTokens(tokensPath), { mode: spec.theme ?? "light", roles: spec.colors ?? {} });
  const m = metrics(width, height, theme.gridUnit);
  const f = frame(spec, theme, m, width, height);
  const echarts = toolchain("echarts");
  echarts.setPlatformAPI({ measureText: measureFont });

  const receipt = { ok: true, kind: spec.kind, width, height, pixelRatio, tokens: tokensPath };
  let svg;
  let texts = [...f.texts];
  let fontSizes = [...f.fontSizes];
  let usesDisplay = Boolean(spec.title);
  if (spec.kind === "diagram") {
    const built = diagram(spec, theme, m, f.box, width, height, echarts, f.graphics);
    svg = built.svg;
    texts.push(...built.texts);
    fontSizes.push(...built.fontSizes);
    receipt.topology = built.topology;
    receipt.gates = [typeFloor(fontSizes)];
  } else if (spec.kind === "cycle") {
    const d = spec.data || {};
    const unknownData = Object.keys(d).filter((k) => !["contract", "expectedTopologyHash", "highlight", "center"].includes(k));
    if (unknownData.length) throw new SpecError(`data has unsupported fields: ${unknownData.join(", ")}`);
    const { contract } = contractFor(d);
    const plot = { x: f.box.left, y: f.box.top, w: width - f.box.left - f.box.right, h: height - f.box.top - f.box.bottom };
    const built = buildCycle(contract, d, theme, m, plot);
    texts.push(...built.texts);
    fontSizes.push(...built.fontSizes);
    usesDisplay ||= built.usesDisplay;
    receipt.topology = { ...auditRenderedGraph(built.drawn, contract), order: built.drawn.nodes };
    receipt.gates = [typeFloor(fontSizes)];
    if (!validateOnly) svg = echartsSvg(echarts, { graphic: [...f.graphics, ...built.graphics] }, theme, width, height);
  } else {
    const built = CHARTS[spec.kind](spec, theme, m, f.box, width, height);
    texts.push(...built.texts);
    fontSizes.push(...built.fontSizes);
    if (spec.kind === "stat-card") {
      usesDisplay = true;
      receipt.gates = [typeFloor(fontSizes)];
      receipt.computed = built.computed;
    } else {
      const gates = runChartGates({ kind: spec.kind, dataset: built.dataset, measures: built.measures, valueAxis: built.valueAxis,
        delivery: { fontSizes, authoredWidth: width, deliveredWidth: width }, partToWhole: built.partToWhole === true });
      if (!gates.ok) throw new SpecError(`chart gates failed: ${gates.checks.filter((c) => !c.ok).map((c) => `${c.name}: ${c.detail}`).join("; ")}`);
      receipt.chart = { datasetHash: built.dataset.hash, sourceHash: built.sourceHash, rows: built.dataset.rows.length, transforms: built.receipt };
      receipt.gates = gates.checks;
      if (built.total !== undefined) receipt.computed = { total: built.total };
      if (built.notes) receipt.notes = built.notes;
    }
    if (!validateOnly) svg = echartsSvg(echarts, { ...built.option, graphic: [...f.graphics, ...(built.option.graphic || [])] }, theme, width, height);
  }
  if (validateOnly) {
    receipt.validated = true;
    return console.log(JSON.stringify(receipt));
  }
  const families = [theme.leadFamilies.text, ...(usesDisplay ? [theme.leadFamilies.display] : [])];
  receipt.fonts = checkFonts([...new Set(families)]);
  receipt.audit = audit(svg, theme, texts);
  if (svgOut) {
    mkdirSync(dirname(svgOut), { recursive: true });
    writeFileSync(svgOut, svg);
    receipt.svgOut = relative(process.cwd(), svgOut);
  }
  const sharp = toolchain("sharp");
  mkdirSync(dirname(out), { recursive: true });
  const info = await sharp(Buffer.from(svg), { density: 72 * pixelRatio }).png({ compressionLevel: 9 }).toFile(out);
  if (info.width !== width * pixelRatio || info.height !== height * pixelRatio) {
    throw new ToolError(`rasteriser wrote ${info.width}x${info.height}, expected ${width * pixelRatio}x${height * pixelRatio}`);
  }
  receipt.out = relative(process.cwd(), out);
  receipt.png = { width: info.width, height: info.height, bytes: info.size };
  console.log(JSON.stringify(receipt));
}

main().catch((error) => {
  const tooling = error instanceof ToolError || error instanceof BrandError;
  const spec = error instanceof SpecError || /^(dataset|transform|gates|graph-contract):/.test(error.message);
  console.error(`viz: ${error.message}`);
  process.exitCode = tooling ? 2 : spec ? 1 : 2;
});
