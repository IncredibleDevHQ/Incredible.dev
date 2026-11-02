"""`sandbox publish` on a fake LangSmith client: the steps, the name, the cleanup, the rewrite."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from design_agent.runtime.sandbox import publish

ROOT = Path(__file__).resolve().parents[2]


class FakeSandbox:
    def __init__(self, log: list[str], setup_exit: int) -> None:
        self.log, self.setup_exit = log, setup_exit

    def write(self, path: str, content: bytes) -> None:
        self.log.append(f"write {path} {len(content)}")

    def run(self, command: str, *, timeout: int) -> Any:
        self.log.append(f"run {command}")
        code = self.setup_exit if "setup" in command else 0
        return SimpleNamespace(exit_code=code, stdout="probe ok: node v22")


class FakeClient:
    def __init__(self, setup_exit: int = 0, existing: tuple[Any, ...] = ()) -> None:
        self.log: list[str] = []
        self.setup_exit = setup_exit
        self.existing = existing

    def list_snapshots(self, *, name_contains: str) -> list[Any]:
        return [snap for snap in self.existing if name_contains in snap.name]

    def create_snapshot(self, name: str, image: str, fs: int, *, timeout: int) -> Any:
        assert timeout >= 600, "building from a Docker image takes minutes"
        self.log.append(f"base {name} {image.split('@')[0]} {fs // publish.GIB}")
        return SimpleNamespace(id="snap-base")

    def wait_for_snapshot(self, snapshot_id: str, *, timeout: int) -> Any:
        return SimpleNamespace(id=snapshot_id, status="ready")

    def create_sandbox(self, **kwargs: Any) -> FakeSandbox:
        self.log.append(f"sandbox {kwargs['name'].rsplit('-', 1)[0]} from {kwargs['snapshot_id']}")
        return FakeSandbox(self.log, self.setup_exit)

    def capture_snapshot(self, sandbox: str, name: str, **_: Any) -> Any:
        self.log.append(f"capture {name}")
        return SimpleNamespace(id="snap-final")

    def delete_sandbox(self, name: str) -> None:
        self.log.append("delete")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A checkout on the Docker base, whatever this one declares (an operator's may name its
    published snapshot)."""
    (tmp_path / "sandbox").mkdir()
    shutil.copy(ROOT / "sandbox" / "setup.sh", tmp_path / "sandbox" / "setup.sh")
    declaration = (ROOT / "sandbox" / "__init__.py").read_text()
    declaration = re.sub(r'^SNAPSHOT_NAME = "[^"]*"\n', "", declaration, flags=re.MULTILINE)
    declaration = declaration.replace("snapshot_name=SNAPSHOT_NAME,", "docker_image=BASE_IMAGE,")
    (tmp_path / "sandbox" / "__init__.py").write_text(declaration)
    return tmp_path


def test_publish_runs_the_recipe_captures_a_named_snapshot_and_cleans_up(project: Path) -> None:
    client = FakeClient()
    published = publish.publish(client, project, say=lambda _: None)
    sha = publish.recipe_sha(project)
    assert (
        published.snapshot_name == f"design-agent-computer-{sha[:12]}"
        and published.snapshot_id == "snap-final"
    )
    assert client.log[0] == f"base design-agent-base-{sha[:12]} node:22.23.3-bookworm-slim 16"
    assert any(line.startswith("run bash /tmp/design-agent-setup.sh") for line in client.log)
    assert f"run {publish.PROBE}" in client.log and client.log[-1] == "delete"


def test_a_failed_recipe_publishes_nothing_and_still_cleans_up(project: Path) -> None:
    client = FakeClient(setup_exit=1)
    with pytest.raises(publish.PublishError, match="setup.sh failed"):
        publish.publish(client, project, say=lambda _: None)
    assert not any(line.startswith("capture") for line in client.log) and client.log[-1] == "delete"


def test_declaring_the_snapshot_rewrites_a_static_literal(project: Path) -> None:
    assert publish.declared_base(project) == "docker_image"
    publish.declare_snapshot(project, "design-agent-computer-abc")
    text = (project / "sandbox" / "__init__.py").read_text()
    assert (
        'SNAPSHOT_NAME = "design-agent-computer-abc"' in text
        and "snapshot_name=SNAPSHOT_NAME," in text
    )
    assert "docker_image=BASE_IMAGE" not in text and publish.declared_base(project) == "snapshot"
    publish.declare_snapshot(project, "design-agent-computer-def")
    assert (project / "sandbox" / "__init__.py").read_text().count("SNAPSHOT_NAME = ") == 1


def test_a_published_recipe_is_not_published_again(project: Path) -> None:
    sha = publish.recipe_sha(project)
    done = SimpleNamespace(name=f"design-agent-computer-{sha[:12]}", id="snap-done", status="ready")
    client = FakeClient(existing=(done,))
    published = publish.publish(client, project, say=lambda _: None)
    assert published.snapshot_id == "snap-done" and client.log == []


def test_a_rerun_picks_up_the_base_snapshot_it_started(project: Path) -> None:
    sha = publish.recipe_sha(project)
    building = SimpleNamespace(
        name=f"design-agent-base-{sha[:12]}", id="snap-old", status="building"
    )
    client = FakeClient(existing=(building,))
    publish.publish(client, project, say=lambda _: None)
    assert not any(line.startswith("base ") for line in client.log)
    assert client.log[0].endswith("from snap-old")


def test_a_ready_snapshot_wins_over_a_duplicate_still_building(project: Path) -> None:
    sha = publish.recipe_sha(project)
    name = f"design-agent-base-{sha[:12]}"
    stuck = SimpleNamespace(name=name, id="snap-stuck", status="building")
    ready = SimpleNamespace(name=name, id="snap-ready", status="ready")
    client = FakeClient(existing=(stuck, ready))
    publish.publish(client, project, say=lambda _: None)
    assert client.log[0].endswith("from snap-ready")
