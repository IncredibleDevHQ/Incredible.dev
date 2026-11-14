"""A built picture: what its builder is handed, what the file must hold, and its clock.

A picture is one HyperFrames sub-composition. Its builder decides how it looks and moves; code
decides when. Every time in the file comes from a block of data (`<id>-clock`) that code
rewrites: from the plan's clock while the picture is being posed, from the take's once the
chapter is recorded. So a recording never sends a picture back to its builder.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from design_agent.episode import geometry
from design_agent.episode import questions as Q

Row = dict[str, Any]

#: The palette a picture and the film's own cards share when the channel wears no brand.
PALETTE: dict[str, str] = {
    "ground": "#F3EFE6",
    "panel": "#FFFFFF",
    "ink": "#16201B",
    "muted": "#5B665F",
    "line": "#D9D3C5",
    "accent": "#1F7A4D",
    "accent_ink": "#FFFFFF",
    "good": "#1F7A4D",
    "bad": "#B23722",
}
#: Fonts the computer that renders has, whatever the builder's own machine has.
FONTS = ("Inter", "Fraunces", "IBM Plex Mono", "Fira Code")
#: Where a picture sits in a HyperFrames project: its checks read sub-compositions from here.
FOLDER = "compositions"


@dataclass(frozen=True)
class Look:
    """What a film's pictures and its own cards wear: the brand's colours by role and its
    type, or the house's plain ones when the channel wears no brand."""

    palette: dict[str, str] = field(default_factory=lambda: dict(PALETTE))
    display: str = "Fraunces"
    text: str = "Inter"
    mono: str = "IBM Plex Mono"

    @property
    def families(self) -> tuple[str, ...]:
        """Every family a picture may name: the look's own, then what the computer has."""
        return tuple(dict.fromkeys((self.display, self.text, self.mono, *FONTS)))

    def faces(self) -> str:
        """Each family declared from the rendering computer's own fonts, which is what the
        renderer's check asks of a family it does not ship itself."""
        return " ".join(
            f"@font-face {{ font-family: '{name}'; src: local('{name}'); }}"
            for name in self.families
        )


CLOCK = re.compile(
    r'(<script[^>]*\bid="(?P<id>[A-Za-z0-9_-]+-clock)"[^>]*>)(?P<body>.*?)(</script>)', re.S
)
MOTION = Q.table("motion_styles")
THEMES = Q.table("themes")
#: What a file may not do: anything that makes two renders of one second differ, or leaves the
#: computer it renders on.
BANNED: tuple[tuple[str, str], ...] = (
    (r"\bMath\.random\s*\(", "Math.random() makes every render differ; place things by rule"),
    (r"\bDate\.now\s*\(|\bnew Date\s*\(", "the clock of the day has no place in a render"),
    (
        r"\bsetTimeout\s*\(|\bsetInterval\s*\(",
        "timers do not run under the renderer; use the timeline",
    ),
    (r"\brequestAnimationFrame\s*\(", "the renderer seeks; nothing may animate on its own"),
    (r"\bfetch\s*\(|XMLHttpRequest", "a picture reaches nothing outside its own file"),
    (
        r"""(?:src|href)\s*=\s*["']\s*(?:https?:)?//""",
        "no file from the network: the renderer has none",
    ),
    (r"""url\(\s*["']?\s*(?:https?:)?//""", "no file from the network: the renderer has none"),
    (r"@import\b", "no @import: put the styles in the file"),
    (r"<script[^>]*\bsrc\s*=", "no script files: the host page already provides `gsap`"),
    (r"<br\s*/?>", "no <br> in text: set each line as its own element"),
)


def composition_id(unit_id: str) -> str:
    return "pic-" + re.sub(r"[^a-z0-9]+", "-", unit_id.lower()).strip("-")


def frames_of(unit: Row, full: Row) -> list[Row]:
    wanted = set(unit["frames"])
    return [
        f
        for ch in full.get("chapters", [])
        for b in ch.get("beats", [])
        for f in b.get("frames", [])
        if f["id"] in wanted
    ]


def cue_keys(unit: Row, full: Row) -> list[str]:
    return [f"{f['id']}/{k}" for f in frames_of(unit, full) for k in range(len(f.get("cues", [])))]


def clock(unit: Row, film_clock: Row) -> Row:
    """The picture's own clock: seconds from its first line, for every cue and line of it."""
    lines = [line for line in film_clock["lines"] if line["frame"] in set(unit["frames"])]
    if not lines:
        return {"seconds": 0.0, "lines": {}, "cues": {}}
    start = float(lines[0]["start"])
    end = float(lines[-1]["start"]) + float(lines[-1]["seconds"])
    return {
        "seconds": round(end - start, 3),
        "lines": {
            line["frame"]: [
                round(float(line["start"]) - start, 3),
                round(float(line["start"]) + float(line["seconds"]) - start, 3),
            ]
            for line in lines
        },
        "cues": {
            key: round(max(0.0, at - start), 3)
            for key, at in film_clock["cues"].items()
            if key.split("/")[0] in set(unit["frames"])
        },
    }


def still_times(own: Row) -> dict[str, float]:
    """When each line is posed: just before it ends, with everything it added in place."""
    return {
        frame: round(max(span[0], span[1] - 0.05), 3)
        for frame, span in own.get("lines", {}).items()
    }


def with_clock(html: str, own: Row) -> str:
    """The file with its clock block replaced by `own`."""
    payload = json.dumps(own, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return CLOCK.sub(lambda m: m.group(1) + payload + m.group(4), html, count=1)


def dressed(html: str, own: Row, look: Look | None = None) -> str:
    """The file as it is rendered: its clock set, and the look's families declared inside the
    template so the renderer finds them."""
    faces = f"<style>{(look or Look()).faces()}</style>"
    timed = with_clock(html, own)
    return re.sub(r"(<template\b[^>]*>)", lambda m: m.group(1) + faces, timed, count=1)


def brief(unit: Row, full: Row, *, look: Look | None = None, note: str = "") -> Row:
    """Everything one picture is built from, as data its builder reads beside the skill's
    rules: the canvas, the look, each line with what it adds, and the cue keys."""
    look = look or Look()
    theme = THEMES.get(str(full.get("brief", {}).get("theme") or ""), THEMES["corner-window"])
    motion = MOTION.get(str(theme.get("motion") or ""), {})
    comp = composition_id(unit["id"])
    lines = []
    for f in frames_of(unit, full):
        lines.append(
            {
                "frame": f["id"],
                "said": f.get("vo", ""),
                "shows_when_finished": f.get("shows")
                or "(holds the picture; adds what its cues say)",
                "focal": f.get("focal", ""),
                "objects": [
                    {k: o[k] for k in ("id", "what", "words", "state", "type") if o.get(k)}
                    for o in f.get("objects", [])
                ],
                "cues": [
                    {
                        "key": f"{f['id']}/{k}",
                        "on_the_word": c.get("at", ""),
                        "object": c.get("object", ""),
                        "does": c.get("does", ""),
                        "move": c.get("move", ""),
                    }
                    for k, c in enumerate(f.get("cues", []))
                ],
            }
        )
    clear = geometry.keep_clear(unit.get("layout"))
    return {
        "file": f"pictures/{comp}.html",
        "composition_id": comp,
        "clock_id": f"{comp}-clock",
        "canvas": {"width": unit["canvas"][0], "height": unit["canvas"][1]},
        "keep_clear": (
            {"left": clear[0], "top": clear[1], "width": clear[2], "height": clear[3]}
            if clear
            else None
        ),
        "level": unit.get("level", "simple"),
        "idea_of_the_film": full.get("brief", {}).get("idea", ""),
        "picture": {
            "kind": unit.get("picture", ""),
            "arrangement": unit.get("arrangement", ""),
            "shows": unit.get("shows", ""),
        },
        "look": {
            "palette": look.palette,
            "fonts": {"display": look.display, "text": look.text, "mono": look.mono},
            "other_fonts_on_the_rendering_computer": [
                f for f in FONTS if f not in (look.display, look.text, look.mono)
            ],
            "motion": {
                k: motion.get(k) for k in ("name", "reveal", "ease", "accent") if motion.get(k)
            },
        },
        "lines": lines,
        "note_from_the_person": note,
    }


def faults(html: str, unit: Row, full: Row, look: Look | None = None) -> list[str]:
    """What stops a file from being this unit's picture. Read from the file alone; what only
    a render can show (overlap, a hero that never lands) is the stills' job."""
    comp = composition_id(unit["id"])
    out: list[str] = []
    template = re.search(r"<template\b[^>]*>(.*)</template>", html, re.S)
    if template is None:
        return ["the file has no <template>: everything the picture needs goes inside one"]
    inside = template.group(1)
    if not re.search(rf'data-composition-id\s*=\s*["\']{re.escape(comp)}["\']', inside):
        out.append(f'the root inside the template needs data-composition-id="{comp}"')
    if not re.search(rf'__timelines\[\s*["\']{re.escape(comp)}["\']\s*\]\s*=', inside):
        out.append(f'register the one paused timeline as window.__timelines["{comp}"]')
    width, height = unit["canvas"]
    if f'data-width="{width}"' not in inside or f'data-height="{height}"' not in inside:
        out.append(f'the root needs data-width="{width}" and data-height="{height}"')
    found = CLOCK.search(inside)
    if found is None or found.group("id") != f"{comp}-clock":
        out.append(
            f'keep the clock as <script type="application/json" id="{comp}-clock"> inside the '
            "template, and read every time from it"
        )
    for key in cue_keys(unit, full):
        if key not in inside:
            out.append(f'cue "{key}" is never used: start its move at the clock\'s cues["{key}"]')
    if re.search(r"<style\b", html.replace(template.group(0), "")):
        out.append("a <style> outside the template is dropped when the picture is mounted")
    for pattern, why in BANNED:
        if re.search(pattern, html, re.I):
            out.append(why)
    families = set(re.findall(r"font-family\s*:\s*([^;}\n]+)", html))
    allowed = (look or Look()).families
    known = {f.lower() for f in allowed} | {
        "sans-serif",
        "serif",
        "monospace",
        "system-ui",
        "inherit",
        "ui-monospace",
    }
    for declared in families:
        first = declared.split(",")[0].strip().strip("\"'").lower()
        if first and first not in known and not first.startswith("var("):
            out.append(
                f"the font {first!r} is not on the rendering computer: use {', '.join(allowed)}"
            )
    return list(dict.fromkeys(out))


def stage(unit: Row, own: Row, *, ground: str = PALETTE["ground"]) -> str:
    """A page that shows this picture alone, at its own size, for posing stills and a draft
    clip of it."""
    comp = composition_id(unit["id"])
    width, height = unit["canvas"]
    seconds = max(float(own.get("seconds", 0.0)), 0.5)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={width}, height={height}" />
    <script src="gsap.min.js"></script>
    <style>
      html, body {{ margin: 0; width: {width}px; height: {height}px; overflow: hidden; background: {ground}; }}
      #root {{ position: relative; width: 100%; height: 100%; overflow: hidden; background: {ground}; }}
      #{comp} {{ position: absolute; inset: 0; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{seconds:.3f}" data-width="{width}" data-height="{height}">
      <div id="{comp}" data-composition-id="{comp}" data-composition-src="{FOLDER}/{comp}.html" data-start="0" data-duration="{seconds:.3f}" data-track-index="1" data-width="{width}" data-height="{height}"></div>
    </div>
    <script>
      window.__timelines["main"] = gsap.timeline({{ paused: true }});
    </script>
  </body>
</html>
"""
