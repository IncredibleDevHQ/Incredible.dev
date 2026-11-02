"""The web presenter's middleware: a turn's progress cards, steering, and the canvas tools."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from design_agent.surfaces.web.agent import FollowUp
from design_agent.surfaces.web.presenter import (
    STOPPED,
    CanvasToolsMiddleware,
    WebProgressMiddleware,
    WebSteeringMiddleware,
)

THREAD = "th_test"


class Runtime:
    config = {"configurable": {"thread_id": THREAD}}


class FakeHost:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.followups: list[FollowUp] = []
        self.stop = False

    def turn_started(self, thread: str) -> None:
        self.calls.append(("started", thread))

    def turn_step(self, thread: str, step: str, title: str, status: str) -> None:
        self.calls.append(("step", step, title, status))

    def turn_note(self, thread: str, text: str) -> None:
        self.calls.append(("note", text))

    def turn_ended(self, thread: str, *, outcome: str) -> None:
        self.calls.append(("ended", outcome))

    def stop_requested(self, thread: str) -> bool:
        return self.stop

    def take_followups(self, thread: str) -> list[FollowUp]:
        taken, self.followups = self.followups, []
        return taken

    async def compose_followup(self, thread: str, item: FollowUp) -> str:
        return f"While you were working, {item.author} added: {item.text}"

    def uploading(self, thread: str, paths: list[str]) -> None:
        self.calls.append(("uploading", thread, paths))


def _request(name: str, args: dict[str, Any], *, call_id: str = "call-1") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": name, "args": args, "id": call_id, "type": "tool_call"},
        tool=SimpleNamespace(name=name),  # type: ignore[arg-type]
        state={"messages": []},
        runtime=Runtime(),  # type: ignore[arg-type]
    )


async def test_each_step_is_a_card_that_settles() -> None:
    host = FakeHost()
    progress = WebProgressMiddleware(host)  # type: ignore[arg-type]
    await progress.abefore_agent({"messages": []}, Runtime())  # type: ignore[arg-type]

    async def ran(request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content="ok", tool_call_id="call-1")

    await progress.awrap_tool_call(
        _request("read_file", {"file_path": "/workspace/brand/voice.md"}), ran
    )
    steps = [c for c in host.calls if c[0] == "step"]
    assert steps[0][1] == "call-1" and steps[0][3] == "running"
    assert steps[1][3] == "done"
    assert "/workspace" not in steps[0][2]  # a card never carries argument text


async def test_our_canvas_tools_read_in_studio_words() -> None:
    host = FakeHost()
    progress = WebProgressMiddleware(host)  # type: ignore[arg-type]

    async def ran(request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content="ok", tool_call_id="call-1")

    await progress.awrap_tool_call(_request("canvas_publish_board", {"frames": []}), ran)
    assert ("step", "call-1", "Putting the board on the canvas", "running") in host.calls


async def test_the_plan_shows_as_its_own_cards() -> None:
    host = FakeHost()
    progress = WebProgressMiddleware(host)  # type: ignore[arg-type]

    async def ran(request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content="ok", tool_call_id="call-1")

    todos = [
        {"content": "Pose the beats", "status": "in_progress"},
        {"content": "Render", "status": "pending"},
    ]
    await progress.awrap_tool_call(_request("write_todos", {"todos": todos}), ran)
    assert ("step", "todo-0", "Pose the beats", "running") in host.calls
    assert ("step", "todo-1", "Render", "pending") in host.calls


async def test_a_turn_ends_done_quiet_or_stopped() -> None:
    host = FakeHost()
    progress = WebProgressMiddleware(host)  # type: ignore[arg-type]
    request = SimpleNamespace(runtime=Runtime())

    async def answer(_: Any) -> AIMessage:
        return AIMessage(content="Here's the board.")

    await progress.awrap_model_call(request, answer)  # type: ignore[arg-type]
    await progress.aafter_agent({"messages": [AIMessage(content="Here's the board.")]}, Runtime())  # type: ignore[arg-type]
    assert ("step", "answer", "Wrote the reply", "done") in host.calls and host.calls[-1] == (
        "ended",
        "done",
    )
    await progress.aafter_agent({"messages": [AIMessage(content="[quiet]")]}, Runtime())  # type: ignore[arg-type]
    assert host.calls[-1] == ("ended", "quiet")
    await progress.aafter_agent({"messages": [AIMessage(content=STOPPED)]}, Runtime())  # type: ignore[arg-type]
    assert host.calls[-1] == ("ended", "stopped")


async def test_a_model_call_that_fails_ends_the_turn() -> None:
    host = FakeHost()
    middleware = WebProgressMiddleware(host)  # type: ignore[arg-type]

    async def failing(request: Any) -> Any:
        raise RuntimeError("provider down")

    request = SimpleNamespace(runtime=Runtime())
    try:
        await middleware.awrap_model_call(request, failing)  # type: ignore[arg-type]
    except RuntimeError:
        pass
    assert host.calls[-1] == ("ended", "stopped")


async def test_narration_between_steps_is_noted() -> None:
    host = FakeHost()
    progress = WebProgressMiddleware(host)  # type: ignore[arg-type]

    async def narrate(_: Any) -> AIMessage:
        return AIMessage(
            content="Posing the beats.",
            tool_calls=[{"name": "write_file", "args": {}, "id": "c", "type": "tool_call"}],
        )

    await progress.awrap_model_call(SimpleNamespace(runtime=Runtime()), narrate)  # type: ignore[arg-type]
    assert ("note", "Posing the beats.") in host.calls


async def test_follow_ups_are_worked_in_and_stop_ends_the_turn() -> None:
    host = FakeHost()
    steering = WebSteeringMiddleware(host)  # type: ignore[arg-type]
    host.followups = [FollowUp(message_id="m1", author="Maya Chen", text="Use the moss green")]
    added = await steering.abefore_model({"messages": [HumanMessage("Make it")]}, Runtime())  # type: ignore[arg-type]
    assert added is not None and added["messages"][0].id == "steer:m1"
    assert "Maya Chen added: Use the moss green" in added["messages"][0].content
    host.followups = [FollowUp(message_id="m1", author="Maya Chen", text="again")]
    again = await steering.abefore_model(
        {"messages": [HumanMessage("x", id="steer:m1")]}, Runtime()
    )  # type: ignore[arg-type]
    assert again is None  # a follow-up already in the conversation is not added twice
    host.stop = True
    stopped = await steering.abefore_model({"messages": []}, Runtime())  # type: ignore[arg-type]
    assert (
        stopped is not None
        and stopped["jump_to"] == "end"
        and stopped["messages"][0].content == STOPPED
    )


def test_the_canvas_tools_are_offered() -> None:
    tools = CanvasToolsMiddleware(FakeHost()).tools  # type: ignore[arg-type]
    assert sorted(t.name for t in tools) == [
        "canvas_deliver",
        "canvas_publish_board",
        "canvas_read_feedback",
        "canvas_update_asset",
    ]
    schema = next(t for t in tools if t.name == "canvas_publish_board").args
    assert {"project", "title", "frames", "kind", "replaces", "answers", "asset"} <= set(schema)
    assert {"asset", "paths", "note", "draft"} <= set(
        next(t for t in tools if t.name == "canvas_deliver").args
    )
    assert {"asset", "status", "note"} <= set(
        next(t for t in tools if t.name == "canvas_update_asset").args
    )


async def test_an_upload_keeps_where_its_files_live() -> None:
    host = FakeHost()
    middleware = CanvasToolsMiddleware(host)  # type: ignore[arg-type]

    async def handler(request: ToolCallRequest) -> ToolMessage:
        return ToolMessage("Files uploaded.", tool_call_id="call-1")

    paths = ["projects/x/renders/teaser.mp4", "/etc/passwd"]
    await middleware.awrap_tool_call(_request("upload_files", {"paths": paths}), handler)
    assert host.calls == [("uploading", THREAD, ["/workspace/projects/x/renders/teaser.mp4"])]
