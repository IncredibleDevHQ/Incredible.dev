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
    "object": "A neutral object with its own label",
}
CAMERAS = ("overview", "focus", "reset")


def asset_for(obj: dict[str, Any]) -> str:
    selected = obj.get("asset")
    if isinstance(selected, str) and selected in ASSETS:
        return selected
    text = str(obj.get("words", "")) + " " + str(obj.get("what", ""))
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
