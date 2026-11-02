"""The design-judgment runtime skills: format, references and the contracts they name, offline.

Covers skills/{content-brief, brand-design, design-wiki, motion-direction, launch-film,
reference-study}. A skill that names a tool, gate, script, skill or CLI command that does not exist
teaches the model to call something it cannot, so every name is checked against the code.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from functools import cache
from pathlib import Path

import pytest
import yaml

from tests.unit.test_public_hygiene import scan

ROOT = Path(__file__).resolve().parents[2]
SKILLS = (
    "content-brief",
    "brand-design",
    "design-wiki",
    "motion-direction",
    "launch-film",
    "reference-study",
)
NODE = shutil.which("node")
SAMPLE_BRAND = ROOT / "examples" / "brands" / "example-studio"

#: Tools every Deep Agents graph has without our code (filesystem, shell, planning, delegation).
DEEPAGENTS_TOOLS = frozenset(
    {"write_todos", "read_file", "write_file", "edit_file", "ls", "glob", "grep", "execute", "task"}
)
#: snake_case words in these skills that are not tools: pipeline names, tool arguments, JSON fields.
NOT_TOOLS = frozenset(
    {
        "launch_film",  # the pipeline's name, passed to run_pipeline
        "builders_at_once",  # a launch_film argument
        "wake_on_progress",  # a start_task argument
        "job_kind",  # artifact-contract fields
        "allowed_additions",
        "allowed_removals",
        "allowed_changes",
        "superseded_by",
        "images_viewed",  # done-act JSON fields
        "run_id",  # tool arguments
        "task_id",
        "started_at",  # run.json fields, read by get_render_status
        "finished_at",
        "max_colors",  # an ffmpeg filter option
    }
)
#: Skills another slice owns; the router already names them.
PENDING_SKILLS = frozenset({"paper-design"})
#: kebab-case words in code spans that are not skills, gates or scripts.
NOT_SKILLS = frozenset(
    {
        "reference-transform",  # an artifact-contract job_kind
        "clip-path",  # CSS
        "text-transform",
        "motion-blur",  # the HyperFrames registry component
    }
)
#: Files a project holds, named by these skills, that no repository script provides.
PROJECT_FILES = frozenset({"timeline.js", "timeline.draft.js", "timeline.snippet.js", "film.js"})

FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
URL = re.compile(r"<?https?://[^\s>)]+>?")
CODE_SPAN = re.compile(r"`([^`\n]+)`")
SNAKE = re.compile(r"(?<![\w./{-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w-])")
KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")
SCRIPT = re.compile(r"(?<![\w.*}>-])([\w-]+\.(?:mjs|js|py))\b")
SKILL_SCRIPT = re.compile(r"(?:skills/)?([a-z0-9-]+)/scripts/([\w./-]+\.(?:mjs|js|py))")
GATE_PATH = re.compile(r"/workspace/tools/([\w-]+\.mjs)")
CLI = re.compile(r"\bhyperframes ([a-z][a-z-]*)\b")
HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9A-Za-z_-])")
CDN = re.compile(
    r"(?i)cdn\.jsdelivr\.net|unpkg\.com|cdnjs\.cloudflare\.com|ajax\.googleapis\.com"
    r"|code\.jquery\.com|esm\.sh|cdn\.skypack\.dev|fonts\.googleapis\.com|fonts\.gstatic\.com"
)


def _docs(skill: str) -> list[Path]:
    return sorted(
        p for p in (ROOT / "skills" / skill).rglob("*") if p.suffix in {".md", ".json", ".js"}
    )


ALL_DOCS = [doc for skill in SKILLS for doc in _docs(skill)]
MARKDOWN = [doc for doc in ALL_DOCS if doc.suffix == ".md"]


def _id(path: Path) -> str:
    return str(path.relative_to(ROOT / "skills"))


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _prose(path: Path) -> str:
    """The text with URLs removed, so a link's path never reads as a name."""
    return URL.sub("", _text(path))


@cache
def tool_names() -> frozenset[str]:
    """Every tool the lead or a helper can call, read from the modules that define them."""
    names: set[str] = set(DEEPAGENTS_TOOLS)
    for module in sorted((ROOT / "src" / "design_agent").glob("[mt]*/*.py")):
        source = module.read_text(encoding="utf-8")
        names.update(re.findall(r"@tool\s+(?:async\s+)?def\s+(\w+)", source))
        names.update(re.findall(r"from_function\([^)]*?name=\"(\w+)\"", source))
        for group in re.findall(r"(?:functions[^=\n]*=|for f in)\s*\(([^)]*)\)", source):
            names.update(re.findall(r"\b([a-z]\w+)\b", group))
        names.update(re.findall(r"UPLOAD_TOOL\s*=\s*\"(\w+)\"", source))
    return frozenset(names)


@cache
def skill_names() -> frozenset[str]:
    return frozenset(p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md"))


@cache
def gate_names() -> frozenset[str]:
    return frozenset(p.stem for p in (ROOT / "workspace" / "tools").glob("*.mjs"))


@cache
def script_basenames() -> frozenset[str]:
    found = {p.name for p in (ROOT / "workspace" / "tools").glob("*.mjs")}
    for scripts in (ROOT / "skills").glob("*/scripts"):
        found.update(p.name for p in scripts.rglob("*") if p.is_file())
    return frozenset(found)


@cache
def cli_commands() -> frozenset[str]:
    cli = ROOT / "skills" / "hyperframes-cli"
    text = "\n".join(
        _text(p) for p in [cli / "SKILL.md", *sorted((cli / "references").glob("*.md"))]
    )
    commands = set(re.findall(r"\bhyperframes ([a-z][a-z-]*)", text))
    description = FRONTMATTER.match(_text(cli / "SKILL.md"))
    assert description
    commands.update(re.findall(r"\b([a-z][a-z-]+)\b", description.group(1)))
    return frozenset(commands)


def _frontmatter(skill: str) -> dict[str, object]:
    match = FRONTMATTER.match(_text(ROOT / "skills" / skill / "SKILL.md"))
    assert match, f"{skill}/SKILL.md has no frontmatter"
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict)
    return data


@pytest.mark.parametrize("skill", SKILLS)
def test_frontmatter_names_the_folder_and_says_when_to_use_it(skill: str) -> None:
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
    description = data["description"]
    assert isinstance(description, str) and description.strip()
    assert "\n" not in description.strip(), "the description is one line"
    assert len(description) <= 200, f"{skill}: {len(description)} chars, resident in every prompt"


@pytest.mark.parametrize("skill", SKILLS)
def test_skill_body_is_small_with_depth_in_references(skill: str) -> None:
    lines = _text(ROOT / "skills" / skill / "SKILL.md").splitlines()
    assert len(lines) <= 250, (
        f"{skill}/SKILL.md is {len(lines)} lines: move detail into references/"
    )
    assert not (ROOT / "skills" / skill / "vendor").exists()
    lock = json.loads(_text(ROOT / "skills-lock.json"))
    assert skill not in lock.get("skills", {}), "our skills are not vendored upstream skills"


@pytest.mark.parametrize("doc", MARKDOWN, ids=_id)
def test_every_relative_link_resolves(doc: Path) -> None:
    for target in LINK.findall(_text(doc)):
        if "://" in target:
            continue
        assert (doc.parent / target).resolve().exists(), f"{_id(doc)} links to missing {target}"


@pytest.mark.parametrize("doc", ALL_DOCS, ids=_id)
def test_every_tool_named_exists(doc: Path) -> None:
    unknown = sorted(set(SNAKE.findall(_prose(doc))) - tool_names() - NOT_TOOLS)
    assert not unknown, f"{_id(doc)} names tools that do not exist: {unknown}"


@pytest.mark.parametrize("doc", ALL_DOCS, ids=_id)
def test_every_script_and_gate_named_exists(doc: Path) -> None:
    text = _prose(doc)
    for skill, path in SKILL_SCRIPT.findall(text):
        if skill in skill_names():
            assert (ROOT / "skills" / skill / "scripts" / path).is_file(), (
                f"{_id(doc)}: {skill}/scripts/{path}"
            )
    for gate in GATE_PATH.findall(text):
        assert (ROOT / "workspace" / "tools" / gate).is_file(), (
            f"{_id(doc)}: /workspace/tools/{gate}"
        )
    unknown = sorted(set(SCRIPT.findall(text)) - script_basenames() - PROJECT_FILES)
    assert not unknown, f"{_id(doc)} names scripts that do not exist: {unknown}"


@pytest.mark.parametrize("doc", MARKDOWN, ids=_id)
def test_every_skill_or_gate_in_code_names_exists(doc: Path) -> None:
    known = skill_names() | gate_names() | PENDING_SKILLS | NOT_SKILLS
    known |= {Path(name).stem for name in script_basenames()}
    spans = {span.strip() for span in CODE_SPAN.findall(_prose(doc))}
    names = {span for span in spans if KEBAB.match(span) and not span.startswith("data-")}
    unknown = sorted(names - known)
    assert not unknown, f"{_id(doc)} names skills or gates that do not exist: {unknown}"


@pytest.mark.parametrize("doc", MARKDOWN, ids=_id)
def test_every_hyperframes_command_named_exists(doc: Path) -> None:
    unknown = sorted(set(CLI.findall(_prose(doc))) - cli_commands())
    assert not unknown, f"{_id(doc)} names hyperframes commands the CLI does not have: {unknown}"


@pytest.mark.parametrize("doc", ALL_DOCS, ids=_id)
def test_colours_come_from_the_brand_pack(doc: Path) -> None:
    """A hex colour may appear only in an example that names the sample brand, and must be one of
    its tokens; every other colour is a brand-pack read."""
    tokens = json.loads(_text(SAMPLE_BRAND / "tokens.json"))["design"]
    sample = {c.lower() for c in [*tokens["allowedColors"], *tokens["extendedPalette"]["colors"]]}
    for number, line in enumerate(_text(doc).splitlines(), start=1):
        for colour in HEX.findall(line):
            assert "Example Studio" in line or "example-studio" in line, (
                f"{_id(doc)}:{number}: {colour} outside a sample-brand example; read the brand pack"
            )
            assert colour.lower() in sample, (
                f"{_id(doc)}:{number}: {colour} is not a sample-brand token"
            )


@pytest.mark.parametrize("doc", ALL_DOCS, ids=_id)
def test_no_library_is_loaded_from_a_cdn(doc: Path) -> None:
    assert not CDN.search(_text(doc)), (
        "the sandbox renders offline: copy libraries next to the composition"
    )


@pytest.mark.parametrize("doc", ALL_DOCS, ids=_id)
def test_model_facing_text_says_the_person(doc: Path) -> None:
    assert not re.search(r"(?i)\boperators?\b", _text(doc)), (
        "say the person, or whoever runs the deployment"
    )


def test_the_public_hygiene_scan_is_clean_on_these_skills() -> None:
    paths = [
        str(doc.relative_to(ROOT))
        for skill in SKILLS
        for doc in (ROOT / "skills" / skill).rglob("*")
        if doc.is_file()
    ]
    assert not scan(paths)


# -- launch-film is what the launch_film pipeline points its helpers at ------------------------------


def _pipeline_source() -> str:
    return _text(ROOT / "src" / "design_agent" / "pipelines" / "launch_film.py")


def _sandbox(path: str) -> Path:
    assert path.startswith("/skills/"), path
    return ROOT / "skills" / path.removeprefix("/skills/")


def test_every_file_the_pipeline_points_at_exists() -> None:
    source = _pipeline_source()
    constants = dict(re.findall(r'^(SKILL|ORCHESTRATION|BRIEFS) = "([^"]+)"', source, re.MULTILINE))
    assert set(constants) == {"SKILL", "ORCHESTRATION", "BRIEFS"}
    assert _sandbox(constants["SKILL"]).is_file()
    assert _sandbox(constants["ORCHESTRATION"]).is_file()
    briefs = _sandbox(constants["BRIEFS"])
    named = set(re.findall(r"\{BRIEFS\}/([\w-]+\.md)", source))
    assert {"act-builder.md", "critic.md", "helper.md", "resume.md", "README.md"} <= named
    for name in named:
        assert (briefs / name).is_file(), f"the pipeline sends helpers to briefs/{name}"
    for name in ("concept.md", "analyst.md", "sound.md"):
        assert (briefs / name).is_file()


def test_the_sections_the_pipeline_cites_exist() -> None:
    skill = _text(ROOT / "skills" / "launch-film" / "SKILL.md")
    sections = dict(re.findall(r"^## (\d+)\. (.+)$", skill, re.MULTILINE))
    assert set(sections) == {str(n) for n in range(11)}
    body = {n: skill.split(f"\n## {n}. ", 1)[1].split("\n## ", 1)[0] for n in sections}
    assert "analysis/requests" in body["6"] and "resume preamble" in body["6"]
    assert "AUDIT" in body["8"].split("\n2.", 1)[0], (
        "section 8, step 1 says what the audit preset means"
    )
    assert "upload_files" in body["8"]
    orchestration = _text(ROOT / "skills" / "launch-film" / "orchestration.md")
    waves = orchestration.split("\n## Waves", 1)[1].split("\n## ", 1)[0]
    assert re.search(r"three builders on one 8 vCPU", waves)
    builder = _text(ROOT / "skills" / "launch-film" / "briefs" / "act-builder.md")
    assert "## Part 1" in builder and "\n4.3 " in builder and "API.md" in builder


def test_the_skill_describes_the_pipeline_it_runs() -> None:
    source = _pipeline_source()
    skill = _text(ROOT / "skills" / "launch-film" / "SKILL.md")
    assert 'run_pipeline("launch_film"' in skill and "answer_pipeline" in skill
    approve, changes = re.search(r'APPROVE, CHANGES = "(\w+)", "(\w+)"', source).groups()  # type: ignore[union-attr]
    assert f'"{approve}"' in skill and f'"{changes}: ' in skill
    builders = re.search(r"^BUILDERS_AT_ONCE = (\d+)", source, re.MULTILINE).group(1)  # type: ignore[union-attr]
    assert f"default {builders}" in skill
    for effort in set(re.findall(r'effort="(\w+)"', source)):
        assert f"(`{effort}`)" in skill, f"the pipeline runs a step at {effort}"


def test_the_case_study_is_pending_not_invented() -> None:
    case_studies = ROOT / "skills" / "launch-film" / "references" / "case-studies"
    assert [p.name for p in case_studies.iterdir()] == ["README.md"]
    assert "Pending" in _text(case_studies / "README.md")


def test_reference_material_stays_out_of_the_repository() -> None:
    ignored = _text(ROOT / ".gitignore").splitlines()
    assert "workspace/references/*" in ignored
    study = _text(ROOT / "skills" / "reference-study" / "SKILL.md")
    assert "/workspace/references/<slug>/" in study and "save_observations" in study


# -- the scripts and the example contract run ---------------------------------------------------------


PRESETS = ROOT / "skills" / "motion-direction" / "scripts" / "motion-presets.js"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_motion_presets_are_deterministic_and_seek_safe() -> None:
    assert NODE is not None
    probe = """
const M = require(process.argv[1]);
const calls = [];
const tl = { fromTo: (...a) => (calls.push(["fromTo", ...a]), tl), to: (...a) => (calls.push(["to", ...a]), tl) };
M.enter(tl, "#s1-title", 0.4, M.family("silk"));
M.exit(tl, "#s1-title", 3.1, M.pick("punchy"));
console.log(JSON.stringify({
  calls, families: Object.keys(M.FAMILIES), aspects: Object.keys(M.ASPECTS),
  seeded: [M.seeded("a"), M.seeded("a"), M.seeded("b")],
  overshoot: M.overshoot(0.7), zoom: M.logZoom(10, 1, 0.5), frame: M.onFrame(1.0167, 30),
}));
"""
    run = subprocess.run(
        [NODE, "-e", probe, str(PRESETS)], capture_output=True, text=True, check=True
    )
    out = json.loads(run.stdout)
    assert out["families"] == ["silk", "snap", "spring", "float", "pulse"]
    assert {"landscape", "vertical", "square", "portrait"} <= set(out["aspects"])
    enter, exit_ = out["calls"]
    assert (
        enter[0] == "fromTo"
        and enter[2]["opacity"] == 0
        and enter[3]["opacity"] == 1
        and enter[4] == 0.4
    )
    assert (
        exit_[0] == "to"
        and exit_[2]["opacity"] == 0
        and exit_[2]["duration"] < enter[3]["duration"]
    )
    a, again, b = out["seeded"]
    assert a == again and a != b and 0 <= a < 1
    assert out["overshoot"] == pytest.approx(0.046, abs=0.001)
    assert out["zoom"] == pytest.approx(10**0.5)
    assert out["frame"] == pytest.approx(31 / 30 - 0.0005)
    gate = subprocess.run(
        [
            NODE,
            str(ROOT / "workspace" / "tools" / "video-gate.mjs"),
            "--root",
            str(PRESETS.parent),
            PRESETS.name,
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert gate.returncode == 0, gate.stdout + gate.stderr


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_example_contract_passes_plan_and_holds_final(tmp_path: Path) -> None:
    assert NODE is not None
    (tmp_path / "projects" / "launch").mkdir(parents=True)
    contract = tmp_path / "projects" / "launch" / "artifact-contract.json"
    shutil.copy(
        ROOT / "skills" / "brand-design" / "references" / "artifact-contract.example.json", contract
    )
    tool = str(ROOT / "workspace" / "tools" / "artifact-contract.mjs")
    args = [
        "--root",
        str(tmp_path),
        "--contract",
        "projects/launch/artifact-contract.json",
        "--phase",
    ]
    plan = subprocess.run([NODE, tool, *args, "plan"], capture_output=True, text=True, check=False)
    assert plan.returncode == 0, plan.stdout + plan.stderr
    final = subprocess.run(
        [NODE, tool, *args, "final"], capture_output=True, text=True, check=False
    )
    assert final.returncode == 1, "a pending requirement must hold the final gate"


def test_the_name_checks_know_the_real_tools_and_catch_a_wrong_one() -> None:
    tools = tool_names()
    for real in (
        "start_task",
        "check_tasks",
        "schedule_wakeup",
        "resume_task",
        "start_render_job",
        "watch_progress",
        "run_pipeline",
        "answer_pipeline",
        "start_looks",
        "pick_look",
        "look",
        "save_observations",
        "read_observations",
        "rate_observation",
        "learn_from_job",
        "report_progress",
        "upload_files",
        "generate_image",
        "generate_voiceover",
        "fetch_asset",
        "get_render_status",
        "list_recent_projects",
    ):
        assert real in tools, real
    assert "attach_file" not in tools
    assert SNAKE.findall("Deliver with `attach_file(path)` and upload_files.") == [
        "attach_file",
        "upload_files",
    ]
    assert SNAKE.findall("/workspace/projects/my_film/index.html") == []
    assert SCRIPT.findall("run breakdown.mjs, then timeline.draft.js and $S/grab.mjs") == [
        "breakdown.mjs",
        "grab.mjs",
    ]
    assert {
        "brand-lint",
        "video-gate",
        "artifact-contract",
        "video-score",
        "audio-lint",
    } <= gate_names()
    assert {"render", "snapshot", "check", "lint", "catalog", "add"} <= cli_commands()
