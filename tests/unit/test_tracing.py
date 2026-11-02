"""The trace says what started a run, where, and what it delivered; nothing about who."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langsmith import RunTree

from design_agent.harness import tasks
from design_agent.middleware import tracing
from design_agent.middleware.background import CHECK_IN_MARK
from design_agent.middleware.quiet import SENTINEL_MARK
from design_agent.middleware.tracing import RunTagsMiddleware, delivered_kind, trigger_of
from design_agent.runtime.waker import wake_marker
from design_agent.tools.delivery import UPLOADED


def slack(kind: str = "message") -> Any:
    event = {"type": kind}
    return SimpleNamespace(
        channel=SimpleNamespace(provider="slack", event=event, raw_event={"user": "U0TESTUSER1"})
    )


@pytest.mark.parametrize(
    ("text", "runtime", "trigger"),
    [
        ("make a poster", slack(), "message"),
        ("make a poster", SimpleNamespace(), "message"),
        (f"t-1 finished\n\n{wake_marker('k1')}", slack("schedule"), "wakeup"),
        (f'{CHECK_IN_MARK} reason="render">\nlook', slack("schedule"), "check_in"),
        (f"{SENTINEL_MARK}>\nrestart", slack("schedule"), "watchdog"),
        ("housekeeping", slack("schedule"), "schedule"),
        ("", slack("interrupt_resume"), "resume"),
    ],
)
def test_the_trigger_is_read_from_our_own_markers_and_the_event_type(
    text: str, runtime: Any, trigger: str
) -> None:
    assert trigger_of(runtime, [HumanMessage(text)]) == trigger


def test_a_helpers_own_trace_says_helper() -> None:
    token = tasks.CURRENT.set(
        tasks.TaskRecord(
            id="t-trace1", thread_id="t", effort="low", label="x", wave=None, started_at=time.time()
        )
    )
    try:
        assert trigger_of(SimpleNamespace(), [HumanMessage("brief")]) == "helper"
    finally:
        tasks.CURRENT.reset(token)


@pytest.fixture
def root(monkeypatch: pytest.MonkeyPatch) -> RunTree:
    run = RunTree(name="design-agent", run_type="chain", session_name="design-agent")
    monkeypatch.setattr(tracing, "trace_runs", lambda: (run, run))
    return run


async def test_the_root_is_tagged_with_trigger_and_surface_and_no_user(root: RunTree) -> None:
    await RunTagsMiddleware(surface="cli").abefore_agent(
        {"messages": [HumanMessage("hi")]}, slack()
    )
    assert root.tags == ["trigger:message", "surface:slack"]
    assert root.metadata == {"trigger": "message", "surface": "slack"}
    assert "U0TESTUSER1" not in str(root.tags) + str(root.metadata)

    other = RunTree(name="x", run_type="chain")
    tracing_runs = tracing.trace_runs
    try:
        tracing.trace_runs = lambda: (other, other)  # type: ignore[assignment]
        await RunTagsMiddleware(surface="cli").abefore_agent(
            {"messages": [HumanMessage("hi")]}, SimpleNamespace()
        )
    finally:
        tracing.trace_runs = tracing_runs  # type: ignore[assignment]
    assert other.tags == ["trigger:message", "surface:cli"]


async def test_a_delivery_tags_the_kinds_of_file_sent(root: RunTree) -> None:
    middleware = RunTagsMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "upload_files",
            "args": {"paths": ["/workspace/a.png", "/workspace/b.mp4", "/workspace/c.png"]},
            "id": "c1",
        }
    )

    async def sent(_request: Any) -> ToolMessage:
        return ToolMessage(content=UPLOADED, tool_call_id="c1")

    async def refused(_request: Any) -> ToolMessage:
        return ToolMessage(content="The workspace file could not be read.", tool_call_id="c1")

    await middleware.awrap_tool_call(request, refused)
    assert not root.tags
    await middleware.awrap_tool_call(request, sent)
    assert root.tags == ["delivered:image", "delivered:video"]
    assert root.metadata["delivered"] == ["image", "video"]


def test_delivered_kinds() -> None:
    assert [delivered_kind(p) for p in ("a.png", "a.mp4", "a.wav", "a.pdf", "a.zip")] == [
        "image",
        "video",
        "audio",
        "pdf",
        "other",
    ]


async def test_labeling_never_costs_a_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> Any:
        raise RuntimeError("tracer gone")

    monkeypatch.setattr(tracing, "trace_runs", broken)
    assert await RunTagsMiddleware().abefore_agent({"messages": []}, SimpleNamespace()) is None
    assert tracing.current_root() is None
