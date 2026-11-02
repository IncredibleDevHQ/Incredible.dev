"""Coding agents find every job through AGENTS.md, and every skill names only commands that exist."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from design_agent.cli import main

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".agents" / "skills"
FRONTMATTER = re.compile(
    r"\A---\nname: (?P<name>[^\n]+)\ndescription: (?P<description>[^\n]+)\n---\n"
)
COMMAND = re.compile(r"design-agent ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?")


def skill_dirs() -> list[Path]:
    return sorted(p for p in SKILLS.iterdir() if p.is_dir())


@pytest.mark.parametrize("skill", skill_dirs(), ids=lambda p: p.name)
def test_frontmatter_names_the_folder_and_says_when_to_use_it(skill: Path) -> None:
    match = FRONTMATTER.match((skill / "SKILL.md").read_text(encoding="utf-8"))
    assert match, f"{skill.name}/SKILL.md needs name and description frontmatter"
    assert match["name"] == skill.name
    assert len(match["description"]) >= 60, f"{skill.name}: say what it does and when to use it"


def test_agents_md_routes_to_every_skill() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    missing = [p.name for p in skill_dirs() if f".agents/skills/{p.name}/SKILL.md" not in agents]
    assert not missing, f"AGENTS.md has no route to: {missing}"


def test_claude_code_sees_the_same_skills() -> None:
    link = ROOT / ".claude" / "skills"
    assert link.is_symlink() and link.resolve() == SKILLS.resolve()


@pytest.mark.parametrize("skill", skill_dirs(), ids=lambda p: p.name)
def test_every_command_named_exists(skill: Path) -> None:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    unknown: list[str] = []
    for name, sub in COMMAND.findall(text):
        command = main.commands.get(name)
        if command is None:
            unknown.append(name)
        elif sub and hasattr(command, "commands") and sub not in command.commands:
            unknown.append(f"{name} {sub}")
    assert not unknown, f"{skill.name} names commands the CLI does not have: {unknown}"
