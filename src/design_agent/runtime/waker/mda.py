"""The Managed Deep Agents waker, on public runtime schedules only.

A wake-up is a one-time schedule on the lead's own thread (`runtime.schedules.create(at=..., new_thread
=False)`). It survives redeploys, runs with the thread's channel binding (so its reply posts to the
Slack thread and `upload_files` works), and counts as delivered only once the woken run reports it
started: the run's first hook writes the wake key to the deployment store and this waker polls it.

Constraints from managed-deepagents 0.9.3 (docs/architecture/orchestration.md):

- `at` is rounded up to the next whole minute and must be at least one minute ahead, so a wake-up
  lands 60-120 s after the event, plus the scheduler's own lag. The harness inbox already
  coalesces events, so one schedule carries everything that happened meanwhile.
- A schedule can only be created from a run's runtime, for that run's thread. The waker keeps each
  thread's latest `runtime.schedules` in memory; after a restart a thread has none until a run on
  it happens. So while a thread has background work it holds one sentinel schedule
  `SENTINEL_MINUTES` ahead, which this process pushes forward every `POSTPONE_SECONDS`: it fires
  only once the process that kept moving it is gone, and that turn's sweep reports what the
  restart interrupted. Should it fire while the work still runs here (a postponement failed), the
  turn ends in code without a model call (`QuietReplyMiddleware`).
- Every scheduled run's reply is posted (MDA's schedule delivery runs after every authored hook),
  so a `[quiet]` reply becomes a one-line status (`middleware/quiet.py`).
- Agent-owned same-thread schedules need a channel binding; runs without one (Studio, the API) use
  the caller as the owner.
- Each owner can hold at most `MDA_MAX_AGENT_SCHEDULES` (default 20) unexpired schedules.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from langgraph.config import get_config

from design_agent.harness.protocols import WakeReceipt, WakeTarget
from design_agent.harness.tasks import running
from design_agent.middleware.quiet import SENTINEL_MARK, latest_human
from design_agent.runtime.waker import wake_key, wake_marker

_LOGGER = logging.getLogger(__name__)

STARTED_NAMESPACE = ("design_agent", "wake_started")
#: The schedule API refuses anything under a minute ahead; this rounds up to the minute after.
LEAD_SECONDS = 61
SENTINEL_MINUTES = 15
POSTPONE_SECONDS = 300.0
START_TIMEOUT_SECONDS = 300.0
POLL_SECONDS = 5.0


def _thread_of(runtime: Any) -> str:
    """The run's thread: a tool's runtime carries its config; a lifecycle hook's reads the
    ambient run config."""
    config = getattr(runtime, "config", None)
    if not config:
        try:
            config = get_config()
        except RuntimeError:
            config = {}
    return str((config.get("configurable") or {}).get("thread_id") or "")


@dataclass
class _Route:
    schedules: Any
    owner: dict[str, str]
    store: Any
    sentinel: str | None = None
    keeper: asyncio.Task[None] | None = None


@dataclass
class MdaScheduleWaker:
    """`harness.protocols.Waker` on MDA runtime schedules (module doc)."""

    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    poll_seconds: float = POLL_SECONDS
    postpone_seconds: float = POSTPONE_SECONDS
    start_timeout_seconds: float = START_TIMEOUT_SECONDS
    _routes: dict[str, _Route] = field(default_factory=dict)
    _pending: dict[str, str] = field(default_factory=dict)

    async def capture(self, runtime: Any) -> WakeTarget | None:
        """Keep where this thread's lead can be woken, from a live run's runtime."""
        thread_id = _thread_of(runtime)
        schedules = getattr(runtime, "schedules", None)
        if not thread_id or schedules is None:
            return None
        owner = (
            {"type": "agent"} if getattr(runtime, "channel", None) is not None else {"type": "user"}
        )
        previous = self._routes.get(thread_id)
        route = _Route(schedules, owner, getattr(runtime, "store", None))
        if previous is not None:
            route.sentinel, route.keeper = previous.sentinel, previous.keeper
        self._routes[thread_id] = route
        return WakeTarget(thread_id, channel={"owner": owner["type"]})

    async def wake(self, target: WakeTarget, message: str, *, dedupe_key: str) -> WakeReceipt:
        route = self._routes.get(target.thread_id)
        if route is None:
            return WakeReceipt(
                False, detail="no live route to this thread; its next run carries the news"
            )
        if dedupe_key not in self._pending:
            at = self.clock() + timedelta(seconds=LEAD_SECONDS)
            record = await route.schedules.create(
                owner=route.owner,
                at=at,
                prompt=f"{message}\n\n{wake_marker(dedupe_key)}",
                new_thread=False,
                metadata={"design_agent": "wake"},
            )
            self._pending[dedupe_key] = str(record["id"])
        if await self._started(route.store, dedupe_key):
            self._pending.pop(dedupe_key, None)
            return WakeReceipt(True)
        return WakeReceipt(False, detail="the scheduled wake-up has not started yet")

    async def _started(self, store: Any, key: str) -> bool:
        if store is None:
            return True  # nothing to confirm with; MDA owns the schedule from here
        deadline = time.monotonic() + self.start_timeout_seconds
        while time.monotonic() < deadline:
            item = await store.aget(STARTED_NAMESPACE, key)
            if item is not None:
                await store.adelete(STARTED_NAMESPACE, key)
                return True
            await asyncio.sleep(self.poll_seconds)
        return False

    async def schedule(self, target: WakeTarget, at: datetime, message: str) -> str:
        route = self._routes.get(target.thread_id)
        if route is None:
            raise RuntimeError("check-ins need a live run on this thread")
        earliest = self.clock() + timedelta(seconds=LEAD_SECONDS)
        record = await route.schedules.create(
            owner=route.owner,
            at=max(at, earliest),
            prompt=message,
            new_thread=False,
            metadata={"design_agent": "check-in"},
        )
        return str(record["id"])

    async def cancel(self, schedule_id: str) -> None:
        for route in self._routes.values():
            try:
                await route.schedules.delete(schedule_id, owner=route.owner)
                return
            except Exception as error:  # noqa: BLE001 - not this owner's, or already gone
                _LOGGER.debug(
                    "[waker] schedule %s not deleted here: %s", schedule_id, type(error).__name__
                )

    async def watchdog(self, target: WakeTarget, active: bool) -> None:
        """Hold one sentinel per thread while it has background work, kept ahead (module doc)."""
        route = self._routes.get(target.thread_id)
        if route is None:
            return
        if active and route.sentinel is None:
            route.sentinel = await self._arm(route)
        if active and (route.keeper is None or route.keeper.done()):
            route.keeper = asyncio.get_running_loop().create_task(
                self._keep(target.thread_id), name=f"sentinel {target.thread_id}"
            )
        elif not active:
            await self._disarm(route)

    async def _keep(self, thread_id: str) -> None:
        """Push the thread's sentinel forward while its work runs here; drop it after."""
        while True:
            await asyncio.sleep(self.postpone_seconds)
            route = self._routes.get(thread_id)
            if route is None:
                return
            if not running(thread_id):
                route.keeper = None
                await self._disarm(route)
                return
            old, route.sentinel = route.sentinel, await self._arm(route)
            if old is not None and route.sentinel is not None:
                await self.cancel(old)
            elif route.sentinel is None:
                route.sentinel = old  # keep the one there is rather than none

    async def _disarm(self, route: _Route) -> None:
        if route.keeper is not None and route.keeper is not asyncio.current_task():
            route.keeper.cancel()
        route.keeper = None
        if route.sentinel is not None:
            sentinel, route.sentinel = route.sentinel, None
            await self.cancel(sentinel)

    async def _arm(self, route: _Route) -> str | None:
        try:
            record = await route.schedules.create(
                owner=route.owner,
                at=self.clock() + timedelta(minutes=SENTINEL_MINUTES),
                prompt=(
                    f"{SENTINEL_MARK}>\nA restart may have stopped background work on this "
                    "thread. Tell the person in a line what stopped and offer to resume it; if "
                    "nothing did, reply exactly [quiet]."
                ),
                new_thread=False,
                metadata={"design_agent": "watchdog"},
            )
        except Exception as error:  # noqa: BLE001 - e.g. the owner's schedule cap; work goes on
            _LOGGER.warning("[waker] sentinel not armed: %s", str(error)[:200])
            return None
        return str(record["id"])

    async def on_turn_start(self, runtime: Any, messages: list[Any]) -> None:
        """Confirm a wake-up started; re-arm the sentinel when it is the one that fired."""
        text = latest_human(messages)
        key = wake_key(text)
        store = getattr(runtime, "store", None)
        if key and store is not None:
            await store.aput(STARTED_NAMESPACE, key, {"at": time.time()})
        if SENTINEL_MARK in text:
            target = await self.capture(runtime)
            if target is not None:
                self._routes[target.thread_id].sentinel = None  # this one has fired
                await self.watchdog(target, bool(running(target.thread_id)))
