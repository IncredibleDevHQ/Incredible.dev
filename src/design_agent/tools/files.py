"""Binary file I/O through the current run's sandbox backend, for host tools."""

from __future__ import annotations

import posixpath
from collections.abc import Callable
from typing import Any

from deepagents.backends.protocol import BackendProtocol

#: Resolves the thread's sandbox backend from a tool's runtime (`RuntimeProfile.backend_for`).
BackendFor = Callable[[Any], BackendProtocol | None]


class WorkspaceError(ValueError):
    """A safe, model-visible error for a sandbox file operation."""


def workspace_path(path: str) -> str:
    """Normalize a path and reject anything outside /workspace.

    This checks the logical path; the sandbox backend owns physical isolation and symlinks. Host
    tools never resolve sandbox paths on the host.
    """
    raw = path.strip()
    if not raw or "\x00" in raw or "\\" in raw:
        raise WorkspaceError("rejected: pass a file path under /workspace.")
    normalized = posixpath.normpath(raw if raw.startswith("/") else f"/workspace/{raw}")
    if not normalized.startswith("/workspace/"):
        raise WorkspaceError("rejected: pass a file path under /workspace.")
    return normalized


def require_backend(backend_for: BackendFor, runtime: Any) -> BackendProtocol:
    """The backend for this call. Never cached between runs."""
    backend = backend_for(runtime)
    if backend is None:
        raise WorkspaceError("sandbox backend unavailable for this run.")
    return backend


async def read_bytes(backend: BackendProtocol, path: str, *, cap_mb: int) -> bytes:
    normalized = workspace_path(path)
    try:
        responses = await backend.adownload_files([normalized])
    except Exception:  # noqa: BLE001 - backend errors can carry paths and hosts
        raise WorkspaceError(f"could not read {normalized}: sandbox read failed.") from None
    if (
        len(responses) != 1
        or responses[0].error
        or responses[0].path != normalized
        or not isinstance(responses[0].content, bytes)
    ):
        raise WorkspaceError(f"could not read {normalized}: file unavailable or unreadable.")
    data = responses[0].content
    if len(data) > cap_mb * 1024 * 1024:
        raise WorkspaceError(f"too large: {normalized} exceeds the {cap_mb} MB limit.")
    return data


async def write_bytes(backend: BackendProtocol, path: str, data: bytes) -> str:
    normalized = workspace_path(path)
    try:
        responses = await backend.aupload_files([(normalized, data)])
    except Exception:  # noqa: BLE001 - backend errors can carry paths and hosts
        raise WorkspaceError(f"could not write {normalized}: sandbox write failed.") from None
    if len(responses) != 1 or responses[0].error or responses[0].path != normalized:
        raise WorkspaceError(f"could not write {normalized}: sandbox write failed.")
    return normalized
