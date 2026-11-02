// Pure-logic tests for the data-viz scripts: run with `node --test` (no toolchain, no browser).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const LIB = join(ROOT, "skills", "data-viz", "scripts", "lib");
const load = (name) => import(join(LIB, name));
const { normalizeDataset } = await load("dataset-contract.mjs");
const { applyTransforms } = await load("transforms.mjs");
const { runChartGates } = await load("chart-gates.mjs");
const { normalizeGraphContract, graphTopology, auditRenderedGraph } = await load("graph-contract.mjs");
const { brandTheme, loadTokens, contrast } = await load("brand-theme.mjs");
const { CHARTS, formatValue, metrics, frame, SpecError } = await load("charts.mjs");
const { loopOrder, buildCycle } = await load("cycle.mjs");
const { d2Source, drawnGraph } = await load("d2.mjs");
const { wrap, textWidth } = await load("measure.mjs");

const TOKENS = join(ROOT, "examples", "brands", "example-studio", "tokens.json");
const tokens = loadTokens(TOKENS);
const palette = new Set([...tokens.design.allowedColors, ...tokens.design.extendedPalette.colors].map((c) => c.toLowerCase()));
const theme = brandTheme(tokens, { roles: { ground: "--brand-color-paper" } });

const dataset = (rows, unit = "min") => ({
  fields: [{ name: "month", type: "dimension" }, { name: "minutes", type: "measure", unit, precision: 0 }],
  rows,
});

test("a dataset refuses prototype keys, undeclared fields and silent nulls", () => {
  assert.throws(() => normalizeDataset({ fields: [{ name: "__proto__", type: "measure" }], rows: [] }), /reserved key|must match/);
  assert.throws(() => normalizeDataset({ ...dataset([{ month: "Jan", minutes: 1, extra: 2 }]) }), /undeclared/);
  assert.throws(() => normalizeDataset(dataset([{ month: "Jan", minutes: null }])), /nullPolicy/);
  const skipped = normalizeDataset({ ...dataset([{ month: "Jan", minutes: null }, { month: "Feb", minutes: 3 }]), nullPolicy: "skip" });
  assert.equal(skipped.rows.length, 1);
});

test("the dataset hash is a receipt: same data, same hash; edited data, new hash", () => {
  const a = normalizeDataset(dataset([{ month: "Jan", minutes: 3 }]));
  const b = normalizeDataset(dataset([{ month: "Jan", minutes: 3 }]));
  const c = normalizeDataset(dataset([{ month: "Jan", minutes: 4 }]));
  assert.equal(a.hash, b.hash);
  assert.notEqual(a.hash, c.hash);
});

test("transforms compute shares, totals and bins in code", () => {
  const source = normalizeDataset(dataset([{ month: "Jan", minutes: 30 }, { month: "Feb", minutes: 10 }, { month: "Jan", minutes: 10 }]));
  const { dataset: summed } = applyTransforms(source, [{ type: "aggregate", groupBy: "month", field: "minutes", op: "sum", as: "total" }]);
  assert.deepEqual(summed.rows.map((r) => [r.month, r.total]), [["Jan", 40], ["Feb", 10]]);
  const { dataset: shares } = applyTransforms(summed, [{ type: "normalize", field: "total", as: "share" }]);
  assert.equal(shares.rows.reduce((s, r) => s + r.share, 0), 100);
  assert.throws(() => applyTransforms(source, [{ type: "eval", code: "1" }]), /type must be one of/);
});

test("gates fail closed on a truncated baseline, mixed units and shares that miss 100%", () => {
  const ds = normalizeDataset(dataset([{ month: "Jan", minutes: 5 }, { month: "Feb", minutes: 6 }]));
  const bad = runChartGates({ kind: "bar", dataset: ds, measures: ["minutes"], valueAxis: { min: 4 } });
  assert.equal(bad.ok, false);
  assert.match(bad.checks.find((c) => !c.ok).detail, /truncates the baseline/);
  assert.equal(runChartGates({ kind: "line", dataset: ds, measures: ["minutes"], valueAxis: { min: 4 } }).ok, true);
  const pct = normalizeDataset(dataset([{ month: "Jan", minutes: 40 }, { month: "Feb", minutes: 50 }], "%"));
  assert.equal(runChartGates({ kind: "bar", dataset: pct, measures: ["minutes"], partToWhole: true }).ok, false);
  const mixed = normalizeDataset({ fields: [{ name: "a", type: "measure", unit: "s" }, { name: "b", type: "measure", unit: "$" }], rows: [{ a: 1, b: 2 }] });
  assert.equal(runChartGates({ kind: "bar", dataset: mixed, measures: ["a", "b"] }).ok, false);
  assert.equal(runChartGates({ kind: "bar", dataset: ds, measures: ["minutes"], delivery: { fontSizes: [9] } }).ok, false);
});

test("the topology hash ignores order and catches a moved label or a reversed edge", () => {
  const contract = (labelA = "A", reverse = false) => normalizeGraphContract({
    version: 1,
    nodes: [{ id: "a", label: labelA }, { id: "b", label: "B" }],
    edges: [{ id: "e", from: reverse ? "b" : "a", to: reverse ? "a" : "b", kind: "flow" }],
  });
  const base = graphTopology(contract()).hash;
  const reordered = normalizeGraphContract({ version: 1, nodes: [{ id: "b", label: "B" }, { id: "a", label: "A" }], edges: [{ id: "e", from: "a", to: "b", kind: "flow" }] });
  assert.equal(graphTopology(reordered).hash, base);
  assert.notEqual(graphTopology(contract("A2")).hash, base);
  assert.notEqual(graphTopology(contract("A", true)).hash, base);
  assert.equal(auditRenderedGraph({ nodes: ["a", "b"], edges: [{ from: "a", to: "b", directed: true }] }, contract()).ok, true);
  assert.throws(() => auditRenderedGraph({ nodes: ["a", "b"], edges: [{ from: "b", to: "a", directed: true }] }, contract()), /not in the contract/);
  assert.throws(() => auditRenderedGraph({ nodes: ["a"], edges: [] }, contract()), /missing nodes/);
});

test("brand roles come from the brand pack's palette, with readable text", () => {
  for (const role of ["ground", "ink", "accent", "muted", "quiet", "rule"]) assert.ok(palette.has(theme[role]), `${role} ${theme[role]} is in the palette`);
  for (const c of [...theme.series, ...theme.ramp]) assert.ok(palette.has(c), `${c} is in the palette`);
  assert.equal(theme.ground, "#f6f1e7");
  assert.equal(theme.accent, "#ff5a36");
  assert.ok(!theme.series.includes(theme.accent), "the accent is never a series colour");
  assert.ok(contrast(theme.ink, theme.ground) >= 7);
  assert.ok(contrast(theme.muted, theme.ground) >= 4.5);
  assert.match(theme.fonts.display, /^'Geist'/);
  assert.throws(() => brandTheme(tokens, { roles: { ground: "--brand-color-nope" } }), /unknown token/);
});

test("the pack's roles win over the measurement, and a spec's pin over both", () => {
  const graphite = tokens.design.tokens["--brand-color-graphite"];
  const paper = tokens.design.tokens["--brand-color-paper"];
  const withRoles = structuredClone(tokens);
  withRoles.design.roles = { light: { accent: "--brand-color-graphite", series: ["--brand-color-paper"] } };
  const assigned = brandTheme(withRoles);
  assert.equal(assigned.accent, graphite.toLowerCase());
  assert.deepEqual(assigned.series, [paper.toLowerCase()]);
  assert.equal(brandTheme(withRoles, { mode: "dark" }).accent, theme.accent, "a mode without roles is measured");
  assert.equal(brandTheme(withRoles, { roles: { accent: "--brand-color-paper" } }).accent, paper.toLowerCase());
  withRoles.design.roles.light.muted = "--brand-color-nope";
  assert.throws(() => brandTheme(withRoles), /roles\.light\.muted: unknown token/);
});

test("numbers are formatted from the field's unit and precision", () => {
  assert.equal(formatValue(1200, { unit: "$", precision: 0 }), "$1,200");
  assert.equal(formatValue(72.04, { unit: "%", precision: 1 }), "72%");
  assert.equal(formatValue(34, { unit: "min", precision: 0 }), "34 min");
  assert.equal(formatValue(-5, { unit: "$", precision: 0 }), "-$5");
});

const m = metrics(1600, 900, 8);
const box = frame({}, theme, m, 1600, 900).box;

test("a bar chart computes its labels and puts the accent on the highlight only", () => {
  const spec = { kind: "bar", data: { dataset: dataset([{ month: "Jan", minutes: 96 }, { month: "Apr", minutes: 34 }]), x: "month", y: "minutes", highlight: "Apr", annotate: { at: "Apr", text: "One page per size" } } };
  const built = CHARTS.bar(spec, theme, m, box, 1600, 900);
  const colours = built.option.series[0].data.map((d) => d.itemStyle.color);
  assert.deepEqual(colours, [theme.quiet, theme.accent]);
  assert.ok(built.texts.includes("34 min") && built.texts.includes("One page per size"));
  assert.throws(() => CHARTS.bar({ ...spec, data: { ...spec.data, highlight: "Dec" } }, theme, m, box, 1600, 900), SpecError);
});

test("more than three series need a highlight", () => {
  const rows = ["a", "b", "c", "d"].flatMap((s) => [{ month: "Jan", s, minutes: 1 }]);
  const ds = { fields: [{ name: "month", type: "dimension" }, { name: "s", type: "dimension" }, { name: "minutes", type: "measure" }], rows };
  assert.throws(() => CHARTS.line({ data: { dataset: ds, x: "month", y: "minutes", series: "s" } }, theme, m, box, 1600, 900), /need a highlight/);
  const ok = CHARTS.line({ data: { dataset: ds, x: "month", y: "minutes", series: "s", highlight: "c" } }, theme, m, box, 1600, 900);
  assert.equal(ok.option.series.filter((s) => s.lineStyle.color === theme.accent).length, 1);
});

test("a waterfall's running total and a stat card's change are computed", () => {
  const ds = { fields: [{ name: "step", type: "dimension" }, { name: "h", type: "measure", unit: "h", precision: 0 }],
    rows: [{ step: "Start", h: 40 }, { step: "Templates", h: -12 }, { step: "Review", h: 4 }] };
  assert.equal(CHARTS.waterfall({ data: { dataset: ds, label: "step", value: "h", total: true } }, theme, m, box, 1600, 900).total, 32);
  const card = CHARTS["stat-card"]({ data: { value: 48, label: "Stills per hour", baseline: { value: 12, label: "Up from" } } }, theme, metrics(1080, 1080, 8), box, 1080, 1080);
  assert.equal(card.computed.compare, "Up from 12 (4×)");
  const pct = CHARTS["stat-card"]({ data: { value: 30, unit: "%", label: "Share", baseline: { value: 20, label: "From" }, change: "percent" } }, theme, m, box, 1600, 900);
  assert.equal(pct.computed.compare, "From 20% (+50%)");
});

const loop = (edges) => normalizeGraphContract({
  version: 1,
  nodes: ["brief", "draft", "review", "ship"].map((id) => ({ id, label: id[0].toUpperCase() + id.slice(1) })),
  edges,
});

test("a cycle follows its edges and refuses anything that is not one loop", () => {
  const ring = loop([["brief", "draft"], ["draft", "review"], ["review", "ship"], ["ship", "brief"]].map(([from, to], i) => ({ id: `e${i}`, from, to, kind: "flow" })));
  assert.deepEqual(loopOrder(ring).order, ["brief", "draft", "review", "ship"]);
  const built = buildCycle(ring, { highlight: "review" }, theme, metrics(1080, 1080, 8), { x: 88, y: 88, w: 904, h: 904 });
  assert.equal(built.graphics.filter((g) => g.type === "arc").length, 4);
  assert.equal(built.graphics.filter((g) => g.type === "rect" && g.style.fill === theme.accent).length, 1);
  const broken = loop([["brief", "draft"], ["draft", "brief"], ["review", "ship"], ["ship", "review"]].map(([from, to], i) => ({ id: `e${i}`, from, to, kind: "flow" })));
  assert.throws(() => loopOrder(broken), SpecError);
});

test("D2 source is generated with escaped labels and brand styles, and drawn edges read back", () => {
  const contract = normalizeGraphContract({
    version: 1,
    nodes: [{ id: "cost", label: 'Cost $1.2M "quoted"' }, { id: "b", label: "B" }],
    edges: [{ id: "e", from: "cost", to: "b", kind: "flow", label: "next" }],
  });
  const source = d2Source(contract, { groups: [{ id: "g", label: "Group", nodes: ["b"] }], highlight: "b" }, theme, { fontSize: 20, layout: "elk" });
  assert.match(source, /"cost": "Cost \\\$1\.2M \\"quoted\\""/);
  assert.match(source, /"cost" -> "g"\."b": "next"/);
  assert.ok(source.includes(theme.accent) && source.includes(theme.ink));
  assert.ok(!/#0D32B2/i.test(source), "no D2 default theme colour");
  const b64 = (s) => Buffer.from(s).toString("base64");
  const svg = [`<g class="${b64("cost")}">`, `<g class="${b64("g")}">`, `<g class="${b64("g.b")} node">`,
    `<g class="${b64("(cost -&gt; g.b)[0]")}">`, `<g class="${b64("g.(b -- b)[0]")}">`].join("");
  const drawn = drawnGraph(svg, new Set(["g"]));
  assert.deepEqual(drawn.nodes.sort(), ["b", "cost"]);
  assert.deepEqual(drawn.edges, [{ from: "cost", to: "b", directed: true }, { from: "b", to: "b", directed: false }]);
});

test("two-line wraps are balanced and refuse what cannot fit", () => {
  assert.deepEqual(wrap("Review with the team", 27, 216), ["Review with", "the team"]);
  assert.equal(wrap("Supercalifragilistic expialidocious", 40, 100), null);
  assert.ok(textWidth("mmm", 20) > textWidth("iii", 20));
});

test("the examples parse and name only kinds the renderer knows", () => {
  for (const name of ["bar-annotated", "flywheel-cycle", "stat-card", "diagram-flow"]) {
    const spec = JSON.parse(readFileSync(join(ROOT, "skills", "data-viz", "examples", `${name}.json`), "utf8"));
    assert.ok(["bar", "cycle", "stat-card", "diagram"].includes(spec.kind), name);
  }
});
