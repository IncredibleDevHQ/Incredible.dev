"""The sandbox recipe pins every download and never bakes project content."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETUP = (ROOT / "sandbox/setup.sh").read_text()
DOCKERFILE = (ROOT / "sandbox/Dockerfile").read_text()


def test_embedded_render_lock_is_current() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/sync_sandbox_recipe.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_base_image_is_pinned_by_digest() -> None:
    assert re.search(
        r"^FROM node:22\.\d+\.\d+-bookworm-slim@sha256:[0-9a-f]{64}$", DOCKERFILE, re.M
    )


def test_no_floating_versions() -> None:
    assert "@latest" not in SETUP and "@latest" not in DOCKERFILE
    assert "npm install" not in SETUP, "npm ci from the embedded lockfile only"


def test_every_fetch_carries_a_checksum() -> None:
    for line in SETUP.splitlines():
        if line.strip().startswith("fetch ") and "() {" not in line:
            assert re.search(r'"\$\w*SHA256\w*"|\$sha"?$', line) or line.rstrip().endswith("\\"), (
                line
            )


def test_baked_fonts_match_the_repository_copies() -> None:
    entries = re.findall(r'"([\w.-]+\.ttf)\|([0-9a-f]{64})\|', SETUP)
    assert len(entries) == 9
    for name, sha in entries:
        assert hashlib.sha256((ROOT / "fonts" / name).read_bytes()).hexdigest() == sha, name


def test_manifest_and_recipe_agree_on_baked_fonts() -> None:
    from design_agent.workspace.manifest import BAKED_FONT_SHA256

    assert set(re.findall(r"\|([0-9a-f]{64})\|ofl/", SETUP)) == set(BAKED_FONT_SHA256)


def test_recipe_writes_no_project_files_or_secrets() -> None:
    for forbidden in ("COPY skills", "COPY workspace", ".env", "API_KEY", "private-fonts"):
        assert forbidden not in DOCKERFILE
    assert ".env" not in SETUP and "API_KEY" not in SETUP


def test_hyperframes_runs_through_the_quiet_wrapper() -> None:
    for variable in (
        "HYPERFRAMES_NO_TELEMETRY=1",
        "HYPERFRAMES_NO_UPDATE_CHECK=1",
        "HYPERFRAMES_SKIP_SKILLS=1",
    ):
        assert variable in SETUP
    assert '"hyperframes": "0.8.169"' in (ROOT / "sandbox/render/package.json").read_text()
