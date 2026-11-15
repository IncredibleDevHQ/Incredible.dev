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
from design_agent.episode.plan import digest, picture_of

Row = dict[str, Any]

SIMPLE, RICH = "simple", "rich"
LEVELS = (SIMPLE, RICH)
#: A picture this long, changing this often, is worth posing as stills before it is animated.
RICH_LINES, RICH_CUES = 3, 6
#: How a type a person picked is laid out, when the plan's arrangement was read for another.
ARRANGED = {
    "list": "stack",
    "chips": "row",
    "typeset-code": "code-panel",
    "slide": "stack",
    "illustration": "single",
}


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
        unit["picture"] = picture_of(first)
        unit["arrangement"] = first.get("arrangement") or ""
        # a type the person picked over the plan's: the builder draws the same content as it
        retyped = bool(unit["picture"]) and unit["picture"] != (first.get("picture") or "")
        if retyped:
            unit["picture_by"] = "person"
            unit["arrangement"] = ARRANGED.get(unit["picture"], unit["arrangement"])
        unit["shows"] = first.get("shows") or ""
        unit["start"] = first.get("start", 0.0)
        unit["seconds"] = round(sum(float(f.get("seconds", 0.0)) for f in frames), 1)
        unit["suggest"] = RICH if len(frames) >= RICH_LINES and cues >= RICH_CUES else SIMPLE
        picked = (chosen.get(unit["id"]) or {}).get("level")
        unit["level"] = picked if picked in LEVELS else level
        built_from: Row = {"theme": theme, "canvas": unit["canvas"], "layout": unit["layout"]}
        if retyped:  # only a pick is part of it, so a picture made before picks existed stands
            built_from["picture"] = unit["picture"]
        # What a picture is drawn from holds no spoken word: the words, and the word each step
        # lands on, only move its clock. So a line said another way keeps its picture, whoever
        # reworded it. `sig_was` is the signature pictures were kept under before that was so
        # (it counted the words); one made then still stands while its words do.
        unit["sig"] = digest(
            json.dumps(
                {**built_from, "frames": [_drawn_from(f) for f in frames]},
                sort_keys=True,
                ensure_ascii=False,
            )
        )
        unit["sig_was"] = digest(
            json.dumps(
                {**built_from, "frames": [_built_from(f) for f in frames]},
                sort_keys=True,
                ensure_ascii=False,
            )
        )
    return out


def same(sig: str, unit: Row) -> bool:
    """Whether a picture kept under `sig` was drawn from the unit as it stands."""
    return bool(sig) and sig in (unit["sig"], unit["sig_was"])


def _drawn_from(f: Row) -> Row:
    """What of a frame a picture is drawn from: what it shows, its objects, and what each step
    does. Not its words, and not the word a step lands on."""
    return {
        "id": f["id"],
        "shows": f.get("shows", ""),
        "focal": f.get("focal", ""),
        "objects": [
            {k: o.get(k) for k in ("id", "what", "words", "state", "type")}
            for o in f.get("objects", [])
        ],
        "cues": [{k: c.get(k) for k in ("object", "does", "move")} for c in f.get("cues", [])],
    }


def _unit(ch: Row, f: Row, kind: str) -> Row:
    return {"id": f["id"], "chapter": ch["id"], "kind": kind, "frames": [f]}


def _built_from(f: Row) -> Row:
    """What a picture was kept under before its words were left out (`sig_was`): the frame
    with its words. A person's words for the line never counted, so a picture made then
    stands when a person rewords its line."""
    was = f.get("by_person") or {}
    cues = [{k: c.get(k) for k in ("at", "object", "does", "move")} for c in f.get("cues", [])]
    landed = was.get("cues") or []
    if len(landed) == len(cues):
        for cue, at in zip(cues, landed, strict=True):
            cue["at"] = at
    return {
        "id": f["id"],
        "vo": was.get("was") or f.get("vo", ""),
        "shows": f.get("shows", ""),
        "focal": f.get("focal", ""),
        "objects": [
            {k: o.get(k) for k in ("id", "what", "words", "state", "type")}
            for o in f.get("objects", [])
        ],
        "cues": cues,
    }


def by_frame(found: list[Row]) -> dict[str, Row]:
    """Each frame's unit."""
    return {frame: unit for unit in found for frame in unit["frames"]}
