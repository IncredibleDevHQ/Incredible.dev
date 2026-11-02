"""The attention rule: who hears about an event, and when.

Every event reaches the lead; nothing is dropped. What this decides is the cost of hearing it:
- `NOW`: wake the lead with a new turn as soon as the event lands (coalesced with anything else that
  lands within a few seconds). Results, failures, stalls, interruptions, check-ins that came due and
  anything someone must act on.
- `NEXT`: hold it for the lead's next turn, whatever starts it: an alert, a check-in the lead
  scheduled, or a message from the person. A helper's progress note, a pipeline step. The lead
  chooses how closely to follow a task (its own check-ins, or `wake_on_progress` on a task, which
  marks that task's notes urgent), so it hears everything without a model call per note.
- `LOG`: record it only (the event log; `check_tasks` and each notice's "still running" lines
  show the latest). Nothing wakes or waits for the lead. Frequent ticks such as a render's
  per-frame counter, starts, usage.

`ping` marks an event a person must act on (an approval, the final, a failure the lead cannot fix
alone): it wakes the lead at once, and the lead asks them in the thread.

Deep Agents has no push: `AsyncSubAgentMiddleware` has the lead poll with `check_async_task`.
Upstream, this is a small pure function next to the event type.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from design_agent.harness import events as ev


class Delivery(StrEnum):
    NOW = "now"
    NEXT = "next"
    LOG = "log"


@dataclass(frozen=True)
class Decision:
    delivery: Delivery
    ping: bool = False


DEFAULT_RULES: Mapping[str, Decision] = {
    ev.TASK_STARTED: Decision(Delivery.LOG),
    ev.TASK_PROGRESS: Decision(Delivery.NEXT),
    ev.TASK_DONE: Decision(Delivery.NOW),
    ev.TASK_FAILED: Decision(Delivery.NOW),
    ev.TASK_CANCELLED: Decision(Delivery.LOG),
    ev.TASK_INTERRUPTED: Decision(Delivery.NOW),
    ev.WAKEUP_DUE: Decision(Delivery.NOW),
    ev.WAKEUP_SET: Decision(Delivery.LOG),
    ev.WAKEUP_CANCELLED: Decision(Delivery.LOG),
    ev.WATCH_STARTED: Decision(Delivery.LOG),
    ev.WATCH_PROGRESS: Decision(Delivery.LOG),
    ev.WATCH_ERROR: Decision(Delivery.NOW),
    ev.WATCH_STALLED: Decision(Delivery.NOW),
    ev.WATCH_DONE: Decision(Delivery.NOW),
    ev.JOB_PHASE: Decision(Delivery.LOG),
    ev.JOB_ATTENTION: Decision(Delivery.NOW, ping=True),
    ev.PIPELINE_STEP: Decision(Delivery.NEXT),
    ev.USAGE: Decision(Delivery.LOG),
}


def decide(event: ev.Event, rules: Mapping[str, Decision] = DEFAULT_RULES) -> Decision:
    """The decision for one event. `data["urgent"]` promotes anything to `NOW`;
    `data["ping"]` adds a ping. Unknown kinds wake the lead: never silently drop what we don't know."""
    decision = rules.get(event.kind, Decision(Delivery.NOW))
    if event.data.get("urgent") and decision.delivery is not Delivery.NOW:
        decision = Decision(Delivery.NOW, decision.ping)
    if event.data.get("ping") and not decision.ping:
        decision = Decision(decision.delivery, True)
    return decision
