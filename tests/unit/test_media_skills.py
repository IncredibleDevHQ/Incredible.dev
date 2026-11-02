"""The media-pipeline runtime skills: format, script hygiene and pure logic, offline.

Covers skills/{image-ops, gif-edit, visual-verify, film-breakdown, data-viz, stills, thumbnails,
image-generation, sound, storyboard, paper-design}. Rendering is covered by tests/render/test_media_render.py.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
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
    "paper-design",
)
NODE = shutil.which("node")
FIXTURES = ROOT / "tests" / "fixtures" / "media"
SAMPLE_TOKENS = ROOT / "examples" / "brands" / "example-studio" / "tokens.json"

NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
TOOLCHAIN_PACKAGES = r"(?:sharp|echarts|gsap|puppeteer-core|puppeteer|playwright|playwright-core)"
BARE_LOAD = re.compile(
    rf"""(?:\bfrom\s+|\bimport\s*\(\s*|(?<![)\w])require\s*\(\s*)["']{TOOLCHAIN_PACKAGES}["']"""
)
TOOLCHAIN_LOAD = re.compile(rf"""\(\s*["']{TOOLCHAIN_PACKAGES}["']\s*\)""")
PROVIDER_URL = re.compile(
    r"(?i)api\.openai\.com|elevenlabs\.io|generativelanguage\.googleapis\.com|api\.groq\.com"
    r"|epidemicsound\.com|api\.anthropic\.com|api\.replicate\.com"
)
SECRET_READ = re.compile(
    r"(?:process\.env|os\.environ)(?:\.get\(|\[|\.)\s*[\"']?[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET)"
)
VENDORED = re.compile(r"(?i)echarts\.min|gsap\.min|/\*!\s*\w+.*\bv?\d+\.\d+\.\d+|@license\b")


def _frontmatter(skill: str) -> dict[str, object]:
    text = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, f"{skill}/SKILL.md has no frontmatter"
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict)
    return data


def _scripts() -> list[Path]:
    found: list[Path] = []
    for skill in SKILLS:
        for path in sorted((ROOT / "skills" / skill).rglob("*")):
            if path.suffix in {".mjs", ".js", ".py"} and path.is_file():
                found.append(path)
    return found


SCRIPTS = _scripts()
JS_SCRIPTS = [p for p in SCRIPTS if p.suffix in {".mjs", ".js"}]


def _id(path: Path) -> str:
    return str(path.relative_to(ROOT / "skills"))


@pytest.mark.parametrize("skill", SKILLS)
def test_skill_frontmatter_is_valid(skill: str) -> None:
    data = _frontmatter(skill)
    assert set(data) <= {
        "name",
        "description",
        "license",
        "metadata",
        "compatibility",
        "allowed-tools",
    }
    assert data["name"] == skill
    assert NAME.match(skill) and len(skill) <= 64
    description = data["description"]
    assert isinstance(description, str) and description.strip()
    assert len(description) <= 300, (
        f"{skill}: description is {len(description)} chars (resident in every prompt)"
    )


@pytest.mark.parametrize("skill", SKILLS)
def test_skill_body_is_small_and_its_links_resolve(skill: str) -> None:
    skill_dir = ROOT / "skills" / skill
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert len(text) <= 10_000, (
        f"{skill}/SKILL.md is {len(text)} chars: move detail into references/"
    )
    for doc in [skill_dir / "SKILL.md", *sorted((skill_dir / "references").glob("*.md"))]:
        for target in LINK.findall(doc.read_text(encoding="utf-8")):
            if "://" in target:
                continue
            assert (doc.parent / target).resolve().exists(), (
                f"{doc.relative_to(ROOT)} links to missing {target}"
            )


def test_every_owned_skill_is_present_and_nothing_is_vendored() -> None:
    for skill in SKILLS:
        assert (ROOT / "skills" / skill / "SKILL.md").is_file()
        assert not (ROOT / "skills" / skill / "vendor").exists()
    lock = json.loads((ROOT / "skills-lock.json").read_text())
    assert not set(SKILLS) & set(lock.get("skills", {})), (
        "our skills are not vendored upstream skills"
    )


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("script", JS_SCRIPTS, ids=_id)
def test_script_parses(script: Path) -> None:
    run = subprocess.run(
        [NODE, "--check", str(script)], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize("script", SCRIPTS, ids=_id)
def test_script_has_no_vendored_library(script: Path) -> None:
    assert script.stat().st_size < 120_000, "a script this large is a vendored bundle"
    text = script.read_text(encoding="utf-8")
    assert not VENDORED.search(text), "vendored library banner or bundle reference"
    assert max((len(line) for line in text.splitlines()), default=0) < 2_000, "minified code"


@pytest.mark.parametrize("script", SCRIPTS, ids=_id)
def test_script_has_no_hard_coded_brand_palette(script: Path) -> None:
    tokens = json.loads(SAMPLE_TOKENS.read_text())
    brand = {
        c.lower()
        for c in [
            *tokens["design"]["allowedColors"],
            *tokens["design"]["extendedPalette"]["colors"],
        ]
    } - {"#ffffff", "#000000"}
    literals = {h.lower() for h in HEX.findall(script.read_text(encoding="utf-8"))}
    assert not literals & brand, f"brand colours baked into a script: {sorted(literals & brand)}"
    assert len(literals - {"#ffffff", "#000000"}) <= 4, f"a hard-coded palette: {sorted(literals)}"


@pytest.mark.parametrize("script", JS_SCRIPTS, ids=_id)
def test_script_loads_render_packages_only_from_the_toolchain(script: Path) -> None:
    text = script.read_text(encoding="utf-8")
    assert not BARE_LOAD.search(text), (
        "a bare import of a render package bypasses the pinned toolchain"
    )
    if TOOLCHAIN_LOAD.search(text):
        assert "createRequire" in text and "DESIGN_AGENT_RENDER_DIR" in text


@pytest.mark.parametrize("script", SCRIPTS, ids=_id)
def test_script_never_calls_a_provider_or_reads_a_key(script: Path) -> None:
    text = script.read_text(encoding="utf-8")
    assert not PROVIDER_URL.search(text), "provider calls belong to host tools"
    assert not SECRET_READ.search(text), "the sandbox never reads credentials"


def test_skill_docs_route_providers_through_host_tools() -> None:
    sound = (ROOT / "skills" / "sound" / "SKILL.md").read_text(encoding="utf-8")
    for tool in (
        "generate_voiceover",
        "generate_sound_effect",
        "generate_music",
        "transcribe_audio",
    ):
        assert tool in sound
    assert "cut to the voiceover" in sound
    image = (ROOT / "skills" / "image-generation" / "SKILL.md").read_text(encoding="utf-8")
    assert "generate_image" in image
    assert "built in HTML on brand" in image
    assert "alpha" in image
    assert not re.search(
        r"\b(?:256|512|1024|1536)x(?:256|512|1024|1536)\b.*(?:only|allowed)", image
    )


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("suite", sorted(FIXTURES.glob("*.test.mjs")), ids=lambda p: p.name)
def test_pure_logic(suite: Path) -> None:
    run = subprocess.run(
        [NODE, "--test", "--test-reporter=tap", str(suite)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    failures = [line for line in run.stdout.splitlines() if line.startswith("not ok")]
    assert run.returncode == 0, "\n".join(failures) + "\n" + run.stdout[-4000:] + run.stderr[-2000:]
