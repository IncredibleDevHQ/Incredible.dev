"""Fakes for real-graph tests: a host-folder sandbox and a staging target that does nothing.

`FolderSandbox` maps the sandbox's `/workspace` to a temporary folder: file tools go through
Deep Agents' virtual filesystem, and shell commands run with `/workspace` rewritten to that folder.
It stands in for the Docker runner in offline tests; it is not isolation.
"""

from __future__ import annotations

from pathlib import Path

from deepagents.backends import LocalShellBackend
from deepagents.backends.protocol import ExecuteResponse

from design_agent.runtime.sandbox import SandboxBinding, _with_skills


class FolderSandbox(LocalShellBackend):
    def __init__(self, root: Path) -> None:
        (root / "workspace").mkdir(parents=True, exist_ok=True)
        super().__init__(root_dir=root, virtual_mode=True, inherit_env=True, timeout=120)
        self.root = root

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        rewritten = command.replace("/workspace", str(self.root / "workspace"))
        return super().execute(rewritten, timeout=timeout)


class NullStaging:
    """A staging target that reports the sandbox ready (tests that do not exercise staging)."""

    def upload(self, files: list[tuple[str, bytes]]) -> None:  # noqa: ARG002 - StagingTarget
        return None

    def execute(self, command: str, *, timeout: int) -> ExecuteResponse:  # noqa: ARG002 - StagingTarget
        return ExecuteResponse(output="", exit_code=0)

    def read(self, path: str) -> bytes | None:  # noqa: ARG002 - StagingTarget
        return None


def folder_binding(root: Path, project_root: Path) -> SandboxBinding:
    sandbox = FolderSandbox(root)
    return SandboxBinding(
        name="folder",
        graph_backend=_with_skills(sandbox, project_root),
        sandbox=sandbox,
        staging=NullStaging(),
    )
