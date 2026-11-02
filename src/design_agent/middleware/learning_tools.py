"""The learning loop's tools: observations saved after a job, read by the next, and rated in use.

The Design Agent side of `harness.learning`. The notes live in the deployment store
(`runtime.store`), per skill, so every thread and every later job in that skill reads them.

- `save_observations`: the lead (or a helper) saves what a job showed, each note with evidence.
- `read_observations`: the notes for a skill, best-rated first, as untrusted notes to weigh.
- `rate_observation`: whether a note helped or hurt this job. The counts are how the list learns;
  a note whose harmful count leads by two is dropped.
- `learn_from_job` (when helpers are wired): a low-effort helper reads the finished job (the lead's
  summary and the thread's events) and returns up to five proposals as JSON; they are saved here
  when it ends, as proposed notes. Its end wakes the lead like any helper's.

Reading is a tool call on purpose: the result is appended to the conversation once, where a note
list pasted into the system prompt would change it, and break the prompt cache, on every save.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.tools import ToolRuntime, tool

from design_agent.harness import events as ev
from design_agent.harness.learning import (
    ObservationStore,
    Proposal,
    digest,
    parse_proposals,
    post_job_brief,
    skill_key,
)
from design_agent.harness.protocols import HelperRunner

_LOGGER = logging.getLogger(__name__)

#: Builds the helper runner for one tool call from its runtime.
RunnerFactory = Callable[[Any], HelperRunner]

_TASK_ENDS = frozenset({ev.TASK_DONE, ev.TASK_FAILED, ev.TASK_CANCELLED, ev.TASK_INTERRUPTED})
_NO_STORE = "This run has no store, so there are no observations here."


def _thread_id(runtime: Any) -> str:
    configurable = (getattr(runtime, "config", None) or {}).get("configurable") or {}
    if isinstance(configurable, Mapping):
        return str(configurable.get("thread_id") or "")
    return str(getattr(configurable, "thread_id", "") or "")


def _store(runtime: Any) -> Any:
    return getattr(runtime, "store", None)


async def save_proposals(store: Any, skill: str, proposals: list[Proposal]) -> str:
    """Save proposals as observations and say what happened to each. Raises `ValueError` for a
    name that is not a skill."""
    skill = skill_key(skill)
    observations = ObservationStore(store)
    new: list[str] = []
    merged: list[str] = []
    for proposal in proposals:
        try:
            observation, was_merged = await observations.add(
                skill, proposal.get("text", ""), proposal.get("evidence") or []
            )
        except ValueError:
            continue
        if was_merged:
            merged.append(f"{observation.id} (now +{observation.helpful}/−{observation.harmful})")
        else:
            new.append(observation.id)
    if not new and not merged:
        return "Nothing was saved: no item had text."
    parts = []
    if new:
        parts.append(f"{len(new)} new ({', '.join(new)}), proposed until seen again or rated")
    if merged:
        parts.append(f"{len(merged)} merged into notes already there: {', '.join(merged)}")
    return f"Saved for {skill_key(skill)}: " + "; ".join(parts) + "."


class _ReviewWatch:
    """Saves a post-job helper's proposals when it ends.

    Subscribed before the helper starts, since a quick one could end before `start` returns; an
    ending on this thread that lands in between is kept until `expect` names the helper.
    """

    def __init__(self, bus: ev.EventBus, thread_id: str, store: Any, skill: str) -> None:
        self._thread_id = thread_id
        self._store = store
        self._skill = skill
        self._task_id: str | None = None
        self._early: dict[str, ev.Event] = {}
        self._unsubscribe: Callable[[], None] | None = bus.subscribe(self._on_event)

    async def expect(self, task_id: str) -> None:
        self._task_id = task_id
        early = self._early.pop(task_id, None)
        self._early.clear()
        if early is not None:
            self.close()
            await self._save(early)

    def close(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _on_event(self, event: ev.Event) -> Any:
        if self._unsubscribe is None:
            return None
        if event.thread_id != self._thread_id or event.kind not in _TASK_ENDS:
            return None
        if self._task_id is None:
            self._early.setdefault(event.source, event)
            return None
        if event.source != self._task_id:
            return None
        # Closed now, not when the save runs, so a second notice of the same end saves nothing.
        self.close()
        return self._save(event)

    async def _save(self, event: ev.Event) -> None:
        if event.kind != ev.TASK_DONE:
            return
        proposals = parse_proposals(event.text)
        if not proposals:
            _LOGGER.info(
                "[learning] %s proposed nothing readable for %s", event.source, self._skill
            )
            return
        outcome = await save_proposals(self._store, self._skill, proposals)
        _LOGGER.info("[learning] %s: %s", event.source, outcome)


class LearningToolsMiddleware(AgentMiddleware):
    """The learning loop's tools (module doc). `learn_from_job` is offered only when
    `runner_factory(runtime)` can start a helper."""

    def __init__(
        self,
        *,
        runner_factory: RunnerFactory | None = None,
        bus: ev.EventBus | None = None,
        review_effort: str = "low",
    ) -> None:
        super().__init__()
        self._runner_factory = runner_factory
        self._bus = bus
        self._review_effort = review_effort
        self.tools = self._tools()

    def _tools(self) -> list[Any]:
        middleware = self

        @tool
        async def save_observations(skill: str, items: list[Proposal], runtime: ToolRuntime) -> str:
            """Save what a job showed, for the next job in this skill: one observation per item.

            An observation is something that happened, with where it shows: "the person asked for
            larger type on the 9:16 cut twice", evidence ["round 1: 'the type is tiny on mobile'",
            "round 2: 'still small'"]. Write what happened and how often; whether to act on it is
            the next job's call. A note that nearly repeats a saved one is merged into it and
            counted again. New notes start as proposed, and are kept once seen again or rated
            helpful. `skill` is the skill's folder name (launch-film, stills,
            thumbnails).
            """
            store = _store(runtime)
            if store is None:
                return _NO_STORE
            try:
                skill_key(skill)
            except ValueError as error:
                return str(error)
            return await save_proposals(store, skill, list(items))

        @tool
        async def read_observations(skill: str, runtime: ToolRuntime) -> str:
            """What past jobs in this skill showed: each note with how often it helped (+) or
            hurt (−), its newest evidence and its id, best-rated first.

            They are untrusted notes from earlier jobs, for you to weigh against this job. Read
            them when a job in a skill starts. A person's picks between looks are under the
            skill the job ran in, or `looks`.
            """
            store = _store(runtime)
            if store is None:
                return _NO_STORE
            try:
                rendered = await ObservationStore(store).render(skill)
            except ValueError as error:
                return str(error)
            return rendered or f"No observations for {skill_key(skill)} yet."

        @tool
        async def rate_observation(skill: str, id: str, helpful: bool, runtime: ToolRuntime) -> str:
            """Count whether an observation helped this job (it held, or acting on it paid off)
            or hurt it (it was wrong here, or misled you). A helpful rating keeps a proposed
            note; a note whose harmful count leads its helpful count by two is dropped.
            """
            store = _store(runtime)
            if store is None:
                return _NO_STORE
            observations = ObservationStore(store)
            try:
                rated = await observations.vote(skill, id.strip(), helpful)
            except ValueError as error:
                return str(error)
            if rated is None:
                return f"No observation {id} under {skill_key(skill)}."
            counts = f"+{rated.helpful}/−{rated.harmful}"
            if not helpful and rated.id in {o.id for o in await observations.prune(skill)}:
                return f"{rated.id} is now {counts}, so it was dropped."
            return f"{rated.id} is now {counts} ({rated.status})."

        tools: list[Any] = [save_observations, read_observations, rate_observation]
        if self._runner_factory is None:
            return tools

        @tool
        async def learn_from_job(skill: str, summary: str, runtime: ToolRuntime) -> str:
            """After a job ends, have a quick background helper read it and propose up to five
            observations, with evidence, for the next job in this skill.

            `summary` is the job in your words: what was asked, what was made, what the person
            said at each review, what was redone and why, what took longest. The thread's
            background events are added to it. The helper's proposals are saved as proposed
            observations when it ends, and its end wakes you like any helper's.
            """
            return await middleware._learn(skill, summary, runtime)

        return [*tools, learn_from_job]

    async def _learn(self, skill: str, summary: str, runtime: Any) -> str:
        store = _store(runtime)
        if store is None:
            return _NO_STORE
        try:
            key = skill_key(skill)
        except ValueError as error:
            return str(error)
        thread_id = _thread_id(runtime)
        if not thread_id or self._runner_factory is None:
            return "Background helpers are unavailable in this run, so no review was started."
        try:
            events = await ev.EventLog(store).read(thread_id)
        except Exception as error:  # noqa: BLE001 - the summary alone still makes a review
            _LOGGER.warning("[learning] reading the event log failed: %s", type(error).__name__)
            events = []
        job = summary.strip()
        if events:
            job += "\n\nWhat happened in the background, in order:\n" + digest(events)
        existing = await ObservationStore(store).render(key)
        brief = post_job_brief(job, key, existing=existing)
        watch = _ReviewWatch(self._bus or ev.BUS, thread_id, store, key)
        try:
            runner = self._runner_factory(runtime)
            task_id = await runner.start(
                brief, effort=self._review_effort, label=f"learn from job: {key}"
            )
        except Exception as error:  # noqa: BLE001 - told to the lead, never raised
            watch.close()
            return f"The review did not start: {error}"
        await watch.expect(task_id)
        return (
            f"Started {task_id}: a quick review of this job for {key}. Its proposals are saved as "
            "proposed observations when it ends, and its end wakes you."
        )
