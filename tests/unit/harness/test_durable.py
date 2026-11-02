"""Durable helpers: a helper's transcript is saved as it works and restored after a restart."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages
from langgraph.store.memory import InMemoryStore
from pydantic import Field

from design_agent.harness import durable
from design_agent.harness.durable import (
    CURRENT_TASK,
    TranscriptCheckpointMiddleware,
    TranscriptStore,
    can_resume,
    resume_brief,
    save_on_cancel,
)


class _Scripted(FakeMessagesListChatModel):
    """Answers from its script in order and keeps every input it was sent. At turn `hang_at` it
    never answers, like a long model call a restart cuts off."""

    seen: list[Any] = Field(default_factory=list)
    hang_at: int = -1

    def bind_tools(self, *_args, **_kwargs):
        return self

    async def _agenerate(self, messages, *args, **kwargs):
        self.seen.append(list(messages))
        turn = len(self.seen) - 1
        if turn == self.hang_at:
            await asyncio.Event().wait()
        return ChatResult(generations=[ChatGeneration(message=self.responses[turn])])


@pytest.fixture(autouse=True)
def _fresh_process():
    yield
    durable._PROGRESS.clear()


def _call(name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def _step(n: int) -> AIMessage:
    return AIMessage(content="", tool_calls=[_call("step", {"n": n}, f"c{n}")])


def _worker(
    model: _Scripted,
    store: InMemoryStore,
    done: list[str],
    rendering: asyncio.Event | None = None,
) -> Any:
    """A tiny worker: a scripted model, two tools that log what ran, and the middleware."""

    @tool
    async def step(n: int) -> str:
        """Do step n of the job."""
        done.append(f"step {n}")
        return f"step {n} done"

    @tool
    async def render(scene: str) -> str:
        """Render a scene: a long job."""
        done.append(f"render {scene}")
        if rendering is not None:
            rendering.set()
        await asyncio.Event().wait()
        return "rendered"

    return create_agent(
        model, tools=[step, render], middleware=[TranscriptCheckpointMiddleware(lambda: store)]
    )


def _start(graph: Any, brief: str, task_id: str) -> asyncio.Task[Any]:
    """Run the worker the way the host runs a helper: detached, with `CURRENT_TASK` naming it."""
    token = CURRENT_TASK.set(task_id)
    try:
        return asyncio.get_running_loop().create_task(
            graph.ainvoke({"messages": [HumanMessage(brief)]})
        )
    finally:
        CURRENT_TASK.reset(token)


async def _kill(run: asyncio.Task[Any], task_id: str) -> int:
    """A restart: the helper's coroutine is cancelled, and the host flushes what it can."""
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    return await save_on_cancel(task_id)


async def test_a_transcript_round_trips_with_images_stubbed_and_thinking_stripped() -> None:
    store = InMemoryStore()
    image = {"type": "image", "base64": "iVBORw0KGgoAAAANSUhEUg" * 50, "mime_type": "image/png"}
    still = "/workspace/projects/film/still.png"
    look = AIMessage(
        content=[
            {"type": "thinking", "thinking": "The act needs its still.", "signature": "sig-1"},
            {"type": "redacted_thinking", "data": "opaque-bytes"},
            {"type": "text", "text": "Checking the still."},
            {"type": "tool_use", "id": "c1", "name": "read_file", "input": {"file_path": still}},
        ],
        tool_calls=[_call("read_file", {"file_path": still}, "c1")],
        id="a1",
    )
    viewed = ToolMessage(
        content=[image], tool_call_id="c1", name="read_file", id="t1", artifact={"raw": b"\x89PNG"}
    )
    grab = AIMessage(content="", tool_calls=[_call("grab_frame", {"frame": 12}, "c2")], id="a2")
    grabbed = ToolMessage(
        content=[
            {"type": "text", "text": "Frame 12:"},
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"},
            },
        ],
        tool_call_id="c2",
        additional_kwargs={"read_file_path": "/workspace/projects/film/frames/12.png"},
        id="t2",
    )
    reference = HumanMessage(
        content=[
            {"type": "text", "text": "Match this reference."},
            {"type": "image_url", "image_url": {"url": "https://example.com/reference.png"}},
        ],
        id="h2",
    )
    thought_only = AIMessage(content=[{"type": "thinking", "thinking": "hm", "signature": "s"}])
    answer = AIMessage(
        content=[
            {"type": "thinking", "thinking": "It matches.", "signature": "sig-2"},
            {"type": "text", "text": "The still matches the reference."},
        ],
        id="a3",
    )

    transcripts = TranscriptStore(store)
    await transcripts.append("t-1", [HumanMessage("Build act 3.", id="h1"), look])
    await transcripts.append("t-1", [viewed, grab, grabbed, reference, thought_only, answer])
    await transcripts.append("t-1", [answer])  # saved twice, as a retried save would

    loaded = await TranscriptStore(store).load("t-1")  # a later process
    assert [m.id for m in loaded] == ["h1", "a1", "t1", "a2", "t2", "h2", "a3"]
    assert loaded[1].tool_calls == look.tool_calls
    assert loaded[1].content == [look.content[2], look.content[3]]
    assert loaded[2].content == [{"type": "text", "text": f"[image you viewed: {still}]"}]
    assert loaded[2].tool_call_id == "c1" and loaded[2].artifact is None
    assert loaded[4].content[1] == {
        "type": "text",
        "text": "[image you viewed: /workspace/projects/film/frames/12.png]",
    }
    assert loaded[5].content[1] == {"type": "text", "text": "[image you viewed earlier]"}
    assert loaded[6].content == [{"type": "text", "text": "The still matches the reference."}]

    saved = json.dumps([item.value for item in await store.asearch(durable.NAMESPACE, limit=50)])
    assert "iVBORw0KGgo" not in saved and "QUJD" not in saved and "reference.png" not in saved
    assert "thinking" not in saved and "opaque-bytes" not in saved
    # Only the saved copies change; the helper's live messages are untouched.
    assert viewed.content == [image] and look.content[0]["type"] == "thinking"


async def test_each_step_is_saved_once_as_it_happens() -> None:
    store = InMemoryStore()
    model = _Scripted(responses=[_step(1), _step(2), AIMessage("Both steps are done.")])
    result = await _start(_worker(model, store, []), "Do two steps.", "t-steps")

    chunks = await TranscriptStore(store)._chunks("t-steps")
    assert [len(value["messages"]) for _, value in chunks] == [1, 1, 1, 1, 1, 1]
    saved = [message for _, value in chunks for message in value["messages"]]
    assert [m["type"] for m in saved] == ["human", "ai", "tool", "ai", "tool", "ai"]
    assert [m["data"]["id"] for m in saved] == [m.id for m in result["messages"]]


async def test_the_worker_saves_nothing_outside_a_background_task() -> None:
    """The same worker run in the lead's own turn (no `CURRENT_TASK`) keeps no transcript."""
    store = InMemoryStore()
    graph = _worker(_Scripted(responses=[_step(1), AIMessage("Done.")]), store, [])
    await graph.ainvoke({"messages": [HumanMessage("Do one step.")]})
    assert await store.asearch(durable.NAMESPACE) == []


async def test_past_the_size_cap_the_brief_and_the_latest_steps_are_kept() -> None:
    store = InMemoryStore()
    transcripts = TranscriptStore(store, max_bytes=6_000)
    await transcripts.append("t-big", [HumanMessage("Build the hero act.", id="brief")])
    for n in range(1, 21):
        await transcripts.append("t-big", [_step(n)])
        await transcripts.append("t-big", [ToolMessage(f"{n}:" + "x" * 400, tool_call_id=f"c{n}")])

    items = await store.asearch(TranscriptStore.namespace("t-big"), limit=100)
    keys = {item.key for item in items}
    assert sum(item.value["bytes"] for item in items) <= 6_000 and len(items) < 41
    assert {"00000000", "00000040"} <= keys

    loaded = await TranscriptStore(store).load("t-big")
    assert loaded[0].content == "Build the hero act."
    assert isinstance(loaded[1], HumanMessage) and "Earlier work was dropped" in loaded[1].text
    assert isinstance(loaded[2], AIMessage)  # a result whose call was dropped goes with it
    assert isinstance(loaded[-1], ToolMessage) and loaded[-1].tool_call_id == "c20"
    called: set[str] = set()
    for message in loaded:
        if isinstance(message, AIMessage):
            called |= {call["id"] for call in message.tool_calls}
        elif isinstance(message, ToolMessage):
            assert message.tool_call_id in called


async def test_a_resume_brief_is_swapped_for_the_saved_transcript() -> None:
    store = InMemoryStore()
    saved = TranscriptStore(store)
    await saved.append(
        "t-abc123",
        [
            HumanMessage("Build act 3.", id="h1"),
            AIMessage(content="", tool_calls=[_call("step", {"n": 1}, "c1")], id="a1"),
        ],
    )
    await saved.append("t-abc123", [ToolMessage("step 1 done", tool_call_id="c1", id="t1")])
    middleware = TranscriptCheckpointMiddleware(lambda: store)
    runtime = SimpleNamespace(store=None)  # a detached helper's runtime has no store
    brief = HumanMessage(resume_brief("t-abc123"), id="brief")
    assert brief.text.startswith("[resume t-abc123]")

    token = CURRENT_TASK.set("t-abc123")
    try:
        update = await middleware.abefore_agent({"messages": [brief]}, runtime)
    finally:
        CURRENT_TASK.reset(token)

    assert update is not None
    remove, *restored, closing = update["messages"]
    assert isinstance(remove, RemoveMessage) and remove.id == REMOVE_ALL_MESSAGES
    assert [m.id for m in restored] == ["h1", "a1", "t1"]
    assert closing.text.startswith("You were interrupted at ")
    assert closing.text.endswith(
        "images you viewed are replaced by their file paths, so re-open any you need. Continue "
        "from where you stopped; don't redo finished steps. Your brief is the first message."
    )
    # The reducer replaces the state rather than appending to it: the one-line brief is gone.
    state = add_messages([brief], update["messages"])
    assert [m.id for m in state] == ["h1", "a1", "t1", closing.id]

    # Any other brief runs as written, and so does a resume with nothing saved: its own text
    # tells the helper to say so, and the lead re-issues the brief.
    fresh = {"messages": [HumanMessage("Build act 4.")]}
    nothing = {"messages": [HumanMessage(resume_brief("t-none"))]}
    assert await middleware.abefore_agent(fresh, runtime) is None
    assert await middleware.abefore_agent(nothing, runtime) is None
    assert await can_resume(store, "t-abc123")
    assert not await can_resume(store, "t-none") and not await can_resume(None, "t-abc123")


async def test_a_helper_killed_mid_run_resumes_without_redoing_its_steps() -> None:
    """End to end: three steps, a restart during the fourth model call, then a resume."""
    store = InMemoryStore()
    done: list[str] = []
    model = _Scripted(responses=[_step(1), _step(2), _step(3), AIMessage("never")], hang_at=3)
    run = _start(_worker(model, store, done), "Do four steps, one at a time.", "t-e2e")
    while len(model.seen) < 4:  # steps 1-3 are done; the fourth model call hangs
        await asyncio.sleep(0.01)
    assert await _kill(run, "t-e2e") == 0  # every step was already saved
    assert await can_resume(store, "t-e2e")

    # A new process: a fresh worker, the same store, the resume brief.
    resumed = _Scripted(responses=[_step(4), AIMessage("All four steps are done.")])
    result = await _start(_worker(resumed, store, done), resume_brief("t-e2e"), "t-e2e")

    history = resumed.seen[0]
    assert [type(m).__name__ for m in history] == [
        "HumanMessage",
        *["AIMessage", "ToolMessage"] * 3,
        "HumanMessage",
    ]
    assert history[0].text == "Do four steps, one at a time."
    calls = [
        call["args"]["n"] for m in history if isinstance(m, AIMessage) for call in m.tool_calls
    ]
    assert calls == [1, 2, 3]
    assert [m.text for m in history if isinstance(m, ToolMessage)] == [
        "step 1 done",
        "step 2 done",
        "step 3 done",
    ]
    assert history[-1].text.startswith("You were interrupted at ")
    assert not any("[resume " in m.text for m in history)
    assert done == ["step 1", "step 2", "step 3", "step 4"]
    assert result["messages"][-1].text == "All four steps are done."
    # The transcript carries on under the same id, so a second restart loses nothing either.
    again = await TranscriptStore(store).load("t-e2e")
    assert len(again) == 11 and again[-1].text == "All four steps are done."


async def test_a_restart_during_a_tool_call_keeps_what_returned_and_marks_the_rest() -> None:
    store = InMemoryStore()
    done: list[str] = []
    rendering = asyncio.Event()
    both = AIMessage(
        content="",
        tool_calls=[_call("step", {"n": 1}, "c1"), _call("render", {"scene": "hero"}, "c2")],
    )
    run = _start(
        _worker(_Scripted(responses=[both]), store, done, rendering), "Render act 3.", "t-render"
    )
    await asyncio.wait_for(rendering.wait(), 5)
    while not durable._PROGRESS["t-render"].returned:  # step 1 is back; the render still runs
        await asyncio.sleep(0.01)
    assert await _kill(run, "t-render") == 1  # step 1's result, flushed on the way down

    resumed = _Scripted(responses=[AIMessage("The render was cut off; starting it again.")])
    await _start(_worker(resumed, store, done), resume_brief("t-render"), "t-render")

    results = {m.tool_call_id: m for m in resumed.seen[0] if isinstance(m, ToolMessage)}
    assert results["c1"].text == "step 1 done"
    assert results["c2"].status == "error"
    assert "interrupted by the restart" in results["c2"].text and "unknown" in results["c2"].text
    assert sorted(done) == ["render hero", "step 1"]  # the resume re-ran nothing by itself
