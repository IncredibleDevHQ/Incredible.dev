// dataset-contract.mjs — the typed dataset every semantic chart kind consumes.
//
// The agent DESCRIBES data as fields + rows; this module proves the description is well-formed before
// any transform, gate, or renderer touches it. Specs are model-authored, so they are untrusted input:
// unknown keys, prototype-polluting names, non-finite numbers, and unbounded row counts all fail closed.

import { createHash } from "node:crypto";

const FIELD_NAME = /^[A-Za-z][A-Za-z0-9_ -]{0,63}$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z)?$/;
const FORBIDDEN_KEYS = new Set(["__proto__", "constructor", "prototype"]);
const FIELD_TYPES = new Set(["dimension", "measure", "temporal"]);
const NULL_POLICIES = new Set(["reject", "zero", "skip"]);
const FIELD_FIELDS = new Set(["name", "type", "unit", "precision"]);
const DATASET_FIELDS = new Set(["fields", "rows", "nullPolicy"]);

export const LIMITS = Object.freeze({ fields: 64, rows: 5000, unit: 16, dimension: 120 });

function fail(message) {
  throw new Error(`dataset: ${message}`);
}

function plainObject(value, name) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(`${name} must be an object`);
  return value;
}

function exactFields(value, allowed, name) {
  const unknown = Object.keys(value).filter((key) => !allowed.has(key));
  if (unknown.length > 0) fail(`${name} has unsupported fields: ${unknown.join(", ")}`);
}

// A model-authored key named __proto__/constructor/prototype must never reach an accumulator or a
// row object. Every row map in this pipeline is null-prototype, and the name itself is refused here.
function safeName(value, name) {
  if (typeof value !== "string" || !FIELD_NAME.test(value)) fail(`${name} must match ${FIELD_NAME}`);
  if (FORBIDDEN_KEYS.has(value)) fail(`${name} uses a reserved key: ${value}`);
  return value;
}

function finiteNumber(value, name) {
  if (typeof value !== "number" || !Number.isFinite(value)) fail(`${name} must be a finite number`);
  return value === 0 ? 0 : value; // normalize -0 so hashes and gate verdicts stay stable
}

function normalizeField(raw, index) {
  plainObject(raw, `fields[${index}]`);
  exactFields(raw, FIELD_FIELDS, `fields[${index}]`);
  const name = safeName(raw.name, `fields[${index}].name`);
  const type = raw.type;
  if (typeof type !== "string" || !FIELD_TYPES.has(type)) {
    fail(`fields[${index}].type must be one of: ${[...FIELD_TYPES].join(", ")}`);
  }
  if (raw.unit !== undefined) {
    if (type !== "measure") fail(`fields[${index}].unit is only valid on a measure`);
    if (typeof raw.unit !== "string" || raw.unit.trim() === "" || raw.unit.length > LIMITS.unit) {
      fail(`fields[${index}].unit must be 1-${LIMITS.unit} characters`);
    }
  }
  if (raw.precision !== undefined) {
    if (type !== "measure") fail(`fields[${index}].precision is only valid on a measure`);
    if (!Number.isInteger(raw.precision) || raw.precision < 0 || raw.precision > 6) {
      fail(`fields[${index}].precision must be an integer between 0 and 6`);
    }
  }
  return Object.freeze({
    name,
    type,
    unit: type === "measure" ? (raw.unit ?? null) : null,
    precision: type === "measure" ? (raw.precision ?? 2) : null,
  });
}

function normalizeCell(value, field, rowIndex, nullPolicy) {
  const label = `rows[${rowIndex}].${field.name}`;
  if (value === null || value === undefined) {
    if (nullPolicy === "reject") fail(`${label} is null and nullPolicy is "reject"`);
    if (nullPolicy === "zero") return field.type === "measure" ? 0 : "";
    return null; // "skip" — the row is dropped after the whole row is inspected
  }
  if (field.type === "measure") return finiteNumber(value, label);
  if (typeof value !== "string" || value.trim() === "") fail(`${label} must be non-empty text`);
  if (value.length > LIMITS.dimension) fail(`${label} exceeds ${LIMITS.dimension} characters`);
  if (field.type === "temporal" && !ISO_DATE.test(value)) fail(`${label} must be an ISO-8601 date`);
  return value;
}

export function normalizeDataset(input) {
  plainObject(input, "data.dataset");
  exactFields(input, DATASET_FIELDS, "data.dataset");

  const nullPolicy = input.nullPolicy ?? "reject";
  if (typeof nullPolicy !== "string" || !NULL_POLICIES.has(nullPolicy)) {
    fail(`nullPolicy must be one of: ${[...NULL_POLICIES].join(", ")}`);
  }

  if (!Array.isArray(input.fields) || input.fields.length === 0) fail("fields must be a non-empty array");
  if (input.fields.length > LIMITS.fields) fail(`fields exceeds ${LIMITS.fields} entries`);
  const fields = input.fields.map(normalizeField);

  const seen = new Set();
  for (const field of fields) {
    if (seen.has(field.name)) fail(`duplicate field name: ${field.name}`);
    seen.add(field.name);
  }

  if (!Array.isArray(input.rows)) fail("rows must be an array");
  if (input.rows.length > LIMITS.rows) fail(`rows exceeds ${LIMITS.rows} entries`);

  const rows = [];
  input.rows.forEach((raw, rowIndex) => {
    plainObject(raw, `rows[${rowIndex}]`);
    const unknown = Object.keys(raw).filter((key) => !seen.has(key));
    if (unknown.length > 0) fail(`rows[${rowIndex}] has undeclared fields: ${unknown.join(", ")}`);
    const row = Object.create(null);
    let skip = false;
    for (const field of fields) {
      const cell = normalizeCell(raw[field.name], field, rowIndex, nullPolicy);
      if (cell === null) skip = true;
      else row[field.name] = cell;
    }
    if (!skip) rows.push(row);
  });

  return Object.freeze({ fields, rows, nullPolicy, hash: datasetHash(fields, rows) });
}

function datasetHash(fields, rows) {
  const canonical = JSON.stringify({
    fields: fields.map((f) => [f.name, f.type, f.unit, f.precision]),
    rows: rows.map((row) => fields.map((f) => (f.name in row ? row[f.name] : null))),
  });
  return createHash("sha256").update(canonical).digest("hex");
}

export function fieldByName(dataset, name, expectedType) {
  const field = dataset.fields.find((candidate) => candidate.name === name);
  if (!field) fail(`unknown field: ${name}`);
  if (expectedType && field.type !== expectedType) {
    fail(`field ${name} must be a ${expectedType}, not a ${field.type}`);
  }
  return field;
}

export function withRows(dataset, fields, rows) {
  return Object.freeze({ ...dataset, fields, rows, hash: datasetHash(fields, rows) });
}

export { fail as failDataset };
