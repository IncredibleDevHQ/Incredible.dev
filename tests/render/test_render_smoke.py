"""Render smoke (SPEC §20.2): the sandbox image can do the media work, end to end.

HyperFrames at the pinned version lints, checks, snapshots and renders a 2 s 1920x1080 film whose
duration ffprobe measures within one frame, with non-blank first and last frames; D2 draws a
diagram. Runs in the locally built sandbox image, offline.

    uv run design-agent sandbox build
    uv run pytest -q -m render tests/render/test_render_smoke.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.render.test_gates_render import DOCKER, GSAP, IMAGE, ROOT, _image_available, last_json

pytestmark = [
    pytest.mark.render,
    pytest.mark.skipif(
        not _image_available(), reason=f"docker or the {IMAGE} image is unavailable"
    ),
]

FIXTURES = ROOT / "tests" / "fixtures" / "render"


def run(work: Path, script: str) -> subprocess.CompletedProcess[str]:
    assert DOCKER is not None
    mounts = [
        f"{ROOT / 'workspace' / 'tools'}:/workspace/tools:ro",
        f"{work}:/workspace/out",
    ]
    return subprocess.run(
        [
            DOCKER,
            "run",
            "--rm",
            "--network=none",
            f"--user={os.getuid()}:{os.getgid()}",
            "--env=HOME=/tmp",
            "--workdir=/workspace/out",
            *[arg for mount in mounts for arg in ("--volume", mount)],
            IMAGE,
            "bash",
            "-c",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


@pytest.fixture(scope="module")
def film(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, subprocess.CompletedProcess[str]]:
    work = tmp_path_factory.mktemp("film")
    shutil.copytree(FIXTURES / "film", work / "film")
    proc = run(
        work,
        f"set -e; cp {GSAP} film/ "
        "&& hyperframes lint film && hyperframes check film "
        "&& hyperframes snapshot film --at 1.0 "
        "&& hyperframes render film --quality draft --fps 30 --output film.mp4 --quiet "
        "&& node /workspace/tools/artifact-contract.mjs --root /workspace/out "
        "--expect film.mp4:1920x1080@2 --json",
    )
    return work, proc


def test_hyperframes_lints_checks_snapshots_and_renders(
    film: tuple[Path, subprocess.CompletedProcess[str]],
) -> None:
    work, proc = film
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert "0 errors" in proc.stdout and "Check passed" in proc.stdout
    snapshots = list((work / "film").rglob("*.png"))
    assert snapshots, "snapshot --at 1.0 wrote a frame"


def test_the_render_is_two_seconds_at_1080p_with_live_first_and_last_frames(
    film: tuple[Path, subprocess.CompletedProcess[str]],
) -> None:
    _, proc = film
    result = last_json(proc)
    assert result["ok"] is True, result


def test_d2_draws_a_diagram(tmp_path: Path) -> None:
    shutil.copy(FIXTURES / "flow.d2", tmp_path / "flow.d2")
    proc = run(tmp_path, "d2 --layout=dagre flow.d2 flow.svg && grep -c '<svg' flow.svg")
    assert proc.returncode == 0, proc.stderr[-2000:]
    svg = (tmp_path / "flow.svg").read_text()
    assert "Storyboard" in svg
