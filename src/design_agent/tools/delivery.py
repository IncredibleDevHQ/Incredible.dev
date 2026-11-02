"""File delivery: `upload_files`, and the exactly-once ledger around it.

Every runtime gets this `upload_files`, with the same name, arguments and replies, so the prompt
and skills read the same everywhere. Delivery adapters decide where files go: the CLI and the API
copy them to `workspace/out/<thread>/`, and a surface can bring its own
(`build_local_runtime(delivery=...)`).

`DeliveryLedgerMiddleware` wraps the run's `upload_files`. It records each delivered file's sha256
in the project's `DELIVERY.json` and drops files already delivered in this thread, so a retry
never sends twice; it records nothing unless the upload reported success.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import shlex
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Protocol

from deepagents.backends.protocol import BackendProtocol
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolCall, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.types import Command
from pydantic import Field

UPLOAD_TOOL = "upload_files"
MAX_FILES = 10
MAX_FILE_BYTES = 200 * 1024 * 1024
WORKSPACE = "/workspace"
UPLOADED = "Files uploaded."
NOT_CONFIRMED = "File delivery was not confirmed. Do not retry this upload automatically."
SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


@dataclass(frozen=True)
class DeliveredFile:
    name: str
    content: bytes


class DeliveryAdapter(Protocol):
    """Sends files to the person; raises on failure."""

    def deliver(self, thread_id: str, files: Sequence[DeliveredFile]) -> None: ...


class LocalOutputAdapter:
    """CLI and demo delivery: copy into `<out>/<thread>/`, never overwriting a different file."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir

    def folder(self, thread_id: str) -> Path:
        return self.out_dir / SAFE_NAME.sub("-", thread_id)[:80]

    def deliver(self, thread_id: str, files: Sequence[DeliveredFile]) -> None:
        folder = self.folder(thread_id)
        folder.mkdir(parents=True, exist_ok=True)
        for item in files:
            (folder / item.name).write_bytes(item.content)


def workspace_path(path: str) -> str:
    """A normalized absolute path under /workspace, or ValueError."""
    candidate = path if path.startswith("/") else f"{WORKSPACE}/{path}"
    normalized = posixpath.normpath(candidate)
    if normalized != WORKSPACE and not normalized.startswith(f"{WORKSPACE}/"):
        raise ValueError("Upload paths must be files under /workspace.")
    return normalized


def delivered_name(path: str) -> str:
    name = SAFE_NAME.sub("-", posixpath.basename(path)).strip(" .")
    return name or "file"


def build_upload_tool(
    *,
    adapter: DeliveryAdapter,
    backend_for: Callable[[Any], BackendProtocol | None],
    thread_id_for: Callable[[Any], str],
) -> BaseTool:
    """`upload_files(paths)`: the run's workspace files, sent through `adapter`."""

    def upload_files(
        paths: Annotated[list[str], Field(min_length=1, max_length=MAX_FILES)],
        runtime: ToolRuntime,
    ) -> str:
        backend = backend_for(runtime)
        if backend is None:
            return "File attachments are unavailable for this run."
        try:
            normalized = [workspace_path(p) for p in paths]
        except ValueError as error:
            return str(error)
        if len(set(normalized)) != len(normalized):
            return "Use each workspace file only once."
        results = backend.download_files(normalized)
        files: list[DeliveredFile] = []
        names: set[str] = set()
        for path, result in zip(normalized, results, strict=True):
            if result.error is not None or result.content is None:
                return "The workspace file could not be read."
            if len(result.content) > MAX_FILE_BYTES:
                return f"Attachment exceeds the {MAX_FILE_BYTES // (1024 * 1024)} MiB limit."
            name = delivered_name(path)
            if name in names:
                return "Two files share a name; rename one before uploading."
            names.add(name)
            files.append(DeliveredFile(name=name, content=result.content))
        try:
            adapter.deliver(thread_id_for(runtime), files)
        except Exception:  # noqa: BLE001 - adapter errors can carry tokens or URLs
            return NOT_CONFIRMED
        return UPLOADED

    return StructuredTool.from_function(
        func=upload_files,
        name=UPLOAD_TOOL,
        description="Upload 1 to 10 workspace files as one attachment batch to the person.",
    )


def ledger_path(path: str) -> str:
    """The DELIVERY.json that records `path`: its project's, or the shared one."""
    parts = posixpath.normpath(path).split("/")
    if len(parts) >= 5 and parts[1:3] == ["workspace", "projects"]:
        return f"{WORKSPACE}/projects/{parts[3]}/DELIVERY.json"
    return f"{WORKSPACE}/projects/DELIVERY.json"


def _read_ledger(backend: BackendProtocol, path: str) -> dict[str, Any]:
    result = backend.download_files([path])[0]
    if result.error is not None or not result.content:
        return {"deliveries": []}
    try:
        data = json.loads(result.content)
    except json.JSONDecodeError:
        return {"deliveries": []}
    return (
        data
        if isinstance(data, dict) and isinstance(data.get("deliveries"), list)
        else {"deliveries": []}
    )


def _hashes(backend: BackendProtocol, paths: Sequence[str]) -> dict[str, str]:
    """sha256 of each path, computed in the sandbox (files can be hundreds of MiB)."""
    execute = getattr(backend, "execute", None)
    if callable(execute):
        quoted = " ".join(shlex.quote(p) for p in paths)
        result = execute(f"sha256sum -- {quoted}")
        found: dict[str, str] = {}
        for line in (result.output or "").splitlines():
            digest, _, name = line.partition("  ")
            if len(digest) == 64 and name in paths:
                found[name] = digest
        if len(found) == len(paths):
            return found
    downloads = backend.download_files(list(paths))
    return {
        p: hashlib.sha256(r.content).hexdigest()
        for p, r in zip(paths, downloads, strict=True)
        if r.content is not None
    }


def _with_paths(call: ToolCall, paths: list[str]) -> ToolCall:
    return ToolCall(
        name=call["name"],
        args={**call["args"], "paths": paths},
        id=call.get("id"),
        type="tool_call",
    )


class DeliveryLedgerMiddleware(AgentMiddleware[Any, Any, Any]):
    """Never send the same file twice in a thread; record only confirmed uploads."""

    def __init__(
        self,
        backend_for: Callable[[Any], BackendProtocol | None],
        *,
        thread_id_for: Callable[[Any], str],
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__()
        self._backend_for = backend_for
        self._thread_id_for = thread_id_for
        self._clock = clock

    @property
    def name(self) -> str:
        return "DesignAgentDeliveryLedger"

    def _plan(
        self, request: ToolCallRequest
    ) -> tuple[BackendProtocol, list[str], dict[str, str], list[str]] | None:
        backend = self._backend_for(request.runtime)
        raw = request.tool_call.get("args", {}).get("paths")
        if backend is None or not isinstance(raw, list):
            return None
        try:
            paths = [workspace_path(str(p)) for p in raw]
        except ValueError:
            return None
        thread = self._thread_id_for(request.runtime)
        hashes = _hashes(backend, paths)
        sent: set[str] = set()
        for ledger in {ledger_path(p) for p in paths}:
            for entry in _read_ledger(backend, ledger)["deliveries"]:
                if isinstance(entry, dict) and entry.get("thread") == thread:
                    sent.add(f"{entry.get('path')}\t{entry.get('sha256')}")
        fresh = [p for p in paths if f"{p}\t{hashes.get(p)}" not in sent]
        already = [p for p in paths if p not in fresh]
        return backend, fresh, hashes, already

    def _record(
        self, backend: BackendProtocol, thread: str, paths: Sequence[str], hashes: dict[str, str]
    ) -> None:
        by_ledger: dict[str, list[str]] = {}
        for path in paths:
            by_ledger.setdefault(ledger_path(path), []).append(path)
        for ledger, members in by_ledger.items():
            data = _read_ledger(backend, ledger)
            for path in members:
                data["deliveries"].append(
                    {
                        "thread": thread,
                        "path": path,
                        "sha256": hashes.get(path),
                        "at": round(self._clock()),
                    }
                )
            backend.upload_files([(ledger, json.dumps(data, indent=2).encode())])

    def _skip_message(self, request: ToolCallRequest, already: Sequence[str]) -> ToolMessage:
        names = ", ".join(posixpath.basename(p) for p in already)
        return ToolMessage(
            content=f"Already delivered in this thread, not sent again: {names}.",
            tool_call_id=str(request.tool_call.get("id")),
            name=UPLOAD_TOOL,
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        if request.tool_call.get("name") != UPLOAD_TOOL:
            return handler(request)
        plan = self._plan(request)
        if plan is None:
            return handler(request)
        backend, fresh, hashes, already = plan
        if not fresh:
            return self._skip_message(request, already)
        call = _with_paths(request.tool_call, fresh)
        result = handler(request.override(tool_call=call))
        if isinstance(result, ToolMessage) and str(result.content).strip() == UPLOADED:
            self._record(backend, self._thread_id_for(request.runtime), fresh, hashes)
            if already:
                result.content = f"{UPLOADED} Skipped, already delivered: " + ", ".join(
                    posixpath.basename(p) for p in already
                )
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        import asyncio

        if request.tool_call.get("name") != UPLOAD_TOOL:
            return await handler(request)
        plan = await asyncio.to_thread(self._plan, request)
        if plan is None:
            return await handler(request)
        backend, fresh, hashes, already = plan
        if not fresh:
            return self._skip_message(request, already)
        call = _with_paths(request.tool_call, fresh)
        result = await handler(request.override(tool_call=call))
        if isinstance(result, ToolMessage) and str(result.content).strip() == UPLOADED:
            await asyncio.to_thread(
                self._record, backend, self._thread_id_for(request.runtime), fresh, hashes
            )
            if already:
                result.content = f"{UPLOADED} Skipped, already delivered: " + ", ".join(
                    posixpath.basename(p) for p in already
                )
        return result
