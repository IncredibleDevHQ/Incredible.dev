"""Background helpers: work that runs detached from the lead's turn and reports as events.

The lead starts a helper and its turn ends at once; the helper keeps working in this process and
everything that happens to it is an event on the bus:
- `TASK_STARTED` when it launches, `TASK_PROGRESS` for each note it sends (`note`);
- `TASK_DONE` with its report, `TASK_FAILED` with its error, `TASK_CANCELLED` when the lead stops it.
A helper a restart killed never says so itself: its heartbeat record goes stale, and the sweep
(`harness.ledger.sweep`) publishes `TASK_INTERRUPTED` for it.

What runs is the adapter's business: `launch` takes the record and a coroutine factory (Design
Agent's runs a declared Deep Agents subagent in the thread's own sandbox; a pipeline runs its
script). `CURRENT` names the record whose code is running, so a helper's own tools
(`report_progress`) and middleware (the meter, the transcript) know whose they are.

Deep Agents' `AsyncSubAgentMiddleware` runs subagents as server runs on their own threads, which
do not share the lead's sandbox; until they can, helpers run in-process behind `HelperRunner`.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

from design_agent.harness import events as ev

_LOGGER = logging.getLogger(__name__)

Status = Literal["running", "done", "failed", "cancelled", "interrupted"]


@dataclass
class TaskRecord:
    """One background helper (or pipeline run) and how it ended."""

    id: str
    thread_id: str
    effort: str
    label: str
    wave: str | None
    started_at: float
    #: What runs it, for the adapter: a deepagents subagent type, a pipeline name.
    subagent_type: str = ""
    status: Status = "running"
    finished_at: float | None = None
    report: str = ""
    error: str = ""
    #: Adapter data a later process needs (the wake target, the brief). Persisted in the ledger.
    meta: dict[str, Any] = field(default_factory=dict)
    handle: asyncio.Task[None] | None = field(default=None, repr=False)
    #: The deployment's store, where the heartbeat record lives (None without one).
    store: Any = field(default=None, repr=False)
    #: Set by `cancel`, so a cancel is told apart from a shutdown (which the sweep reports).
    cancel_requested: bool = False
    #: Resolved when the helper ends, for callers that await it (`HelperRunner.run`).
    ended: asyncio.Future[TaskRecord] | None = field(default=None, repr=False)
    #: The ledger record stays until the lead has been told how the helper ended.
    delivered: bool = False

    def summary(self) -> dict[str, Any]:
        return {
            "effort": self.effort,
            "label": self.label,
            "wave": self.wave,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


#: Every helper this process runs, by id. Process-level on purpose: a helper outlives the run (and
#: the middleware instance's graph) that started it.
REGISTRY: dict[str, TaskRecord] = {}
#: The helper whose code is running (None in the lead).
CURRENT: ContextVar[TaskRecord | None] = ContextVar("harness_task", default=None)

Body = Callable[[], Awaitable[str]]
OnEnd = Callable[[TaskRecord], Awaitable[None]]


def new_id(prefix: str = "t") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def minutes(seconds: float) -> str:
    return f"{max(1, round(seconds / 60))} min"


def launch(
    record: TaskRecord,
    body: Body,
    *,
    on_end: OnEnd | None = None,
    bus: ev.EventBus | None = None,
) -> None:
    """Run `body` detached from the caller. It returns the helper's report; raising fails it."""
    bus = bus or ev.BUS
    loop = asyncio.get_running_loop()
    REGISTRY[record.id] = record
    record.ended = loop.create_future()
    record.handle = loop.create_task(_run(record, body, on_end, bus), name=f"helper {record.id}")
    bus.publish(
        ev.Event(
            ev.TASK_STARTED,
            record.thread_id,
            record.id,
            label=record.label,
            data={"effort": record.effort, "wave": record.wave},
        )
    )


async def _run(record: TaskRecord, body: Body, on_end: OnEnd | None, bus: ev.EventBus) -> None:
    token = CURRENT.set(record)
    try:
        record.report = await body()
        record.status = "done"
    except asyncio.CancelledError:
        record.status, record.finished_at = "cancelled", time.time()
        if record.cancel_requested:
            # The lead asked for it: recorded, never a wake-up. A shutdown instead
            # leaves the heartbeat record behind, and the sweep reports it as interrupted.
            bus.publish(
                ev.Event(ev.TASK_CANCELLED, record.thread_id, record.id, label=record.label)
            )
            if on_end is not None:
                await on_end(record)
        _resolve(record)
        raise
    except Exception as error:  # noqa: BLE001 - reported to the lead, never raised
        record.status = "failed"
        record.error = (
            f"It failed with {type(error).__name__}: {str(error)[:300]}. Its files are on disk."
        )
        _LOGGER.warning("[harness] %s failed: %s", record.id, type(error).__name__)
    finally:
        CURRENT.reset(token)
    record.finished_at = time.time()
    kind = ev.TASK_DONE if record.status == "done" else ev.TASK_FAILED
    bus.publish(
        ev.Event(
            kind,
            record.thread_id,
            record.id,
            label=record.label,
            text=record.report if record.status == "done" else record.error,
            data={
                "effort": record.effort,
                "wave": record.wave,
                "started_at": record.started_at,
                "finished_at": record.finished_at,
            },
        )
    )
    _resolve(record)
    if on_end is not None:
        await on_end(record)


def _resolve(record: TaskRecord) -> None:
    if record.ended is not None and not record.ended.done():
        record.ended.set_result(record)


def note(
    record: TaskRecord, text: str, *, urgent: bool = False, bus: ev.EventBus | None = None
) -> None:
    """A helper's progress note: held for the lead's next turn, unless it is `urgent` or the lead
    asked to follow this task closely (`record.meta["wake_on_progress"]`)."""
    urgent = urgent or bool(record.meta.get("wake_on_progress"))
    (bus or ev.BUS).publish(
        ev.Event(
            ev.TASK_PROGRESS,
            record.thread_id,
            record.id,
            label=record.label,
            text=text,
            data={"urgent": urgent, "effort": record.effort},
        )
    )


def cancel(task_id: str, thread_id: str) -> str:
    record = REGISTRY.get(task_id)
    if record is None or record.thread_id != thread_id:
        return f"No task {task_id} on this thread."
    if record.status != "running" or record.handle is None:
        return f"{task_id} is already {record.status}."
    record.cancel_requested = True
    record.handle.cancel()
    return f"Cancelled {task_id}; its files stay in the project."


def running(thread_id: str) -> list[TaskRecord]:
    return [r for r in REGISTRY.values() if r.thread_id == thread_id and r.status == "running"]


def running_lines(thread_id: str) -> list[str]:
    """One line per running helper, for notices and status: '<id> (<effort>, <label>, N min)'."""
    now = time.time()
    return [
        f"{r.id} ({r.effort}, {r.label}{', wave ' + r.wave if r.wave else ''}, "
        f"{minutes(now - r.started_at)})"
        for r in running(thread_id)
    ]
