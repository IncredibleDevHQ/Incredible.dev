"""The picture vocabulary shared by classification, the studio and both picture builders."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from design_agent.episode import connections

Row = dict[str, Any]
CATALOG_VERSION = 2
# Drawing revisions are independent of the classifier's choice vocabulary.
ILLUSTRATED = {
    "flowchart",
    "relationship-diagram",
    "sequence-diagram",
    "list",
    "stepper",
    "timeline",
}
DRAWING_VERSION = 3


@dataclass(frozen=True)
class Component:
    purpose: str
    layouts: tuple[str, ...]
    motion: str


COMPONENTS = {
    "illustration": Component(
        "Reusable illustrated objects composed for a spoken scene",
        ("balanced", "focused"),
        "Reveal each asset on its cue, focus the named subject and restore context at the next overview.",
    ),
    "detail-card": Component(
        "Fields or status for one subject",
        ("stacked", "split", "compact"),
        "Reveal the header, then each field or badge on its word.",
    ),
    "list": Component(
        "A collection of related items",
        ("vertical", "horizontal", "grid"),
        "Reveal items in reading order and hold previous items.",
    ),
    "comparison": Component(
        "Compare options on shared attributes",
        ("side-by-side", "table", "stacked-pairs"),
        "Show matching attributes together and highlight the difference.",
    ),
    "stepper": Component(
        "Which stage is current",
        ("horizontal", "vertical", "focused-step"),
        "Advance the active marker and complete preceding stages.",
    ),
    "timeline": Component(
        "When events happen",
        ("horizontal", "vertical", "alternating"),
        "Advance along the axis and reveal each event on its cue.",
    ),
    "sequence-diagram": Component(
        "Ordered messages between named participants",
        ("vertical-lanes", "horizontal-lanes", "focused-exchange"),
        "Draw each message from sender to receiver, retaining earlier arrows.",
    ),
    "flowchart": Component(
        "Directed steps, decisions or retries",
        ("top-down", "left-to-right", "swimlanes"),
        "Follow the edge to the destination and illuminate the selected branch.",
    ),
    "relationship-diagram": Component(
        "Connections among parts",
        ("hub", "tree", "network"),
        "Hold node positions and reveal the connection being discussed.",
    ),
    "bar-chart": Component(
        "Compare measured quantities in the same unit",
        ("vertical", "horizontal", "grouped"),
        "Extend bars from zero to their measured values.",
    ),
    "line-chart": Component(
        "A series of measurements in order",
        ("single", "overlay", "small-multiples"),
        "Trace the series and highlight the current point.",
    ),
    "code-block": Component(
        "Exact code or configuration",
        ("full-width", "side-notes", "focused-excerpt"),
        "Hold the code steady and highlight the cited line.",
    ),
    "statement": Component(
        "A single idea or figure to remember",
        ("centered", "left-aligned", "split-emphasis"),
        "Set the headline first and reveal supporting words on cue.",
    ),
    "custom": Component(
        "A drawing specific to this idea",
        ("full-canvas", "side-caption", "bottom-caption"),
        "Follow the person's direction and the shot plan.",
    ),
}


def measured(obj: Row) -> bool:
    value = obj.get("value")
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and abs(value) < 1e300
        and math.isfinite(value)
        and isinstance(obj.get("unit"), str)
        and bool(obj["unit"].strip())
    )


def available(objects: list[Row], edges: list[Row] | None = None) -> dict[str, list[str]]:
    quantities = [o for o in objects if measured(o)]
    has_series = len({str(o["series"]) for o in quantities if o.get("series")}) > 1
    options = {key: list(item.layouts) for key, item in COMPONENTS.items()}
    if len(quantities) < 2 or len({o["unit"] for o in quantities}) != 1:
        options.pop("bar-chart")
        options.pop("line-chart")
    elif not has_series:
        options["bar-chart"].remove("grouped")
        options["line-chart"] = ["single"]
    if not edges and not any(
        isinstance(o.get("from"), str) and isinstance(o.get("to"), str) and o["from"] and o["to"]
        for o in objects
    ):
        options.pop("sequence-diagram")
    if not any(o.get("parent") for o in objects):
        options["relationship-diagram"].remove("tree")
    if not any(o.get("owner") for o in objects):
        options["flowchart"].remove("swimlanes")
    return options


def select(first: Row, frames: list[Row], pick: Row, kind: str, width: int) -> Row:
    objects = [o for frame in frames for o in frame.get("objects", [])]
    edges = (
        connections.resolve(frames)
        if kind in ("diagram", "illustration")
        or pick.get("component") in ("sequence-diagram", "relationship-diagram", "flowchart")
        or first.get("component") in ("sequence-diagram", "relationship-diagram", "flowchart")
        else []
    )
    options = available(objects, edges)
    suggested = first.get("component")
    if suggested not in options or first.get("picture") != kind:
        suggested = {
            "list": "list",
            "chips": "list",
            "typeset-code": "code-block",
            "slide": "detail-card",
            "illustration": "illustration",
        }.get(
            kind,
            {
                "pipeline": "flowchart",
                "tree": "relationship-diagram",
                "hub": "relationship-diagram",
                "two-sides": "comparison",
                "timeline": "timeline",
                "loop": "flowchart",
            }.get(first.get("arrangement", ""), "custom"),
        )
        if first.get("arrangement") == "timeline" and kind in ("diagram", "illustration"):
            suggested = "timeline"
        elif edges and kind in ("diagram", "illustration") and suggested != "illustration":
            if (
                any(o.get("type") == "lifeline" for o in objects)
                and sum(bool(e["label"]) for e in edges) > 1
            ):
                suggested = "sequence-diagram"
            elif suggested not in ("flowchart", "relationship-diagram"):
                suggested = "flowchart"
        elif (
            suggested in ("custom", "comparison")
            and "bar-chart" in options
            and kind in ("diagram", "illustration")
        ):
            suggested = "bar-chart"
    chosen = pick.get("component") or suggested
    if chosen not in options:
        chosen = suggested
    layouts = options[chosen]
    default = first.get("arrangement")
    if (
        chosen == "list"
        and len(objects) <= 4
        and width >= 1100
        and all(len(str(o.get("words", ""))) <= 22 for o in objects)
    ):
        default = "horizontal"
    if chosen in ("timeline", "stepper") and default not in layouts:
        events = [o for o in objects if not (o.get("from") and o.get("to"))]
        label_width = max(
            (len(str(o.get("words") or o.get("what") or "")) for o in events), default=0
        )
        default = (
            "horizontal"
            if width / max(1, len(events)) >= max(140, label_width * 12)
            else "vertical"
        )
    if chosen == "flowchart" and default not in layouts and width >= 1000:
        default = "left-to-right"
    variant = pick.get("variant") or default
    return {
        "component": chosen,
        "suggested": suggested,
        "variant_pick": pick.get("variant") if pick.get("variant") in layouts else None,
        "variant": variant if variant in layouts else layouts[0],
        "direction": pick.get("direction", ""),
        "options": options,
        "connections": edges
        if chosen in ("sequence-diagram", "relationship-diagram", "flowchart", "illustration")
        else [],
        "automatic": not pick.get("component"),
    }
