#!/usr/bin/env node
// thumb-gate.mjs — the one hard stop on a thumbnail is what the platform itself rejects or degrades.
// Everything else it prints is a measurement to read, not a verdict: design judgment belongs to the
// eye looking at the small-size sheet, and to an A/B test result after that.
//
// Gates (exit 1), from YouTube Help (answers 72431 and 13861714):
//   aspect     16:9, which is the only shape a long-form thumbnail is shown in
//   width      ≥ 1280 px: one Test & Compare variant under 1280×720 downscales every arm to 480p
//   bytes      < 50 MB, the desktop and API upload limit
// Measurements (printed, never fail):
//   resolution against the recommended 3840×2160, which TV and 4K surfaces are served from
//   bytes against 2 MB, the limit when someone uploads from the phone app
//   drawn content under the duration badge, which at the smallest desktop render (215 px wide) covers
//     roughly the right 22% × bottom 22% of the frame
//   with --comp: the hero element's words, size, weight and measured ink-vs-ground contrast, and any
//     raster the comp draws wider than its own pixels
//
// Usage:
//   node /workspace/skills/thumbnails/scripts/thumb-gate.mjs projects/<slug>/renders/a.png \
//        [--comp projects/<slug>/thumbnail/a.html]
//
// A comp that wants its hero measured marks it `data-thumb-role="hero"` with px top/left/width/height
// on a 1280×720 canvas; a render at any larger 16:9 size is measured in that same coordinate space.
// Paths are confined to the workspace (/workspace, or DESIGN_AGENT_WORKSPACE). sharp resolves from the
// pinned render toolchain (DESIGN_AGENT_RENDER_DIR, default /opt/design-agent/render).
// Exit: 0 every platform gate passes · 1 a platform gate fails · 2 bad arguments, an unreadable image,
// or the render toolchain is unavailable.

import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";

const WORKSPACE = path.resolve(process.env.DESIGN_AGENT_WORKSPACE || "/workspace");
const RENDER_DIR = process.env.DESIGN_AGENT_RENDER_DIR || "/opt/design-agent/render";
const CANVAS = { width: 1280, height: 720 }; // the authoring space every measurement is taken in
const RECOMMENDED = { width: 3840, height: 2160 };
const MAX_BYTES = 50 * 1024 * 1024;
const PHONE_MAX_BYTES = 2 * 1024 * 1024;
const BADGE_ZONE = { x: 0.78, y: 0.78 };
const DETAIL_DELTA = 0.15; // local luminance step that reads as drawn content, not a soft field
const RASTER = /\.(?:png|jpe?g|webp|avif|gif|bmp)$/i;

function confine(p) {
  const abs = path.resolve(p);
  if (abs !== WORKSPACE && !abs.startsWith(WORKSPACE + path.sep)) {
    throw new Error(`refusing path outside ${WORKSPACE}: ${p}`);
  }
  return abs;
}

let sharpModule = null;
async function loadSharp() {
  sharpModule ??= createRequire(path.join(RENDER_DIR, "package.json"))("sharp");
  return sharpModule;
}

// ---------- color math (WCAG 2.1 relative luminance) ----------
const CHANNEL = Array.from({ length: 256 }, (_, v) =>
  v / 255 <= 0.03928 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4,
);
export const relativeLuminance = (r, g, b) =>
  0.2126 * CHANNEL[r] + 0.7152 * CHANNEL[g] + 0.0722 * CHANNEL[b];
export const contrastRatio = (a, b) =>
  (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);

// ---------- comp parsing (pure — no sharp, no DOM) ----------
const mask = (text) => text.replace(/[^\n]/g, " ");

function declarations(body) {
  const out = new Map();
  for (const m of body.matchAll(/([\w-]+)\s*:\s*([^;{}]+)/g)) out.set(m[1].toLowerCase(), m[2].trim());
  return out;
}

function styleRules(source) {
  const rules = [];
  for (const block of source.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style\b[^>]*>/gi)) {
    const clean = block[1].replace(/\/\*[\s\S]*?\*\//g, mask);
    for (const rule of clean.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const selectorText = rule[1].trim();
      if (!selectorText || selectorText.startsWith("@")) continue;
      const parsed = declarations(rule[2]);
      for (const selector of selectorText.split(",")) rules.push({ selector: selector.trim(), parsed });
    }
  }
  return rules;
}

function attrValue(attrs, name) {
  return attrs.match(new RegExp(`\\b${name}\\s*=\\s*["']([^"']*)["']`, "i"))?.[1] || "";
}

// Selector match for the hero only: id, class, attribute, or bare tag on the last compound. The comp
// is one authored file at one size, so descendant context never disambiguates a hero rule here.
function targetsHero(selector, hero) {
  const compound = selector.split(/[\s>+~]+/).filter(Boolean).at(-1);
  if (!compound) return false;
  if (/::?[\w-]/.test(compound.replace(/\[[^\]]*\]/g, ""))) return false;
  for (const attr of compound.matchAll(/\[([\w-]+)\s*=\s*["']?([^\]"']+)["']?\]/g)) {
    if (attrValue(hero.attrs, attr[1]) !== attr[2]) return false;
  }
  const stripped = compound.replace(/\[[^\]]*\]/g, "");
  const id = stripped.match(/#([\w-]+)/)?.[1];
  if (id && id !== attrValue(hero.attrs, "id")) return false;
  const classes = new Set(attrValue(hero.attrs, "class").split(/\s+/).filter(Boolean));
  if ([...stripped.matchAll(/\.([\w-]+)/g)].some((m) => !classes.has(m[1]))) return false;
  const tag = stripped.match(/^[a-z][\w-]*/i)?.[0];
  if (tag && tag.toLowerCase() !== hero.tag) return false;
  return Boolean(tag || id || classes.size > 0 || compound.includes("["));
}

function textOf(html) {
  return html
    .replace(/<[^>]*>/g, " ")
    .replace(/&(?:nbsp|#160);/gi, " ")
    .replace(/&(?:#\d{1,6}|#x[\da-f]{1,6}|[a-z]{1,10});/gi, "")
    .replace(/\s+/g, " ")
    .trim();
}

function heroElement(source) {
  const open = source.match(/<([a-z][\w-]*)([^>]*\bdata-thumb-role\s*=\s*["']hero["'][^>]*)>/i);
  if (!open) return null;
  const tag = open[1].toLowerCase();
  const bodyStart = open.index + open[0].length;
  let depth = 1;
  let cursor = bodyStart;
  const scan = new RegExp(`</?${tag}\\b[^>]*>`, "gi");
  scan.lastIndex = bodyStart;
  for (let m = scan.exec(source); m; m = scan.exec(source)) {
    depth += m[0].startsWith("</") ? -1 : 1;
    if (depth === 0) {
      cursor = m.index;
      break;
    }
  }
  return { tag, attrs: open[2], inner: source.slice(bodyStart, cursor) };
}

function heroStyle(source, hero) {
  const merged = new Map();
  for (const rule of styleRules(source)) {
    if (!targetsHero(rule.selector, hero)) continue;
    for (const [property, value] of rule.parsed) merged.set(property, value);
  }
  for (const [property, value] of declarations(attrValue(hero.attrs, "style"))) merged.set(property, value);
  return merged;
}

const pxOf = (value) => {
  const m = /^([\d.]+)px$/.exec((value || "").trim());
  return m ? Number(m[1]) : null;
};

function rasterReferences(source) {
  const refs = [];
  for (const m of source.matchAll(/(?:\bsrc\s*=\s*["']([^"']+)["']|url\(\s*["']?([^"')]+)["']?\s*\))/gi)) {
    const ref = (m[1] || m[2]).trim();
    if (!ref || ref.startsWith("#") || ref.startsWith("data:")) continue;
    refs.push({ ref, index: m.index });
  }
  return refs;
}

// Declared render width for a referenced raster: the px width stated inside the same rule or tag,
// else the full canvas — a reference with no stated width is assumed to stretch full bleed.
function declaredWidth(source, index) {
  const start = Math.max(source.lastIndexOf("{", index), source.lastIndexOf("<", index)) + 1;
  const ends = [source.indexOf("}", index), source.indexOf(">", index)].filter((i) => i >= 0);
  const scope = source.slice(start, ends.length ? Math.min(...ends) : source.length);
  return pxOf(scope.match(/(?:^|[;{"'\s])width\s*:\s*([\d.]+px)/i)?.[1]) ?? CANVAS.width;
}

// The `font` shorthand ("600 104px/1.05 'Brand Display'") carries size and weight too.
function fromShorthand(font) {
  const size = /([\d.]+)px/.exec(font || "")?.[1];
  const weight = /(?:^|\s)([1-9]00)(?=\s)/.exec(font || "")?.[1];
  return { size: size ? Number(size) : null, weight: weight ? Number(weight) : null };
}

export function readComp(source) {
  const hero = heroElement(source);
  const style = hero ? heroStyle(source, hero) : new Map();
  const text = hero ? textOf(hero.inner) : "";
  const shorthand = fromShorthand(style.get("font"));
  return {
    hero: hero && {
      text,
      words: text.split(/\s+/).filter(Boolean),
      fontSize: pxOf(style.get("font-size")) ?? shorthand.size,
      fontWeight: Number.parseInt(style.get("font-weight") || "", 10) || shorthand.weight,
      box: {
        left: pxOf(style.get("left")),
        top: pxOf(style.get("top")),
        width: pxOf(style.get("width")),
        height: pxOf(style.get("height")),
      },
    },
    rasters: rasterReferences(source).map((r) => ({ ...r, width: declaredWidth(source, r.index) })),
  };
}

const gate = (name, ok, detail) => ({ name, ok, detail, kind: "gate" });
const measure = (name, detail, note = false) => ({ name, ok: true, detail, note, kind: "measure" });

// ---------- pixel measurements ----------
function luminanceMap(data, width, height, channels) {
  const map = new Float32Array(width * height);
  for (let i = 0; i < width * height; i++) {
    const o = i * channels;
    map[i] = relativeLuminance(data[o], data[o + 1], data[o + 2]);
  }
  return map;
}

// Split a region into ink and ground by Otsu threshold, then contrast the two cluster means: the
// measured version of "is the hero readable", as opposed to the authored token values.
function inkGroundContrast(map, width, region) {
  const values = [];
  for (let y = region.top; y < region.top + region.height; y++) {
    for (let x = region.left; x < region.left + region.width; x++) values.push(map[y * width + x]);
  }
  if (values.length < 100) return null;
  const bins = new Array(64).fill(0);
  for (const v of values) bins[Math.min(63, Math.floor(v * 64))]++;
  const total = values.length;
  let best = { score: -1, threshold: 32 };
  let sum = 0;
  for (let i = 0; i < 64; i++) sum += i * bins[i];
  let weightLow = 0;
  let sumLow = 0;
  for (let t = 0; t < 64; t++) {
    weightLow += bins[t];
    sumLow += t * bins[t];
    const weightHigh = total - weightLow;
    if (weightLow === 0 || weightHigh === 0) continue;
    const meanLow = sumLow / weightLow;
    const meanHigh = (sum - sumLow) / weightHigh;
    const score = weightLow * weightHigh * (meanLow - meanHigh) ** 2;
    if (score > best.score) best = { score, threshold: (t + 1) / 64 };
  }
  const low = values.filter((v) => v < best.threshold);
  const high = values.filter((v) => v >= best.threshold);
  if (!low.length || !high.length) return null;
  const mean = (list) => list.reduce((a, b) => a + b, 0) / list.length;
  return contrastRatio(mean(low), mean(high));
}

// Drawn content = local luminance step. A flat or softly graded ground is not content; type, a logo,
// and a focal object are.
function detailFraction(map, width, region) {
  let detail = 0;
  let counted = 0;
  for (let y = region.top; y < region.top + region.height - 1; y++) {
    for (let x = region.left; x < region.left + region.width - 1; x++) {
      const here = map[y * width + x];
      const step = Math.abs(map[y * width + x + 1] - here) + Math.abs(map[(y + 1) * width + x] - here);
      if (step > DETAIL_DELTA) detail++;
      counted++;
    }
  }
  return counted === 0 ? 0 : detail / counted;
}

async function rasterMeasures(comp, compDir) {
  const sharp = await loadSharp();
  const out = [];
  for (const raster of comp.rasters) {
    if (!RASTER.test(raster.ref)) continue;
    let abs;
    try {
      abs = confine(path.resolve(compDir, raster.ref));
    } catch (error) {
      out.push(measure("raster", `${raster.ref} — ${error.message}`, true));
      continue;
    }
    if (!fs.existsSync(abs)) {
      out.push(measure("raster", `${raster.ref} is referenced but missing`, true));
      continue;
    }
    const { width } = await sharp(abs).metadata();
    // The render is supersampled, so a raster needs its drawn width in real pixels at the output scale.
    if (width < raster.width) {
      out.push(measure("raster", `${path.basename(raster.ref)} is ${width}px wide but drawn at ${raster.width}px: it will look soft`, true));
    }
  }
  return out;
}

export async function inspect(pngPath, comp, compDir) {
  const sharp = await loadSharp();
  const bytes = fs.statSync(pngPath).size;
  const meta = await sharp(pngPath).metadata();
  const { width, height } = meta;
  const aspectOk = Math.abs(width * 9 - height * 16) <= 16;
  const results = [
    gate("aspect", aspectOk, `${width}×${height} (${aspectOk ? "16:9" : "not 16:9 — YouTube crops or letterboxes it"})`),
    gate(
      "width",
      width >= CANVAS.width,
      width >= CANVAS.width
        ? `${width}px wide (Test & Compare needs every arm at 1280×720 or more)`
        : `${width}px wide — under 1280, and one arm this small downscales every arm of a Test & Compare to 480p`,
    ),
    gate("bytes", bytes < MAX_BYTES, `${(bytes / 1024 / 1024).toFixed(2)} MB (desktop and API upload limit 50 MB)`),
  ];
  if (width < RECOMMENDED.width) {
    results.push(measure("resolution", `${width}×${height}; YouTube recommends ${RECOMMENDED.width}×${RECOMMENDED.height}, which TV and 4K surfaces are served from`, true));
  }
  if (bytes >= PHONE_MAX_BYTES) {
    results.push(measure("phoneUpload", `${(bytes / 1024 / 1024).toFixed(2)} MB is over the phone app's 2 MB limit; upload it from a desktop`, true));
  }
  if (!aspectOk) return results;

  // Measure in the 1280×720 authoring space, whatever size was rendered.
  const { data, info } = await sharp(pngPath)
    .resize(CANVAS.width, CANVAS.height, { fit: "fill", kernel: "lanczos3" })
    .removeAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  const map = luminanceMap(data, info.width, info.height, info.channels);

  const badge = detailFraction(map, info.width, {
    left: Math.round(info.width * BADGE_ZONE.x),
    top: Math.round(info.height * BADGE_ZONE.y),
    width: Math.round(info.width * (1 - BADGE_ZONE.x)),
    height: Math.round(info.height * (1 - BADGE_ZONE.y)),
  });
  results.push(
    measure(
      "badgeZone",
      `${(badge * 100).toFixed(2)}% drawn content in the bottom-right 22%, where the duration badge sits on the smallest render${badge >= 0.015 ? " — check the sidebar sheet for anything that matters under it" : ""}`,
      badge >= 0.015,
    ),
  );

  const hero = comp?.hero;
  if (comp && !hero) results.push(measure("hero", 'no element carries data-thumb-role="hero", so no hero measurements'));
  if (hero) {
    results.push(
      measure(
        "hero",
        `"${hero.text.slice(0, 60)}" — ${hero.words.length} words, ${hero.fontSize ? `${hero.fontSize}px` : "size undeclared"}, weight ${hero.fontWeight ?? "undeclared"}`,
      ),
    );
    const box = hero.box;
    if (Object.values(box).every((v) => typeof v === "number")) {
      const region = {
        left: Math.max(0, Math.round(box.left)),
        top: Math.max(0, Math.round(box.top)),
        width: Math.min(info.width - Math.max(0, Math.round(box.left)), Math.round(box.width)),
        height: Math.min(info.height - Math.max(0, Math.round(box.top)), Math.round(box.height)),
      };
      const ratio = inkGroundContrast(map, info.width, region);
      results.push(
        measure(
          "heroContrast",
          ratio === null
            ? "no measurable ink/ground split in the hero box — is the title inside its declared box?"
            : `hero ink vs its own ground ${ratio.toFixed(2)}:1${ratio < 4.5 ? " — under 4.5:1, which reads poorly at feed size" : ""}`,
          ratio === null || ratio < 4.5,
        ),
      );
    }
  }
  if (comp) results.push(...(await rasterMeasures(comp, compDir)));
  return results;
}

// ---------- CLI ----------
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const argv = process.argv.slice(2);
  let compArg = null;
  const inputs = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--comp") compArg = argv[++i];
    else inputs.push(argv[i]);
  }
  if (!inputs.length) {
    console.error("usage: thumb-gate.mjs <thumbnail.png|jpg> [--comp <comp.html>]");
    process.exit(2);
  }
  let png;
  let results;
  try {
    png = confine(inputs[0]);
    const compPath = compArg ? confine(compArg) : null;
    const comp = compPath ? readComp(fs.readFileSync(compPath, "utf8")) : null;
    results = await inspect(png, comp, compPath ? path.dirname(compPath) : null);
  } catch (error) {
    // A gate that could not look at the image checked nothing: a tooling failure, never a pass.
    console.error(`thumb-gate: ${error.message}`);
    process.exit(2);
  }

  const failures = results.filter((r) => r.kind === "gate" && !r.ok);
  for (const r of results) {
    const mark = r.kind === "gate" ? (r.ok ? "✓" : "✗") : r.note ? "•" : "·";
    console.log(`${mark} ${r.name} — ${r.detail}`);
  }
  console.log(`\n${failures.length} platform failure(s) on ${path.basename(png)}; the • lines are for your judgment`);
  if (failures.length === 0) console.log("__THUMB_GATE_OK__");
  process.exit(failures.length > 0 ? 1 : 0);
}
