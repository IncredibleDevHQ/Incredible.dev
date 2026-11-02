"""The inbox: every event for a thread reaches its lead, at a cost the attention rule chooses.

An `Inbox` subscribes to the bus. For each event of a thread it has a target for,
`harness.policy.decide` says:
- `NOW`: wake the lead. Events that land within `COALESCE_SECONDS` of each other, or while a wake-up
  is under way, arrive together in the next one, so the lead is never woken twice at once;
- `NEXT`: hold it for the lead's next turn, whatever starts it: a wake-up (it rides along), or a
  message from the person (the host takes it with `take_held` at the start of that turn);
- `LOG`: recorded only (`check_tasks` and the notices' running lines show the latest).

The host builds one inbox per process and injects its `Waker` (`harness.protocols`), which starts
a lead turn on the thread. Whatever starts work on a thread registers where its lead is
(`set_target`).

A wake-up that fails, or whose receipt says the run did not start, is tried again after 10 s, 1 min
and 5 min (`RETRY_SECONDS`), with whatever landed meanwhile. After the last try its events wait for
the lead's next turn, as held ones do. Nothing counts as delivered until a wake-up went through or
a turn carried it (`delivered`), because the host acts on delivery (it forgets a finished helper's
ledger record then): counting a failed wake-up would lose news the lead never heard.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from design_agent.harness import events as ev
from design_agent.harness import notices
from design_agent.harness.policy import Decision, Delivery, decide
from design_agent.harness.protocols import Waker, WakeTarget

_LOGGER = logging.getLogger(__name__)

#: Events this close together are delivered in one wake-up.
COALESCE_SECONDS = 5.0
#: A wake-up that fails is tried again after each of these; after the last, its events are held.
RETRY_SECONDS: tuple[float, ...] = (10.0, 60.0, 300.0)

Delivered = Callable[[Sequence[ev.Event]], Awaitable[None]]


class WakeNotDelivered(RuntimeError):
    """The waker answered, but the lead's run did not start."""


@dataclass
class ThreadInbox:
    thread_id: str
    target: WakeTarget
    now: list[ev.Event] = field(default_factory=list)
    held: list[ev.Event] = field(default_factory=list)
    delivery: asyncio.Task[None] | None = None


def dedupe_key(thread_id: str, batch: Sequence[ev.Event]) -> str:
    """One key per thread and set of events, so a retried wake-up of the same batch that
    did start a run is not started twice by the waker."""
    digest = hashlib.sha256(",".join(sorted(e.id for e in batch)).encode()).hexdigest()
    return f"{thread_id}:{digest[:16]}"


class Inbox:
    """Delivers each thread's events to its lead through the injected `Waker` (module doc)."""

    def __init__(
        self,
        waker: Waker,
        *,
        render: Callable[[str, Sequence[ev.Event]], str] = notices.render,
        policy: Callable[[ev.Event], Decision] = decide,
        bus: ev.EventBus | None = None,
    ) -> None:
        self._waker = waker
        self._render = render
        self._policy = policy
        self._bus = bus or ev.BUS
        self._on_delivered: list[Delivered] = []
        self._detach: Callable[[], None] | None = None
        #: Per thread id.
        self.boxes: dict[str, ThreadInbox] = {}

    def on_delivered(self, callback: Delivered) -> None:
        """Run `callback` with each batch the lead has heard (`delivered`)."""
        if callback not in self._on_delivered:
            self._on_delivered.append(callback)

    def attach(self) -> None:
        """Listen to the bus (done by `set_target`)."""
        if self._detach is None:
            self._detach = self._bus.subscribe(self.handle)

    def set_target(self, thread_id: str, target: WakeTarget) -> None:
        """Where to wake this thread's lead. The latest registration wins."""
        self.attach()
        box = self.boxes.get(thread_id)
        if box is None:
            self.boxes[thread_id] = ThreadInbox(thread_id, target)
        else:
            box.target = target

    def box(self, thread_id: str) -> ThreadInbox | None:
        return self.boxes.get(thread_id)

    def handle(self, event: ev.Event) -> None:
        box = self.boxes.get(event.thread_id)
        if box is None:
            return
        decision = self._policy(event)
        if decision.delivery is Delivery.LOG:
            return
        if decision.delivery is Delivery.NOW:
            box.now.append(event)
            self._ensure_delivery(box)
        else:
            box.held.append(event)

    def _ensure_delivery(self, box: ThreadInbox) -> None:
        if box.delivery is None or box.delivery.done():
            box.delivery = asyncio.get_running_loop().create_task(
                self._deliver(box), name=f"wake {box.thread_id}"
            )

    def take_held(self, thread_id: str) -> list[ev.Event]:
        """The events of a thread not yet on their way to its lead, removed: held ones, and due
        ones still coalescing. A lead turn is starting anyway (a message from the person, or a
        wake-up that carried earlier events), so they reach the lead then rather than in another
        wake-up. The caller reports them with `delivered` once the turn carries them."""
        box = self.boxes.get(thread_id)
        if box is None or not (box.held or box.now):
            return []
        taken, box.now, box.held = [*box.now, *box.held], [], []
        return taken

    async def delivered(self, batch: Sequence[ev.Event]) -> None:
        """The lead has heard `batch`, from a wake-up or a turn that carried it: run the
        `on_delivered` callbacks."""
        for callback in self._on_delivered:
            try:
                await callback(batch)
            except Exception as error:  # noqa: BLE001
                _LOGGER.warning("[harness] after delivery: %s", type(error).__name__)

    async def _wake(self, box: ThreadInbox, batch: Sequence[ev.Event]) -> None:
        receipt = await self._waker.wake(
            box.target,
            self._render(box.thread_id, batch),
            dedupe_key=dedupe_key(box.thread_id, batch),
        )
        if not receipt.delivered:
            raise WakeNotDelivered(receipt.detail or "the lead's run did not start")

    async def _deliver(self, box: ThreadInbox) -> None:
        """Wake the lead until nothing is due. Held events ride along with each wake-up.

        A wake-up that fails is tried again after each of `RETRY_SECONDS`, with whatever landed
        meanwhile. After the last try its events are held, so the lead's next turn carries them:
        the next wake-up (any later `NOW` event starts one), or a message from the person. Only a
        wake-up that went through counts as delivered.
        """
        failures = 0
        while box.now:
            await asyncio.sleep(RETRY_SECONDS[failures - 1] if failures else COALESCE_SECONDS)
            batch, box.now, box.held = [*box.now, *box.held], [], []
            if not batch:  # a lead turn took them meanwhile (`take_held`)
                return
            try:
                await self._wake(box, batch)
            except Exception as error:  # noqa: BLE001 - retried, then held for the next turn
                failures += 1
                if failures > len(RETRY_SECONDS):
                    box.held, box.now = [*batch, *box.now, *box.held], []
                    _LOGGER.warning(
                        "[harness] waking the lead failed: %s; %d events held for its next turn",
                        type(error).__name__,
                        len(box.held),
                    )
                    return
                box.now[:0] = batch
                _LOGGER.warning(
                    "[harness] waking the lead failed: %s; trying again in %.0f s",
                    type(error).__name__,
                    RETRY_SECONDS[failures - 1],
                )
            else:
                failures = 0
                await self.delivered(batch)

    def reset(self) -> None:
        """Forget every thread's inbox, cancelling pending deliveries (tests, shutdown)."""
        for box in self.boxes.values():
            if box.delivery is not None and not box.delivery.done():
                box.delivery.cancel()
        self.boxes.clear()

    def close(self) -> None:
        """Stop listening to the bus and forget every thread."""
        self.reset()
        if self._detach is not None:
            self._detach()
            self._detach = None
