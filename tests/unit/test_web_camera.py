"""A camera's card on this computer: its clips listed where they are, and only those."""

from __future__ import annotations

import os
import struct
from datetime import UTC, datetime
from pathlib import Path

from design_agent.surfaces.web import camera

EPOCH_1904 = 2_082_844_800


def box(kind: bytes, content: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(content), kind) + content


def movie(seconds: float, made: float, *, wide: bool = False, big_mdat: bool = False) -> bytes:
    """An MP4 as a camera writes one: its type, the picture (here a few bytes), and the movie
    header after it, in the 64-bit form when `wide`."""
    scale = 30000
    if wide:
        header = struct.pack(">B3xQQIQ", 1, int(made) + EPOCH_1904, 0, scale, int(seconds * scale))
    else:
        header = struct.pack(">B3xIIII", 0, int(made) + EPOCH_1904, 0, scale, int(seconds * scale))
    picture = b"\x00" * 64
    if big_mdat:
        mdat = struct.pack(">I4sQ", 1, b"mdat", 16 + len(picture)) + picture
    else:
        mdat = box(b"mdat", picture)
    return (
        box(b"ftyp", b"XAVC\x00\x00\x00\x00")
        + mdat
        + box(b"moov", box(b"mvhd", header + b"\x00" * 80))
    )


def test_a_sony_card_and_another_cameras_clips_are_listed_newest_first(tmp_path: Path) -> None:
    mounts = tmp_path / "Volumes"
    clips = mounts / "UNTITLED" / "PRIVATE" / "M4ROOT" / "CLIP"
    clips.mkdir(parents=True)
    made = datetime(2026, 11, 20, 9, 30, tzinfo=UTC).timestamp()
    (clips / "C0001.MP4").write_bytes(movie(612.5, made, big_mdat=True))
    (clips / "C0001M01.XML").write_text(
        '<?xml version="1.0"?><NonRealTimeMeta><CreationDate value="2026-11-20T15:02:11+05:30"/>'
        '<VideoFormat><VideoFrame videoCodec="AVC_3840_2160_HP@L51" captureFps="29.97p"/>'
        '</VideoFormat><AcquisitionRecord><Group name="CameraUnitMetadataSet">'
        '<Item name="CaptureGammaEquation" value="S-Cinetone"/></Group></AcquisitionRecord>'
        "</NonRealTimeMeta>"
    )
    # what macOS writes beside each clip on a card, and a link a camera never writes
    (clips / "._C0001.MP4").write_bytes(b"\x00\x05\x16\x07")
    secret = tmp_path / "secret.mp4"
    secret.write_bytes(movie(5, made))
    os.symlink(secret, clips / "C0009.MP4")
    other = mounts / "EOS_DIGITAL" / "DCIM" / "100CANON"
    other.mkdir(parents=True)
    (other / "MVI_0001.MOV").write_bytes(movie(30.0, made + 3600, wide=True))
    (other / "IMG_0002.JPG").write_bytes(b"\xff\xd8")
    (mounts / "Macintosh HD").mkdir()

    found = camera.clips([mounts])
    assert [c.name for c in found] == ["MVI_0001.MOV", "C0001.MP4"]
    canon, sony = found
    assert canon.card == "EOS_DIGITAL" and canon.seconds == 30.0
    assert canon.recorded_at == made + 3600 and canon.look == "" and canon.fps == ""
    assert sony.card == "UNTITLED" and sony.seconds == 612.5
    # Sony's own file says the time zone, so its time wins over the movie header's
    assert sony.recorded_at == datetime(2026, 11, 20, 9, 32, 11, tzinfo=UTC).timestamp()
    assert sony.look == "s-cinetone" and sony.fps == "29.97"
    assert sony.size == (clips / "C0001.MP4").stat().st_size
    assert sony.view()["path"] == str((clips / "C0001.MP4").resolve())

    # only a clip the listing names is ever brought in
    assert camera.find([mounts], str(clips / "C0001.MP4")) == sony
    for elsewhere in (secret, clips / "C0009.MP4", clips / "C0001M01.XML", tmp_path / "gone.MP4"):
        assert camera.find([mounts], str(elsewhere)) is None
    # a card can be the folder named itself
    assert [c.name for c in camera.clips([mounts / "UNTITLED"])] == ["C0001.MP4"]
    assert camera.clips([tmp_path / "nowhere"]) == []


def test_a_clip_with_no_movie_header_is_listed_by_its_files_time(tmp_path: Path) -> None:
    clips = tmp_path / "CARD" / "PRIVATE" / "M4ROOT" / "CLIP"
    clips.mkdir(parents=True)
    cut_short = clips / "C0003.MP4"
    cut_short.write_bytes(box(b"ftyp", b"XAVC") + struct.pack(">I4s", 4096, b"mdat"))
    found = camera.clips([tmp_path])
    assert [(c.name, c.seconds, c.recorded_at) for c in found] == [("C0003.MP4", 0.0, 0.0)]
    with cut_short.open("rb") as f:
        assert camera.movie_header(f, cut_short.stat().st_size) == (0.0, 0.0)
