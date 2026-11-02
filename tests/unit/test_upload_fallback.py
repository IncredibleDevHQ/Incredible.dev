"""MDA runs without a Slack channel still deliver: files go on the upload call's LangSmith run."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import pytest
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langsmith.run_trees import RunTree
from langsmith.schemas import Attachment

from design_agent.tools import delivery
from design_agent.tools.delivery import (
    TRACE_NOTE,
    UPLOAD_TOOL,
    DeliveredFile,
    TraceAttachmentAdapter,
    UploadFallbackMiddleware,
)


@tool("upload_files")
def ours(paths: list[str]) -> str:
    """Our upload."""
    return "ours"


@tool("upload_files")
def platforms(paths: list[str]) -> str:
    """The platform's upload."""
    return "platform"


@tool
def ls(path: str) -> str:
    """List."""
    return ""


@dataclass
class Request:
    tools: list[Any]
    runtime: Any = "thread-1"
    system_message: SystemMessage | None = field(default_factory=lambda: SystemMessage("base"))
    tool_call: dict[str, Any] = field(default_factory=dict)
    tool: Any = None

    def override(self, **changes: Any) -> Request:
        return replace(self, **changes)


def middleware() -> UploadFallbackMiddleware:
    return UploadFallbackMiddleware(ours, thread_id_for=lambda runtime: str(runtime))


def test_a_run_without_the_platforms_upload_gets_ours_and_a_note() -> None:
    seen: list[Request] = []
    mw = middleware()
    mw.wrap_model_call(Request(tools=[ls]), lambda r: seen.append(r))
    assert [t.name for t in seen[0].tools] == ["ls", UPLOAD_TOOL]
    assert TRACE_NOTE in seen[0].system_message.text  # type: ignore[union-attr]
    call = Request(tools=[], tool_call={"name": UPLOAD_TOOL, "args": {}}, tool=platforms)
    assert mw.wrap_tool_call(call, lambda r: r.tool).name == UPLOAD_TOOL  # type: ignore[arg-type,return-value]
    assert mw.wrap_tool_call(call, lambda r: r.tool) is ours  # type: ignore[arg-type,comparison-overlap]


def test_a_slack_run_keeps_the_platforms_upload() -> None:
    seen: list[Request] = []
    mw = middleware()
    request = Request(tools=[ls, platforms])
    mw.wrap_model_call(request, lambda r: seen.append(r))
    assert seen[0] is request
    call = Request(tools=[], tool_call={"name": UPLOAD_TOOL, "args": {}}, tool=platforms)
    assert mw.wrap_tool_call(call, lambda r: r.tool) is platforms  # type: ignore[arg-type,comparison-overlap]


def test_files_go_on_the_current_run_with_names_langsmith_keeps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = RunTree(name="upload_files", run_type="tool")
    monkeypatch.setattr("langsmith.run_helpers.get_current_run_tree", lambda: run)
    TraceAttachmentAdapter().deliver("t", [DeliveredFile("card-1200x630.png", b"png")])
    assert run.attachments == {"card-1200x630_png": Attachment("image/png", b"png")}
    assert run.metadata["delivered"] == ["card-1200x630.png"]


def test_an_untraced_run_or_an_oversized_file_is_not_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("langsmith.run_helpers.get_current_run_tree", lambda: None)
    with pytest.raises(RuntimeError):
        TraceAttachmentAdapter().deliver("t", [DeliveredFile("a.png", b"x")])
    run = RunTree(name="upload_files", run_type="tool")
    monkeypatch.setattr("langsmith.run_helpers.get_current_run_tree", lambda: run)
    monkeypatch.setattr(delivery, "TRACE_ATTACHMENT_BYTES", 2)
    with pytest.raises(ValueError):
        TraceAttachmentAdapter().deliver("t", [DeliveredFile("a.png", b"xyz")])
    assert not run.attachments
