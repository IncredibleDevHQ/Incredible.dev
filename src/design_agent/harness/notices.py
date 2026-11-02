"""The notice the lead is woken with: what happened in the background, and what is still running.

A notice is a message appended to the lead's conversation (never edited, so the prompt cache
holds) that says how each helper ended with its report, what helpers and
watches reported, which check-ins came due, what still runs, and what the lead might do next. It is
rendered from the events the inbox delivers, so a new kind of source only needs a line format here.

Two things stay out of it on purpose:
- per-call timers in the system prompt: time-varying text there breaks the cache on every call. The
  running list lives here, in a message written once;
- instructions that decide for the lead: it gets the facts and the likely next step, and judges.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from design_agent.harness import events as ev
from design_agent.harness.tasks import minutes

#: A wake-up reply that is exactly this is not posted anywhere.
QUIET = "[quiet]"
#: Set by the adapter: text a helper's report carries when it stopped at the graph's step limit.
PARTIAL_MARKER: str | None = None

#: Sources of "still running" lines, one callable per kind of background work (helpers, watches,
#: pipelines). Each takes a thread id and returns lines like "t-1a2b3c (xhigh, act 3, 12 min)".
RUNNING_PROVIDERS: list[Callable[[str], list[str]]] = []
#: Sources of scheduled check-in ids for a thread.
SCHEDULED_PROVIDERS: list[Callable[[str], list[str]]] = []

_ENDED = {ev.TASK_DONE, ev.TASK_FAILED}
_WATCH_ALERTS = {ev.WATCH_ERROR, ev.WATCH_STALLED}


def _took(event: ev.Event) -> str:
    started = float(event.data.get("started_at") or event.at)
    finished = float(event.data.get("finished_at") or event.at)
    return minutes(finished - started)


def _head(event: ev.Event) -> str:
    effort = event.data.get("effort")
    wave = event.data.get("wave")
    parts = [p for p in (effort, event.label) if p]
    return f"- {event.source} ({', '.join(parts)}{', wave ' + str(wave) if wave else ''})"


def _line(event: ev.Event) -> str:
    kind, head = event.kind, _head(event)
    if kind == ev.TASK_DONE:
        report = event.text.strip() or "(no report)"
        ended = (
            "stopped early at the graph's step limit"
            if PARTIAL_MARKER and PARTIAL_MARKER in report
            else "done"
        )
        return f"{head}: {ended} in {_took(event)}. Its report:\n{report}"
    if kind == ev.TASK_FAILED:
        return f"{head}: failed after {_took(event)}. {event.text}".rstrip()
    if kind == ev.TASK_INTERRUPTED:
        return f"{head}: interrupted by a restart after {_took(event)}. {event.text}".rstrip()
    if kind == ev.TASK_PROGRESS:
        return f"{head} reports: {event.text}"
    if kind == ev.PIPELINE_STEP:
        return f"- {event.source} ({event.label}): {event.text}"
    if kind == ev.WAKEUP_DUE:
        set_at = float(event.data.get("set_at") or event.at)
        return (
            f"- Your wake-up {event.source}, set {minutes(time.time() - set_at)} ago "
            f"({event.label}). Your note: {event.text}"
        )
    if kind == ev.WATCH_ERROR:
        return f"- {event.source} ({event.label}) failed:\n{event.text}".rstrip()
    if kind == ev.WATCH_STALLED:
        why = "timed out" if event.data.get("timeout") else "has shown no progress"
        return f"- {event.source} ({event.label}) {why}. {event.text}".rstrip()
    if kind == ev.WATCH_DONE:
        return f"- {event.source} ({event.label}) finished. {event.text}".rstrip()
    if kind == ev.WATCH_PROGRESS:
        fraction = event.data.get("fraction")
        pct = f"{round(float(fraction) * 100)}%" if fraction is not None else event.text
        if event.data.get("resumed"):
            return f"- {event.source} ({event.label}) is moving again: {event.text or pct}"
        return f"- {event.source} ({event.label}): {pct}"
    if kind == ev.JOB_ATTENTION:
        return (
            f"- {event.label or event.source} needs someone: {event.text} (the person was pinged)"
        )
    return f"- {event.kind} from {event.source} ({event.label}): {event.text}".rstrip()


def _title(events: Sequence[ev.Event]) -> str:
    kinds = {e.kind for e in events}
    if kinds & _ENDED:
        return "Background work finished"
    if ev.TASK_INTERRUPTED in kinds:
        return "Background work was interrupted"
    if kinds & _WATCH_ALERTS:
        return "A watched job needs you"
    if ev.WATCH_DONE in kinds:
        return "A watched job finished"
    if ev.JOB_ATTENTION in kinds:
        return "Someone needs to act"
    if kinds & {ev.TASK_PROGRESS, ev.PIPELINE_STEP, ev.WATCH_PROGRESS}:
        return "Progress from background work"
    if ev.WAKEUP_DUE in kinds:
        return "The wake-up you scheduled"
    return "Background update"


def render(thread_id: str, events: Sequence[ev.Event], *, guidance: bool = True) -> str:
    """The wake-up message for one delivery: the events in the order they happened. Without
    `guidance` it is only the news (for a turn the person started: they asked for something else)."""
    events = sorted(events, key=lambda e: e.at)
    ended = [e for e in events if e.kind in _ENDED]
    finished = ended + [e for e in events if e.kind == ev.TASK_INTERRUPTED]
    header = f"[Runtime notice, not from the user] {_title(events)}"
    header += f" ({len(finished)} tasks)." if len(finished) > 1 else "."
    lines = [header, *(_line(e) for e in events)]

    running = [line for provider in RUNNING_PROVIDERS for line in provider(thread_id)]
    if running:
        lines.append(
            f"Still running: {'; '.join(running)}. Each wakes you when it ends or needs you; "
            "progress notes reach you with your next turn."
        )
    if not guidance:
        return "\n".join(lines)
    kinds = {e.kind for e in events}
    if ev.TASK_INTERRUPTED in kinds:
        lines.append(
            "Resume each interrupted task now with resume_task: it continues from its saved "
            "transcript, in the same sandbox. If nothing was saved, re-issue it with start_task "
            "under the resume preamble (/skills/launch-film/briefs/resume.md), since its files and "
            "progress notes are on disk. Tell the person what happened and the new ETA."
        )
    if kinds & _WATCH_ALERTS:
        lines.append(
            "Look at what the watch reported: fix and restart the job, or tell the person what "
            "happened and what you'll do."
        )
    if ev.WAKEUP_DUE in kinds:
        lines.append(
            "Do what your note says. If work is still running, schedule the next wake-up before you "
            "end the turn; if it is done, don't."
        )
    if not finished and not kinds & (_WATCH_ALERTS | {ev.WATCH_DONE, ev.JOB_ATTENTION}):
        lines.append(
            "If this changes what the person expects, tell them in a line; otherwise reply with "
            f"exactly {QUIET}: at most a one-line status of the running work is posted."
        )
    elif not ended:
        pass
    elif running:
        lines.append(
            "Do what this result needs now: review it, or start the work that depends only on it, in "
            "the background. Leave what depends on the running work (integration, shared-file "
            "merges) until it lands. Tell the person in a line or two what landed and what comes "
            "next, with an ETA."
        )
    else:
        lines.append(
            "Nothing else is running. Review these results against the plan (a critic pass if the "
            "plan calls for one), start the next step, and tell the person where things stand and "
            "what comes next, with an ETA."
        )
        scheduled = [i for provider in SCHEDULED_PROVIDERS for i in provider(thread_id)]
        if scheduled:
            lines.append(
                f"Check-ins still scheduled: {', '.join(scheduled)}. Cancel them if the work is done."
            )
    # Without this, replies borrow the notice's vocabulary, and the people reading them are not
    # engineers.
    lines.append(
        "Whatever you tell the person, say it about the work, in a teammate's words: the tasks, "
        "watches, logs and check-ins above are yours, not theirs."
    )
    return "\n".join(lines)


def should_post(text: str) -> bool:
    """A wake-up reply is posted unless it is empty or the lead chose to stay quiet."""
    return bool(text) and text.strip() != QUIET
