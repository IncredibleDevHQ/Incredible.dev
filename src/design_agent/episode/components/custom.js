// A live builder redraws this seed to the person's brief. Scripted previews keep the planned objects.
const captioned = variant !== "full-canvas",
  caption = captioned ? items.at(-1) : null;
const art = caption ? items.slice(0, -1) : items;
const artW = variant === "side-caption" ? w * 0.64 : w,
  artH = variant === "bottom-caption" ? h * 0.72 : h;
const cols = Math.max(1, Math.ceil(Math.sqrt(art.length))),
  rows = Math.ceil(art.length / cols);
art.forEach((item, i) => {
  const x = left + (((i % cols) + 0.5) * artW) / cols,
    y = top + ((Math.floor(i / cols) + 0.5) * artH) / rows;
  const g = node("g"),
    cw = (artW / cols) * 0.88,
    ch = Math.min(size * 2.8, (artH / rows) * 0.85);
  rect(x - cw / 2, y - ch / 2, cw, ch, item.state === "active" ? colors.accent : colors.panel, g);
  label(
    words(item),
    x,
    y,
    cw * 0.92,
    Math.min(size, ch * 0.54),
    g,
    "middle",
    item.state === "active" ? colors.accent_ink : colors.ink
  );
  reveal(g, item);
});
if (caption) {
  const side = variant === "side-caption",
    x = side ? left + w * 0.82 : left + w * 0.5,
    y = side ? top + h * 0.5 : top + h * 0.85;
  const el = label(
    words(caption),
    x,
    y,
    side ? w * 0.3 : w * 0.88,
    size,
    stage,
    "middle",
    colors.ink,
    brief.look.fonts.display
  );
  reveal(el, caption);
}
