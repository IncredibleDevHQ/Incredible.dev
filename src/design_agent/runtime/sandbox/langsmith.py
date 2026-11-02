"""LangSmith Sandboxes for the local and self-hosted runtimes: one sandbox per thread, cloned from
the snapshot `design-agent sandbox publish` built from the same recipe MDA bakes.

Egress is default-deny: `access_control.allow_list` holds only the hosts the operator lists in
`DESIGN_AGENT_SANDBOX_EGRESS_ALLOW`. Hosts resolving to private, loopback or metadata addresses
are refused by the platform either way.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepagents.backends.langsmith import LangSmithSandbox
from deepagents.backends.protocol import ExecuteResponse, FileDownloadResponse, FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox

from design_agent.config import Settings
from design_agent.runtime.sandbox.docker import current_thread_id

if TYPE_CHECKING:
    from design_agent.runtime.sandbox import SandboxBinding

GIB = 1024**3


def egress_policy(allow: tuple[str, ...]) -> dict[str, Any]:
    """The sandbox proxy config: only `allow` is reachable."""
    return {"access_control": {"allow_list": list(allow)}}


class LangSmithSandboxPool:
    """Thread id -> LangSmith sandbox, created from the snapshot on first use."""

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        if not settings.sandbox_snapshot:
            raise ValueError("DESIGN_AGENT_SANDBOX_SNAPSHOT names the published snapshot to clone")
        if client is None:
            from langsmith.sandbox import SandboxClient

            key = (
                settings.langsmith_api_key.get_secret_value()
                if settings.langsmith_api_key
                else None
            )
            client = SandboxClient(api_key=key)
        self._client = client
        self._settings = settings
        self._lock = threading.Lock()
        self._backends: dict[str, LangSmithSandbox] = {}

    @staticmethod
    def name_for(thread_id: str) -> str:
        return f"design-agent-{hashlib.sha256(thread_id.encode()).hexdigest()[:16]}"

    def backend(self, thread_id: str) -> LangSmithSandbox:
        with self._lock:
            found = self._backends.get(thread_id)
            if found is not None:
                return found
            name = self.name_for(thread_id)
            try:
                sandbox = self._client.get_sandbox(name)
                self._client.start_sandbox(name)
            except Exception:  # noqa: BLE001 - not found (or stopped beyond recovery): create it
                s = self._settings
                sandbox = self._client.create_sandbox(
                    snapshot_id=s.sandbox_snapshot,
                    name=name,
                    idle_ttl_seconds=s.sandbox_idle_ttl_seconds,
                    vcpus=s.sandbox_vcpus,
                    mem_bytes=s.sandbox_mem_gib * GIB,
                    fs_capacity_bytes=s.sandbox_fs_gib * GIB,
                    proxy_config=egress_policy(s.egress_allowlist()),
                )
            backend = LangSmithSandbox(sandbox)
            self._backends[thread_id] = backend
            return backend


class LangSmithThreadBackend(BaseSandbox):
    """The graph's one backend instance, routed to the current thread's sandbox per call."""

    enable_capture_offload = True

    def __init__(
        self, pool: LangSmithSandboxPool, *, thread_id: Callable[[], str] = current_thread_id
    ) -> None:
        self._pool = pool
        self._thread_id = thread_id

    def _current(self) -> LangSmithSandbox:
        return self._pool.backend(self._thread_id())

    @property
    def id(self) -> str:
        return self._pool.name_for(self._thread_id())

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return self._current().execute(command, timeout=timeout)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return self._current().upload_files(files)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return self._current().download_files(paths)


def langsmith_binding(settings: Settings, project_root: Path) -> SandboxBinding:
    from design_agent.middleware.workspace import BackendTarget
    from design_agent.runtime.sandbox import SandboxBinding, _with_skills

    backend = LangSmithThreadBackend(LangSmithSandboxPool(settings))
    return SandboxBinding(
        name="langsmith",
        graph_backend=_with_skills(backend, project_root),
        sandbox=backend,
        staging=BackendTarget(backend),
    )
