"""The offline demo through the real graph, the Docker sandbox and the real gates."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from design_agent.config import Settings
from design_agent.demo import run_demo
from design_agent.testing.demo_script import SIZES

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.render
async def test_demo_renders_three_sizes_and_a_teaser_that_pass_the_gates(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, sandbox="docker", workspace_root=tmp_path)  # type: ignore[call-arg]
    result = await run_demo(ROOT, settings)
    assert result.ok, result.problems
    assert [p.name for p in result.outputs] == [
        *(f"card-{w}x{h}.png" for w, h in SIZES),
        "teaser.mp4",
    ]
    for path, size in zip(result.outputs, SIZES, strict=False):
        with Image.open(path) as image:
            assert image.size == size
            # Paper ground with ink text: both extremes are present, so the frame is not blank.
            low, high = image.convert("L").getextrema()
            assert low < 40 and high > 220
