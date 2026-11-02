// transforms.mjs — the allowlisted, declarative transform pipeline.
//
// The agent names an operation and its arguments; it never supplies an expression, a callback, or a
// regex. Every op is a fixed lookup in a frozen table, every argument is validated against the typed
// dataset first, and the chain is bounded so a model-authored spec cannot buy unbounded work.

import { fieldByName, withRows } from "./dataset-contract.mjs";

const MAX_OPS = 12;
const MAX_BINS = 60;
const COMPARATORS = Object.freeze({
  eq: (a, b) => a === b,
  neq: (a, b) => a !== b,
  gt: (a, b) => a > b,
  gte: (a, b) => a >= b,
  lt: (a, b) => a < b,
  lte: (a, b) => a <= b,
});
const AGGREGATORS = Object.freeze({
  sum: (values) => values.reduce((total, value) => total + value, 0),
  mean: (values) => values.reduce((total, value) => total + value, 0) / values.length,
  median: (values) => {
    const sorted = [...values].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
  },
  min: (values) => Math.min(...values),
  max: (values) => Math.max(...values),
  count: (values) => values.length,
});

const CATALOG = Object.freeze({
  filter: Object.freeze(["field", "op", "value"]),
  sort: Object.freeze(["field", "direction"]),
  topN: Object.freeze(["field", "count", "direction"]),
  aggregate: Object.freeze(["groupBy", "field", "op", "as"]),
  bin: Object.freeze(["field", "binCount", "as"]),
  normalize: Object.freeze(["field", "as"]),
  percentChange: Object.freeze(["field", "as"]),
  cumulative: Object.freeze(["field", "as"]),
});

function fail(message) {
  throw new Error(`transform: ${message}`);
}

function exactFields(value, allowed, name) {
  const unknown = Object.keys(value).filter((key) => key !== "type" && !allowed.includes(key));
  if (unknown.length > 0) fail(`${name} has unsupported fields: ${unknown.join(", ")}`);
}

function enumValue(value, allowed, fallback, name) {
  const selected = value ?? fallback;
  if (typeof selected !== "string" || !allowed.includes(selected)) {
    fail(`${name} must be one of: ${allowed.join(", ")}`);
  }
  return selected;
}

function outputName(op, fallback) {
  if (op.as === undefined) return fallback;
  if (typeof op.as !== "string" || op.as.trim() === "") fail("as must be non-empty text");
  return op.as;
}

function measureOf(dataset, name, label) {
  if (typeof name !== "string") fail(`${label} must name a measure`);
  return fieldByName(dataset, name, "measure");
}

function replaceField(fields, name, next) {
  const index = fields.findIndex((field) => field.name === name);
  if (index < 0) return [...fields, next];
  return fields.map((field, position) => (position === index ? next : field));
}

function applyFilter(dataset, op) {
  const field = fieldByName(dataset, op.field);
  const comparator = Object.hasOwn(COMPARATORS, op.op) ? COMPARATORS[op.op] : undefined;
  const isIn = op.op === "in";
  if (!comparator && !isIn) fail(`filter op must be one of: ${Object.keys(COMPARATORS).join(", ")}, in`);
  if (isIn) {
    if (!Array.isArray(op.value) || op.value.length === 0 || op.value.length > 64) {
      fail("filter with op \"in\" needs a value array of 1-64 entries");
    }
    const allowed = new Set(op.value);
    return withRows(dataset, dataset.fields, dataset.rows.filter((row) => allowed.has(row[field.name])));
  }
  if (field.type === "measure" && typeof op.value !== "number") fail(`filter on ${field.name} needs a numeric value`);
  if (field.type !== "measure" && typeof op.value !== "string") fail(`filter on ${field.name} needs a text value`);
  return withRows(dataset, dataset.fields, dataset.rows.filter((row) => comparator(row[field.name], op.value)));
}

function applySort(dataset, op) {
  const field = fieldByName(dataset, op.field);
  const direction = enumValue(op.direction, ["asc", "desc"], "asc", "sort direction");
  const sign = direction === "asc" ? 1 : -1;
  const rows = [...dataset.rows].sort((a, b) => {
    const left = a[field.name];
    const right = b[field.name];
    if (left === right) return 0;
    return (left < right ? -1 : 1) * sign;
  });
  return withRows(dataset, dataset.fields, rows);
}

function applyTopN(dataset, op) {
  if (!Number.isInteger(op.count) || op.count < 1 || op.count > 200) fail("topN count must be an integer 1-200");
  return withRows(dataset, dataset.fields, applySort(dataset, { field: op.field, direction: op.direction ?? "desc" }).rows.slice(0, op.count));
}

function applyAggregate(dataset, op) {
  const groupBy = fieldByName(dataset, op.groupBy);
  if (groupBy.type === "measure") fail("aggregate groupBy must be a dimension or temporal field");
  const source = measureOf(dataset, op.field, "aggregate field");
  const operation = enumValue(op.op, Object.keys(AGGREGATORS), "sum", "aggregate op");
  const target = outputName(op, source.name);

  const buckets = new Map(); // Map, not a plain object: model-authored keys never become properties
  for (const row of dataset.rows) {
    const key = row[groupBy.name];
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(row[source.name]);
  }
  const rows = [...buckets.entries()].map(([key, values]) => {
    const row = Object.create(null);
    row[groupBy.name] = key;
    row[target] = AGGREGATORS[operation](values);
    return row;
  });
  const measure = { ...source, name: target };
  return withRows(dataset, [groupBy, measure], rows);
}

function applyBin(dataset, op) {
  const source = measureOf(dataset, op.field, "bin field");
  const binCount = op.binCount ?? 10;
  if (!Number.isInteger(binCount) || binCount < 2 || binCount > MAX_BINS) {
    fail(`bin binCount must be an integer between 2 and ${MAX_BINS}`);
  }
  if (dataset.rows.length === 0) fail("bin needs at least one row");
  const values = dataset.rows.map((row) => row[source.name]);
  const low = Math.min(...values);
  const high = Math.max(...values);
  if (low === high) fail(`bin cannot split a constant field: ${source.name}`);
  const width = (high - low) / binCount;
  const counts = new Array(binCount).fill(0);
  for (const value of values) {
    const slot = value === high ? binCount - 1 : Math.floor((value - low) / width);
    counts[slot] += 1;
  }
  const precision = source.precision ?? 2;
  const target = outputName(op, "count");
  const label = { name: `${source.name} bin`, type: "dimension", unit: null, precision: null };
  const measure = { name: target, type: "measure", unit: null, precision: 0 };
  const rows = counts.map((count, index) => {
    const row = Object.create(null);
    row[label.name] = `${(low + width * index).toFixed(precision)}–${(low + width * (index + 1)).toFixed(precision)}`;
    row[target] = count;
    return row;
  });
  return withRows(dataset, [label, measure], rows);
}

function derive(dataset, op, label, compute) {
  const source = measureOf(dataset, op.field, `${label} field`);
  const target = outputName(op, source.name);
  const values = dataset.rows.map((row) => row[source.name]);
  const derived = compute(values, source);
  const rows = dataset.rows.map((row, index) => {
    const next = Object.create(null);
    for (const key of Object.keys(row)) next[key] = row[key];
    next[target] = derived[index];
    return next;
  });
  const measure = { ...source, name: target, ...(label === "normalize" || label === "percentChange" ? { unit: "%" } : {}) };
  return withRows(dataset, replaceField(dataset.fields, target, measure), rows);
}

function applyNormalize(dataset, op) {
  return derive(dataset, op, "normalize", (values) => {
    const total = values.reduce((sum, value) => sum + value, 0);
    if (total === 0) fail("normalize cannot divide by a zero total");
    return values.map((value) => (value / total) * 100);
  });
}

function applyPercentChange(dataset, op) {
  return derive(dataset, op, "percentChange", (values) => values.map((value, index) => {
    if (index === 0) return 0;
    const previous = values[index - 1];
    if (previous === 0) fail("percentChange cannot divide by a zero previous value");
    return ((value - previous) / Math.abs(previous)) * 100;
  }));
}

function applyCumulative(dataset, op) {
  return derive(dataset, op, "cumulative", (values) => {
    let running = 0;
    return values.map((value) => { running += value; return running; });
  });
}

const OPS = Object.freeze({
  filter: applyFilter,
  sort: applySort,
  topN: applyTopN,
  aggregate: applyAggregate,
  bin: applyBin,
  normalize: applyNormalize,
  percentChange: applyPercentChange,
  cumulative: applyCumulative,
});

export function transformCatalog() {
  return Object.fromEntries(Object.entries(CATALOG).map(([name, args]) => [name, [...args]]));
}

export function applyTransforms(dataset, ops) {
  if (ops === undefined) return { dataset, receipt: [] };
  if (!Array.isArray(ops)) fail("transforms must be an array");
  if (ops.length > MAX_OPS) fail(`transforms exceeds ${MAX_OPS} operations`);

  let current = dataset;
  const receipt = [];
  ops.forEach((op, index) => {
    if (!op || typeof op !== "object" || Array.isArray(op)) fail(`transforms[${index}] must be an object`);
    const type = op.type;
    // Fixed table lookup guarded by an own-property check — never dynamic dispatch on model text.
    if (typeof type !== "string" || !Object.hasOwn(OPS, type)) {
      fail(`transforms[${index}].type must be one of: ${Object.keys(OPS).join(", ")}`);
    }
    exactFields(op, CATALOG[type], `transforms[${index}]`);
    current = OPS[type](current, op);
    receipt.push({ type, rows: current.rows.length });
  });
  return { dataset: current, receipt };
}
