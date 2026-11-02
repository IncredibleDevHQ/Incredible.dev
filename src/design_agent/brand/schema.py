"""The brand pack contract: `brand.toml`, `tokens.json` and `fonts.toml`, validated on load.

A broken pack fails loudly with every problem listed, in `doctor`, in `brand validate` and before a
deploy. Gates (`workspace/tools/brand-lint.mjs`) read the same `tokens.json`; renderers read font
stacks and CSS custom properties from the generated `tokens.css`, never a hard-coded family.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
TOKEN = re.compile(r"^--brand-[a-z0-9]+(?:-[a-z0-9]+)*$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

HexColor = Annotated[str, Field(pattern=HEX.pattern)]
CssToken = Annotated[str, Field(pattern=TOKEN.pattern)]


def normalize_hex(value: str) -> str:
    """`#ABC` -> `#aabbcc`."""
    raw = value.lower()
    if len(raw) == 4:
        return "#" + "".join(c * 2 for c in raw[1:])
    return raw


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class NotedColors(_Strict):
    note: str = Field(default="", alias="_note")
    colors: tuple[HexColor, ...] = ()


class OfficialAssetColors(NotedColors):
    assets: Mapping[str, tuple[HexColor, ...]] = Field(default_factory=dict)
    """Logo file -> the colors that appear only inside that official artwork."""


class FontStacks(_Strict):
    display: tuple[str, ...] = Field(min_length=2)
    text: tuple[str, ...] = Field(min_length=2)
    mono: tuple[str, ...] = Field(min_length=2)

    @field_validator("display", "text", "mono")
    @classmethod
    def _generic_fallback_last(cls, stack: tuple[str, ...]) -> tuple[str, ...]:
        generic = {"serif", "sans-serif", "monospace", "system-ui", "ui-monospace", "ui-sans-serif"}
        if stack[-1] not in generic:
            raise ValueError(f"font stack {list(stack)} must end with a generic family")
        return stack

    def css(self, role: Literal["display", "text", "mono"]) -> str:
        families = getattr(self, role)
        return ", ".join(f'"{f}"' if " " in f or f[0].isupper() else f for f in families)


class CreativeTypography(_Strict):
    mono_letter_spacing: str = Field(default="0", alias="monoLetterSpacing")
    allow_mono_uppercase_transform: bool = Field(default=False, alias="allowMonoUppercaseTransform")
    banned_decorative_chars: tuple[str, ...] = Field(default=("•",), alias="bannedDecorativeChars")
    banned_decorative_marker_classes: tuple[str, ...] = Field(
        default=("bullet", "dot", "tick", "marker"), alias="bannedDecorativeMarkerClasses"
    )
    banned_generic_motif_classes: tuple[str, ...] = Field(
        default=("dot-grid", "dot-field", "node-cloud", "node-network", "network-lattice"),
        alias="bannedGenericMotifClasses",
    )
    allowed_all_caps_terms: tuple[str, ...] = Field(default=(), alias="allowedAllCapsTerms")
    canonical_casing: Mapping[str, str] = Field(default_factory=dict, alias="canonicalCasing")


class DiagramConstruction(_Strict):
    note: str = Field(default="", alias="_note")
    base_grid_unit_px: int = Field(default=8, ge=1, alias="baseGridUnitPx")
    stroke_to_grid_ratio: float = Field(default=0.25, gt=0, le=1, alias="strokeToGridRatio")
    stroke_tokens: tuple[CssToken, ...] = Field(default=("--brand-stroke",), alias="strokeTokens")
    connector_elements: tuple[str, ...] = Field(
        default=("path", "line", "polyline"), alias="connectorElements"
    )
    max_arrowhead_markers: int = Field(default=1, ge=0, alias="maxArrowheadMarkers")


class ColorRoles(_Strict):
    """The colours a brand assigns to each role in one mode, as tokens. Renderers prefer these over
    what they would measure from the palette; a role left out is still measured."""

    note: str = Field(default="", alias="_note")
    ground: CssToken | None = None
    ink: CssToken | None = None
    accent: CssToken | None = None
    muted: CssToken | None = None
    """Secondary text."""
    quiet: CssToken | None = None
    """De-emphasised marks: the bars that are not the point."""
    rule: CssToken | None = None
    """Grid lines and dividers."""
    series: tuple[CssToken, ...] = ()
    """Categorical colours, in the order a chart uses them."""

    def named(self) -> list[tuple[str, CssToken]]:
        single = [
            (role, token)
            for role in ("ground", "ink", "accent", "muted", "quiet", "rule")
            if (token := getattr(self, role)) is not None
        ]
        return single + [(f"series[{i}]", token) for i, token in enumerate(self.series)]


class DesignTokens(_Strict):
    allowed_colors: tuple[HexColor, ...] = Field(min_length=2, alias="allowedColors")
    extended_palette: NotedColors = Field(default_factory=NotedColors, alias="extendedPalette")
    official_asset_colors: OfficialAssetColors = Field(
        default_factory=OfficialAssetColors, alias="officialAssetColors"
    )
    banned_colors: NotedColors = Field(default_factory=NotedColors, alias="bannedColors")
    replacement_colors: Mapping[HexColor, CssToken] = Field(
        default_factory=dict, alias="replacementColors"
    )
    """Off-brand color -> the token a fix should use instead."""
    allowed_font_tokens: tuple[str, ...] = Field(min_length=1, alias="allowedFontTokens")
    known_off_brand_fonts: tuple[str, ...] = Field(default=(), alias="knownOffBrandFonts")
    font_stacks: FontStacks = Field(alias="fontStacks")
    max_rect_radius_px: int = Field(ge=0, le=999, alias="maxRectRadiusPx")
    creative_typography: CreativeTypography = Field(
        default_factory=CreativeTypography, alias="creativeTypography"
    )
    diagram_construction: DiagramConstruction = Field(
        default_factory=DiagramConstruction, alias="diagramConstruction"
    )
    tokens: Mapping[CssToken, str] = Field(min_length=1)
    """CSS custom properties written to tokens.css. Colors must come from the palette."""
    roles: Mapping[Literal["light", "dark"], ColorRoles] = Field(default_factory=dict)
    """Optional colour roles per mode (charts and diagrams); see `ColorRoles`."""
    rules: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> DesignTokens:
        palette = self.palette()
        banned = {normalize_hex(c) for c in self.banned_colors.colors}
        if overlap := sorted(palette & banned):
            raise ValueError(f"colors both allowed and banned: {overlap}")
        for name, value in self.tokens.items():
            if HEX.match(value.strip()) and normalize_hex(value.strip()) not in palette:
                raise ValueError(f"token {name} uses {value}, which is not in the palette")
        for color, token in self.replacement_colors.items():
            if token not in self.tokens:
                raise ValueError(f"replacement for {color} names unknown token {token}")
        for token in self.diagram_construction.stroke_tokens:
            if token not in self.tokens:
                raise ValueError(f"diagram stroke token {token} is not defined in tokens")
        for mode, roles in self.roles.items():
            for role, token in roles.named():
                value = self.tokens.get(token, "").strip()
                if not HEX.match(value) or normalize_hex(value) not in palette:
                    raise ValueError(
                        f"roles.{mode}.{role}: {token} must be a token holding a palette colour"
                    )
        return self

    def palette(self) -> frozenset[str]:
        """Every color generated creative may use (core palette plus extended)."""
        return frozenset(
            normalize_hex(c) for c in (*self.allowed_colors, *self.extended_palette.colors)
        )


class CasingRules(_Strict):
    headlines: Literal["sentence", "title", "any"] = "sentence"
    canonical: Mapping[str, str] = Field(default_factory=dict)
    """Lowercased term -> its one correct spelling (product and brand names)."""


class CopyRules(_Strict):
    note: str = Field(default="", alias="_note")
    banned_phrases: tuple[str, ...] = Field(default=(), alias="bannedPhrases")
    warn_phrases: tuple[str, ...] = Field(default=(), alias="warnPhrases")
    banned_chars: Mapping[str, str] = Field(default_factory=dict, alias="bannedChars")
    max_hashtags: int = Field(default=3, ge=0, alias="maxHashtags")
    casing_rules: CasingRules = Field(default_factory=CasingRules, alias="casingRules")
    rules: tuple[str, ...] = ()


class TokensFile(_Strict):
    comment: str = Field(default="", alias="_comment")
    version: Literal["1"]
    design: DesignTokens
    copy_rules: CopyRules = Field(alias="copy")


class FontFile(_Strict):
    family: str = Field(min_length=1)
    weight: str = Field(pattern=r"^\d{3}(?: \d{3})?$")
    """A weight (`400`) or a variable range (`100 900`)."""
    style: Literal["normal", "italic"] = "normal"
    file: str = Field(min_length=1)
    """Path relative to the repository root: `fonts/...` (open) or `private-fonts/...` (licensed)."""
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    required: bool = True
    license: str = Field(min_length=1)


class FontsFile(_Strict):
    fonts: tuple[FontFile, ...] = Field(min_length=1)


class FormatSpec(_Strict):
    slug: str = Field(pattern=SLUG.pattern)
    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)
    label: str = ""


class BrandFiles(_Strict):
    tokens: str = "tokens.json"
    fonts: str = "fonts.toml"
    voice: str = "voice.md"
    graphic_language: str = "graphic-language.md"
    logos: str = "logos"


class Logo(_Strict):
    file: str
    use: str = ""
    """Where this mark goes (light grounds, dark grounds, small sizes)."""
    min_width_px: int = Field(default=24, ge=1)
    clear_space: str = ""


class BrandToml(_Strict):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=400)
    voice: str = Field(min_length=1, max_length=600)
    """A one-paragraph voice summary; the full guide is voice.md."""
    license: str = Field(min_length=1)
    formats: tuple[FormatSpec, ...] = Field(min_length=1)
    #: Empty until the brand supplies files: the agent then asks for a logo instead of drawing one.
    logos: tuple[Logo, ...] = ()
    files: BrandFiles = Field(default_factory=BrandFiles)


class BrandPackError(ValueError):
    """Every problem with a brand pack, one per line."""

    def __init__(self, root: Path, problems: list[str]) -> None:
        self.root = root
        self.problems = problems
        super().__init__(f"brand pack {root} is invalid:\n" + "\n".join(f"- {p}" for p in problems))


class BrandPack(BaseModel):
    """A loaded, validated brand pack. Paths are absolute."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    root: Path
    brand: BrandToml
    tokens: TokensFile
    fonts: FontsFile

    @property
    def tokens_path(self) -> Path:
        return self.root / self.brand.files.tokens

    def font_path(self, font: FontFile, project_root: Path) -> Path:
        return project_root / font.file

    def required_families(self) -> tuple[str, ...]:
        return tuple(sorted({f.family for f in self.fonts.fonts if f.required}))


def _errors(error: ValidationError, label: str) -> list[str]:
    return [
        f"{label}: {'.'.join(str(p) for p in item['loc']) or '(root)'}: {item['msg']}"
        for item in error.errors()
    ]


def load_brand_pack(
    root: Path, *, project_root: Path | None = None, check_fonts: bool = True
) -> BrandPack:
    """Load and validate a pack. Raises BrandPackError listing every problem found."""
    problems: list[str] = []
    brand = tokens = fonts = None
    try:
        brand = BrandToml.model_validate(tomllib.loads((root / "brand.toml").read_text()))
    except FileNotFoundError:
        problems.append("brand.toml: missing")
    except (tomllib.TOMLDecodeError, ValidationError) as error:
        problems += (
            _errors(error, "brand.toml")
            if isinstance(error, ValidationError)
            else [f"brand.toml: {error}"]
        )
    files = brand.files if brand else BrandFiles()
    try:
        tokens = TokensFile.model_validate(json.loads((root / files.tokens).read_text()))
    except FileNotFoundError:
        problems.append(f"{files.tokens}: missing")
    except (json.JSONDecodeError, ValidationError) as error:
        problems += (
            _errors(error, files.tokens)
            if isinstance(error, ValidationError)
            else [f"{files.tokens}: {error}"]
        )
    try:
        fonts = FontsFile.model_validate(tomllib.loads((root / files.fonts).read_text()))
    except FileNotFoundError:
        problems.append(f"{files.fonts}: missing")
    except (tomllib.TOMLDecodeError, ValidationError) as error:
        problems += (
            _errors(error, files.fonts)
            if isinstance(error, ValidationError)
            else [f"{files.fonts}: {error}"]
        )
    for name in (files.voice, files.graphic_language):
        if not (root / name).is_file():
            problems.append(f"{name}: missing")
    if brand:
        for logo in brand.logos:
            if not (root / logo.file).is_file():
                problems.append(f"logo {logo.file}: missing")
    if tokens and fonts:
        stacked = {
            f
            for role in ("display", "text", "mono")
            for f in getattr(tokens.design.font_stacks, role)
        }
        for font in fonts.fonts:
            if font.required and font.family not in stacked:
                problems.append(f"fonts.toml: required family {font.family!r} is in no font stack")
    if fonts and check_fonts:
        base = project_root or root
        for font in fonts.fonts:
            path = base / font.file
            if not path.is_file():
                if font.required:
                    problems.append(f"fonts.toml: {font.file} is missing (required)")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != font.sha256:
                problems.append(f"fonts.toml: {font.file} sha256 does not match")
    if problems or brand is None or tokens is None or fonts is None:
        raise BrandPackError(root, problems)
    return BrandPack(root=root, brand=brand, tokens=tokens, fonts=fonts)


#: Formats Chrome reads only through @font-face, never as installed system fonts.
WEB_FONT_FORMATS = {".woff2": "woff2", ".woff": "woff"}


def render_tokens_css(pack: BrandPack) -> str:
    """tokens.css: an @font-face rule for each web-format brand font (staged in /workspace/fonts/),
    then every token plus the three font-stack variables, sorted, under `:root`."""
    design = pack.tokens.design
    values = dict(design.tokens)
    for role in ("display", "text", "mono"):
        values.setdefault(f"--brand-font-{role}", design.font_stacks.css(role))
    body = "\n".join(f"  {name}: {values[name]};" for name in sorted(values))
    faces = [
        "@font-face {\n"
        f"  font-family: {json.dumps(font.family)};\n"
        f"  font-weight: {font.weight};\n"
        f"  font-style: {font.style};\n"
        f'  src: url("/workspace/fonts/{PurePosixPath(font.file).name}") format("{kind}");\n'
        "}\n"
        for font in pack.fonts.fonts
        if (kind := WEB_FONT_FORMATS.get(PurePosixPath(font.file).suffix.lower()))
    ]
    return (
        f"/* Generated from {pack.brand.files.tokens} by `design-agent brand css`. Do not edit. */\n"
        + "".join(faces)
        + f":root {{\n{body}\n}}\n"
    )
