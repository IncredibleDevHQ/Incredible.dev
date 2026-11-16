const numbered = variant === "focused-excerpt",
  withNotes = variant === "side-notes";
const rowH = Math.min(size * 2.3, h / Math.max(1, n)),
  start = top + (h - rowH * n) / 2;
rect(left, start, w, rowH * n, colors.panel);
items.forEach((item, i) => {
  const g = node("g"),
    y = start + (i + 0.5) * rowH;
  const numberSpace = numbered ? size * 1.8 : 0;
  if (numbered) label(i + 1, left + size * 0.5, y, size, size * 0.7, g, "start", colors.muted, brief.look.fonts.mono);
  label(
    words(item),
    left + size * 0.5 + numberSpace,
    y,
    w * (withNotes ? 0.6 : 0.93) - numberSpace,
    Math.min(rowH * 0.52, size),
    g,
    "start",
    colors.ink,
    brief.look.fonts.mono
  );
  if (withNotes && item.what !== item.words)
    label(item.what || "", left + w * 0.67, y, w * 0.28, size * 0.67, g, "start", colors.muted);
  const mark = rect(left, y - rowH * 0.43, 6, rowH * 0.86, colors.accent, g, 1);
  reveal(g, item);
  if (i + 1 < n) tl.to(mark, { opacity: 0, duration: 0.18 }, at(items[i + 1]));
});
