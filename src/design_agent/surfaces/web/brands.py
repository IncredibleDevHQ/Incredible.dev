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
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
#: Files of a pack the app may show: its marks and the site it was read from.
SHOWN = re.compile(r"^(?:logos|reference)/[\w.-]+\.(?:svg|png|jpe?g|webp)$")


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
        logo = next(
            (f"logos/{name}" for name in view["logos"] if name.startswith(("lockup", "mark"))),
            "",
        )
        return {
            "slug": slug,
            "name": view["name"],
            "colors": view["colors"][:8],
            "logo": self.file_url(slug, logo) if logo else "",
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
        if folder is None or not SHOWN.match(name):
            return None
        path = (folder / name).resolve()
        return path if path.is_file() and path.is_relative_to(folder.resolve()) else None

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
        """Start reading a site's brand; the result arrives as a `brand.updated` event, and a
        channel named here wears the brand once it is made."""
        address = checked_url(url)
        if address in self._reads and not self._reads[address].done():
            return self.reading[address]
        status = {"url": address, "status": "reading", "by": by, "started": time.time()}
        self.reading[address] = status
        self._reads[address] = asyncio.get_running_loop().create_task(
            self._read(address, channel_id), name=f"brand read {address}"
        )
        self.hub.publish("brand.updated", read=status)
        return status

    async def _read(self, url: str, channel_id: str) -> None:
        status = self.reading[url]
        out = self.captures / f"{int(time.time())}-{re.sub(r'[^a-z0-9]+', '-', url.lower())[:60]}"
        try:
            found = await read_site(url, out, image=self.image)
            slug = slug_of(found)
            await asyncio.to_thread(write_pack, found, out, self.root / slug, self.project_root)
            status.update(status="ready", slug=slug, brand=self.summary(slug))
            if channel_id and self.store.channel(channel_id) is not None:
                self.wear(channel_id, slug)
                status["brand"] = self.summary(slug)
        except (SiteBrandError, BrandPackError) as error:
            status.update(status="failed", message=str(error).splitlines()[0][:300])
        except Exception as error:  # a read that breaks must say so, never hang
            _LOGGER.exception("brand read failed for %s", url)
            status.update(status="failed", message=f"The read stopped: {type(error).__name__}.")
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
    return {
        "name": brand.get("name") or brand.get("brand", {}).get("name") or root.name,
        "brand": brand,
        "tokens": tokens,
        "fonts": fonts,
        "colors": colors,
        "families": families,
        "logos": logos,
        "voice": text("voice.md"),
        "graphic_language": text("graphic-language.md"),
        "sample": root.name == SAMPLE_BRAND.name,
    }
