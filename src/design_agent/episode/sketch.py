"""Build a self-contained, cue-driven picture from the episode brief.

The demo renders this scene directly. A live worker receives it as the starting picture
for the selected component, brand and layout.
"""

from __future__ import annotations

import html as html_lib
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from design_agent.episode import catalog, picture

Row = dict[str, Any]


def built(brief: Row) -> str:
    """The file a picture's brief (`picture.brief`) asks for, drawn the plainest way."""
    if brief.get("visual", {}).get("component"):
        return component_scene(brief)
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


_ADAPTERS = {
    "sequence-diagram": "sequence",
    "bar-chart": "chart",
    "line-chart": "chart",
    "relationship-diagram": "graph",
    "flowchart": "graph",
    "detail-card": "card",
    "comparison": "comparison",
    "code-block": "code",
    "custom": "custom",
}


@lru_cache(maxsize=12)
def _scene_script(adapter: str) -> str:
    folder = Path(__file__).with_name("components")
    scripts = ["stage"]
    if adapter in ("graph", "sequence"):
        scripts.append("participants")
    scripts.append(adapter)
    return "\n".join((folder / f"{name}.js").read_text(encoding="utf8") for name in scripts)


def component_scene(brief: Row) -> str:
    """One self-contained stage shared by the demo and the live builder's starting file."""
    comp = brief["composition_id"]
    canvas = brief["canvas"]
    visual = brief["visual"]
    scene = {key: brief[key] for key in ("canvas", "keep_clear", "look")}
    scene["connections"] = brief.get("connections", [])
    scene["subject"] = brief.get("picture", {}).get("shows", "")
    scene["visual"] = {key: visual[key] for key in ("component", "variant")}
    chart = visual["component"] in ("bar-chart", "line-chart")
    scene["lines"] = [
        {
            "frame": line["frame"],
            "objects": [obj for obj in line["objects"] if not chart or catalog.measured(obj)],
            "cues": [{"key": c["key"], "object": c.get("object", "")} for c in line["cues"]],
        }
        for line in brief["lines"]
    ]
    payload = json.dumps(scene, ensure_ascii=True).replace("<", r"\u003c")
    theme = json.dumps(brief["look"], ensure_ascii=True).replace("<", r"\u003c")
    return f'''<!doctype html><html><body><template>
<style>#root {{ position:absolute; inset:0; background: {brief["look"]["palette"]["ground"]};
font-family: '{brief["look"]["fonts"]["text"]}', sans-serif; font-weight: 600; }}</style>
<div id="root" data-composition-id="{comp}" data-width="{canvas["width"]}" data-height="{canvas["height"]}" data-variant="{visual["variant"]}">
<script type="application/json" id="{comp}-clock">{{"seconds":0,"lines":{{}},"cues":{{}}}}</script>
<script type="application/json" data-episode-theme>{theme}</script>
<svg id="{comp}-art" width="{canvas["width"]}" height="{canvas["height"]}" viewBox="0 0 {canvas["width"]} {canvas["height"]}"></svg></div>
<script>(() => {{
const comp={json.dumps(comp)}, brief={payload};
const clock=JSON.parse(document.getElementById(comp+"-clock").textContent);
const tl=gsap.timeline({{paused:true}});
window.__timelines["{comp}"] = tl;

{_scene_script(_ADAPTERS.get(visual["component"], "blocks"))}
if (!n && brief.subject) label(brief.subject, left + w / 2, top + h / 2, w, size, stage, "middle");
}})();</script></template></body></html>'''
