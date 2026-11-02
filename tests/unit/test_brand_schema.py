"""Brand pack validation, failure listing and token CSS generation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from design_agent.brand.schema import BrandPackError, load_brand_pack, render_tokens_css

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "examples/brands/example-studio"


@pytest.fixture
def pack_copy(tmp_path: Path) -> Path:
    target = tmp_path / "brand"
    shutil.copytree(SAMPLE, target)
    return target


def test_sample_brand_is_valid_and_complete() -> None:
    pack = load_brand_pack(SAMPLE, project_root=ROOT)
    assert pack.brand.name == "Example Studio"
    assert pack.required_families() == ("Fragment Mono", "Geist")
    assert {f.slug for f in pack.brand.formats} >= {"linkedin-portrait", "square", "landscape"}
    assert pack.brand.license == "CC0-1.0"


def test_committed_tokens_css_is_current() -> None:
    pack = load_brand_pack(SAMPLE, project_root=ROOT)
    assert (SAMPLE / "tokens.css").read_text() == render_tokens_css(pack)


def test_tokens_css_carries_every_token_and_font_stack() -> None:
    css = render_tokens_css(load_brand_pack(SAMPLE, project_root=ROOT))
    assert "--brand-color-signal: #ff5a36;" in css
    assert '--brand-font-display: "Geist", system-ui, sans-serif;' in css
    assert "--brand-font-mono:" in css


def _mutate(path: Path, change) -> None:  # type: ignore[no-untyped-def]
    data = json.loads((path / "tokens.json").read_text())
    change(data)
    (path / "tokens.json").write_text(json.dumps(data))


def test_every_problem_is_listed_at_once(pack_copy: Path) -> None:
    (pack_copy / "voice.md").unlink()
    (pack_copy / "logos/mark.svg").unlink()
    _mutate(pack_copy, lambda d: d["design"].update(allowedColors=["#14161a", "not-a-color"]))
    with pytest.raises(BrandPackError) as caught:
        load_brand_pack(pack_copy, project_root=ROOT)
    joined = "\n".join(caught.value.problems)
    assert "voice.md: missing" in joined
    assert "logo logos/mark.svg: missing" in joined
    assert "allowedColors" in joined


def test_a_color_cannot_be_both_allowed_and_banned(pack_copy: Path) -> None:
    _mutate(pack_copy, lambda d: d["design"]["bannedColors"]["colors"].append("#FF5A36"))
    with pytest.raises(BrandPackError, match="both allowed and banned"):
        load_brand_pack(pack_copy, project_root=ROOT)


def test_tokens_must_use_palette_colors(pack_copy: Path) -> None:
    _mutate(pack_copy, lambda d: d["design"]["tokens"].update({"--brand-color-odd": "#123456"}))
    with pytest.raises(BrandPackError, match="not in the palette"):
        load_brand_pack(pack_copy, project_root=ROOT)


def test_colour_roles_name_tokens_that_hold_palette_colours(pack_copy: Path) -> None:
    roles = {"light": {"accent": "--brand-color-signal", "series": ["--brand-color-graphite"]}}
    _mutate(pack_copy, lambda d: d["design"].update(roles=roles))
    assert load_brand_pack(pack_copy, project_root=ROOT).tokens.design.roles["light"].accent
    _mutate(pack_copy, lambda d: d["design"]["roles"]["light"].update(muted="--brand-font-display"))
    with pytest.raises(BrandPackError, match=r"roles\.light\.muted"):
        load_brand_pack(pack_copy, project_root=ROOT)


def test_font_checksum_mismatch_fails(pack_copy: Path) -> None:
    fonts = (
        (pack_copy / "fonts.toml")
        .read_text()
        .replace("73894e0448cae90a92b6c2f8732b7bb9acb7b94c418bff559dad4a18e1de9659", "0" * 64)
    )
    (pack_copy / "fonts.toml").write_text(fonts)
    with pytest.raises(BrandPackError, match="sha256 does not match"):
        load_brand_pack(pack_copy, project_root=ROOT)


def test_missing_required_licensed_font_fails(pack_copy: Path) -> None:
    extra = (
        '\n[[fonts]]\nfamily = "Inter"\nweight = "700"\nfile = "private-fonts/Licensed-Bold.otf"\n'
        f'sha256 = "{"1" * 64}"\nrequired = true\nlicense = "commercial"\n'
    )
    (pack_copy / "fonts.toml").write_text((pack_copy / "fonts.toml").read_text() + extra)
    with pytest.raises(BrandPackError, match="private-fonts/Licensed-Bold.otf is missing"):
        load_brand_pack(pack_copy, project_root=ROOT)


def test_unknown_keys_are_rejected(pack_copy: Path) -> None:
    _mutate(pack_copy, lambda d: d["design"].update(sparkle=True))
    with pytest.raises(BrandPackError, match="sparkle"):
        load_brand_pack(pack_copy, project_root=ROOT)
