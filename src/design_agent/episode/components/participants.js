// Participants keep a silhouette at thumbnail size. The drawing is local and uses only look tokens.
function participantKind(name, description) {
  function match(text) {
    if (/\bbrowser\b|\bweb page\b/i.test(text)) return "browser";
    if (/\bserver\b|\borigin\b/i.test(text)) return "server";
    if (/\bcache\b|\bstorage\b|\bdatabase\b/i.test(text)) return "storage";
    if (/\bdecision\b|\bcondition\b/i.test(text)) return "decision";
    if (/\bfile\b|\bdocument\b|\brequest payload\b|\.(?:png|js|html|pdf)\b/i.test(text)) return "document";
    if (/\b(?:person|user|customer|buyer|speaker)\b/i.test(text)) return "person";
    if (/\b(?:bank|issuer)\b/i.test(text)) return "bank";
    if (/\b(?:store|shop|merchant)\b/i.test(text)) return "shop";
    return "";
  }
  return match(name) || match(description) || "point";
}

function participant(x, y, scale, name, description, parent) {
  const role = participantKind(name, description);
  const g = node(
    "g",
    {
      transform: `translate(${x} ${y}) scale(${scale})`,
      "data-symbol": role,
      "stroke-linejoin": "round",
      "stroke-linecap": "round"
    },
    parent
  );
  const { ink, panel, accent, ground } = colors;
  const surface = (d, fill = panel, stroke = ink, weight = 2.4) =>
    node("path", { d, fill, stroke, "stroke-width": weight }, g);
  const line = (d, color = ink, weight = 2.4) => path(d, color, g, weight);
  const dot = (cx, cy, r, fill) => node("circle", { cx, cy, r, fill }, g);
  if (role === "browser") {
    surface("M-49 -33 H38 Q44 -33 44 -27 V24 Q44 30 38 30 H-49 Q-55 30 -55 24 V-27 Q-55 -33 -49 -33Z");
    line("M-54 -19 H43");
    [-45, -38, -31].forEach((cx) => dot(cx, -26, 1.7, ink));
    surface("M-43 -9 H-26 V9 H-43Z", accent, accent, 1);
    line("M-18 -5 H21 M-18 3 H8", ink, 2);
    if (/cache/i.test(name + " " + description)) {
      surface("M13 9 L37 3 L55 11 L31 18Z", panel);
      surface("M13 9 V24 L31 32 L55 24 V11 L31 18Z", panel);
      line("M31 18 V31 M14 17 L31 25 L54 18", accent, 2);
    }
  } else if (role === "server") {
    for (const dy of [11, -10, -31]) {
      const unit = node("g", { transform: `translate(0 ${dy})` }, g);
      node("path", { d: "M-43 1 L-22 -8 H43 L24 1Z", fill: ground, stroke: ink, "stroke-width": 2.4 }, unit);
      node(
        "path",
        { d: "M-43 1 H24 V19 H-43Z M24 1 L43 -8 V10 L24 19Z", fill: panel, stroke: ink, "stroke-width": 2.4 },
        unit
      );
      node("circle", { cx: -35, cy: 10, r: 2.5, fill: accent }, unit);
      path("M-26 10 H-8 M9 7 V13 M15 7 V13", ink, unit, 1.7);
    }
  } else if (role === "storage") {
    surface("M-35 -22 C-35 -38 35 -38 35 -22 V20 C35 38 -35 38 -35 20Z");
    line("M-35 -22 C-35 -7 35 -7 35 -22 M-35 -6 C-35 9 35 9 35 -6 M-35 9 C-35 25 35 25 35 9");
    dot(22, 22, 3, accent);
  } else if (role === "document") {
    surface("M-24 -33 H10 L27 -17 V33 H-24Z");
    line("M10 -32 V-17 H26 M-14 -5 H14 M-14 5 H14 M-14 15 H3", ink);
    line("M-24 -26 V18", accent, 4);
  } else if (role === "decision") {
    surface("M0 -33 L40 0 L0 33 L-40 0Z");
    line("M-10 0 L-2 9 L13 -10", accent, 4);
  } else if (role === "person") {
    node("circle", { cx: 0, cy: -15, r: 12, fill: panel, stroke: ink, "stroke-width": 2.5 }, g);
    surface("M-26 29 Q-24 -2 0 0 Q24 -2 26 29Z");
    line("M-16 27 H16", accent, 3);
  } else if (role === "bank") {
    surface("M-38 -11 L0 -32 L38 -11Z");
    [-25, 0, 25].forEach((cx) => line(`M${cx} -4 V19`, ink, 5));
    line("M-37 26 H37", accent, 5);
  } else if (role === "shop") {
    surface("M-32 -8 H32 V28 H-32Z");
    surface("M-36 -8 L-27 -27 H27 L36 -8 Q27 5 18 -8 Q9 5 0 -8 Q-9 5 -18 -8 Q-27 5 -36 -8Z", panel);
    line("M-20 8 H-5 V20 H-20Z M8 28 V6 H22 V28", accent, 2.5);
  } else {
    node("circle", { cx: 0, cy: 0, r: 25, fill: panel, stroke: ink, "stroke-width": 2.5 }, g);
    dot(0, 0, 8, accent);
  }
  return g;
}
