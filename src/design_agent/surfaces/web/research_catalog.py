"""Export repository folder names for an operator-selected private account."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile

from design_agent.surfaces.web.research import SKIP_DIRS


def _checkouts(projects: Path) -> Iterator[Path]:
    """Index checkouts up to two folders deep without reading their code or Git metadata."""
    if not projects.is_dir():
        raise ValueError("The projects directory does not exist")
    for folder, children, files in os.walk(projects, followlinks=False):
        relative = Path(folder).relative_to(projects)
        if ".git" in files or ".git" in children:
            yield relative
            children.clear()
        elif len(relative.parts) >= 2:
            children.clear()
        else:
            children[:] = [
                name for name in children if not name.startswith(".") and name not in SKIP_DIRS
            ]


def write_catalog(projects: Path, destination: Path, *, extra_roots: Sequence[Path] = ()) -> None:
    roots = [projects, *extra_roots]
    if len({root.name for root in roots}) != len(roots):
        raise ValueError("Give each scan root a distinct folder name")
    repositories = []
    for root in roots:
        for relative in _checkouts(root):
            if extra_roots:
                repositories.append(str(Path(root.name) / relative))
            else:
                repositories.append(str(relative) if relative.parts else root.name)
    with NamedTemporaryFile("w", dir=destination.parent, delete=False) as output:
        json.dump(sorted(repositories, key=str.casefold), output)
    os.replace(output.name, destination)


def catalog_repos(directory: Path, user_id: str) -> list[dict[str, str]] | None:
    try:
        paths = json.loads((directory / f"{uuid.UUID(user_id)}.json").read_text())
    except FileNotFoundError:
        return None
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise ValueError("Invalid repository catalog")
    return [{"name": Path(path).name or path, "path": path, "branch": ""} for path in paths]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("projects", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--also-scan", type=Path, action="append", default=[])
    args = parser.parse_args()
    write_catalog(args.projects, args.destination, extra_roots=args.also_scan)
