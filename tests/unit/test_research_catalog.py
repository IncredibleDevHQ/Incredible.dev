import json
from pathlib import Path

from design_agent.surfaces.web.research_catalog import write_catalog


def test_catalog_discovers_repos_and_worktrees_without_following_links(tmp_path: Path):
    projects = tmp_path / "projects"
    (projects / "one/.git").mkdir(parents=True)
    (projects / "team/two").mkdir(parents=True)
    (projects / "team/two/.git").write_text("gitdir: /elsewhere")
    (projects / ".private/repo/.git").mkdir(parents=True)
    (projects / "third/too/deep/.git").mkdir(parents=True)
    (projects / "node_modules/lib/.git").mkdir(parents=True)
    (tmp_path / "outside/.git").mkdir(parents=True)
    (projects / "linked").symlink_to(tmp_path / "outside", target_is_directory=True)
    destination = tmp_path / "account.json"
    write_catalog(projects, destination)
    assert json.loads(destination.read_text()) == ["one", "team/two"]
    (projects / "one/.git").rmdir()
    write_catalog(projects, destination)
    assert json.loads(destination.read_text()) == ["team/two"]


def test_catalog_combines_roots_and_keeps_same_named_repos_distinct(tmp_path: Path):
    projects = tmp_path / "projects"
    work = tmp_path / "work-repos"
    for path in [projects / "studio", work / "studio", work / "tools/sample-app"]:
        (path / ".git").mkdir(parents=True)
    destination = tmp_path / "account.json"
    write_catalog(projects, destination, extra_roots=[work])
    assert json.loads(destination.read_text()) == [
        "projects/studio",
        "work-repos/studio",
        "work-repos/tools/sample-app",
    ]
