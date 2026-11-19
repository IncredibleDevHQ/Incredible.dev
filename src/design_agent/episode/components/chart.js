function chart() {
  const data = items.filter((item) => typeof item.value === "number" && Number.isFinite(item.value));
  if (!data.length) return;
  const series = [...new Set(data.map((o) => o.series || ""))],
    cats = [...new Set(data.map(words))];
  const lo = Math.min(0, ...data.map((o) => o.value)),
    hi = Math.max(0, ...data.map((o) => o.value));
  const scale = (v) => (v - lo) / (hi - lo || 1);
  const unit = String(data[0].unit || "");
  label(unit, left, top + size, w, size);
  const grouped = variant === "grouped",
    small = variant === "small-multiples",
    horizontal = variant === "horizontal";
  const plotX = left + w * 0.15,
    plotY = top + h * 0.19,
    plotW = w * 0.76,
    plotH = h * 0.64;
  const tone = brief.look.series?.length ? brief.look.series : [colors.accent, colors.ink, colors.muted];
  if (series.some(Boolean))
    label(series.join("   /   "), right, top + size, w * 0.65, size * 0.7, stage, "end", colors.muted);
  // Establish the scale before the first measured mark enters.
  const panels = small ? series.length : 1;
  for (let panel = 0; panel < panels; panel++) {
    const ph = plotH / panels,
      py = plotY + panel * ph;
    for (const value of new Set([lo, 0, hi])) {
      const t = scale(value);
      const x = horizontal ? plotX + t * plotW : plotX;
      const y = horizontal ? py : py + (1 - t) * ph;
      path("M" + x + " " + y + (horizontal ? "v" + ph : "h" + plotW), colors.line, stage, value === 0 ? 3 : 1);
      if (horizontal) label(value, x, py + ph + size * 0.6, plotW * 0.15, size * 0.57, stage, "middle", colors.muted);
      else label(value, x - 10, y, w * 0.12, size * 0.57, stage, "end", colors.muted);
    }
    if (small) label(series[panel], right, py + size * 0.5, w * 0.16, size * 0.65, stage, "end", colors.muted);
  }
  data.forEach((item) => {
    const cat = cats.indexOf(words(item)),
      s = series.indexOf(item.series || "");
    const g = node("g"),
      color = tone[s % tone.length];
    const fmt = String(item.value);
    if (kind === "bar-chart" && horizontal) {
      const row = plotH / data.length,
        y = plotY + data.indexOf(item) * row;
      const zero = plotX + plotW * scale(0),
        end = plotX + plotW * scale(item.value);
      label(words(item), plotX - 8, y + row * 0.4, w * 0.15, size * 0.72, g, "end");
      const bar = rect(Math.min(zero, end), y + row * 0.15, Math.abs(end - zero), row * 0.5, color, g, 2);
      tl.fromTo(
        bar,
        { attr: { x: zero, width: 0 } },
        { attr: { x: Math.min(zero, end), width: Math.abs(end - zero) }, duration: 0.38 },
        at(item)
      );
      label(
        fmt,
        end + (item.value < 0 ? -6 : 6),
        y + row * 0.4,
        w * 0.09,
        size * 0.65,
        g,
        item.value < 0 ? "end" : "start"
      );
    } else if (kind === "bar-chart") {
      const count = grouped ? cats.length : data.length,
        cell = plotW / count,
        split = grouped ? series.length : 1;
      const slot = grouped ? cat : data.indexOf(item);
      const x = plotX + (slot + 0.12) * cell + ((grouped ? s : 0) * cell * 0.76) / split,
        bw = (cell * 0.7) / split;
      const zero = plotY + plotH * (1 - scale(0)),
        end = plotY + plotH * (1 - scale(item.value));
      const bar = rect(x, Math.min(zero, end), bw, Math.abs(end - zero), color, g, 2);
      tl.fromTo(
        bar,
        { attr: { y: zero, height: 0 } },
        { attr: { y: Math.min(end, zero), height: Math.abs(end - zero) }, duration: 0.38 },
        at(item)
      );
      label(fmt, x + bw / 2, end + (item.value < 0 ? 16 : -16), bw, size * 0.65, g, "middle");
      if (!grouped || s === 0)
        label(words(item), plotX + (slot + 0.5) * cell, plotY + plotH + size, cell * 0.93, size * 0.72, g, "middle");
    } else {
      const sh = small ? plotH / series.length : plotH,
        sy = plotY + (small ? s * sh : 0);
      const xy = (o) => [
        plotX + (plotW * cats.indexOf(words(o))) / Math.max(1, cats.length - 1),
        sy + sh * (1 - scale(o.value))
      ];
      const [x, y] = xy(item),
        prior = data
          .slice(0, data.indexOf(item))
          .filter((o) => o.series === item.series)
          .pop();
      if (prior) {
        const [px, py] = xy(prior);
        const line = path("M" + px + " " + py + "L" + x + " " + y, color, g);
        const len = line.getTotalLength();
        line.setAttribute("stroke-dasharray", len);
        tl.fromTo(
          line,
          { attr: { "stroke-dashoffset": len } },
          { attr: { "stroke-dashoffset": 0 }, duration: 0.38 },
          at(item)
        );
      }
      node("circle", { cx: x, cy: y, r: 6, fill: color }, g);
      label(fmt, x, y - 19, w * 0.1, size * 0.62, g, "middle");
      if (s === 0) label(words(item), x, plotY + plotH + size, plotW / cats.length, size * 0.65, g, "middle");
    }
    reveal(g, item);
  });
}

chart();
