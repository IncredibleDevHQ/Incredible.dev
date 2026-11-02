"""Events: the one record every harness primitive writes, and the bus that carries it.

Everything that happens in the background of a thread (a helper starts, reports progress, finishes or
dies; a watched render moves or stalls; a check-in comes due; someone must act; a model call spends
tokens) is one `Event`. Producers publish to `BUS`; consumers subscribe:
- the inbox (`harness.inbox`) delivers events to the lead, now or at its next wake-up, as the
  attention policy (`harness.policy`) decides;
- the cost meter (`harness.meter`) adds up usage;
- the event log keeps them in the store.

Producers and consumers never import each other, so a new primitive plugs in by publishing or
subscribing, and a new surface (a web UI, a log) is one more subscriber.

`EventLog` keeps a thread's events in the deployment store too, so a later process (after a deploy)
can read the job (a post-job review, a rebuilt status). The bus is in-process and lossy by design
(a subscriber that raises is logged and skipped); the log is the durable copy.

Deep Agents has no event bus yet. The closest pieces are LangGraph's `custom` stream mode
(`get_stream_writer`) for live progress, and `AsyncSubAgentMiddleware`'s polled task status.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)

# -- event kinds ------------------------------------------------------------------------------------
# A kind is "<source>.<what happened>". Consumers match on these constants, never on free text.

TASK_STARTED = "task.started"
TASK_PROGRESS = "task.progress"
TASK_DONE = "task.done"
TASK_FAILED = "task.failed"
TASK_CANCELLED = "task.cancelled"
TASK_INTERRUPTED = "task.interrupted"
WAKEUP_DUE = "wakeup.due"
WAKEUP_SET = "wakeup.set"
WAKEUP_CANCELLED = "wakeup.cancelled"
WATCH_STARTED = "watch.started"
WATCH_PROGRESS = "watch.progress"
WATCH_ERROR = "watch.error"
WATCH_STALLED = "watch.stalled"
WATCH_DONE = "watch.done"
JOB_PHASE = "job.phase"
JOB_ATTENTION = "job.attention"
PIPELINE_STEP = "pipeline.step"
USAGE = "usage"

#: Kinds that end their source: nothing more comes from that task or watch.
TERMINAL_KINDS = frozenset(
    {TASK_DONE, TASK_FAILED, TASK_CANCELLED, TASK_INTERRUPTED, WATCH_ERROR, WATCH_DONE}
)


@dataclass(frozen=True)
class Event:
    """One thing that happened in the background of a thread.

    Attributes:
        kind: One of the constants above.
        thread_id: The thread whose lead this concerns.
        source: The id of what produced it: a task (`t-…`), a watch (`r-…`), a wake-up (`w-…`),
            a pipeline run (`p-…`), or `lead` for the lead's own model calls.
        label: A short human name for the source ("act 3", "final render").
        text: One or two sentences for a person or the lead: a report, a note, an error.
        data: Structured detail for machines: `fraction` (0-1), `eta_seconds`, `usage`, `urgent`,
            `report`, and so on. JSON-serializable.
        at: When it happened (epoch seconds).
        id: Unique, for de-duplication across the bus and the log.
    """

    kind: str
    thread_id: str
    source: str
    label: str = ""
    text: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)
    at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def terminal(self) -> bool:
        return self.kind in TERMINAL_KINDS

    def to_value(self) -> dict[str, Any]:
        """A JSON-safe dict for the store."""
        value = asdict(self)
        value["data"] = dict(self.data)
        return value

    @classmethod
    def from_value(cls, value: Mapping[str, Any]) -> Event:
        return cls(
            kind=str(value.get("kind", "")),
            thread_id=str(value.get("thread_id", "")),
            source=str(value.get("source", "")),
            label=str(value.get("label", "")),
            text=str(value.get("text", "")),
            data=dict(value.get("data") or {}),
            at=float(value.get("at") or 0.0),
            id=str(value.get("id") or uuid.uuid4().hex[:12]),
        )


Subscriber = Callable[[Event], Awaitable[None] | None]


class EventBus:
    """In-process publish/subscribe. Publishing never blocks and never raises.

    A synchronous subscriber runs inline; an async one runs as its own task on the running loop.
    A subscriber that raises is logged and the others still run.
    """

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []
        self._tasks: set[asyncio.Task[None]] = set()

    def subscribe(self, subscriber: Subscriber) -> Callable[[], None]:
        """Add a subscriber; returns a function that removes it."""
        self._subscribers.append(subscriber)

        def unsubscribe() -> None:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

        return unsubscribe

    def is_subscribed(self, subscriber: Subscriber) -> bool:
        return subscriber in self._subscribers

    def publish(self, event: Event) -> None:
        for subscriber in list(self._subscribers):
            try:
                result = subscriber(event)
            except Exception as error:  # noqa: BLE001 - one bad subscriber never stops the rest
                _LOGGER.warning("[harness] subscriber failed on %s: %s", event.kind, error)
                continue
            if inspect.isawaitable(result):
                self._spawn(result, event)

    def _spawn(self, awaitable: Awaitable[None], event: Event) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # no loop: nothing async can run; drop quietly
            if inspect.iscoroutine(awaitable):
                awaitable.close()
            return

        async def run() -> None:
            try:
                await awaitable
            except Exception as error:  # noqa: BLE001
                _LOGGER.warning("[harness] async subscriber failed on %s: %s", event.kind, error)

        task = loop.create_task(run(), name=f"harness event {event.kind}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Wait for the async subscribers already started (tests, shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def clear(self) -> None:
        """Drop every subscriber (tests)."""
        self._subscribers.clear()


#: The process-wide bus. Primitives publish here unless a test hands them another.
BUS = EventBus()

#: Days a thread's events stay in the store.
EVENT_TTL_MINUTES = 7 * 24 * 60


class EventLog:
    """A thread's events in the deployment store: the durable twin of the bus.

    Namespace `("harness", "events", <thread_id>)`; keys sort by time. The store is LangGraph's
    `BaseStore` (`aput`, `asearch`); a store that rejects `ttl` gets the put without it.
    """

    NAMESPACE = ("harness", "events")

    def __init__(self, store: Any) -> None:
        self._store = store

    def _namespace(self, thread_id: str) -> tuple[str, ...]:
        return (*self.NAMESPACE, thread_id)

    async def append(self, event: Event) -> None:
        if self._store is None or not event.thread_id:
            return
        key = f"{event.at:017.6f}-{event.id}"
        try:
            await self._store.aput(
                self._namespace(event.thread_id), key, event.to_value(), ttl=EVENT_TTL_MINUTES
            )
        except (TypeError, NotImplementedError):  # a store without TTL support (InMemoryStore)
            await self._store.aput(self._namespace(event.thread_id), key, event.to_value())
        except Exception as error:  # noqa: BLE001 - the bus copy still reached every subscriber
            _LOGGER.warning("[harness] logging %s failed: %s", event.kind, type(error).__name__)

    async def read(self, thread_id: str, *, since: float = 0.0, limit: int = 500) -> list[Event]:
        if self._store is None:
            return []
        items = await self._store.asearch(self._namespace(thread_id), limit=limit)
        events = [Event.from_value(item.value or {}) for item in items]
        return sorted((e for e in events if e.at > since), key=lambda e: e.at)
