"""A follow-up reaches the running work: a helper takes the lead's note at its next model call,
and a person's turn while helpers run notes what is running."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from design_agent.harness import tasks
from design_agent.middleware.background import CHECK_IN_MARK
from design_agent.middleware.steering import (
    RUNNING_NOTE,
    HelperSteeringMiddleware,
    SteeringToolsMiddleware,
    SteerNotes,
)
from design_agent.runtime.waker import wake_marker

THREAD = "t-steer"
RUNTIME = SimpleNamespace(config={"configurable": {"thread_id": THREAD}})


def state(*messages: Any) -> dict[str, Any]:
    return {"messages": list(messages)}


@pytest.fixture
def helper() -> Any:
    record = tasks.TaskRecord(
        id="t-steer1",
        thread_id=THREAD,
        effort="xhigh",
        label="fix pass",
        wave=None,
        started_at=time.time(),
    )
    tasks.REGISTRY[record.id] = record
    yield record
    tasks.REGISTRY.pop(record.id, None)


async def test_a_note_for_a_running_helper_reaches_its_next_model_call_once(
    helper: tasks.TaskRecord,
) -> None:
    notes = SteerNotes()
    lead = SteeringToolsMiddleware(notes)
    said = lead.steer(helper.id, "Make the title blue, the person asked.", THREAD)
    assert "fix pass" in said and helper.id in said

    tasks.CURRENT.set(helper)
    worker = HelperSteeringMiddleware(notes)
    update = await worker.abefore_model(state(HumanMessage("brief")), RUNTIME)
    (note,) = update["messages"]
    assert isinstance(note, HumanMessage) and "Make the title blue" in note.content
    assert await worker.abefore_model(state(HumanMessage("brief"), note), RUNTIME) is None


async def test_a_note_that_came_too_late_is_named_in_the_helpers_report(
    helper: tasks.TaskRecord,
) -> None:
    """A helper that ended before its next model call never read the note: its report says so,
    so the lead can start the change as new work instead of claiming it was made."""
    notes = SteerNotes()
    SteeringToolsMiddleware(notes).steer(helper.id, "Make the title blue.", THREAD)
    tasks.CURRENT.set(helper)
    final = AIMessage(content="Rendered the title card.", id="final")
    update = await HelperSteeringMiddleware(notes).aafter_agent(
        state(HumanMessage("brief"), final), RUNTIME
    )
    (report,) = update["messages"]
    assert report.id == "final" and report.content.startswith("Rendered the title card.")
    assert "Not applied" in report.content and "Make the title blue." in report.content


async def test_steering_refuses_what_it_cannot_reach(helper: tasks.TaskRecord) -> None:
    lead = SteeringToolsMiddleware(SteerNotes())
    assert "not a helper" in lead.steer("p-abc123", "x", THREAD)
    assert "No running task" in lead.steer("t-nope00", "x", THREAD)
    assert "No running task" in lead.steer(helper.id, "x", "another-thread")
    assert "empty" in lead.steer(helper.id, "   ", THREAD)
    helper.status = "done"
    assert "already done" in lead.steer(helper.id, "x", THREAD)


async def test_a_persons_turn_while_helpers_run_notes_what_is_running(
    helper: tasks.TaskRecord,
) -> None:
    """So the lead can pass a correction on instead of starting the work again."""
    lead = SteeringToolsMiddleware(SteerNotes())
    update = await lead.abefore_agent(
        state(AIMessage("Started the fix pass."), HumanMessage("make it blue")), RUNTIME
    )
    (note,) = update["messages"]
    assert str(note.id).startswith(RUNNING_NOTE)
    assert helper.id in note.content and "fix pass" in note.content and "steer_task" in note.content


@pytest.mark.parametrize(
    "text",
    [f"news\n\n{wake_marker('k1')}", f'{CHECK_IN_MARK} reason="x">\nlook', "<watchdog>\nrestart"],
)
async def test_no_running_note_on_a_turn_no_person_started(
    helper: tasks.TaskRecord, text: str
) -> None:
    lead = SteeringToolsMiddleware(SteerNotes())
    assert await lead.abefore_agent(state(HumanMessage(text)), RUNTIME) is None


async def test_no_running_note_when_nothing_runs() -> None:
    lead = SteeringToolsMiddleware(SteerNotes())
    assert await lead.abefore_agent(state(HumanMessage("make it blue")), RUNTIME) is None
