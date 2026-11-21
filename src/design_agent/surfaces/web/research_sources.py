"""Bounded, tool-free context from committed blobs in an operator's selected checkouts."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from design_agent.surfaces.web.research import SKIP_DIRS
from design_agent.surfaces.web.research_catalog import _checkouts

SOURCE_EXTENSIONS = set(
    ".md .rst .txt .py .ts .tsx .js .jsx .rs .go .java .kt .rb .cs .cpp .c .h .swift .sql .vue .svelte .html .css".split()
)
PRIVATE_NAME = re.compile(r"credential|secret|private[-_]?key|password|\.min\.", re.I)


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(  # noqa: S603 - fixed Git plumbing commands, no shell
        ["/usr/bin/git", "-c", f"safe.directory={repo}", "-C", str(repo), *args],
        env={
            "PATH": os.defpath,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_ALLOW_PROTOCOL": "",
        },
        capture_output=True,
        timeout=12,
        check=True,
    ).stdout


def excerpts(repo: Path, question: str, budget: int) -> str:
    marker = repo / ".git"
    if marker.is_symlink() or not (marker.is_dir() or marker.is_file()):
        raise ValueError("Choose a Git checkout")
    if marker.is_file():
        directory = Path(os.fsdecode(_git(repo, "rev-parse", "--absolute-git-dir")).strip())
        backlink = directory / "gitdir"
        if (
            directory.parent.name != "worktrees"
            or not backlink.is_file()
            or not Path(backlink.read_text().strip()).samefile(marker)
        ):
            raise ValueError("The linked worktree does not belong to this checkout")
    terms = set(re.findall(r"[a-z0-9_]{3,}", question.lower()))
    candidates = []
    for record in _git(repo, "ls-tree", "-rlz", "HEAD").split(b"\0"):
        if not record:
            continue
        meta, name = record.split(b"\t", 1)
        mode, kind, oid, size = meta.split()
        path = Path(os.fsdecode(name))
        if (
            mode not in (b"100644", b"100755")
            or kind != b"blob"
            or int(size) > 512_000
            or path.suffix.lower() not in SOURCE_EXTENSIONS
            or PRIVATE_NAME.search(str(path))
            or any(
                p.startswith(".")
                or p in SKIP_DIRS
                or p in {"private-fonts", "workspace", "coverage"}
                for p in path.parts
            )
        ):
            continue
        score = len(terms.intersection(re.findall(r"[a-z0-9_]+", str(path).lower())))
        candidates.append(
            (-score, path.name.lower() != "readme.md", len(path.parts), str(path), oid)
        )
    sections = []
    for _, _, _, filename, blob in sorted(candidates)[:30]:
        text = _git(repo, "cat-file", "blob", blob.decode()).decode("utf-8", errors="replace")
        section = f"\n--- {filename} ---\n{text[: min(6000, budget)]}"
        sections.append(section)
        budget -= len(section)
        if budget <= 0:
            break
    return "".join(sections) or "(No supported committed source files.)"


def read_sources(roots: list[Path], selected: list[str], question: str) -> str:
    if not 1 <= len(selected) <= 8 or len(set(selected)) != len(selected):
        raise ValueError("Choose one to eight distinct repositories")
    available = {
        str(Path(root.name) / relative)
        if len(roots) > 1
        else (str(relative) if relative.parts else root.name): (root / relative).resolve()
        for root in roots
        for relative in _checkouts(root)
    }
    if any(name not in available for name in selected):
        raise ValueError("A selected repository is no longer in the catalog")
    return "\n".join(
        f"Repository {name}\n{excerpts(available[name], question, 90000 // len(selected))}"
        for name in selected
    )


if __name__ == "__main__":
    request = json.load(sys.stdin)
    roots = [Path(p) for p in os.environ["DESIGN_AGENT_RESEARCH_ROOTS"].split(",")]
    print(read_sources(roots, request["repos"], request["question"]))
