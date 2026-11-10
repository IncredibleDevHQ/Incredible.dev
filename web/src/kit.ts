// A brand pack as the web app draws with it: its colours by role, its logos, its faces as
// @font-face rules, and contrast. The Brand page shows a pack; template covers draw in one.
import { useMemo, type CSSProperties } from "react";
import type { BrandPackView, ColourRole } from "./api";

const GENERIC = new Set(["serif", "sans-serif", "monospace", "cursive", "system-ui", "ui-serif", "ui-sans-serif", "ui-monospace", "ui-rounded", "emoji", "math"]);

export function rolesOf(pack: BrandPackView) {
  return Object.fromEntries(pack.roles.map((r) => [r.role, r.value])) as Partial<Record<ColourRole, string>>;
}

export function pick(logos: BrandPackView["logos"], prefix: string, dark: boolean) {
  return logos.find((l) => l.name.startsWith(prefix) && /reversed|white|on-dark|dark-bg/i.test(l.name) === dark);
}

// The pack's faces as @font-face rules under names of their own, and the stacks that use them.
export function useFaces(pack: BrandPackView | null) {
  return useMemo(() => {
    if (!pack) return { css: "", display: "var(--font)", text: "var(--font)", mono: "var(--mono)", vars: {} as CSSProperties };
    const alias = (family: string) => `kit-${pack.slug}-${family.replace(/\W+/g, "-")}`;
    const css = pack.faces
      .map((f) => `@font-face{font-family:"${alias(f.family)}";src:url("${f.url}");font-weight:${f.weight};font-style:${f.style};font-display:swap}`)
      .join("\n");
    const loaded = new Set(pack.faces.map((f) => f.family));
    const stack = (names: string[] = [], fallback: string) => {
      const listed = names.map((name) => (GENERIC.has(name) ? name : `"${name}"`));
      const own = names[0] && loaded.has(names[0]) ? [`"${alias(names[0])}"`] : [];
      return [...own, ...listed].join(", ") || fallback;
    };
    const display = stack(pack.stacks.display, "var(--font)");
    const text = stack(pack.stacks.text, "var(--font)");
    const mono = stack(pack.stacks.mono, "var(--mono)");
    const vars = { "--kit-display": display, "--kit-text": text, "--kit-mono": mono } as CSSProperties;
    return { css, display, text, mono, vars };
  }, [pack]);
}

function channel(hex: string, i: number) {
  return parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16) / 255;
}

export function luminance(hex: string) {
  if (!/^#[0-9a-f]{6}$/i.test(hex)) return 1;
  const [r, g, b] = [0, 1, 2].map((i) => {
    const c = channel(hex, i);
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

export function onColour(hex: string) {
  return contrast("#ffffff", hex) >= contrast("#111111", hex) ? "#ffffff" : "#111111";
}
