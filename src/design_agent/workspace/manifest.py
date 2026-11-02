"""What the stager puts into a sandbox's /workspace, with sha256 for every file.

Generated from the checkout on each process start (and by `scripts/build_manifest.py` for
inspection); never hand-edited. Sources are confined to an allowlist of roots, symlinks that leave
the tree are refused, and nothing named `.env*` is ever read.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from design_agent.brand.schema import BrandPack, render_tokens_css

WORKSPACE = PurePosixPath("/workspace")
#: Where a deployed project keeps skills' binary files: MDA syncs `skills/` to Context Hub, which
#: takes only UTF-8 text (`deploy.stage` moves them here).
SKILL_BINARIES = "skill-binaries"
#: Fonts the sandbox recipe bakes, by sha256, so the stager never uploads them again.
BAKED_FONT_SHA256 = frozenset(
    {
        "29160a80ff49ddcab2c97711247e08b1fab27a484a329ce8b813d820dc559031",
        "acd98e64795781b2058f07b18475e0ecee2a0fe2b42a49e2f9e37d0d6bf66ce6",
        "6a3412f058c7d8dfd9170c41e85ade48e5156ecb89356110ca57a0a27734af46",
        "a9b4c49bb299e05b5f6c481e7fb5e78943d2793249a0c8874ab574a2d1ea6755",
        "d3c38e55c78f5b0f28009fddba4834ec503278936a5986032424c9bd2d23aa46",
        "ac27abd6450a64dd94467580a02fe6235156d5b92f2926ebbc8e7489df64e0be",
        "9335b082b3c7850d98a64b584f3417f65355f3471278bb5eeb8c6c0e8657aeeb",
        "177ff6c0f14e5550a3c624247cd1189611d4eb65d000b14944c63d967958abbb",
        "b24448c43702fac4ee856781d461a0dfba8d8e594b6e8e190234b75fed2c0e01",
    }
)
SKIPPED_NAMES = frozenset({".DS_Store", "__pycache__", "node_modules", ".git"})


class ManifestError(ValueError):
    """A source the stager refuses to read. The message names the path, never its content."""


@dataclass(frozen=True)
class Asset:
    source: Path
    destination: PurePosixPath
    sha256: str
    size: int


@dataclass(frozen=True)
class Manifest:
    assets: tuple[Asset, ...]
    required_families: tuple[str, ...]
    generated: tuple[tuple[PurePosixPath, bytes], ...] = ()
    """Files produced in memory (the brand's tokens.css when the pack ships none)."""

    @property
    def digest(self) -> str:
        """One hash over every destination, checksum and required family."""
        lines = [f"{a.destination}\t{a.sha256}" for a in self.assets]
        lines += [f"{p}\t{hashlib.sha256(c).hexdigest()}" for p, c in self.generated]
        lines += [f"font\t{f}" for f in self.required_families]
        return hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()

    def to_json(self) -> str:
        return json.dumps(
            {
                "digest": self.digest,
                "required_families": list(self.required_families),
                "files": [
                    {"destination": str(a.destination), "sha256": a.sha256, "bytes": a.size}
                    for a in self.assets
                ],
                "generated": [str(p) for p, _ in self.generated],
            },
            indent=2,
        )

    def checklist(self) -> bytes:
        """`sha256sum -c` input for every staged file."""
        rows = [(a.destination, a.sha256) for a in self.assets]
        rows += [(p, hashlib.sha256(c).hexdigest()) for p, c in self.generated]
        return "".join(f"{sha}  {dest}\n" for dest, sha in sorted(rows)).encode()

    def archive(self) -> bytes:
        """A deterministic gzipped tar relative to /workspace, parent directories first.

        Explicit directory members make tar replace a planted directory symlink instead of
        writing through it; fixed modes and mtimes make one manifest produce one set of bytes.
        """
        members: list[tuple[str, bytes]] = [
            (str(a.destination.relative_to(WORKSPACE)), a.source.read_bytes()) for a in self.assets
        ]
        members += [(str(p.relative_to(WORKSPACE)), c) for p, c in self.generated]
        members.sort()
        directories: set[str] = set()
        for name, _ in members:
            parts = name.split("/")[:-1]
            directories.update("/".join(parts[:depth]) for depth in range(1, len(parts) + 1))
        buffer = io.BytesIO()
        with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=6, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for directory in sorted(directories):
                    entry = tarfile.TarInfo(f"{directory}/")
                    entry.type, entry.mode, entry.mtime = tarfile.DIRTYPE, 0o755, 0
                    tar.addfile(entry)
                for name, content in members:
                    entry = tarfile.TarInfo(name)
                    entry.size, entry.mode, entry.mtime = len(content), 0o644, 0
                    tar.addfile(entry, io.BytesIO(content))
        return buffer.getvalue()


def _files(root: Path, base: Path) -> Iterator[Path]:
    for path in sorted(base.rglob("*")):
        if any(part in SKIPPED_NAMES for part in path.relative_to(base).parts):
            continue
        if path.name.startswith(".env"):
            raise ManifestError(f"refusing to stage an environment file: {path.relative_to(root)}")
        if path.is_symlink() and not path.resolve().is_relative_to(root.resolve()):
            raise ManifestError(f"symlink leaves the checkout: {path.relative_to(root)}")
        if path.is_file():
            yield path


def _asset(source: Path, destination: PurePosixPath) -> Asset:
    data = source.read_bytes()
    return Asset(source, destination, hashlib.sha256(data).hexdigest(), len(data))


def build_manifest(project_root: Path, brand: BrandPack) -> Manifest:
    """Skills, workspace gates, the active brand pack and its non-baked fonts."""
    root = project_root.resolve()
    assets: list[Asset] = []
    skills = root / "skills"
    if skills.is_dir():
        for skill in sorted(
            p for p in skills.iterdir() if p.is_dir() and p.name not in SKIPPED_NAMES
        ):
            for path in _files(root, skill):
                rel = path.relative_to(skill).as_posix()
                assets.append(_asset(path, WORKSPACE / "skills" / skill.name / rel))
    # Skills' binary files live here, because Context Hub takes only UTF-8 text (skills_lock).
    binaries = root / SKILL_BINARIES
    if binaries.is_dir():
        for path in _files(root, binaries):
            assets.append(
                _asset(path, WORKSPACE / "skills" / path.relative_to(binaries).as_posix())
            )
    tools = root / "workspace" / "tools"
    if tools.is_dir():
        for path in _files(root, tools):
            assets.append(_asset(path, WORKSPACE / "tools" / path.relative_to(tools).as_posix()))
    brand_root = brand.root.resolve()
    for path in _files(brand_root, brand_root):
        assets.append(_asset(path, WORKSPACE / "brand" / path.relative_to(brand_root).as_posix()))
    generated: list[tuple[PurePosixPath, bytes]] = []
    if not (brand_root / "tokens.css").is_file():
        generated.append((WORKSPACE / "brand" / "tokens.css", render_tokens_css(brand).encode()))
    seen_fonts: set[str] = set()
    for font in brand.fonts.fonts:
        source = (root / font.file).resolve()
        if not source.is_relative_to(root):
            raise ManifestError(f"brand font leaves the checkout: {font.file}")
        if not source.is_file():
            if font.required:
                raise ManifestError(f"required brand font is missing: {font.file}")
            continue
        asset = _asset(source, WORKSPACE / "fonts" / source.name)
        if asset.sha256 != font.sha256:
            raise ManifestError(f"brand font does not match fonts.toml: {font.file}")
        if asset.sha256 in BAKED_FONT_SHA256 or asset.sha256 in seen_fonts:
            continue
        seen_fonts.add(asset.sha256)
        assets.append(asset)
    destinations = [a.destination for a in assets] + [p for p, _ in generated]
    if len(destinations) != len(set(destinations)):
        raise ManifestError("two sources stage to the same destination")
    return Manifest(
        assets=tuple(assets),
        required_families=brand.required_families(),
        generated=tuple(generated),
    )
