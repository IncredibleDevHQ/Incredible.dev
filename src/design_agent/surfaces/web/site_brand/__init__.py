"""A brand pack from a website: the house's own read of the brand a site shows, modelled on
HyperFrames' capture but never calling it (the product must carry the capability itself).

`read_site` renders the page in a throwaway container of the sandbox image, the one place a page
from the internet runs, with network for that read alone (`capture.mjs`, `page.js`). It keeps how
every colour is used, the faces in use, the site's logo and icon, the shape of its type and
controls, and its first screen; a human check or a block stops it with a reason, never a brand.
`write_pack` turns the read into a pack the engine validates: `brand.toml`, `tokens.json`,
`fonts.toml`, `voice.md`, `graphic-language.md`, the logos and the first screen as a reference.
A face the site licenses for its own pages only is never copied: the nearest open face in
`fonts/` stands in for it, and the guide names both.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hashlib
import json
import re
import shutil
import statistics
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from design_agent.brand.schema import BrandPack, load_brand_pack
from design_agent.config import SAMPLE_BRAND

CAPTURE_DIR = Path(__file__).parent
#: A read's limit, start to finish (a page that never settles is read as it stands at 30 s).
READ_SECONDS = 150.0
#: What a container may use for one read.
LIMITS = ("--memory", "2g", "--cpus", "2", "--pids-limit", "512")

#: Open faces the checkout already has, by family: (file, weight, style, required).
REPO_FONTS: dict[str, tuple[tuple[str, str, str, bool], ...]] = {
    "Inter": (
        ("fonts/Inter-Variable.ttf", "100 900", "normal", True),
        ("fonts/Inter-Italic-Variable.ttf", "100 900", "italic", False),
    ),
    "Geist": (
        ("fonts/Geist-Variable.ttf", "100 900", "normal", True),
        ("fonts/Geist-Italic-Variable.ttf", "100 900", "italic", False),
    ),
    "Fraunces": (
        ("fonts/Fraunces-Variable.ttf", "100 900", "normal", True),
        ("fonts/Fraunces-Italic-Variable.ttf", "100 900", "italic", False),
    ),
    "IBM Plex Mono": (
        ("fonts/IBMPlexMono-Regular.ttf", "400", "normal", True),
        ("fonts/IBMPlexMono-Medium.ttf", "500", "normal", False),
        ("fonts/IBMPlexMono-SemiBold.ttf", "600", "normal", False),
    ),
    "Fira Code": (("fonts/FiraCode-Variable.ttf", "300 700", "normal", True),),
    "Fragment Mono": (
        ("fonts/FragmentMono-Regular.ttf", "400", "normal", True),
        ("fonts/FragmentMono-Italic.ttf", "400", "italic", False),
    ),
}
#: The open face that stands in for a licensed one, by the licensed face's kind.
STAND_INS = {"sans": "Inter", "serif": "Fraunces", "mono": "IBM Plex Mono"}
SERIF = re.compile(
    r"serif|garamond|times|georgia|playfair|tiempos|lora|freight|caslon|baskerville|didot|bodoni|"
    r"chronicle|merriweather|newsreader|fraunces|canela|lyon|reckless|editorial",
    re.IGNORECASE,
)
MONO = re.compile(r"mono|code|courier|menlo|consolas", re.IGNORECASE)
GENERIC = {"system-ui", "ui-monospace", "sans-serif", "serif", "monospace"}
#: Hype a brand's words never carry, whatever the site says.
BANNED_PHRASES = (
    "game-changer",
    "game changer",
    "revolutionize",
    "revolutionary",
    "seamless",
    "seamlessly",
    "unlock the power",
    "unleash",
    "cutting-edge",
    "next-level",
    "synergy",
    "in today's fast-paced world",
    "delve into",
    "elevate your",
)
PRIMARIES = ("#ff0000", "#00ff00", "#0000ff", "#ff00ff")


class SiteBrandError(RuntimeError):
    """A read that could not make a brand: the page wouldn't load, asked for a human check, or
    the container failed. The message is said to the person as it is."""


# -- the read ------------------------------------------------------------------------------


def checked_url(url: str) -> str:
    raw = url.strip()
    if not re.match(r"^https?://", raw, re.IGNORECASE):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or "." not in parsed.hostname:
        raise SiteBrandError("Give the site's address, like https://example.com.")
    return raw


async def read_site(
    url: str, out: Path, *, image: str, timeout: float = READ_SECONDS
) -> dict[str, Any]:
    """Read a site's brand into `out` (capture.json and the files it names)."""
    out.mkdir(parents=True, exist_ok=True)
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "bridge",
        *LIMITS,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "1000:1000",
        "-e",
        "HOME=/tmp",
        "-v",
        f"{CAPTURE_DIR}:/capture:ro",
        "-v",
        f"{out}:/out",
        "--entrypoint",
        "node",
        image,
        "/capture/capture.mjs",
        url,
        "/out",
    ]
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        _, said = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        raise SiteBrandError("The site took too long to read.") from None
    if process.returncode:
        lines = [line for line in said.decode(errors="replace").splitlines() if line.strip()]
        raise SiteBrandError(lines[-1][:300] if lines else "The read stopped.")
    try:
        found = json.loads((out / "capture.json").read_text())
    except (OSError, ValueError):
        raise SiteBrandError("The read left nothing to make a brand from.") from None
    if not isinstance(found, dict):
        raise SiteBrandError("The read left nothing to make a brand from.")
    return found


# -- colour ----------------------------------------------------------------------------------


def _rgb(hex_: str) -> tuple[int, int, int]:
    raw = hex_.lstrip("#")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _hex(rgb: Sequence[float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def lightness(hex_: str) -> float:
    r, g, b = _rgb(hex_)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def colourfulness(hex_: str) -> int:
    rgb = _rgb(hex_)
    return max(rgb) - min(rgb)


def mix(a: str, b: str, share: float) -> str:
    """`share` of `a` laid over `b`."""
    return _hex([x * share + y * (1 - share) for x, y in zip(_rgb(a), _rgb(b), strict=True)])


def _valid(hex_: Any) -> bool:
    return isinstance(hex_, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", hex_) is not None


def palette_of(found: Mapping[str, Any]) -> dict[str, str]:
    """The colours by role: ground, ink and accent from the read's roles, then what the site
    also uses (a second accent it fills controls with, secondary text, rules, a raised surface)."""
    roles = found.get("roles") or {}
    ground = str(roles.get("ground") or "#ffffff").lower()
    ink = str(roles.get("text") or ("#111111" if lightness(ground) > 128 else "#f5f5f5")).lower()
    stats = [s for s in found.get("stats") or [] if _valid(s.get("hex"))]
    for stat in stats:
        stat["hex"] = stat["hex"].lower()
    colourful = [
        s
        for s in stats
        if colourfulness(s["hex"]) > 40 and s["hex"] not in (ground, ink) and s["bgCount"]
    ]
    accent = str(roles.get("accent") or "").lower()
    if not _valid(accent):
        accent = colourful[0]["hex"] if colourful else ink
    picked = {"ground": ground, "ink": ink, "accent": accent}
    used = {s["hex"]: s for s in stats}
    second = str(roles.get("second") or "").lower()
    # A second accent only when the site really uses it (a fill, or recurring text), not a badge.
    if (
        _valid(second)
        and second in used
        and (used[second]["bgCount"] >= 2 or used[second]["textCount"] >= 4)
    ):
        picked["second"] = second
    fills = sorted(
        (s for s in colourful if s["interactiveBg"] and s["hex"] not in picked.values()),
        key=lambda s: -(s["interactiveBg"] * 3 + s["bgCount"]),
    )
    if fills:
        picked["accent-bright"] = fills[0]["hex"]
    span = lightness(ink) - lightness(ground)
    neutral = [s for s in stats if colourfulness(s["hex"]) < 24 and s["hex"] not in picked.values()]
    between = [
        s
        for s in neutral
        if s["textCount"] and 0.35 <= (lightness(s["hex"]) - lightness(ground)) / (span or 1) <= 0.8
    ]
    picked["muted"] = (
        max(between, key=lambda s: s["textCount"])["hex"] if between else mix(ink, ground, 0.62)
    )
    near = [
        s
        for s in neutral
        if s["bgCount"] and 0.04 <= abs(lightness(s["hex"]) - lightness(ground)) / 255 <= 0.2
    ]
    picked["rule"] = near[0]["hex"] if near else mix(ink, ground, 0.14)
    painted_white = used.get("#ffffff", {}).get("bgCount", 0) > 0
    if (
        ground != "#ffffff"
        and lightness(ground) > 128
        and (painted_white or lightness(ground) < 245)
    ):
        picked["white"] = "#ffffff"
    return picked


# -- type ------------------------------------------------------------------------------------


def _kind(family: str, role: str) -> str:
    if role == "mono" or MONO.search(family):
        return "mono"
    return "serif" if SERIF.search(family) else "sans"


def type_of(found: Mapping[str, Any], target: Path, project_root: Path) -> dict[str, Any]:
    """The faces renders use, by role, with fonts.toml entries: the site's open faces as files
    (the checkout's copy when it has one), an open stand-in for any licensed face."""
    fonts = found.get("fonts") or {}
    files = [f for f in found.get("fontFiles") or [] if isinstance(f, dict)]
    roles: dict[str, dict[str, str]] = {}
    entries: list[dict[str, Any]] = []
    for role, key in (("display", "display"), ("text", "body"), ("mono", "mono")):
        site = str(fonts.get(key) or "").strip()
        kind = _kind(site, role)
        family = ""
        if site in REPO_FONTS:
            family = site
        else:
            kept = [
                f
                for f in files
                if f.get("family") == site and str(f.get("format")) in ("ttf", "otf")
            ]
            identity = (kept[0].get("identity") or {}) if kept else {}
            if kept and identity.get("family"):
                family = str(identity["family"])
                for face in kept:
                    source = Path(found["_dir"]) / str(face["file"])
                    copy = target / "fonts" / source.name
                    copy.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, copy)
                    italic = bool((face.get("identity") or {}).get("italic"))
                    entries.append(
                        {
                            "family": family,
                            "weight": _weight(face),
                            "style": "italic" if italic else "normal",
                            "file": str(copy.relative_to(project_root)),
                            "required": not italic,
                            "license": f"Open (SIL OFL or Apache), as {found.get('host', 'the site')} serves it",
                        }
                    )
        stand_in = not family
        if stand_in:
            family = STAND_INS[kind]
        if family in REPO_FONTS:
            for file, weight, style, required in REPO_FONTS[family]:
                entries.append(
                    {
                        "family": family,
                        "weight": weight,
                        "style": style,
                        "file": file,
                        "required": required,
                        "license": "OFL-1.1",
                    }
                )
        roles[role] = {
            "family": family,
            "site": site if site and site not in GENERIC else "",
            "kind": kind,
            "stand_in": "yes" if stand_in and site and site not in GENERIC else "",
        }
    seen: set[str] = set()
    unique = []
    for entry in entries:
        if entry["file"] in seen:
            continue
        seen.add(entry["file"])
        path = project_root / entry["file"]
        entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        unique.append(entry)
    return {"roles": roles, "entries": unique}


def _weight(face: Mapping[str, Any]) -> str:
    identity = face.get("identity") or {}
    value = identity.get("weight") or re.sub(r"[^\d ]", "", str(face.get("weight") or "400"))
    parts = [int(p) for p in str(value).split() if p.isdigit()][:2] or [400]
    if len(parts) == 2 and parts[0] != parts[1]:
        return f"{min(parts):03d} {max(parts):03d}"
    return f"{parts[0]:03d}"


# -- the pack ----------------------------------------------------------------------------------


def slug_of(found: Mapping[str, Any]) -> str:
    host = str(found.get("host") or urlparse(str(found.get("url") or "")).hostname or "site")
    labels = [p for p in host.lower().split(".") if p and p != "www"]
    name = labels[-2] if len(labels) >= 2 else labels[0]
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-") or "site"


def name_of(found: Mapping[str, Any]) -> str:
    meta = found.get("meta") or {}
    site = str(meta.get("siteName") or "").strip()
    if site:
        return site[:80]
    title = str(meta.get("title") or "")
    parts = [p.strip() for p in re.split(r"\s[|\-–—:·]\s", title) if p.strip()]
    slug = slug_of(found)
    for part in reversed(parts):
        if slug in part.lower().replace(" ", ""):
            return str(part)[:80]
    return slug.replace("-", " ").title()


def _median(values: Sequence[float], default: float) -> float:
    return statistics.median(values) if values else default


def shape_of(found: Mapping[str, Any]) -> dict[str, Any]:
    shape = found.get("shape") or {}
    radii = [float(r) for r in shape.get("buttonRadii") or [] if isinstance(r, int | float)]
    cards = [float(c.get("radius") or 0) for c in shape.get("cards") or [] if isinstance(c, dict)]
    # A corner of 40px or more is a pill's (or a tab's), not a card's.
    pills = any(r >= 40 for r in radii)
    plain = sorted(r for r in [*radii, *cards] if 0 < r < 40)
    headlines = [h for h in shape.get("headlines") or [] if isinstance(h, dict)]
    weights = [float(h.get("weight") or 400) for h in headlines]
    tracking = []
    for h in headlines:
        match = re.match(r"(-?[\d.]+)px", str(h.get("tracking") or ""))
        if match and h.get("size"):
            tracking.append(float(match.group(1)) / float(h["size"]))
    titled = [h for h in headlines if len(str(h.get("text") or "").split()) >= 2]
    title_case = sum(
        1
        for h in titled
        if all(w[:1].isupper() for w in str(h["text"]).split() if len(w) > 3 and w[:1].isalpha())
    )
    return {
        "sm": int(plain[0]) if plain else 4,
        "md": int(_median(plain, 8)),
        "lg": int(min(plain[-1], 48)) if plain else 12,
        "pills": pills,
        "display_weight": int(round(_median(weights, 500) / 100) * 100),
        "tracking": round(_median(tracking, -0.01), 3),
        "casing": "title" if titled and title_case / len(titled) >= 0.6 else "sentence",
        "headlines": [str(h.get("text") or "") for h in headlines[:6]],
        "calls": _calls(shape.get("controls") or []),
    }


def _calls(controls: Sequence[Any]) -> list[str]:
    """The site's calls to action: filled in a colour of its own, never a nav tab or a search box."""
    out: list[str] = []
    for control in controls:
        if not isinstance(control, dict):
            continue
        text = str(control.get("text") or "").strip()
        fill = str(control.get("background") or "")
        if not text or re.search(r"ctrl|⌘|cmd|search", text, re.IGNORECASE):
            continue
        if _valid(fill) and colourfulness(fill) > 40 and text not in out:
            out.append(text)
    return out[:4]


def write_pack(
    found: Mapping[str, Any], source: Path, target: Path, project_root: Path
) -> BrandPack:
    """Write the pack for a read (`source` holds its files) into `target`, replacing any pack
    there only once the new one validates."""
    project_root = project_root.resolve()
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    try:
        found = {**found, "_dir": str(source)}
        _write(found, source, staging, project_root, final=target)
        load_brand_pack(staging, project_root=project_root)
        old = target.with_name(f".{target.name}-old")
        if target.exists():
            shutil.rmtree(old, ignore_errors=True)
            target.rename(old)
        staging.rename(target)
        shutil.rmtree(old, ignore_errors=True)
        # Fonts copied in were named for the staging folder: the pack names them in place.
        fonts_toml = target / "fonts.toml"
        fonts_toml.write_text(
            fonts_toml.read_text().replace(
                str(staging.relative_to(project_root)), str(target.relative_to(project_root))
            )
        )
        return load_brand_pack(target, project_root=project_root)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _write(
    found: Mapping[str, Any], source: Path, out: Path, project_root: Path, *, final: Path
) -> None:
    colours = palette_of(found)
    kinds = type_of(found, out, project_root)
    shape = shape_of(found)
    name = name_of(found)
    host = str(found.get("host") or "the site")
    url = str(found.get("finalUrl") or found.get("url") or "")
    today = dt.date.today().isoformat()
    meta = found.get("meta") or {}
    description = str(meta.get("description") or "").strip() or f"The brand {host} shows."
    dark = lightness(colours["ground"]) < 128
    mode = "dark" if dark else "light"

    tokens = {f"--brand-color-{role}": value for role, value in colours.items()}
    tokens.update(
        {
            "--brand-radius-sm": f"{min(shape['sm'], shape['md'])}px",
            "--brand-radius-md": f"{shape['md']}px",
            "--brand-radius-lg": f"{max(shape['lg'], shape['md'])}px",
            "--brand-space-unit": "8px",
            "--brand-stroke": "2px",
            "--brand-weight-display": str(shape["display_weight"]),
            "--brand-weight-text": "400",
            "--brand-weight-strong": "600" if shape["display_weight"] < 600 else "700",
            "--brand-tracking-display": f"{shape['tracking']}em",
        }
    )
    if shape["pills"]:
        tokens["--brand-radius-pill"] = "999px"
    accent = colours["accent"]
    extended = sorted(
        {
            mix(accent, colours["ground"], 0.7),
            mix(accent, colours["ground"], 0.4),
            mix(accent, colours["ground"], 0.15),
            *(mix(colours["second"], colours["ground"], 0.5) for _ in [0] if "second" in colours),
        }
        - set(colours.values())
    )
    allowed = list(dict.fromkeys(colours.values()))
    banned = [c for c in (*PRIMARIES, "#000000") if c not in allowed and c not in extended]
    series = [
        f"--brand-color-{r}" for r in ("accent", "second", "accent-bright", "muted") if r in colours
    ]
    families = [kinds["roles"][r]["family"] for r in ("display", "text", "mono")]
    stacks = {
        "display": [
            families[0],
            "system-ui",
            "serif" if kinds["roles"]["display"]["kind"] == "serif" else "sans-serif",
        ],
        "text": [
            families[1],
            "system-ui",
            "serif" if kinds["roles"]["text"]["kind"] == "serif" else "sans-serif",
        ],
        "mono": [families[2], "ui-monospace", "monospace"],
    }
    tokens_file = {
        "_comment": f"{name}, read from {url} on {today}. Validated by src/design_agent/brand/schema.py.",
        "version": "1",
        "design": {
            "allowedColors": allowed,
            "extendedPalette": {
                "_note": "Tints of the accent for charts and diagrams only.",
                "colors": extended,
            },
            "officialAssetColors": {
                "_note": "Colours that appear only inside the official marks.",
                "colors": [],
                "assets": {},
            },
            "bannedColors": {
                "_note": "Defaults and saturated primaries the site never uses.",
                "colors": banned,
            },
            "replacementColors": {"#000000": "--brand-color-ink"} if "#000000" in banned else {},
            "allowedFontTokens": [
                "--brand-font-display",
                "--brand-font-text",
                "--brand-font-mono",
                *dict.fromkeys(families),
            ],
            "knownOffBrandFonts": [
                f
                for f in (
                    "Arial",
                    "Helvetica",
                    "Times New Roman",
                    "Comic Sans MS",
                    "Papyrus",
                    "Impact",
                )
                if f not in families
            ],
            "fontStacks": stacks,
            "maxRectRadiusPx": max(shape["lg"], 16),
            "creativeTypography": {
                "canonicalCasing": {name.upper(): name} if name.upper() != name else {}
            },
            "tokens": tokens,
            "roles": {
                mode: {
                    "_note": f"As {host} uses them.",
                    "ground": "--brand-color-ground",
                    "ink": "--brand-color-ink",
                    "accent": "--brand-color-accent",
                    "muted": "--brand-color-muted",
                    "quiet": "--brand-color-rule",
                    "rule": "--brand-color-rule",
                    "series": series,
                }
            },
            "rules": [
                f"Grounds are {colours['ground']}{' or white' if 'white' in colours else ''}, as {host} shows them.",
                f"The accent {accent} marks the one thing that matters in a frame: a control, the key number, the active step.",
                "Headlines in the display face at its weight and tracking; body text in the text face.",
            ],
        },
        "copy": {
            "_note": "Applies to words on graphics and in posts the agent drafts.",
            "bannedPhrases": list(BANNED_PHRASES),
            "warnPhrases": ["simply", "just", "very", "innovative", "world-class", "robust"],
            "bannedChars": {},
            "maxHashtags": 2,
            "casingRules": {"headlines": shape["casing"], "canonical": {name.lower(): name}},
            "rules": [
                "Say the one thing the graphic is for.",
                "Keep to what the source says; no invented claims.",
            ],
        },
    }
    (out / "tokens.json").write_text(json.dumps(tokens_file, indent=2) + "\n")

    fonts_lines = [f"# Faces renders use for {name}; read from {url} on {today}.", ""]
    for entry in kinds["entries"]:
        fonts_lines += [
            "[[fonts]]",
            f"family = {json.dumps(entry['family'])}",
            f"weight = {json.dumps(entry['weight'])}",
            f"style = {json.dumps(entry['style'])}",
            f"file = {json.dumps(entry['file'])}",
            f"sha256 = {json.dumps(entry['sha256'])}",
            f"required = {'true' if entry['required'] else 'false'}",
            f"license = {json.dumps(entry['license'])}",
            "",
        ]
    (out / "fonts.toml").write_text("\n".join(fonts_lines))

    logos = _logos(found, source, out, colours)
    formats = tomllib.loads((project_root / SAMPLE_BRAND / "brand.toml").read_text())["formats"]
    calls = ", ".join(f"“{c}”" for c in shape["calls"][:3] if c) or "short, plain calls to action"
    voice = (
        f"{name} as its site reads: {shape['casing']}-case headlines, direct and specific, and "
        f"{calls}. Lead with what the reader can do; keep every claim to what the source says."
    )[:600]
    toml_lines = [
        f"# {name}: read from {url} on {today} by the house's site read.",
        f"name = {json.dumps(name)}",
        f"description = {json.dumps(description[:400])}",
        f"voice = {json.dumps(voice)}",
        f"license = {json.dumps(f'{name} brand as {host} shows it, read for drafts about {name}. Check usage rights before anything is published.')}",
        "",
    ]
    for spec in formats:
        toml_lines += [
            "[[formats]]",
            f"slug = {json.dumps(spec['slug'])}",
            f"width = {spec['width']}",
            f"height = {spec['height']}",
            f"label = {json.dumps(spec.get('label', ''))}",
            "",
        ]
    for logo in logos:
        toml_lines += [
            "[[logos]]",
            f"file = {json.dumps(logo['file'])}",
            f"use = {json.dumps(logo['use'])}",
            f"min_width_px = {logo['min_width_px']}",
            "",
        ]
    (out / "brand.toml").write_text("\n".join(toml_lines))

    reference = ""
    first = source / str(found.get("firstScreen") or "first-screen.jpg")
    if first.is_file():
        (out / "reference").mkdir(exist_ok=True)
        shutil.copyfile(first, out / "reference" / "site.jpg")
        reference = "reference/site.jpg"

    (out / "voice.md").write_text(_voice(name, host, url, today, shape, description))
    (out / "graphic-language.md").write_text(
        _graphic(name, host, url, today, colours, kinds["roles"], shape, logos, reference)
    )
    (out / "README.md").write_text(
        f"# {name}\n\nRead from <{url}> on {today} by Creative House's site read: the page rendered "
        "in a throwaway container, how its colours, faces, logo and controls are used, kept as a "
        "brand pack. Licensed faces are named but never copied; open faces stand in for them.\n"
    )
    faces = {role: dict(info) for role, info in kinds["roles"].items()}
    (out / ".source.json").write_text(
        json.dumps(
            {"url": url, "host": host, "read": today, "final": str(final.name), "faces": faces},
            indent=2,
        )
    )


def _logos(
    found: Mapping[str, Any], source: Path, out: Path, colours: Mapping[str, str]
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    (out / "logos").mkdir(exist_ok=True)
    ground = colours["ground"]
    for key, stem, use, width in (
        (
            "logo",
            "lockup",
            f"Light grounds like {ground} and white; the default."
            if lightness(ground) > 128
            else f"Dark grounds like {ground}; the default.",
            160,
        ),
        ("symbol", "mark", "Small sizes, avatars and favicons.", 24),
    ):
        entry = found.get(key) or {}
        for kind in ("svg", "png"):
            name = entry.get(kind)
            if not name or not (source / str(name)).is_file():
                continue
            file = f"logos/{stem}.{kind}"
            shutil.copyfile(source / str(name), out / file)
            kept.append({"file": file, "use": use, "min_width_px": width})
            break
    return kept


def _voice(
    name: str, host: str, url: str, today: str, shape: Mapping[str, Any], description: str
) -> str:
    lines = [
        f"# {name} voice",
        "",
        f"Read from {url} on {today}: how {host} speaks, in its own words. Refine it with the team;",
        "until then, write the way these examples do.",
        "",
        "## How the site speaks",
        "",
        f"- It describes itself as: “{description}”",
    ]
    if shape["headlines"]:
        lines.append("- Headlines: " + "; ".join(f"“{h}”" for h in shape["headlines"] if h) + ".")
    if shape["calls"]:
        lines.append("- Calls to action: " + "; ".join(f"“{c}”" for c in shape["calls"] if c) + ".")
    lines += [
        f"- Headlines are {shape['casing']} case.",
        "",
        "## On graphics",
        "",
        "- Say the one thing the graphic is for. Every fact appears once.",
        f"- Keep to what the source says about {name}; no claim it does not make.",
        "- Use the fewest words that carry the point.",
        "",
    ]
    return "\n".join(lines)


def _graphic(
    name: str,
    host: str,
    url: str,
    today: str,
    colours: Mapping[str, str],
    roles: Mapping[str, Mapping[str, str]],
    shape: Mapping[str, Any],
    logos: Sequence[Mapping[str, Any]],
    reference: str,
) -> str:
    lines = [
        f"# {name} graphic language",
        "",
        f"Read from {url} on {today}. The values are in `tokens.json`; this is how {host} uses them.",
        "",
        "## Colour",
        "",
        "| Role | Colour | How the site uses it |",
        "| --- | --- | --- |",
    ]
    uses = {
        "ground": "what most of the screen sits on",
        "ink": "headlines and body text",
        "accent": "the primary control and the one highlighted block",
        "second": "a second colour the site fills controls or text with",
        "accent-bright": "brighter controls in the accent's family",
        "muted": "secondary text",
        "rule": "dividers, outlines and quiet fills",
        "white": "raised cards on the ground",
    }
    for role, value in colours.items():
        lines.append(f"| {role} | `{value}` | {uses.get(role, '')} |")
    lines += ["", "## Type", ""]
    for role, label in (("display", "Headlines"), ("text", "Body"), ("mono", "Code")):
        info = roles[role]
        if info["stand_in"]:
            lines.append(
                f"- {label}: the site sets {info['site']}, which it licenses for its own pages; "
                f"renders use {info['family']}, the nearest open face."
            )
        else:
            lines.append(f"- {label}: {info['family']}.")
    lines += [
        f"- Headline weight {shape['display_weight']}, tracking {shape['tracking']}em; "
        f"{shape['casing']}-case headlines.",
        "",
        "## Shape",
        "",
        f"- Corners: {shape['sm']}px small, {shape['md']}px for controls, {shape['lg']}px for cards."
        + (" The site's main calls to action are pills." if shape["pills"] else ""),
        "- Flat, light surfaces: shadows stay rare and soft.",
        "",
        "## Marks",
        "",
    ]
    if logos:
        lines += [f"- `{logo['file']}`: {logo['use']}" for logo in logos]
    else:
        lines.append("- The read found no logo it could keep; ask the team for the files.")
    if reference:
        lines += [
            "",
            "## The site",
            "",
            f"`{reference}` is the first screen of {url} as it was read.",
        ]
    return "\n".join(lines) + "\n"
