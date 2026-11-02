// charts.mjs: typed dataset -> declared transforms -> gates -> an ECharts option in brand roles.
//
// The model names fields and words; code computes every value on the chart (pivots, totals, steps,
// bins, changes, ratios) and formats every number from the field's unit and precision. Colour follows
// one rule: up to three series get the brand's categorical colours; beyond that one series is the
// point (accent) and the rest are quiet, so a spec with more than three series must say which one.

import { fieldByName, normalizeDataset } from "./dataset-contract.mjs";
import { applyTransforms } from "./transforms.mjs";
import { textWidth, wrap } from "./measure.mjs";

export class SpecError extends Error {}
const fail = (message) => {
  throw new SpecError(message);
};

const MAX_CATEGORIES = 40;
const PREFIX_UNITS = new Set(["$", "€", "£", "¥"]);
const TIGHT_UNITS = new Set(["%", "×", "x"]);

export function formatValue(value, field) {
  if (value === null || value === undefined || value === "-") return "";
  const precision = field?.precision ?? 2;
  const text = Number(value).toLocaleString("en-US", { maximumFractionDigits: precision, minimumFractionDigits: 0 });
  const unit = field?.unit;
  if (!unit) return text;
  if (PREFIX_UNITS.has(unit)) return text.startsWith("-") ? `-${unit}${text.slice(1)}` : `${unit}${text}`;
  return TIGHT_UNITS.has(unit) ? `${text}${unit}` : `${text} ${unit}`;
}

/** Type sizes and margins for a canvas, from the 1600 x 900 reference. Never below 12 px. */
export function metrics(width, height, unit) {
  const k = Math.min(width / 1600, height / 900);
  const size = (px) => Math.max(12, Math.round(px * k));
  const margin = Math.max(2 * unit, Math.round((0.08 * Math.min(width, height)) / unit) * unit);
  return { k, unit, margin, title: size(56), axis: size(22), value: size(24), label: size(26), caption: size(18) };
}

/** Title (top left) and caption (bottom left) as graphic text; returns the plot box between them. */
export function frame(spec, theme, m, width, height) {
  const graphics = [];
  const texts = [];
  let top = m.margin;
  let bottom = m.margin;
  if (spec.title) {
    const lines = wrap(spec.title, m.title, width - 2 * m.margin, { maxLines: 2, weight: theme.weights.display });
    if (!lines) fail("title does not fit on two lines at this size: shorten it or drop it");
    lines.forEach((line, i) => {
      graphics.push({ type: "text", style: { text: line, x: m.margin, y: top + i * m.title * 1.1, align: "left",
        verticalAlign: "top", fill: theme.ink, font: `${theme.weights.display} ${m.title}px ${theme.fonts.display}` } });
      texts.push(line);
    });
    top += lines.length * m.title * 1.1 + 4 * m.unit;
  }
  if (spec.caption) {
    graphics.push({ type: "text", style: { text: spec.caption, x: m.margin, y: height - m.margin, align: "left",
      verticalAlign: "bottom", fill: theme.muted, font: `${theme.weights.text} ${m.caption}px ${theme.fonts.text}` } });
    texts.push(spec.caption);
    bottom += m.caption * 1.4 + 2 * m.unit;
  }
  return { graphics, texts, box: { left: m.margin, right: m.margin, top, bottom }, fontSizes: [spec.title ? m.title : null, spec.caption ? m.caption : null].filter(Boolean) };
}

function prepare(d, allowed) {
  if (!d || typeof d !== "object" || Array.isArray(d)) fail("data must be an object");
  const unknown = Object.keys(d).filter((key) => !allowed.includes(key));
  if (unknown.length) fail(`data has unsupported fields: ${unknown.join(", ")}`);
  const source = normalizeDataset(d.dataset);
  const { dataset, receipt } = applyTransforms(source, d.transforms);
  return { dataset, receipt, sourceHash: source.hash };
}

function dimension(dataset, name, label) {
  if (typeof name !== "string") fail(`data.${label} must name a field`);
  const field = fieldByName(dataset, name);
  if (field.type === "measure") fail(`data.${label} must be a dimension or temporal field, not a measure`);
  return field;
}

function uniqueInOrder(values) {
  return [...new Set(values)];
}

const axisText = (theme, m) => ({ color: theme.muted, fontFamily: theme.fonts.text, fontSize: m.axis, fontWeight: theme.weights.text });

function categoryAxis(theme, m, categories, plotWidth) {
  const longest = Math.max(0, ...categories.map((c) => textWidth(c, m.axis)));
  const slot = plotWidth / Math.max(categories.length, 1);
  return {
    type: "category",
    data: categories,
    axisLine: { show: true, lineStyle: { color: theme.ink, width: theme.stroke } },
    axisTick: { show: false },
    axisLabel: { ...axisText(theme, m), interval: 0, margin: m.unit * 2, rotate: longest > slot * 0.92 ? 30 : 0 },
    splitLine: { show: false },
  };
}

function valueAxis(theme, m, field, extra = {}) {
  return {
    type: "value",
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { ...axisText(theme, m), margin: m.unit * 2, formatter: (v) => formatValue(v, field) },
    splitLine: { show: true, lineStyle: { color: theme.rule, width: 1 } },
    ...extra,
  };
}

function grid(box, extra = {}) {
  return { left: box.left, right: box.right, top: box.top, bottom: box.bottom, containLabel: true, ...extra };
}

/** Colours for n series: categorical up to 3, otherwise the highlighted one is the point. */
function seriesColours(theme, names, highlight) {
  if (highlight !== undefined && !names.includes(highlight)) fail(`highlight "${highlight}" is not one of: ${names.join(", ")}`);
  if (highlight !== undefined) return names.map((n) => (n === highlight ? theme.accent : theme.quiet));
  if (names.length > 3) fail(`${names.length} series need a highlight: more than 3 categorical colours stop reading as categories`);
  if (names.length > theme.series.length) fail(`the brand palette has ${theme.series.length} series colours for ${names.length} series`);
  return names.map((_, i) => theme.series[i]);
}

function pivot(dataset, xField, yField, sField) {
  const categories = uniqueInOrder(dataset.rows.map((r) => r[xField.name]));
  if (categories.length > MAX_CATEGORIES) fail(`${categories.length} categories: at most ${MAX_CATEGORIES} read on one chart (use topN or aggregate)`);
  const names = sField ? uniqueInOrder(dataset.rows.map((r) => r[sField.name])) : [yField.name];
  const values = Object.fromEntries(names.map((n) => [n, categories.map(() => null)]));
  for (const row of dataset.rows) {
    const name = sField ? row[sField.name] : yField.name;
    const i = categories.indexOf(row[xField.name]);
    if (values[name][i] !== null) fail(`two rows for ${row[xField.name]}${sField ? ` / ${name}` : ""}: aggregate them first`);
    values[name][i] = row[yField.name];
  }
  return { categories, names, values };
}

function sanitizeRich(text) {
  return String(text).replace(/[{}|]/g, "");
}

// ------------------------------------------------------------------------------------------- kinds

function bar(spec, theme, m, box, width) {
  const d = spec.data;
  const { dataset, receipt, sourceHash } = prepare(d, ["dataset", "transforms", "x", "y", "series", "stack", "orient", "highlight", "annotate", "valueAxis", "partToWhole"]);
  const xField = dimension(dataset, d.x, "x");
  const yField = fieldByName(dataset, d.y, "measure");
  const sField = d.series === undefined ? null : dimension(dataset, d.series, "series");
  const { categories, names, values } = pivot(dataset, xField, yField, sField);
  const horizontal = d.orient === "horizontal";
  if (d.orient !== undefined && !["horizontal", "vertical"].includes(d.orient)) fail("data.orient must be horizontal or vertical");
  const single = names.length === 1;
  if (single && d.highlight !== undefined && !categories.includes(d.highlight)) fail(`highlight "${d.highlight}" is not a category`);
  const colours = single ? null : seriesColours(theme, names, d.highlight);
  const annotate = d.annotate;
  if (annotate !== undefined) {
    if (!single) fail("annotate works on a single-series bar chart");
    if (!annotate || typeof annotate.at !== "string" || typeof annotate.text !== "string") fail("annotate needs {at, text}");
    if (!categories.includes(annotate.at)) fail(`annotate.at "${annotate.at}" is not a category`);
    if (annotate.text.length > 60) fail("annotate.text is longer than 60 characters: say it in fewer words");
  }
  const plotWidth = width - box.left - box.right;
  const radius = horizontal ? [0, theme.barRadius, theme.barRadius, 0] : [theme.barRadius, theme.barRadius, 0, 0];
  const texts = [...categories];
  const series = names.map((name, si) => ({
    type: "bar",
    name,
    stack: d.stack ? "total" : undefined,
    barMaxWidth: Math.round(plotWidth / Math.max(categories.length * (d.stack ? 1 : names.length), 1) * 0.6),
    barGap: "12%",
    data: values[name].map((value, ci) => {
      const cat = categories[ci];
      const colour = single
        ? d.highlight === undefined ? theme.series[0] : cat === d.highlight ? theme.accent : theme.quiet
        : colours[si];
      const hero = single && (cat === d.highlight || cat === annotate?.at);
      const text = formatValue(value, yField);
      if (single) texts.push(text);
      const item = { value, itemStyle: { color: colour, borderRadius: d.stack ? 0 : radius } };
      if (single) {
        item.label = {
          show: true,
          position: horizontal ? "right" : "top",
          distance: m.unit,
          color: theme.ink,
          fontFamily: theme.fonts.text,
          fontSize: m.value,
          fontWeight: hero ? theme.weights.strong : theme.weights.text,
          formatter: () => text,
        };
        if (annotate && cat === annotate.at) {
          const note = sanitizeRich(annotate.text);
          texts.push(note);
          item.label.formatter = horizontal ? `{v|${text}}  {a|${note}}` : `{a|${note}}\n{v|${text}}`;
          item.label.rich = {
            v: { color: theme.ink, fontFamily: theme.fonts.text, fontSize: m.value, fontWeight: theme.weights.strong, lineHeight: m.value * 1.3 },
            a: { color: theme.muted, fontFamily: theme.fonts.text, fontSize: m.axis, fontWeight: theme.weights.text, lineHeight: m.axis * 1.5 },
          };
        }
      }
      return item;
    }),
  }));
  const cat = categoryAxis(theme, m, categories, plotWidth);
  const val = valueAxis(theme, m, yField, { min: d.valueAxis?.min, max: d.valueAxis?.max });
  if (single) {
    // Every bar carries its value, so a value axis would say each number twice.
    val.axisLabel = { show: false };
    val.splitLine = { show: false };
  }
  if (horizontal) cat.inverse = true;
  const legend = single ? undefined : {
    data: names, top: box.top, left: box.left, icon: "rect", itemWidth: m.unit * 2, itemHeight: m.unit * 2, itemGap: m.unit * 3,
    textStyle: { color: theme.ink, fontFamily: theme.fonts.text, fontSize: m.axis },
  };
  if (!single) texts.push(...names);
  const option = {
    grid: grid({ ...box, top: box.top + (single ? m.value * (annotate ? 2.6 : 1.4) : m.axis * 2 + m.unit * 3) }, horizontal ? { right: box.right + m.unit * 10 } : {}),
    xAxis: horizontal ? val : cat,
    yAxis: horizontal ? cat : val,
    legend,
    series,
  };
  return {
    option, texts, dataset, sourceHash, receipt, measures: [yField.name],
    valueAxis: d.valueAxis || {}, fontSizes: [m.axis, m.value], partToWhole: d.partToWhole === true,
  };
}

function line(spec, theme, m, box, width) {
  const d = spec.data;
  const { dataset, receipt, sourceHash } = prepare(d, ["dataset", "transforms", "x", "y", "series", "highlight", "valueAxis"]);
  const xField = dimension(dataset, d.x, "x");
  const yField = fieldByName(dataset, d.y, "measure");
  const sField = d.series === undefined ? null : dimension(dataset, d.series, "series");
  const { categories, names, values } = pivot(dataset, xField, yField, sField);
  const colours = names.length === 1 ? [theme.series[0]] : seriesColours(theme, names, d.highlight);
  const endText = (name) => (names.length === 1 ? formatValue(values[name].at(-1), yField) : name);
  const labelRoom = Math.max(...names.map((n) => textWidth(endText(n), m.axis))) + m.unit * 3;
  const texts = [...categories, ...names.map(endText)];
  const series = names.map((name, i) => {
    const hero = names.length === 1 || name === d.highlight;
    return {
      type: "line",
      name,
      data: values[name],
      showSymbol: false,
      smooth: false,
      z: hero ? 3 : 2,
      lineStyle: { color: colours[i], width: theme.stroke * (hero ? 1.5 : 1) },
      itemStyle: { color: colours[i] },
      endLabel: {
        show: true, distance: m.unit,
        color: hero ? theme.ink : theme.muted, fontFamily: theme.fonts.text, fontSize: m.axis,
        fontWeight: hero ? theme.weights.strong : theme.weights.text, formatter: () => endText(name),
      },
    };
  });
  return {
    option: {
      grid: grid({ ...box, top: box.top + m.unit * 2, right: box.right + labelRoom }),
      xAxis: { ...categoryAxis(theme, m, categories, width - box.left - box.right - labelRoom), boundaryGap: false },
      yAxis: valueAxis(theme, m, yField, { min: d.valueAxis?.min, max: d.valueAxis?.max, scale: d.valueAxis?.min === undefined }),
      series,
    },
    texts, dataset, sourceHash, receipt, measures: [yField.name], valueAxis: d.valueAxis || {}, fontSizes: [m.axis],
  };
}

function scatter(spec, theme, m, box) {
  const d = spec.data;
  const { dataset, receipt, sourceHash } = prepare(d, ["dataset", "transforms", "x", "y", "label", "size", "highlight", "xLabel", "yLabel"]);
  const xField = fieldByName(dataset, d.x, "measure");
  const yField = fieldByName(dataset, d.y, "measure");
  const lField = d.label === undefined ? null : dimension(dataset, d.label, "label");
  const sField = d.size === undefined ? null : fieldByName(dataset, d.size, "measure");
  if (dataset.rows.length > 200) fail("more than 200 points: aggregate or filter first");
  const maxSize = sField ? Math.max(...dataset.rows.map((r) => Math.abs(r[sField.name])), 1e-9) : 1;
  const names = lField ? dataset.rows.map((r) => r[lField.name]) : [];
  if (d.highlight !== undefined && !names.includes(d.highlight)) fail(`highlight "${d.highlight}" is not a label`);
  const texts = [...names];
  const data = dataset.rows.map((r) => {
    const name = lField ? r[lField.name] : "";
    const hero = name === d.highlight;
    const area = sField ? Math.abs(r[sField.name]) / maxSize : 0.35;
    return {
      value: [r[xField.name], r[yField.name]],
      name,
      symbolSize: Math.round(m.unit * 1.5 + Math.sqrt(area) * m.unit * 6),
      itemStyle: { color: d.highlight === undefined ? theme.series[0] : hero ? theme.accent : theme.quiet },
      label: {
        show: Boolean(name), position: "right", distance: m.unit, formatter: () => name,
        color: hero ? theme.ink : theme.muted, fontFamily: theme.fonts.text, fontSize: m.axis,
        fontWeight: hero ? theme.weights.strong : theme.weights.text,
      },
    };
  });
  // The y name sits beyond the widest tick label, so it never collides with one.
  const yTickWidth = Math.max(...dataset.rows.map((r) => textWidth(formatValue(r[yField.name], yField), m.axis))) * 1.3;
  const axisName = (text, gap) => ({ name: text || "", nameLocation: "middle", nameGap: gap, nameTextStyle: axisText(theme, m) });
  if (d.xLabel) texts.push(d.xLabel);
  if (d.yLabel) texts.push(d.yLabel);
  return {
    option: {
      grid: grid({ ...box, top: box.top + m.unit * 2, bottom: box.bottom + (d.xLabel ? m.axis * 2 : 0), left: box.left + (d.yLabel ? m.axis * 2 : 0) }),
      xAxis: { ...valueAxis(theme, m, xField, { scale: true }), ...axisName(d.xLabel, m.axis * 2.6), splitLine: { show: false },
        axisLine: { show: true, lineStyle: { color: theme.ink, width: theme.stroke } } },
      yAxis: { ...valueAxis(theme, m, yField, { scale: true }), ...axisName(d.yLabel, yTickWidth + m.unit * 3) },
      series: [{ type: "scatter", data }],
    },
    texts, dataset, sourceHash, receipt, measures: [xField.name], fontSizes: [m.axis], valueAxis: {},
  };
}

function heatmap(spec, theme, m, box) {
  const d = spec.data;
  const { dataset, receipt, sourceHash } = prepare(d, ["dataset", "transforms", "x", "y", "value", "valueAxis"]);
  const xField = dimension(dataset, d.x, "x");
  const yField = dimension(dataset, d.y, "y");
  const vField = fieldByName(dataset, d.value, "measure");
  const xs = uniqueInOrder(dataset.rows.map((r) => r[xField.name]));
  const ys = uniqueInOrder(dataset.rows.map((r) => r[yField.name]));
  if (xs.length * ys.length > 400) fail("more than 400 cells do not read as a heatmap");
  const vals = dataset.rows.map((r) => r[vField.name]);
  const lo = d.valueAxis?.min ?? Math.min(...vals);
  const hi = d.valueAxis?.max ?? Math.max(...vals);
  const steps = theme.ramp;
  const bucket = (v) => (hi === lo ? steps.length - 1 : Math.min(steps.length - 1, Math.max(0, Math.floor(((v - lo) / (hi - lo)) * steps.length))));
  const seen = new Set();
  const texts = [...xs, ...ys];
  const data = dataset.rows.map((r) => {
    const key = `${r[xField.name]}\u0000${r[yField.name]}`;
    if (seen.has(key)) fail(`two rows for ${r[xField.name]} / ${r[yField.name]}: aggregate them first`);
    seen.add(key);
    const fill = steps[bucket(r[vField.name])];
    const text = formatValue(r[vField.name], vField);
    texts.push(text);
    return {
      value: [xs.indexOf(r[xField.name]), ys.indexOf(r[yField.name]), r[vField.name]],
      itemStyle: { color: fill, borderColor: theme.ground, borderWidth: theme.stroke },
      label: { show: true, formatter: () => text, color: theme.onFill(fill), fontFamily: theme.fonts.text, fontSize: m.axis },
    };
  });
  const cat = (values) => ({ type: "category", data: values, axisLine: { show: false }, axisTick: { show: false },
    axisLabel: { ...axisText(theme, m), interval: 0 }, splitLine: { show: false } });
  // ECharts requires a visualMap for a heatmap; this one repeats the buckets above and draws nothing.
  const step = (hi - lo) / steps.length || 1;
  const pieces = steps.map((color, i) => (i === steps.length - 1 ? { gte: lo + i * step, color } : { gte: lo + i * step, lt: lo + (i + 1) * step, color }));
  return {
    option: {
      grid: grid({ ...box, top: box.top + m.unit }), xAxis: cat(xs), yAxis: { ...cat(ys), inverse: true },
      visualMap: { type: "piecewise", show: false, dimension: 2, pieces: [{ lt: lo, color: steps[0] }, ...pieces] },
      series: [{ type: "heatmap", data }],
    },
    texts, dataset, sourceHash, receipt, measures: [vField.name], fontSizes: [m.axis], valueAxis: {},
    notes: [`${steps.length} colour steps from ${formatValue(lo, vField)} to ${formatValue(hi, vField)}`],
  };
}

function waterfall(spec, theme, m, box, width) {
  const d = spec.data;
  const { dataset, receipt, sourceHash } = prepare(d, ["dataset", "transforms", "label", "value", "total", "totalLabel", "valueAxis", "partToWhole"]);
  const lField = dimension(dataset, d.label, "label");
  const vField = fieldByName(dataset, d.value, "measure");
  if (dataset.rows.length < 2) fail("a waterfall needs at least 2 steps");
  if (dataset.rows.length > 24) fail("a waterfall reads up to 24 steps");
  const labels = [];
  const base = [];
  const rise = [];
  const fall = [];
  const texts = [];
  let running = 0;
  const item = (v, colour, text) => ({ value: v, itemStyle: { color: colour, borderRadius: 0 }, label: { formatter: () => text } });
  for (const row of dataset.rows) {
    const delta = row[vField.name];
    labels.push(row[lField.name]);
    const text = `${delta >= 0 ? "+" : "−"}${formatValue(Math.abs(delta), vField)}`;
    texts.push(text);
    if (delta >= 0) {
      base.push(running); rise.push(item(delta, theme.series[0], text)); fall.push("-"); running += delta;
    } else {
      running += delta; base.push(running); rise.push("-"); fall.push(item(-delta, theme.quiet, text));
    }
  }
  if (d.total === true) {
    labels.push(d.totalLabel ?? "Total");
    base.push(0); fall.push("-");
    const text = formatValue(running, vField);
    texts.push(text);
    rise.push(item(running, theme.ink, text));
  }
  texts.push(...labels);
  const label = (position) => ({ show: true, position, distance: m.unit, color: theme.ink, fontFamily: theme.fonts.text, fontSize: m.value });
  const plotWidth = width - box.left - box.right;
  const barWidth = Math.round((plotWidth / labels.length) * 0.6);
  return {
    option: {
      grid: grid({ ...box, top: box.top + m.value * 2 }),
      xAxis: categoryAxis(theme, m, labels, plotWidth),
      yAxis: valueAxis(theme, m, vField, { min: d.valueAxis?.min, max: d.valueAxis?.max }),
      series: [
        { type: "bar", stack: "w", barWidth, data: base, itemStyle: { color: "none" }, silent: true },
        { type: "bar", stack: "w", barWidth, data: rise, label: label("top") },
        { type: "bar", stack: "w", barWidth, data: fall, label: label("bottom") },
      ],
    },
    texts, dataset, sourceHash, receipt, measures: [vField.name], valueAxis: d.valueAxis || {},
    fontSizes: [m.axis, m.value], partToWhole: d.partToWhole === true, total: running,
  };
}

function histogram(spec, theme, m, box, width) {
  const d = spec.data;
  const { dataset: source, receipt, sourceHash } = prepare(d, ["dataset", "transforms", "value", "binCount", "valueAxis"]);
  const vField = fieldByName(source, d.value, "measure");
  const { dataset, receipt: binReceipt } = applyTransforms(source, [{ type: "bin", field: vField.name, binCount: d.binCount ?? 10 }]);
  const binName = `${vField.name} bin`;
  const labels = dataset.rows.map((r) => r[binName]);
  const counts = dataset.rows.map((r) => r.count);
  const plotWidth = width - box.left - box.right;
  return {
    option: {
      grid: grid({ ...box, top: box.top + m.value * 2 }),
      xAxis: categoryAxis(theme, m, labels, plotWidth),
      yAxis: valueAxis(theme, m, { precision: 0 }, {}),
      series: [{ type: "bar", barCategoryGap: "6%", data: counts, itemStyle: { color: theme.series[0] },
        label: { show: true, position: "top", distance: m.unit, color: theme.ink, fontFamily: theme.fonts.text, fontSize: m.value } }],
    },
    texts: [...labels], dataset, sourceHash, receipt: [...receipt, ...binReceipt], measures: ["count"],
    valueAxis: d.valueAxis || {}, fontSizes: [m.axis, m.value],
  };
}

function sankey(spec, theme, m, box) {
  const d = spec.data;
  const { dataset, receipt, sourceHash } = prepare(d, ["dataset", "transforms", "source", "target", "value"]);
  const sField = dimension(dataset, d.source, "source");
  const tField = dimension(dataset, d.target, "target");
  const vField = fieldByName(dataset, d.value, "measure");
  const nodes = uniqueInOrder(dataset.rows.flatMap((r) => [r[sField.name], r[tField.name]]));
  if (nodes.length > 30) fail("more than 30 nodes do not read as a flow");
  const inflow = Object.fromEntries(nodes.map((n) => [n, 0]));
  const outflow = Object.fromEntries(nodes.map((n) => [n, 0]));
  for (const r of dataset.rows) {
    if (r[vField.name] <= 0) fail("sankey flows must be positive");
    if (r[sField.name] === r[tField.name]) fail(`a flow cannot return to its own node: ${r[sField.name]}`);
    outflow[r[sField.name]] += r[vField.name];
    inflow[r[tField.name]] += r[vField.name];
  }
  const totals = Object.fromEntries(nodes.map((n) => [n, Math.max(inflow[n], outflow[n])]));
  const texts = nodes.map((n) => `${n} ${formatValue(totals[n], vField)}`);
  return {
    option: {
      series: [{
        type: "sankey", left: box.left, right: box.right + m.unit * 24, top: box.top + m.unit, bottom: box.bottom,
        nodeWidth: m.unit * 2, nodeGap: m.unit * 2, layoutIterations: 64, draggable: false,
        data: nodes.map((n, i) => ({ name: n, itemStyle: { color: theme.series[i % Math.min(theme.series.length, 3)], borderWidth: 0 } })),
        links: dataset.rows.map((r) => ({ source: r[sField.name], target: r[tField.name], value: r[vField.name] })),
        lineStyle: { color: "source", opacity: 0.35, curveness: 0.5 },
        label: { color: theme.ink, fontFamily: theme.fonts.text, fontSize: m.axis, formatter: (p) => `${p.name} ${formatValue(totals[p.name], vField)}` },
      }],
    },
    texts, dataset, sourceHash, receipt, measures: [vField.name], valueAxis: {}, fontSizes: [m.axis],
  };
}

function change(value, baseline, mode, field) {
  if (mode === "none") return "";
  if (mode === "ratio") {
    if (baseline === 0) fail("a ratio against a baseline of 0 is undefined: use delta");
    return `${Number((value / baseline).toFixed(1)).toLocaleString("en-US")}×`;
  }
  if (mode === "percent") {
    if (baseline === 0) fail("a percent change from 0 is undefined: use delta");
    const pct = ((value - baseline) / Math.abs(baseline)) * 100;
    return `${pct >= 0 ? "+" : "−"}${Number(Math.abs(pct).toFixed(1)).toLocaleString("en-US")}%`;
  }
  if (mode === "delta") {
    const delta = value - baseline;
    return `${delta >= 0 ? "+" : "−"}${formatValue(Math.abs(delta), field)}`;
  }
  return fail("data.change must be ratio, percent, delta or none");
}

function statCard(spec, theme, m, box, width, height) {
  const d = spec.data;
  if (!d || typeof d !== "object") fail("data must be an object");
  const unknown = Object.keys(d).filter((k) => !["value", "unit", "precision", "label", "baseline", "change"].includes(k));
  if (unknown.length) fail(`data has unsupported fields: ${unknown.join(", ")}`);
  if (typeof d.value !== "number" || !Number.isFinite(d.value)) fail("data.value must be a number");
  if (typeof d.label !== "string" || !d.label.trim()) fail("data.label must say what the number counts");
  const field = { unit: d.unit, precision: d.precision ?? 1 };
  const big = formatValue(d.value, field);
  let compare = "";
  if (d.baseline !== undefined) {
    const b = d.baseline;
    if (!b || typeof b.value !== "number" || typeof b.label !== "string") fail("data.baseline needs {value, label}");
    const delta = change(d.value, b.value, d.change ?? "ratio", field);
    compare = `${b.label} ${formatValue(b.value, field)}${delta ? ` (${delta})` : ""}`;
  }
  const avail = width - box.left - box.right;
  let bigSize = Math.round(Math.min(height * 0.42, width * 0.5));
  while (textWidth(big, bigSize, { weight: theme.weights.display }) > avail && bigSize > m.title) bigSize -= 4;
  const labelSize = Math.max(Math.round(m.title * 0.9), 16);
  const compareSize = Math.max(Math.round(labelSize * 0.75), 14);
  const ruleH = theme.stroke * 3;
  // Text boxes are one em tall and figures sit at about 0.17-0.9 em inside the number's box, so the
  // gaps are set from the figures, not the box.
  const blockH = ruleH + m.unit * 4 + bigSize * 0.73 + m.unit * 4 + labelSize * 1.25 + (compare ? m.unit * 2 + compareSize * 1.3 : 0);
  let y = box.top + Math.max(0, (height - box.top - box.bottom - blockH) / 2);
  const x = box.left;
  const graphics = [{ type: "rect", shape: { x, y, width: m.unit * 8, height: ruleH }, style: { fill: theme.accent } }];
  y += ruleH + m.unit * 4 - bigSize * 0.17;
  graphics.push({ type: "text", style: { text: big, x, y, align: "left", verticalAlign: "top", fill: theme.ink,
    font: `${theme.weights.display} ${bigSize}px ${theme.fonts.display}` } });
  y += bigSize * 0.9 + m.unit * 4;
  const labelLines = wrap(d.label, labelSize, avail, { maxLines: 2 });
  if (!labelLines) fail("data.label does not fit on two lines: say it in fewer words");
  for (const lineText of labelLines) {
    graphics.push({ type: "text", style: { text: lineText, x, y, align: "left", verticalAlign: "top", fill: theme.ink,
      font: `${theme.weights.text} ${labelSize}px ${theme.fonts.text}` } });
    y += labelSize * 1.25;
  }
  if (compare) {
    y += m.unit * 2;
    graphics.push({ type: "text", style: { text: compare, x, y, align: "left", verticalAlign: "top", fill: theme.muted,
      font: `${theme.weights.text} ${compareSize}px ${theme.fonts.text}` } });
  }
  return { option: { graphic: graphics }, texts: [big, ...labelLines, ...(compare ? [compare] : [])], fontSizes: [bigSize, labelSize, compareSize],
    computed: { value: big, compare } };
}

export const CHARTS = { bar, line, scatter, heatmap, waterfall, histogram, sankey, "stat-card": statCard };
