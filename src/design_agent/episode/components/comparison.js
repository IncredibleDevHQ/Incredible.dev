const cols = variant === "side-by-side" ? Math.max(1, Math.min(n, 3)) : 2;
const rows = Math.ceil(n / cols),
  cw = w / cols,
  rh = Math.min(h / Math.max(1, rows), size * 3.6);
items.forEach((item, i) => {
  const col = i % cols,
    row = Math.floor(i / cols),
    x = left + col * cw,
    y = top + row * rh,
    g = node("g");
  if (variant === "side-by-side") rect(x + 4, y + 4, cw - 8, rh - 8, colors.panel, g);
  if (variant === "table") {
    path("M" + x + " " + (y + rh) + "h" + cw, colors.line, g);
    if (col) path("M" + x + " " + y + "v" + rh, colors.line, g);
  }
  if (variant === "stacked-pairs" && col === 0) rect(x, y + rh * 0.1, 6, rh * 0.8, colors.accent, g, 2);
  label(words(item), x + cw * 0.5, y + rh * 0.5, cw * 0.88, Math.min(size, rh * 0.5), g, "middle");
  reveal(g, item);
});
