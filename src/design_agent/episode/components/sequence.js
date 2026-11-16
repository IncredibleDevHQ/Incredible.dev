function sequence() {
  const names = new Map(items.map((o) => [o.id, words(o)]));
  const messages = brief.connections?.length
    ? brief.connections.map((e) => ({
        id: e.object,
        frame: e.frame,
        cue: e.cue,
        words: e.label || "",
        from: names.get(e.from) || e.from,
        to: names.get(e.to) || e.to
      }))
    : items.filter((o) => o.from && o.to);
  const people = [...new Set(messages.flatMap((o) => [o.from, o.to]))];
  if (!messages.length) return false;
  const horizontal = variant === "horizontal-lanes";
  const lane = (name) => (people.indexOf(name) + 0.5) / people.length;
  for (const person of people) {
    const x = left + w * lane(person),
      y = top + h * lane(person);
    if (horizontal) {
      label(person, left, y, w * 0.21, size);
      path("M" + (left + w * 0.23) + " " + y + "H" + right, colors.line);
    } else {
      label(person, x, top + size, (w / people.length) * 0.9, size, stage, "middle");
      path("M" + x + " " + (top + size * 2) + "V" + (top + h), colors.line);
    }
  }
  messages.forEach((item, i) => {
    const t = (i + 1) / (messages.length + 1);
    const x = horizontal ? left + w * (0.26 + 0.67 * t) : left + w * lane(item.from);
    const y = horizontal ? top + h * lane(item.from) : top + h * (0.15 + 0.8 * t);
    const ex = horizontal ? x : left + w * lane(item.to),
      ey = horizontal ? top + h * lane(item.to) : y;
    const g = node("g", { "data-from": item.from, "data-to": item.to }),
      dx = ex - x,
      dy = ey - y,
      mag = Math.hypot(dx, dy) || 1;
    const arrow = path("M" + x + " " + y + "L" + ex + " " + ey, colors.accent, g, 5);
    arrow.setAttribute("stroke-dasharray", mag);
    tl.fromTo(
      arrow,
      { attr: { "stroke-dashoffset": mag } },
      { attr: { "stroke-dashoffset": 0 }, duration: 0.32 },
      at(item)
    );
    const ux = dx / mag,
      uy = dy / mag;
    path(
      "M" +
        (ex - 14 * ux + 7 * uy) +
        " " +
        (ey - 14 * uy - 7 * ux) +
        "L" +
        ex +
        " " +
        ey +
        "L" +
        (ex - 14 * ux - 7 * uy) +
        " " +
        (ey - 14 * uy + 7 * ux),
      colors.accent,
      g,
      4
    );
    label(
      item.words || "",
      (x + ex) / 2,
      (y + ey) / 2 - size * 0.6,
      horizontal ? w * 0.2 : mag * 0.93,
      size * 0.7,
      g,
      "middle"
    );
    reveal(g, item);
    if (variant === "focused-exchange" && i + 1 < messages.length)
      tl.to(g, { opacity: 0.55, duration: 0.2 }, at(messages[i + 1]));
  });
  return true;
}

sequence();
