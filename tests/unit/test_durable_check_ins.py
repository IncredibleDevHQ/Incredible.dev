"""In-process check-ins survive a restart through the store, and fire at once when overdue."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from langgraph.store.memory import InMemoryStore

from design_agent.harness.protocols import WakeTarget
from design_agent.runtime.waker.local import CHECK_INS, InProcessWaker


async def test_a_check_in_kept_by_a_stopped_process_fires_after_restore() -> None:
    store = InMemoryStore()
    fired: list[tuple[str, str]] = []

    async def never(_thread: str, _message: str, _started: asyncio.Event) -> None:
        raise AssertionError("the first process stops before the check-in is due")

    first = InProcessWaker(never, store=store)
    schedule_id = await first.schedule(
        WakeTarget("t1"), datetime.now(UTC) + timedelta(hours=1), "See if the render finished."
    )
    first._timers[schedule_id].cancel()  # the process stops
    assert await store.aget(CHECK_INS, schedule_id) is not None

    async def run_turn(thread: str, message: str, started: asyncio.Event) -> None:
        started.set()
        fired.append((thread, message))

    second = InProcessWaker(run_turn, store=store, sleep=lambda _s: asyncio.sleep(0))
    assert await second.restore("other-thread") == 0
    assert await second.restore() == 1
    for _ in range(50):
        if fired:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.01)
    assert fired == [("t1", "See if the render finished.")]
    assert await store.aget(CHECK_INS, schedule_id) is None, "a delivered check-in is forgotten"


async def test_a_cancelled_check_in_is_forgotten() -> None:
    store = InMemoryStore()

    async def run_turn(_thread: str, _message: str, started: asyncio.Event) -> None:
        started.set()

    waker = InProcessWaker(run_turn, store=store)
    schedule_id = await waker.schedule(
        WakeTarget("t1"), datetime.now(UTC) + timedelta(minutes=5), "later"
    )
    await waker.cancel(schedule_id)
    assert await store.aget(CHECK_INS, schedule_id) is None and waker.pending() == 0
