"""`install.sh`: clones the repository, installs its dependencies with uv, and never touches a key."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "install.sh"


def _run(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "uv"
    stub.write_text('#!/usr/bin/env bash\necho "$PWD $*" >> "$UV_LOG"\n')
    stub.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "UV_LOG": str(tmp_path / "uv.log"),
        "DESIGN_AGENT_REPO": f"file://{ROOT}",
        "DESIGN_AGENT_DIR": str(tmp_path / "design-agent"),
    }
    return subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=False, cwd=tmp_path
    )


def test_the_script_parses() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_it_clones_syncs_and_points_at_mda_deploy(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    target = tmp_path / "design-agent"
    assert (target / "agent.py").is_file()
    assert (tmp_path / "uv.log").read_text().split() == [str(target), "sync"]
    assert "uv run mda deploy" in result.stdout
    assert not (target / ".env").exists()
    again = _run(tmp_path)
    assert again.returncode == 0, again.stderr
    assert "Updating" in again.stdout


def test_it_refuses_a_folder_that_is_not_a_checkout(tmp_path: Path) -> None:
    (tmp_path / "design-agent").mkdir()
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "not a Design Agent checkout" in result.stderr
