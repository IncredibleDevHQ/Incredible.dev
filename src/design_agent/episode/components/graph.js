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
const links = edges.map((o) => ({ a: endpoint(o.from), b: endpoint(o.to), item: o }));
for (const item of nodes) if (item.parent) links.push({ a: endpoint(item.parent), b: item.id, item });
const ids = [...new Set([...nodes.map((o) => o.id), ...links.flatMap((e) => [e.a, e.b])])];
const horizontal = variant === "left-to-right",
  swim = variant === "swimlanes";
const owners = [...new Set(nodes.map((o) => String(o.owner || "")))];
const bw = Math.min(w * 0.3, Math.max(75, w / Math.max(3, Math.sqrt(ids.length) * 2))),
  bh = Math.min(size * 2, h / Math.max(4, ids.length + 1));
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
    y = top + h * 0.5 + (hub && i === 0 ? 0 : Math.sin(angle) * (h - bh) * 0.43);
  } else if (variant === "tree") {
    const siblings = ids.filter((_, j) => depths[j] === depths[i]);
    x = left + (w * (siblings.indexOf(id) + 0.5)) / siblings.length;
    y = top + (h * (depths[i] + 0.5)) / levels;
  } else if (swim) {
    const owner = String(item?.owner || "");
    x = left + (w * (Math.max(0, owners.indexOf(owner)) + 0.5)) / owners.length;
    y = top + h * (0.15 + (0.8 * (i + 0.5)) / ids.length);
  } else {
    const t = (i + 0.5) / ids.length;
    x = left + w * (horizontal ? t : 0.5);
    y = top + h * (horizontal ? 0.5 : t);
  }
  coords.set(id, [x, y]);
});
links.forEach(({ a, b, item }) => {
  const [sx, sy] = coords.get(a),
    [ex, ey] = coords.get(b),
    dx = ex - sx,
    dy = ey - sy;
  const mag = Math.hypot(dx, dy);
  if (!mag) return;
  const offset = Math.min(bw / 2 / Math.max(0.0001, Math.abs(dx / mag)), bh / 2 / Math.max(0.0001, Math.abs(dy / mag)));
  const x = ex - (offset * dx) / mag,
    y = ey - (offset * dy) / mag,
    g = node("g");
  path("M" + sx + " " + sy + "L" + x + " " + y, colors.accent, g);
  if (kind === "flowchart")
    path(
      "M" +
        (x - (12 * dx) / mag + (6 * dy) / mag) +
        " " +
        (y - (12 * dy) / mag - (6 * dx) / mag) +
        "L" +
        x +
        " " +
        y +
        "L" +
        (x - (12 * dx) / mag - (6 * dy) / mag) +
        " " +
        (y - (12 * dy) / mag + (6 * dx) / mag),
      colors.accent,
      g
    );
  if (item.words && item.from)
    label(words(item), (sx + ex) / 2, (sy + ey) / 2 - size * 0.55, w * 0.3, size * 0.6, g, "middle");
  reveal(g, item);
});
for (const id of ids) {
  const [x, y] = coords.get(id),
    g = node("g");
  rect(x - bw / 2, y - bh / 2, bw, bh, colors.panel, g);
  const item = byName.get(id);
  label(item ? words(item) : id, x, y, bw * 0.92, Math.min(size, bh * 0.58), g, "middle");
  if (item) reveal(g, item);
}
