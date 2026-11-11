"""The house's brands: the pack the process is configured with, and the packs read from websites
(`site_brand`), kept under `workspace/brands/<slug>/`. A channel can wear one: every thread in it
is staged with that pack (`brand_for`, the engine's per-thread manifest), and the Brand page shows
what each pack holds. A read runs as a job: its progress and its result reach the app live.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import shutil
import time
import tomllib
from pathlib import Path
from typing import Any

from design_agent.brand.schema import BrandPackError
from design_agent.config import SAMPLE_BRAND, Settings
from design_agent.surfaces.web.hub import Hub
from design_agent.surfaces.web.site_brand import (
    SiteBrandError,
    checked_url,
    read_site,
    slug_of,
    write_pack,
)
from design_agent.surfaces.web.store import Row, Store

_LOGGER = logging.getLogger(__name__)

#: The configured pack, by the name the app uses for it.
DEFAULT = "default"
#: A read's steps, in order: the capture says when it reaches colours, type and logo; the pack is
#: written here. What each is called while it runs, for a read that stops in it.
STEPS = ("open", "colours", "type", "logo", "pack")
WHILE = {
    "open": "opening the site",
    "colours": "taking its colours",
    "type": "finding its type",
    "logo": "finding its logo",
    "pack": "writing the brand pack",
}
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
#: Files of a pack the app may show: its marks and the site it was read from.
SHOWN = re.compile(r"^(?:logos|reference)/[\w.-]+\.(?:svg|png|jpe?g|webp)$")
#: Font files a pack names in fonts.toml, which the Brand page loads to set its specimens.
FONT_FILE = re.compile(r"^fonts/[\w.-]+\.(?:ttf|otf|woff2?)$")
#: The colour roles the Brand page leads with, in order, and the names a pack without a roles
#: table usually gives them.
ROLES = ("ground", "ink", "accent", "muted", "rule")
ROLE_NAMES = {
    "ground": ("ground", "paper", "background", "canvas", "white"),
    "ink": ("ink", "text", "foreground", "black"),
    "accent": ("accent", "signal", "primary", "brand"),
    "muted": ("muted", "graphite", "secondary", "slate", "grey", "gray"),
    "rule": ("rule", "line", "border", "mist", "quiet"),
}


class BrandShelf:
    def __init__(
        self, *, store: Store, hub: Hub, settings: Settings, project_root: Path, data_dir: Path
    ) -> None:
        self.store = store
        self.hub = hub
        self.project_root = project_root.resolve()
        workspace = (
            settings.workspace_root
            if settings.workspace_root.is_absolute()
            else project_root / settings.workspace_root
        )
        self.root = workspace / "brands"
        self.default = settings.resolved_brand_path(project_root)
        self.image = settings.sandbox_image
        self.captures = data_dir / "captures"
        self._reads: dict[str, asyncio.Task[None]] = {}
        #: What a running read is doing, by the address it reads.
        self.reading: dict[str, dict[str, Any]] = {}

    # -- the packs ------------------------------------------------------------------------------

    def path(self, slug: str) -> Path | None:
        if not slug or slug == DEFAULT:
            return self.default
        if not SLUG.match(slug):
            return None
        folder = self.root / slug
        return folder if (folder / "brand.toml").is_file() else None

    def brands(self) -> list[dict[str, Any]]:
        packs = [self.summary(DEFAULT)]
        if self.root.is_dir():
            for folder in sorted(self.root.iterdir()):
                if folder.name.startswith(".") or not (folder / "brand.toml").is_file():
                    continue
                packs.append(self.summary(folder.name))
        return packs

    def summary(self, slug: str) -> dict[str, Any]:
        folder = self.path(slug)
        if folder is None:
            raise KeyError(slug)
        view = brand_view(folder)
        source = _source(folder)
        logo = _mark(view["logos"])
        roles = {r["role"]: r["value"] for r in view["roles"]}
        return {
            "slug": slug,
            "name": view["name"],
            "colors": view["colors"][:8],
            "logo": self.file_url(slug, f"logos/{logo}") if logo else "",
            # The ground the mark sits on in the kit list: the pack's own, or ink for a
            # reversed mark.
            "ground": roles.get("ink", "#14161a") if _reversed(logo) else roles.get("ground", ""),
            "source": source.get("url", ""),
            "read": source.get("read", ""),
            "sample": view["sample"],
            "channels": [
                c["id"] for c in self.store.channels() if (c.get("brand") or DEFAULT) == slug
            ],
        }

    def view(self, slug: str) -> dict[str, Any]:
        folder = self.path(slug)
        if folder is None:
            raise KeyError(slug)
        view = brand_view(folder)
        source = _source(folder)
        reference = folder / "reference" / "site.jpg"
        return {
            **view,
            "slug": slug,
            "logos": [{"name": n, "url": self.file_url(slug, f"logos/{n}")} for n in view["logos"]],
            "source": source.get("url", ""),
            "read": source.get("read", ""),
            "reference": self.file_url(slug, "reference/site.jpg") if reference.is_file() else "",
            # Each face with a file the page can load, for specimens set in the pack's own type.
            "faces": [
                {**face, "url": self.file_url(slug, face["file"])}
                for face in view["faces"]
                if self._font(folder, face["file"]) is not None
            ],
            # The site's own face behind each open face that stands in for it.
            "stand_ins": {
                str(info.get("family")): str(info.get("site"))
                for info in (source.get("faces") or {}).values()
                if isinstance(info, dict) and info.get("stand_in")
            },
        }

    def file_url(self, slug: str, name: str) -> str:
        return f"/api/brands/{slug}/files/{name}"

    def file(self, slug: str, name: str) -> Path | None:
        folder = self.path(slug)
        if folder is None:
            return None
        if FONT_FILE.match(name):
            return self._font(folder, name)
        if not SHOWN.match(name):
            return None
        path = (folder / name).resolve()
        return path if path.is_file() and path.is_relative_to(folder.resolve()) else None

    def _font(self, folder: Path, name: str) -> Path | None:
        """A font file the pack's fonts.toml names: in the pack, else in the checkout's fonts."""
        if not FONT_FILE.match(name) or name not in _font_files(folder):
            return None
        for base in (folder.resolve(), self.project_root):
            path = (base / name).resolve()
            if path.is_file() and path.is_relative_to(base):
                return path
        return None

    # -- which brand a channel wears -------------------------------------------------------------

    def channel_brand(self, channel_id: str) -> str:
        channel = self.store.channel(channel_id)
        return str((channel or {}).get("brand") or "") or DEFAULT

    def wear(self, channel_id: str, slug: str) -> Row:
        if self.store.channel(channel_id) is None:
            raise KeyError(channel_id)
        if self.path(slug) is None:
            raise ValueError(f"There is no brand called {slug}.")
        channel = self.store.update_channel(channel_id, brand="" if slug == DEFAULT else slug)
        self.hub.publish("channel.created", channel=channel)
        return channel

    def brand_for(self, thread_id: str) -> Path | None:
        """The pack a thread's work wears: its channel's, or None for the configured one."""
        thread = self.store.thread(thread_id)
        slug = self.channel_brand(str(thread["channel_id"])) if thread else DEFAULT
        return None if slug == DEFAULT else self.path(slug)

    # -- reading a brand from a website ----------------------------------------------------------

    def read(self, url: str, *, by: str, channel_id: str = "") -> dict[str, Any]:
        """Start reading a site's brand; each step it reaches and then its result arrive as
        `brand.updated` events, and a channel named here wears the brand once it is made."""
        address = checked_url(url)
        if address in self._reads and not self._reads[address].done():
            return self.reading[address]
        status = {
            "url": address,
            "status": "reading",
            "step": STEPS[0],
            "by": by,
            "channel": channel_id,
            "started": time.time(),
        }
        self.reading[address] = status
        self._reads[address] = asyncio.get_running_loop().create_task(
            self._read(address, channel_id), name=f"brand read {address}"
        )
        self.hub.publish("brand.updated", read=status)
        return status

    async def _read(self, url: str, channel_id: str) -> None:
        status = self.reading[url]
        out = self.captures / f"{int(time.time())}-{re.sub(r'[^a-z0-9]+', '-', url.lower())[:60]}"

        def step(name: str) -> None:
            if name in STEPS and status.get("step") != name:
                status["step"] = name
                self.hub.publish("brand.updated", read=status)

        try:
            found = await read_site(url, out, image=self.image, on_step=step)
            slug = slug_of(found)
            step("pack")
            await asyncio.to_thread(write_pack, found, out, self.root / slug, self.project_root)
            status.update(status="ready", step="done", slug=slug, brand=self.summary(slug))
            if channel_id and self.store.channel(channel_id) is not None:
                self.wear(channel_id, slug)
                status["brand"] = self.summary(slug)
        except (SiteBrandError, BrandPackError) as error:
            status.update(status="failed", message=str(error).splitlines()[0][:300])
        except Exception:  # a read that breaks must say so, never hang
            _LOGGER.exception("brand read failed for %s", url)
            doing = WHILE.get(str(status.get("step")), "reading the site")
            status.update(
                status="failed",
                message=f"The read stopped while {doing}. The server's log has the details.",
            )
        finally:
            with contextlib.suppress(OSError):
                shutil.rmtree(out, ignore_errors=True)
            self._reads.pop(url, None)
            self.hub.publish("brand.updated", read=status)

    async def close(self) -> None:
        reads = list(self._reads.values())
        for task in reads:
            task.cancel()
        await asyncio.gather(*reads, return_exceptions=True)


def _source(folder: Path) -> dict[str, Any]:
    with contextlib.suppress(OSError, ValueError):
        found = json.loads((folder / ".source.json").read_text())
        return found if isinstance(found, dict) else {}
    return {}


def brand_view(root: Path) -> dict[str, Any]:
    tokens: dict[str, Any] = {}
    with contextlib.suppress(OSError, ValueError):
        tokens = json.loads((root / "tokens.json").read_text(encoding="utf-8"))
    brand: dict[str, Any] = {}
    with contextlib.suppress(OSError, ValueError):
        brand = tomllib.loads((root / "brand.toml").read_text(encoding="utf-8"))
    fonts: dict[str, Any] = {}
    with contextlib.suppress(OSError, ValueError):
        fonts = tomllib.loads((root / "fonts.toml").read_text(encoding="utf-8"))

    def text(name: str) -> str:
        with contextlib.suppress(OSError):
            return (root / name).read_text(encoding="utf-8")[:6_000]
        return ""

    logos = sorted(p.name for p in (root / "logos").glob("*") if p.is_file())
    raw_design = tokens.get("design")
    design: dict[str, Any] = raw_design if isinstance(raw_design, dict) else {}
    raw_named = design.get("tokens")
    named: dict[str, Any] = raw_named if isinstance(raw_named, dict) else {}
    colors = [
        {"name": key.removeprefix("--brand-color-"), "value": str(value)}
        for key, value in named.items()
        if key.startswith("--brand-color-")
    ]
    families: list[dict[str, Any]] = []
    for face in fonts.get("fonts") or []:
        if not isinstance(face, dict):
            continue
        family = str(face.get("family") or "")
        known = next((f for f in families if f["family"] == family), None)
        style = f"{face.get('style', 'normal')} {face.get('weight', '')}".strip()
        if known is None:
            families.append(
                {
                    "family": family,
                    "styles": [style],
                    "license": str(face.get("license") or ""),
                    "required": bool(face.get("required")),
                }
            )
        else:
            known["styles"].append(style)
            known["required"] = known["required"] or bool(face.get("required"))
    faces = [
        {
            "family": str(face.get("family") or ""),
            "style": str(face.get("style") or "normal"),
            "weight": str(face.get("weight") or "400"),
            "file": str(face["file"]),
        }
        for face in fonts.get("fonts") or []
        if isinstance(face, dict) and face.get("file")
    ]
    roles, palette, series = _roles(design, colors)
    raw_copy = tokens.get("copy")
    copy: dict[str, Any] = raw_copy if isinstance(raw_copy, dict) else {}
    raw_stacks = design.get("fontStacks")
    stacks: dict[str, Any] = raw_stacks if isinstance(raw_stacks, dict) else {}
    raw_about = brand.get("brand")
    about: dict[str, Any] = raw_about if isinstance(raw_about, dict) else brand
    return {
        "name": brand.get("name") or about.get("name") or root.name,
        "brand": brand,
        "tokens": tokens,
        "fonts": fonts,
        "colors": colors,
        "families": families,
        "logos": logos,
        "voice": text("voice.md"),
        "graphic_language": text("graphic-language.md"),
        "sample": root.name == SAMPLE_BRAND.name,
        # What the Brand page leads with: the brand in a line, its colours by role, how it sets
        # type, its shapes, the rules and words it keeps to, and the sizes it ships in.
        "description": str(about.get("description") or ""),
        "voice_line": str(about.get("voice") or ""),
        "license_note": str(about.get("license") or ""),
        "formats": [f for f in brand.get("formats") or [] if isinstance(f, dict)],
        "roles": roles,
        "palette": palette,
        "series": series,
        "faces": faces,
        "stacks": {
            role: [str(name) for name in names]
            for role, names in stacks.items()
            if role in ("display", "text", "mono") and isinstance(names, list)
        },
        "shape": _shape(named),
        "rules": [str(rule) for rule in design.get("rules") or [] if isinstance(rule, str)],
        "banned": [str(p) for p in copy.get("bannedPhrases") or [] if isinstance(p, str)],
    }


def _roles(
    design: dict[str, Any], colors: list[dict[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    """The colours by role (the pack's roles table, else by their names), the rest of the
    palette, and the series a chart uses."""
    values = {c["name"]: c["value"] for c in colors}
    raw = design.get("roles")
    table = raw if isinstance(raw, dict) else {}
    mode = table.get("light") if isinstance(table.get("light"), dict) else None
    if mode is None:
        mode = next((v for v in table.values() if isinstance(v, dict)), {})
    named = {
        role: str(token).removeprefix("--brand-color-")
        for role, token in mode.items()
        if isinstance(token, str)
    }
    chosen: dict[str, str] = {}
    for role in ROLES:
        if named.get(role) in values:
            chosen[role] = named[role]
            continue
        guess = next(
            (n for n in ROLE_NAMES[role] if n in values and n not in chosen.values()), None
        )
        if guess:
            chosen[role] = guess
    roles = [
        {"role": r, "name": chosen[r], "value": values[chosen[r]]} for r in ROLES if r in chosen
    ]
    palette = [c for c in colors if c["name"] not in chosen.values()]
    raw_series = mode.get("series")
    listed: list[Any] = raw_series if isinstance(raw_series, list) else []
    series = [values[n] for t in listed if (n := str(t).removeprefix("--brand-color-")) in values]
    if not series:
        accent = [values[chosen["accent"]]] if "accent" in chosen else []
        series = accent + [c["value"] for c in palette if _luminance(c["value"]) < 0.85][:3]
    return roles, palette, series


def _luminance(value: str) -> float:
    hexes = value.lstrip("#")
    if len(hexes) != 6:
        return 1.0
    try:
        r, g, b = (int(hexes[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return 1.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _shape(named: dict[str, Any]) -> dict[str, Any]:
    def get(key: str) -> str:
        value = named.get(f"--brand-{key}")
        return "" if value is None else str(value)

    return {
        "radius": [r for r in (get("radius-sm"), get("radius-md"), get("radius-lg")) if r],
        "pill": get("radius-pill"),
        "stroke": get("stroke"),
        "space": get("space-unit"),
        "weights": {
            k: get(f"weight-{k}") for k in ("display", "text", "strong") if get(f"weight-{k}")
        },
        "tracking": get("tracking-display"),
    }


def _reversed(name: str) -> bool:
    """A logo drawn for dark grounds."""
    return bool(re.search(r"reversed|white|on-dark|dark-bg", name))


def _mark(logos: list[str]) -> str:
    """The logo that stands for a pack in a list: its mark, else its lockup, for light grounds
    when there is one."""
    for prefix in ("mark", "lockup"):
        light = [n for n in logos if n.startswith(prefix) and not _reversed(n)]
        if light:
            return light[0]
    return next((n for n in logos if n.startswith(("mark", "lockup"))), "")


def _font_files(folder: Path) -> set[str]:
    with contextlib.suppress(OSError, ValueError):
        fonts = tomllib.loads((folder / "fonts.toml").read_text(encoding="utf-8"))
        return {
            str(face["file"])
            for face in fonts.get("fonts") or []
            if isinstance(face, dict) and face.get("file")
        }
    return set()
