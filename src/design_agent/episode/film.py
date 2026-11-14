"""The film as one HyperFrames project, written by code from what a person approved.

Nothing here is a model's: the page places each line's person and picture where its layout
says (`geometry`), cuts between layouts where the plan cuts, plays each take from where its
line was said, and mounts every built picture as a sub-composition whose clock was set from
the takes (`timeline`, `picture`). Layout changes are cuts, set at an instant, so the render
never tweens a box.
"""

from __future__ import annotations

import html as html_lib
import json
from typing import Any

from design_agent.episode import geometry, picture
from design_agent.episode import questions as Q
from design_agent.episode.timeline import line_of

Row = dict[str, Any]

CHAPTERS = Q.table("chapter_types")
#: A person's box when no take has been recorded for the line yet: the draft shows a stand-in.
STAND_IN = "stand-in"
FADE = 0.4


def project(
    full: Row,
    clock: Row,
    units: list[Row],
    pictures: dict[str, str],
    *,
    takes: dict[str, Row] | None = None,
    voice: dict[str, str] | None = None,
    look: picture.Look | None = None,
) -> dict[str, str]:
    """The project's text files by path: `index.html` and each picture with its clock set.

    `pictures` is the built file by unit id. `takes` is `{take id: {"video": path or "",
    "audio": path}}` and `voice` is `{frame id: path}`, both as paths inside the project.
    """
    look = look or picture.Look()
    colours = {**picture.PALETTE, **look.palette}
    takes = takes or {}
    voice = voice or {}
    frames = {
        f["id"]: f
        for ch in full.get("chapters", [])
        for b in ch.get("beats", [])
        for f in b.get("frames", [])
    }
    files: dict[str, str] = {}
    body: list[str] = []
    script: list[str] = []
    track = 1

    built = [u for u in units if u["id"] in pictures]
    for unit in built:
        comp = picture.composition_id(unit["id"])
        own = picture.clock(unit, clock)
        if not own["lines"]:
            continue
        files[f"{picture.FOLDER}/{comp}.html"] = picture.dressed(pictures[unit["id"]], own, look)
        first = line_of(clock, unit["frames"][0])
        assert first is not None  # noqa: S101 - the unit's lines are in the clock (checked above)
        width, height = unit["canvas"]
        home = geometry.region(unit.get("layout"))
        radius = home.picture_radius
        style = f"width: {width}px; height: {height}px; border-radius: {radius}px"
        if home.glass:
            style += "; z-index: 3; opacity: 0.94"
        body.append(
            f'<div class="pic" id="wrap-{comp}" style="{style}">'
            f'<div id="{comp}" data-composition-id="{comp}" '
            f'data-composition-src="{picture.FOLDER}/{comp}.html" '
            f'data-start="{first["start"]:.3f}" '
            f'data-duration="{own["seconds"]:.3f}" data-track-index="{track}" '
            f'data-width="{width}" data-height="{height}"></div></div>'
        )
        track += 1
        last: tuple[float, float, float, int] | None = None
        for frame_id in unit["frames"]:
            line = line_of(clock, frame_id)
            f = frames[frame_id]
            if line is None:
                continue
            spot = geometry.region(f.get("layout"))
            shown = f.get("presence") in ("both", "content") and spot.picture is not None
            x, y, scale = geometry.fit((width, height), spot.picture or geometry.FULL)
            now = (x, y, scale, 1 if shown else 0)
            if now != last:
                script.append(
                    f'tl.set("#wrap-{comp}", {{ x: {x}, y: {y}, scale: {scale}, '
                    f"opacity: {now[3]} }}, {line['start']:.3f});"
                )
                last = now

    # the person: one clip for each run of lines said in one take inside one window
    runs: list[Row] = []
    for line in clock["lines"]:
        f = frames[line["frame"]]
        spot = geometry.region(f.get("layout"))
        source = line["source"]
        on_screen = f.get("presence") in ("person", "both") and spot.person is not None
        take_id = source.get("take") if source["kind"] == "take" else None
        key = (take_id, f.get("layout") if on_screen else None)
        end = line["start"] + line["seconds"]
        previous = runs[-1] if runs else None
        if (
            previous is not None
            and previous["key"] == key
            and take_id is not None
            and abs(previous["media_end"] - float(source.get("offset", 0.0))) < 0.05
        ) or (previous is not None and previous["key"] == key and take_id is None):
            previous["end"] = end
            previous["media_end"] = float(source.get("offset", 0.0)) + line["seconds"]
            continue
        runs.append(
            {
                "key": key,
                "take": take_id,
                "layout": f.get("layout"),
                "on_screen": on_screen,
                "start": line["start"],
                "end": end,
                "offset": float(source.get("offset", 0.0)),
                "media_end": float(source.get("offset", 0.0)) + line["seconds"],
            }
        )
    for i, run in enumerate(runs):
        seconds = run["end"] - run["start"]
        take = takes.get(str(run["take"])) if run["take"] else None
        if run["on_screen"]:
            spot = geometry.region(run["layout"])
            assert spot.person is not None  # noqa: S101 - on_screen means the layout has a window
            left, top, width, height = spot.person
            box = (
                f"left: {left}px; top: {top}px; width: {width}px; height: {height}px; "
                f"border-radius: {spot.person_radius}px"
            )
            if take is not None and take.get("video"):
                body.append(
                    f'<div class="person" style="{box}"><video id="person-{i}" '
                    f'src="{_attr(take["video"])}" muted playsinline data-start="{run["start"]:.3f}" '
                    f'data-duration="{seconds:.3f}" data-media-start="{run["offset"]:.3f}" '
                    f'data-track-index="{track}" style="transform: scale({spot.zoom})"></video></div>'
                )
            else:
                body.append(
                    f'<div class="person {STAND_IN} clip" id="person-{i}" style="{box}" '
                    f'data-start="{run["start"]:.3f}" data-duration="{seconds:.3f}" '
                    f'data-track-index="{track}"><i></i><b></b></div>'
                )
        if take is not None and take.get("audio"):
            body.append(
                f'<audio id="said-{i}" src="{_attr(take["audio"])}" data-start="{run["start"]:.3f}" '
                f'data-duration="{seconds:.3f}" data-media-start="{run["offset"]:.3f}" '
                f'data-track-index="{track + 1}" data-volume="1"></audio>'
            )
    track += 2
    for n, line in enumerate(clock["lines"]):
        if line["source"]["kind"] == "voice" and line["frame"] in voice:
            body.append(
                f'<audio id="voice-{n}" src="{_attr(voice[line["frame"]])}" '
                f'data-start="{line["start"]:.3f}" data-duration="{line["seconds"]:.3f}" '
                f'data-track-index="{track}" data-volume="1"></audio>'
            )
    track += 1

    title = str(full.get("title") or full.get("brief", {}).get("idea") or "")
    idea = str(full.get("brief", {}).get("idea") or "")
    for mark in clock["marks"]:
        start, seconds = float(mark["start"]), float(mark["seconds"])
        if mark["mark"] == "title-sting":
            body.append(
                f'<section class="card clip" id="sting" data-start="{start:.3f}" '
                f'data-duration="{seconds:.3f}" data-track-index="{track}">'
                f'<h1 id="sting-title">{_text(title)}</h1></section>'
            )
            script.append(
                f'tl.fromTo("#sting-title", {{ opacity: 0, y: 36 }}, '
                f'{{ opacity: 1, y: 0, duration: 0.6, ease: "power3.out" }}, {start + 0.2:.3f});'
            )
        elif mark["mark"] == "chapter-card":
            chapter = next(c for c in full["chapters"] if c["id"] == mark["chapter"])
            number = full["chapters"].index(chapter) + 1
            name = CHAPTERS.get(str(chapter.get("type")), {}).get("name", "")
            body.append(
                f'<div class="chapter clip" id="card-{number}" data-start="{start:.3f}" '
                f'data-duration="{seconds:.3f}" data-track-index="{track}">'
                f'<span id="card-{number}-text">{number} · {_text(str(name))}</span></div>'
            )
            script.append(
                f'tl.fromTo("#card-{number}-text", {{ opacity: 0, y: -14 }}, '
                f'{{ opacity: 1, y: 0, duration: 0.35, ease: "power2.out" }}, {start + 0.05:.3f});'
            )
        elif mark["mark"] == "end-card":
            body.append(
                f'<section class="card clip" id="end" data-start="{start:.3f}" '
                f'data-duration="{seconds:.3f}" data-track-index="{track}">'
                f'<h1 id="end-title">{_text(title)}</h1><p id="end-idea">{_text(idea)}</p></section>'
            )
            script.append(
                f'tl.fromTo("#end-title", {{ opacity: 0, y: 28 }}, '
                f'{{ opacity: 1, y: 0, duration: 0.6, ease: "power3.out" }}, {start + 0.15:.3f});'
            )
            script.append(
                f'tl.fromTo("#end-idea", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.6 }}, '
                f"{start + 0.6:.3f});"
            )

    files["index.html"] = _page(colours, look, clock["total"], body, script)
    return files


def _page(
    colours: dict[str, str], look: picture.Look, total: float, body: list[str], script: list[str]
) -> str:
    ground, ink, muted = colours["ground"], colours["ink"], colours["muted"]
    accent, on_accent, line = colours["accent"], colours["accent_ink"], colours["line"]
    markup = "\n      ".join(body)
    moves = "\n      ".join(script)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={geometry.FRAME_W}, height={geometry.FRAME_H}" />
    <script src="gsap.min.js"></script>
    <style>
      {look.faces()}
      html, body {{ margin: 0; width: {geometry.FRAME_W}px; height: {geometry.FRAME_H}px; overflow: hidden; background: {ground}; }}
      #root {{ position: relative; width: 100%; height: 100%; overflow: hidden; background: {ground}; color: {ink}; font-family: '{look.text}', sans-serif; }}
      .pic {{ position: absolute; left: 0; top: 0; transform-origin: 0 0; overflow: hidden; z-index: 1; }}
      .pic > div {{ position: absolute; inset: 0; }}
      .person {{ position: absolute; overflow: hidden; z-index: 2; }}
      .person video {{ display: block; width: 100%; height: 100%; object-fit: cover; }}
      .{STAND_IN} {{ background: {line}; }}
      .{STAND_IN} i {{ position: absolute; left: 50%; top: 24%; width: 26%; aspect-ratio: 1; margin-left: -13%; border-radius: 999px; background: {muted}; opacity: 0.55; }}
      .{STAND_IN} b {{ position: absolute; left: 50%; bottom: -8%; width: 62%; height: 46%; margin-left: -31%; border-radius: 999px 999px 0 0; background: {muted}; opacity: 0.55; }}
      .card {{ position: absolute; inset: 0; z-index: 5; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 28px; padding: 0 220px; box-sizing: border-box; background: {ground}; text-align: center; }}
      .card h1 {{ margin: 0; font-family: '{look.display}', serif; font-weight: 600; font-size: 92px; line-height: 1.08; letter-spacing: -0.02em; text-wrap: balance; }}
      .card p {{ margin: 0; font-size: 38px; line-height: 1.35; color: {muted}; text-wrap: balance; }}
      .chapter {{ position: absolute; left: 64px; top: 56px; z-index: 4; }}
      .chapter span {{ display: block; padding: 14px 26px; border-radius: 999px; background: {accent}; color: {on_accent}; font-size: 30px; font-weight: 600; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{total:.3f}" data-width="{geometry.FRAME_W}" data-height="{geometry.FRAME_H}">
      {markup}
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      {moves}
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""


def _text(value: str) -> str:
    return html_lib.escape(value, quote=False)


def _attr(value: str) -> str:
    return html_lib.escape(value, quote=True)


def summary(clock: Row) -> str:
    """One line a log or a person can read: how long, and what each line plays from."""
    kinds: dict[str, int] = {}
    for line in clock["lines"]:
        kinds[line["source"]["kind"]] = kinds.get(line["source"]["kind"], 0) + 1
    return json.dumps({"seconds": clock["total"], "lines": kinds}, separators=(",", ":"))
