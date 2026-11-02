"""The watch's restart record: kept while the watch runs and until its end is heard, swept after a
restart, and resumable for a day. Every test runs on an in-memory store with an injected clock."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from langgraph.store.memory import InMemoryStore

from design_agent.harness import events as ev
from design_agent.harness.notices import render
from design_agent.harness.policy import Delivery, decide
from design_agent.harness.watch import (
    RESUMABLE_SECONDS,
    WATCH_LEDGER,
    Update,
    WatchLedger,
    WatchRecord,
    WatchRunner,
)


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class Quiet:
    """A `WatchSource` that never has anything new."""

    closed = False
    note = ""

    async def read(self) -> str:
        return ""


async def _records(store: InMemoryStore) -> dict[str, dict[str, Any]]:
    return {item.key: item.value for item in await store.asearch(WATCH_LEDGER)}


async def _until(check: Callable[[], bool], timeout: float = 5.0) -> None:
    async def wait() -> None:
        while not check():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(wait(), timeout)


def _record(status: str = "watching", **fields: Any) -> WatchRecord:
    return WatchRecord(
        id="r-abc123",
        thread_id="t-1",
        label="final render",
        started_at=999_400.0,
        poll_seconds=15,
        stall_seconds=300,
        status=status,  # type: ignore[arg-type]
        **fields,
    )


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def ledger(clock: Clock):
    watches = WatchRunner(clock=clock)
    kept = WatchLedger(watches, clock=clock, heartbeat_seconds=60)
    yield kept
    kept.stop()
    watches.clear()


async def test_a_running_watch_writes_its_record_once_a_heartbeat(clock, ledger) -> None:
    store = InMemoryStore()
    beat = ledger.beat(store, {"kind": "hyperframes", "path": "/workspace/out/render.log"})
    record = _record(fraction=0.42)

    await beat(record)
    (value,) = (await _records(store)).values()
    assert value["kind"] == "hyperframes" and value["path"] == "/workspace/out/render.log"
    assert value["status"] == "watching" and value["fraction"] == 0.42
    assert value["alive_at"] == clock.now and value["final"] is None

    clock.now += 30
    record.fraction = 0.5
    await beat(record)  # within the heartbeat: not written
    assert (await _records(store))["r-abc123"]["fraction"] == 0.42
    clock.now += 31
    await beat(record)
    assert (await _records(store))["r-abc123"]["fraction"] == 0.5


async def test_an_ended_watch_keeps_its_record_until_the_lead_heard_the_end(ledger) -> None:
    store = InMemoryStore()
    beat = ledger.beat(store, {})
    final = ev.Event(ev.WATCH_DONE, "t-1", "r-abc123", label="final render", text="done")
    record = _record("done", final=final)

    await beat(record)
    assert (await _records(store))["r-abc123"]["final"]["id"] == final.id

    other = ev.Event(ev.WATCH_PROGRESS, "t-1", "r-abc123", text="90%")
    await ledger.delivered([other])  # not its end: kept
    assert "r-abc123" in await _records(store)
    await ledger.delivered([final])
    assert await _records(store) == {}


async def test_an_end_heard_before_its_record_was_written_drops_it(ledger) -> None:
    store = InMemoryStore()
    watches = ledger.watches
    watch_id = watches.start("t-1", label="x", source=Quiet(), parser=_Done(), poll_seconds=0.01)
    await _until(lambda: watches.get(watch_id).status == "done")
    record = watches.get(watch_id)

    await ledger.delivered([record.final])  # the wake-up won the race with the beat
    await ledger.beat(store, {})(record)
    assert await _records(store) == {}


async def test_a_watch_the_lead_stopped_drops_its_record_at_once(ledger) -> None:
    store = InMemoryStore()
    beat = ledger.beat(store, {})
    await beat(_record())
    await beat(_record("cancelled"))
    assert await _records(store) == {}


async def test_the_sweep_reports_a_cut_off_watch_once_and_keeps_it_resumable_for_a_day(
    clock, ledger
) -> None:
    store = InMemoryStore()
    stale = clock.now - 600
    await store.aput(
        WATCH_LEDGER,
        "r-dead01",
        {
            "thread_id": "t-gone",
            "label": "final render",
            "status": "watching",
            "fraction": 0.42,
            "started_at": stale - 600,
            "alive_at": stale,
            "log_path": "/workspace/.renders/final-abc123.log",
            "command": "hyperframes render . --output out/film.mp4",
            "job_id": "4242",
            "wake": {"channel": "opaque"},
        },
    )
    await store.aput(WATCH_LEDGER, "r-alive1", {"thread_id": "t-other", "alive_at": clock.now - 10})
    bus, seen = ev.EventBus(), []
    bus.subscribe(seen.append)
    found: list[tuple[str, dict[str, Any]]] = []

    async def on_found(watch_id: str, value: dict[str, Any]) -> None:
        found.append((watch_id, value))

    assert await ledger.sweep(store, on_found=on_found, bus=bus) == 1

    assert [watch_id for watch_id, _ in found] == ["r-dead01"]
    assert found[0][1]["wake"] == {"channel": "opaque"}  # the host's data, to wake its lead
    (event,) = seen
    assert event.kind == ev.TASK_INTERRUPTED and event.thread_id == "t-gone"
    assert event.data["watch"] is True and decide(event).delivery is Delivery.NOW
    notice = render("t-gone", [event])
    assert "Background work was interrupted" in notice
    assert "- r-dead01 (final render): interrupted by a restart after 10 min." in notice
    assert "The watch stopped at 42% when the server restarted." in notice
    assert "/workspace/.renders/final-abc123.log" in notice
    assert "resume_task('r-dead01')" in notice and "and the exit code" in notice

    records = await _records(store)
    assert set(records) == {"r-dead01", "r-alive1"}
    assert records["r-dead01"]["reported_at"] == clock.now
    assert records["r-dead01"]["status"] == "interrupted"
    assert await ledger.sweep(store, bus=bus, now=clock.now + 60) == 0  # told once
    assert len(seen) == 1

    resumable = await ledger.resumable(store, "r-dead01", "t-gone")
    assert resumable is not None and resumable["command"].startswith("hyperframes render")
    assert await ledger.resumable(store, "r-dead01", "t-other") is None  # another thread's
    assert await ledger.resumable(store, "r-alive1", "t-other") is None  # never reported
    later = clock.now + RESUMABLE_SECONDS + 1
    assert await ledger.resumable(store, "r-dead01", "t-gone", now=later) is None

    await ledger.sweep(store, bus=bus, now=later)
    assert "r-dead01" not in await _records(store)  # not resumed within a day: gone


async def test_the_sweep_delivers_an_end_a_restart_swallowed(clock, ledger) -> None:
    store = InMemoryStore()
    done = ev.Event(
        ev.WATCH_DONE, "t-late", "r-late01", label="final", text="Render complete: /out/film.mp4"
    )
    await store.aput(
        WATCH_LEDGER,
        "r-late01",
        {
            "thread_id": "t-late",
            "label": "final",
            "status": "done",
            "final": done.to_value(),
            "alive_at": clock.now - 600,
        },
    )
    bus, seen = ev.EventBus(), []
    bus.subscribe(seen.append)

    assert await ledger.sweep(store, bus=bus) == 1
    assert seen == [done] and await _records(store) == {}
    assert "- r-late01 (final) finished. Render complete: /out/film.mp4" in render("t-late", seen)


async def test_the_sweep_leaves_a_record_a_live_watch_holds(clock, ledger) -> None:
    store = InMemoryStore()
    watch_id = ledger.watches.start("t-1", label="x", source=Quiet(), parser=_Never())
    await store.aput(WATCH_LEDGER, watch_id, {"thread_id": "t-1", "alive_at": clock.now - 600})
    assert await ledger.sweep(store, bus=ev.EventBus()) == 0


class _Done:
    """A parser that finishes on the first poll."""

    def parse(self, text: str) -> list[Update]:
        return [Update("done", 1.0, text="finished")]


class _Never:
    """A parser that never finds anything."""

    def parse(self, text: str) -> list[Update]:
        return []
