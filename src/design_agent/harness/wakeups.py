"""Check-ins: the lead wakes itself later on the same thread, with a note it leaves for itself.

The lead picks a delay by what it is waiting for, leaves a prompt for its future self, and says in
one line why. Tracked work (helpers, watches) reports by itself, so a check-in is for keeping a
person informed through a long job, or for work nothing reports on. The wake-up is saved in the
ledger, so a restart fires it late rather than never.

A due check-in is a `WAKEUP_DUE` event: the inbox wakes the lead with the note, together with
whatever else is waiting for it.

Deep Agents has no self-scheduled wake-up. A host whose runtime keeps durable schedules (MDA's
one-time schedules) can also route check-ins through `Waker.schedule`.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from design_agent.harness import events as ev
from design_agent.harness import ledger

#: Seconds in a minute of delay (tests shorten it).
SECONDS_PER_MINUTE = 60.0


@dataclass
class Wakeup:
    id: str
    thread_id: str
    due_at: float
    prompt: str
    reason: str
    set_at: float
    store: Any = field(default=None, repr=False)
    #: Adapter data a later process needs (the wake target). Persisted in the ledger.
    meta: dict[str, Any] = field(default_factory=dict)
    handle: asyncio.Task[None] | None = field(default=None, repr=False)

    def value(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "due_at": self.due_at,
            "prompt": self.prompt,
            "reason": self.reason,
            "set_at": self.set_at,
            **(self.meta or {}),
        }


#: Every check-in this process holds a timer for, by id.
WAKEUPS: dict[str, Wakeup] = {}


async def schedule(wakeup: Wakeup, *, bus: ev.EventBus | None = None) -> None:
    bus = bus or ev.BUS
    WAKEUPS[wakeup.id] = wakeup
    await ledger.save_wakeup(wakeup.store, wakeup.id, wakeup.value())
    wakeup.handle = asyncio.get_running_loop().create_task(
        _fire_later(wakeup, bus), name=f"check-in {wakeup.id}"
    )
    bus.publish(
        ev.Event(
            ev.WAKEUP_SET,
            wakeup.thread_id,
            wakeup.id,
            label=wakeup.reason,
            text=wakeup.prompt,
            data={"due_at": wakeup.due_at, "reason": wakeup.reason},
        )
    )


async def _fire_later(wakeup: Wakeup, bus: ev.EventBus) -> None:
    await asyncio.sleep(max(0.0, wakeup.due_at - time.time()))
    WAKEUPS.pop(wakeup.id, None)
    await ledger.drop_wakeup(wakeup.store, wakeup.id)
    fire(wakeup, bus=bus)


def fire(wakeup: Wakeup, *, bus: ev.EventBus | None = None, late: bool = False) -> None:
    (bus or ev.BUS).publish(
        ev.Event(
            ev.WAKEUP_DUE,
            wakeup.thread_id,
            wakeup.id,
            label=wakeup.reason + (", fired late after a restart" if late else ""),
            text=wakeup.prompt,
            data={"set_at": wakeup.set_at, "due_at": wakeup.due_at, "reason": wakeup.reason},
        )
    )


def cancel(wakeup_id: str, thread_id: str) -> bool:
    wakeup = WAKEUPS.get(wakeup_id)
    if wakeup is None or wakeup.thread_id != thread_id:
        return False
    WAKEUPS.pop(wakeup_id, None)
    if wakeup.handle is not None:
        wakeup.handle.cancel()
    asyncio.get_running_loop().create_task(ledger.drop_wakeup(wakeup.store, wakeup.id))
    ev.BUS.publish(ev.Event(ev.WAKEUP_CANCELLED, wakeup.thread_id, wakeup.id, label=wakeup.reason))
    return True


def pending(thread_id: str) -> list[Wakeup]:
    return [w for w in WAKEUPS.values() if w.thread_id == thread_id]
