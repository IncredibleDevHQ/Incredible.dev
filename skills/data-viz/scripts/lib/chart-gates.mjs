// chart-gates.mjs — deterministic correctness gates for semantic charts.
//
// These catch the failures a visual judge reliably false-passes: a truncated baseline that exaggerates
// a difference, part-to-whole shares that do not sum to the whole, one value axis carrying two units,
// and type that is unreadable at the delivery size. Every gate is a pure function over the typed
// dataset and the render descriptor, and the receipt names the exact reason it failed.

const BASELINE_KINDS = new Set(["bar", "grouped", "stacked", "waterfall", "histogram"]);
const PERCENT_TOLERANCE = 0.5;
const MIN_FONT_PX = 12;

function plainObject(value, name) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`gates: ${name} must be an object`);
  }
  return value;
}

function measuresOf(dataset, names) {
  const selected = names ?? dataset.fields.filter((field) => field.type === "measure").map((field) => field.name);
  return selected.map((name) => {
    const field = dataset.fields.find((candidate) => candidate.name === name);
    if (!field) throw new Error(`gates: unknown measure: ${name}`);
    if (field.type !== "measure") throw new Error(`gates: ${name} is not a measure`);
    return field;
  });
}

// A bar or histogram encodes magnitude by length, so a non-zero baseline misstates every ratio on the
// chart. Line and scatter encode position, where a zoomed range is legitimate.
function zeroBaseline(kind, dataset, measures, valueAxis) {
  if (!BASELINE_KINDS.has(kind)) {
    return { name: "zeroBaseline", ok: true, detail: `${kind} does not encode magnitude by length` };
  }
  const values = dataset.rows.flatMap((row) => measures.map((field) => row[field.name]));
  const lowestValue = values.length > 0 ? Math.min(...values) : 0;
  const min = valueAxis.min ?? Math.min(0, lowestValue);
  if (min > 0) {
    return { name: "zeroBaseline", ok: false, detail: `${kind} value axis starts at ${min}, which truncates the baseline` };
  }
  return { name: "zeroBaseline", ok: true, detail: `value axis includes zero (min ${min})` };
}

function unitConsistency(measures) {
  const units = new Set(measures.map((field) => field.unit ?? "(none)"));
  if (units.size > 1) {
    return { name: "unitConsistency", ok: false, detail: `one value axis mixes units: ${[...units].join(", ")}` };
  }
  return { name: "unitConsistency", ok: true, detail: `single unit: ${[...units][0] ?? "(none)"}` };
}

function percentTotal(dataset, measures, partToWhole) {
  if (!partToWhole) return { name: "percentTotal", ok: true, detail: "not a part-to-whole chart" };
  const percentFields = measures.filter((field) => field.unit === "%");
  if (percentFields.length === 0) {
    return { name: "percentTotal", ok: true, detail: "no percent measure to reconcile" };
  }
  for (const field of percentFields) {
    const total = dataset.rows.reduce((sum, row) => sum + row[field.name], 0);
    if (Math.abs(total - 100) > PERCENT_TOLERANCE) {
      return { name: "percentTotal", ok: false, detail: `${field.name} sums to ${total.toFixed(2)}%, not 100%` };
    }
  }
  return { name: "percentTotal", ok: true, detail: "percent shares sum to 100%" };
}

// Fonts are authored in the render's own coordinate space; the delivered raster may be smaller. The
// floor is checked at the delivered scale, which is the size a reader actually sees.
function typographyFloor(delivery) {
  const { authoredWidth, deliveredWidth, fontSizes } = delivery;
  if (!Array.isArray(fontSizes) || fontSizes.length === 0) {
    return { name: "typographyFloor", ok: true, detail: "no type declared" };
  }
  const scale = authoredWidth && deliveredWidth ? deliveredWidth / authoredWidth : 1;
  const smallest = Math.min(...fontSizes) * scale;
  if (smallest < MIN_FONT_PX) {
    return {
      name: "typographyFloor",
      ok: false,
      detail: `smallest type renders at ${smallest.toFixed(1)}px, below the ${MIN_FONT_PX}px floor`,
    };
  }
  return { name: "typographyFloor", ok: true, detail: `smallest type renders at ${smallest.toFixed(1)}px` };
}

export function runChartGates({ kind, dataset, measures, valueAxis = {}, delivery = {}, partToWhole = false } = {}) {
  if (typeof kind !== "string" || kind === "") throw new Error("gates: kind is required");
  plainObject(dataset, "dataset");
  const selected = measuresOf(dataset, measures);
  const checks = [
    zeroBaseline(kind, dataset, selected, plainObject(valueAxis, "valueAxis")),
    unitConsistency(selected),
    percentTotal(dataset, selected, partToWhole === true),
    typographyFloor(plainObject(delivery, "delivery")),
  ];
  return { ok: checks.every((check) => check.ok), checks };
}

export { MIN_FONT_PX, PERCENT_TOLERANCE };
