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
  const headerScale = Math.min(size / 34, w / people.length / 140, h / people.length / 110);
  const header = size * 3.5;
  for (const person of people) {
    const x = left + w * lane(person),
      y = top + h * lane(person);
    if (horizontal) {
      participant(left + w * 0.09, y - headerScale * 17, headerScale * 0.7, person, "", stage);
      label(person, left + w * 0.09, y + headerScale * 25, w * 0.17, size * 0.7, stage, "middle");
      path(`M${left + w * 0.19} ${y}H${right}`, colors.line).setAttribute("stroke-dasharray", "5 8");
    } else {
      participant(x, top + headerScale * 32, headerScale, person, "", stage);
      label(person, x, top + headerScale * 75, (w / people.length) * 0.9, size * 0.84, stage, "middle");
      path(`M${x} ${top + header}V${top + h}`, colors.line).setAttribute("stroke-dasharray", "5 8");
    }
  }
  messages.forEach((item, i) => {
    const t = (i + 1) / (messages.length + 1);
    const x = horizontal ? left + w * (0.26 + 0.67 * t) : left + w * lane(item.from);
    const y = horizontal ? top + h * lane(item.from) : top + header + (h - header) * t;
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
    const head = path(
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
    tl.fromTo(head, { opacity: 0 }, { opacity: 1, duration: 0.12 }, at(item) + 0.28);
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
