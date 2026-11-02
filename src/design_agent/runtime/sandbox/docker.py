"""The Docker sandbox runner: one container per thread, built from `sandbox/Dockerfile`.

Only this module touches the Docker socket; containers never see it. Each thread gets a container
and a named volume mounted at `/workspace`, so files survive an idle stop while processes do not,
as on Managed Deep Agents. Containers run with no network (default-deny egress), all capabilities
dropped and a pids limit. The agent's commands run as the image's unprivileged `node` user
(uid 1000); staging runs as root, so the staged brand pack, gates and skill copies are read-only
to the agent.

`DockerSandboxBackend` is the one backend instance a compiled graph holds: Deep Agents takes a
backend instance, not a factory, so each call resolves the current thread's container from the
run config.
"""

from __future__ import annotations

import hashlib
import io
import logging
import posixpath
import shlex
import shutil
import subprocess
import tarfile
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import MAX_OUTPUT_BYTES, BaseSandbox
from langgraph.config import get_config

_LOGGER = logging.getLogger(__name__)

AGENT_USER = "1000:1000"
AGENT_HOME = "/home/node"
#: Where Deep Agents offloads conversation history, large tool results and media when it
#: summarizes. Its default is `/`, which the agent cannot write.
ARTIFACTS_ROOT = "/workspace/.agent"
#: Paths the agent may write. Everything else in the container is image or staged content.
AGENT_WRITABLE = (
    "/workspace/projects",
    "/workspace/attachments",
    "/workspace/.renders",
    ARTIFACTS_ROOT,
    "/tmp",
)
#: Paths the agent may read back through the file tools.
AGENT_READABLE = ("/workspace", "/tmp", "/opt/design-agent/probe")
#: Directories created at container start. The first set belongs to the agent; the second is
#: staged by the host and stays root-owned.
AGENT_DIRS = (
    "/workspace/projects",
    "/workspace/attachments",
    "/workspace/references",
    "/workspace/.renders",
    ARTIFACTS_ROOT,
)
STAGED_DIRS = ("/workspace/skills", "/workspace/tools", "/workspace/brand", "/workspace/fonts")
DEFAULT_TIMEOUT_SECONDS = 30 * 60


class SandboxUnavailableError(RuntimeError):
    """Docker or the sandbox image is missing. The message says what to run."""


def _under(path: str, roots: Iterable[str]) -> bool:
    normalized = posixpath.normpath(path)
    return any(normalized == root or normalized.startswith(f"{root}/") for root in roots)


def current_thread_id(default: str = "local") -> str:
    """The thread of the run in progress, from the LangGraph run config."""
    try:
        configurable = get_config().get("configurable") or {}
    except RuntimeError:
        return default
    thread_id = configurable.get("thread_id")
    return str(thread_id) if thread_id else default


@dataclass(frozen=True)
class DockerLimits:
    vcpus: int = 8
    mem_gib: int = 16
    pids: int = 4096
    shm_gib: int = 2


@dataclass
class _Container:
    name: str
    volume: str
    last_used: float = field(default_factory=time.monotonic)


class DockerSandboxRunner:
    """Creates, reuses and reaps per-thread containers. Thread-safe; one per process."""

    def __init__(
        self,
        *,
        image: str,
        limits: DockerLimits | None = None,
        idle_ttl_seconds: int = 600,
        docker: str = "docker",
        prefix: str = "design-agent",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.image = image
        self.limits = limits or DockerLimits()
        self.idle_ttl_seconds = idle_ttl_seconds
        self._docker = docker
        self._prefix = prefix
        self._clock = clock
        self._lock = threading.Lock()
        self._containers: dict[str, _Container] = {}

    # -- docker plumbing ------------------------------------------------------------------------

    def _run(
        self,
        args: Sequence[str],
        *,
        input_bytes: bytes | None = None,
        timeout: float | None = 120,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        if shutil.which(self._docker) is None:
            raise SandboxUnavailableError(
                "Docker is not installed or not on PATH; install Docker or choose another sandbox"
            )
        result = subprocess.run(  # noqa: S603 - fixed docker argv, never a shell
            [self._docker, *args],
            input=input_bytes,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if check and result.returncode != 0:
            # The CLI ends with "Run 'docker run --help' …"; the daemon's reason is above it.
            lines = [
                line
                for line in result.stderr.decode(errors="replace").strip().splitlines()
                if line.strip() and not line.startswith("Run '")
            ]
            detail = lines[-1] if lines else ""
            raise SandboxUnavailableError(f"docker {args[0]} failed: {detail[:300]}")
        return result

    def _host_limits(self) -> tuple[str, str]:
        """`--cpus` and `--memory`: the configured limits, capped at the Docker host's. The daemon
        refuses more CPUs than it has, and a memory limit above the VM's only hides the OOM."""
        info = self._run(["info", "--format", "{{.NCPU}} {{.MemTotal}}"], timeout=30, check=False)
        try:
            cpus, memory = (int(part) for part in info.stdout.split())
        except ValueError:
            cpus, memory = 0, 0
        wanted = self.limits.mem_gib * 1024**3
        return (
            str(min(self.limits.vcpus, cpus) if cpus > 0 else self.limits.vcpus),
            str(min(wanted, memory) if memory > 0 else wanted),
        )

    def available(self) -> tuple[bool, str]:
        """Whether Docker answers and the image exists, with a reason when not."""
        try:
            self._run(["version", "--format", "{{.Server.Version}}"], timeout=15)
        except (SandboxUnavailableError, subprocess.TimeoutExpired) as error:
            return False, str(error) or "docker did not answer"
        found = self._run(["image", "inspect", self.image], timeout=15, check=False)
        if found.returncode != 0:
            return False, (
                f"sandbox image {self.image} is not built; run "
                f"`docker build -t {self.image} sandbox/` (or `design-agent sandbox build`)"
            )
        return True, "ok"

    def names_for(self, thread_id: str) -> tuple[str, str]:
        digest = hashlib.sha256(thread_id.encode()).hexdigest()[:16]
        return f"{self._prefix}-{digest}", f"{self._prefix}-ws-{digest}"

    def container_for(self, thread_id: str) -> str:
        """The running container for `thread_id`, created or restarted as needed."""
        with self._lock:
            known = self._containers.get(thread_id)
            if known is None:
                name, volume = self.names_for(thread_id)
                known = _Container(name=name, volume=volume)
                self._containers[thread_id] = known
            self._ensure_running(known)
            known.last_used = self._clock()
            return known.name

    def _ensure_running(self, container: _Container) -> None:
        state = self._run(
            ["container", "inspect", "--format", "{{.State.Running}}", container.name],
            check=False,
            timeout=30,
        )
        if state.returncode == 0 and state.stdout.strip() == b"true":
            return
        if state.returncode == 0:
            self._run(["start", container.name], timeout=60)
        else:
            cpus, memory = self._host_limits()
            self._run(
                [
                    "run",
                    "--detach",
                    "--name",
                    container.name,
                    "--label",
                    f"{self._prefix}.thread=1",
                    "--network",
                    "none",
                    "--cap-drop",
                    "ALL",
                    # Root needs these three to stage read-only files; the agent's uid has none.
                    "--cap-add",
                    "CHOWN",
                    "--cap-add",
                    "DAC_OVERRIDE",
                    "--cap-add",
                    "FOWNER",
                    "--security-opt",
                    "no-new-privileges",
                    "--pids-limit",
                    str(self.limits.pids),
                    "--cpus",
                    cpus,
                    "--memory",
                    memory,
                    "--shm-size",
                    f"{self.limits.shm_gib}g",
                    "--mount",
                    f"type=volume,source={container.volume},target=/workspace",
                    self.image,
                    "sleep",
                    "infinity",
                ],
                timeout=120,
            )
        dirs = " ".join(shlex.quote(d) for d in (*AGENT_DIRS, *STAGED_DIRS))
        agent_dirs = " ".join(shlex.quote(d) for d in AGENT_DIRS)
        self._run(
            [
                "exec",
                container.name,
                "sh",
                "-c",
                f"mkdir -p {dirs} && chown {AGENT_USER} {agent_dirs}",
            ],
            timeout=60,
        )

    def reap_idle(self) -> list[str]:
        """Stop containers idle past the TTL. Their volumes (the thread's files) stay."""
        stopped: list[str] = []
        now = self._clock()
        with self._lock:
            for container in self._containers.values():
                if now - container.last_used >= self.idle_ttl_seconds:
                    self._run(["stop", "--time", "5", container.name], check=False, timeout=60)
                    stopped.append(container.name)
        return stopped

    def stop_all(self) -> None:
        with self._lock:
            for container in self._containers.values():
                self._run(["stop", "--time", "5", container.name], check=False, timeout=60)

    # -- execution and file transfer ------------------------------------------------------------

    def exec(
        self,
        thread_id: str,
        command: str,
        *,
        timeout: int | None = None,
        root: bool = False,
    ) -> ExecuteResponse:
        name = self.container_for(thread_id)
        seconds = DEFAULT_TIMEOUT_SECONDS if timeout is None or timeout <= 0 else int(timeout)
        # The in-container `timeout` kills the process tree; killing the docker client would not.
        wrapped = f"exec 2>&1; timeout --kill-after=10 {seconds} bash -c {shlex.quote(command)}"
        user = ["--user", "0:0"] if root else ["--user", AGENT_USER, "--env", f"HOME={AGENT_HOME}"]
        result = self._run(
            ["exec", *user, "--workdir", "/workspace", name, "bash", "-c", wrapped],
            timeout=seconds + 30,
            check=False,
        )
        output = result.stdout
        truncated = len(output) > MAX_OUTPUT_BYTES
        if truncated:
            output = output[:MAX_OUTPUT_BYTES]
        exit_code = result.returncode
        text = output.decode(errors="replace")
        if exit_code == 124:
            text += f"\n[command timed out after {seconds} s]"
        return ExecuteResponse(output=text, exit_code=exit_code, truncated=truncated)

    def put_archive(self, thread_id: str, archive: bytes, *, root: bool) -> None:
        """Extract a tar archive at `/` in the thread's container."""
        name = self.container_for(thread_id)
        user = ["--user", "0:0"] if root else ["--user", AGENT_USER]
        self._run(
            ["exec", "-i", *user, name, "tar", "-x", "-C", "/", "--no-same-owner", "-f", "-"],
            input_bytes=archive,
            timeout=300,
        )

    def get_file(self, thread_id: str, path: str) -> bytes | None:
        name = self.container_for(thread_id)
        result = self._run(
            ["exec", "--user", AGENT_USER, name, "cat", "--", path], check=False, timeout=300
        )
        return result.stdout if result.returncode == 0 else None


def tar_of(files: Iterable[tuple[str, bytes]], *, mode: int = 0o644) -> bytes:
    """A tar archive holding `files` at their absolute paths (leading slash stripped)."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for path, content in files:
            info = tarfile.TarInfo(path.lstrip("/"))
            info.size = len(content)
            info.mode = mode
            info.mtime = int(time.time())
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


class DockerSandboxBackend(BaseSandbox):
    """The agent-facing backend: commands and file tools in the current thread's container."""

    def __init__(
        self, runner: DockerSandboxRunner, *, thread_id: Callable[[], str] = current_thread_id
    ) -> None:
        self._runner = runner
        self._thread_id = thread_id

    @property
    def id(self) -> str:
        return self._runner.names_for(self._thread_id())[0]

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return self._runner.exec(self._thread_id(), command, timeout=timeout)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        allowed = [(p, c) for p, c in files if _under(p, AGENT_WRITABLE)]
        responses = [
            FileUploadResponse(
                path=p, error=None if _under(p, AGENT_WRITABLE) else "permission_denied"
            )
            for p, _ in files
        ]
        if allowed:
            try:
                # Create parents as the agent so new folders stay writable to it.
                parents = sorted({posixpath.dirname(posixpath.normpath(p)) for p, _ in allowed})
                quoted = " ".join(shlex.quote(p) for p in parents)
                self._runner.exec(self._thread_id(), f"mkdir -p {quoted}")
                self._runner.put_archive(self._thread_id(), tar_of(allowed), root=False)
            except SandboxUnavailableError as error:
                _LOGGER.warning("[sandbox] upload failed: %s", error)
                return [FileUploadResponse(path=p, error="upload failed") for p, _ in files]
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            if not _under(path, AGENT_READABLE):
                responses.append(FileDownloadResponse(path=path, error="permission_denied"))
                continue
            content = self._runner.get_file(self._thread_id(), path)
            responses.append(
                FileDownloadResponse(
                    path=path,
                    content=content,
                    error=None if content is not None else "file_not_found",
                )
            )
        return responses


class DockerStagingTarget:
    """Privileged staging into the current thread's container: files land root-owned and
    read-only to the agent (`middleware.workspace.StagingTarget`)."""

    def __init__(
        self, runner: DockerSandboxRunner, *, thread_id: Callable[[], str] = current_thread_id
    ) -> None:
        self._runner = runner
        self._thread_id = thread_id

    def upload(self, files: list[tuple[str, bytes]]) -> None:
        self._runner.put_archive(self._thread_id(), tar_of(files), root=True)

    def execute(self, command: str, *, timeout: int) -> ExecuteResponse:
        return self._runner.exec(self._thread_id(), command, timeout=timeout, root=True)

    def read(self, path: str) -> bytes | None:
        return self._runner.get_file(self._thread_id(), path)
