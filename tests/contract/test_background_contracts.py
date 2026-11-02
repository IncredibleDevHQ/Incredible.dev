"""Real graph, scripted models, a folder sandbox: background helpers, wake-ups and check-ins.

These pin SPEC §7.2-§7.4: `start_task` returns at once and the turn ends; a helper's progress
waits for the lead's next turn; the lead is woken when the helper finishes, with the report; a
check-in wakes it with its own note; a `[quiet]` reply posts nothing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from design_agent.config import Settings
from design_agent.harness import inbox as inbox_module
from design_agent.harness.tasks import REGISTRY
from design_agent.middleware.today import DATE_NOTE
from design_agent.runtime.local import LocalRuntime, build_local_runtime
from design_agent.testing.fakes import folder_binding
from design_agent.testing.scripted_model import ScriptedChatModel, reply, tool_call

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def fast_inbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(inbox_module, "COALESCE_SECONDS", 0.05)
    monkeypatch.setattr(inbox_module, "RETRY_SECONDS", (0.05, 0.05, 0.05))
    yield
    REGISTRY.clear()


def latest_human(messages: Sequence[BaseMessage]) -> str:
    """The newest input, passing over the date note each turn starts with."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage) and not str(message.id or "").startswith(DATE_NOTE):
            return str(message.content)
    return ""


def build(
    tmp_path: Path, lead: ScriptedChatModel, **roles: ScriptedChatModel
) -> tuple[LocalRuntime, list[tuple[str, str]]]:
    posted: list[tuple[str, str]] = []
    settings = Settings(_env_file=None, workspace_root=tmp_path / "ws")  # type: ignore[call-arg]
    runtime = build_local_runtime(
        settings,
        ROOT,
        model=lead,
        role_models=roles,
        binding=folder_binding(tmp_path / "sandbox", ROOT),
        replies=lambda thread, text: posted.append((thread, text)),
    )
    return runtime, posted


async def test_start_task_returns_at_once_and_the_finish_wakes_the_lead(tmp_path: Path) -> None:
    seen_on_wake: list[str] = []

    def on_wake(messages: Sequence[BaseMessage]) -> AIMessage:
        seen_on_wake.append(latest_human(messages))
        return reply("The frame grabs are ready.")

    lead = ScriptedChatModel(
        steps=[
            lambda _m: tool_call(
                "start_task",
                {"description": "Grab three frames.", "effort": "low", "label": "grabs"},
            ),
            lambda _m: reply("Started the frame grabs; about two minutes."),
            on_wake,
        ]
    )
    helper = ScriptedChatModel(
        steps=[
            lambda _m: tool_call(
                "write_file",
                {"file_path": "/workspace/projects/p/grabs.txt", "content": "3 frames"},
            ),
            lambda _m: tool_call(
                "report_progress", {"note": "Two of three done; one minute left."}
            ),
            lambda _m: reply("Wrote /workspace/projects/p/grabs.txt with 3 frames."),
        ]
    )
    runtime, posted = build(tmp_path, lead, low=helper)

    added = await runtime.ask("Grab three frames from the film.", thread_id="t1")
    assert "two minutes" in str(added[-1].content), "the turn ends on what started, at once"
    assert await runtime.settle(timeout_seconds=30, poll_seconds=0.05)

    assert (tmp_path / "sandbox/workspace/projects/p/grabs.txt").read_text() == "3 frames"
    assert posted == [("t1", "The frame grabs are ready.")]
    notice = seen_on_wake[0]
    assert "grabs" in notice and "3 frames" in notice, "the wake-up carries the helper's report"
    assert "Two of three done" in notice, "held progress rides along with the wake-up"


async def test_workers_refuse_synchronous_task_calls(tmp_path: Path) -> None:
    lead = ScriptedChatModel(
        steps=[
            lambda _m: tool_call("task", {"description": "Render it.", "subagent_type": "max"}),
            lambda m: reply("refused" if "start_task" in str(m[-1].content) else "ran"),
        ]
    )
    runtime, _ = build(tmp_path, lead)
    added = await runtime.ask("Render the film.", thread_id="t2")
    assert added[-1].content == "refused"


async def test_a_check_in_wakes_the_lead_with_its_note_and_quiet_posts_nothing(
    tmp_path: Path,
) -> None:
    notes: list[str] = []

    def on_check_in(messages: Sequence[BaseMessage]) -> AIMessage:
        notes.append(latest_human(messages))
        return reply("[quiet]")

    lead = ScriptedChatModel(
        steps=[
            lambda _m: tool_call(
                "schedule_wakeup",
                {"minutes": 1, "prompt": "See if the render finished.", "reason": "render check"},
            ),
            lambda _m: reply("I'll check on the render in a minute."),
            on_check_in,
        ]
    )
    runtime, posted = build(tmp_path, lead)

    async def instant(_delay: float) -> None:
        await asyncio.sleep(0)

    runtime.waker.sleep = instant  # one minute is the floor; fire the check-in at once
    await runtime.ask("Render the teaser and keep me posted.", thread_id="t3")
    assert await runtime.settle(timeout_seconds=10, poll_seconds=0.05)
    assert notes and "See if the render finished." in notes[0]
    assert posted == [], "a [quiet] reply posts nothing"


async def test_a_failed_helper_wakes_the_lead_with_the_failure(tmp_path: Path) -> None:
    seen: list[str] = []

    def on_wake(messages: Sequence[BaseMessage]) -> AIMessage:
        seen.append(latest_human(messages))
        return reply("The build failed; I'll retry it.")

    def explode(_m: Sequence[BaseMessage]) -> AIMessage:
        raise RuntimeError("provider exploded")

    lead = ScriptedChatModel(
        steps=[
            lambda _m: tool_call(
                "start_task", {"description": "Build act 1.", "effort": "xhigh", "label": "act 1"}
            ),
            lambda _m: reply("Act 1 is building."),
            on_wake,
        ]
    )
    runtime, posted = build(tmp_path, lead, xhigh=ScriptedChatModel(steps=[explode]))
    await runtime.ask("Build act 1.", thread_id="t4")
    assert await runtime.settle(timeout_seconds=30, poll_seconds=0.05)
    assert "act 1" in seen[0] and "failed" in seen[0].lower()
    assert posted == [("t4", "The build failed; I'll retry it.")]


async def test_a_restart_reports_the_helper_interrupted_and_resume_continues_its_transcript(
    tmp_path: Path,
) -> None:
    import threading

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from design_agent.harness import ledger

    store, checkpointer = InMemoryStore(), InMemorySaver()
    release = threading.Event()

    def stuck(_m: Sequence[BaseMessage]) -> AIMessage:
        release.wait(timeout=30)
        return reply("too late")

    first_helper = ScriptedChatModel(
        steps=[
            lambda _m: tool_call(
                "write_file",
                {"file_path": "/workspace/projects/p/act2.html", "content": "<h1>half</h1>"},
            ),
            stuck,
        ]
    )
    first_lead = ScriptedChatModel(
        steps=[
            lambda _m: tool_call(
                "start_task",
                {
                    "description": "Build act 2 into /workspace/projects/p/act2.html.",
                    "effort": "xhigh",
                    "label": "act 2",
                },
            ),
            lambda _m: reply("Act 2 is building."),
        ]
    )
    settings = Settings(_env_file=None, workspace_root=tmp_path / "ws")  # type: ignore[call-arg]
    binding = folder_binding(tmp_path / "sandbox", ROOT)
    first = build_local_runtime(
        settings,
        ROOT,
        model=first_lead,
        role_models={"xhigh": first_helper},
        binding=binding,
        checkpointer=checkpointer,
        store=store,
        replies=lambda *_: None,
    )
    await first.ask("Build act 2.", thread_id="t5")
    for _ in range(200):
        if first_helper.call_count >= 2:
            break
        await asyncio.sleep(0.02)
    (task_id,) = list(REGISTRY)
    REGISTRY[task_id].handle.cancel()  # the deploy: the process stops the helper mid-call
    await asyncio.sleep(0.1)
    item = await store.aget(ledger.LEDGER, task_id)
    await store.aput(
        ledger.LEDGER, task_id, {**item.value, "alive_at": 0}
    )  # its heartbeat is stale
    REGISTRY.clear()
    release.set()

    restored: list[list[BaseMessage]] = []

    def resumed_step(messages: Sequence[BaseMessage]) -> AIMessage:
        restored.append(list(messages))
        return tool_call(
            "write_file",
            {"file_path": "/workspace/projects/p/act2-final.html", "content": "<h1>done</h1>"},
        )

    notices: list[str] = []

    def on_interrupted(messages: Sequence[BaseMessage]) -> AIMessage:
        notices.append(latest_human(messages))
        return tool_call("resume_task", {"task_id": task_id})

    second_lead = ScriptedChatModel(
        steps=[
            lambda _m: reply("Let me check on act 2."),
            on_interrupted,
            lambda _m: reply("A restart stopped act 2; I picked it up where it left off."),
            lambda _m: reply("Act 2 is finished."),
        ]
    )
    second_helper = ScriptedChatModel(
        steps=[resumed_step, lambda _m: reply("Act 2 finished in act2-final.html.")]
    )
    posted: list[tuple[str, str]] = []
    second = build_local_runtime(
        settings,
        ROOT,
        model=second_lead,
        role_models={"xhigh": second_helper},
        binding=binding,
        checkpointer=checkpointer,
        store=store,
        replies=lambda thread, text: posted.append((thread, text)),
    )
    await second.ask("How is act 2 going?", thread_id="t5")
    assert await second.settle(timeout_seconds=30, poll_seconds=0.05)

    assert notices and "interrupted" in notices[0].lower() and "act 2" in notices[0]
    flat = " ".join(str(m.content) for m in restored[0])
    assert "act2.html" in flat, "the resumed helper starts from its saved transcript, not the brief"
    assert (tmp_path / "sandbox/workspace/projects/p/act2-final.html").exists()
    assert ("t5", "Act 2 is finished.") in posted
