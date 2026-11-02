// d2.mjs: diagrams (flows, architectures, hierarchies, networks) laid out by D2 in brand roles.
//
// The D2 source is generated from the graph contract, never hand-written by the model, so labels are
// escaped and every node and edge carries an explicit brand style. D2 measures labels with the brand's
// own text font file (resolved through fontconfig), then the SVG's embedded font faces are swapped for
// the brand family so the rasteriser draws the same face D2 measured. After layout, the SVG is read
// back (D2 names each group with the base64 of its key) and audited against the contract.

import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { SpecError } from "./charts.mjs";

export class ToolError extends Error {}
const fail = (message) => {
  throw new SpecError(message);
};

export const D2_BIN = process.env.DESIGN_AGENT_D2 || "/usr/local/bin/d2";
export const LAYOUTS = Object.freeze(["elk", "dagre"]);
const DIRECTIONS = new Set(["right", "down", "left", "up"]);

const quote = (text) => `"${String(text).replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\$/g, "\\$").replace(/\r?\n/g, " ")}"`;

function groupsOf(contract, groups = []) {
  if (!Array.isArray(groups)) fail("data.groups must be an array");
  if (groups.length > 12) fail("at most 12 groups");
  const nodeIds = new Set(contract.nodes.map((n) => n.id));
  const groupOf = new Map();
  const seen = new Set();
  for (const [i, g] of groups.entries()) {
    if (!g || typeof g.id !== "string" || !/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(g.id)) fail(`groups[${i}].id must be an id`);
    if (nodeIds.has(g.id) || seen.has(g.id)) fail(`groups[${i}].id ${g.id} collides with another id`);
    seen.add(g.id);
    if (typeof g.label !== "string" || !g.label.trim() || g.label.length > 80) fail(`groups[${i}].label must be 1-80 characters`);
    if (!Array.isArray(g.nodes) || g.nodes.length === 0) fail(`groups[${i}].nodes must list node ids`);
    for (const id of g.nodes) {
      if (!nodeIds.has(id)) fail(`groups[${i}] names unknown node ${id}`);
      if (groupOf.has(id)) fail(`node ${id} is in two groups`);
      groupOf.set(id, g);
    }
  }
  return groupOf;
}

/** D2 source for a contract in brand roles. */
export function d2Source(contract, presentation, theme, { fontSize, layout }) {
  const direction = presentation.direction ?? "right";
  if (!DIRECTIONS.has(direction)) fail(`data.direction must be one of: ${[...DIRECTIONS].join(", ")}`);
  if (!LAYOUTS.includes(layout)) fail(`data.layout must be one of: ${LAYOUTS.join(", ")}`);
  const groupOf = groupsOf(contract, presentation.groups);
  const highlight = presentation.highlight;
  if (highlight !== undefined && !contract.nodes.some((n) => n.id === highlight)) fail(`highlight "${highlight}" is not a node id`);
  const key = (id) => (groupOf.has(id) ? `${quote(groupOf.get(id).id)}.${quote(id)}` : quote(id));
  const s = theme.stroke;
  const small = Math.max(12, Math.round(fontSize * 0.8));
  const lines = [
    "vars: {",
    "  d2-config: {",
    "    theme-overrides: {",
    `      N1: "${theme.ink}"; N2: "${theme.muted}"; N3: "${theme.quiet}"; N4: "${theme.rule}"; N5: "${theme.rule}"; N6: "${theme.ground}"; N7: "${theme.ground}"`,
    `      B1: "${theme.ink}"; B2: "${theme.muted}"; B3: "${theme.quiet}"; B4: "${theme.rule}"; B5: "${theme.rule}"; B6: "${theme.ground}"`,
    `      AA2: "${theme.muted}"; AA4: "${theme.rule}"; AA5: "${theme.ground}"; AB4: "${theme.rule}"; AB5: "${theme.ground}"`,
    "    }",
    "  }",
    "}",
    `direction: ${direction}`,
    `style: { fill: "${theme.ground}" }`,
    "classes: {",
    `  node: { style: { fill: "${theme.ground}"; stroke: "${theme.ink}"; stroke-width: ${s}; border-radius: ${theme.radius}; font-color: "${theme.ink}"; font-size: ${fontSize}; bold: false; shadow: false; 3d: false; multiple: false } }`,
    `  hero: { style: { fill: "${theme.accent}"; stroke: "${theme.accent}"; stroke-width: ${s}; border-radius: ${theme.radius}; font-color: "${theme.onFill(theme.accent)}"; font-size: ${fontSize}; bold: false; shadow: false } }`,
    `  group: { style: { fill: "${theme.ground}"; stroke: "${theme.rule}"; stroke-width: ${s}; border-radius: ${theme.radius}; font-color: "${theme.muted}"; font-size: ${small}; bold: false; shadow: false } }`,
    "}",
  ];
  const groups = [...new Set(groupOf.values())];
  for (const g of groups) {
    lines.push(`${quote(g.id)}: ${quote(g.label)} { class: group; label.near: top-left }`);
  }
  for (const node of contract.nodes) {
    lines.push(`${key(node.id)}: ${quote(node.label)} { class: ${node.id === highlight ? "hero" : "node"}; shape: rectangle }`);
  }
  for (const edge of contract.edges) {
    const arrow = edge.kind === "association" ? "--" : "->";
    const label = edge.label ? `: ${quote(edge.label)}` : "";
    lines.push(`${key(edge.from)} ${arrow} ${key(edge.to)}${label} { style: { stroke: "${theme.muted}"; stroke-width: ${s}; font-color: "${theme.muted}"; font-size: ${small}; italic: false; bold: false; animated: false } }`);
  }
  return `${lines.join("\n")}\n`;
}

/** The file fontconfig resolves for a family at a weight, and the family it actually matched. */
export function fontFile(family, weight) {
  const run = spawnSync("fc-match", ["-f", "%{file}\n%{family[0]}", `${family}:weight=${weight >= 600 ? 200 : 80}`], { encoding: "utf8", timeout: 15000 });
  if (run.error) throw new ToolError(`fc-match is not available (${run.error.code || run.error.message})`);
  const [file, matched] = run.stdout.split("\n");
  return { file, matched };
}

export function runD2(source, { layout, fontPath }) {
  const dir = mkdtempSync(join(tmpdir(), "viz-d2-"));
  try {
    const input = join(dir, "diagram.d2");
    const output = join(dir, "diagram.svg");
    writeFileSync(input, source, { mode: 0o600 });
    const fonts = fontPath && /\.ttf$/i.test(fontPath)
      ? ["--font-regular", fontPath, "--font-italic", fontPath, "--font-bold", fontPath, "--font-semibold", fontPath]
      : [];
    const run = spawnSync(D2_BIN, ["--layout", layout, "--pad", "8", "--theme", "0", ...fonts, input, output], {
      encoding: "utf8", timeout: 60000, maxBuffer: 1 << 26, env: { ...process.env, D2_LAYOUT: layout },
    });
    if (run.error?.code === "ENOENT") throw new ToolError(`d2 is not installed at ${D2_BIN} (set DESIGN_AGENT_D2 or run inside the sandbox)`);
    if (run.error) throw new ToolError(`d2 did not finish: ${run.error.message}`);
    if (run.status !== 0) fail(`d2 rejected the diagram: ${(run.stderr || "").trim().split("\n").slice(-3).join(" ")}`);
    return readFileSync(output, "utf8");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

/** Natural size of a D2 SVG (its outer viewBox). */
export function d2Size(svg) {
  const m = /<svg[^>]*\bviewBox="0 0 ([\d.]+) ([\d.]+)"/.exec(svg);
  if (!m) throw new ToolError("d2 output has no viewBox");
  return { w: Number(m[1]), h: Number(m[2]) };
}

const decode = (token) => {
  try {
    return Buffer.from(token, "base64").toString("utf8").replace(/&gt;/g, ">").replace(/&lt;/g, "<").replace(/&amp;/g, "&");
  } catch {
    return null;
  }
};

/** What D2 drew: node ids (groups excluded) and edges with direction, from the SVG's group classes. */
export function drawnGraph(svg, groupIds) {
  const nodes = [];
  const edges = [];
  const leaf = (k) => k.split(".").at(-1);
  for (const [, cls] of svg.matchAll(/<g class="([^"]+)"/g)) {
    const key = decode(cls.split(/\s+/)[0]);
    if (!key) continue;
    // An edge between two nodes of one group is named inside it: "group.(a -> b)[0]".
    const edge = /^(?:[A-Za-z0-9_.-]+\.)?\((.+?) (->|--|<-) (.+?)\)\[\d+\]$/.exec(key);
    if (edge) {
      const [from, to] = edge[2] === "<-" ? [edge[3], edge[1]] : [edge[1], edge[3]];
      edges.push({ from: leaf(from), to: leaf(to), directed: edge[2] !== "--" });
    } else if (/^[A-Za-z][A-Za-z0-9_.-]*$/.test(key) && !groupIds.has(key)) {
      nodes.push(leaf(key));
    }
  }
  return { nodes, edges };
}

/** Swap D2's embedded faces for the brand family and drop CSS that styles nothing we draw. */
export function brandSvg(svg, theme) {
  return svg
    .replace(/<\?xml[^>]*\?>/, "")
    .replace(/@font-face\s*\{[^}]*\}/g, "")
    .replace(/font-family:\s*"?d2-\d+-font-(?:regular|italic|bold|semibold)"?/g, `font-family: ${theme.fonts.text}`)
    .replace(/\.md\{[^}]*\}/g, "")
    .replace(/\.appendix text\.text\{[^}]*\}/g, "")
    .replace(/\.d2-\d+ \.(?:fill|stroke|background-color|color)-[A-Z0-9]+\{[^}]*\}/g, "");
}
