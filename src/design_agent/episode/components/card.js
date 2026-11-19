// The opening object names the subject. Each following object stays attached to its receipt.
const compact = variant === "compact",
  split = variant === "split";
const cardH = h * (compact ? 0.5 : 0.87),
  cardY = top + (h - cardH) / 2;
rect(left, cardY, w, cardH, colors.panel, stage, 24);
const pad = Math.min(40, w * 0.04);
const heading = items[0];
if (heading) {
  const headerWidth = split ? w * 0.36 : w - 2 * pad;
  const el = label(
    words(heading),
    left + pad,
    cardY + pad + size * 0.5,
    headerWidth,
    size * 1.2,
    stage,
    "start",
    colors.ink,
    brief.look.fonts.display
  );
  reveal(el, heading);
}
const fields = items.slice(1),
  fieldX = left + (split ? w * 0.42 : pad);
const fieldY = cardY + (split ? pad : cardH * 0.29);
const fieldW = right - pad - fieldX,
  fieldH = cardY + cardH - pad - fieldY;
if (split) path("M" + (fieldX - pad / 2) + " " + (cardY + pad) + "v" + (cardH - 2 * pad), colors.line);
const rows = compact ? 1 : Math.max(1, fields.length),
  cols = compact ? Math.max(1, fields.length) : 1;
fields.forEach((item, i) => {
  const g = node("g"),
    cw = fieldW / cols,
    rh = fieldH / rows;
  const x = fieldX + (i % cols) * cw,
    y = fieldY + Math.floor(i / cols) * rh;
  path("M" + x + " " + y + "h" + (cw - pad / 2), colors.line, g, 2);
  const caption = item.what && item.what !== words(item) ? String(item.what) : "";
  if (caption) label(caption, x, y + rh * 0.26, cw * 0.94, Math.min(size * 0.57, rh * 0.24), g, "start", colors.muted);
  const active = item.state === "active" || item.state === "good";
  if (active) {
    const bw = Math.min(cw * 0.94, Math.max(80, words(item).length * size * 0.5 + 30));
    rect(x, y + rh * 0.42, bw, rh * 0.45, colors.accent, g, Math.min(20, rh * 0.2));
    label(words(item), x + bw / 2, y + rh * 0.64, bw * 0.88, Math.min(size, rh * 0.37), g, "middle", colors.accent_ink);
  } else label(words(item), x, y + rh * 0.65, cw * 0.94, Math.min(size, rh * 0.42), g);
  reveal(g, item);
});
