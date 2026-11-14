"""The built pictures of a plan: which lines each one runs under, and what it is built from.

A picture is designed once, on the first line that shows it, and grows across the lines that
hold it. That run is one unit of work for a builder and one thing a person approves. A line
that was said to camera and has been given the frame's picture side by a person has nothing
designed yet: it is a unit of its own, waiting on the writer.
"""

from __future__ import annotations

import json
from typing import Any

from design_agent.episode import geometry
from design_agent.episode.plan import digest

Row = dict[str, Any]

SIMPLE, RICH = "simple", "rich"
LEVELS = (SIMPLE, RICH)
#: A picture this long, changing this often, is worth posing as stills before it is animated.
RICH_LINES, RICH_CUES = 3, 6


def units(full: Row, picks: Row | None = None, *, level: str = SIMPLE) -> list[Row]:
    """Every built picture of a derived plan, in order. `picks` holds a person's choice of
    level per unit (`{"units": {id: {"level": ...}}}`); `level` is the film's default."""
    chosen = (picks or {}).get("units", {})
    theme = str(full.get("brief", {}).get("theme") or "")
    out: list[Row] = []
    current: Row | None = None
    for ch in full.get("chapters", []):
        for b in ch.get("beats", []):
            for f in b.get("frames", []):
                shows = bool(f.get("shows"))
                if shows and not f.get("hold"):
                    current = _unit(ch, f, "picture")
                    out.append(current)
                elif f.get("hold") and current is not None:
                    current["frames"].append(f)
                elif f.get("presence") in ("both", "content"):
                    out.append(_unit(ch, f, "undesigned"))
                    current = None
                else:
                    current = None
    for unit in out:
        frames: list[Row] = unit.pop("frames")
        first = frames[0]
        cues = sum(len(f.get("cues", [])) for f in frames)
        unit["frames"] = [f["id"] for f in frames]
        unit["canvas"] = list(geometry.canvas(first.get("layout")))
        unit["layout"] = first.get("layout")
        unit["picture"] = first.get("picture") or ""
        unit["arrangement"] = first.get("arrangement") or ""
        unit["shows"] = first.get("shows") or ""
        unit["start"] = first.get("start", 0.0)
        unit["seconds"] = round(sum(float(f.get("seconds", 0.0)) for f in frames), 1)
        unit["suggest"] = RICH if len(frames) >= RICH_LINES and cues >= RICH_CUES else SIMPLE
        picked = (chosen.get(unit["id"]) or {}).get("level")
        unit["level"] = picked if picked in LEVELS else level
        unit["sig"] = digest(
            json.dumps(
                {
                    "theme": theme,
                    "canvas": unit["canvas"],
                    "layout": unit["layout"],
                    "frames": [_built_from(f) for f in frames],
                },
                sort_keys=True,
                ensure_ascii=False,
            )
        )
    return out


def _unit(ch: Row, f: Row, kind: str) -> Row:
    return {"id": f["id"], "chapter": ch["id"], "kind": kind, "frames": [f]}


def _built_from(f: Row) -> Row:
    """What of a frame a picture is built from. Its seconds are not part of it: a take changes
    when things land, never what is drawn."""
    return {
        "id": f["id"],
        "vo": f.get("vo", ""),
        "shows": f.get("shows", ""),
        "focal": f.get("focal", ""),
        "objects": [
            {k: o.get(k) for k in ("id", "what", "words", "state", "type")}
            for o in f.get("objects", [])
        ],
        "cues": [
            {k: c.get(k) for k in ("at", "object", "does", "move")} for c in f.get("cues", [])
        ],
    }


def by_frame(found: list[Row]) -> dict[str, Row]:
    """Each frame's unit."""
    return {frame: unit for unit in found for frame in unit["frames"]}
