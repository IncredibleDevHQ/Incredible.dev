"""The MDA waker on a fake `runtime.schedules`: wake-ups confirmed by the run that starts, and a
restart sentinel this process keeps pushing ahead, so it fires only after a restart."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langgraph.store.memory import InMemoryStore

from design_agent.harness.tasks import REGISTRY, TaskRecord
from design_agent.middleware.quiet import SENTINEL_MARK, running_status
from design_agent.runtime.waker import wake_marker
from design_agent.runtime.waker.mda import LEAD_SECONDS, MdaScheduleWaker

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


class FakeSchedules:
    def __init__(self) -> None:
        self.live: dict[str, dict[str, Any]] = {}
        self.created: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    async def create(self, **kwargs: Any) -> dict[str, Any]:
        schedule_id = f"s{len(self.created)}"
        record = {"id": schedule_id, **kwargs}
        self.created.append(record)
        self.live[schedule_id] = record
        return record

    async def delete(self, schedule_id: str, *, owner: dict[str, str]) -> None:
        if schedule_id not in self.live:
            raise KeyError(schedule_id)
        assert owner == self.live[schedule_id]["owner"]
        del self.live[schedule_id]
        self.deleted.append(schedule_id)


def runtime_for(schedules: FakeSchedules, store: Any, *, channel: bool = True) -> Any:
    return SimpleNamespace(
        config={"configurable": {"thread_id": "t1"}},
        schedules=schedules,
        channel=object() if channel else None,
        store=store,
    )


@pytest.fixture(autouse=True)
def clean() -> Iterator[None]:
    yield
    REGISTRY.clear()


def helper(label: str = "act 2", minutes: float = 12) -> TaskRecord:
    record = TaskRecord(
        id="t-1",
        thread_id="t1",
        effort="xhigh",
        label=label,
        wave=None,
        started_at=time.time() - minutes * 60,
    )
    REGISTRY[record.id] = record
    return record


async def test_a_wake_up_is_a_same_thread_schedule_confirmed_when_its_run_starts() -> None:
    schedules, store = FakeSchedules(), InMemoryStore()
    waker = MdaScheduleWaker(clock=lambda: NOW, poll_seconds=0.01)
    target = await waker.capture(runtime_for(schedules, store))
    assert target is not None

    pending = asyncio.create_task(waker.wake(target, "Act 2 finished.", dedupe_key="t1:abc"))
    await asyncio.sleep(0.05)
    (created,) = schedules.created
    assert created["owner"] == {"type": "agent"} and created["new_thread"] is False
    assert created["at"] == NOW + timedelta(seconds=LEAD_SECONDS)
    assert wake_marker("t1:abc") in created["prompt"]
    assert not pending.done(), "not delivered until the run reports it started"

    await waker.on_turn_start(runtime_for(schedules, store), [HumanMessage(created["prompt"])])
    receipt = await asyncio.wait_for(pending, 1)
    assert receipt.delivered


async def test_a_run_without_a_channel_owns_its_schedules_as_the_user() -> None:
    schedules = FakeSchedules()
    waker = MdaScheduleWaker(clock=lambda: NOW)
    target = await waker.capture(runtime_for(schedules, None, channel=False))
    assert target is not None
    await waker.schedule(target, NOW + timedelta(minutes=10), "Check the render.")
    assert schedules.created[0]["owner"] == {"type": "user"}


async def test_the_sentinel_is_kept_ahead_while_work_runs_and_dropped_after() -> None:
    schedules = FakeSchedules()
    waker = MdaScheduleWaker(clock=lambda: NOW, postpone_seconds=0.02)
    target = await waker.capture(runtime_for(schedules, None))
    assert target is not None
    record = helper()

    await waker.watchdog(target, True)
    await asyncio.sleep(0.07)
    assert len(schedules.created) >= 3, "pushed forward each period"
    assert len(schedules.live) == 1, "one sentinel at a time"
    (sentinel,) = schedules.live.values()
    assert SENTINEL_MARK in sentinel["prompt"]
    assert sentinel["at"] == NOW + timedelta(minutes=15)

    record.status = "done"
    await asyncio.sleep(0.05)
    assert schedules.live == {}, "no work, no sentinel"


async def test_a_fired_sentinel_re_arms_only_while_work_still_runs() -> None:
    schedules = FakeSchedules()
    waker = MdaScheduleWaker(clock=lambda: NOW, postpone_seconds=60)
    runtime = runtime_for(schedules, None)
    target = await waker.capture(runtime)
    assert target is not None
    helper()
    await waker.watchdog(target, True)
    fired = schedules.created[-1]
    schedules.live.pop(fired["id"])  # MDA ran it

    await waker.on_turn_start(runtime, [HumanMessage(fired["prompt"])])
    assert len(schedules.live) == 1 and schedules.created[-1]["id"] != fired["id"]

    REGISTRY.clear()
    again = schedules.created[-1]
    schedules.live.pop(again["id"])
    await waker.on_turn_start(runtime, [HumanMessage(again["prompt"])])
    assert schedules.live == {}


def test_the_quiet_status_names_the_running_work() -> None:
    assert running_status("t1") == "Nothing new since my last message."
    helper("the final render", minutes=7)
    assert (
        running_status("t1") == "Still working: the final render (7 min). I'll post when it lands."
    )


async def test_a_lifecycle_hook_runtime_without_config_uses_the_ambient_thread() -> None:
    from langchain_core.runnables.config import var_child_runnable_config

    schedules = FakeSchedules()
    waker = MdaScheduleWaker(clock=lambda: NOW)
    hook_runtime = SimpleNamespace(schedules=schedules, channel=object(), store=None)  # no `config`
    token = var_child_runnable_config.set({"configurable": {"thread_id": "t9"}})
    try:
        target = await waker.capture(hook_runtime)
    finally:
        var_child_runnable_config.reset(token)
    assert target is not None and target.thread_id == "t9"
