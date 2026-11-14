"""Where the person and the picture sit in each layout, in pixels of the 1920 by 1080 frame.

One table serves the studio's stage, the brief a picture is built from and the film itself, so
what a person picks is what gets rendered. A picture is built on the canvas of the layout it
first appears in; where a later line puts it in another layout it is fitted into that layout's
box whole, never cropped or stretched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FRAME_W, FRAME_H = 1920, 1080
Box = tuple[int, int, int, int]
Row = dict[str, Any]


@dataclass(frozen=True)
class Region:
    #: The person's window: left, top, width, height. None when nobody is on screen.
    person: Box | None = None
    #: The picture's box. None when the person has the frame alone.
    picture: Box | None = None
    person_radius: int = 0
    picture_radius: int = 0
    #: The picture is a translucent card laid over the person.
    glass: bool = False
    #: How far the camera is punched in on the person.
    zoom: float = 1.0


FULL: Box = (0, 0, FRAME_W, FRAME_H)
REGIONS: dict[str, Region] = {
    "full-frame": Region(person=FULL),
    "full-frame-close": Region(person=FULL, zoom=1.18),
    "framed-on-ground": Region(person=(154, 97, 1612, 886), person_radius=28),
    "glass-card": Region(person=FULL, picture=(96, 140, 768, 800), picture_radius=24, glass=True),
    "split": Region(person=(960, 0, 960, 1080), picture=(48, 60, 864, 960), picture_radius=20),
    "panel-and-portrait": Region(
        person=(1440, 162, 422, 756),
        picture=(58, 162, 1344, 756),
        person_radius=20,
        picture_radius=20,
    ),
    "corner-window": Region(person=(1478, 676, 384, 346), picture=FULL, person_radius=18),
    "avatar-bubble": Region(
        person=(77, 733, 270, 270),
        picture=(422, 86, 1421, 907),
        person_radius=999,
        picture_radius=20,
    ),
    "graphic-on-ground": Region(picture=FULL),
    "card-on-ground": Region(picture=(346, 151, 1228, 778), picture_radius=24),
    "recording-fills": Region(picture=FULL),
    "title-card": Region(picture=FULL),
}
#: The layout a picture is built for when its own is unknown.
FALLBACK = "graphic-on-ground"


def region(layout: str | None) -> Region:
    return REGIONS.get(layout or "", REGIONS[FALLBACK])


def canvas(layout: str | None) -> tuple[int, int]:
    """The size a picture is built at for this layout: the layout's picture box."""
    box = region(layout).picture or FULL
    return box[2], box[3]


def fit(size: tuple[int, int], box: Box) -> tuple[float, float, float]:
    """Where a canvas of `size` goes to sit whole and centred in `box`: x, y and scale."""
    width, height = size
    scale = min(box[2] / width, box[3] / height)
    return (
        round(box[0] + (box[2] - width * scale) / 2, 2),
        round(box[1] + (box[3] - height * scale) / 2, 2),
        round(scale, 5),
    )


def keep_clear(layout: str | None) -> Box | None:
    """The part of the picture's own canvas the person's window covers, with a margin: where a
    picture must put nothing that has to be read. None when the two do not overlap."""
    spot = region(layout)
    if spot.person is None or spot.picture is None or spot.glass:
        return None
    px, py, pw, ph = spot.person
    cx, cy, cw, ch = spot.picture
    left, top = max(px, cx), max(py, cy)
    right, bottom = min(px + pw, cx + cw), min(py + ph, cy + ch)
    if right <= left or bottom <= top:
        return None
    margin = 40
    x, y = max(0, left - cx - margin), max(0, top - cy - margin)
    return (
        x,
        y,
        min(cw, right - cx + margin) - x,
        min(ch, bottom - cy + margin) - y,
    )


def view() -> Row:
    """The table as the studio draws it."""
    return {
        "frame": [FRAME_W, FRAME_H],
        "layouts": {
            name: {
                "person": list(spot.person) if spot.person else None,
                "picture": list(spot.picture) if spot.picture else None,
                "person_radius": spot.person_radius,
                "picture_radius": spot.picture_radius,
                "glass": spot.glass,
                "zoom": spot.zoom,
            }
            for name, spot in REGIONS.items()
        },
    }
