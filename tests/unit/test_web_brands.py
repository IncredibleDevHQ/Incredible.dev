"""Brands from websites: a site's read becomes a brand pack the engine validates, a channel wears
it (every thread in it staged with that pack), and the shelf reads brands as jobs."""

from __future__ import annotations

import asyncio
import json
import shutil
import tomllib
from pathlib import Path
from typing import Any

import pytest

from design_agent.brand.schema import load_brand_pack
from design_agent.config import Settings, project_root
from design_agent.surfaces.web import brands as brands_module
from design_agent.surfaces.web.brands import DEFAULT, BrandShelf
from design_agent.surfaces.web.hub import Hub
from design_agent.surfaces.web.site_brand import (
    SiteBrandError,
    checked_url,
    name_of,
    slug_of,
    write_pack,
)
from design_agent.surfaces.web.store import Store
from design_agent.workspace.manifest import ManifestBook, build_manifest

ROOT = project_root()
FIXTURE = Path(__file__).parent / "fixtures" / "site-brand"


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A checkout with the repo's open fonts and the sample brand, where packs can be written."""
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "fonts", root / "fonts")
    shutil.copytree(
        ROOT / "examples" / "brands" / "example-studio",
        root / "examples" / "brands" / "example-studio",
    )
    shutil.copytree(ROOT / "skills" / "canvas", root / "skills" / "canvas")
    return root


def _found() -> dict[str, Any]:
    found: dict[str, Any] = json.loads((FIXTURE / "capture.json").read_text())
    return found


def test_addresses_are_checked_before_a_read() -> None:
    assert checked_url("docs.perplexity.ai") == "https://docs.perplexity.ai"
    assert checked_url(" https://example.com/x ") == "https://example.com/x"
    for bad in ("ftp://example.com", "localhost", "https://"):
        with pytest.raises(SiteBrandError):
            checked_url(bad)


def test_a_sites_read_becomes_a_valid_pack(checkout: Path) -> None:
    found = _found()
    assert (slug_of(found), name_of(found)) == ("perplexity", "Perplexity")
    pack = write_pack(found, FIXTURE, checkout / "workspace" / "brands" / "perplexity", checkout)

    design = pack.tokens.design
    assert design.tokens["--brand-color-ground"] == "#f7f7f8"
    assert design.tokens["--brand-color-ink"] == "#121516"
    assert design.tokens["--brand-color-accent"] == "#1a6872"
    assert "#ffffff" in design.allowed_colors
    assert "#00bc7d" not in design.palette()  # a badge's colour is not a brand colour
    assert "#000000" in design.banned_colors.colors
    assert design.replacement_colors["#000000"] == "--brand-color-ink"
    assert set(design.roles) == {"light"}
    assert (
        design.font_stacks.display[0] == "Inter" and design.font_stacks.mono[0] == "IBM Plex Mono"
    )
    assert pack.required_families() == ("IBM Plex Mono", "Inter")
    assert all(f.file.startswith("fonts/") for f in pack.fonts.fonts)
    assert design.tokens["--brand-radius-pill"] == "999px"
    assert int(design.tokens["--brand-radius-lg"].removesuffix("px")) < 40

    folder = pack.root
    assert [logo.file for logo in pack.brand.logos] == ["logos/lockup.svg", "logos/mark.png"]
    assert (
        "GT Standard, which it licenses for its own pages; renders use Inter"
        in (folder / "graphic-language.md").read_text()
    )
    assert "“Get Started”" in pack.brand.voice and "Ctrl" not in pack.brand.voice
    assert (folder / "reference" / "site.jpg").is_file()
    assert pack.tokens.copy_rules.casing_rules.headlines == "title"


def test_a_new_read_replaces_the_pack_in_place(checkout: Path) -> None:
    target = checkout / "workspace" / "brands" / "perplexity"
    write_pack(_found(), FIXTURE, target, checkout)
    (target / "stale.txt").write_text("from the last read")
    again = _found()
    again["roles"] = {**again["roles"], "accent": "#35BDC8"}
    pack = write_pack(again, FIXTURE, target, checkout)
    assert pack.tokens.design.tokens["--brand-color-accent"] == "#35bdc8"
    assert not (target / "stale.txt").exists()
    assert sorted(p.name for p in target.parent.iterdir()) == ["perplexity"]


def test_each_thread_is_staged_with_its_channels_pack(checkout: Path) -> None:
    pack = write_pack(_found(), FIXTURE, checkout / "workspace" / "brands" / "perplexity", checkout)
    sample = load_brand_pack(
        checkout / "examples" / "brands" / "example-studio", project_root=checkout
    )
    default = build_manifest(checkout, sample)
    worn = {"th_lily": pack.root}
    book = ManifestBook(checkout, default, lambda thread: worn.get(thread))

    assert book.for_thread("th_other") is default
    staged = book.for_thread("th_lily")
    assert staged is not default and staged is book.for_thread("th_lily")
    brand_files = {
        str(a.destination) for a in staged.assets if "/workspace/brand/" in str(a.destination)
    }
    assert (
        "/workspace/brand/brand.toml" in brand_files
        and "/workspace/brand/logos/lockup.svg" in brand_files
    )
    assert staged.required_families == ("IBM Plex Mono", "Inter")

    (pack.root / "voice.md").write_text("# Perplexity voice\n\nPlain.\n")
    assert book.for_thread("th_lily").digest != staged.digest  # a changed pack stages again
    (pack.root / "tokens.json").write_text("{}")
    assert book.for_thread("th_lily") is default  # a pack that no longer loads is never staged


async def test_a_channel_wears_a_brand_read_from_a_website(
    checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path / "house.sqlite")
    hub = Hub()
    seen: list[dict[str, Any]] = []
    hub.publish = lambda kind, **data: seen.append({"type": kind, **data})  # type: ignore[method-assign]
    settings = Settings(workspace_root=checkout / "workspace")
    shelf = BrandShelf(
        store=store, hub=hub, settings=settings, project_root=checkout, data_dir=tmp_path
    )
    channel = store.add_channel("lily", "Lily, the Metal inference engine")
    thread = store.add_thread(
        thread_id="th_1",
        channel_id=channel["id"],
        task=True,
        title="Research",
        kind="research",
        by="you",
    )

    async def fake_read(url: str, out: Path, *, image: str, timeout: float = 0) -> dict[str, Any]:
        assert url == "https://docs.perplexity.ai" and image == settings.sandbox_image
        shutil.copytree(FIXTURE, out, dirs_exist_ok=True)
        return _found()

    monkeypatch.setattr(brands_module, "read_site", fake_read)
    status = shelf.read("docs.perplexity.ai", by="you", channel_id=channel["id"])
    assert status["status"] == "reading"
    await asyncio.gather(*list(shelf._reads.values()))

    assert status["status"] == "ready" and status["slug"] == "perplexity"
    assert [e["read"]["status"] for e in seen if e["type"] == "brand.updated"] == ["ready", "ready"]
    assert shelf.channel_brand(channel["id"]) == "perplexity"
    assert shelf.brand_for(thread["id"]) == checkout / "workspace" / "brands" / "perplexity"
    assert [b["slug"] for b in shelf.brands()] == [DEFAULT, "perplexity"]
    assert shelf.summary("perplexity")["channels"] == [channel["id"]]
    assert (
        shelf.view("perplexity")["reference"] == "/api/brands/perplexity/files/reference/site.jpg"
    )
    assert shelf.file("perplexity", "logos/lockup.svg") is not None
    for refused in ("brand.toml", "logos/../brand.toml", "fonts.toml"):
        assert shelf.file("perplexity", refused) is None

    shelf.wear(channel["id"], DEFAULT)
    assert shelf.brand_for(thread["id"]) is None
    with pytest.raises(ValueError):
        shelf.wear(channel["id"], "nobody")


async def test_a_read_that_cannot_make_a_brand_says_why(
    checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path / "house.sqlite")
    settings = Settings(workspace_root=checkout / "workspace")
    shelf = BrandShelf(
        store=store, hub=Hub(), settings=settings, project_root=checkout, data_dir=tmp_path
    )

    async def blocked(url: str, out: Path, *, image: str, timeout: float = 0) -> dict[str, Any]:
        raise SiteBrandError("The site answered with a human check or a block (HTTP 403).")

    monkeypatch.setattr(brands_module, "read_site", blocked)
    status = shelf.read("https://www.perplexity.ai", by="you")
    await asyncio.gather(*list(shelf._reads.values()))
    assert status["status"] == "failed" and "human check" in status["message"]
    assert [b["slug"] for b in shelf.brands()] == [DEFAULT]


def test_fonts_toml_names_files_where_the_pack_lives(checkout: Path) -> None:
    found = _found()
    found["fonts"] = {**found["fonts"], "display": "Inter", "body": "Inter", "mono": "Fira Code"}
    pack = write_pack(found, FIXTURE, checkout / "workspace" / "brands" / "perplexity", checkout)
    fonts = tomllib.loads((pack.root / "fonts.toml").read_text())["fonts"]
    assert {f["family"] for f in fonts} == {"Inter", "Fira Code"}
    assert "stands in" not in (pack.root / "graphic-language.md").read_text()
