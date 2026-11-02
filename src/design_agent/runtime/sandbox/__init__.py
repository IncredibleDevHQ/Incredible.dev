"""Sandbox backends for the local and self-hosted runtimes, and how they are chosen.

MDA brings its own per-thread sandbox; these are the other three: the Docker runner (default when
Docker answers), LangSmith Sandboxes from a published snapshot, and the host (development only,
explicit flag). Each binding gives the graph its backend, host tools their file access, and the
stager its target.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepagents.backends import CompositeBackend, FilesystemBackend
from deepagents.backends.protocol import (
    BackendProtocol,
    DeleteResult,
    EditResult,
    FileUploadResponse,
    WriteResult,
)

from design_agent.config import Settings
from design_agent.middleware.workspace import BackendTarget, StagingTarget
from design_agent.runtime.sandbox.docker import (
    ARTIFACTS_ROOT,
    DockerLimits,
    DockerSandboxBackend,
    DockerSandboxRunner,
    DockerStagingTarget,
)

SKILLS_ROUTE = "/skills/"


class ReadOnlyFilesystemBackend(FilesystemBackend):
    """A host folder the agent may read but never change (the local stand-in for MDA's
    read-only Context Hub skills mount)."""

    _REFUSAL = "permission_denied: this folder is read-only"

    def write(self, file_path: str, content: str) -> WriteResult:  # noqa: ARG002 - base signature
        return WriteResult(error=self._REFUSAL)

    def edit(
        self,
        file_path: str,  # noqa: ARG002 - base signature
        old_string: str,  # noqa: ARG002
        new_string: str,  # noqa: ARG002
        replace_all: bool = False,  # noqa: ARG002
    ) -> EditResult:
        return EditResult(error=self._REFUSAL)

    def delete(self, file_path: str) -> DeleteResult:  # noqa: ARG002 - base signature
        return DeleteResult(error=self._REFUSAL)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return [FileUploadResponse(path=p, error="permission_denied") for p, _ in files]


class SandboxSelectionError(RuntimeError):
    """No sandbox can run here; the message says what to install or set."""


@dataclass(frozen=True)
class SandboxBinding:
    """One sandbox choice, wired three ways."""

    name: str
    graph_backend: BackendProtocol
    """What the compiled graph's file tools and `execute` use (skills routed read-only)."""
    sandbox: BackendProtocol
    """The bare sandbox backend, for host tools that move files in and out."""
    staging: StagingTarget
    runner: DockerSandboxRunner | None = None

    def staging_for(self, runtime: Any) -> StagingTarget:  # noqa: ARG002 - profile signature
        return self.staging

    def backend_for(self, runtime: Any) -> BackendProtocol:  # noqa: ARG002 - profile signature
        return self.sandbox


def _with_skills(sandbox: BackendProtocol, project_root: Path) -> CompositeBackend:
    skills = ReadOnlyFilesystemBackend(root_dir=project_root / "skills", virtual_mode=True)
    return CompositeBackend(
        default=sandbox, routes={SKILLS_ROUTE: skills}, artifacts_root=ARTIFACTS_ROOT
    )


def docker_binding(settings: Settings, project_root: Path) -> SandboxBinding:
    runner = DockerSandboxRunner(
        image=settings.sandbox_image,
        limits=DockerLimits(vcpus=settings.sandbox_vcpus, mem_gib=settings.sandbox_mem_gib),
        idle_ttl_seconds=settings.sandbox_idle_ttl_seconds,
    )
    sandbox = DockerSandboxBackend(runner)
    return SandboxBinding(
        name="docker",
        graph_backend=_with_skills(sandbox, project_root),
        sandbox=sandbox,
        staging=DockerStagingTarget(runner),
        runner=runner,
    )


def host_binding(project_root: Path) -> SandboxBinding:
    """Development only: renderers run on this machine, inside `<root>/.host-sandbox/`."""
    from deepagents.backends import LocalShellBackend

    root = project_root / ".host-sandbox"
    (root / "workspace").mkdir(parents=True, exist_ok=True)
    sandbox = LocalShellBackend(root_dir=root, virtual_mode=True, inherit_env=False)
    return SandboxBinding(
        name="host",
        graph_backend=_with_skills(sandbox, project_root),
        sandbox=sandbox,
        staging=BackendTarget(sandbox),
    )


def select_binding(settings: Settings, project_root: Path) -> SandboxBinding:
    """The configured sandbox, or for `auto` the Docker runner when Docker and the image exist."""
    choice = settings.sandbox
    if choice == "mda":
        raise SandboxSelectionError("the mda sandbox exists only inside a Managed Deep Agents run")
    if choice == "host":
        return host_binding(project_root)
    if choice == "langsmith":
        from design_agent.runtime.sandbox.langsmith import langsmith_binding

        return langsmith_binding(settings, project_root)
    binding = docker_binding(settings, project_root)
    runner = binding.runner
    ok, reason = runner.available() if runner is not None else (False, "no runner")
    if ok:
        return binding
    if choice == "auto" and settings.langsmith_api_key and settings.sandbox_snapshot:
        from design_agent.runtime.sandbox.langsmith import langsmith_binding

        return langsmith_binding(settings, project_root)
    raise SandboxSelectionError(
        f"No sandbox is available: {reason}. Install Docker and build the image, or set "
        "LANGSMITH_API_KEY and DESIGN_AGENT_SANDBOX_SNAPSHOT for LangSmith Sandboxes."
    )
