"""Steering: a person's follow-up while their job runs reaches the running work.

What Managed Deep Agents 0.9.3 does with a second Slack message (its public Trigger ingress):
every message becomes a run on the LangGraph thread of its Slack thread (`uuid5` of the source
thread key) with `multitask_strategy="enqueue"`. A follow-up in the same Slack thread therefore
waits behind the run at work and starts when it ends; nothing public lets a run take input
mid-flight, interrupt the run at work, or end a run without a post (an empty reply reposts the
newest earlier answer). A top-level DM message is a source thread of its own: its run starts at
once, beside the run at work, with neither its history nor its sandbox.

So steering happens in two places, both on public APIs:

- **Background helpers** (the usual case: the lead hands work off and its turn ends, so the
  follow-up starts a lead turn at once). `SteeringToolsMiddleware` gives the lead `steer_task`,
  and on a person's turn while helpers run it notes what is running, so the lead can pass the
  message on ("I've added your notes to the fix pass that's already running"). The helper's
  `HelperSteeringMiddleware` adds the note to its conversation before its next model call: a step
  in flight (a render) finishes first, and nothing done is thrown away. Notes live in this
  process; a helper a restart killed is resumed from its transcript without unread ones.
- **The lead's own busy run** in a Slack thread. `LeadSteeringMiddleware` reads the thread before
  each model call (one shared read per thread per `followups.TTL_SECONDS`) and adds each
  follow-up as the person's message under a stable id (`steer_id`). The run MDA queued for that
  message then finds its id in the history and ends at once with one line, without a model call.
  A follow-up leading with "stop" (or cancel, abort, never mind) ends the run at its next step,
  and its own queued run answers it as a new request. Files a follow-up brings are fetched on the
  host into `/workspace/attachments/` under MDA's own naming.

A failed Slack read leaves the run unsteered; nothing here costs a run its work.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import Any

from deepagents.backends.protocol import BackendProtocol
from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool

from design_agent.harness import tasks
from design_agent.middleware.background import CHECK_IN_MARK
from design_agent.middleware.quiet import SENTINEL_MARK
from design_agent.runtime.waker import wake_key
from design_agent.surfaces.slack.client import SlackError
from design_agent.surfaces.slack.followups import MAX_FILE_BYTES, FollowUp, attachment_path, is_stop
from design_agent.surfaces.slack.target import SlackBinding, SlackSurface, thread_of
from design_agent.tools.files import WorkspaceError, write_bytes

_LOGGER = logging.getLogger(__name__)

#: The running-work note's id starts with this, so code looking for what a person asked can
#: pass it over (as it passes over the date note).
RUNNING_NOTE = "running:"
#: What the queued run for a follow-up this thread already took says, and what a stopped run says.
TAKEN = "Folded that into the work above."
STOPPED = "Stopped here, as you asked. I'll take your new message next."
NOTES_KEPT = 20
NOTE_CHARS = 2_000


def steer_id(channel: str, ts: str) -> str:
    """The id a follow-up carries in the lead's history: one Slack message, one id."""
    return f"steer:{channel}:{ts}"


# -- background helpers -----------------------------------------------------------------------


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
            return self.steer(task_id, note, thread_of(runtime))

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
        running = tasks.running(thread_of(runtime))
        if not running or not _person_turn(messages):
            return None
        lines = ", ".join(tasks.running_lines(thread_of(runtime))[:6])
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


# -- the lead's own run, in a Slack thread ----------------------------------------------------


def _as_message(follow_up: FollowUp, files: Sequence[str]) -> str:
    """The follow-up as the person's message, saying it came mid-run and what it brought."""
    brought = "".join(f"\n(attached: {path})" for path in files)
    return f"While you were working, the person added: {follow_up.text}{brought}"


class LeadSteeringMiddleware(AgentMiddleware[AgentState[Any], Any, Any]):
    """Fold a Slack thread's follow-ups into the lead's running turn (module doc).

    `backend_for` resolves the thread's sandbox, so a follow-up's files are staged; without it
    a file is named, not staged. Place it before `ReplyFooterMiddleware` and the progress
    middleware, so a queued run it ends at once registers with neither.
    """

    def __init__(
        self,
        surface: SlackSurface,
        *,
        backend_for: Callable[[Any], BackendProtocol | None] | None = None,
    ) -> None:
        super().__init__()
        self._surface = surface
        self._backend_for = backend_for
        #: When each Slack thread's run began, for a run no message started (a wake-up).
        self._since: dict[tuple[str, str], str] = {}

    @property
    def name(self) -> str:
        return "DesignAgentLeadSteering"

    @hook_config(can_jump_to=["end"])
    async def abefore_agent(self, state: AgentState[Any], runtime: Any) -> dict[str, Any] | None:
        """End a run whose message an earlier run already took; otherwise note when it began."""
        binding = await self._surface.bind(runtime)
        if binding is None:
            return None
        target = binding.target
        if target.message_ts:
            taken = steer_id(target.channel, target.message_ts)
            if any(getattr(m, "id", None) == taken for m in state.get("messages") or []):
                return {"messages": [AIMessage(content=TAKEN)], "jump_to": "end"}
        self._since[target.key] = target.message_ts or f"{time.time():.6f}"
        return None

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state: AgentState[Any], runtime: Any) -> dict[str, Any] | None:
        """Add follow-ups not yet in the conversation, or end the run for a stop."""
        binding = await self._surface.bind(runtime)
        if binding is None:
            return None
        since = self._since.get(binding.target.key) or binding.target.message_ts
        if not since:
            return None
        try:
            found = await self._surface.follow_ups.read(binding.client, binding.target, since)
        except SlackError as error:
            _LOGGER.warning("[steering] thread not read: %s", error.code)
            return None
        seen = {getattr(m, "id", None) for m in state.get("messages") or []}
        fresh = [f for f in found if steer_id(binding.target.channel, f.ts) not in seen]
        if not fresh:
            return None
        if any(is_stop(follow_up.text) for follow_up in fresh):
            return {"messages": [AIMessage(content=STOPPED)], "jump_to": "end"}
        added = [
            HumanMessage(
                _as_message(follow_up, await self._stage(binding, follow_up, runtime)),
                id=steer_id(binding.target.channel, follow_up.ts),
            )
            for follow_up in fresh
        ]
        return {"messages": added}

    async def aafter_agent(self, state: AgentState[Any], runtime: Any) -> dict[str, Any] | None:  # noqa: ARG002 - hook signature
        binding = await self._surface.bind(runtime)
        if binding is not None:
            self._since.pop(binding.target.key, None)
        return None

    async def _stage(self, binding: SlackBinding, follow_up: FollowUp, runtime: Any) -> list[str]:
        """Each file the follow-up brought, as the sandbox path it now has (or its name, when it
        could not be staged)."""
        staged: list[str] = []
        backend = self._backend_for(runtime) if self._backend_for is not None else None
        for ref in follow_up.files:
            found = attachment_path(ref)
            if found is None:
                continue
            path, url = found
            if backend is None:
                staged.append(
                    f"{path.rsplit('__', 1)[-1]} (not staged; ask for it again if needed)"
                )
                continue
            try:
                data = await binding.client.download(url, limit_bytes=MAX_FILE_BYTES)
                staged.append(await write_bytes(backend, path, data))
            except (SlackError, WorkspaceError) as error:
                _LOGGER.warning(
                    "[steering] a follow-up file was not staged: %s", type(error).__name__
                )
                staged.append(f"{path.rsplit('__', 1)[-1]} (could not be staged)")
        return staged
