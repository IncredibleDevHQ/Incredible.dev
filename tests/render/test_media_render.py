"""Media skills rendering inside the sandbox image: charts, diagrams, pixel work, sound, thumbnails.

Each test runs in a fresh `design-agent-sandbox:local` container laid out like a staged sandbox: the
repository read-only at /repo, a scratch /workspace with the sample brand at /workspace/brand, our
skills at /workspace/skills and the gates at /workspace/tools (what the workspace stager uploads).

    docker build -t design-agent-sandbox:local sandbox/
    uv run pytest -q -m render tests/render/test_media_render.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
IMAGE = os.environ.get("DESIGN_AGENT_SANDBOX_IMAGE", "design-agent-sandbox:local")
SKILLS = (
    "image-ops",
    "gif-edit",
    "visual-verify",
    "film-breakdown",
    "data-viz",
    "stills",
    "thumbnails",
    "image-generation",
    "sound",
    "storyboard",
)
TOKENS = json.loads((ROOT / "examples/brands/example-studio/tokens.json").read_text())
PALETTE = {
    c.lower()
    for c in [*TOKENS["design"]["allowedColors"], *TOKENS["design"]["extendedPalette"]["colors"]]
}
SIGNAL = TOKENS["design"]["tokens"]["--brand-color-signal"]
STAGE = (
    "set -e\n"
    "mkdir -p /workspace/brand /workspace/skills /workspace/tools /workspace/projects/t\n"
    "cp -r /repo/examples/brands/example-studio/. /workspace/brand/\n"
    f"for s in {' '.join(SKILLS)}; do cp -r /repo/skills/$s /workspace/skills/; done\n"
    "cp -r /repo/workspace/tools/. /workspace/tools/\n"
    # The sample brand's fonts are staged, not baked, as the workspace stager does at run time.
    "mkdir -p /workspace/fonts && cp /repo/fonts/Geist-*.ttf /repo/fonts/FragmentMono-*.ttf /workspace/fonts/\n"
    "fc-cache -f >/dev/null 2>&1 || true\n"
    "cd /workspace\n"
    "set +e\n"
)
VIZ = "node skills/data-viz/scripts/viz.mjs"

pytestmark = pytest.mark.render

Sandbox = Callable[..., subprocess.CompletedProcess[str]]


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    docker = shutil.which("docker")
    assert docker, "docker is required for render tests"

    def run(script: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
        command = [
            docker,
            "run",
            "--rm",
            "-v",
            f"{ROOT}:/repo:ro",
            "-v",
            f"{tmp_path}:/workspace",
            IMAGE,
        ]
        return subprocess.run(
            [*command, "bash", "-c", STAGE + script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    return run


def _json_line(stdout: str) -> dict[str, object]:
    lines = [line for line in stdout.splitlines() if line.startswith("{")]
    assert lines, f"no JSON line in output:\n{stdout[-2000:]}"
    data = json.loads(lines[-1])
    assert isinstance(data, dict)
    return data


def _svg_colours(svg: str) -> set[str]:
    svg = re.sub(r"<(mask|clipPath)\b.*?</\1>", "", svg, flags=re.DOTALL)
    found = {c.lower() for c in re.findall(r'(?:fill|stroke)="(#[0-9a-fA-F]{6})"', svg)}
    found |= {c.lower() for c in re.findall(r"(?:fill|stroke)\s*:\s*(#[0-9a-fA-F]{6})", svg)}
    return found


def _share_near(path: Path, rgb: tuple[int, int, int], tolerance: int = 12) -> float:
    with Image.open(path) as image:
        pixels = list(image.convert("RGB").resize((400, 400)).getdata())
    near = sum(
        1 for p in pixels if all(abs(a - b) <= tolerance for a, b in zip(p, rgb, strict=True))
    )
    return near / len(pixels)


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ------------------------------------------------------------------------------------------ data-viz


def test_echarts_bar_renders_svg_and_png_in_brand_colours_only(
    sandbox: Sandbox, tmp_path: Path
) -> None:
    run = sandbox(
        f"{VIZ} --spec /repo/skills/data-viz/examples/bar-annotated.json "
        "--out projects/t/bar.png --svg-out projects/t/bar.svg"
    )
    assert run.returncode == 0, run.stderr
    receipt = _json_line(run.stdout)
    png_receipt = receipt["png"]
    assert isinstance(png_receipt, dict) and (png_receipt["width"], png_receipt["height"]) == (
        3200,
        1800,
    )
    assert all(gate["ok"] for gate in receipt["gates"])  # type: ignore[union-attr]
    svg = (tmp_path / "projects/t/bar.svg").read_text()
    colours = _svg_colours(svg)
    assert colours and colours <= PALETTE, f"off-palette: {colours - PALETTE}"
    assert SIGNAL in colours, "the highlighted bar carries the accent"
    for text in ("Minutes to finish one ad set", "34 min", "One HTML page per size", "Apr"):
        assert text in svg
    assert "Geist" in svg
    png = tmp_path / "projects/t/bar.png"
    with Image.open(png) as image:
        assert image.size == (3200, 1800)
    assert 0.002 < _share_near(png, _rgb(SIGNAL)) < 0.2, "one accent bar, not an accent frame"


def test_d2_diagram_renders_with_an_audited_topology(sandbox: Sandbox, tmp_path: Path) -> None:
    run = sandbox(
        f"{VIZ} --spec /repo/skills/data-viz/examples/diagram-flow.json "
        "--out projects/t/diagram.png --svg-out projects/t/diagram.svg"
    )
    assert run.returncode == 0, run.stderr
    topology = _json_line(run.stdout)["topology"]
    assert topology["ok"] and topology["nodeCount"] == 6 and topology["edgeCount"] == 6  # type: ignore[index]
    assert len(topology["topologyHash"]) == 64  # type: ignore[index, arg-type]
    svg = (tmp_path / "projects/t/diagram.svg").read_text()
    assert _svg_colours(svg) <= PALETTE, f"off-palette: {_svg_colours(svg) - PALETTE}"
    assert not re.search(r"font-family:\s*\"?d2-\d+-font", svg), (
        "D2's embedded faces are swapped for the brand family"
    )
    for label in (
        "Request in the thread",
        "One HTML page",
        "Look and fix",
        "In the sandbox",
        "fix",
    ):
        assert label in svg
    png = tmp_path / "projects/t/diagram.png"
    with Image.open(png) as image:
        assert image.size == (3200, 1800)
        low, high = image.convert("L").getextrema()
    assert low < 40 and high > 220
    assert _share_near(png, _rgb(SIGNAL)) > 0.001, "the highlighted node carries the accent"


def test_d2_topology_pin_fails_before_layout_when_meaning_moves(
    sandbox: Sandbox, tmp_path: Path
) -> None:
    spec = json.loads((ROOT / "skills/data-viz/examples/diagram-flow.json").read_text())
    spec["data"]["expectedTopologyHash"] = "0" * 64
    spec["out"] = "projects/t/pinned.png"
    (tmp_path / "pinned.json").write_text(json.dumps(spec))
    run = sandbox(f"{VIZ} --spec pinned.json")
    assert run.returncode == 1
    assert "topology changed" in run.stderr
    assert not (tmp_path / "projects/t/pinned.png").exists()


@pytest.mark.parametrize("example", ["flywheel-cycle", "stat-card"])
def test_square_examples_render(sandbox: Sandbox, tmp_path: Path, example: str) -> None:
    run = sandbox(
        f"{VIZ} --spec /repo/skills/data-viz/examples/{example}.json --out projects/t/{example}.png"
    )
    assert run.returncode == 0, run.stderr
    receipt = _json_line(run.stdout)
    assert set(receipt["audit"]["colours"]) <= PALETTE  # type: ignore[index]
    with Image.open(tmp_path / f"projects/t/{example}.png") as image:
        assert image.size == (2160, 2160)


def test_a_chart_that_misstates_its_data_writes_nothing(sandbox: Sandbox, tmp_path: Path) -> None:
    spec = {
        "kind": "bar",
        "out": "projects/t/bad.png",
        "data": {
            "dataset": {
                "fields": [{"name": "x", "type": "dimension"}, {"name": "v", "type": "measure"}],
                "rows": [{"x": "a", "v": 5}, {"x": "b", "v": 6}],
            },
            "x": "x",
            "y": "v",
            "valueAxis": {"min": 4},
        },
    }
    (tmp_path / "bad.json").write_text(json.dumps(spec))
    run = sandbox(f"{VIZ} --spec bad.json")
    assert run.returncode == 1
    assert "zeroBaseline" in run.stderr
    assert not (tmp_path / "projects/t/bad.png").exists()


# ----------------------------------------------------------------------------------------- image-ops


def test_image_ops_pipeline_resizes_crops_pads_and_composites(
    sandbox: Sandbox, tmp_path: Path
) -> None:
    img = "node skills/image-ops/scripts/img.mjs"
    run = sandbox(
        "set -e\n"
        "ffmpeg -nostdin -v error -f lavfi -i color=c=0x3d73b0:s=1200x800 -frames:v 1 -y in.png\n"
        f"{img} in.png step.png --resize 600x400:cover --crop 50,50,500,300 "
        "--extend 10,10,10,10:--brand-color-paper --composite /workspace/brand/logos/mark.svg@20,20\n"
        f"{img} step.png --info\n"
        f"{img} step.png small.webp --tint --brand-color-sky --resize 260x --to webp --quality 80\n"
        f"{img} small.webp --info\n"
    )
    assert run.returncode == 0, run.stderr
    results = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
    assert results[0]["width"] == 520 and results[0]["height"] == 320
    assert (
        results[1]["width"] == 520 and results[1]["height"] == 320 and results[1]["format"] == "png"
    )
    assert (
        results[3]["format"] == "webp"
        and results[3]["width"] == 260
        and results[3]["height"] == 160
    )
    with Image.open(tmp_path / "step.png") as image:
        rgb = image.convert("RGB")
        assert rgb.size == (520, 320)
        assert rgb.getpixel((2, 2)) == _rgb(TOKENS["design"]["tokens"]["--brand-color-paper"]), (
            "padded with the paper token"
        )
        assert sum(rgb.getpixel((24, 50))) < 150, "the mark's ink frame was composited at 20,20"


# ---------------------------------------------------------------------------------------------- sound


def _ebur128(stderr: str) -> tuple[float, float]:
    summary = stderr[stderr.rfind("Summary:") :]
    integrated = re.search(r"I:\s*(-?[\d.]+)\s*LUFS", summary)
    peak = re.search(r"True peak:\s*Peak:\s*(-?[\d.]+)\s*dBFS", summary)
    assert integrated and peak, summary
    return float(integrated.group(1)), float(peak.group(1))


def test_master_lands_a_three_second_tone_on_target(sandbox: Sandbox) -> None:
    run = sandbox(
        "ffmpeg -nostdin -v error -f lavfi -i sine=frequency=440:duration=3 -af volume=-20dB -y tone.wav\n"
        "node skills/sound/scripts/master.mjs tone.wav tone-master.wav || exit $?\n"
        "ffmpeg -nostdin -hide_banner -i tone-master.wav -af ebur128=peak=true -f null - 2>&1 | tail -16 >&2\n"
    )
    assert run.returncode == 0, run.stderr
    report = _json_line(run.stdout)
    assert report["ok"] is True
    assert abs(report["result"]["i"] - -14) <= 1  # type: ignore[index]
    integrated, true_peak = _ebur128(run.stderr)
    assert abs(integrated - -14) <= 1, integrated
    assert true_peak <= -1, true_peak


def test_score_pipeline_mixes_masters_and_passes_audio_lint(
    sandbox: Sandbox, tmp_path: Path
) -> None:
    plan = {
        "video": {"path": "projects/t/film-silent.mp4", "duration_s": 4, "fps": 25},
        "music": [
            {
                "act": "all",
                "start_s": 0,
                "end_s": 4,
                "selected": {"source": "supplied", "file": "music/bed.wav", "title": "tone"},
            }
        ],
        "sfx_cues": [
            {
                "t_start_s": 0.5,
                "dur_s": 0.2,
                "intent": "reveal",
                "description": "card",
                "gain": 1,
                "source": "synth",
                "recipe": "ui-confirm",
            },
            {
                "t_start_s": 2.0,
                "dur_s": 0.3,
                "intent": "transition",
                "description": "wipe",
                "gain": 0.8,
                "source": "synth",
                "recipe": "ui-swipe",
            },
        ],
        "vo": [],
    }
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    run = sandbox(
        "set -e\nmkdir -p projects/t/sound-assets/music && cp plan.json projects/t/plan.json\n"
        "ffmpeg -nostdin -v error -f lavfi -i color=c=gray:s=320x180:d=4:r=25 -c:v libx264 -pix_fmt yuv420p -y projects/t/film-silent.mp4\n"
        "ffmpeg -nostdin -v error -f lavfi -i sine=frequency=220:duration=3 -af apad=pad_dur=1 -y projects/t/sound-assets/music/bed.wav\n"
        "node skills/sound/scripts/score.mjs projects/t plan.json\n"
        "ffprobe -v error -show_entries stream=codec_type -of csv=p=0 projects/t/film-scored.mp4\n"
    )
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-2000:]
    assert "ok   2/2 audio-lint" in run.stdout
    assert run.stdout.strip().splitlines()[-2:] == ["video", "audio"]
    ledger = json.loads((tmp_path / "projects/t/sound-assets/ledger.json").read_text())
    assert {entry["source"] for entry in ledger} == {"supplied", "synth"}


def test_synthesized_cue_is_a_short_audible_wav(sandbox: Sandbox) -> None:
    run = sandbox(
        "set -e\nnode skills/sound/scripts/synth-cue.mjs ui-confirm cue.wav\n"
        "ffprobe -v error -show_entries stream=sample_rate,channels:format=duration -of json cue.wav\n"
        "ffmpeg -nostdin -hide_banner -i cue.wav -af volumedetect -f null - 2>&1 | grep max_volume >&2\n"
    )
    assert run.returncode == 0, run.stderr
    probe = json.loads(run.stdout[run.stdout.index("{", run.stdout.index("}") + 1) :])
    assert probe["streams"][0]["sample_rate"] == "44100" and probe["streams"][0]["channels"] == 1
    assert 0.15 < float(probe["format"]["duration"]) < 0.3
    peak = float(re.search(r"max_volume:\s*(-?[\d.]+) dB", run.stderr).group(1))  # type: ignore[union-attr]
    assert -10 < peak <= 0


# ----------------------------------------------------------------------------------------- thumbnails


def test_thumbnail_gate_passes_a_16x9_frame_and_fails_a_small_one(
    sandbox: Sandbox, tmp_path: Path
) -> None:
    gate = "node skills/thumbnails/scripts/thumb-gate.mjs"
    run = sandbox(
        "ffmpeg -nostdin -v error -f lavfi -i color=c=0x14161a:s=1280x720 -frames:v 1 -y projects/t/good.png\n"
        "ffmpeg -nostdin -v error -f lavfi -i color=c=0x14161a:s=1000x700 -frames:v 1 -y projects/t/bad.png\n"
        f"{gate} projects/t/good.png; echo GOOD=$?\n"
        f"{gate} projects/t/bad.png; echo BAD=$?\n"
        "node skills/thumbnails/scripts/small-size-gate.mjs projects/t/good.png; echo SHEET=$?\n"
    )
    assert "GOOD=0" in run.stdout, run.stdout + run.stderr
    assert "BAD=1" in run.stdout
    assert "✗ aspect" in run.stdout and "✗ width" in run.stdout
    assert "SHEET=0" in run.stdout
    with Image.open(tmp_path / "projects/t/good.smallsize-sheet.jpg") as sheet:
        assert sheet.width > 1000


# ------------------------------------------------------------------------------------- film-breakdown


def test_breakdown_finds_a_hard_cut_and_compare_matches_it(
    sandbox: Sandbox, tmp_path: Path
) -> None:
    run = sandbox(
        "set -e\n"
        "ffmpeg -nostdin -v error -f lavfi -i color=c=0x2f6b4f:s=640x360:d=2:r=25 -f lavfi -i color=c=0xf6f1e7:s=640x360:d=2:r=25 "
        "-filter_complex '[0:v][1:v]concat=n=2:v=1[v]' -map '[v]' -c:v libx264 -pix_fmt yuv420p -y projects/t/ref.mp4\n"
        "node skills/film-breakdown/scripts/breakdown.mjs projects/t/ref.mp4 projects/t/ref-out --no-audio > /dev/null\n"
        "node skills/film-breakdown/scripts/compare.mjs --ref projects/t/ref.mp4 --mine projects/t/ref.mp4 "
        "--out projects/t/compare --no-video --times 0.5,3.5 > /dev/null\n",
        timeout=600,
    )
    assert run.returncode == 0, run.stderr[-3000:]
    breakdown = json.loads((tmp_path / "projects/t/ref-out/breakdown.json").read_text())
    assert [round(c["t"], 2) for c in breakdown["cuts"]] == [2.0]
    compare = json.loads((tmp_path / "projects/t/compare/compare.json").read_text())
    assert compare["cuts"]["exact"] == 1 and compare["stillsSummary"]["meanSsim"] > 0.99
