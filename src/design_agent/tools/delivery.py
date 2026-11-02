"""File delivery: `upload_files` outside MDA, and the exactly-once ledger around any delivery.

On Managed Deep Agents the Slack channel brings its own `upload_files` tool and drops it from runs
without a channel (the API, Studio); those runs get this one through `UploadFallbackMiddleware`,
which attaches the files to the call's LangSmith run. Every other runtime gets this one too, with
the same name, arguments and replies, so the prompt and skills read the same everywhere. Delivery
adapters decide where files go: the CLI copies them to `workspace/out/`, the self-hosted Slack
adapter uploads them to the thread.

`DeliveryLedgerMiddleware` wraps whichever `upload_files` the run has. It records each delivered
file's sha256 in the project's `DELIVERY.json` and drops files already delivered in this thread,
so a retry never sends twice; it records nothing unless the upload reported success.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import posixpath
import re
import shlex
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Protocol, cast

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


#: LangSmith refuses larger attachments, and skips a name with a period in it.
TRACE_ATTACHMENT_BYTES = 100 * 1024 * 1024
TRACE_NOTE = (
    "This run has no chat channel: `upload_files` attaches files to this run in LangSmith, where "
    "the person opens them from the trace or Studio. Say so when you deliver."
)


class TraceAttachmentAdapter:
    """Delivery for Managed Deep Agents runs without a channel: each file goes on the upload
    call's own run, which the tracer sends as the call ends, so a long job holds nothing."""

    def deliver(self, thread_id: str, files: Sequence[DeliveredFile]) -> None:  # noqa: ARG002
        from langsmith.run_helpers import get_current_run_tree
        from langsmith.schemas import Attachment, Attachments

        run = get_current_run_tree()
        if run is None:
            raise RuntimeError("this run is not traced")
        if any(len(item.content) > TRACE_ATTACHMENT_BYTES for item in files):
            raise ValueError("a file is over the LangSmith attachment limit")
        # A run being written holds attachments to send (`Attachments`), not read-back info.
        attachments = cast("Attachments", run.attachments)
        for item in files:
            mime = mimetypes.guess_type(item.name)[0] or "application/octet-stream"
            attachments[re.sub(r"[^A-Za-z0-9_-]", "_", item.name)] = Attachment(mime, item.content)
        run.add_metadata({"delivered": [item.name for item in files]})


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
    """`upload_files(paths)` for runtimes without MDA's Slack channel."""

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


def _tool_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        name = tool.get("name") or (tool.get("function") or {}).get("name")
        return name if isinstance(name, str) else None
    return getattr(tool, "name", None)


class UploadFallbackMiddleware(AgentMiddleware[Any, Any, Any]):
    """Managed Deep Agents: when the platform drops its `upload_files` from a run (no Slack
    channel), offer `tool` under the same name and run calls to it there.

    MDA's channel middleware wraps every authored one, so the tools a model call sees here already
    say whether the platform's upload is available. The answer is kept per thread for the tool
    calls that follow, and refreshed on each model call."""

    def __init__(self, tool: BaseTool, *, thread_id_for: Callable[[Any], str]) -> None:
        super().__init__()
        self._tool = tool
        self._thread_id_for = thread_id_for
        self._fallback: dict[str, bool] = {}

    @property
    def name(self) -> str:
        return "DesignAgentUploadFallback"

    def _prepare(self, request: Any) -> Any:
        from langchain_core.messages import SystemMessage

        missing = UPLOAD_TOOL not in {_tool_name(t) for t in request.tools}
        thread = self._thread_id_for(request.runtime)
        self._fallback[thread] = missing
        if len(self._fallback) > 512:
            self._fallback.pop(next(iter(self._fallback)))
        if not missing:
            return request
        blocks = list(request.system_message.content_blocks if request.system_message else [])
        blocks.append({"type": "text", "text": TRACE_NOTE})
        return request.override(
            tools=[*request.tools, self._tool], system_message=SystemMessage(content_blocks=blocks)
        )

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return handler(self._prepare(request))

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        return await handler(self._prepare(request))

    def _route(self, request: ToolCallRequest) -> ToolCallRequest:
        if request.tool_call.get("name") == UPLOAD_TOOL and self._fallback.get(
            self._thread_id_for(request.runtime)
        ):
            return request.override(tool=self._tool)
        return request

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        return handler(self._route(request))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        return await handler(self._route(request))
