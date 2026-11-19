// Physical subjects have silhouettes and material details that read at thumbnail size.
function physicalGlyph(g, asset) {
  const pen = { color: colors.ink, width: 2, linecap: "round", linejoin: "round" };
  const shape = (d, fill) => g.path(d).fill(fill).stroke(pen);
  const detail = (d, color = colors.ink, width = 1.5) =>
    g.path(d).fill("none").stroke({ ...pen, color, width });
  switch (asset) {
    case "metal-spoon":
    case "wooden-spoon": {
      const wood = asset === "wooden-spoon";
      shape("M10 59 Q3 59 3 64 Q3 69 10 69 L61 68 Q71 68 80 74 Q91 83 103 83 C115 83 125 75 125 64 C125 53 115 45 103 45 Q91 45 80 54 Q71 60 61 60Z", wood ? "#d8a46c" : "#cddce4");
      shape("M83 64 Q89 51 104 51 C113 51 120 57 120 64 C120 71 113 77 104 77 Q89 77 83 64Z", wood ? "#b47742" : "#819eaf");
      if (wood) {
        detail("M11 63 Q35 66 65 63 M89 63 Q101 55 114 61 M92 69 Q103 64 115 68", "#72502e");
      } else {
        detail("M12 62 L62 63 Q74 62 82 56 M90 61 Q103 51 114 58 M98 73 Q110 76 116 69", "#fff", 2);
      }
      return true;
    }
    case "hand":
      shape("M6 52 H30 V88 H6Z", colors.accent);
      shape("M26 53 Q40 41 53 43 L109 49 Q122 50 122 59 Q122 66 110 67 L75 67 Q83 74 75 81 Q72 92 63 92 Q58 100 47 97 L26 86Z", "#df9b75");
      detail("M50 66 Q59 67 71 77 M47 78 L66 87 M48 88 L59 93 M109 54 H116", "#734430");
      return true;
    case "thermometer":
      shape("M55 82 V19 A9 9 0 0 1 73 19 V82 A18 18 0 1 1 55 82Z", colors.panel);
      g.circle(24).center(64, 98).fill(colors.accent);
      g.rect(7, 57).move(60.5, 40).radius(3.5).fill(colors.accent);
      detail("M68 30 H76 M68 42 H76 M68 54 H76 M68 66 H76 M68 78 H76");
      return true;
    case "cup":
      shape("M89 46 H108 C129 46 129 79 101 83 H90 V74 H101 C117 71 119 56 107 56 H89Z", colors.panel);
      shape("M12 41 H99 L94 83 Q91 100 74 102 H39 Q22 100 17 83Z", colors.panel);
      g.ellipse(87, 26).center(55.5, 41).fill(colors.ground).stroke(pen);
      g.ellipse(70, 13).center(55.5, 43).fill("#9b623f");
      detail("M25 62 Q28 85 36 89 M42 29 Q39 20 44 12 M63 28 Q60 18 66 8");
      return true;
    default:
      return false;
  }
}
