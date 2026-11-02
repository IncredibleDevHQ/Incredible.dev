// cycle.mjs: a flywheel (2-8 stages in one directed loop) with every coordinate computed here.
//
// Stages sit on a ring, clockwise from the top in the order the contract's edges visit them. Each
// connector is an arc of that ring, trimmed where it meets the stage boxes, ending in one arrowhead
// style. The highlighted stage is the one accent-coloured element. Geometry only; the contract is
// validated and hashed by graph-contract.mjs.

import { SpecError } from "./charts.mjs";
import { textWidth, wrap } from "./measure.mjs";

const fail = (message) => {
  throw new SpecError(message);
};

const LOOP_KINDS = new Set(["flow", "feedback", "return", "human-loop"]);

/** Node ids in loop order, or a reason the edges are not one loop through every stage. */
export function loopOrder(contract) {
  const n = contract.nodes.length;
  if (n < 2 || n > 8) fail(`a cycle has 2-8 stages, not ${n}`);
  if (contract.edges.length !== n) fail(`a cycle of ${n} stages has exactly ${n} edges, not ${contract.edges.length}`);
  const next = new Map();
  for (const edge of contract.edges) {
    if (!LOOP_KINDS.has(edge.kind)) fail(`cycle edge ${edge.id} has kind ${edge.kind}; use flow`);
    if (next.has(edge.from)) fail(`stage ${edge.from} has two outgoing edges: a cycle is one loop`);
    next.set(edge.from, edge);
  }
  const order = [contract.nodes[0].id];
  const edges = [];
  while (edges.length < n) {
    const edge = next.get(order.at(-1));
    if (!edge) fail(`stage ${order.at(-1)} has no outgoing edge: a cycle is one loop`);
    edges.push(edge);
    if (edge.to === order[0]) break;
    if (order.includes(edge.to)) fail("the edges close a loop that skips some stages");
    order.push(edge.to);
  }
  if (order.length !== n || edges.length !== n) fail("the edges do not visit every stage exactly once");
  return { order, edges };
}

function inside(px, py, box, gap) {
  return Math.abs(px - box.cx) <= box.hw + gap && Math.abs(py - box.cy) <= box.hh + gap;
}

/** Angular offset from a stage's centre to where the ring leaves its (padded) box. */
function exitAngle(theta, R, cx, cy, box, gap, direction) {
  let lo = 0;
  let hi = Math.PI;
  for (let i = 0; i < 40; i++) {
    const mid = (lo + hi) / 2;
    const a = theta + direction * mid;
    if (inside(cx + R * Math.cos(a), cy + R * Math.sin(a), box, gap)) lo = mid;
    else hi = mid;
  }
  return hi;
}

export function buildCycle(contract, presentation, theme, m, plot) {
  const { order, edges } = loopOrder(contract);
  const label = new Map(contract.nodes.map((node) => [node.id, node.label]));
  const highlight = presentation.highlight;
  if (highlight !== undefined && !label.has(highlight)) fail(`highlight "${highlight}" is not a stage id`);
  const n = order.length;
  const cx = plot.x + plot.w / 2;
  const cy = plot.y + plot.h / 2;
  const font = Math.max(14, Math.round(m.label * 1.25));
  const pad = Math.round(font * 1.1);
  // Long stage names wrap to two lines: a narrow box leaves the ring more room.
  const maxLine = Math.min(plot.w * 0.25, font * 8);
  const boxes = new Map();
  for (const id of order) {
    const lines = wrap(label.get(id), font, maxLine, { maxLines: 2 });
    if (!lines) fail(`stage "${label.get(id)}" does not fit on two lines: shorten it`);
    const w = Math.max(...lines.map((l) => textWidth(l, font))) + 2 * pad;
    const h = lines.length * font * 1.25 + pad * 1.4;
    boxes.set(id, { lines, w: Math.max(w, h * 2), h });
  }
  const maxW = Math.max(...[...boxes.values()].map((b) => b.w));
  const maxH = Math.max(...[...boxes.values()].map((b) => b.h));
  const R = Math.min(plot.w / 2 - maxW / 2, plot.h / 2 - maxH / 2);
  if (R < maxH * 1.5) fail("the canvas is too small for this cycle: fewer stages, shorter labels or a bigger canvas");
  const gap = m.unit;
  const arrowLength = Math.max(theme.stroke * 6, 12);
  const graphics = [];
  const placed = order.map((id, i) => {
    const theta = -Math.PI / 2 + (i * 2 * Math.PI) / n;
    const b = boxes.get(id);
    return { id, theta, cx: cx + R * Math.cos(theta), cy: cy + R * Math.sin(theta), hw: b.w / 2, hh: b.h / 2, ...b };
  });
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const a = placed[i];
      const b = placed[j];
      if (Math.abs(a.cx - b.cx) < a.hw + b.hw + gap && Math.abs(a.cy - b.cy) < a.hh + b.hh + gap) {
        fail("stages overlap at this size: fewer stages, shorter labels or a bigger canvas");
      }
    }
  }
  const drawnEdges = [];
  const edgeTexts = [];
  edges.forEach((edge, i) => {
    const from = placed[i];
    const to = placed[(i + 1) % n];
    const start = from.theta + exitAngle(from.theta, R, cx, cy, from, gap, 1);
    let end = to.theta - exitAngle(to.theta, R, cx, cy, to, gap, -1);
    if (end <= start) end += 2 * Math.PI;
    const arrowAngle = arrowLength / R;
    if (end - start <= arrowAngle * 1.5) fail("stages are too close for a readable connector: a bigger canvas or fewer stages");
    graphics.push({ type: "arc", shape: { cx, cy, r: R, startAngle: start, endAngle: end - arrowAngle, clockwise: true },
      style: { stroke: theme.muted, lineWidth: theme.stroke, fill: "none", lineCap: "round" } });
    const tip = [cx + R * Math.cos(end), cy + R * Math.sin(end)];
    const baseAngle = end - arrowAngle;
    const base = [cx + R * Math.cos(baseAngle), cy + R * Math.sin(baseAngle)];
    const normal = [Math.cos(baseAngle), Math.sin(baseAngle)];
    const half = arrowLength * 0.45;
    graphics.push({ type: "polygon", shape: { points: [tip, [base[0] + normal[0] * half, base[1] + normal[1] * half], [base[0] - normal[0] * half, base[1] - normal[1] * half]] },
      style: { fill: theme.muted } });
    drawnEdges.push({ from: edge.from, to: edge.to, directed: true });
    if (edge.label) {
      const mid = (start + end) / 2;
      const r = R + maxH * 0.5 + m.unit * 2;
      const x = cx + r * Math.cos(mid);
      const y = cy + r * Math.sin(mid);
      graphics.push({ type: "text", style: { text: edge.label, x, y, align: Math.abs(Math.cos(mid)) < 0.2 ? "center" : Math.cos(mid) > 0 ? "left" : "right",
        verticalAlign: "middle", fill: theme.muted, font: `${theme.weights.text} ${m.axis}px ${theme.fonts.text}` } });
      edgeTexts.push(edge.label);
    }
  });
  for (const p of placed) {
    const hero = p.id === highlight;
    const fill = hero ? theme.accent : theme.ground;
    graphics.push({ type: "rect", shape: { x: p.cx - p.hw, y: p.cy - p.hh, width: p.w, height: p.h, r: theme.radius },
      style: { fill, stroke: hero ? theme.accent : theme.ink, lineWidth: theme.stroke } });
    p.lines.forEach((text, k) => {
      const y = p.cy + (k - (p.lines.length - 1) / 2) * font * 1.25;
      graphics.push({ type: "text", style: { text, x: p.cx, y, align: "center", verticalAlign: "middle", fill: theme.onFill(fill),
        font: `${hero ? theme.weights.strong : theme.weights.text} ${font}px ${theme.fonts.text}` } });
    });
  }
  const texts = [...placed.flatMap((p) => p.lines), ...edgeTexts];
  const fontSizes = [font, ...(edgeTexts.length ? [m.axis] : [])];
  if (presentation.center) {
    const size = Math.max(16, Math.round(m.title * 0.75));
    const lines = wrap(presentation.center, size, R * 1.1, { maxLines: 2, weight: theme.weights.display });
    if (!lines) fail("center text does not fit inside the ring on two lines");
    lines.forEach((text, k) => {
      graphics.push({ type: "text", style: { text, x: cx, y: cy + (k - (lines.length - 1) / 2) * size * 1.15, align: "center", verticalAlign: "middle",
        fill: theme.ink, font: `${theme.weights.display} ${size}px ${theme.fonts.display}` } });
    });
    texts.push(...lines);
    fontSizes.push(size);
  }
  return { graphics, texts, fontSizes, drawn: { nodes: order, edges: drawnEdges }, usesDisplay: Boolean(presentation.center) };
}
