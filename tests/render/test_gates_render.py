"""Gates that need the sandbox: Chrome Headless Shell, ffmpeg/ffprobe, sharp and the brand fonts.

Each test runs the tools inside the locally built sandbox image with the sandbox's own layout:
workspace/tools/ at /workspace/tools, the sample brand at /workspace/brand, the gate fixtures at
/workspace/fixtures (all read-only), and a scratch directory at /workspace/out.

    docker build -t design-agent-sandbox:local sandbox/
    uv run pytest -q -m render tests/render/test_gates_render.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGE = os.environ.get("DESIGN_AGENT_SANDBOX_IMAGE", "design-agent-sandbox:local")
DOCKER = shutil.which("docker")
SIZES = [(1080, 1350), (1080, 1080), (1600, 900)]
GSAP = "/opt/design-agent/render/node_modules/gsap/dist/gsap.min.js"


def _image_available() -> bool:
    if DOCKER is None:
        return False
    probe = subprocess.run([DOCKER, "image", "inspect", IMAGE], capture_output=True, check=False)
    return probe.returncode == 0


pytestmark = [
    pytest.mark.render,
    pytest.mark.skipif(
        not _image_available(), reason=f"docker or the {IMAGE} image is unavailable"
    ),
]

Sandbox = Callable[[str], subprocess.CompletedProcess[str]]


@pytest.fixture
def out(tmp_path: Path) -> Path:
    return tmp_path


def sandbox_in(out: Path) -> Sandbox:
    def run(script: str) -> subprocess.CompletedProcess[str]:
        assert DOCKER is not None
        mounts = [
            f"{ROOT / 'workspace' / 'tools'}:/workspace/tools:ro",
            f"{ROOT / 'examples' / 'brands' / 'example-studio'}:/workspace/brand:ro",
            # The sample brand's fonts are staged, not baked, as the workspace stager does.
            f"{ROOT / 'fonts'}:/workspace/fonts:ro",
            f"{ROOT / 'tests' / 'fixtures' / 'gates'}:/workspace/fixtures:ro",
            f"{out}:/workspace/out",
        ]
        return subprocess.run(
            [
                DOCKER,
                "run",
                "--rm",
                "--network=none",
                f"--user={os.getuid()}:{os.getgid()}",
                "--env=HOME=/tmp",
                "--workdir=/workspace",
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

    return run


@pytest.fixture
def sandbox(out: Path) -> Sandbox:
    return sandbox_in(out)


def last_json(proc: subprocess.CompletedProcess[str]) -> Any:
    return json.loads(proc.stdout.strip().splitlines()[-1])


# --- stills ----------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def three_sizes(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, subprocess.CompletedProcess[str]]:
    out = tmp_path_factory.mktemp("stills")
    sizes = " ".join(f"--size {w}x{h}" for w, h in SIZES)
    proc = sandbox_in(out)(
        f"node tools/html2png.mjs fixtures/brand/clean.html --out out --name clean {sizes} "
        '--require-font "Geist" --require-font "Fragment Mono" --brand-fonts'
    )
    return out, proc


def test_html2png_renders_each_size_with_brand_fonts(
    three_sizes: tuple[Path, subprocess.CompletedProcess[str]],
) -> None:
    from PIL import Image

    out, proc = three_sizes
    assert proc.returncode == 0, proc.stderr
    report = last_json(proc)
    assert report["ok"] is True
    assert report["fonts"] == {"Geist": True, "Fragment Mono": True}
    assert [(o["path"], o["width"], o["height"]) for o in report["outputs"]] == [
        (f"/workspace/out/clean-{w}x{h}.png", w, h) for w, h in SIZES
    ]
    for (w, h), entry in zip(SIZES, report["outputs"], strict=True):
        local = out / f"clean-{w}x{h}.png"
        assert local.stat().st_size == entry["bytes"] > 0
        with Image.open(local) as image:
            assert image.size == (w, h)
            colors = image.convert("RGB").getcolors(maxcolors=1 << 20) or []
            assert len(colors) > 50, "a render with almost no distinct colors drew nothing"


def test_html2png_recomposes_rather_than_scales(
    three_sizes: tuple[Path, subprocess.CompletedProcess[str]],
) -> None:
    from PIL import Image

    out, _ = three_sizes
    # The signal block sits top-right in portrait and fills the right side in landscape.
    with (
        Image.open(out / "clean-1080x1350.png") as portrait,
        Image.open(out / "clean-1600x900.png") as landscape,
    ):
        signal = (255, 90, 54)
        assert portrait.convert("RGB").getpixel((540, 700)) != signal
        assert landscape.convert("RGB").getpixel((1300, 700)) == signal


def test_rendered_stills_meet_the_artifact_contract(
    three_sizes: tuple[Path, subprocess.CompletedProcess[str]],
) -> None:
    out, _ = three_sizes
    expects = " ".join(f"--expect out/clean-{w}x{h}.png:{w}x{h}" for w, h in SIZES)
    proc = sandbox_in(out)(f"node tools/artifact-contract.mjs {expects} --json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert last_json(proc)["ok"] is True


def test_html2png_fails_when_a_required_font_is_missing(sandbox: Sandbox, out: Path) -> None:
    proc = sandbox(
        'node tools/html2png.mjs fixtures/brand/clean.html --out out --name x --size 1080x1080 --require-font "Nonexistent Sans"'
    )
    assert proc.returncode == 1, proc.stderr
    report = last_json(proc)
    assert report == {**report, "ok": False, "outputs": [], "fonts": {"Nonexistent Sans": False}}
    assert list(out.iterdir()) == []


def test_html2png_counts_a_web_font_under_its_css_family(sandbox: Sandbox, out: Path) -> None:
    """woff2 faces load only through @font-face, and CDP names them by the name inside the file
    (here "Inter"), not the CSS family the page asked for."""
    (out / "f").mkdir()
    shutil.copy(ROOT / "fonts" / "Inter-Variable.ttf", out / "f" / "probe.ttf")
    (out / "page.html").write_text(
        '<style>@font-face{font-family:"Probe Face";src:url("f/probe.woff2") format("woff2")}'
        'body{font-family:"Probe Face"}</style><body>Probe</body>'
    )
    proc = sandbox(
        "woff2_compress out/f/probe.ttf >/dev/null && "
        'node tools/html2png.mjs out/page.html --out out --name p --size 400x200 --require-font "Probe Face"'
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert last_json(proc)["fonts"] == {"Probe Face": True}


def test_html2png_writes_jpeg_and_webp(sandbox: Sandbox, out: Path) -> None:
    proc = sandbox(
        "node tools/html2png.mjs fixtures/brand/clean.html --out out --name j --size 1080x1080 --format jpeg && "
        "node tools/html2png.mjs fixtures/brand/clean.html --out out --name w --size 1080x1080 --format webp --scale 2 && "
        "node tools/artifact-contract.mjs --expect out/j-1080x1080.jpg:1080x1080 --expect out/w-1080x1080.webp:2160x2160"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_review_thumb_makes_a_contact_sheet(sandbox: Sandbox, out: Path) -> None:
    from PIL import Image

    sizes = " ".join(f"--size {w}x{h}" for w, h in SIZES)
    proc = sandbox(
        f"node tools/html2png.mjs fixtures/brand/clean.html --out out --name s {sizes} --scale 2 >/dev/null && "
        "node tools/review-thumb.mjs --sheet out/s-1080x1350.png out/s-1080x1080.png out/s-1600x900.png"
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == "/workspace/out/review-sheet.jpg"
    with Image.open(out / "review-sheet.jpg") as sheet:
        assert max(sheet.size) <= 1600


def test_a_contact_sheet_takes_the_frames_shape(sandbox: Sandbox, out: Path) -> None:
    """Four 16:9 frames make a wide 2x2 sheet, not four letterboxed squares."""
    from PIL import Image

    proc = sandbox(
        "node tools/html2png.mjs fixtures/brand/clean.html --out out --name w --size 1600x900 >/dev/null && "
        "node tools/review-thumb.mjs --sheet out/w-1600x900.png out/w-1600x900.png "
        "out/w-1600x900.png out/w-1600x900.png"
    )
    assert proc.returncode == 0, proc.stderr
    with Image.open(out / "review-sheet.jpg") as sheet:
        width, height = sheet.size
    assert width == 1600 and height < 1000, sheet.size


# --- PDF and copy ----------------------------------------------------------------------------------


def test_html2pdf_writes_an_audited_pdf(sandbox: Sandbox, out: Path) -> None:
    proc = sandbox(
        "node tools/html2pdf.mjs --html fixtures/brand/clean.html --out out/clean.pdf --size 8.5x11in --brand-fonts && "
        "node tools/text-fidelity.mjs out/clean.pdf --json"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "__HTML2PDF_OK__" in proc.stdout
    assert (out / "clean.pdf").read_bytes()[:5] == b"%PDF-"
    audit = last_json(proc)
    assert audit["ok"] is True
    assert audit["runsJudged"] >= 1


def test_html2pdf_refuses_a_missing_font(sandbox: Sandbox, out: Path) -> None:
    proc = sandbox(
        'node tools/html2pdf.mjs --html fixtures/brand/clean.html --out out/x.pdf --require-font "Nonexistent Sans"'
    )
    assert proc.returncode == 1
    assert "did not resolve" in proc.stderr
    assert not (out / "x.pdf").exists()


@pytest.mark.parametrize(
    ("page", "code", "problem"),
    [("brand/clean.html", 0, None), ("text/transformed.html", 1, "casing")],
)
def test_text_fidelity_compares_rendered_copy(
    sandbox: Sandbox, page: str, code: int, problem: str | None
) -> None:
    proc = sandbox(
        f"node tools/text-fidelity.mjs --html fixtures/{page} --expect fixtures/text/clean-copy.txt --size 1080x1350 --json"
    )
    assert proc.returncode == code, proc.stderr
    report = last_json(proc)
    if problem:
        assert {p["problem"] for p in report["problems"]} >= {problem}
        assert {
            "line": "Field notes, issue 3",
            "problem": "casing",
            "rendered": "FIELD NOTES, ISSUE 3",
        } in report["problems"]


# --- film ------------------------------------------------------------------------------------------


def film_script(name: str, command: str) -> str:
    return f"cp fixtures/video/{name}.html {GSAP} out/ && {command}"


def test_film_probe_records_a_model_the_analysis_passes(sandbox: Sandbox, out: Path) -> None:
    proc = sandbox(
        film_script(
            "clean",
            "node tools/film-probe.mjs out/clean.html --out out/model.json && node tools/film-analysis.mjs out/model.json --json",
        )
    )
    assert proc.returncode == 0, proc.stderr
    model = json.loads((out / "model.json").read_text())
    assert model["duration"] == 3
    assert model["stage"] == {"w": 1920, "h": 1080}
    assert model["timeline"]["paused"] is True
    assert min(f["ink"] for f in model["frames"]) > 0.00145
    assert last_json(proc)["errors"] == 0


@pytest.mark.parametrize(("name", "code"), [("clean", 0), ("blank-gap", 1)])
def test_video_score_gates_the_rendered_film(sandbox: Sandbox, name: str, code: int) -> None:
    proc = sandbox(film_script(name, f"node tools/video-score.mjs out/{name}.html --json"))
    assert proc.returncode == code, proc.stderr
    report = last_json(proc)
    assert report["measured"] is True
    assert report["pass"] is (code == 0)
    errors = {f["code"] for f in report["film"]["findings"] if f["sev"] == "ERROR"}
    assert ("frames.blank" in errors) is (name == "blank-gap")


def test_film_probe_without_a_timeline_cannot_run(sandbox: Sandbox) -> None:
    proc = sandbox("node tools/film-probe.mjs fixtures/brand/clean.html")
    assert proc.returncode == 2
    assert "no GSAP timeline" in proc.stderr


# --- video and audio files -------------------------------------------------------------------------

TESTSRC = "ffmpeg -v error -f lavfi -i testsrc=size=1280x720:rate=30 -t 2 -pix_fmt yuv420p out/testsrc.mp4"
BLACK = "ffmpeg -v error -f lavfi -i color=c=black:size=1280x720:rate=30 -t 2 -pix_fmt yuv420p out/black.mp4"


def test_artifact_contract_measures_a_video(sandbox: Sandbox) -> None:
    proc = sandbox(
        f"{TESTSRC} && node tools/artifact-contract.mjs --expect out/testsrc.mp4:1280x720@2 --json"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    (entry,) = last_json(proc)["outputs"]
    assert (entry["width"], entry["height"], entry["codec"]) == (1280, 720, "h264")
    assert abs(entry["duration"] - 2) <= 1 / 30
    assert entry["firstFrameInk"] > 0.00145 and entry["lastFrameInk"] > 0.00145


@pytest.mark.parametrize(
    ("make", "spec", "problems"),
    [
        (
            BLACK,
            "out/black.mp4:1280x720@2",
            ["its first frame is blank", "its last frame is blank"],
        ),
        (TESTSRC, "out/testsrc.mp4:1920x1080@2", ["is 1280x720, expected 1920x1080"]),
        (TESTSRC, "out/testsrc.mp4:1280x720@3", ["runs 2s, expected 3s"]),
    ],
)
def test_artifact_contract_fails_a_wrong_video(
    sandbox: Sandbox, make: str, spec: str, problems: list[str]
) -> None:
    proc = sandbox(f"{make} && node tools/artifact-contract.mjs --expect {spec} --json")
    assert proc.returncode == 1, proc.stderr
    (entry,) = last_json(proc)["outputs"]
    for problem in problems:
        assert any(p.startswith(problem) for p in entry["problems"]), entry["problems"]


def test_artifact_contract_allows_declared_blank_ends(sandbox: Sandbox) -> None:
    proc = sandbox(
        f"{BLACK} && node tools/artifact-contract.mjs --expect out/black.mp4:1280x720@2 --allow-blank-ends"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


TONE = "ffmpeg -v error -f lavfi -i sine=frequency=440:duration=5 -af loudnorm=I=-14:TP=-2:LRA=7 -ar 48000 out/tone.wav"


def test_audio_lint_passes_a_mastered_tone(sandbox: Sandbox) -> None:
    proc = sandbox(f"{TONE} && node tools/audio-lint.mjs out/tone.wav --expect-duration 5 --json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = last_json(proc)
    assert abs(report["lufs"] + 14) <= 1
    assert report["truePeak"] <= -1


@pytest.mark.parametrize(
    ("make", "args", "finding"),
    [
        (
            "ffmpeg -v error -f lavfi -i sine=frequency=440:duration=5 -af volume=-30dB -ar 48000 out/a.wav",
            "out/a.wav",
            "integrated loudness",
        ),
        (
            "ffmpeg -v error -f lavfi -i sine=frequency=440:duration=5 -af volume=20dB -ar 48000 out/a.wav",
            "out/a.wav",
            "true peak",
        ),
        (
            TONE.replace("out/tone.wav", "out/a.wav"),
            "out/a.wav --expect-duration 6",
            "audio runs 5",
        ),
        (TESTSRC.replace("out/testsrc.mp4", "out/a.mp4"), "out/a.mp4", "no audio stream"),
    ],
)
def test_audio_lint_fails_out_of_range_audio(
    sandbox: Sandbox, make: str, args: str, finding: str
) -> None:
    proc = sandbox(f"{make} && node tools/audio-lint.mjs {args} --json")
    assert proc.returncode == 1, proc.stderr
    assert any(f.startswith(finding) for f in last_json(proc)["findings"])
