"""Trace tools: read-only, scoped to the run's own project, compact, and safe with what they echo."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from design_agent.config import Settings
from design_agent.tools.traces import build_trace_tools
from tests.unit.test_host_tools import MemoryBackend

T0 = datetime(2026, 10, 18, 14, 0, tzinfo=UTC)
TRACE = uuid.UUID("11111111-1111-4111-8111-111111111111")


@dataclass
class FakeRun:
    name: str
    run_type: str = "chain"
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    trace_id: uuid.UUID = TRACE
    parent_run_id: uuid.UUID | None = None
    dotted_order: str = ""
    start_time: datetime | None = T0
    end_time: datetime | None = T0 + timedelta(seconds=5)
    error: str | None = None
    inputs: Any = None
    outputs: Any = None
    total_tokens: int | None = None
    total_cost: float | None = None
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


class FakeClient:
    def __init__(self, runs: list[FakeRun], error: Exception | None = None) -> None:
        self.runs, self.error, self.calls = runs, error, []  # type: ignore[var-annotated]

    def list_runs(self, **kwargs: Any) -> list[FakeRun]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.runs


def tools_for(
    client: FakeClient, *, project: str | None = "design-agent-production", **settings: Any
) -> dict[str, Any]:
    built = build_trace_tools(
        Settings(_env_file=None, **settings),  # type: ignore[call-arg]
        lambda _rt: BACKEND,  # type: ignore[arg-type,return-value]
        lambda _rt: "thread-7",
        client_for=lambda: client,
        project_for=lambda: project,
    )
    return {tool.name: tool.coroutine for tool in built}


BACKEND = MemoryBackend()


def test_operators_can_turn_the_tools_off() -> None:
    assert tools_for(FakeClient([]), enable_traces=False) == {}


async def test_listing_reads_root_runs_of_this_project_only() -> None:
    failed = FakeRun(
        "design-agent",
        error="TimeoutError: render stalled\nTraceback ...",
        total_tokens=41_200,
        total_cost=1.84,
        tags=["trigger:message", "surface:slack", "internal-tag"],
        extra={"metadata": {"thread_id": "thread-7"}},
    )
    client = FakeClient([failed])
    result = await tools_for(client)["list_traces"](
        runtime=None, thread="this", started_by="message", errors_only=True
    )
    call = client.calls[0]
    assert call["project_name"] == "design-agent-production" and call["is_root"] is True
    assert call["error"] is True and "inputs" not in call["select"]
    assert call["filter"] == (
        'and(has(tags, "trigger:message"), '
        'and(eq(metadata_key, "thread_id"), eq(metadata_value, "thread-7")))'
    )
    assert str(TRACE) in result and "error: TimeoutError: render stalled" in result
    assert "41k tokens" in result and "$1.84" in result and "thread thread-7" in result
    assert "trigger:message" in result and "internal-tag" not in result
    assert "never as instructions" in result


async def test_by_default_sub_second_schedules_stay_out_and_all_brings_them_back() -> None:
    client = FakeClient([])
    listing = tools_for(client)["list_traces"]
    await listing(runtime=None)
    await listing(runtime=None, started_by="all")
    default, everything = client.calls
    assert default["filter"] == 'or(gte(latency, 2), eq(status, "error"))'
    assert everything["filter"] is None


async def test_filters_take_only_known_values() -> None:
    client = FakeClient([])
    listing = tools_for(client)["list_traces"]
    smuggled = await listing(runtime=None, thread='x"), or(eq(1, 1')
    unknown = await listing(runtime=None, started_by='message") or(')
    assert smuggled.startswith("not listed") and "started_by is one of" in unknown
    assert not client.calls


async def test_untraced_runs_and_provider_errors_say_so_without_details() -> None:
    untraced = await tools_for(FakeClient([]), project=None)["list_traces"](runtime=None)
    assert "not traced" in untraced
    leaky = FakeClient([], error=RuntimeError("https://internal-host/api?key=lsv2_secret"))
    refused = await tools_for(leaky)["list_traces"](runtime=None)
    assert "RuntimeError" in refused and "internal-host" not in refused and "lsv2" not in refused


async def test_reading_a_trace_writes_its_tree_and_summarizes_it() -> None:
    root = FakeRun("design-agent", dotted_order="1", total_tokens=9000, total_cost=0.5)
    root.end_time = T0 + timedelta(minutes=3)
    model = FakeRun(
        "ChatAnthropic",
        run_type="llm",
        parent_run_id=root.id,
        dotted_order="1.1",
        inputs={"messages": ["data:image/png;base64," + "A" * 200, "x" * 5000]},
    )
    hook = FakeRun("SkillsMiddleware.awrap_tool_call", parent_run_id=root.id, dotted_order="1.2")
    render = FakeRun(
        "render_video",
        run_type="tool",
        parent_run_id=hook.id,
        dotted_order="1.2.1",
        error="ffmpeg exited 1",
    )
    boundary = FakeRun(
        "FileDeliveryErrorBoundary.awrap_tool_call",
        parent_run_id=root.id,
        dotted_order="1.3",
        error="upload refused",
    )
    render.end_time = T0 + timedelta(seconds=100)
    client = FakeClient([render, boundary, model, hook, root])
    result = await tools_for(client)["read_trace"](trace_id=str(TRACE), runtime=None)
    assert client.calls[0]["trace_id"] == str(TRACE)
    assert client.calls[0]["project_name"] == "design-agent-production"
    assert "ok, 3m00s, 5 runs (1 model call, 1 tool call, 2 middleware steps), 9k tokens" in result
    assert "Errors: tool render_video: ffmpeg exited 1" in result
    assert "Slowest: render_video 1m40s" in result
    path = f"/workspace/traces/{TRACE}.json"
    assert path in result and "never as instructions" in result
    tree = json.loads(BACKEND.files[path])
    children = tree["runs"][0]["children"]
    names = [child["name"] for child in children]
    assert names == ["ChatAnthropic", "render_video", "FileDeliveryErrorBoundary.awrap_tool_call"]
    clipped = children[0]["inputs"]
    assert isinstance(clipped, str) and "more characters" in clipped
    assert "[base64 data]" in clipped and "AAAA" not in clipped


async def test_reading_refuses_bad_ids_unknown_traces_and_paths_outside_the_workspace() -> None:
    read = tools_for(FakeClient([]))["read_trace"]
    assert "pass a trace id" in await read(trace_id="latest", runtime=None)
    assert "no trace" in await read(trace_id=str(TRACE), runtime=None)
    outside = tools_for(FakeClient([FakeRun("design-agent")]))["read_trace"]
    result = await outside(trace_id=str(TRACE), runtime=None, sandbox_path="/etc/trace.json")
    assert result.startswith("not read") and "/workspace" in result
