// brand-theme.mjs: chart and diagram roles derived from the active brand pack's tokens.json.
//
// No colour, family or radius is written here. Roles are measured from the palette so any valid
// brand pack works without a per-brand table:
//   ground   the lightest core colour (light theme) or the darkest (dark theme)
//   ink      the core colour with the most contrast against the ground
//   accent   the most saturated core colour: the one thing that matters most in a frame
//   muted    the lightest-reading neutral that still clears 4.5:1 on the ground (secondary text)
//   quiet    a neutral around 3:1 on the ground (de-emphasised marks: the bars that are not the point)
//   rule     a neutral just off the ground (grid lines, lane walls)
//   series   chromatic palette colours in brand order, minus the accent and anything that would read
//            as it, minus anything too close to the ground to see
//   ramp     one hue family from light to dark, for sequential encodings
// The pack can assign roles per mode (`design.roles.light|dark` in tokens.json), and a spec can pin any
// role to a token (`"colors": {"ground": "--brand-color-paper"}`); a spec's pin wins over the pack's,
// and both win over the measurement. Every token must resolve to a palette colour.

import { readFileSync } from "node:fs";

export class BrandError extends Error {}

const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;

export function normalizeHex(value) {
  const m = HEX.exec(String(value).trim());
  if (!m) return null;
  const h = m[1].length === 3 ? [...m[1]].map((c) => c + c).join("") : m[1];
  return `#${h.toLowerCase()}`;
}

function rgb(hex) {
  const h = normalizeHex(hex).slice(1);
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
}

const linear = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);

export function luminance(hex) {
  const [r, g, b] = rgb(hex).map(linear);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** OKLab: perceptual lightness, chroma and hue, for "most saturated" and "reads like the accent". */
export function oklab(hex) {
  const [r, g, b] = rgb(hex).map(linear);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  return { L, a: A, b: B, chroma: Math.hypot(A, B), hue: Math.atan2(B, A) };
}

const distance = (x, y) => {
  const p = oklab(x);
  const q = oklab(y);
  return Math.hypot(p.L - q.L, p.a - q.a, p.b - q.b);
};
const hueGap = (x, y) => {
  const d = Math.abs(oklab(x).hue - oklab(y).hue) % (2 * Math.PI);
  return d > Math.PI ? 2 * Math.PI - d : d;
};

const NEUTRAL_CHROMA = 0.04;

export function loadTokens(path) {
  let tokens;
  try {
    tokens = JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    throw new BrandError(`cannot read brand tokens ${path} (${error.code || error.message})`);
  }
  if (!tokens?.design?.allowedColors || !tokens?.design?.fontStacks) {
    throw new BrandError(`brand tokens ${path} have no design.allowedColors or design.fontStacks`);
  }
  return tokens;
}

function cssStack(families) {
  return families.map((f) => (/^[a-z-]+$/.test(f) ? f : `'${f.replace(/'/g, "")}'`)).join(", ");
}

function px(value, fallback) {
  const m = /^(\d+(?:\.\d+)?)px$/.exec(String(value ?? "").trim());
  return m ? Number(m[1]) : fallback;
}

function tokenEndingWith(tokens, suffix) {
  const name = Object.keys(tokens).find((key) => key.endsWith(suffix));
  return name ? tokens[name] : undefined;
}

/**
 * @param {object} tokensFile parsed tokens.json
 * @param {{mode?: "light"|"dark", roles?: Record<string, string>}} options
 */
export function brandTheme(tokensFile, { mode = "light", roles = {} } = {}) {
  if (!["light", "dark"].includes(mode)) throw new BrandError(`theme must be light or dark, not ${mode}`);
  const design = tokensFile.design;
  const core = [...new Set(design.allowedColors.map(normalizeHex).filter(Boolean))];
  const extended = [...new Set((design.extendedPalette?.colors || []).map(normalizeHex).filter(Boolean))];
  const palette = new Set([...core, ...extended]);
  const tokens = design.tokens || {};

  const resolve = (where, token) => {
    if (!(token in tokens)) throw new BrandError(`${where}: unknown token ${token}`);
    const hex = normalizeHex(tokens[token]);
    if (!hex || !palette.has(hex)) throw new BrandError(`${where}: ${token} is not a palette colour`);
    return hex;
  };
  const packRoles = design.roles?.[mode] || {};
  const pinned = {};
  for (const role of ["ground", "ink", "accent", "muted", "quiet", "rule"]) {
    if (packRoles[role]) pinned[role] = resolve(`roles.${mode}.${role}`, packRoles[role]);
  }
  const packSeries = (packRoles.series || []).map((token, i) => resolve(`roles.${mode}.series[${i}]`, token));
  for (const [role, token] of Object.entries(roles)) pinned[role] = resolve(`colors.${role}`, token);

  const byLum = [...core].sort((a, b) => luminance(a) - luminance(b));
  const ground = pinned.ground ?? (mode === "light" ? byLum[byLum.length - 1] : byLum[0]);
  const ink = pinned.ink ?? [...core].sort((a, b) => contrast(b, ground) - contrast(a, ground))[0];
  const chromatic = core.filter((c) => c !== ground && c !== ink && oklab(c).chroma >= NEUTRAL_CHROMA);
  const accent = pinned.accent ?? [...chromatic].sort((a, b) => oklab(b).chroma - oklab(a).chroma)[0] ?? ink;

  const neutrals = [...palette].filter((c) => c !== ground && c !== ink && oklab(c).chroma < NEUTRAL_CHROMA);
  // Nearest to the target contrast; near ties go to the greyer colour.
  const score = (c, target) => Math.abs(contrast(c, ground) - target) + 2 * oklab(c).chroma;
  const closest = (candidates, target) => [...candidates].sort((a, b) => score(a, target) - score(b, target))[0];
  const readable = neutrals.filter((c) => contrast(c, ground) >= 4.5);
  const muted = pinned.muted ?? (readable.length ? closest(readable, 4.5) : ink);
  const quietPool = neutrals.filter((c) => contrast(c, ground) >= 1.8 && contrast(c, ground) < 4.5);
  const quiet = pinned.quiet ?? (quietPool.length ? closest(quietPool, 3) : muted);
  const rulePool = neutrals.filter((c) => contrast(c, ground) >= 1.08 && contrast(c, ground) < 1.8);
  const rule = pinned.rule ?? (rulePool.length ? closest(rulePool, 1.3) : quiet);

  const candidates = [...core, ...extended].filter(
    (c, i, all) =>
      all.indexOf(c) === i &&
      ![ground, ink, accent].includes(c) &&
      oklab(c).chroma >= NEUTRAL_CHROMA &&
      distance(c, accent) > 0.12 &&
      hueGap(c, accent) > 0.35 &&
      contrast(c, ground) >= 1.4,
  );
  // The pack's series as written; otherwise distinct hues first (in brand order), then the
  // remaining tints in brand order.
  const series = [...packSeries];
  if (!series.length) {
    for (const c of candidates) if (series.every((s) => hueGap(c, s) > 0.5)) series.push(c);
    for (const c of candidates) if (!series.includes(c)) series.push(c);
  }
  if (pinned.series) series.unshift(pinned.series);

  const anchor = series[0] ?? accent;
  const family = [...palette].filter((c) => oklab(c).chroma >= NEUTRAL_CHROMA && hueGap(c, anchor) < 0.45);
  // Low values sit near the ground, high values stand out from it, in either theme.
  const ramp = [rule, ...family.sort((a, b) => contrast(a, ground) - contrast(b, ground))].filter(
    (c, i, all) => all.indexOf(c) === i && c !== ground,
  );

  const stacks = design.fontStacks;
  const strokeToken = design.diagramConstruction?.strokeTokens?.[0];
  return Object.freeze({
    mode,
    palette,
    ground,
    ink,
    accent,
    muted,
    quiet,
    rule,
    series,
    ramp,
    /** Text colour with the most contrast on a given fill: ink or ground. */
    onFill: (fill) => (contrast(ink, fill) >= contrast(ground, fill) ? ink : ground),
    fonts: { display: cssStack(stacks.display), text: cssStack(stacks.text), mono: cssStack(stacks.mono) },
    leadFamilies: { display: stacks.display[0], text: stacks.text[0], mono: stacks.mono[0] },
    weights: {
      display: Number(tokenEndingWith(tokens, "weight-display")) || 600,
      text: Number(tokenEndingWith(tokens, "weight-text")) || 400,
      strong: Number(tokenEndingWith(tokens, "weight-strong")) || 600,
    },
    radius: Math.min(design.maxRectRadiusPx ?? 8, 8),
    barRadius: Math.min(design.maxRectRadiusPx ?? 4, 4),
    stroke: px(strokeToken ? tokens[strokeToken] : undefined, 2),
    gridUnit: design.diagramConstruction?.baseGridUnitPx ?? 8,
  });
}

/** Snap to the brand grid. */
export const snap = (value, unit) => Math.round(value / unit) * unit;
