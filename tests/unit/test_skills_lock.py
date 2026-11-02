"""Vendored upstream skills match their lock, and no repo tooling rewrites them."""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from design_agent.skills_lock import is_text, load_lock, locked_files, vendored_folders, verify

ROOT = Path(__file__).resolve().parents[2]


def test_vendored_skills_match_the_lock() -> None:
    result = verify(ROOT)
    assert result.ok, result


def test_git_tracks_every_locked_file() -> None:
    """Upstream skills ship their own `.gitignore`s, which can hide a locked file from `git add`."""
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("not a Git checkout")
    listed = subprocess.run(
        [git, "-C", str(ROOT), "ls-files", "skills", "skill-binaries", ".agents/skills"],
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = set(listed.stdout.splitlines())
    untracked = [
        path
        for folder, entry in vendored_folders(load_lock(ROOT))
        for path in locked_files(folder, entry)
        if path not in tracked
    ]
    assert not untracked, f"git add -f these: {untracked}"


def test_lint_skips_exactly_the_vendored_skills() -> None:
    excluded = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["ruff"][
        "extend-exclude"
    ]
    vendored = {folder for folder, _ in vendored_folders(load_lock(ROOT))}
    assert {path for path in excluded if path.startswith(("skills/", ".agents/"))} == vendored


def test_runtime_skills_are_utf8_text() -> None:
    """MDA syncs `skills/` to Context Hub, which refuses anything else, so a plain `mda deploy`
    fails on one binary file. Binary skill files live in `skill-binaries/<skill>/`."""
    binary = [
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "skills").rglob("*"))
        if path.is_file() and not is_text(path)
    ]
    assert not binary, f"move these to skill-binaries/: {binary}"


def test_binary_skill_files_reach_the_sandbox_beside_their_skill() -> None:
    from design_agent.brand.schema import load_brand_pack
    from design_agent.workspace.manifest import build_manifest

    fonts = sorted((ROOT / "skill-binaries").rglob("*.woff2"))
    assert fonts, "the vendored frame-preset fonts live in skill-binaries/"
    pack = load_brand_pack(ROOT / "examples/brands/example-studio", project_root=ROOT)
    staged = {str(asset.destination) for asset in build_manifest(ROOT, pack).assets}
    for font in fonts:
        assert f"/workspace/skills/{font.relative_to(ROOT / 'skill-binaries').as_posix()}" in staged
