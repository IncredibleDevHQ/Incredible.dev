function blocks() {
  if (!n) return;
  const horizontal = [
    "horizontal",
    "compact",
    "side-by-side",
    "split",
    "left-to-right",
    "split-emphasis",
    "focused-step"
  ].includes(variant);
  const grid = ["grid", "table", "stacked-pairs"].includes(variant);
  const cols = horizontal ? n : grid ? Math.min(n, Math.ceil(Math.sqrt(n))) : 1;
  const rows = Math.ceil(n / cols),
    gap = Math.min(24, w / (cols * 12)),
    cw = (w - gap * (cols - 1)) / cols;
  const ch = Math.min((h - gap * (rows - 1)) / rows, h * (horizontal ? 0.52 : 0.26));
  const y0 = top + (h - rows * ch - (rows - 1) * gap) / 2;
  let prev = null;
  items.forEach((item, i) => {
    let x = left + (i % cols) * (cw + gap),
      y = y0 + Math.floor(i / cols) * (ch + gap);
    const g = node("g"),
      isStep = kind === "stepper" || kind === "timeline",
      isCode = kind === "code-block";
    const isText = kind === "statement";
    const rowFont = isCode ? brief.look.fonts.mono : isText ? brief.look.fonts.display : brief.look.fonts.text;
    if (isStep) {
      const alternating = variant === "alternating",
        focused = variant === "focused-step";
      const r = Math.min(29, cw * 0.13, ch * 0.28),
        cx = x + (alternating ? cw * 0.5 : horizontal ? cw / 2 : r + 10),
        cy = y + (horizontal ? ch * 0.32 : ch / 2);
      if (prev) path("M" + prev.cx + " " + prev.cy + "L" + cx + " " + cy, colors.line, g, 4);
      const marker = node("circle", { cx, cy, r, fill: colors.accent }, g);
      const index = label(i + 1, cx, cy, r * 1.6, r, g, "middle", colors.accent_ink);
      if (kind === "stepper" && i + 1 < n) {
        const done = path(
          "M" + (cx - r * 0.45) + " " + cy + "l" + r * 0.3 + " " + r * 0.3 + "l" + r * 0.62 + " " + -r * 0.65,
          colors.accent,
          g,
          3
        );
        tl.fromTo(done, { opacity: 0 }, { opacity: 1, duration: 0.15 }, at(items[i + 1]));
        tl.set(index, { opacity: 0 }, at(items[i + 1]));
      }
      if (focused) {
        const detail = label(words(item), left + w / 2, top + h * 0.8, w * 0.9, size * 1.5, g, "middle");
        if (i + 1 < n) tl.set(detail, { opacity: 0 }, at(items[i + 1]));
      } else {
        const before = alternating && i % 2 === 0;
        label(
          words(item),
          horizontal ? cx : before ? cx - r - 20 : cx + r + 20,
          horizontal ? cy + r + size : cy,
          alternating ? cw * 0.43 : horizontal ? cw * 0.94 : cw - r * 3,
          Math.min(size, ch * 0.5),
          g,
          horizontal ? "middle" : before ? "end" : "start"
        );
      }
      if (prev) tl.to(prev.marker, { attr: { fill: colors.panel, stroke: colors.accent }, duration: 0.2 }, at(item));
      prev = { cx, cy, marker };
    } else if (kind === "list") {
      const text = words(item);
      const numbered = text.match(/^\s*(\d+)\s*[.·):–-]\s*(.+)$/);
      const font = Math.min(size * 1.18, ch * 0.4);
      const cx = x + (horizontal || grid ? cw * 0.5 : font * 0.8);
      const cy = y + (horizontal || grid ? ch * 0.36 : ch * 0.5);
      if (horizontal || grid) {
        const marker = Math.min(font * 1.45, cw * 0.35);
        if (numbered) label(numbered[1], cx, cy, cw * 0.8, marker, g, "middle", colors.accent, brief.look.fonts.mono);
        else node("circle", { cx, cy, r: font * 0.14, fill: colors.accent }, g);
        label(numbered?.[2] || text, cx, cy + font * 1.5, cw * 0.88, font, g, "middle");
        if (i % cols !== cols - 1 && i + 1 < n)
          path(`M${x + cw + gap / 2} ${cy - font * 0.7}v${font * 2.7}`, colors.line, g, 2);
      } else {
        if (numbered) label(numbered[1], cx, cy, font * 1.45, font, g, "middle", colors.accent, brief.look.fonts.mono);
        else node("circle", { cx, cy, r: font * 0.13, fill: colors.accent }, g);
        label(numbered?.[2] || text, x + font * 2, cy, cw - font * 2.2, font, g);
        if (i < n - 1) path(`M${x} ${y + ch + gap / 2}h${cw}`, colors.line, g, 2);
      }
    } else {
      if (!isText) {
        rect(x, y, cw, ch, colors.panel, g);
        rect(x, y, Math.min(7, cw * 0.04), ch, colors.accent, g, 2);
      }
      const centered = horizontal || variant === "centered" || grid;
      const textX = centered ? x + cw / 2 : x + Math.min(30, cw * 0.08);
      label(words(item), textX, y + ch / 2, cw * 0.89, size, g, centered ? "middle" : "start", colors.ink, rowFont);
    }
    reveal(g, item);
  });
}

blocks();
