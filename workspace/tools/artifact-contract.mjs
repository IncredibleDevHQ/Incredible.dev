#!/usr/bin/env node
// artifact-contract.mjs — fail-closed intake and completion checks for visual work, and a measurement
// of the files that were actually produced.
//
// Usage:
//   node /workspace/tools/artifact-contract.mjs --contract projects/<slug>/artifact-contract.json --phase plan
//   node /workspace/tools/artifact-contract.mjs --contract projects/<slug>/artifact-contract.json --phase final
//   node /workspace/tools/artifact-contract.mjs --layers projects/<slug>/layer-manifest.json
//   node /workspace/tools/artifact-contract.mjs --expect <path>:<W>x<H> [--expect <path>:<W>x<H>@<seconds> ...] [--json]
//
// --expect measures each output: it must exist, be non-empty and decode as the format its extension
// names, at exactly W x H. Stills (PNG, JPEG, WebP) are read from their header bytes, no image
// library needed. A video expectation adds @<seconds>: ffprobe must report that duration within one
// frame, and the first and last frames must not be blank (frame 0 is the poster and the thumbnail);
// --allow-blank-ends accepts a fade from or to a flat ground that the person asked for.
// In --phase final, a contract whose output names a `path` is measured the same way.
//
// Relative paths resolve against --root (default: the folder holding tools/, i.e. /workspace) and
// nothing outside it is read.
// Exit: 0 pass · 1 findings (a missing or wrong output, an invalid contract) · 2 the check could not
// run (bad arguments, unreadable contract file, ffprobe/ffmpeg missing).

import { lstatSync, readFileSync, statSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { extname, isAbsolute, relative, resolve, sep } from "node:path";
import { EXIT, ToolingError, WORKSPACE, isMain, parseFlags, runCli } from "./toolchain.mjs";

let ROOT = WORKSPACE;
const MAX_DIMENSION = 16_384;
const MAX_ITEMS = 250;
const MAX_TEXT = 2_000;
const MAX_PATH = 512;
const problems = [];

function fail(message) {
  problems.push(message);
}

function confinedFile(input, label) {
  if (typeof input !== "string" || input.length === 0 || input.length > MAX_PATH) {
    throw new ToolingError(`${label} must be a non-empty path under ${ROOT}`);
  }
  const file = resolve(ROOT, input);
  const fromRoot = relative(ROOT, file);
  if (fromRoot.startsWith(`..${sep}`) || isAbsolute(fromRoot)) {
    throw new ToolingError(`${label} escapes the workspace root: ${input}`);
  }
  let stats;
  try {
    stats = lstatSync(file);
  } catch {
    throw new ToolingError(`${label} is not a file: ${input}`);
  }
  if (stats.isSymbolicLink()) throw new ToolingError(`${label} must not be a symbolic link: ${input}`);
  if (!stats.isFile()) throw new ToolingError(`${label} is not a file: ${input}`);
  return file;
}

function confinedAssetPath(value, label) {
  if (typeof value !== "string" || value.length === 0 || value.length > MAX_PATH) {
    fail(`${label} must be a non-empty relative path`);
    return false;
  }
  if (value.includes("\0") || value.includes("\\") || isAbsolute(value) || /^[A-Za-z]:/.test(value)) {
    fail(`${label} must use a workspace-relative POSIX path`);
    return false;
  }
  const resolved = resolve(ROOT, value);
  const fromRoot = relative(ROOT, resolved);
  if (fromRoot.startsWith(`..${sep}`) || isAbsolute(fromRoot)) {
    fail(`${label} escapes the workspace root: ${value}`);
    return false;
  }
  return true;
}

function existingAssetPath(value, label) {
  if (!confinedAssetPath(value, label)) return false;
  const file = resolve(ROOT, value);
  let stats;
  try {
    stats = lstatSync(file);
  } catch {
    fail(`${label} is not a file: ${value}`);
    return false;
  }
  if (stats.isSymbolicLink()) {
    fail(`${label} must not be a symbolic link: ${value}`);
    return false;
  }
  if (!stats.isFile()) {
    fail(`${label} is not a file: ${value}`);
    return false;
  }
  return true;
}

function readJson(file, label) {
  try {
    const value = JSON.parse(readFileSync(file, "utf8"));
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      fail(`${label} must contain one JSON object`);
      return null;
    }
    return value;
  } catch (error) {
    fail(`${label} is not valid JSON (${error.constructor.name})`);
    return null;
  }
}

function boundedString(value, label, { allowEmpty = false } = {}) {
  if (
    typeof value !== "string" ||
    value.length > MAX_TEXT ||
    (!allowEmpty && value.trim().length === 0)
  ) {
    fail(`${label} must be ${allowEmpty ? "a" : "a non-empty"} string up to ${MAX_TEXT} characters`);
    return false;
  }
  return true;
}

function boundedArray(value, label) {
  if (!Array.isArray(value) || value.length > MAX_ITEMS) {
    fail(`${label} must be an array with at most ${MAX_ITEMS} items`);
    return false;
  }
  return true;
}

function uniqueIds(items, label) {
  const seen = new Set();
  let valid = true;
  for (const [index, item] of items.entries()) {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      fail(`${label}[${index}] must be an object`);
      valid = false;
      continue;
    }
    if (!boundedString(item.id, `${label}[${index}].id`)) {
      valid = false;
      continue;
    }
    if (seen.has(item.id)) {
      fail(`${label} contains duplicate id ${JSON.stringify(item.id)}`);
      valid = false;
    }
    seen.add(item.id);
  }
  return valid ? seen : null;
}

function positiveDimension(value, label, { integer = true } = {}) {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value <= 0 ||
    value > MAX_DIMENSION ||
    (integer && !Number.isInteger(value))
  ) {
    fail(`${label} must be a positive${integer ? " integer" : ""} <= ${MAX_DIMENSION}`);
    return false;
  }
  return true;
}

function coordinate(value, label) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > MAX_DIMENSION) {
    fail(`${label} must be a finite number from 0 to ${MAX_DIMENSION}`);
    return false;
  }
  return true;
}

function validateOutput(output) {
  if (!output || typeof output !== "object" || Array.isArray(output)) {
    fail("output must be an object");
    return;
  }
  positiveDimension(output.width, "output.width");
  positiveDimension(output.height, "output.height");
  boundedString(output.format, "output.format");
  boundedString(output.mode, "output.mode");
}

// A revoked requirement stays in the ledger (it answers "why doesn't it do X any more?") and points
// at the requirement that replaced it. The chain must end on a live one, so a loop cannot retire all.
function validateSupersession(requirement, index, byId) {
  let next = requirement.superseded_by;
  if (typeof next !== "string" || next === requirement.id || !byId.has(next)) {
    fail(`requirements[${index}] status=superseded needs superseded_by naming the requirement that replaced it`);
    return;
  }
  const seen = new Set([requirement.id]);
  while (byId.get(next)?.status === "superseded") {
    if (seen.has(next)) {
      fail(`requirements[${index}] superseded_by loops; the chain must end on a live requirement`);
      return;
    }
    seen.add(next);
    next = byId.get(next).superseded_by;
  }
}

function validateContract(contract, phase) {
  if (contract.version !== 1) fail("contract.version must be 1");
  if (!new Set(["net-new", "reference-transform", "motion"]).has(contract.job_kind)) {
    fail("job_kind must be net-new, reference-transform, or motion");
  }
  validateOutput(contract.output);

  const source = contract.source;
  if (!source || typeof source !== "object" || Array.isArray(source)) {
    fail("source must be an object");
  } else {
    if (!new Set(["none", "reference", "copy", "reference-and-copy"]).has(source.kind)) {
      fail("source.kind must be none, reference, copy, or reference-and-copy");
    }
    if (boundedArray(source.inventory, "source.inventory")) {
      const ids = uniqueIds(source.inventory, "source.inventory");
      for (const [index, item] of source.inventory.entries()) {
        if (!item || typeof item !== "object" || Array.isArray(item)) continue;
        boundedString(item.type, `source.inventory[${index}].type`);
        boundedString(item.value, `source.inventory[${index}].value`);
      }
      if (source.kind !== "none" && ids?.size === 0) {
        fail("reference/copy work requires a non-empty source.inventory");
      }
    }
    for (const key of ["allowed_additions", "allowed_removals", "allowed_changes"]) {
      if (!boundedArray(source[key], `source.${key}`)) continue;
      source[key].forEach((item, index) => boundedString(item, `source.${key}[${index}]`));
    }
  }

  if (boundedArray(contract.requirements, "requirements")) {
    if (contract.requirements.length === 0) {
      fail("requirements must include at least one explicit request");
    }
    uniqueIds(contract.requirements, "requirements");
    const byId = new Map(contract.requirements.filter((item) => item?.id).map((item) => [item.id, item]));
    for (const [index, requirement] of contract.requirements.entries()) {
      if (!requirement || typeof requirement !== "object" || Array.isArray(requirement)) continue;
      boundedString(requirement.request, `requirements[${index}].request`);
      if (!new Set(["pending", "satisfied", "blocked", "superseded"]).has(requirement.status)) {
        fail(`requirements[${index}].status must be pending, satisfied, blocked, or superseded`);
      }
      boundedString(requirement.evidence, `requirements[${index}].evidence`, { allowEmpty: true });
      if (
        new Set(["satisfied", "blocked", "superseded"]).has(requirement.status) &&
        (!requirement.evidence || requirement.evidence.trim().length === 0)
      ) {
        fail(`requirements[${index}] needs evidence when status=${requirement.status}`);
      }
      if (requirement.status === "superseded") validateSupersession(requirement, index, byId);
      // Only the person can accept a blocked requirement; `waiver` records their words.
      const waiver = requirement.waiver ?? "";
      boundedString(waiver, `requirements[${index}].waiver`, { allowEmpty: true });
      const waived = requirement.status === "blocked" && typeof waiver === "string" && waiver.trim();
      if (phase === "final" && !["satisfied", "superseded"].includes(requirement.status) && !waived) {
        fail(
          `final validation requires ${requirement.id || `requirements[${index}]`} to be satisfied, ` +
            "superseded by its replacement, or blocked with the person's waiver",
        );
      }
    }
  }

  if (boundedArray(contract.assets, "assets")) {
    uniqueIds(contract.assets, "assets");
    for (const [index, asset] of contract.assets.entries()) {
      if (!asset || typeof asset !== "object" || Array.isArray(asset)) continue;
      boundedString(asset.role, `assets[${index}].role`);
      if (typeof asset.required !== "boolean") fail(`assets[${index}].required must be boolean`);
      if (asset.required === true) existingAssetPath(asset.path, `assets[${index}].path`);
      else confinedAssetPath(asset.path, `assets[${index}].path`);
    }
  }
}

function validateRect(rect, label, canvas) {
  if (!rect || typeof rect !== "object" || Array.isArray(rect)) {
    fail(`${label} must be an object`);
    return false;
  }
  let valid =
    coordinate(rect.x, `${label}.x`) &&
    coordinate(rect.y, `${label}.y`) &&
    positiveDimension(rect.width, `${label}.width`, { integer: false }) &&
    positiveDimension(rect.height, `${label}.height`, { integer: false });
  if (valid && (rect.x + rect.width > canvas.width || rect.y + rect.height > canvas.height)) {
    fail(`${label} must fit inside the canvas`);
    valid = false;
  }
  return valid;
}

function contains(outer, inner) {
  return (
    inner.x >= outer.x &&
    inner.y >= outer.y &&
    inner.x + inner.width <= outer.x + outer.width &&
    inner.y + inner.height <= outer.y + outer.height
  );
}

function validateLayers(manifest) {
  if (manifest.version !== 1) fail("layer manifest version must be 1");
  const canvas = manifest.canvas;
  if (!canvas || typeof canvas !== "object" || Array.isArray(canvas)) {
    fail("canvas must be an object");
    return;
  }
  positiveDimension(canvas.width, "canvas.width");
  positiveDimension(canvas.height, "canvas.height");

  const layerMap = new Map();
  if (boundedArray(manifest.layers, "layers")) {
    uniqueIds(manifest.layers, "layers");
    for (const [index, layer] of manifest.layers.entries()) {
      if (!layer || typeof layer !== "object" || Array.isArray(layer)) continue;
      existingAssetPath(layer.path, `layers[${index}].path`);
      boundedString(layer.role, `layers[${index}].role`);
      if (!new Set(["separate-alpha", "vector", "flat-reference"]).has(layer.isolation)) {
        fail(`layers[${index}].isolation must be separate-alpha, vector, or flat-reference`);
      }
      const boundsValid = validateRect(layer.bounds, `layers[${index}].bounds`, canvas);
      if (
        !layer.anchor ||
        typeof layer.anchor !== "object" ||
        !Number.isFinite(layer.anchor.x) ||
        !Number.isFinite(layer.anchor.y) ||
        layer.anchor.x < 0 ||
        layer.anchor.x > 1 ||
        layer.anchor.y < 0 ||
        layer.anchor.y > 1
      ) {
        fail(`layers[${index}].anchor must contain normalized x/y values from 0 to 1`);
      }
      if (boundedArray(layer.animate, `layers[${index}].animate`)) {
        layer.animate.forEach((item, itemIndex) =>
          boundedString(item, `layers[${index}].animate[${itemIndex}]`),
        );
        if (layer.animate.length > 0 && layer.isolation === "flat-reference") {
          fail(`layers[${index}] cannot animate a flat-reference; request a separated alpha/vector layer`);
        }
      }
      if (boundsValid && typeof layer.id === "string") layerMap.set(layer.id, layer);
    }
  }

  if (boundedArray(manifest.safe_areas, "safe_areas")) {
    uniqueIds(manifest.safe_areas, "safe_areas");
    for (const [index, safeArea] of manifest.safe_areas.entries()) {
      if (!safeArea || typeof safeArea !== "object" || Array.isArray(safeArea)) continue;
      const validRect = validateRect(safeArea.bounds, `safe_areas[${index}].bounds`, canvas);
      if (!boundedArray(safeArea.contains, `safe_areas[${index}].contains`)) continue;
      for (const layerId of safeArea.contains) {
        boundedString(layerId, `safe_areas[${index}].contains[]`);
        const layer = layerMap.get(layerId);
        if (!layer) fail(`safe_areas[${index}] references unknown layer ${JSON.stringify(layerId)}`);
        else if (validRect && !contains(safeArea.bounds, layer.bounds)) {
          fail(`layer ${JSON.stringify(layerId)} does not fit safe area ${JSON.stringify(safeArea.id)}`);
        }
      }
    }
  }

  if (boundedArray(manifest.attachments, "attachments")) {
    for (const [index, attachment] of manifest.attachments.entries()) {
      if (!attachment || typeof attachment !== "object" || Array.isArray(attachment)) {
        fail(`attachments[${index}] must be an object`);
        continue;
      }
      for (const key of ["child", "parent", "child_anchor", "parent_anchor"]) {
        boundedString(attachment[key], `attachments[${index}].${key}`);
      }
      if (!layerMap.has(attachment.child)) {
        fail(`attachments[${index}] references unknown child ${JSON.stringify(attachment.child)}`);
      }
      if (!layerMap.has(attachment.parent)) {
        fail(`attachments[${index}] references unknown parent ${JSON.stringify(attachment.parent)}`);
      }
      if (attachment.child === attachment.parent) fail(`attachments[${index}] cannot self-attach`);
    }
  }
}

// --- measuring produced files ----------------------------------------------------------------------
// Stills are read from their own header bytes: a truncated or mislabelled file fails here without an
// image library. Each reader returns {format, width, height} or a problem string.

function readPng(buf) {
  if (buf.length < 33 || buf.readUInt32BE(0) !== 0x89504e47 || buf.readUInt32BE(4) !== 0x0d0a1a0a) return "not a PNG (bad signature)";
  if (buf.toString("latin1", 12, 16) !== "IHDR") return "not a PNG (no IHDR chunk)";
  let off = 8;
  let idat = false;
  while (off + 12 <= buf.length) {
    const len = buf.readUInt32BE(off);
    const type = buf.toString("latin1", off + 4, off + 8);
    if (off + 12 + len > buf.length) return `truncated PNG (${type} chunk runs past the end of the file)`;
    if (type === "IDAT") idat = true;
    if (type === "IEND") {
      if (!idat) return "PNG has no image data (no IDAT chunk)";
      return { format: "png", width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
    }
    off += 12 + len;
  }
  return "truncated PNG (no IEND chunk)";
}

// Start-of-frame markers carry the dimensions; C4 (DHT), C8 (JPG) and CC (DAC) are not frames.
const JPEG_SOF = new Set([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf]);
function readJpeg(buf) {
  if (buf.length < 4 || buf[0] !== 0xff || buf[1] !== 0xd8) return "not a JPEG (no SOI marker)";
  let size = null;
  let off = 2;
  while (off + 4 <= buf.length) {
    if (buf[off] !== 0xff) return "corrupt JPEG (segment does not start with 0xFF)";
    const marker = buf[off + 1];
    if (marker === 0xff) { off++; continue; } // fill byte
    if (marker === 0xd9) break;
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) { off += 2; continue; }
    const len = buf.readUInt16BE(off + 2);
    if (len < 2 || off + 2 + len > buf.length) return "truncated JPEG (segment runs past the end of the file)";
    if (JPEG_SOF.has(marker) && len >= 7) size = { width: buf.readUInt16BE(off + 7), height: buf.readUInt16BE(off + 5) };
    if (marker === 0xda) break; // entropy-coded data follows; the end marker is checked below
    off += 2 + len;
  }
  if (!size) return "corrupt JPEG (no start-of-frame segment)";
  if (buf[buf.length - 2] !== 0xff || buf[buf.length - 1] !== 0xd9) return "truncated JPEG (no EOI marker)";
  return { format: "jpeg", ...size };
}

function readWebp(buf) {
  if (buf.length < 30 || buf.toString("latin1", 0, 4) !== "RIFF" || buf.toString("latin1", 8, 12) !== "WEBP") return "not a WebP (bad RIFF header)";
  if (buf.readUInt32LE(4) + 8 > buf.length) return "truncated WebP (RIFF size runs past the end of the file)";
  const chunk = buf.toString("latin1", 12, 16);
  if (chunk === "VP8X") return { format: "webp", width: 1 + buf.readUIntLE(24, 3), height: 1 + buf.readUIntLE(27, 3) };
  if (chunk === "VP8L") {
    if (buf[20] !== 0x2f) return "corrupt WebP (bad lossless signature)";
    const bits = buf.readUInt32LE(21);
    return { format: "webp", width: 1 + (bits & 0x3fff), height: 1 + ((bits >> 14) & 0x3fff) };
  }
  if (chunk === "VP8 ") {
    if (buf[23] !== 0x9d || buf[24] !== 0x01 || buf[25] !== 0x2a) return "corrupt WebP (bad lossy start code)";
    return { format: "webp", width: buf.readUInt16LE(26) & 0x3fff, height: buf.readUInt16LE(28) & 0x3fff };
  }
  return `not a WebP image (first chunk ${JSON.stringify(chunk)})`;
}

const STILL_READERS = { ".png": readPng, ".jpg": readJpeg, ".jpeg": readJpeg, ".webp": readWebp };
const VIDEO_EXTENSIONS = new Set([".mp4", ".mov", ".webm", ".m4v"]);

function run(binary, args, { encoding = "utf8", maxBuffer = 64 * 1024 * 1024 } = {}) {
  const result = spawnSync(binary, args, { encoding, maxBuffer });
  if (result.error?.code === "ENOENT") throw new ToolingError(`${binary} is not installed (run inside the sandbox image)`);
  if (result.error) throw new ToolingError(`${binary} failed: ${result.error.message}`);
  return result;
}

// Non-ground pixels against the frame's own modal color: mean luminance hides a frame whose only
// content is one headline. Floor: ~3000 px on a 1920x1080 frame, kept as a fraction of the frame.
const INK_DISTANCE = 36;
export const BLANK_INK = 3000 / (1920 * 1080);
const SAMPLE_W = 192;
const SAMPLE_H = 108;
export function inkFraction(rgb) {
  const counts = new Map();
  for (let i = 0; i + 2 < rgb.length; i += 3) {
    const key = ((rgb[i] >> 3) << 10) | ((rgb[i + 1] >> 3) << 5) | (rgb[i + 2] >> 3);
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  let modal = 0;
  let modalKey = 0;
  for (const [key, count] of counts) if (count > modal) { modal = count; modalKey = key; }
  const r = ((modalKey >> 10) & 31) * 8 + 4, g = ((modalKey >> 5) & 31) * 8 + 4, b = (modalKey & 31) * 8 + 4;
  let ink = 0;
  for (let i = 0; i + 2 < rgb.length; i += 3) {
    if (Math.abs(rgb[i] - r) + Math.abs(rgb[i + 1] - g) + Math.abs(rgb[i + 2] - b) > INK_DISTANCE) ink++;
  }
  return ink / (rgb.length / 3);
}

function frameInk(file, which) {
  const frameBytes = SAMPLE_W * SAMPLE_H * 3;
  const seek = which === "last" ? ["-sseof", "-1"] : [];
  const out = run(
    "ffmpeg",
    ["-v", "error", "-nostdin", ...seek, "-i", file, ...(which === "first" ? ["-frames:v", "1"] : []),
      "-vf", `scale=${SAMPLE_W}:${SAMPLE_H}:flags=area`, "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
    { encoding: "buffer", maxBuffer: 512 * 1024 * 1024 },
  );
  if (out.status !== 0 || out.stdout.length < frameBytes) return null;
  const start = which === "last" ? out.stdout.length - frameBytes : 0;
  return inkFraction(out.stdout.subarray(start, start + frameBytes));
}

function measureVideo(file) {
  const probe = run("ffprobe", [
    "-v", "error", "-select_streams", "v:0",
    "-show_entries", "stream=codec_name,width,height,avg_frame_rate:format=duration,format_name",
    "-of", "json", file,
  ]);
  if (probe.status !== 0) return `not a decodable video (${(probe.stderr || "").trim().split("\n")[0] || "ffprobe failed"})`;
  const info = JSON.parse(probe.stdout || "{}");
  const stream = info.streams?.[0];
  if (!stream) return "has no video stream";
  const [num, den] = String(stream.avg_frame_rate || "0/1").split("/").map(Number);
  return {
    format: info.format?.format_name || "video",
    codec: stream.codec_name,
    width: stream.width,
    height: stream.height,
    duration: Number(info.format?.duration),
    fps: den ? num / den : null,
    firstFrameInk: frameInk(file, "first"),
    lastFrameInk: frameInk(file, "last"),
  };
}

/** `out/a.png:1080x1350` or `out/film.mp4:1920x1080@2` (the path may itself contain colons). */
export function parseExpectation(spec) {
  const m = /^(.+):(\d{1,5})x(\d{1,5})(?:@(\d+(?:\.\d+)?)s?)?$/.exec(spec);
  if (!m) throw new ToolingError(`--expect must look like <path>:<W>x<H> or <path>:<W>x<H>@<seconds>, got "${spec}"`);
  return { path: m[1], width: Number(m[2]), height: Number(m[3]), duration: m[4] === undefined ? null : Number(m[4]) };
}

/** Measure one produced file against what was asked for. Returns the report entry with `problems`. */
export function checkOutput(expected, { allowBlankEnds = false } = {}) {
  const entry = { path: expected.path, expected: { width: expected.width, height: expected.height }, problems: [] };
  if (expected.duration !== null && expected.duration !== undefined) entry.expected.duration = expected.duration;
  const file = resolve(ROOT, expected.path);
  const fromRoot = relative(ROOT, file);
  if (fromRoot.startsWith(`..${sep}`) || isAbsolute(fromRoot)) throw new ToolingError(`${expected.path} escapes the workspace root ${ROOT}`);
  let stats;
  try {
    stats = statSync(file);
  } catch {
    entry.problems.push("does not exist");
    return entry;
  }
  if (!stats.isFile()) {
    entry.problems.push("is not a file");
    return entry;
  }
  entry.bytes = stats.size;
  if (stats.size === 0) {
    entry.problems.push("is empty (0 bytes)");
    return entry;
  }
  const ext = extname(file).toLowerCase();
  let measured;
  if (STILL_READERS[ext]) {
    measured = STILL_READERS[ext](readFileSync(file));
    if (expected.duration !== null && expected.duration !== undefined) entry.problems.push(`a duration was expected but ${ext} is a still`);
  } else if (VIDEO_EXTENSIONS.has(ext)) {
    measured = measureVideo(file);
  } else {
    entry.problems.push(`unsupported output type ${ext || "(no extension)"}: expected .png, .jpg, .webp, .mp4, .mov or .webm`);
    return entry;
  }
  if (typeof measured === "string") {
    entry.problems.push(measured);
    return entry;
  }
  Object.assign(entry, measured);
  if (measured.width !== expected.width || measured.height !== expected.height) {
    entry.problems.push(`is ${measured.width}x${measured.height}, expected ${expected.width}x${expected.height}`);
  }
  if (VIDEO_EXTENSIONS.has(ext)) {
    if (expected.duration !== null && expected.duration !== undefined) {
      const frame = measured.fps > 0 ? 1 / measured.fps : 1 / 30;
      if (!(Math.abs(measured.duration - expected.duration) <= frame + 1e-6)) {
        entry.problems.push(`runs ${measured.duration}s, expected ${expected.duration}s (within one frame, ${frame.toFixed(4)}s)`);
      }
    }
    for (const which of ["first", "last"]) {
      const ink = measured[`${which}FrameInk`];
      if (ink === null) entry.problems.push(`its ${which} frame could not be decoded`);
      else if (ink < BLANK_INK && !allowBlankEnds) entry.problems.push(`its ${which} frame is blank (ink ${ink.toFixed(5)} < ${BLANK_INK.toFixed(5)} of the frame)`);
    }
  }
  return entry;
}

if (isMain(import.meta.url)) {
  await runCli("artifact-contract", async () => {
    const { flags, positionals } = parseFlags(process.argv.slice(2), {
      values: ["contract", "layers", "phase", "root"],
      multi: ["expect"],
      booleans: ["json", "allow-blank-ends"],
    });
    if (positionals.length) throw new ToolingError(`unexpected argument ${positionals[0]}`);
    ROOT = resolve(flags.root || WORKSPACE);
    const phase = flags.phase || "plan";
    if (!new Set(["plan", "final"]).has(phase)) throw new ToolingError("--phase must be plan or final");
    if (!flags.contract && !flags.layers && !flags.expect.length) {
      throw new ToolingError("provide --contract, --layers and/or --expect <path>:<W>x<H>");
    }
    const options = { allowBlankEnds: Boolean(flags["allow-blank-ends"]) };
    const outputs = [];
    for (const expectation of flags.expect.map(parseExpectation)) outputs.push(checkOutput(expectation, options));
    if (flags.contract) {
      const contract = readJson(confinedFile(flags.contract, "--contract"), "contract");
      if (contract) {
        validateContract(contract, phase);
        const out = contract.output;
        if (phase === "final" && out && typeof out === "object" && typeof out.path === "string") {
          if (confinedAssetPath(out.path, "output.path")) {
            outputs.push(
              checkOutput(
                { path: out.path, width: out.width, height: out.height, duration: out.duration_s ?? null },
                { allowBlankEnds: options.allowBlankEnds || out.allow_blank_ends === true },
              ),
            );
          }
        }
      }
    }
    if (flags.layers) {
      const manifest = readJson(confinedFile(flags.layers, "--layers"), "layer manifest");
      if (manifest) validateLayers(manifest);
    }
    for (const entry of outputs) for (const problem of entry.problems) fail(`${entry.path} ${problem}`);
    const ok = problems.length === 0;
    if (flags.json) {
      console.log(JSON.stringify({ ok, phase: flags.contract ? phase : undefined, outputs, problems }));
    } else {
      for (const problem of problems) console.error(`artifact-contract: ${problem}`);
      for (const entry of outputs.filter((e) => !e.problems.length)) {
        console.log(`  ok  ${entry.path}  ${entry.width}x${entry.height}${entry.duration ? ` ${entry.duration}s` : ""}  ${entry.bytes} bytes`);
      }
      if (ok) console.log(`__ARTIFACT_CONTRACT_OK__${flags.contract ? ` phase=${phase}` : ""}`);
    }
    return ok ? EXIT.PASS : EXIT.FINDINGS;
  });
}
