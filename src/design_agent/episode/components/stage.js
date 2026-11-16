// Embedded inside one HyperFrames composition. The renderer owns its clock.
const svgNS = "http://www.w3.org/2000/svg";
const stage = document.getElementById(comp + "-art");
const { width, height } = brief.canvas;
const { component: kind, variant } = brief.visual;
const root = stage.parentElement;
const theme = root.querySelector("script[data-episode-theme]");
if (theme) brief.look = JSON.parse(theme.textContent);
const colors = brief.look.palette;
root.style.backgroundColor = colors.ground;
root.style.fontFamily = brief.look.fonts.text;
const inset = Math.min(width, height) * 0.055;
const left = inset,
  top = inset;
const right = brief.keep_clear && brief.keep_clear.left > width / 2 ? brief.keep_clear.left - inset : width - inset;
const w = right - left,
  h = height - 2 * inset;
const cues = new Map();
const items = [];
for (const line of brief.lines) {
  for (const cue of line.cues) {
    const target = line.frame + "/" + cue.object;
    if (!cues.has(target)) cues.set(target, cue.key);
  }
  for (const obj of line.objects) items.push({ ...obj, frame: line.frame });
}
function at(item) {
  return clock.cues[item.cue] ?? clock.cues[cues.get(item.frame + "/" + item.id)] ?? clock.lines[item.frame]?.[0] ?? 0;
}
function node(tag, attrs = {}, parent = stage) {
  const el = document.createElementNS(svgNS, tag);
  for (const [key, val] of Object.entries(attrs)) el.setAttribute(key, String(val));
  parent.appendChild(el);
  return el;
}
function rect(x, y, width, height, fill, parent = stage, r = 8) {
  return node("rect", { x, y, width, height, rx: r, fill }, parent);
}
function path(d, color, parent = stage, stroke = 3) {
  return node(
    "path",
    { d, stroke: color, "stroke-width": stroke, fill: "none", "stroke-linecap": "round", "stroke-linejoin": "round" },
    parent
  );
}
function label(
  text,
  x,
  y,
  maxWidth,
  size,
  parent = stage,
  anchor = "start",
  fill = colors.ink,
  font = brief.look.fonts.text
) {
  const el = node(
    "text",
    { x, y, "text-anchor": anchor, fill, "font-family": font, "font-size": size, "dominant-baseline": "middle" },
    parent
  );
  el.textContent = String(text);
  const length = el.getComputedTextLength();
  if (length > maxWidth) el.setAttribute("font-size", String((size * maxWidth) / length));
  return el;
}
const words = (item) => String(item.words || item.what || item.id);
function reveal(el, item) {
  tl.fromTo(el, { opacity: 0 }, { opacity: 1, duration: 0.24, ease: "power1.out" }, at(item));
}
const n = items.length;
const size = Math.min(44, h * 0.051);
