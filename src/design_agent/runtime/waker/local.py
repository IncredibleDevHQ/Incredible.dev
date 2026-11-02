"""The in-process waker: the CLI, the demo and the self-hosted API queue a lead turn directly.

`run_turn(thread_id, message, started)` runs one turn on the thread (serialized with the person's
own messages by the caller) and sets `started` once the graph run has begun; a wake-up counts as
delivered then. Check-ins are timers in this process, kept in the store too (`CHECK_INS`) when one
is given: `restore()` re-arms them after a restart, and one whose time passed while the process
was down fires at once.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from design_agent.harness.protocols import WakeReceipt, WakeTarget

_LOGGER = logging.getLogger(__name__)

RunTurn = Callable[[str, str, asyncio.Event], Awaitable[None]]
START_TIMEOUT_SECONDS = 120.0
CHECK_INS = ("design_agent", "check_ins")


@dataclass
class InProcessWaker:
    run_turn: RunTurn
    start_timeout_seconds: float = START_TIMEOUT_SECONDS
    #: How a check-in waits for its time (tests make it instant).
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    #: Where check-ins are kept across restarts (a LangGraph store); None keeps them in memory.
    store: Any | None = None
    _seen: set[str] = field(default_factory=set)
    _timers: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    _turns: set[asyncio.Task[None]] = field(default_factory=set)

    async def capture(self, runtime: Any) -> WakeTarget | None:
        config = getattr(runtime, "config", None) or {}
        thread_id = str((config.get("configurable") or {}).get("thread_id") or "")
        return WakeTarget(thread_id) if thread_id else None

    async def wake(self, target: WakeTarget, message: str, *, dedupe_key: str) -> WakeReceipt:
        if dedupe_key in self._seen:
            return WakeReceipt(True, detail="already started")
        started = asyncio.Event()
        turn = asyncio.get_running_loop().create_task(
            self._turn(target.thread_id, message, started)
        )
        self._turns.add(turn)
        turn.add_done_callback(self._turns.discard)
        try:
            await asyncio.wait_for(started.wait(), self.start_timeout_seconds)
        except TimeoutError:
            return WakeReceipt(False, detail="the woken turn did not start in time")
        self._seen.add(dedupe_key)
        return WakeReceipt(True)

    async def _turn(self, thread_id: str, message: str, started: asyncio.Event) -> None:
        try:
            await self.run_turn(thread_id, message, started)
        except Exception as error:  # noqa: BLE001 - the inbox retries undelivered wake-ups
            _LOGGER.warning("[waker] a woken turn failed: %s", type(error).__name__)

    async def schedule(self, target: WakeTarget, at: datetime, message: str) -> str:
        schedule_id = f"w-{uuid.uuid4().hex[:6]}"
        if self.store is not None:
            record = {
                "thread_id": target.thread_id,
                "channel": target.channel,
                "at": at.isoformat(),
                "message": message,
            }
            await self.store.aput(CHECK_INS, schedule_id, record)
        self._arm(schedule_id, target, at, message)
        return schedule_id

    def _arm(self, schedule_id: str, target: WakeTarget, at: datetime, message: str) -> None:
        delay = max(0.0, (at - datetime.now(UTC)).total_seconds())

        async def fire() -> None:
            await self.sleep(delay)
            self._timers.pop(schedule_id, None)
            receipt = await self.wake(target, message, dedupe_key=f"check-in:{schedule_id}")
            if receipt.delivered and self.store is not None:
                await self.store.adelete(CHECK_INS, schedule_id)

        self._timers[schedule_id] = asyncio.get_running_loop().create_task(
            fire(), name=f"check-in {schedule_id}"
        )

    async def restore(self, thread_id: str | None = None) -> int:
        """Re-arm the check-ins a previous process kept (one thread's, or all); returns how many."""
        if self.store is None:
            return 0
        restored = 0
        for item in await self.store.asearch(CHECK_INS, limit=1000):
            value = item.value
            if item.key in self._timers or (
                thread_id is not None and value.get("thread_id") != thread_id
            ):
                continue
            try:
                at = datetime.fromisoformat(str(value["at"]))
                target = WakeTarget(str(value["thread_id"]), channel=value.get("channel"))
            except (KeyError, ValueError):
                await self.store.adelete(CHECK_INS, item.key)
                continue
            self._arm(item.key, target, at, str(value.get("message") or ""))
            restored += 1
        return restored

    async def cancel(self, schedule_id: str) -> None:
        timer = self._timers.pop(schedule_id, None)
        if timer is not None:
            timer.cancel()
        if self.store is not None:
            await self.store.adelete(CHECK_INS, schedule_id)

    def pending(self) -> int:
        """Timers and woken turns still outstanding (the CLI waits for these before exiting)."""
        return len(self._timers) + sum(1 for t in self._turns if not t.done())
