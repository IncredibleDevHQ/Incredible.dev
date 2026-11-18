"""A built picture: what its builder is handed, what the file must hold, and its clock.

A picture is one HyperFrames sub-composition. Its builder decides how it looks and moves; code
decides when. Every time in the file comes from a block of data (`<id>-clock`) that code
rewrites: from the plan's clock while the picture is being posed, from the take's once the
chapter is recorded. So a recording never sends a picture back to its builder.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any

from design_agent.episode import catalog, geometry
from design_agent.episode import questions as Q

Row = dict[str, Any]

#: The palette a picture and the film's own cards share when the channel wears no brand.
PALETTE: dict[str, str] = {
    # Incredible's own: zinc greys on white and its green, as the old product had them
    "ground": "#F4F4F5",
    "panel": "#FFFFFF",
    "ink": "#18181B",
    "muted": "#52525B",
    "line": "#D4D4D8",
    "accent": "#15803D",
    "accent_ink": "#FFFFFF",
    "good": "#15803D",
    "bad": "#B91C1C",
}
#: Fonts the computer that renders has, whatever the builder's own machine has.
FONTS = ("Inter", "Fraunces", "IBM Plex Mono", "Fira Code")
#: Where a picture sits in a HyperFrames project: its checks read sub-compositions from here.
FOLDER = "compositions"
#: The ways a picture carries an idea. A rich picture's motion plan names one, so the picture
#: is one thing that develops and not a set of boxes that arrive.
DEVICES = (
    "the object is the explanation",
    "one diagram that grows",
    "continuous transformation",
    "the worked example",
    "steps in order",
    "two sides",
    "one chosen out of many",
    "a number that lands",
    "a real screen, the detail circled",
)
#: What a shot of a motion plan says. `shot` is the line a person reads beside the script, so
#: it is short; the rest is the builder's and is kept nearly whole. `camera` (how the shot is
#: framed and how the view moves) and `between` (what happens where the line's cues leave more
#: than a few seconds with nothing changing) are the shot as HyperFrames' spec writes one, and
#: a plan may leave them out.
SHOT_FIELDS = ("shot", "opens_on", "hero", "others", "still", "camera", "between")
#: The picture's spec, after HyperFrames' `SPEC.md`: the look as numbers, how each thing is
#: drawn so it reads without its label, the motion by role, and what the picture must not
#: become. Each is prose with numbers in it; a plan written before the spec has none.
SPEC_FIELDS = ("look", "objects", "motion", "banned")
#: The treatments weighed before one was built, a line each, so a person can ask for another.
TREATMENTS = 3
#: The fields every shot has, as the studio shows them; the others are kept only when said.
REQUIRED_SHOT_FIELDS = ("shot", "opens_on", "hero", "others", "still")
SHOT_CHARS = 1500
SHOT_WORDS = 24


# Fixed, offline CSS patterns shared by the picker and both render surfaces.
_MARK = "color-mix(in srgb, currentColor 16%, transparent)"
TEXTURES = {
    "solid": ("none", "auto"),
    "dots": (f"radial-gradient(circle, {_MARK} 1.6px, transparent 2px)", "26px 26px"),
    "grid": (
        f"linear-gradient(to right, {_MARK} 1px, transparent 1px), "
        f"linear-gradient(to bottom, {_MARK} 1px, transparent 1px)",
        "40px 40px",
    ),
    "diagonal": (
        f"repeating-linear-gradient(135deg, transparent 0 17px, {_MARK} 17px 18px)",
        "auto",
    ),
}


def _luminance(hex_color: str) -> float:
    raw = hex_color.lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    rgb = [int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


@dataclass(frozen=True)
class Look:
    """What a film's pictures and its own cards wear: the brand's colours by role and its
    type, or the house's plain ones when the channel wears no brand."""

    palette: dict[str, str] = field(default_factory=lambda: dict(PALETTE))
    display: str = "Fraunces"
    text: str = "Inter"
    mono: str = "IBM Plex Mono"
    series: tuple[str, ...] = ()

    texture: str = "solid"
    custom_color: bool = False

    def with_background(self, color: str, texture: str) -> Look:
        if not color:
            return replace(self, texture=texture)
        palette = {**self.palette, "ground": color}
        ground, ink = _luminance(color), _luminance(palette["ink"])
        if (max(ground, ink) + 0.05) / (min(ground, ink) + 0.05) < 4.5:
            if ground < 0.179:
                palette.update(ink="#ffffff", panel="#17212c", muted="#e4e8ed", line="#697685")
            else:
                palette.update(ink="#101114", panel="#fafafa", muted="#26282b", line="#85888b")
        return replace(self, palette=palette, texture=texture, custom_color=True)

    def background_css(self) -> str:
        image, size = TEXTURES[self.texture]
        return f"background-color:{self.palette['ground']};background-image:{image};background-size:{size};color:{self.palette['ink']}"

    def tokens(self) -> Row:
        return {
            "palette": self.palette,
            "fonts": {"display": self.display, "text": self.text, "mono": self.mono},
            "series": self.series,
            **({"texture": self.texture} if self.texture != "solid" else {}),
        }

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
LAYOUTS = Q.table("layouts")
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


#: A stretch this long with no cue in it is where a picture goes dead (HyperFrames' check
#: warns past three seconds with nothing changing).
QUIET_SECONDS = 3.0
#: The most frames taken of one picture's motion for its review.
MOTION_FRAMES = 24


def motion_times(own: Row) -> list[tuple[str, float]]:
    """Where a picture's motion is looked at, beyond the still at each line's end: inside every
    cue's move, once it has landed, and in the middle of each stretch the cues leave quiet. Each
    is named by its line, its place in the picture and what it shows, in the order they play."""
    seconds = float(own.get("seconds") or 0.0)
    lines = own.get("lines", {})
    cues = sorted(own.get("cues", {}).items(), key=lambda item: item[1])

    def line_of(at: float) -> str:
        return next((frame for frame, (start, end) in lines.items() if start <= at <= end), "")

    marks: list[tuple[str, float]] = []
    edges = [0.0]
    for key, at in cues:
        frame, _, n = key.partition("/")
        cue = f"cue{int(n) + 1}" if n.isdigit() else "cue"
        marks.append((f"{frame}-{cue}-moving", at + 0.15))
        marks.append((f"{frame}-{cue}-landed", at + 0.75))
        edges.append(float(at))
    edges.append(seconds)
    for before, after in zip(edges, edges[1:], strict=False):
        if after - before > QUIET_SECONDS + 0.75:
            middle = (before + 0.75 + after) / 2
            marks.append((f"{line_of(middle) or 'picture'}-quiet", middle))
    kept = sorted(
        ((name, round(min(max(at, 0.0), max(seconds - 0.05, 0.0)), 3)) for name, at in marks),
        key=lambda mark: mark[1],
    )
    # two looks a few frames apart show the same thing: the first of each is kept
    spaced: list[tuple[str, float]] = []
    for name, at in kept:
        if not spaced or at - spaced[-1][1] >= 0.1:
            spaced.append((name, at))
    if len(spaced) > MOTION_FRAMES:
        step = len(spaced) / MOTION_FRAMES
        spaced = [spaced[int(i * step)] for i in range(MOTION_FRAMES)]
    return [(f"{n:02d}-{name}", at) for n, (name, at) in enumerate(spaced, start=1)]


def with_clock(html: str, own: Row) -> str:
    """The file with its clock block replaced by `own`."""
    payload = json.dumps(own, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return CLOCK.sub(lambda m: m.group(1) + payload + m.group(4), html, count=1)


def dressed(html: str, own: Row, look: Look | None = None) -> str:
    """The file as it is rendered: its clock set, and the look's families declared inside the
    template so the renderer finds them."""
    theme = look or Look()
    faces = f"<style>{theme.faces()}</style>"
    tokens = json.dumps(theme.tokens(), ensure_ascii=True).replace("<", r"\u003c")
    html = re.sub(
        r'(<script type="application/json" data-episode-theme>).*?(</script>)',
        lambda match: match[1] + tokens + match[2],
        html,
        count=1,
        flags=re.S,
    )
    if theme.custom_color or theme.texture != "solid":
        style = f"<style>#root {{ {theme.background_css()} }}</style>"
        html = re.sub(r"</template>", lambda m: style + m[0], html, count=1)
    timed = with_clock(html, own)
    return re.sub(r"(<template\b[^>]*>)", lambda m: m.group(1) + faces, timed, count=1)


def brief(
    unit: Row,
    full: Row,
    *,
    look: Look | None = None,
    note: str = "",
    planned: Row | None = None,
) -> Row:
    """Everything one picture is built from, as data its builder reads beside the skill's
    rules: the canvas, the look, each line with what it adds, and the cue keys. A rich
    picture's brief also carries its motion plan once that is written (`planned`)."""
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
                    {
                        k: o[k]
                        for k in (
                            "id",
                            "what",
                            "words",
                            "state",
                            "type",
                            "value",
                            "unit",
                            "series",
                            "from",
                            "to",
                            "parent",
                            "owner",
                        )
                        if o.get(k) is not None
                    }
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
    layout = LAYOUTS.get(str(unit.get("layout")), LAYOUTS[geometry.FALLBACK])
    clear = unit.get("keep_clear", geometry.keep_clear(unit.get("layout")))
    return {
        "layout": {"id": layout["id"], "presence": layout["presence"], "use": layout["reads_as"]},
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
        "connections": unit.get("visual", {}).get("connections", []),
        "visual": {
            **{
                k: unit["visual"][k]
                for k in ("component", "variant", "direction")
                if k in unit.get("visual", {})
            },
            "motion": catalog.COMPONENTS[unit.get("visual", {}).get("component", "custom")].motion,
        },
        "idea_of_the_film": full.get("brief", {}).get("idea", ""),
        "picture": {
            "kind": unit.get("picture", ""),
            "arrangement": unit.get("arrangement", ""),
            "shows": unit.get("shows", ""),
            **(
                {"kind_chosen_by": "the person, over the plan's own reading"}
                if unit.get("picture_by") == "person"
                else {}
            ),
        },
        "look": {
            **look.tokens(),
            "other_fonts_on_the_rendering_computer": [
                f for f in FONTS if f not in (look.display, look.text, look.mono)
            ],
            "motion": {
                k: motion.get(k) for k in ("name", "reveal", "ease", "accent") if motion.get(k)
            },
        },
        "lines": lines,
        "note_from_the_person": note,
        **({"motion_plan": planned} if planned else {}),
    }


def motion_file(unit_id: str) -> str:
    """Where a rich picture's builder writes its motion plan, in the episode's folder."""
    return f"pictures/{composition_id(unit_id)}.motion.json"


def brief_motion(brief: Row) -> Row:
    """A complete editable shot sheet built only from this picture's approved lines and cues."""
    shots: list[Row] = []
    for line in brief["lines"]:
        names = {
            obj["id"]: obj.get("words") or obj.get("what") or obj["id"] for obj in line["objects"]
        }
        moves = [
            f"{names.get(c['object'], c['object'])} {c['does']}".strip()
            for c in line["cues"]
            if c["does"]
        ]
        still = line["shows_when_finished"]
        if not still or still.startswith("("):
            still = (
                ", ".join(str(n) for n in names.values())
                or brief["picture"]["shows"]
                or "Hold the preceding frame."
            )
        hero = moves[0] if moves else still
        shots.append(
            {
                "frame": line["frame"],
                "shot": " ".join(hero.split()[:20]),
                "opens_on": shots[-1]["still"] if shots else "",
                "hero": hero,
                "others": "; ".join(moves[1:]),
                "still": still,
            }
        )
    device = {
        "timeline": "steps in order",
        "stepper": "steps in order",
        "comparison": "two sides",
        "bar-chart": "a number that lands",
        "line-chart": "a number that lands",
        "detail-card": "the object is the explanation",
    }.get(brief["visual"].get("component"), "one diagram that grows")
    return {
        "device": device,
        "world": brief["picture"]["shows"] or shots[0]["still"],
        "shots": shots,
    }


def motion_plan(text: str, unit: Row) -> tuple[Row, list[str]]:
    """A motion plan as its builder wrote it, read and held to its shape: one shot per line of
    the picture, in order, each with the move the line is about and what its still shows.
    Returns the plan as it is kept (only what the shape names) and what stops it."""
    try:
        given = json.loads(text)
    except ValueError as error:
        return {}, [f"the file is not JSON: {error}"]
    if not isinstance(given, dict) or not isinstance(given.get("shots"), list):
        return {}, ['the file is one object with "device", "world" and a "shots" list']
    faults: list[str] = []
    shots: list[Row] = []
    by_frame = {str(shot.get("frame")): shot for shot in given["shots"] if isinstance(shot, dict)}
    if len(by_frame) != len(given["shots"]):
        faults.append("Each shot must be an object with a unique frame; remove duplicate shots.")
    for frame in unit["frames"]:
        shot = by_frame.get(frame)
        if shot is None:
            faults.append(f"line {frame} has no shot: write one shot for every line, in order")
            continue
        kept: Row = {"frame": frame}
        for name in SHOT_FIELDS:
            value = " ".join(str(shot.get(name) or "").split())[:SHOT_CHARS]
            if value or name in REQUIRED_SHOT_FIELDS:
                kept[name] = value
        for name in ("shot", "hero", "still"):
            if not kept[name]:
                faults.append(f'the shot for line {frame} needs "{name}"')
        said = len(kept["shot"].split())
        if said > SHOT_WORDS:
            faults.append(
                f'"shot" for line {frame} is one plain sentence of at most 20 words '
                f'(it has {said}): the detail goes in "hero" and "others"'
            )
        shots.append(kept)
    extra = [frame for frame in by_frame if frame not in unit["frames"]]
    if extra:
        faults.append(f"shots for lines the picture does not have: {', '.join(sorted(extra))}")
    device = " ".join(str(given.get("device") or "").split())
    if device not in DEVICES:
        faults.append('"device" is one of: ' + "; ".join(DEVICES))
    world = " ".join(str(given.get("world") or "").split())[:SHOT_CHARS]
    if not world:
        faults.append('"world" says where the picture happens, in one line')
    plan: Row = {"device": device, "world": world, "shots": shots}
    for name in SPEC_FIELDS:
        value = " ".join(str(given.get(name) or "").split())[:SHOT_CHARS]
        if value:
            plan[name] = value
    weighed = given.get("treatments")
    if isinstance(weighed, list):
        lines = [
            " ".join(str(t).split())[:400] for t in weighed if isinstance(t, str) and t.strip()
        ]
        if lines:
            plan["treatments"] = lines[:TREATMENTS]
    return plan, faults


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


def label_probe(html: str, unit: Row, own: Row) -> str:
    """Mount the same dressed template at its native canvas size in sandbox Chromium."""
    comp = composition_id(unit["id"])
    width, height = unit["canvas"]
    content = re.search(r"<template\b[^>]*>(.*)</template>", html, re.S)
    if content is None:
        raise ValueError("Missing picture template.")
    times = sorted(
        {*still_times(own).values(), *(min(t + 0.45, own["seconds"]) for t in own["cues"].values())}
    )
    return f"""<!doctype html><meta charset="utf-8"><style>
    html,body {{margin:0;position:relative;width:{width}px;height:{height}px}}
    [data-composition-id="{comp}"] {{position:absolute;inset:0}}</style>
    <script src="gsap.min.js"></script><script>window.__timelines={{}};</script>
    {content[1]}
    <script src="check-labels.js"></script><script>
    document.fonts.ready.then(() => {{
      const scene = document.querySelector('[data-composition-id="{comp}"]');
      const tl = window.__timelines["{comp}"];
      const issues = new Set();
      for (const t of {json.dumps(times)}) {{
        tl.time(t, false);
        for (const problem of checkLabels(scene)) issues.add(problem);
      }}
      document.body.textContent = 'LABEL_REPORT=' + encodeURIComponent(JSON.stringify([...issues]));
    }});
    </script>"""


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
