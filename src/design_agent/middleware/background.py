"""Background work: the harness's helper primitives, bound to a runtime through a `Waker`.

The primitives live in `design_agent.harness` (docs/architecture/orchestration.md). This module is
the agent's side of them:

- **`start_task`** runs one of the declared subagents through the `task` tool Deep Agents built
  for this run, detached from the turn. It returns at once, so the lead replies with an ETA and
  its turn ends. The helper's config is the lead's minus LangGraph's per-run internals, so it works
  in the thread's own sandbox with the thread's files.
- **The lead is woken** through the runtime's `Waker` (MDA one-time schedules on the thread; the
  self-hosted and local runners queue a run in-process) when a helper finishes, fails or was
  interrupted by a restart, when a watched job fails, stalls or finishes, and when a check-in comes
  due. A helper's `report_progress` note waits for the lead's next turn unless it is urgent or the
  lead asked to follow that task closely. A reply of exactly `[quiet]` posts nothing, or one
  status line where the platform posts every scheduled run (`QuietReplyMiddleware`).
- **`schedule_wakeup`** lets the lead wake itself later with a note; **`check_tasks`** and
  **`cancel_task`** report and stop background work; **`resume_task`** continues a helper a
  restart killed from its saved transcript (`harness.durable`).

Effort workers (`low`, `xhigh`, `max`) run only in the background: a synchronous `task` call naming
one is refused with a pointer to `start_task`. `general-purpose` stays available synchronously.

Helpers live in this process: a deploy or restart ends them. Each keeps a heartbeat record in the
store until the lead has been told how it ended, so a restart loses neither a running helper (the
sweep reports it interrupted) nor a finished one whose notice was not yet delivered.

The lead's system prompt carries nothing that changes while work runs, so the prompt cache holds:
what is running is in each notice and in `check_tasks`.

One middleware instance serves every run in the process, and each run's `task` tool runs its
subagents in that run's own sandbox, so captured task tools are keyed by run, never shared.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, NotRequired, cast

from langchain.agents.middleware import AgentMiddleware, AgentState, ModelRequest, ModelResponse
from langchain.tools import ToolRuntime
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import var_child_runnable_config
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.config import get_config
from langgraph.types import Command

from design_agent.harness import durable, ledger, notices, tasks
from design_agent.harness import events as ev
from design_agent.harness.inbox import Inbox
from design_agent.harness.meter import CURRENT_TASK_ID
from design_agent.harness.protocols import HelperResult, Waker, WakeTarget
from design_agent.harness.tasks import REGISTRY, TaskRecord
from design_agent.middleware.quiet import is_watchdog_turn

_LOGGER = logging.getLogger(__name__)

#: The declared effort workers (`design_agent.subagents`). They run only in the background.
WORKER_TYPES = frozenset({"low", "xhigh", "max", "learning"})
#: `start_task`'s effort, as the subagent type that runs it: `high` is general-purpose, on the
#: lead's model and effort.
EFFORT_TYPES: dict[str, str] = {
    "low": "low",
    "high": "general-purpose",
    "xhigh": "xhigh",
    "max": "max",
    "learning": "learning",
}
REFUSED_SYNC = (
    "Workers run in the background, so this was not started. Use start_task with the same "
    "description and effort; it returns at once, and you are woken when the work is done."
)
#: How many runs' `task` tools are kept; a finished run's entry is pushed out by newer ones.
TASK_TOOLS_KEPT = 64
#: How often a run looks for work a restart killed (housekeeping always does).
SWEEP_EVERY_SECONDS = 120.0
CHECK_IN_MARK = "<check-in"

CaptureTarget = Callable[[Any], Awaitable[WakeTarget | None]]
#: Told when a thread gains or loses background work (`active`), so an adapter can keep a
#: restart watchdog such as MDA's sentinel check-in.
Watchdog = Callable[[WakeTarget, bool], Awaitable[None]]
#: Called at the start of every lead turn with the runtime and messages (a waker confirming that
#: the turn it scheduled started).
TurnStart = Callable[[Any, list[Any]], Awaitable[None]]


def _merge(
    existing: dict[str, dict[str, Any]] | None, update: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    merged = dict(existing or {})
    for key, entry in update.items():
        merged[key] = {**merged.get(key, {}), **entry}
    return merged


class BackgroundState(AgentState[Any]):
    #: What was started on this thread, so a later run (after a restart) knows a task existed even
    #: when this process no longer holds it.
    background_tasks: NotRequired[Annotated[dict[str, dict[str, Any]], _merge]]
    #: Check-ins the lead scheduled, by id, so `cancel_task` can find one after a restart.
    background_check_ins: NotRequired[Annotated[dict[str, dict[str, Any]], _merge]]


@dataclass
class BackgroundServices:
    """The process's wake-up plumbing, built once by the runtime adapter."""

    waker: Waker
    capture_target: CaptureTarget
    watchdog: Watchdog | None = None
    on_turn_start: TurnStart | None = None
    #: Other sweeps a restart needs (watches, pipelines), run after the helpers' sweep.
    sweepers: list[Callable[[Any], Awaitable[int]]] = field(default_factory=list)
    inbox: Inbox = field(init=False)
    _last_sweep: float = field(default=0.0, init=False)
    _sweeping: asyncio.Task[None] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.inbox = Inbox(self.waker)
        self.inbox.on_delivered(self._after_delivery)

    async def attach(self, runtime: Any) -> WakeTarget | None:
        """Register where to wake this thread's lead. None outside a thread."""
        target = await self.capture_target(runtime)
        if target is not None:
            self.inbox.set_target(target.thread_id, target)
        return target

    async def _after_delivery(self, batch: Sequence[ev.Event]) -> None:
        """Once the lead has heard how a helper ended, its record can go, and so can the
        transcript of one that finished (a failed helper's stays, so it can be resumed)."""
        for event in batch:
            if event.kind not in (ev.TASK_DONE, ev.TASK_FAILED):
                continue
            record = REGISTRY.get(event.source)
            if record is None or record.delivered:
                continue
            await ledger.forget(record)
            if event.kind == ev.TASK_DONE and record.store is not None:
                try:
                    await durable.TranscriptStore(record.store).delete(record.id)
                except Exception as error:  # noqa: BLE001 - it expires with the store's TTL
                    _LOGGER.warning("[background] dropping a transcript: %s", type(error).__name__)
            if self.watchdog is not None and not tasks.running(record.thread_id):
                box = self.inbox.box(record.thread_id)
                if box is not None:
                    await self.watchdog(box.target, False)

    async def sweep(self, store: Any) -> int:
        """Tell leads about helpers a restart killed or whose notice a restart swallowed."""

        async def on_task(key: str, value: dict[str, Any]) -> None:
            thread_id = str(value.get("thread_id") or "")
            if not thread_id:
                return
            if self.inbox.box(thread_id) is None:
                self.inbox.set_target(thread_id, WakeTarget(thread_id, channel=value.get("wake")))
            status = str(value.get("status") or "running")
            if status == "done":
                kind, text = ev.TASK_DONE, str(value.get("report") or "")
            elif status == "failed":
                kind, text = ev.TASK_FAILED, str(value.get("error") or "")
            else:
                kind, text = ev.TASK_INTERRUPTED, "Its files and progress notes are on disk."
            ev.BUS.publish(
                ev.Event(
                    kind,
                    thread_id,
                    key,
                    label=str(value.get("label") or key),
                    text=text,
                    data={
                        "effort": value.get("effort"),
                        "wave": value.get("wave"),
                        "started_at": value.get("started_at"),
                        "finished_at": value.get("finished_at") or value.get("alive_at"),
                    },
                )
            )

        async def ignore(_key: str, _value: dict[str, Any]) -> None:
            return None

        found = await ledger.sweep(store, on_task=on_task, on_wakeup=ignore)
        for sweeper in self.sweepers:
            try:
                found += await sweeper(store)
            except Exception as error:  # noqa: BLE001 - one sweeper failing never stops the rest
                _LOGGER.warning("[background] a sweeper failed: %s", type(error).__name__)
        return found

    def maybe_sweep(self, store: Any) -> None:
        if store is None or time.time() - self._last_sweep < SWEEP_EVERY_SECONDS:
            return
        self._last_sweep = time.time()

        async def run() -> None:
            try:
                await self.sweep(store)
            except Exception as error:  # noqa: BLE001 - the next sweep tries again
                _LOGGER.warning("[background] the sweep failed: %s", type(error).__name__)

        self._sweeping = asyncio.get_running_loop().create_task(run(), name="background sweep")

    async def aclose(self) -> None:
        """Let a sweep in flight finish before the process's loop closes (the CLI exits)."""
        if self._sweeping is not None and not self._sweeping.done():
            await asyncio.wait({self._sweeping}, timeout=30)


def _field(value: object, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def detached_config(config: Mapping[str, Any]) -> RunnableConfig:
    """The lead run's config without LangGraph's per-run internals or callbacks: a helper must not
    write checkpoints into a run that ended. The thread id that names the sandbox stays."""
    configurable = {
        key: value
        for key, value in dict(config.get("configurable") or {}).items()
        if not key.startswith(("__pregel_", "checkpoint_"))
    }
    detached = {
        key: value for key, value in config.items() if key not in {"configurable", "callbacks"}
    }
    detached["configurable"] = configurable
    return cast("RunnableConfig", detached)


def detached_runtime(runtime: Any, task_id: str) -> ToolRuntime:
    """A tool runtime for a helper that outlives the lead's call: the lead's state without its
    messages, its context and store, and its config without the ended run's internals."""
    return ToolRuntime(
        state={k: v for k, v in dict(runtime.state or {}).items() if k != "messages"},
        context=runtime.context,
        config=detached_config(dict(runtime.config or {})),
        stream_writer=lambda *_args, **_kwargs: None,
        tool_call_id=f"background-{task_id}",
        store=runtime.store,
    )


def _run_key(config: Mapping[str, Any] | None) -> str:
    for container in ("configurable", "metadata"):
        run_id = _field((config or {}).get(container), "run_id")
        if run_id:
            return f"run:{run_id}"
    return f"thread:{_field((config or {}).get('configurable'), 'thread_id') or ''}"


def _current_config(runtime: Any = None) -> Mapping[str, Any]:
    try:
        return get_config()
    except RuntimeError:
        return dict(getattr(runtime, "config", None) or {})


def _thread_of(runtime: Any) -> str:
    return str(
        _field((getattr(runtime, "config", None) or {}).get("configurable"), "thread_id") or ""
    )


def _report(result: object) -> str:
    """The subagent's final message, from the `Command` Deep Agents' `task` returns."""
    update = getattr(result, "update", None)
    messages = update.get("messages") if isinstance(update, Mapping) else None
    if isinstance(messages, list) and messages:
        content = getattr(messages[-1], "content", "")
        return content if isinstance(content, str) else str(content)
    return result if isinstance(result, str) else ""


async def _ended(record: TaskRecord) -> None:
    """Persist how the helper ended before the lead is told; a cancelled one needs no telling."""
    if record.status == "cancelled":
        await ledger.forget(record)
    else:
        await ledger.beat(record)


class BackgroundTaskMiddleware(AgentMiddleware[BackgroundState, Any, Any]):
    """The lead's background tools, task capture and the start-of-turn catch-up (module doc)."""

    state_schema = BackgroundState

    def __init__(self, services: BackgroundServices) -> None:
        super().__init__()
        self.services = services
        self._task_tools: OrderedDict[str, Any] = OrderedDict()
        self.tools = self._build_tools()

    @property
    def name(self) -> str:
        return "DesignAgentBackground"

    # -- tools -------------------------------------------------------------------------------

    def _build_tools(self) -> list[BaseTool]:
        middleware = self

        async def start_task(
            description: str,
            effort: Literal["low", "high", "xhigh", "max"],
            runtime: ToolRuntime,
            label: str = "",
            wave: str = "",
            wake_on_progress: bool = False,
        ) -> Command[Any] | str:
            """Start a helper in the background and return at once.

            `description` is the helper's whole prompt: a complete brief stating the role,
            quality bar, inputs, the files it owns, how to check the work, budget, progress file
            and how to resume (the launch-film skill has brief templates). `effort`:
            - `low` for mechanical work: grabs, conversions, renders of an approved film;
            - `high` for ordinary work;
            - `xhigh` for substantial work to a clear brief: a build, a breakdown, a review;
            - `max` for the hardest creative work: a flagship concept, a hero act.
            Helpers work in this thread's computer, so they see the project's files. `label`
            names the job in status lines ("act 3"); `wave` groups related tasks.

            You are woken when it finishes, fails or is interrupted. Its progress notes wait for
            your next turn; set `wake_on_progress` to be woken by each one. Do not poll with
            check_tasks. After starting work, say what is running and when to expect it, and end
            your turn.
            """
            launched = await middleware.launch(
                description, effort, label, wave, runtime, wake_on_progress=wake_on_progress
            )
            if isinstance(launched, str):
                return launched
            started = (
                f"Started {launched.id} ({effort}, {launched.label}) in the background"
                + (f" as part of wave {launched.wave}" if launched.wave else "")
                + ". It works in this thread's computer; you will be woken when it ends or needs "
                "you. If it will run longer than about 15 minutes, schedule a check-in with "
                "schedule_wakeup so the person hears how it is going."
            )
            return Command(
                update={
                    "messages": [ToolMessage(started, tool_call_id=runtime.tool_call_id)],
                    "background_tasks": {launched.id: launched.summary()},
                }
            )

        async def check_tasks(runtime: ToolRuntime, task_id: str = "") -> str:
            """What is running in the background on this thread, and what finished with its
            report. Pass `task_id` for one task's full report; leave it empty for everything."""
            return middleware.status(runtime, task_id)

        async def cancel_task(task_id: str, runtime: ToolRuntime) -> Command[Any] | str:
            """Stop background work by its id: a task, a watch, a pipeline, or a check-in you
            scheduled. A task's files stay; nothing you cancel wakes you."""
            return await middleware.cancel(runtime, task_id)

        async def schedule_wakeup(
            minutes: int, prompt: str, reason: str, runtime: ToolRuntime
        ) -> Command[Any] | str:
            """Wake yourself later on this thread, with `prompt` as a note to your future self.

            Use it to keep the person informed during long work and to check on work nothing
            reports on. It fires once; to keep checking in, schedule the next one when it fires,
            and stop once the work is done. Pick `minutes` (1 to 1440): about 10-15 for long work
            someone is following, 30-60 or more for slow or overnight work. Tasks and watches wake
            you themselves when they end or need you. `prompt` holds what to check, what to tell
            the person, and whether to check in again; `reason` is one short line shown in status.
            If nothing has changed when it fires, reply exactly `[quiet]`: at most a one-line
            status of the running work is posted.
            """
            return await middleware.schedule(minutes, prompt, reason, runtime)

        async def resume_task(task_id: str, runtime: ToolRuntime) -> Command[Any] | str:
            """Continue a background task a restart interrupted, from its saved transcript: same
            id, effort and label, picking up where it stopped. Use it when a notice says a task
            was interrupted; if nothing was saved, re-issue the brief with start_task."""
            return await middleware.resume(task_id, runtime)

        functions: tuple[Callable[..., Awaitable[Any]], ...] = (
            start_task,
            check_tasks,
            cancel_task,
            schedule_wakeup,
            resume_task,
        )
        return [StructuredTool.from_function(coroutine=f, name=f.__name__) for f in functions]

    # -- starting helpers -------------------------------------------------------------------

    def task_tool_for(self, runtime: Any) -> Any:
        """The `task` tool this run's own model calls were offered, or None before the first."""
        return self._task_tools.get(_run_key(_current_config(runtime)))

    async def launch(
        self,
        description: str,
        effort: str,
        label: str,
        wave: str,
        runtime: Any,
        *,
        task_id: str | None = None,
        wake_on_progress: bool = False,
    ) -> TaskRecord | str:
        """Start one helper; a string is the reason it could not start."""
        task_tool = self.task_tool_for(runtime)
        if task_tool is None:
            return "Delegation is unavailable in this run; do the work yourself."
        subagent_type = EFFORT_TYPES.get(effort)
        if subagent_type is None:
            return f"Unknown effort {effort!r}; use one of: low, high, xhigh, max."
        thread_id = _thread_of(runtime)
        if not thread_id:
            return "Background tasks need a thread; use task instead."
        target = await self.services.attach(runtime)
        if target is None:
            return "Background tasks need a thread; use task instead."
        record = TaskRecord(
            id=task_id or tasks.new_id(),
            thread_id=thread_id,
            effort=effort,
            subagent_type=subagent_type,
            label=label.strip() or description.strip().splitlines()[0][:60],
            wave=wave.strip() or None,
            started_at=time.time(),
            meta={"wake": target.channel, "wake_on_progress": wake_on_progress},
            store=getattr(runtime, "store", None),
        )
        detached = detached_runtime(runtime, record.id)
        await ledger.beat(record)
        ledger.ensure_heartbeat()
        tasks.launch(
            record,
            lambda: self._run_helper(record, task_tool, description, detached),
            on_end=_ended,
        )
        if self.services.watchdog is not None:
            await self.services.watchdog(target, True)
        return record

    async def _run_helper(
        self, record: TaskRecord, task_tool: Any, description: str, runtime: ToolRuntime
    ) -> str:
        token = var_child_runnable_config.set(runtime.config)
        scoped = [(var, var.set(record.id)) for var in (durable.CURRENT_TASK, CURRENT_TASK_ID)]
        try:
            result = await task_tool.coroutine(
                description=description, subagent_type=record.subagent_type, runtime=runtime
            )
        except asyncio.CancelledError:
            # A shutdown or cancel_task: flush what the helper did since its last save, so
            # resume_task continues from its latest step. Best effort; the store may be closing.
            await durable.save_on_cancel(record.id)
            raise
        finally:
            for var, reset in reversed(scoped):
                var.reset(reset)
            var_child_runnable_config.reset(token)
        return _report(result)

    async def run_inline(
        self, description: str, effort: str, label: str, wave: str, runtime: Any
    ) -> HelperResult:
        """Run one helper inside the caller's own task, reporting nothing itself: for code that
        reports each step and wakes the lead once (pipelines). Cancelling the caller cancels it."""
        subagent_type = EFFORT_TYPES.get(effort)
        task_tool = self.task_tool_for(runtime)
        if task_tool is None or subagent_type is None:
            reason = (
                "Delegation is unavailable in this run."
                if subagent_type
                else f"Unknown effort {effort!r}."
            )
            return HelperResult("", "failed", error=reason)
        record = TaskRecord(
            id=tasks.new_id(),
            thread_id=_thread_of(runtime),
            effort=effort,
            subagent_type=subagent_type,
            label=label.strip() or description.strip().splitlines()[0][:60],
            wave=wave or None,
            started_at=time.time(),
            store=getattr(runtime, "store", None),
        )
        current = tasks.CURRENT.set(record)
        try:
            report = await self._run_helper(
                record, task_tool, description, detached_runtime(runtime, record.id)
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - the pipeline reports it
            return HelperResult(
                record.id,
                "failed",
                error=f"It failed with {type(error).__name__}: {str(error)[:300]}. Its files are on disk.",
            )
        finally:
            tasks.CURRENT.reset(current)
        return HelperResult(record.id, "done", report)

    # -- check-ins, status, cancel, resume ----------------------------------------------------

    async def schedule(
        self, minutes: int, prompt: str, reason: str, runtime: Any
    ) -> Command[Any] | str:
        if not 1 <= minutes <= 1440:
            return "Pick between 1 and 1440 minutes (24 hours)."
        target = await self.services.attach(runtime)
        if target is None:
            return "A check-in needs a thread."
        due = datetime.now(UTC) + timedelta(minutes=minutes)
        note = f'{CHECK_IN_MARK} reason="{reason.strip()[:120]}">\nThe check-in you scheduled: {prompt.strip()}'
        try:
            schedule_id = await self.services.waker.schedule(target, due, note)
        except Exception as error:  # noqa: BLE001 - adapters raise their own types; the text is safe
            return f"The check-in could not be scheduled: {str(error)[:200]}"
        ev.BUS.publish(
            ev.Event(ev.WAKEUP_SET, target.thread_id, schedule_id, label=reason.strip()[:80])
        )
        message = f"Scheduled {schedule_id} for {due:%H:%M UTC} (in {minutes} min): {reason.strip()}. You will be woken with your note."
        return Command(
            update={
                "messages": [
                    ToolMessage(message, tool_call_id=getattr(runtime, "tool_call_id", "") or "")
                ],
                "background_check_ins": {
                    schedule_id: {"due_at": due.isoformat(), "reason": reason.strip()[:120]}
                },
            }
        )

    def status(self, runtime: Any, task_id: str) -> str:
        thread_id = _thread_of(runtime)
        known = dict((getattr(runtime, "state", None) or {}).get("background_tasks") or {})
        records = [r for r in REGISTRY.values() if r.thread_id == thread_id]
        others = [
            line
            for provider in notices.RUNNING_PROVIDERS
            if provider is not tasks.running_lines
            for line in provider(thread_id)
        ]
        if task_id:
            for describer in DESCRIBERS:
                described = describer(task_id, thread_id)
                if described is not None:
                    return described
            match = REGISTRY.get(task_id)
            if match is None or match.thread_id != thread_id:
                if known.get(task_id, {}).get("status") == "running":
                    return f"{task_id} was interrupted (a restart ended it); resume it with resume_task."
                if task_id in known:
                    return f"{task_id} {known[task_id].get('status')}; its report was in the wake-up message."
                return f"No task {task_id} on this thread."
            if match.status == "running":
                return f"{task_id} ({match.effort}, {match.label}) has been running for {tasks.minutes(time.time() - match.started_at)}."
            return f"{task_id} {match.status}.\n{match.report or match.error}"
        if not records and not known and not others:
            return "Nothing has run in the background on this thread."
        now, lines = time.time(), []
        for r in records:
            if r.status == "running":
                lines.append(
                    f"- {r.id} ({r.effort}, {r.label}{', wave ' + r.wave if r.wave else ''}): running, {tasks.minutes(now - r.started_at)}"
                )
            else:
                lines.append(
                    f"- {r.id} ({r.effort}, {r.label}): {r.status}; check_tasks('{r.id}') for its report"
                )
        for missing in sorted(set(known) - {r.id for r in records}):
            entry = known[missing]
            if entry.get("status") == "running":
                lines.append(
                    f"- {missing} ({entry.get('label', '')}): interrupted by a restart; resume it with resume_task"
                )
            else:
                lines.append(
                    f"- {missing} ({entry.get('label', '')}): {entry.get('status')}; its report was in the wake-up message"
                )
        lines += [f"- {line}" for line in others]
        return "\n".join(lines)

    async def cancel(self, runtime: Any, task_id: str) -> Command[Any] | str:
        thread_id = _thread_of(runtime)
        check_ins = dict((getattr(runtime, "state", None) or {}).get("background_check_ins") or {})
        if task_id in check_ins:
            await self.services.waker.cancel(task_id)
            ev.BUS.publish(ev.Event(ev.WAKEUP_CANCELLED, thread_id, task_id))
            return f"Cancelled check-in {task_id}."
        for canceller in CANCELLERS:
            handled = canceller(task_id, thread_id)
            if handled is not None:
                return handled
        return tasks.cancel(task_id, thread_id)

    async def resume(self, task_id: str, runtime: Any) -> Command[Any] | str:
        for resumer in RESUMERS:
            handled = await resumer(task_id, runtime)
            if handled is not None:
                return handled
        record = REGISTRY.get(task_id)
        if record is not None and record.status == "running":
            return f"{task_id} is still running; it wakes you when it ends."
        if not await durable.can_resume(getattr(runtime, "store", None), task_id):
            return (
                f"No saved transcript for {task_id}. Re-issue it with start_task using the resume "
                "brief in the launch-film skill: its files and progress notes are on disk."
            )
        known = dict((getattr(runtime, "state", None) or {}).get("background_tasks") or {}).get(
            task_id, {}
        )
        effort = str(known.get("effort") or (record.effort if record else "xhigh"))
        label = str(known.get("label") or (record.label if record else task_id))
        wave = str(known.get("wave") or "")
        REGISTRY.pop(task_id, None)
        launched = await self.launch(
            durable.resume_brief(task_id), effort, label, wave, runtime, task_id=task_id
        )
        if isinstance(launched, str):
            return launched
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Resumed {task_id} ({effort}, {label}) from its saved transcript.",
                        tool_call_id=getattr(runtime, "tool_call_id", "") or "",
                    )
                ],
                "background_tasks": {launched.id: launched.summary()},
            }
        )

    # -- hooks ----------------------------------------------------------------------------------

    async def abefore_agent(self, state: BackgroundState, runtime: Any) -> dict[str, Any] | None:
        """Write what finished since the last run into the thread's state (so after a restart
        `check_tasks` tells finished work from interrupted work), and hand the lead what the inbox
        held for its next turn, whatever started this one."""
        try:
            configurable = get_config().get("configurable") or {}
        except RuntimeError:
            return None
        if self.services.on_turn_start is not None:
            try:
                await self.services.on_turn_start(runtime, list(state.get("messages") or []))
            except Exception as error:  # noqa: BLE001 - a receipt never blocks the turn
                _LOGGER.warning("[background] turn-start hook failed: %s", type(error).__name__)
        store = getattr(runtime, "store", None)
        if store is not None and is_watchdog_turn(list(state.get("messages") or [])):
            # The watchdog fires only when the process that kept postponing it is gone, so what a
            # restart killed is told in this turn, which posts anyway.
            try:
                await self.services.sweep(store)
            except Exception as error:  # noqa: BLE001 - the regular sweep tries again
                _LOGGER.warning("[background] the watchdog sweep failed: %s", type(error).__name__)
        else:
            self.services.maybe_sweep(store)
        thread_id = str(configurable.get("thread_id") or "")
        known = dict(state.get("background_tasks") or {})
        changed = {
            r.id: r.summary()
            for r in REGISTRY.values()
            if r.thread_id == thread_id and r.id in known and known[r.id] != r.summary()
        }
        update: dict[str, Any] = {"background_tasks": changed} if changed else {}
        held = self.services.inbox.take_held(thread_id) if thread_id else []
        if held:
            update["messages"] = [HumanMessage(notices.render(thread_id, held, guidance=False))]
            await self.services.inbox.delivered(held)
        return update or None

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        # The compiled subagents live in the closure of the `task` tool Deep Agents built for this
        # run; start_task runs them through it, so it is kept under this run's key. Nothing is
        # added to the system prompt: it stays byte-identical while work runs.
        for candidate in request.tools or []:
            if getattr(candidate, "name", None) == "task":
                key = _run_key(_current_config(getattr(request, "runtime", None)))
                self._task_tools[key] = candidate
                self._task_tools.move_to_end(key)
                while len(self._task_tools) > TASK_TOOLS_KEPT:
                    self._task_tools.popitem(last=False)
        return await handler(request)

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        call = request.tool_call
        if (
            call.get("name") == "task"
            and (call.get("args") or {}).get("subagent_type") in WORKER_TYPES
        ):
            return ToolMessage(REFUSED_SYNC, tool_call_id=call["id"], status="error")
        return await handler(request)


#: Other kinds of background work (watches, pipelines) register how to cancel their ids: each
#: returns a message when it owns the id, None otherwise.
CANCELLERS: list[Callable[[str, str], str | None]] = []
#: ... and how to resume them (`resume_task`).
RESUMERS: list[Callable[[str, Any], Awaitable[str | None]]] = []
#: ... and how to describe one for `check_tasks(id)`.
DESCRIBERS: list[Callable[[str, str], str | None]] = []


@dataclass
class BackgroundHelpers:
    """`HelperRunner` for code that starts helpers itself (pipelines, looks, the post-job review)."""

    middleware: BackgroundTaskMiddleware
    runtime: Any
    #: Run each helper inside the caller's own task and report nothing (pipelines).
    inline: bool = False

    async def start(
        self, brief: str, *, effort: str, label: str = "", wave: str | None = None
    ) -> str:
        launched = await self.middleware.launch(brief, effort, label, wave or "", self.runtime)
        if isinstance(launched, str):
            raise RuntimeError(launched)
        return launched.id

    async def run(
        self, brief: str, *, effort: str, label: str = "", wave: str | None = None
    ) -> HelperResult:
        if self.inline:
            return await self.middleware.run_inline(brief, effort, label, wave or "", self.runtime)
        launched = await self.middleware.launch(brief, effort, label, wave or "", self.runtime)
        if isinstance(launched, str):
            return HelperResult(task_id="", status="failed", error=launched)
        if launched.ended is None:
            return HelperResult(launched.id, "failed", error="the helper did not start")
        record = await asyncio.shield(launched.ended)
        return HelperResult(record.id, record.status, record.report, record.error)


async def report_progress(note: str, urgent: bool = False) -> str:
    """Tell the lead how this task is going.

    Send one when a section is done, when something blocks you or moves your ETA, and before you
    stop early: one or two sentences on what happened and what comes next, with a time. It reaches
    the lead with its next turn. Set `urgent` only when the lead must act now: you are blocked on a
    decision, or the plan no longer works.
    """
    record = tasks.CURRENT.get()
    if record is None:
        return "This is not a background task; put it in your final report instead."
    tasks.note(record, note.strip()[:600], urgent=urgent)
    return "Sent to the lead."


class WorkerProgressMiddleware(AgentMiddleware[Any, Any, Any]):
    """Gives a helper `report_progress`, so the lead hears more than its final report."""

    def __init__(self) -> None:
        super().__init__()
        self.tools = [
            StructuredTool.from_function(coroutine=report_progress, name="report_progress")
        ]

    @property
    def name(self) -> str:
        return "DesignAgentWorkerProgress"


def helper_store() -> Any:
    """The store of the helper whose code is running, for its transcript (`harness.durable`)."""
    record = tasks.CURRENT.get()
    return record.store if record is not None else None
