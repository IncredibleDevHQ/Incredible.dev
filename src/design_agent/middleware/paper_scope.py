"""Paper calls held to the deployment's policy on the host, plus the drafts default and receipts.

The policy is `tools.paper.PaperPolicy`, the same decision the bridge applies in front of Paper
Desktop, so a rolled-back bridge, a Local connection with no bridge at all, or a server whose tool
list grows cannot widen what the model may do. A refusal is one written sentence the model can act
on, never a transport error it would retry.

Model calls: `paper_*` tools the policy does not admit are dropped from what the model sees, and the
first call that carries Paper's tools logs how the advertised list lines up with the policy (a tool
Paper stopped advertising is missing alone). When the deployment names a drafts or brand file, one
line naming them is appended to the system message, so the model can pass `fileId` explicitly.

Tool calls: each `paper_*` call goes through `PaperPolicy.decide`. A file-scoped call that names no
file is aimed at the drafts file. Exports take one host argument the model sees in their schema,
`project` (a folder under /workspace/projects): what Paper returns as file bytes, or in Local mode
the files Paper Desktop just wrote to this machine's Downloads folder (`tools.paper.take_exports`),
is written to that project's `renders/`, the images are replaced by the saved paths so they do not
pile up in context,
and the Paper file id, page id and app link are recorded under `paper` in the project's `run.json`.
Only ids this code validated reach the receipt; no token or header ever does.

Paper's MCP tools are async-only, so there is no sync tool path to fence.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import posixpath
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.messages import SystemMessage, ToolCall, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command

from design_agent.tools.files import BackendFor, WorkspaceError, read_bytes, write_bytes
from design_agent.tools.paper import (
    EXPORT_TOOLS,
    Decision,
    PaperPolicy,
    bare_name,
    check_catalog,
    exported_paths,
    link,
    log_catalog,
    take_exports,
)
from design_agent.tools.projects import PROJECT_SLUG, PROJECTS_ROOT

_LOGGER = logging.getLogger(__name__)

#: Formats Paper exports, by the MIME type its result blocks carry.
_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/avif": "avif",
    "image/svg+xml": "svg",
    "application/pdf": "pdf",
    "video/mp4": "mp4",
    "video/webm": "webm",
}
_PAGE_ID = re.compile(r"[A-Za-z0-9-]{1,64}")
_MAX_EXPORT_BYTES = 200 * 1024 * 1024
_PROJECT_ARG = {
    "type": "string",
    "description": (
        "Host argument: the project folder under /workspace/projects this export belongs to. The "
        "file is saved to its renders/ and the Paper link is recorded in its run.json."
    ),
}

NEEDS_PROJECT = (
    "Pass project (the folder name under /workspace/projects) on a Paper export, so the file "
    "lands in its renders/ and the run keeps a receipt."
)
NO_SANDBOX = "The sandbox is not available for this run, so a Paper export has nowhere to land."


def _refused(call: ToolCall, sentence: str) -> ToolMessage:
    return ToolMessage(
        content=sentence, tool_call_id=call.get("id") or "", name=call["name"], status="error"
    )


def _tool_name(tool: BaseTool | dict[str, Any]) -> str | None:
    name = tool.name if isinstance(tool, BaseTool) else tool.get("name")
    return name if isinstance(name, str) else None


def _with_project(tool: BaseTool) -> BaseTool:
    """An export tool whose schema also asks for the host's `project` argument."""
    schema = tool.args_schema
    if not isinstance(schema, dict) or "project" in (schema.get("properties") or {}):
        return tool
    extended = {
        **schema,
        "properties": {**(schema.get("properties") or {}), "project": _PROJECT_ARG},
        "required": [*(schema.get("required") or []), "project"],
    }
    return tool.model_copy(update={"args_schema": extended})


def _with_note(message: SystemMessage | None, note: str) -> SystemMessage:
    if message is None:
        return SystemMessage(content=note)
    if isinstance(message.content, str):
        return SystemMessage(content=f"{message.content}\n\n{note}")
    return SystemMessage(content=[*message.content, {"type": "text", "text": note}])


def _binary(block: object) -> tuple[bytes, str] | str | None:
    """A result block's file bytes and extension, "unknown" for bytes in a format it does not
    keep, or None for a block that carries no bytes (text, a link)."""
    if not isinstance(block, dict) or block.get("type") not in ("image", "file"):
        return None
    raw = block.get("base64")
    if raw is None and block.get("source_type") == "base64":
        raw = block.get("data")
    if not isinstance(raw, str):
        return None
    extension = _EXTENSIONS.get(str(block.get("mime_type") or "").lower())
    if extension is None:
        return "unknown"
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return "unknown"
    return (data, extension) if 0 < len(data) <= _MAX_EXPORT_BYTES else "unknown"


def _text_of(block: object) -> str | None:
    if isinstance(block, str):
        return block
    if isinstance(block, dict) and block.get("type") == "text":
        text = block.get("text")
        return text if isinstance(text, str) else None
    return None


async def _listed(backend: Any, path: str, *, directory: bool) -> bool:
    """Whether the sandbox lists `path` (a folder or a file) in its parent."""
    try:
        listing = await backend.als(posixpath.dirname(path))
    except Exception:  # noqa: BLE001 - backend errors can carry paths and hosts
        return False
    if listing.error:
        return False
    return any(
        bool(entry.get("is_dir")) == directory and entry["path"].rstrip("/") == path
        for entry in listing.entries or []
    )


class PaperScopeMiddleware(AgentMiddleware[Any, Any, Any]):
    """Hold each `paper_*` call to `PaperPolicy`; aim, export and record as the module says."""

    def __init__(
        self,
        policy: PaperPolicy,
        *,
        backend_for: BackendFor,
        local_exports: bool = False,
        exports_folder: Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__()
        self._policy = policy
        self._backend_for = backend_for
        self._local_exports = local_exports
        self._exports_folder = exports_folder
        self._clock = clock
        self._checked = False

    @property
    def name(self) -> str:
        return "DesignAgentPaperScope"

    # Model calls

    def _prepare(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        admitted = self._policy.admitted
        tools: list[BaseTool | dict[str, Any]] = []
        present: list[str] = []
        changed = False
        for tool in request.tools:
            bare = bare_name(name) if (name := _tool_name(tool)) else None
            if bare is None:
                tools.append(tool)
                continue
            present.append(bare)
            if bare not in admitted:
                changed = True
                continue
            shown = (
                _with_project(tool) if bare in EXPORT_TOOLS and isinstance(tool, BaseTool) else tool
            )
            changed |= shown is not tool
            tools.append(shown)
        if not present:
            return request
        if not self._checked:
            self._checked = True
            log_catalog(check_catalog(present, self._policy))
        overrides: dict[str, Any] = {}
        if changed:
            overrides["tools"] = tools
        note = self._policy.note()
        if note is not None:
            overrides["system_message"] = _with_note(request.system_message, note)
        return request.override(**overrides) if overrides else request

    def wrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], ModelResponse[Any]]
    ) -> ModelResponse[Any]:
        return handler(self._prepare(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(self._prepare(request))

    # Tool calls

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        call = request.tool_call
        tool = bare_name(str(call.get("name") or ""))
        if tool is None:
            return await handler(request)
        args = dict(call.get("args") or {})
        project = args.pop("project", None) if tool in EXPORT_TOOLS else None
        decision = self._policy.decide(tool, args)
        if decision.refusal is not None:
            return _refused(call, decision.refusal)
        if tool in EXPORT_TOOLS:
            return await self._export(request, handler, decision, project)
        if decision.args == call.get("args"):
            return await handler(request)
        return await handler(request.override(tool_call={**call, "args": decision.args}))

    async def _export(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
        decision: Decision,
        project: object,
    ) -> ToolMessage | Command[Any]:
        call = request.tool_call
        if not isinstance(project, str) or not PROJECT_SLUG.fullmatch(project):
            return _refused(call, NEEDS_PROJECT)
        backend = self._backend_for(request.runtime)
        if backend is None:
            return _refused(call, NO_SANDBOX)
        folder = f"{PROJECTS_ROOT}/{project}"
        if not await _listed(backend, folder, directory=True):
            return _refused(
                call,
                f"There is no project folder named {project}; pass the folder under "
                "/workspace/projects this board belongs to.",
            )
        started = self._clock()
        result = await handler(request.override(tool_call={**call, "args": decision.args}))
        if not isinstance(result, ToolMessage) or result.status == "error":
            return result
        blocks = result.content if isinstance(result.content, list) else [result.content]
        kept: list[Any] = []
        files: list[tuple[bytes, str]] = []
        unreadable = 0
        for block in blocks:
            found = _binary(block)
            if isinstance(found, tuple):
                files.append(found)
            elif found is None:
                kept.append(block)
            else:
                unreadable += 1
        if not files and self._local_exports:
            taken = take_exports(
                [text for block in kept if (text := _text_of(block))],
                since=started,
                folder=self._exports_folder,
            )
            if taken:
                files = [(item.data, _EXTENSIONS[item.mime_type]) for item in taken]
                kept = [block for block in kept if not exported_paths(_text_of(block) or "")]
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(self._clock()))
        saved: list[str] = []
        try:
            for index, (data, extension) in enumerate(files, start=1):
                saved.append(
                    await write_bytes(
                        backend, f"{folder}/renders/paper-{stamp}-{index}.{extension}", data
                    )
                )
            recorded = await self._record(backend, folder, decision, saved)
        except WorkspaceError as error:
            return _refused(call, f"Paper exported, but saving it in the sandbox failed: {error}")
        summary = self._summary(folder, saved, unreadable, recorded)
        text_only = all(isinstance(b, str) for b in kept)
        content: Any = (
            "\n".join([*(str(b) for b in kept), summary])
            if text_only
            else [*kept, {"type": "text", "text": summary}]
        )
        return result.model_copy(update={"content": content, "artifact": None})

    async def _record(
        self, backend: Any, folder: str, decision: Decision, saved: Sequence[str]
    ) -> bool:
        """Upsert this export's receipt in the project's run.json; False when an existing one is
        not a JSON object this code can read whole, so it is left as it is."""
        path = f"{folder}/run.json"
        data: Any = {}
        if await _listed(backend, path, directory=False):
            try:
                data = json.loads(await read_bytes(backend, path, cap_mb=1))
            except (WorkspaceError, ValueError, UnicodeError):
                return False
        receipts = data.setdefault("paper", []) if isinstance(data, dict) else None
        if not isinstance(receipts, list) or decision.file is None:
            return False
        page = decision.args.get("pageId")
        page = page if isinstance(page, str) and _PAGE_ID.fullmatch(page) else None
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._clock()))
        for receipt in receipts:
            if isinstance(receipt, dict) and (receipt.get("file_id"), receipt.get("page_id")) == (
                decision.file,
                page,
            ):
                previous = [p for p in receipt.get("exports") or [] if isinstance(p, str)]
                receipt.update(exports=[*previous, *(p for p in saved if p not in previous)], at=at)
                break
        else:
            receipts.append(
                {
                    "file_id": decision.file,
                    "page_id": page,
                    "link": link(decision.file, page),
                    "exports": list(saved),
                    "at": at,
                }
            )
        await write_bytes(backend, path, json.dumps(data, indent=2).encode())
        return True

    @staticmethod
    def _summary(folder: str, saved: Sequence[str], unreadable: int, recorded: bool) -> str:
        run = posixpath.join(folder, "run.json")
        receipt = (
            f"the Paper link is recorded in {run}"
            if recorded
            else f"{run} could not be read as a JSON object, so no receipt was recorded"
        )
        if not saved:
            return (
                "Paper returned no file bytes for this export, so nothing was saved; render the "
                f"board in the sandbox and attach that ({receipt})."
            )
        skipped = (
            f" {unreadable} part(s) in a format this host does not keep were left out."
            if unreadable
            else ""
        )
        return f"Saved {', '.join(saved)}; {receipt}.{skipped}"
