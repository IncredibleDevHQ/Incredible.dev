// Edges and hierarchy come from the supplied relationships. Never infer an arrow from proximity.
const edges = items.filter((o) => o.from && o.to);
const nodes = items.filter((o) => !o.from && !o.to);
const byName = new Map(
  nodes.flatMap((o) => [
    [o.id, o],
    [words(o), o]
  ])
);
function endpoint(value) {
  return byName.get(value)?.id || String(value);
}
const links = brief.connections?.length
  ? brief.connections.map((e) => ({
      a: endpoint(e.from),
      b: endpoint(e.to),
      item: {
        id: e.object,
        frame: e.frame,
        cue: e.cue,
        words: e.label || (e.object !== e.from && e.object !== e.to ? byName.get(e.object)?.words : "")
      },
      blocked: e.blocked
    }))
  : edges.map((o) => ({ a: endpoint(o.from), b: endpoint(o.to), item: o, blocked: false }));
for (const item of nodes) if (item.parent) links.push({ a: endpoint(item.parent), b: item.id, item, blocked: false });
const connected = new Set(links.flatMap((e) => [e.a, e.b]));
const ids = [
  ...new Set([...nodes.filter((o) => !connected.size || connected.has(o.id)).map((o) => o.id), ...connected])
];
const linkLabels = new Set(links.filter((e) => e.item.words).map((e) => e.item.id));
if (variant === "left-to-right") {
  const position = (id) => {
    const text = byName.get(id)?.what || "";
    if (/\b(?:left|right)\b/.test(text) && !/\b(?:line|arrow|callout)\b/.test(text))
      return /\bleft\b/.test(text) ? -1 : 1;
    return 0;
  };
  // Respect the plan's stated orientation when placing already-connected objects.
  ids.sort((a, b) => position(a) - position(b));
}
const notes = nodes.filter((o) => !ids.includes(o.id) && !linkLabels.has(o.id));
const graphHeight = notes.length ? h * 0.66 : h;
const horizontal = variant === "left-to-right",
  swim = variant === "swimlanes";
const owners = [...new Set(nodes.map((o) => String(o.owner || "")))];
const glyphScale = Math.min(
  w / (horizontal ? Math.max(1, ids.length) * 158 : 360),
  graphHeight / (horizontal ? 190 : Math.max(1, ids.length) * 122),
  2.7
);
const bw = glyphScale * 112,
  bh = glyphScale * 70;
const coords = new Map();
function depth(id) {
  const visited = new Set([id]);
  while (true) {
    const parent = links.find((l) => l.b === id)?.a;
    if (!parent || visited.has(parent)) break;
    visited.add(parent);
    id = parent;
  }
  return visited.size - 1;
}
const depths = ids.map(depth),
  levels = Math.max(0, ...depths) + 1;
if (swim)
  owners.forEach((owner, i) => {
    label(
      owner,
      left + ((i + 0.5) * w) / owners.length,
      top + size,
      (w / owners.length) * 0.92,
      size * 0.8,
      stage,
      "middle"
    );
  });
ids.forEach((id, i) => {
  let x, y;
  const item = byName.get(id);
  if (variant === "hub" || variant === "network") {
    const hub = variant === "hub",
      angle = (2 * Math.PI * (i - (hub ? 1 : 0))) / Math.max(1, ids.length - (hub ? 1 : 0)) - Math.PI / 2;
    x = left + w * 0.5 + (hub && i === 0 ? 0 : Math.cos(angle) * (w - bw) * 0.46);
    y = top + graphHeight * 0.5 + (hub && i === 0 ? 0 : Math.sin(angle) * (graphHeight - bh) * 0.43);
  } else if (variant === "tree") {
    const siblings = ids.filter((_, j) => depths[j] === depths[i]);
    x = left + (w * (siblings.indexOf(id) + 0.5)) / siblings.length;
    y = top + (graphHeight * (depths[i] + 0.5)) / levels;
  } else if (swim) {
    const owner = String(item?.owner || "");
    x = left + (w * (Math.max(0, owners.indexOf(owner)) + 0.5)) / owners.length;
    y = top + graphHeight * (0.15 + (0.8 * (i + 0.5)) / ids.length);
  } else {
    const t = (i + 0.5) / ids.length;
    x = left + w * (horizontal ? t : 0.5);
    y = top + graphHeight * (horizontal ? 0.5 : t);
  }
  coords.set(id, [x, y]);
});
links.forEach(({ a, b, item, blocked }) => {
  const [sx, sy] = coords.get(a),
    [ex, ey] = coords.get(b);
  const dx = ex - sx,
    dy = ey - sy,
    length = Math.hypot(dx, dy);
  if (!length) return;
  const ux = dx / length,
    uy = dy / length;
  const offset = Math.min(bw / 2 / Math.max(0.0001, Math.abs(ux)), bh / 2 / Math.max(0.0001, Math.abs(uy)));
  const parallel = horizontal && links.some((other) => other.a === b && other.b === a) ? Math.sign(dx) * bh * 0.24 : 0;
  const x0 = sx + ux * offset,
    y0 = sy + uy * offset + parallel,
    x1 = ex - ux * offset,
    y1 = ey - uy * offset + parallel;
  const g = node("g", { "data-from": a, "data-to": b, "data-blocked": !!blocked });
  const bypass = horizontal && Math.abs(ids.indexOf(a) - ids.indexOf(b)) > 1;

  const d = bypass
    ? `M${sx} ${sy - bh / 2} C${sx} ${sy - bh * 1.65} ${ex} ${ey - bh * 1.65} ${ex} ${ey - bh / 2}`
    : `M${x0} ${y0} L${x1} ${y1}`;
  const stroke = blocked ? colors.muted : colors.accent;
  const wire = path(d, stroke, g, 4),
    len = wire.getTotalLength();
  const tip = wire.getPointAtLength(len),
    prior = wire.getPointAtLength(Math.max(0, len - 2));
  const angle = Math.atan2(tip.y - prior.y, tip.x - prior.x);
  const mid = wire.getPointAtLength(len / 2);
  if (blocked) {
    wire.setAttribute("stroke-dasharray", "9 7");
    const mask = node("mask", { id: comp + "-wire-" + stage.childElementCount, maskUnits: "userSpaceOnUse", x: 0, y: 0, width, height }, stage);
    wire.setAttribute("mask", "url(#" + mask.id + ")");
    trace(path(d, "white", mask, 10), at(item));
    const stop = path(`M${mid.x - 8} ${mid.y - 8}l16 16m0 -16l-16 16`, colors.ink, g, 4);
    tl.fromTo(stop, { opacity: 0 }, { opacity: 1, duration: 0.15 }, at(item) + 0.25);
  } else {
    wire.setAttribute("stroke-dasharray", len);
    tl.fromTo(
      wire,
      { attr: { "stroke-dashoffset": len } },
      { attr: { "stroke-dashoffset": 0 }, duration: 0.35 },
      at(item)
    );
    const pulse = node(
      "circle",
      { cx: tip.x, cy: tip.y, r: 3, fill: "none", stroke, "stroke-width": 3, opacity: 0 },
      g
    );
    tl.fromTo(
      pulse,
      { attr: { r: 3 }, opacity: 0.8 },
      { attr: { r: 15 }, opacity: 0, duration: 0.36, immediateRender: false },
      at(item) + 0.35
    );
    if (kind === "flowchart") {
      const head = path("M-14 -7 L0 0 L-14 7", stroke, g, 4);
      tl.fromTo(head, { opacity: 0 }, { opacity: 1, duration: 0.12 }, at(item) + 0.30);
      head.setAttribute("transform", `translate(${tip.x} ${tip.y}) rotate(${(angle * 180) / Math.PI})`);
    }
  }
  if (item.words) {
    const caption = label(
      item.words,
      mid.x,
      mid.y - size * 0.58,
      Math.min(w * 0.32, Math.max(size * 2, len * 0.85)),
      size * 0.68,
      g,
      "middle"
    );
    caption.setAttribute("paint-order", "stroke");
    caption.setAttribute("stroke", colors.ground);
    caption.setAttribute("stroke-width", 6);
  }
  reveal(g, item);
});
for (const id of ids) {
  const [x, y] = coords.get(id),
    g = node("g", { "data-node": id });
  const item = byName.get(id);
  const name = item ? words(item) : id;
  participant(x, y, glyphScale, name, item?.what || "", g);
  const font = Math.min(size * 1.15, glyphScale * 18);
  const text = label(
    name,
    x,
    y + bh * 0.55 + font * 0.75,
    Math.min(horizontal ? (w / ids.length) * 0.89 : w * 0.55, 2 * Math.min(x - left, right - x)),
    font,
    g,
    "middle"
  );
  text.setAttribute("paint-order", "stroke");
  text.setAttribute("stroke", colors.ground);
  text.setAttribute("stroke-width", 5);
  // Establish the endpoints before an exchange; retain them through the following cues.
  const firstLink = Math.min(...links.filter(link => link.a === id || link.b === id).map(link => at(link.item)));
  const entrance = Math.min(item ? at(item) : 0, Math.max(0, firstLink - 0.28));
  tl.fromTo(g, { opacity: entrance === 0 ? 0.35 : 0, y: 8 },
    { opacity: 1, y: 0, duration: 0.28, ease: "power2.out" }, entrance);
}
const cols = Math.min(4, notes.length),
  rows = Math.ceil(notes.length / (cols || 1));
notes.forEach((item, i) => {
  const cw = w / cols,
    rh = Math.min((h - graphHeight) / rows, size * 1.8);
  const x = left + (i % cols) * cw,
    y = top + graphHeight + Math.floor(i / cols) * rh;
  const g = node("g");
  const font = Math.min(size * 0.72, rh * 0.4);
  path(`M${x + 6} ${y + rh * 0.5}h${font * 0.7}`, colors.accent, g, 4);
  label(words(item), x + font + 10, y + rh / 2, cw - font - 20, font, g, "start");
  reveal(g, item);
});
