"""Stage skills, gates, the brand pack and fonts into the thread's sandbox.

On the first run of a cold sandbox, and whenever the manifest digest changes, the stager uploads
one compressed archive with a sha256 checklist, expands it over the staged roots (which it clears
first, so a deleted file does not linger), refreshes fontconfig, checks every required brand font
family resolves, and writes a ready marker. A warm sandbox costs one marker read per run.

Staging failures never end a run silently: the model is told in one note that the computer is not
ready, so it can say so instead of rendering with substitute fonts. The next run retries.
"""

from __future__ import annotations

import asyncio
import secrets
import shlex
from collections.abc import Callable
from typing import Any, Protocol

from deepagents.backends.protocol import ExecuteResponse
from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from design_agent.workspace.manifest import Manifest

MARKER = "/workspace/.design-agent-ready"
STAGED_ROOTS = ("/workspace/skills", "/workspace/tools", "/workspace/brand", "/workspace/fonts")
_EXPAND_FAILED, _CHECK_FAILED, _FONT_FAILED = 91, 92, 93
_FAILURES = {
    _EXPAND_FAILED: "the workspace archive did not expand in the sandbox",
    _CHECK_FAILED: "staged files did not match their checksums",
    _FONT_FAILED: "a required brand font does not resolve in the sandbox",
}


class StagingTarget(Protocol):
    """Where staging writes: the sandbox's file API and shell, privileged where the backend allows."""

    def upload(self, files: list[tuple[str, bytes]]) -> None: ...

    def execute(self, command: str, *, timeout: int) -> ExecuteResponse: ...

    def read(self, path: str) -> bytes | None: ...


class BackendTarget:
    """Stage through a Deep Agents sandbox backend (MDA's `runtime.backend`, LangSmith, host)."""

    def __init__(self, backend: Any) -> None:
        self._backend = backend

    def upload(self, files: list[tuple[str, bytes]]) -> None:
        results = self._backend.upload_files(files)
        if len(results) != len(files) or any(r.error for r in results):
            raise StagingError("the staging upload was refused")

    def execute(self, command: str, *, timeout: int) -> ExecuteResponse:
        result: ExecuteResponse = self._backend.execute(command, timeout=timeout)
        return result

    def read(self, path: str) -> bytes | None:
        result = self._backend.download_files([path])[0]
        return result.content if result.error is None else None


class StagingError(RuntimeError):
    """Staging failed; the message is safe to show the model."""


def staging_script(
    *, digest: str, archive_path: str, check_path: str, families: tuple[str, ...]
) -> str:
    roots = " ".join(shlex.quote(r) for r in STAGED_ROOTS)
    lines = [
        "set -u",
        f"rm -rf {roots} && mkdir -p {roots} || exit {_EXPAND_FAILED}",
        f"tar -xzf {shlex.quote(archive_path)} -C /workspace --no-same-owner --no-same-permissions"
        f" || exit {_EXPAND_FAILED}",
        f"rm -f {shlex.quote(archive_path)}",
        f"sha256sum -c --quiet {shlex.quote(check_path)} >/dev/null 2>&1 || exit {_CHECK_FAILED}",
        f"rm -f {shlex.quote(check_path)}",
        "fc-cache /workspace/fonts >/dev/null 2>&1 || true",
    ]
    for family in families:
        quoted = shlex.quote(family)
        probe = f"[ \"$(fc-match -f '%{{family[0]}}' {quoted})\" = {quoted} ]"
        lines.append(
            f"{probe} || {{ fc-cache -f /workspace/fonts >/dev/null 2>&1; {probe}; }} || exit {_FONT_FAILED}"
        )
    lines.append(f"printf '%s' {shlex.quote(digest)} > {MARKER}")
    return "\n".join(lines) + "\n"


def stage(target: StagingTarget, manifest: Manifest) -> bool:
    """Bring the sandbox up to `manifest`. Returns True when it staged, False when already ready."""
    digest = manifest.digest
    if target.read(MARKER) == digest.encode():
        return False
    token = f"{digest[:16]}-{secrets.token_hex(4)}"
    archive_path = f"/tmp/design-agent-stage-{token}.tar.gz"
    check_path = f"/tmp/design-agent-check-{token}.sha256"
    target.upload([(archive_path, manifest.archive()), (check_path, manifest.checklist())])
    result = target.execute(
        staging_script(
            digest=digest,
            archive_path=archive_path,
            check_path=check_path,
            families=manifest.required_families,
        ),
        timeout=300,
    )
    if result.exit_code != 0:
        raise StagingError(_FAILURES.get(result.exit_code or -1, "workspace staging failed"))
    return True


class WorkspaceStagerMiddleware(AgentMiddleware[AgentState[Any], Any, Any]):
    """Stage the workspace before the lead's first model call of each run.

    `target_for` resolves the staging target from the run's runtime on every run; nothing per-run
    is kept on the instance.
    """

    def __init__(
        self, manifest: Manifest, target_for: Callable[[Runtime[Any]], StagingTarget | None]
    ) -> None:
        super().__init__()
        self._manifest = manifest
        self._target_for = target_for

    @property
    def name(self) -> str:
        return "DesignAgentWorkspaceStager"

    def _note(self, error: Exception) -> dict[str, Any]:
        reason = (
            str(error) if isinstance(error, StagingError) else "the sandbox could not be reached"
        )
        return {
            "messages": [
                HumanMessage(
                    content=(
                        "<workspace-status>The design computer is not ready: "
                        f"{reason}. Tell the person in one plain line that rendering is "
                        "unavailable right now and that the next message will retry; do not "
                        "render or run gates in this turn.</workspace-status>"
                    )
                )
            ]
        }

    def before_agent(self, state: AgentState[Any], runtime: Runtime[Any]) -> dict[str, Any] | None:  # noqa: ARG002 - hook signature
        target = self._target_for(runtime)
        if target is None:
            return None
        try:
            stage(target, self._manifest)
        except Exception as error:  # noqa: BLE001 - reported to the model, never silent
            return self._note(error)
        return None

    async def abefore_agent(
        self, state: AgentState[Any], runtime: Runtime[Any]
    ) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.before_agent, state, runtime)
