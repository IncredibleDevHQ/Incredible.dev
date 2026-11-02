"""Every relative link in the public docs and our skills resolves to a file in the repository."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)|(?:src|href)=\"([^\"]+)\"")


def documents() -> list[Path]:
    lock = json.loads((ROOT / "skills-lock.json").read_text())
    vendored = set(lock["skills"])
    vendored_agent_skills = {ROOT / ".agents" / "skills" / name for name in lock["agent_skills"]}
    found = [
        ROOT / name
        for name in (
            "README.md",
            "OPERATIONS.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "NOTICE.md",
            "CHANGELOG.md",
            "AGENTS.md",
        )
    ]
    found += sorted((ROOT / "docs").rglob("*.md"))
    found += [
        p
        for p in sorted((ROOT / ".agents").rglob("*.md"))
        if not vendored_agent_skills.intersection(p.parents)
    ]
    found += [
        p
        for p in sorted((ROOT / "skills").rglob("*.md"))
        if p.relative_to(ROOT / "skills").parts[0] not in vendored
    ]
    return [p for p in found if p.is_file()]


def test_relative_links_resolve() -> None:
    broken: list[str] = []
    for doc in documents():
        text = re.sub(r"```.*?```", "", doc.read_text(encoding="utf-8"), flags=re.DOTALL)
        for match in LINK.finditer(text):
            target = (match.group(1) or match.group(2) or "").split("#", 1)[0]
            if (
                not target
                or re.match(r"^[a-z]+:", target)
                or target.startswith(("#", "/", "mailto:"))
            ):
                continue
            if not (doc.parent / target).resolve().exists():
                broken.append(f"{doc.relative_to(ROOT)} -> {target}")
    assert not broken, "\n".join(broken)
