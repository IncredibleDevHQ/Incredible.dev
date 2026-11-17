const cols = variant === "side-by-side" ? Math.max(1, Math.min(3, Math.ceil(Math.sqrt(n)))) : 2;
const rows = Math.ceil(n / cols),
  gap = Math.min(size * 0.65, w / cols * 0.12),
  cw = w / cols,
  rh = Math.min(h / Math.max(1, rows), size * 5);
items.forEach((item, i) => {
  const col = i % cols,
    row = Math.floor(i / cols),
    x = left + col * cw,
    y = top + (h - rows * rh) / 2 + row * rh,
    g = node("g");
  if (variant === "side-by-side") rect(x + gap / 2, y + gap / 2, cw - gap, rh - gap, colors.panel, g);
  if (variant === "table") {
    path("M" + x + " " + (y + rh) + "h" + cw, colors.line, g);
    if (col) path("M" + x + " " + y + "v" + rh, colors.line, g);
  }
  if (variant === "stacked-pairs" && col === 0) rect(x, y + rh * 0.1, 6, rh * 0.8, colors.accent, g, 2);
  label(words(item), x + cw * 0.5, y + rh * 0.5, cw * 0.88, Math.min(size, rh * 0.5), g, "middle");
  reveal(g, item);
});
