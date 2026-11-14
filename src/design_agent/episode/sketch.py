"""A picture drawn by code from its brief alone: every object as a labelled block, arriving on
its cue.

It is what the demo shows and what tests build, where no agent is there to design one. It is a
stand-in, plain on purpose: it proves the clock and the layout, not the craft.
"""

from __future__ import annotations

import html as html_lib
import json
import math
from typing import Any

from design_agent.episode import picture

Row = dict[str, Any]


def built(brief: Row) -> str:
    """The file a picture's brief (`picture.brief`) asks for, drawn the plainest way."""
    colours = {**picture.PALETTE, **brief["look"]["palette"]}
    comp = str(brief["composition_id"])
    width, height = int(brief["canvas"]["width"]), int(brief["canvas"]["height"])
    objects: list[tuple[str, Row]] = []
    first_cue: dict[str, str] = {}
    keys: list[str] = []
    for line in brief["lines"]:
        for o in line.get("objects", []):
            objects.append((line["frame"], o))
        for cue in line.get("cues", []):
            keys.append(cue["key"])
            first_cue.setdefault(str(cue.get("object")), cue["key"])
    clear = brief.get("keep_clear")
    usable_w = width - 2 * 96 - (clear["width"] if clear and clear["left"] > width / 2 else 0)
    columns = max(1, min(3, math.ceil(math.sqrt(max(len(objects), 1)))))
    rows = max(1, math.ceil(len(objects) / columns))
    gap = 28
    cell_w = (usable_w - gap * (columns - 1)) / columns
    cell_h = min(190.0, (height - 2 * 110 - gap * (rows - 1)) / rows)
    blocks, moves = [], []
    for i, (frame_id, o) in enumerate(objects):
        left = 96 + (i % columns) * (cell_w + gap)
        top = 110 + (i // columns) * (cell_h + gap)
        ident = f"{comp}-o{i}"
        label = html_lib.escape(str(o.get("words") or o.get("what") or o.get("id")), quote=False)
        active = o.get("state") == "active"
        fill = colours["accent"] if active else colours["panel"]
        ink = colours["accent_ink"] if active else colours["ink"]
        blocks.append(
            f'<div class="{comp}-block" id="{ident}" style="left: {left:.0f}px; top: {top:.0f}px; '
            f'width: {cell_w:.0f}px; height: {cell_h:.0f}px; background: {fill}; color: {ink}">'
            f"{label}</div>"
        )
        key = first_cue.get(str(o.get("id")))
        at = f"clock.cues[{json.dumps(key)}]" if key else f"clock.lines[{json.dumps(frame_id)}][0]"
        moves.append(
            f'tl.fromTo("#{ident}", {{ opacity: 0, y: 24 }}, '
            f'{{ opacity: 1, y: 0, duration: 0.45, ease: "power2.out" }}, {at});'
        )
    size = max(26, round(height * 0.034))
    return f"""<!doctype html>
<html>
  <head><meta charset="UTF-8" /></head>
  <body>
    <template>
      <style>
        #root {{ position: absolute; inset: 0; background: {colours["ground"]}; font-family: '{brief["look"]["fonts"]["text"]}', sans-serif; }}
        .{comp}-block {{ position: absolute; box-sizing: border-box; display: flex; align-items: center; justify-content: center; padding: 18px 24px; border-radius: 18px; border: 2px solid {colours["line"]}; font-size: {size}px; font-weight: 600; text-align: center; line-height: 1.2; }}
      </style>
      <div id="root" data-composition-id="{comp}" data-width="{width}" data-height="{height}">
        <script type="application/json" id="{comp}-clock">{{"seconds": 0, "lines": {{}}, "cues": {{}}}}</script>
        {"".join(blocks)}
      </div>
      <script>
        (function () {{
          // every cue of this picture: {" ".join(keys)}
          const clock = JSON.parse(document.getElementById("{comp}-clock").textContent);
          const tl = gsap.timeline({{ paused: true }});
          {" ".join(moves)}
          window.__timelines["{comp}"] = tl;
        }})();
      </script>
    </template>
  </body>
</html>
"""
