"""The Docker sandbox runner's isolation flags and path policy (docker calls are recorded, not run)."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from design_agent.runtime.sandbox import _with_skills
from design_agent.runtime.sandbox.docker import (
    ARTIFACTS_ROOT,
    DockerSandboxBackend,
    DockerSandboxRunner,
    SandboxUnavailableError,
)


class RecordingRunner(DockerSandboxRunner):
    def __init__(self, host_cpus: int = 16, host_mem_gib: int = 64, **kwargs: Any) -> None:
        super().__init__(image="design-agent-sandbox:test", **kwargs)
        self.calls: list[list[str]] = []
        self.running: set[str] = set()
        self.host = f"{host_cpus} {host_mem_gib * 1024**3}\n"

    def _run(
        self,
        args: Sequence[str],
        *,
        input_bytes: bytes | None = None,
        timeout: float | None = 120,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(list(args))
        if args[0] == "container":
            name = args[-1]
            return subprocess.CompletedProcess(
                args,
                0 if name in self.running else 1,
                b"true" if name in self.running else b"",
                b"",
            )
        if args[0] == "info":
            return subprocess.CompletedProcess(args, 0, self.host.encode(), b"")
        if args[0] == "run":
            self.running.add(args[args.index("--name") + 1])
        if args[0] == "exec" and args[-2:-1] == ["cat"]:
            return subprocess.CompletedProcess(args, 0, b"content", b"")
        return subprocess.CompletedProcess(args, 0, b"ok", b"")


def test_container_runs_isolated() -> None:
    runner = RecordingRunner()
    runner.container_for("thread-a")
    run = next(c for c in runner.calls if c[0] == "run")
    flag = lambda name: run[run.index(name) + 1]  # noqa: E731
    assert flag("--network") == "none"
    assert flag("--cap-drop") == "ALL"
    assert flag("--security-opt") == "no-new-privileges"
    assert "/var/run/docker.sock" not in " ".join(run)
    assert flag("--mount").startswith("type=volume,") and flag("--mount").endswith(
        "target=/workspace"
    )


@pytest.mark.parametrize(
    ("host_cpus", "host_mem_gib", "cpus", "mem_gib"), [(16, 64, "8", 16), (4, 8, "4", 8)]
)
def test_limits_never_exceed_the_docker_host(
    host_cpus: int, host_mem_gib: int, cpus: str, mem_gib: int
) -> None:
    runner = RecordingRunner(host_cpus=host_cpus, host_mem_gib=host_mem_gib)
    runner.container_for("t")
    run = next(c for c in runner.calls if c[0] == "run")
    assert run[run.index("--cpus") + 1] == cpus
    assert run[run.index("--memory") + 1] == str(mem_gib * 1024**3)


def test_a_failed_docker_call_reports_the_daemon_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    stderr = (
        b"docker: Error response from daemon: range of CPUs is from 0.01 to 4.00.\n"
        b"Run 'docker run --help' for more information\n"
    )
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        "subprocess.run", lambda args, **_kw: subprocess.CompletedProcess(args, 125, b"", stderr)
    )
    with pytest.raises(SandboxUnavailableError, match="range of CPUs"):
        DockerSandboxRunner(image="x")._run(["run"])


def test_threads_get_their_own_container_and_volume() -> None:
    runner = RecordingRunner()
    assert runner.container_for("a") != runner.container_for("b")
    assert runner.names_for("a")[1] != runner.names_for("b")[1]
    assert sum(1 for c in runner.calls if c[0] == "run") == 2
    runner.container_for("a")
    assert sum(1 for c in runner.calls if c[0] == "run") == 2, "a running container is reused"


def test_agent_commands_run_unprivileged_and_staging_runs_as_root() -> None:
    runner = RecordingRunner()
    runner.exec("t", "echo hi")
    agent = [c for c in runner.calls if c[0] == "exec"][-1]
    assert agent[agent.index("--user") + 1] == "1000:1000"
    runner.exec("t", "fc-cache", root=True)
    staged = [c for c in runner.calls if c[0] == "exec"][-1]
    assert staged[staged.index("--user") + 1] == "0:0"


def test_commands_are_killed_inside_the_container_on_timeout() -> None:
    runner = RecordingRunner()
    runner.exec("t", "sleep 100", timeout=7)
    script = [c for c in runner.calls if c[0] == "exec"][-1][-1]
    assert "timeout --kill-after=10 7 bash -c" in script


def test_uploads_outside_writable_folders_are_refused() -> None:
    runner = RecordingRunner()
    backend = DockerSandboxBackend(runner, thread_id=lambda: "t")
    results = backend.upload_files(
        [("/workspace/brand/tokens.json", b"{}"), ("/workspace/projects/x/a.txt", b"a")]
    )
    assert [r.error for r in results] == ["permission_denied", None]


def test_summarization_offloads_land_where_the_agent_can_write(tmp_path: Path) -> None:
    """Deep Agents writes conversation history, large results and media under the graph backend's
    artifacts root; the default `/` failed with permission_denied (issue 41)."""
    graph = _with_skills(DockerSandboxBackend(RecordingRunner(), thread_id=lambda: "t"), tmp_path)
    assert graph.artifacts_root == ARTIFACTS_ROOT
    media = f"{ARTIFACTS_ROOT}/conversation_history/media/910208ce0b6e3c89.png"
    backend = DockerSandboxBackend(RecordingRunner(), thread_id=lambda: "t")
    assert backend.upload_files([(media, b"png")])[0].error is None


@pytest.mark.parametrize("path", ["/etc/passwd", "/workspace/../etc/shadow", "/root/.ssh/id_rsa"])
def test_downloads_outside_readable_folders_are_refused(path: str) -> None:
    backend = DockerSandboxBackend(RecordingRunner(), thread_id=lambda: "t")
    assert backend.download_files([path])[0].error == "permission_denied"


def test_idle_containers_are_stopped_but_volumes_kept() -> None:
    now = [0.0]
    runner = RecordingRunner(idle_ttl_seconds=60, clock=lambda: now[0])
    runner.container_for("t")
    now[0] = 61
    assert runner.reap_idle() == [runner.names_for("t")[0]]
    assert not any(c[0] in {"rm", "volume"} for c in runner.calls)
