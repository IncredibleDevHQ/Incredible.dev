import subprocess
from pathlib import Path

import pytest

from design_agent.surfaces.web.research_sources import read_sources


def test_selected_repositories_supply_only_committed_source(tmp_path: Path):
    root = tmp_path / "projects"
    for name in ("alpha", "beta", "other"):
        repo = root / name
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "README.md").write_text("Documentation for " + name)
        (repo / "secrets.json").write_text("private fixture")
        (repo / "linked.md").symlink_to(repo / "secrets.json")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.org",
                "commit",
                "-qm",
                "sample",
            ],
            check=True,
        )
        (repo / "README.md").write_text("uncommitted")
    result = read_sources([root], ["alpha", "beta"], "Documentation")
    assert "Documentation for alpha" in result and "Documentation for beta" in result
    for excluded in ("Documentation for other", "private fixture", "uncommitted", "linked.md"):
        assert excluded not in result
    with pytest.raises(ValueError):
        read_sources([root], ["../other"], "Documentation")
