"""The local illustration vocabulary shared by the writer and the SVG.js renderer."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ASSETS = {
    "phone": "A handheld phone with a map pin",
    "satellite": "A satellite with solar panels",
    "cloud": "A cloud or remote service",
    "pin": "A location pin",
    "browser": "A browser window",
    "server": "A server rack",
    "storage": "A database or cache",
    "document": "A document or file",
    "person": "A person",
    "shop": "A shop",
    "bank": "A bank",
    "hand": "A hand with an extended finger",
    "metal-spoon": "A reflective metal spoon",
    "wooden-spoon": "A wooden spoon with visible grain",
    "thermometer": "A bulb thermometer with a marked scale",
    "cup": "A cup or mug with a handle",
    "object": "A neutral object with its own label",
}
CAMERAS = ("overview", "focus", "reset")
PHYSICAL = {
    "hand": r"\b(?:warm(?:er)? |human |open )?hand\b",
    "metal-spoon": r"\b(?:metal|steel|silver)(?:\s+[a-z-]+){0,2}\s+spoons?\b",
    "wooden-spoon": r"\bwood(?:en)?(?:\s+[a-z-]+){0,2}\s+spoons?\b",
    "thermometer": r"\bthermometers?\b",
    "cup": r"\b(?:cups?|mugs?)\b",
}
DETAIL = re.compile(
    r"[,;]|\b(?:with|beside|holding|held|touching|next to|under|above|on|inside|into|in)\b", re.I
)


def asset_for(obj: dict[str, Any]) -> str:
    selected = obj.get("asset")
    if isinstance(selected, str) and selected in ASSETS and selected != "object":
        return selected
    if obj.get("type") in ("connector", "cross") or obj.get("from") or obj.get("to"):
        return "object"
    # An object's leading name outranks the props it interacts with.
    names = [DETAIL.split(str(obj.get(key, "")), maxsplit=1)[0] for key in ("what", "words")]
    for text in names:
        matches = [
            (match.start(), -len(match[0]), asset)
            for asset, pattern in PHYSICAL.items()
            if (match := re.search(pattern, text, re.I))
        ]
        if matches:
            return min(matches)[2]
    text = " ".join(names)
    for pattern, asset in (
        (r"phone|handset|receiver", "phone"),
        (r"satellite|solar panel", "satellite"),
        (r"cloud", "cloud"),
        (r"location|map pin|blue dot", "pin"),
        (r"browser|web page", "browser"),
        (r"server|origin", "server"),
        (r"database|cache|storage", "storage"),
        (r"file|document|payload", "document"),
        (r"person|user|customer|speaker", "person"),
        (r"shop|store|merchant", "shop"),
        (r"bank|issuer", "bank"),
    ):
        if re.search(pattern, text, re.I):
            return asset
    return "object"


def custom_objects(objects: list[dict[str, Any]]) -> list[str]:
    """Object identities that need a bespoke drawing rather than a stock symbol."""
    return list(
        dict.fromkeys(
            str(obj["id"])
            for obj in objects
            if obj.get("id") and obj.get("type") == "illustration" and asset_for(obj) == "object"
        )
    )


def has_subjects(objects: list[dict[str, Any]]) -> bool:
    return any(obj.get("type") == "illustration" or asset_for(obj) in PHYSICAL for obj in objects)


def direction(frame: dict[str, Any]) -> dict[str, Any]:
    """Keep creative shot intent bounded to known modes and object identities."""
    camera = frame.get("camera")
    visible = frame.get("visible")
    return {
        "camera": camera if camera in CAMERAS else "overview",
        "visible": list(dict.fromkeys(x for x in visible if isinstance(x, str)))[:24]
        if isinstance(visible, list)
        else [],
    }


FILENAME = "svg.min.js"
SCRIPT = '<script src="svg.min.js"></script>'


@lru_cache(maxsize=1)
def library() -> str:
    """The pinned MIT browser bundle, loaded by the local render page."""
    return (Path(__file__).with_name("vendor") / FILENAME).read_text(encoding="utf8")
