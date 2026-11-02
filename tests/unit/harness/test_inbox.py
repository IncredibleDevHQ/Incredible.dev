"""The inbox's delivery: a wake-up that fails is tried again, and nothing it carried is lost.

A failed wake-up must never count as delivered, or the host forgets news the lead never heard.
Each test runs a private `Inbox` on its own bus, with a `Waker` that fails as told and a render of
one line per event, so it reads exactly what each wake-up carried.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from datetime import datetime

import pytest

from design_agent.harness import events as ev
from design_agent.harness import inbox as harness_inbox
from design_agent.harness.inbox import Inbox, dedupe_key
from design_agent.harness.protocols import Waker, WakeReceipt, WakeTarget

TARGET = WakeTarget("t-1", channel={"reply": "opaque"})
INBOXES: list[Inbox] = []


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(harness_inbox, "COALESCE_SECONDS", 0)
    monkeypatch.setattr(harness_inbox, "RETRY_SECONDS", (0.0, 0.0, 0.0))
    yield
    for inbox in INBOXES:
        inbox.close()
    INBOXES.clear()


class FlakyWaker:
    """Fails its first `failures` calls with a 404 and keeps what each call carried. `landing`
    publishes an event during the given call, as when news lands while a wake-up is under way.
    With `refuse`, a failure is a receipt saying the run did not start instead of an error."""

    def __init__(
        self,
        bus: ev.EventBus,
        *,
        failures: float,
        landing: dict[int, ev.Event] | None = None,
        refuse: bool = False,
    ) -> None:
        self.bus, self.failures, self.landing = bus, failures, landing or {}
        self.refuse = refuse
        self.calls: list[list[str]] = []
        self.targets: list[WakeTarget] = []
        self.keys: list[str] = []

    async def wake(self, target: WakeTarget, message: str, *, dedupe_key: str) -> WakeReceipt:
        self.calls.append(message.splitlines())
        self.targets.append(target)
        self.keys.append(dedupe_key)
        if len(self.calls) in self.landing:
            self.bus.publish(self.landing[len(self.calls)])
        if len(self.calls) <= self.failures:
            if self.refuse:
                return WakeReceipt(delivered=False, detail="the thread is busy")
            raise RuntimeError("404 Not Found")
        return WakeReceipt(delivered=True, run_id=f"run-{len(self.calls)}")

    async def schedule(self, target: WakeTarget, at: datetime, message: str) -> str:
        raise NotImplementedError

    async def cancel(self, schedule_id: str) -> None:
        raise NotImplementedError


def _render(_thread_id: str, events: Sequence[ev.Event]) -> str:
    return "\n".join(event.text for event in events)


def _event(kind: str, text: str) -> ev.Event:
    return ev.Event(kind, "t-1", "t-writer", label="writer", text=text)


def _inbox(waker: FlakyWaker) -> tuple[Inbox, list[tuple[int, list[str]]]]:
    """A private inbox for thread t-1 on the waker's bus, and what it reports delivered: one entry
    per batch, with how many wake-ups had gone out by then."""
    heard: list[tuple[int, list[str]]] = []

    async def delivered(batch: Sequence[ev.Event]) -> None:
        heard.append((len(waker.calls), [event.text for event in batch]))

    inbox = Inbox(waker, render=_render, bus=waker.bus)
    INBOXES.append(inbox)
    inbox.on_delivered(delivered)
    inbox.set_target("t-1", TARGET)
    return inbox, heard


async def _delivery(inbox: Inbox) -> None:
    """Wait for thread t-1's delivery to end."""
    box = inbox.box("t-1")
    assert box is not None and box.delivery is not None
    await asyncio.wait_for(box.delivery, timeout=5)


async def test_a_failed_wake_up_is_retried_and_carries_everything_once() -> None:
    """A helper's progress note and its finish, and a render that finished while the first
    wake-up was failing."""
    bus = ev.EventBus()
    waker = FlakyWaker(bus, failures=2, landing={1: _event(ev.WATCH_DONE, "render finished")})
    inbox, heard = _inbox(waker)

    bus.publish(_event(ev.TASK_PROGRESS, "writer started"))  # held for the lead's next turn
    bus.publish(_event(ev.TASK_DONE, "script is in"))
    await _delivery(inbox)

    assert waker.calls[0] == ["script is in", "writer started"]
    assert len(waker.calls) == 3
    assert sorted(waker.calls[2]) == ["render finished", "script is in", "writer started"]
    # Reported delivered once, after the wake-up that went through, and never after a failed one.
    assert heard == [(3, waker.calls[2])]


async def test_after_the_last_retry_the_events_wait_for_the_leads_next_turn() -> None:
    bus = ev.EventBus()
    tries = 1 + len(harness_inbox.RETRY_SECONDS)
    last = _event(ev.WATCH_DONE, "render finished")  # lands during the last try
    waker = FlakyWaker(bus, failures=math.inf, landing={tries: last})
    inbox, heard = _inbox(waker)

    bus.publish(_event(ev.TASK_PROGRESS, "writer started"))
    bus.publish(_event(ev.TASK_DONE, "script is in"))
    await _delivery(inbox)

    assert len(waker.calls) == tries and heard == []
    news = ["script is in", "writer started", "render finished"]
    box = inbox.box("t-1")
    assert box is not None
    assert not box.now and [event.text for event in box.held] == news
    assert [event.text for event in inbox.take_held("t-1")] == news
    assert inbox.take_held("t-1") == []


async def test_events_held_after_the_last_retry_ride_along_with_the_next_wake_up() -> None:
    bus = ev.EventBus()
    waker = FlakyWaker(bus, failures=1 + len(harness_inbox.RETRY_SECONDS))
    inbox, heard = _inbox(waker)
    bus.publish(_event(ev.TASK_DONE, "script is in"))
    await _delivery(inbox)
    box = inbox.box("t-1")
    assert box is not None
    assert heard == [] and [event.text for event in box.held] == ["script is in"]

    bus.publish(_event(ev.WAKEUP_DUE, "check the render"))  # starts a fresh delivery
    await _delivery(inbox)

    assert waker.calls[-1] == ["check the render", "script is in"]
    assert heard == [(len(waker.calls), ["check the render", "script is in"])]
    assert not box.held


async def test_a_receipt_that_says_the_run_did_not_start_is_retried() -> None:
    """Delivery counts only once the lead's run actually started."""
    bus = ev.EventBus()
    waker = FlakyWaker(bus, failures=1, refuse=True)
    inbox, heard = _inbox(waker)

    bus.publish(_event(ev.TASK_DONE, "script is in"))
    await _delivery(inbox)

    assert len(waker.calls) == 2 and heard == [(2, ["script is in"])]
    # The same batch both times: the waker can tell a retry from a new wake-up.
    assert waker.keys[0] == waker.keys[1]
    assert waker.targets == [TARGET, TARGET]


async def test_the_waker_is_the_injected_one_and_targets_are_per_thread() -> None:
    bus = ev.EventBus()
    waker = FlakyWaker(bus, failures=0)
    inbox, _ = _inbox(waker)
    assert isinstance(waker, Waker)
    later = WakeTarget("t-1", channel="newer")
    inbox.set_target("t-1", later)  # the latest registration wins
    bus.publish(ev.Event(ev.TASK_DONE, "t-unknown", "t-x", text="nobody registered"))
    bus.publish(_event(ev.TASK_DONE, "script is in"))
    await _delivery(inbox)

    assert waker.targets == [later] and waker.calls == [["script is in"]]
    assert inbox.box("t-unknown") is None


def test_the_dedupe_key_names_the_thread_and_the_batch() -> None:
    one, two = _event(ev.TASK_DONE, "a"), _event(ev.TASK_DONE, "b")
    assert dedupe_key("t-1", [one, two]) == dedupe_key("t-1", [two, one])
    assert dedupe_key("t-1", [one]) != dedupe_key("t-1", [one, two])
    assert dedupe_key("t-1", [one]).startswith("t-1:") != dedupe_key("t-2", [one]).startswith(
        "t-1:"
    )
