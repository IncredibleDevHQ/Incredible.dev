"""The workspace gates (workspace/tools/*.mjs) that run on plain Node, against the sample brand.

Browser, ffmpeg and sharp paths run in the sandbox image (tests/render/test_gates_render.py). Here
every gate is held to the shared exit-code contract: 0 pass, 1 findings, 2 the check could not run.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import zlib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "workspace" / "tools"
FIXTURES = ROOT / "tests" / "fixtures" / "gates"
TOKENS = ROOT / "examples" / "brands" / "example-studio" / "tokens.json"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH")


def run(
    tool: str, *args: str | Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    assert NODE is not None
    return subprocess.run(
        [NODE, str(TOOLS / tool), *map(str, args)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )


def node_eval(script: str) -> Any:
    """Evaluate an ES module snippet and parse the JSON it prints."""
    assert NODE is not None
    out = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(out.stdout)


def lint(
    target: str, *extra: str | Path, root: Path = FIXTURES, tokens: Path = TOKENS
) -> tuple[int, dict[str, Any]]:
    proc = run("brand-lint.mjs", "--root", root, "--tokens", tokens, "--json", *extra, target)
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def rules(report: dict[str, Any]) -> set[str]:
    return {f["rule"] for f in report["findings"]}


# --- every tool ------------------------------------------------------------------------------------


@pytest.mark.parametrize("tool", sorted(p.name for p in TOOLS.glob("*.mjs")))
def test_tool_parses(tool: str) -> None:
    assert NODE is not None
    proc = subprocess.run(
        [NODE, "--check", str(TOOLS / tool)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    "tool",
    [
        "brand-lint.mjs",
        "video-gate.mjs",
        "audio-lint.mjs",
        "film-probe.mjs",
        "film-analysis.mjs",
        "video-score.mjs",
        "review-thumb.mjs",
    ],
)
def test_missing_target_is_a_tooling_failure(tool: str, tmp_path: Path) -> None:
    proc = run(tool, "--root", tmp_path, "nope.html")
    assert proc.returncode == 2, (proc.stdout, proc.stderr)


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("html2png.mjs", ["missing.html", "--out", "out", "--size", "1080x1080"]),
        ("html2pdf.mjs", ["--html", "missing.html", "--out", "out/x.pdf"]),
        ("text-fidelity.mjs", ["missing.pdf"]),
        ("text-fidelity.mjs", ["--html", "missing.html", "--expect", "missing.txt"]),
        ("artifact-contract.mjs", ["--contract", "missing.json"]),
    ],
)
def test_missing_input_is_a_tooling_failure(tool: str, args: list[str]) -> None:
    assert run(tool, *args).returncode == 2


@pytest.mark.parametrize(
    "tool", ["brand-lint.mjs", "video-gate.mjs", "html2png.mjs", "artifact-contract.mjs"]
)
def test_unknown_flag_is_a_tooling_failure(tool: str) -> None:
    assert run(tool, "--definitely-not-a-flag", "x").returncode == 2


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("html2png.mjs", [FIXTURES / "brand/clean.html", "--out", "{tmp}", "--size", "1080x1080"]),
        ("html2pdf.mjs", ["--html", FIXTURES / "brand/clean.html", "--out", "{tmp}/x.pdf"]),
        (
            "text-fidelity.mjs",
            ["--html", FIXTURES / "brand/clean.html", "--expect", FIXTURES / "text/clean-copy.txt"],
        ),
        ("film-probe.mjs", ["--root", FIXTURES, "video/clean.html"]),
        ("video-score.mjs", ["--root", FIXTURES, "--tokens", TOKENS, "video/clean.html"]),
    ],
)
def test_missing_render_toolchain_is_never_a_pass(
    tool: str, args: list[Any], tmp_path: Path
) -> None:
    env = {"PATH": "/usr/bin:/bin", "DESIGN_AGENT_RENDER_DIR": str(tmp_path / "no-toolchain")}
    proc = run(tool, *[str(a).replace("{tmp}", str(tmp_path / "out")) for a in args], env=env)
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "not installed" in proc.stderr
    assert not (tmp_path / "out").exists()


# --- brand-lint ------------------------------------------------------------------------------------


def test_brand_lint_clean_still_passes() -> None:
    code, report = lint("brand/clean.html")
    assert code == 0
    assert report == {**report, "ok": True, "errors": 0, "warnings": 0, "findings": []}


def test_brand_lint_text_report_names_the_file() -> None:
    proc = run("brand-lint.mjs", "--root", FIXTURES, "--tokens", TOKENS, "brand/fail/radius.html")
    assert proc.returncode == 1
    assert "brand/fail/radius.html:8  [ERROR] border-radius 24px" in proc.stdout


@pytest.mark.parametrize(
    ("fixture", "rule"),
    [
        ("off-palette", "color.off-palette"),
        ("banned-color", "color.banned"),
        ("off-brand-font", "font.off-brand"),
        ("font-lead", "font.lead"),
        ("mono-lead", "font.mono-lead"),
        ("radius", "radius.max"),
        ("decorative-bullet", "type.decorative-bullet"),
        ("motif", "motif.generic"),
        ("all-caps", "case.all-caps"),
        ("contrast", "contrast.wcag"),
        ("canonical", "case.canonical"),
        ("banned-copy", "copy.banned-phrase"),
        ("pixel-grid", "grid.fractional"),
        ("diagram-stroke", "diagram.stroke-width"),
    ],
)
def test_brand_lint_flags_each_rule(fixture: str, rule: str) -> None:
    code, report = lint(f"brand/fail/{fixture}.html")
    assert code == 1
    assert report["ok"] is False
    assert rule in rules(report)
    assert all(f["severity"] in {"ERROR", "WARN"} and f["line"] > 0 for f in report["findings"])


def test_brand_lint_banned_color_names_its_replacement_token() -> None:
    _, report = lint("brand/fail/banned-color.html")
    (finding,) = [f for f in report["findings"] if f["rule"] == "color.banned"]
    assert "var(--brand-color-ink)" in finding["message"]
    assert "#14161a" in finding["message"]


def test_brand_lint_suggests_sentence_case_for_shouted_copy() -> None:
    _, report = lint("brand/fail/all-caps.html")
    assert any('"Technical guide"' in f["message"] for f in report["findings"])


def test_brand_lint_mono_lead_comes_from_the_brand_stack() -> None:
    _, report = lint("brand/fail/mono-lead.html")
    (finding,) = [f for f in report["findings"] if f["rule"] == "font.mono-lead"]
    assert '"Fragment Mono"' in finding["message"]
    assert "var(--brand-font-mono)" in finding["message"]


@pytest.mark.parametrize(
    ("fixture", "rule", "count"),
    [
        ("banned-phrase", "copy.banned-phrase", 1),
        ("hashtags", "copy.hashtags", 1),
        ("canonical", "case.canonical", 2),
    ],
)
def test_brand_lint_copy_mode(fixture: str, rule: str, count: int) -> None:
    code, report = lint(f"copy/{fixture}.txt", "--copy")
    assert code == 1
    assert report["mode"] == "copy"
    assert [f["rule"] for f in report["findings"]].count(rule) == count


def test_brand_lint_clean_copy_passes() -> None:
    code, report = lint("copy/clean-post.txt", "--copy")
    assert (code, report["findings"]) == (0, [])


def test_brand_lint_reads_every_fact_from_the_tokens(tmp_path: Path) -> None:
    tokens = json.loads(TOKENS.read_text())
    tokens["design"]["bannedColors"]["colors"].remove("#000000")
    del tokens["design"]["replacementColors"]["#000000"]
    tokens["design"]["allowedColors"].append("#000000")
    tokens["design"]["fontStacks"]["mono"] = ["Fira Code", "Fragment Mono", "monospace"]
    tokens["copy"]["casingRules"]["headlines"] = "any"
    other = tmp_path / "tokens.json"
    other.write_text(json.dumps(tokens))
    for fixture in ("banned-color", "mono-lead", "all-caps"):
        code, report = lint(f"brand/fail/{fixture}.html", tokens=other)
        assert (code, report["findings"]) == (0, []), fixture


def test_brand_lint_lints_linked_stylesheets_in_their_own_file(tmp_path: Path) -> None:
    (tmp_path / "base.css").write_text(".a { margin: 0; }\n.b { color: #ff0000; }\n")
    (tmp_path / "page.html").write_text(
        '<!doctype html>\n<html>\n<head>\n<link rel="stylesheet" href="base.css">\n</head>\n'
        "<body><p>Quarterly review</p></body>\n</html>\n"
    )
    code, report = lint("page.html", root=tmp_path)
    assert code == 1
    (finding,) = report["findings"]
    assert (finding["rule"], finding["file"], finding["line"]) == ("color.banned", "base.css", 2)
    assert "var(--brand-color-signal)" in finding["message"]


def test_brand_lint_does_not_read_stylesheets_outside_the_workspace(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (tmp_path / "outside.css").write_text(".b { color: #ff0000; }\n")
    (root / "page.html").write_text(
        '<link rel="stylesheet" href="../outside.css">\n<p>Quarterly review</p>\n'
    )
    code, report = lint("page.html", root=root)
    assert code == 0
    assert rules(report) == {"stylesheet.outside"}


@pytest.mark.parametrize(
    ("setup", "args"),
    [
        ("raster", ["image.png"]),
        ("escape", ["../clean.html"]),
        ("tokens", ["--tokens", "missing-tokens.json", "page.html"]),
        ("usage", []),
    ],
)
def test_brand_lint_tooling_failures(setup: str, args: list[str], tmp_path: Path) -> None:
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n#7cb#dda")
    (tmp_path / "page.html").write_text("<p>Quarterly review</p>\n")
    extra = [] if setup == "tokens" else ["--tokens", str(TOKENS)]
    proc = run("brand-lint.mjs", "--root", tmp_path, *extra, *args)
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert proc.stdout == ""


# --- video-gate ------------------------------------------------------------------------------------

CLEAN_COMPOSITION = (FIXTURES / "video" / "clean.html").read_text()


def composition_with(tmp_path: Path, snippet: str, *, where: str = "script") -> Path:
    if where == "script":
        text = CLEAN_COMPOSITION.replace(
            'window.__timelines["main"] = tl;', f'{snippet}\n      window.__timelines["main"] = tl;'
        )
    elif where == "style":
        text = CLEAN_COMPOSITION.replace("      #root {", f"      {snippet}\n      #root {{")
    else:
        text = CLEAN_COMPOSITION.replace(
            "    </div>\n    <script>", f"      {snippet}\n    </div>\n    <script>"
        )
    assert text != CLEAN_COMPOSITION
    path = tmp_path / "comp.html"
    path.write_text(text)
    return path


def gate(path: Path) -> tuple[int, dict[str, Any]]:
    proc = run("video-gate.mjs", "--root", path.parent, "--json", path.name)
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def test_video_gate_clean_composition_passes() -> None:
    proc = run("video-gate.mjs", "--root", FIXTURES, "--json", "video/clean.html")
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["findings"] == []


@pytest.mark.parametrize(
    ("snippet", "rule", "where"),
    [
        ("const jitter = Math.random();", "random", "script"),
        ("const seed = crypto.getRandomValues(new Uint32Array(1));", "random", "script"),
        ("const started = Date.now();", "clock", "script"),
        ("const today = new Date();", "clock", "script"),
        ("const stamp = Date();", "clock", "script"),
        ("const t0 = performance.now();", "clock", "script"),
        ("setTimeout(() => tl.play(), 100);", "timer", "script"),
        ("setInterval(() => {}, 16);", "timer", "script"),
        ("requestAnimationFrame(() => {});", "raf", "script"),
        ('gsap.to("#bar", { x: 40, duration: 1 });', "standalone-tween", "script"),
        ("const loose = gsap.timeline();", "unpaused-timeline", "script"),
        (
            "const loose = gsap.timeline({\n        defaults: { ease: 'none' },\n      });",
            "unpaused-timeline",
            "script",
        ),
        ('tl.set("#sub", { opacity: 0 }, 0);', "initial-set", "script"),
        ("#bar { offset-path: path('M0 0 L100 0'); }", "offset-path", "style"),
        ('<img src="https://example.com/logo.png" alt="" />', "remote-asset", "body"),
        ("@import url('https://example.com/fonts.css');", "remote-asset", "style"),
        (
            'const at = (317 / 30).toFixed(4); tl.set("#bar", { opacity: 1 }, at);',
            "time-rounding",
            "script",
        ),
    ],
)
def test_video_gate_fails_each_seek_breaking_pattern(
    snippet: str, rule: str, where: str, tmp_path: Path
) -> None:
    code, report = gate(composition_with(tmp_path, snippet, where=where))
    assert code == 1
    assert rule in {f["rule"] for f in report["findings"] if f["severity"] == "ERROR"}


@pytest.mark.parametrize(
    ("snippet", "rule", "where"),
    [
        ('tl.call(() => document.body.classList.add("done"), null, 2);', "callback", "script"),
        ('tl.to("#bar", { left: 400, duration: 1 }, 1);', "left-top-tween", "script"),
        ('fetch("data.json");', "network", "script"),
        ("#bar { transition: opacity 0.3s; }", "css-motion", "style"),
        ("#bar { inset: 0; }", "inset", "style"),
    ],
)
def test_video_gate_warns_on_risky_patterns(
    snippet: str, rule: str, where: str, tmp_path: Path
) -> None:
    code, report = gate(composition_with(tmp_path, snippet, where=where))
    assert code == 0
    assert rule in {f["rule"] for f in report["findings"] if f["severity"] == "WARN"}


@pytest.mark.parametrize(
    ("snippet", "where"),
    [
        ("const cut = new Date(2025, 0, 1);", "script"),
        (
            "const later = gsap.timeline({\n        defaults: { ease: 'none' },\n        paused: true,\n      });",
            "script",
        ),
        ("#bar { transition: none; }", "style"),
        ('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"></svg>', "body"),
        ('gsap.set("#sub", { opacity: 0 });', "script"),
    ],
)
def test_video_gate_does_not_flag_deterministic_code(
    snippet: str, where: str, tmp_path: Path
) -> None:
    code, report = gate(composition_with(tmp_path, snippet, where=where))
    assert (code, report["findings"]) == (0, [])


def test_video_gate_checks_harness_scripts(tmp_path: Path) -> None:
    script = tmp_path / "probe.mjs"
    script.write_text(
        'const out = run("ffprobe", ["-show_entries", "frame=pts_time", "-of", "csv=p=0"]);\n'
    )
    code, report = gate(script)
    assert code == 1
    assert {f["rule"] for f in report["findings"]} == {"ffprobe-csv"}


def test_video_gate_does_not_lint_the_brand(tmp_path: Path) -> None:
    code, report = gate(
        composition_with(tmp_path, "#title { color: #000000; font-family: Arial; }", where="style")
    )
    assert (code, report["findings"]) == (0, [])


# --- artifact-contract -----------------------------------------------------------------------------


@pytest.fixture
def stills(tmp_path: Path) -> Path:
    from PIL import Image

    image = Image.new("RGB", (1080, 1350), (246, 241, 231))
    image.save(tmp_path / "post.png")
    image.save(tmp_path / "post.jpg", quality=90)
    image.save(tmp_path / "post.webp", quality=90)
    image.save(tmp_path / "lossless.webp", lossless=True)
    Image.new("RGBA", (300, 200), (20, 22, 26, 128)).save(tmp_path / "alpha.webp")
    data = (tmp_path / "post.png").read_bytes()
    (tmp_path / "truncated.png").write_bytes(data[: len(data) // 2])
    (tmp_path / "mislabelled.png").write_bytes((tmp_path / "post.jpg").read_bytes())
    (tmp_path / "empty.png").write_bytes(b"")
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    (tmp_path / "truncated.jpg").write_bytes(buf.getvalue()[:-200])
    return tmp_path


def expect(root: Path, *specs: str) -> tuple[int, dict[str, Any]]:
    proc = run(
        "artifact-contract.mjs",
        "--root",
        root,
        "--json",
        *[a for s in specs for a in ("--expect", s)],
    )
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def test_artifact_contract_measures_stills(stills: Path) -> None:
    code, report = expect(
        stills,
        "post.png:1080x1350",
        "post.jpg:1080x1350",
        "post.webp:1080x1350",
        "lossless.webp:1080x1350",
        "alpha.webp:300x200",
    )
    assert code == 0, report["problems"]
    assert [(o["format"], o["width"], o["height"]) for o in report["outputs"]] == [
        ("png", 1080, 1350),
        ("jpeg", 1080, 1350),
        ("webp", 1080, 1350),
        ("webp", 1080, 1350),
        ("webp", 300, 200),
    ]
    assert all(o["bytes"] > 0 for o in report["outputs"])


@pytest.mark.parametrize(
    ("spec", "problem"),
    [
        ("post.png:1080x1080", "is 1080x1350, expected 1080x1080"),
        ("missing.png:1080x1350", "does not exist"),
        ("empty.png:1080x1350", "is empty"),
        ("truncated.png:1080x1350", "truncated PNG"),
        ("truncated.jpg:1080x1350", "truncated JPEG"),
        ("mislabelled.png:1080x1350", "not a PNG"),
        ("post.png:1080x1350@3", "a duration was expected"),
    ],
)
def test_artifact_contract_fails_wrong_outputs(stills: Path, spec: str, problem: str) -> None:
    code, report = expect(stills, spec)
    assert code == 1
    assert report["ok"] is False
    (entry,) = report["outputs"]
    assert any(problem in p for p in entry["problems"]), entry["problems"]


@pytest.mark.parametrize(
    "spec", ["post.png", "post.png:1080", "post.png:axb", "../escape.png:10x10"]
)
def test_artifact_contract_bad_expectation_is_a_tooling_failure(stills: Path, spec: str) -> None:
    assert run("artifact-contract.mjs", "--root", stills, "--expect", spec).returncode == 2


def test_artifact_contract_plan_passes_and_final_holds_the_ledger() -> None:
    plan = run(
        "artifact-contract.mjs",
        "--root",
        FIXTURES,
        "--contract",
        "contract/plan.json",
        "--phase",
        "plan",
    )
    assert plan.returncode == 0, plan.stderr
    assert "__ARTIFACT_CONTRACT_OK__ phase=plan" in plan.stdout
    final = run(
        "artifact-contract.mjs",
        "--root",
        FIXTURES,
        "--contract",
        "contract/final-pending.json",
        "--phase",
        "final",
        "--json",
    )
    assert final.returncode == 1
    problems = json.loads(final.stdout)["problems"]
    assert any("final validation requires r1" in p for p in problems)
    assert any("brand/missing.html" in p for p in problems)


# --- text-fidelity (PDF audit, pure Node) ----------------------------------------------------------


def pdf_with_advances(advances: list[float], size: float = 12) -> bytes:
    ops = " ".join(f"{a:.5f} 0 Td (a) Tj" for a in advances)
    stream = zlib.compress(f"BT /F1 {size} Tf {ops} ET".encode())
    head = f"%PDF-1.4\n1 0 obj\n<< /Length {len(stream)} /Filter /FlateDecode >>\nstream\n".encode()
    return head + stream + b"\nendstream\nendobj\n%%EOF\n"


def audit(tmp_path: Path, data: bytes) -> tuple[int, dict[str, Any]]:
    (tmp_path / "x.pdf").write_bytes(data)
    proc = run("text-fidelity.mjs", tmp_path / "x.pdf", "--json")
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def test_text_fidelity_fails_quantized_advances(tmp_path: Path) -> None:
    code, report = audit(
        tmp_path, pdf_with_advances([n + 0.87468 for n in (7, 3, 10, 6, 8, 4, 9, 5)] * 3)
    )
    assert code == 1
    assert report["offenders"][0]["verdict"] == "quantized"


def test_text_fidelity_passes_subpixel_advances(tmp_path: Path) -> None:
    advances = [7.1234, 3.5521, 10.0917, 6.3402, 8.7713, 4.2291, 9.4807, 5.6612] * 3
    code, report = audit(
        tmp_path, pdf_with_advances([a + i * 0.0013 for i, a in enumerate(advances)])
    )
    assert (code, report["runsJudged"]) == (0, 1)


def test_text_fidelity_does_not_flag_monospace(tmp_path: Path) -> None:
    code, _ = audit(tmp_path, pdf_with_advances([7.2] * 24))
    assert code == 0


def test_text_fidelity_refuses_a_non_pdf(tmp_path: Path) -> None:
    (tmp_path / "x.pdf").write_text("not a pdf")
    assert run("text-fidelity.mjs", tmp_path / "x.pdf").returncode == 2


def test_text_fidelity_compares_requested_copy() -> None:
    result = node_eval(
        f"import {{ compareCopy }} from {json.dumps(str(TOOLS / 'text-fidelity.mjs'))};\n"
        "console.log(JSON.stringify(compareCopy('Field notes\\nMake the brief\\nNot here', 'FIELD NOTES\\n Make  the\\nbrief')));"
    )
    assert result["ok"] is False
    assert result["problems"] == [
        {"line": "Field notes", "problem": "casing", "rendered": "FIELD NOTES"},
        {"line": "Not here", "problem": "missing"},
    ]


# --- film-analysis (pure, recorded models) ---------------------------------------------------------


def analyse(model: str) -> tuple[int, dict[str, Any]]:
    proc = run("film-analysis.mjs", "--root", FIXTURES, "--json", f"film/{model}.model.json")
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def test_film_analysis_passes_a_developing_shot() -> None:
    code, report = analyse("clean")
    assert code == 0
    assert (report["sceneCount"], report["cutCount"], report["errors"]) == (1, 0, 0)
    assert report["development"]["scenes"][0]["develops"] is True


def test_film_analysis_fails_an_interior_blank() -> None:
    code, report = analyse("blank-gap")
    assert code == 1
    blank = [f for f in report["findings"] if f["code"] == "frames.blank"]
    assert blank and blank[0]["sev"] == "ERROR"


def test_film_analysis_ignores_overlapping_track_clips() -> None:
    model = json.loads((FIXTURES / "film" / "clean.model.json").read_text())
    assert len(model["clips"]) == 3  # parallel tracks, each the full length: layers, not shots
    _, report = analyse("clean")
    assert report["sceneCount"] == 1


def test_film_analysis_refuses_a_non_model(tmp_path: Path) -> None:
    (tmp_path / "m.json").write_text(json.dumps({"hello": "world"}))
    assert run("film-analysis.mjs", "--root", tmp_path, "m.json").returncode == 2


# --- fetch-asset (address policy; nothing here reaches the network) -------------------------------


def test_fetch_asset_address_policy() -> None:
    cases = {
        "8.8.8.8": False,
        "1.1.1.1": False,
        "172.32.0.1": False,
        "::ffff:8.8.8.8": False,
        "64:ff9b::808:808": False,
        "2002:808:808::": False,
        "2606:4700:4700::1111": False,
        "10.1.2.3": True,
        "172.31.0.1": True,
        "192.168.1.1": True,
        "100.64.0.1": True,
        "127.0.0.1": True,
        "169.254.169.254": True,
        "0.0.0.0": True,
        "255.255.255.255": True,
        "224.0.0.1": True,
        "::1": True,
        "::": True,
        "[::1]": True,
        "::ffff:127.0.0.1": True,
        "::ffff:7f00:1": True,
        "64:ff9b::a9fe:a9fe": True,
        "2002:7f00:1::": True,
        "2001::1": True,
        "fe80::1": True,
        "febf::1": True,
        "fc00::1": True,
        "fd00:ec2::254": True,
        "ff02::1": True,
        "2001:db8::1": True,
        "not-an-ip": True,
    }
    got = node_eval(
        f"import {{ isBlockedIP }} from {json.dumps(str(TOOLS / 'fetch-asset.mjs'))};\n"
        f"const cases = {json.dumps(list(cases))};\n"
        "console.log(JSON.stringify(Object.fromEntries(cases.map((ip) => [ip, isBlockedIP(ip)]))));"
    )
    assert got == cases


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("file:///etc/passwd", "only http(s)"),
        ("ftp://example.com/a.png", "only http(s)"),
        ("http://127.0.0.1/a.png", "blocked address"),
        ("http://[::1]/a.png", "blocked address"),
        ("http://[::ffff:127.0.0.1]/a.png", "blocked address"),
        ("http://169.254.169.254/latest/meta-data/", "blocked address"),
        ("http://0x7f000001/a.png", "blocked address"),
        ("http://[fd00:ec2::254]/a.png", "blocked address"),
        ("http://localhost:8080/a.png", "blocked host"),
        ("http://user:secret@example.com/a.png", "credentials"),
    ],
)
def test_fetch_asset_refuses_unsafe_urls(url: str, reason: str, tmp_path: Path) -> None:
    proc = run("fetch-asset.mjs", url, "--root", tmp_path, "--out", "assets")
    assert proc.returncode == 1
    assert proc.stdout.startswith(f"__FETCH_ERR__ {url} ")
    assert reason in proc.stdout
    assert not (tmp_path / "assets").exists()


def test_fetch_asset_guarded_lookup_refuses_names_that_resolve_inward() -> None:
    result = node_eval(
        f"import {{ guardedLookup }} from {json.dumps(str(TOOLS / 'fetch-asset.mjs'))};\n"
        "guardedLookup('localhost', { all: true }, (error, addresses) =>"
        " console.log(JSON.stringify({ code: error?.code ?? null, addresses: addresses ?? null })));"
    )
    assert result == {"code": "EBLOCKED", "addresses": None}


@pytest.mark.parametrize(
    "args",
    [
        ["https://example.com/a.png"],
        ["https://example.com/a.png", "--out", "../outside"],
        ["--out", "assets"],
        ["https://example.com/a.png", "--out", "assets", "--kind", "video"],
    ],
)
def test_fetch_asset_bad_arguments_are_tooling_failures(args: list[str], tmp_path: Path) -> None:
    assert run("fetch-asset.mjs", "--root", tmp_path, *args).returncode == 2
