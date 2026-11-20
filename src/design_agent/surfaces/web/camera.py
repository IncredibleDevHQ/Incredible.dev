"""A camera's memory card, put into this computer: the clips on it, read where they are.

A camera writes its clips in a layout of its own: Sony's under `PRIVATE/M4ROOT/CLIP` (with an
XML file of what it knew beside each one), most others' under `DCIM`. A card shows up as a
folder (`/Volumes/<card>` on macOS, under `/media` on Linux). Each clip is listed with its
length and when it was recorded, read from the file itself (the movie header every MP4 and MOV
has), and from Sony's XML when there is one, since that says the time zone as well.

Nothing here is ever written to a card, and only a clip the listing names can be brought in:
a path a request names is looked up in a fresh listing, never opened as given.
"""

from __future__ import annotations

import contextlib
import re
import struct
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import IO, Any

#: Where cameras keep their clips on a card, from its top.
LAYOUTS = (("PRIVATE", "M4ROOT", "CLIP"), ("DCIM",))
#: A clip's file ending, as cameras write them.
ENDINGS = frozenset({".mp4", ".mov", ".mxf"})
#: The most clips listed from all cards together, newest first.
MOST = 400
#: Seconds from the movie header's epoch (1904) to the Unix one (1970).
EPOCH_1904 = 2_082_844_800
#: How much of a clip's XML is read: Sony's is a few kilobytes.
XML_BYTES = 64 * 1024


@dataclass(frozen=True)
class Clip:
    path: str
    name: str
    card: str
    size: int
    seconds: float
    #: When the camera began recording it (seconds since 1970), or 0 when no one says.
    recorded_at: float
    #: The camera's own word for its picture, when its XML has one (`s-cinetone`, `s-log3-cine`).
    look: str = ""
    #: The frame rate the camera recorded at, when its XML says (`29.97`).
    fps: str = ""

    def view(self) -> dict[str, Any]:
        return asdict(self)


def clips(roots: Sequence[Path]) -> list[Clip]:
    """Every clip on the cards under `roots`, newest first."""
    found: dict[str, Clip] = {}
    for card, folder in _folders(roots):
        for path in _files(folder):
            with contextlib.suppress(OSError):
                clip = _clip(path, card)
                found.setdefault(clip.path, clip)
    return sorted(found.values(), key=lambda c: (c.recorded_at, c.name), reverse=True)[:MOST]


def find(roots: Sequence[Path], path: str) -> Clip | None:
    """The clip at `path`, only when a listing of the cards names it."""
    try:
        wanted = str(Path(path).resolve(strict=True))
    except (OSError, RuntimeError):
        return None
    return next((c for c in clips(roots) if c.path == wanted), None)


def _folders(roots: Sequence[Path]) -> Iterator[tuple[str, Path]]:
    """Each camera folder on a card under the roots: a root that is a card itself, or the
    cards in it (a computer's mount point)."""
    for root in roots:
        with contextlib.suppress(OSError):
            places = [root, *(p for p in sorted(root.iterdir()) if p.is_dir())]
            for place in places:
                for layout in LAYOUTS:
                    folder = place.joinpath(*layout)
                    with contextlib.suppress(OSError):
                        if folder.is_dir():
                            yield place.name or str(place), folder


def _files(folder: Path) -> Iterator[Path]:
    """The clips in a camera folder: in it, and one folder down (DCIM's `100CANON`)."""
    with contextlib.suppress(OSError):
        for entry in sorted(folder.iterdir()):
            # a dot file is the computer's own (macOS writes `._C0001.MP4` beside each clip),
            # and a camera writes no links: one would point off the card
            if entry.name.startswith(".") or entry.is_symlink():
                continue
            if entry.is_dir():
                with contextlib.suppress(OSError):
                    yield from (p for p in sorted(entry.iterdir()) if _a_clip(p))
            elif _a_clip(entry):
                yield entry


def _a_clip(path: Path) -> bool:
    return (
        not path.name.startswith(".")
        and path.suffix.lower() in ENDINGS
        and not path.is_symlink()
        and path.is_file()
    )


def _clip(path: Path, card: str) -> Clip:
    resolved = path.resolve(strict=True)
    stat = resolved.stat()
    with resolved.open("rb") as f:
        seconds, made = movie_header(f, stat.st_size)
    xml = _sony_xml(resolved)
    when = _xml_time(xml) or made
    if not when and seconds:
        # a file's time is when the camera last wrote it: the end of the clip
        when = stat.st_mtime - seconds
    look = re.search(r'name="CaptureGammaEquation"\s+value="([^"]{1,40})"', xml)
    fps = re.search(r'captureFps="([0-9.]{1,8})', xml)
    return Clip(
        path=str(resolved),
        name=path.name,
        card=card,
        size=stat.st_size,
        seconds=round(seconds, 3),
        recorded_at=round(when, 3),
        look=look[1].lower() if look else "",
        fps=fps[1] if fps else "",
    )


def movie_header(f: IO[bytes], size: int) -> tuple[float, float]:
    """A movie's length (seconds) and when it was made (seconds since 1970, 0 when unset), from
    the `mvhd` box in its `moov`. Both 0 when the file has none it can say."""
    for kind, start, end in _boxes(f, 0, size):
        if kind != b"moov":
            continue
        for inner, at, _ in _boxes(f, start, end):
            if inner != b"mvhd":
                continue
            f.seek(at)
            version = f.read(4)[:1]
            if version == b"\x01":
                made, _, scale, length = struct.unpack(">QQIQ", f.read(28))
            else:
                made, _, scale, length = struct.unpack(">IIII", f.read(16))
            seconds = length / scale if scale else 0.0
            return seconds, (made - EPOCH_1904 if made > EPOCH_1904 else 0.0)
    return 0.0, 0.0


def _boxes(f: IO[bytes], start: int, end: int) -> Iterator[tuple[bytes, int, int]]:
    """The boxes between two places in an MP4: each one's kind and where its content runs."""
    at, seen = start, 0
    while at + 8 <= end and seen < 256:
        seen += 1
        f.seek(at)
        head = f.read(8)
        if len(head) < 8:
            return
        length, kind = struct.unpack(">I4s", head)
        header = 8
        if length == 1:
            wide = f.read(8)
            if len(wide) < 8:
                return
            length, header = struct.unpack(">Q", wide)[0], 16
        elif length == 0:
            length = end - at
        if length < header or at + length > end:
            return
        yield kind, at + header, at + length
        at += length


def _sony_xml(clip: Path) -> str:
    """What a Sony camera wrote of the clip (`C0001M01.XML` beside `C0001.MP4`), or nothing."""
    for sidecar in (clip.with_name(f"{clip.stem}M01.XML"), clip.with_name(f"{clip.stem}M01.xml")):
        with contextlib.suppress(OSError):
            if sidecar.is_file():
                with sidecar.open("rb") as f:
                    return f.read(XML_BYTES).decode("utf-8", "replace")
    return ""


def _xml_time(xml: str) -> float:
    found = re.search(r'<CreationDate\s+value="([^"]{10,40})"', xml)
    if not found:
        return 0.0
    try:
        moment = datetime.fromisoformat(found[1])
    except ValueError:
        return 0.0
    # a time with no zone is the computer's own, as the camera's clock was set
    return moment.timestamp()
