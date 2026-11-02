"""Steering: a person's follow-up while their job runs reaches the running background work.

The lead usually hands work off to background helpers and ends its turn, so a follow-up starts a
lead turn at once. `SteeringToolsMiddleware` gives the lead `steer_task`, and on a person's turn
while helpers run it notes what is running, so the lead can pass the message on ("I've added your
notes to the fix pass that's already running"). The helper's `HelperSteeringMiddleware` adds the
note to its conversation before its next model call: a step in flight (a render) finishes first,
and nothing done is thrown away. Notes live in this process; a helper a restart killed is resumed
from its transcript without unread ones.

Follow-ups that reach the lead's own busy turn come from the runtime's presenter
(`surfaces/presenter.py`), which knows where the thread's people are.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool
from langgraph.config import get_config

from design_agent.harness import tasks
from design_agent.middleware.background import CHECK_IN_MARK
from design_agent.middleware.quiet import SENTINEL_MARK
from design_agent.runtime.waker import wake_key

#: The running-work note's id starts with this, so code looking for what a person asked can
#: pass it over (as it passes over the date note).
RUNNING_NOTE = "running:"
NOTES_KEPT = 20
NOTE_CHARS = 2_000


def _thread_of(runtime: Any = None) -> str:
    """The run's LangGraph thread id, from the ambient run config or the runtime's own."""
    try:
        config: Mapping[str, Any] = get_config()
    except RuntimeError:
        config = getattr(runtime, "config", None) or {}
    return str((config.get("configurable") or {}).get("thread_id") or "")


class SteerNotes:
    """Notes for running helpers, by task id, until each helper's next model call takes them."""

    def __init__(self) -> None:
        self._notes: defaultdict[str, list[str]] = defaultdict(list)

    def add(self, task_id: str, note: str) -> None:
        held = self._notes[task_id]
        held.append(note)
        del held[:-NOTES_KEPT]

    def take(self, task_id: str) -> list[str]:
        return self._notes.pop(task_id, [])


#: The process's notes: a helper outlives the lead's run (and middleware instance) that steered it.
NOTES = SteerNotes()


def _person_turn(messages: list[Any]) -> bool:
    """Whether this turn's input came from a person: no wake-up, check-in or watchdog marker in
    any message since the last reply."""
    inputs: list[str] = []
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            break
        if isinstance(message, HumanMessage):
            inputs.append(
                message.content if isinstance(message.content, str) else str(message.content)
            )
    marked = any(
        wake_key(text) or CHECK_IN_MARK in text or SENTINEL_MARK in text for text in inputs
    )
    return bool(inputs) and not marked


class SteeringToolsMiddleware(AgentMiddleware[AgentState[Any], Any, Any]):
    """The lead's `steer_task`, and a note of the running work on a person's turn (module doc).

    Place it after `BackgroundTaskMiddleware`: that hook reads the newest input for a wake-up's
    marker, which this note must not cover.
    """

    def __init__(self, notes: SteerNotes = NOTES) -> None:
        super().__init__()
        self._notes = notes

        async def steer_task(task_id: str, note: str, runtime: ToolRuntime) -> str:
            """Pass the person's follow-up to a background task that is still running.

            Use it when a message arrives while a helper works and it changes that work: a
            correction, an extra ask, a new constraint. `note` is what the helper should do
            differently, in the person's own words where they matter. The helper reads it before
            its next step; a step already under way (a render) finishes first. Then tell the
            person in a line that their notes reached the running work. To drop the work
            instead, use cancel_task.
            """
            return self.steer(task_id, note, _thread_of(runtime))

        self.tools = [StructuredTool.from_function(coroutine=steer_task, name="steer_task")]

    @property
    def name(self) -> str:
        return "DesignAgentSteeringTools"

    def steer(self, task_id: str, note: str, thread_id: str) -> str:
        task_id = task_id.strip()
        if not task_id.startswith("t-"):
            return f"{task_id} is not a helper; only start_task helpers (t-...) take notes."
        record = tasks.REGISTRY.get(task_id)
        if record is None or record.thread_id != thread_id:
            return f"No running task {task_id} on this thread; check_tasks lists what runs."
        if record.status != "running":
            return f"{task_id} already {record.status}; start the change as new work if it is still needed."
        text = note.strip()[:NOTE_CHARS]
        if not text:
            return "The note is empty; nothing was passed on."
        self._notes.add(record.id, text)
        return f"Passed to {record.id} ({record.label}); it reads the note before its next step."

    async def abefore_agent(self, state: AgentState[Any], runtime: Any) -> dict[str, Any] | None:
        messages = list(state.get("messages") or [])
        running = tasks.running(_thread_of(runtime))
        if not running or not _person_turn(messages):
            return None
        lines = ", ".join(tasks.running_lines(_thread_of(runtime))[:6])
        note = (
            f"[Running in the background now: {lines}. If the message above changes that work, "
            "pass it on with steer_task; to drop it, cancel_task.]"
        )
        return {"messages": [HumanMessage(note, id=f"{RUNNING_NOTE}{uuid.uuid4().hex}")]}


class HelperSteeringMiddleware(AgentMiddleware[AgentState[Any], Any, Any]):
    """A helper takes the lead's notes before its next model call (module doc).

    Place it before `TranscriptCheckpointMiddleware`, so a note is saved with the transcript a
    resumed helper replays.
    """

    def __init__(self, notes: SteerNotes = NOTES) -> None:
        super().__init__()
        self._notes = notes

    @property
    def name(self) -> str:
        return "DesignAgentHelperSteering"

    async def abefore_model(self, state: AgentState[Any], runtime: Any) -> dict[str, Any] | None:  # noqa: ARG002 - hook signature
        record = tasks.CURRENT.get()
        notes = self._notes.take(record.id) if record is not None else []
        if not notes:
            return None
        body = "\n".join(f"- {note}" for note in notes)
        text = (
            "A note from the lead, passing on what the person asked while you work. Follow it "
            f"where it conflicts with your brief, and say in your report what you changed:\n{body}"
        )
        return {"messages": [HumanMessage(text, id=f"steer-note:{uuid.uuid4().hex}")]}

    async def aafter_agent(self, state: AgentState[Any], runtime: Any) -> dict[str, Any] | None:  # noqa: ARG002 - hook signature
        """A note that came after the helper's last step is not lost silently: its report says
        it was not applied, so the lead can start the change as new work."""
        record = tasks.CURRENT.get()
        unread = self._notes.take(record.id) if record is not None else []
        messages = list(state.get("messages") or [])
        last = messages[-1] if messages else None
        if not unread or not isinstance(last, AIMessage):
            return None
        late = f"\n\n(Not applied, it came after my last step: {'; '.join(unread)})"
        content = last.content
        updated = (
            content + late
            if isinstance(content, str)
            else [*content, {"type": "text", "text": late}]
        )
        return {"messages": [AIMessage(content=updated, id=last.id)]}
