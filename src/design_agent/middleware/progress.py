"""Live progress in the Slack thread: one message per run, a card per step, and one per helper.

The answer stays the platform's own message (MDA posts a run's final reply; the self-hosted
adapter posts it itself), so this streams the work and only the work
(`surfaces/slack/stream.py`):

- **`ThreadProgressMiddleware`** (the lead) opens the run's message at its first step. Each tool
  call is a card, "doing" while it runs and "done" (or failed) after; the plan (`write_todos`)
  is shown as its own cards instead of a "Planning" step, each appearing once it starts (Slack
  draws a pending card as a warning) and ticked off in place; the model's narration between
  steps goes in as text; the turn that answers gets a "Writing the reply" card. It settles to
  "Done" when the run ends, and to "Stopped" when the run is cancelled mid-step.
- **A turn that says nothing posts nothing.** When the reply the platform would post is `[quiet]`
  or empty (`harness.notices.should_post`), the message is deleted rather than settled.
- **`HelperProgressMiddleware`** (each background helper) streams a message of its own into the
  thread that asked, headed with the helper's label ("act 3: Rolling the render"), so helpers
  side by side keep separate messages. Its words are its report to the lead, so it shows steps
  only and always settles. A `task` run inside the lead's turn is no background helper and stays
  silent: the lead's own message shows it.

What a card may say: a card is the one surface nobody reviews before it is posted, so it never
carries argument text (no path, file id, query or anybody's words), only this repository's phrase
for the step and the service a tool reaches (`surfaces/slack/phrasebook.py`). A call to a tool
the agent does not have reads as a generic step, since its name is the model's own words. The
plan is the one exception: `write_todos` is the model's own summary of the work for the person.

While a long step runs, the lead's heartbeat also reads the thread: a follow-up the person sent
gets an `eyes` reaction and one line saying it will be worked in at the next step (with steering
on, `middleware/steering.py`) or picked up once this run is done.

Streams are keyed by the Slack thread, never the run's LangGraph config: every hook names the
same thread. Slack failures are swallowed with a class-name log (`SlackProgress`).

Ordering: put these after `QuietReplyMiddleware`, so their `after_agent` sees a `[quiet]` reply
before it is rewritten, and before the model guards (retry, failure boundary), so a retried
call's attempts are seen as one step and the boundary's message counts as the reply.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState, ModelRequest, ModelResponse
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from design_agent.harness import tasks
from design_agent.harness.notices import should_post
from design_agent.surfaces.slack.client import SlackError
from design_agent.surfaces.slack.followups import is_stop
from design_agent.surfaces.slack.phrasebook import phrase, todo_status
from design_agent.surfaces.slack.stream import Card, Progress, Silent, SlackProgress, card
from design_agent.surfaces.slack.target import SlackBinding, SlackSurface, thread_of

ANSWER = "answer"
WRITING, WROTE = "Writing the reply", "Wrote the reply"
DONE, STOPPED = "Done", "Stopped"
UNKNOWN_STEP = ("Working on a step", "Worked on a step")
#: What a follow-up that arrives mid-run is told, once.
STEERED = "_Got it. I'll work that in at my next step._"
QUEUED = "_Got your follow-up. I'll pick it up as soon as this is done._"
STOPPING = "_Stopping at my next step, then I'll take your new message._"
PLAN_STEPS, PLAN_TITLE = 25, 140
RUNS_KEPT = 256


def working(step: str) -> str:
    """The group's header: what the run is doing, readable while the group is collapsed."""
    return f"Working: {step}" if step else ""


def message_text(message: object) -> str:
    """A message's words: its string, or the text of its text blocks."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content if isinstance(content, list) else []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, Mapping) and block.get("type", "text") == "text":
            parts.append(str(block.get("text") or ""))
    return "".join(parts)


def posted_reply(messages: Sequence[object]) -> str:
    """What the platform posts for a run: the newest assistant message that has words."""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            text = message_text(message).strip()
            if text:
                return text
    return ""


def _response_messages(response: object) -> list[AIMessage]:
    """The model's messages in whatever a handler returned (a response, a message, a wrapper)."""
    if isinstance(response, AIMessage):
        return [response]
    inner = getattr(response, "model_response", None)
    messages = getattr(inner if inner is not None else response, "result", None)
    return [m for m in messages or [] if isinstance(m, AIMessage)]


@dataclass
class _Run:
    sink: Progress
    answering: bool = False
    #: The plan's cards as last shown, by id, so a new plan sends only what changed.
    shown: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: Follow-ups already given their reaction, and whether the line about them was said.
    acked: set[str] = field(default_factory=set)
    told: bool = False


class _Progress(AgentMiddleware[AgentState[Any], Any, Any]):
    """What the lead's and the helpers' progress share: runs by key, cards per tool call."""

    def __init__(self, surface: SlackSurface, *, servers: Mapping[str, str] | None = None) -> None:
        super().__init__()
        self._surface = surface
        self._servers = dict(servers or {})
        self._runs: OrderedDict[tuple[str, ...], _Run] = OrderedDict()

    # Subclasses say where a run streams, and how its header reads.
    async def _where(self, runtime: Any) -> tuple[tuple[str, ...], SlackBinding | None]:
        raise NotImplementedError

    def _sink(self, binding: SlackBinding, run: _Run) -> Progress:  # noqa: ARG002 - the lead's uses it
        return SlackProgress(binding.client, binding.target)

    def _header(self, step: str) -> str:
        return working(step)

    def _settled(self, done: bool) -> str:
        return DONE if done else STOPPED

    async def _run(self, runtime: Any) -> tuple[tuple[str, ...], _Run]:
        """The run a hook belongs to, made on first sight; `()` and a silent run off Slack."""
        key, binding = await self._where(runtime)
        run = self._runs.get(key) if key else None
        if run is None:
            run = _Run(Silent())
            if binding is not None and key:
                run.sink = self._sink(binding, run)
                self._runs[key] = run
                while len(self._runs) > RUNS_KEPT:
                    self._runs.popitem(last=False)
        return key, run

    async def _abandon(self, key: tuple[str, ...]) -> None:
        run = self._runs.pop(key, None)
        if run is not None:
            with contextlib.suppress(Exception):
                await run.sink.close(self._settled(False))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        key, run = await self._run(request.runtime)
        name = str(request.tool_call.get("name") or "")
        args = request.tool_call.get("args")
        if name == "write_todos":
            await self._plan(run, args)
            return await handler(request)
        doing, done = UNKNOWN_STEP
        if getattr(request, "tool", None) is not None:
            given = args if isinstance(args, Mapping) else None
            doing, done = phrase(name, given, servers=self._servers)
        # The call's own id: parallel steps hold separate cards, and a repeat of the same tool
        # later does not rewrite the earlier one.
        card_id = str(request.tool_call.get("id") or f"{name}-{id(request)}")
        try:
            await run.sink.step(card(card_id, doing, "in_progress"), self._header(doing))
            result = await handler(request)
        except BaseException as error:
            await run.sink.step(card(card_id, done, "error"))
            if isinstance(error, asyncio.CancelledError):
                # A cancelled run never reaches `after_agent`: settle it here, or the heartbeat
                # would keep a "Working" card alive for a run that is gone.
                await self._abandon(key)
            raise
        failed = isinstance(result, ToolMessage) and result.status == "error"
        await run.sink.step(card(card_id, done, "error" if failed else "complete"))
        return result

    async def _plan(self, run: _Run, args: object) -> None:
        """The model's todos as the plan's cards, sent when they change (module doc)."""
        todos = args.get("todos") if isinstance(args, Mapping) else None
        if not isinstance(todos, list):
            return
        changed: list[Card] = []
        current = ""
        for index, todo in enumerate(todos[:PLAN_STEPS]):
            content = todo.get("content") if isinstance(todo, Mapping) else todo
            title = " ".join(str(content or f"Step {index + 1}").split())[:PLAN_TITLE]
            status = todo_status(todo.get("status") if isinstance(todo, Mapping) else "")
            if status == "pending":
                continue
            if status == "in_progress" and not current:
                current = title
            card_id = f"todo-{index}"
            if run.shown.get(card_id) != (title, status):
                run.shown[card_id] = (title, status)
                changed.append(card(card_id, title, status))
        if changed:
            await run.sink.steps(changed, self._header(current))


class ThreadProgressMiddleware(_Progress):
    """The lead's live progress message (module doc).

    `servers` maps declared MCP servers to the service a card names (`phrasebook.services`).
    `steering` says whether follow-ups are worked into the running turn (the acknowledgement
    says so) or wait for the next one. `narrate` puts the model's words between steps in the
    thread.
    """

    def __init__(
        self,
        surface: SlackSurface,
        *,
        servers: Mapping[str, str] | None = None,
        steering: bool = True,
        narrate: bool = True,
    ) -> None:
        super().__init__(surface, servers=servers)
        self._steering = steering
        self._narrate = narrate

    @property
    def name(self) -> str:
        return "DesignAgentSlackProgress"

    async def _where(self, runtime: Any) -> tuple[tuple[str, ...], SlackBinding | None]:
        binding = await self._surface.bind(runtime)
        return (binding.target.key if binding is not None else ()), binding

    def _sink(self, binding: SlackBinding, run: _Run) -> Progress:
        async def beat(stream: SlackProgress) -> None:
            await self._acknowledge(binding, run, stream)

        return SlackProgress(binding.client, binding.target, on_beat=beat)

    async def _acknowledge(self, binding: SlackBinding, run: _Run, stream: SlackProgress) -> None:
        """Give a follow-up waiting on this run its reaction, and say once what happens to it."""
        since = binding.target.message_ts
        if not since:
            return
        found = await self._surface.follow_ups.read(binding.client, binding.target, since)
        fresh = [follow_up for follow_up in found if follow_up.ts not in run.acked]
        for follow_up in fresh:
            run.acked.add(follow_up.ts)
            with contextlib.suppress(SlackError):
                await binding.client.call(
                    "reactions.add",
                    {"channel": binding.target.channel, "timestamp": follow_up.ts, "name": "eyes"},
                )
        if fresh and not run.told:
            run.told = True
            if any(is_stop(follow_up.text) for follow_up in fresh):
                await stream.note(STOPPING)
            else:
                await stream.note(STEERED if self._steering else QUEUED)

    async def abefore_agent(self, state: AgentState[Any], runtime: Any) -> dict[str, Any] | None:  # noqa: ARG002 - hook signature
        """A run starts with a fresh message; one an earlier run left open says it stopped."""
        key, _ = await self._where(runtime)
        stale = self._runs.pop(key, None) if key else None
        if stale is not None:
            with contextlib.suppress(Exception):
                await stale.sink.close(STOPPED)
        await self._run(runtime)
        return None

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        key, run = await self._run(request.runtime)
        if not key:
            return await handler(request)
        try:
            response = await handler(request)
        except asyncio.CancelledError:
            await self._abandon(key)
            raise
        messages = _response_messages(response)
        if any(m.tool_calls for m in messages):
            if self._narrate:
                for message in messages:
                    await run.sink.text(message_text(message))
        else:
            if should_post(" ".join(message_text(m) for m in messages).strip()):
                run.answering = True
                await run.sink.step(card(ANSWER, WRITING, "in_progress"), self._header(WRITING))
        return response

    async def aafter_agent(self, state: AgentState[Any], runtime: Any) -> dict[str, Any] | None:
        key, _ = await self._where(runtime)
        run = self._runs.pop(key, None) if key else None
        if run is None:
            return None
        if not should_post(posted_reply(list(state.get("messages") or []))):
            await run.sink.discard()
            return None
        if run.answering:
            await run.sink.step(card(ANSWER, WROTE, "complete"))
        await run.sink.close(DONE)
        return None


class HelperProgressMiddleware(_Progress):
    """A background helper's own progress message in the thread that asked (module doc)."""

    @property
    def name(self) -> str:
        return "DesignAgentHelperProgress"

    async def _where(self, runtime: Any) -> tuple[tuple[str, ...], SlackBinding | None]:
        record = tasks.CURRENT.get()
        binding = self._surface.bound(record.thread_id or thread_of(runtime)) if record else None
        if record is None or binding is None:
            return (), None
        return (*binding.target.key, record.id), binding

    def _label(self) -> str:
        record = tasks.CURRENT.get()
        return record.label if record is not None else ""

    def _header(self, step: str) -> str:
        label = self._label()
        if not step:
            return ""
        return f"{label}: {step}" if label else working(step)

    def _settled(self, done: bool) -> str:
        label, word = self._label(), DONE if done else STOPPED
        return f"{label}: {word}" if label else word

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Steps only. A cancel that lands in a model call, where a stopped helper usually is,
        settles its message like one in a step."""
        try:
            return await handler(request)
        except asyncio.CancelledError:
            key, _ = await self._where(request.runtime)
            await self._abandon(key)
            raise

    async def aafter_agent(self, state: AgentState[Any], runtime: Any) -> dict[str, Any] | None:  # noqa: ARG002 - hook signature
        key, _ = await self._where(runtime)
        run = self._runs.pop(key, None) if key else None
        if run is not None:
            await run.sink.close(self._settled(True))
        return None
