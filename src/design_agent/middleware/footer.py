"""A footer line under the lead's replies in a Slack thread while it has work in the background.

It says only what changes. While work runs: `Trace • 2 agents running • render 45%, ~6 min left
• 12 min • ~$12.40 so far`, redrawn as the work moves; under the reply that closes the job it
settles to `Trace • 3 agents • 14 min • ~$18.20 total`. Cost is the meter's estimate
(`METER.summary`), counted from the job's start; "Trace" links the trace of the run that wrote
the reply, and appears only when `DESIGN_AGENT_TRACE_HOST` is set (`middleware/tracing.py`).

A turn with nothing in the background gets no footer: a footer is a message of its own, and one
under every reply would be a second notification each time. Nor does a `[quiet]` turn, a turn
that says nothing, or a run that ended in code before this saw it start (a follow-up already
worked into the run before it): none of them wrote a reply of the job's.

The reply is not this app's message: the platform posts it after the run ends. So the footer is
posted right after the reply lands, found by reading the thread a few times (`REPLY_CHECKS`; Slack
allows `conversations.replies` about 50 times a minute per app). While anything runs for the
thread, the newest footer is redrawn every `REFRESH_SECONDS` from what this process holds: the
running helpers, the watches and the meter. A newer reply's footer takes over, and the older one
keeps what the job had cost by then. Slack failures are swallowed with the error code logged.

Each thread's job and newest footer are saved in the store (`FOOTER_NAMESPACE`): a restart kills
the process holding them, and the next one carries on counting from what the job had cost and
retires the dead process's footer, which would otherwise say agents are running forever.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain.agents.middleware import AgentMiddleware, AgentState

from design_agent.harness import tasks
from design_agent.harness.inbox import Inbox
from design_agent.harness.notices import QUIET, should_post
from design_agent.middleware.meter import METER
from design_agent.middleware.progress import posted_reply
from design_agent.middleware.tracing import TraceLinks, TraceRoot, current_root
from design_agent.surfaces.slack.client import SlackClient, SlackError
from design_agent.surfaces.slack.target import SlackBinding, SlackSurface, thread_of

_LOGGER = logging.getLogger(__name__)

REFRESH_SECONDS = 15.0
#: How long the newest footer waits, once nothing runs and no news is on its way to the lead,
#: before it settles to the job's totals: time for a last reply's own footer to take over.
SETTLE_SECONDS = 30.0
#: When to look for the reply after its run ended: it usually lands within a second or two.
REPLY_CHECKS: tuple[float, ...] = (2.0, 4.0, 8.0, 16.0)
FOOTER_NAMESPACE = ("design_agent", "footer")
#: A saved job older than this is over, whatever it says.
ADOPT_SECONDS = 6 * 3600.0

State = Literal["live", "snapshot", "done"]


def footer_line(
    trace: str,
    state: State,
    *,
    usd: float,
    running: int = 0,
    progress: str = "",
    agents: int = 0,
    minutes: int = 0,
) -> str:
    """The footer in Slack markup: `live` while the job runs, `done` once it has, `snapshot` for
    an older footer a newer reply took over. `usd` is the job's estimated cost so far."""
    parts = [f"<{trace}|Trace>"] if trace else []
    if state == "live":
        # A watched job in the sandbox is not an agent: its progress says it is running.
        if running:
            parts.append(f"{_count(running, 'agent')} running")
        if progress:
            parts.append(progress)
        if minutes >= 1:
            parts.append(f"{minutes} min")
        parts.append(f"~{_usd(usd)} so far")
    elif state == "done":
        if agents:
            parts.append(_count(agents, "agent"))
        parts += [f"{max(minutes, 1)} min", f"~{_usd(usd)} total"]
    else:
        parts.append(f"~{_usd(usd)} so far")
    return " • ".join(parts)


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _usd(usd: float) -> str:
    return f"${max(usd, 0.0):,.2f}"


def _blocks(text: str) -> list[dict[str, object]]:
    return [{"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}]


def _watches(thread_id: str) -> list[Any]:
    from design_agent.middleware.watch_tools import WATCHES

    return list(WATCHES.list(thread_id))


def watch_progress(thread_id: str) -> str:
    """The first watch with a measured fraction: "render 45%, ~6 min left"."""
    for record in _watches(thread_id):
        if record.status != "watching" or record.fraction is None:
            continue
        text = f"{record.label or 'progress'} {record.fraction * 100:.0f}%"
        if record.eta_seconds:
            text += f", ~{max(round(record.eta_seconds / 60), 1)} min left"
        return text
    return ""


def busy(thread_id: str) -> bool:
    return bool(tasks.running(thread_id)) or any(
        r.status == "watching" for r in _watches(thread_id)
    )


@dataclass
class _Footer:
    channel: str
    ts: str
    trace: str
    text: str = ""
    #: Still saying the job is running; a newer footer turns it into a snapshot.
    live: bool = True


@dataclass
class _Job:
    """A thread's newest footer, and the job it counts while one runs."""

    client: SlackClient
    store: Any = None
    footer: _Footer | None = None
    loop: asyncio.Task[None] | None = None
    #: When the job began, and what the thread had cost by then.
    started: float | None = None
    usd_base: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class Footers:
    """The footers of every thread this process answers in (module doc). `inbox` tells whether
    news of the job is still on its way to the lead, which keeps the job open."""

    def __init__(self, *, traces: TraceLinks | None = None, inbox: Inbox | None = None) -> None:
        self._traces = traces
        self._inbox = inbox
        self._jobs: dict[str, _Job] = {}
        #: Strong references to the work a run's end starts, which outlives the run.
        self._pending: set[asyncio.Task[None]] = set()

    def after_run(
        self,
        thread_id: str,
        binding: SlackBinding,
        *,
        root: TraceRoot | None,
        started: float,
        usd_at_start: float,
        ended: float,
        store: Any = None,
    ) -> None:
        """Post the footer under the reply this run is about to get, and keep it live."""
        task = asyncio.get_running_loop().create_task(
            self._after_run(thread_id, binding, root, started, usd_at_start, ended, store),
            name=f"footer {thread_id}",
        )
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    def news_pending(self, thread_id: str) -> bool:
        """News of the job on its way to the lead: a wake-up queued or under way, or a helper
        that ended without the lead hearing yet. The reply carrying it is the job's last."""
        box = self._inbox.box(thread_id) if self._inbox is not None else None
        if box is not None and (box.now or (box.delivery is not None and not box.delivery.done())):
            return True
        return any(
            r.thread_id == thread_id
            and r.status not in ("running", "cancelled")
            and not r.delivered
            for r in tasks.REGISTRY.values()
        )

    async def _after_run(
        self,
        thread_id: str,
        binding: SlackBinding,
        root: TraceRoot | None,
        started: float,
        usd_at_start: float,
        ended: float,
        store: Any,
    ) -> None:
        client, target = binding.client, binding.target
        job = self._jobs.get(thread_id) or await _adopt(store, thread_id, client)
        if job is not None:
            self._jobs[thread_id] = job
        if not busy(thread_id) and (job is None or job.started is None):
            return
        try:
            if not await _reply_landed(binding, after=ended):
                return
            trace = await self._traces.url(root) if self._traces is not None else ""
            job = self._jobs.setdefault(thread_id, _Job(client, store))
            job.client, job.store = client, job.store or store
            async with job.lock:
                await self._retire(thread_id, job)
                if busy(thread_id) and job.started is None:
                    job.started, job.usd_base = started, usd_at_start
                if job.started is None:
                    return  # the job settled while the reply was on its way
                # Never the totals straight away: more news may be on its way, and the job's
                # last reply is the one they go under. The loop settles the newest footer.
                text = self._line(thread_id, job, trace, "live")
                posted = await client.call(
                    "chat.postMessage",
                    {
                        "channel": target.channel,
                        "thread_ts": target.thread_ts,
                        "text": text,
                        "blocks": _blocks(text),
                    },
                )
                job.footer = _Footer(
                    str(posted.get("channel") or target.channel),
                    str(posted.get("ts") or ""),
                    trace,
                    text,
                )
                await _save(thread_id, job)
                job.loop = asyncio.get_running_loop().create_task(
                    self._follow(thread_id, job), name=f"footer live {thread_id}"
                )
        except SlackError as error:
            _LOGGER.warning("[footer] not posted: %s", error.code)

    def _line(self, thread_id: str, job: _Job, trace: str, state: State) -> str:
        started = job.started or time.time()
        agents = [
            r
            for r in tasks.REGISTRY.values()
            if r.thread_id == thread_id and r.started_at >= started
        ]
        return footer_line(
            trace,
            state,
            usd=METER.summary(thread_id).usd - job.usd_base,
            running=len(tasks.running(thread_id)),
            progress=watch_progress(thread_id),
            agents=len(agents),
            minutes=round((time.time() - started) / 60),
        )

    async def _retire(self, thread_id: str, job: _Job) -> None:
        """A newer reply takes the footer over: the older one keeps the job's cost by then. That
        includes a footer a dead process left saying agents are running."""
        loop, job.loop = job.loop, None
        if loop is not None and not loop.done():
            loop.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await loop
        footer = job.footer
        if footer is None or not footer.live:
            return
        usd = METER.summary(thread_id).usd - job.usd_base
        await self._draw(thread_id, job, footer, footer_line(footer.trace, "snapshot", usd=usd))
        footer.live = False

    async def _follow(self, thread_id: str, job: _Job) -> None:
        """Redraw the newest footer while the job runs, and settle it to the totals once nothing
        runs, no news is on its way to the lead, and no newer reply has taken over."""
        idle_since: float | None = None
        while True:
            await asyncio.sleep(REFRESH_SECONDS)
            footer = job.footer
            if footer is None:
                return
            live = self._line(thread_id, job, footer.trace, "live")
            if busy(thread_id) or self.news_pending(thread_id):
                idle_since = None
                await self._draw(thread_id, job, footer, live)
                continue
            idle_since = idle_since or time.monotonic()
            if time.monotonic() - idle_since < SETTLE_SECONDS:
                await self._draw(thread_id, job, footer, live)
                continue
            done = self._line(thread_id, job, footer.trace, "done")
            footer.live, job.started = False, None
            await self._draw(thread_id, job, footer, done)
            await _save(thread_id, job)
            return

    async def _draw(self, thread_id: str, job: _Job, footer: _Footer, text: str) -> None:
        if text == footer.text or not footer.ts:
            return
        try:
            await job.client.call(
                "chat.update",
                {"channel": footer.channel, "ts": footer.ts, "text": text, "blocks": _blocks(text)},
            )
        except SlackError as error:
            _LOGGER.warning("[footer] not redrawn: %s", error.code)
            return
        footer.text = text
        await _save(thread_id, job)

    async def aclose(self) -> None:
        """Stop following every thread (tests, shutdown)."""
        for job in self._jobs.values():
            if job.loop is not None and not job.loop.done():
                job.loop.cancel()
        for task in list(self._pending):
            task.cancel()
        await asyncio.gather(
            *self._pending, *(j.loop for j in self._jobs.values() if j.loop), return_exceptions=True
        )
        self._jobs.clear()


async def _reply_landed(binding: SlackBinding, *, after: float) -> bool:
    """Whether the bot posted into the thread after the run ended (the reply the footer goes
    under), passing over the messages this client made itself."""
    client, target = binding.client, binding.target
    me = (await client.identity()).user_id
    fields = {
        "channel": target.channel,
        "ts": target.thread_ts,
        "oldest": f"{after - 1:.6f}",
        "limit": 20,
    }
    for wait in REPLY_CHECKS:
        await asyncio.sleep(wait)
        found = (await client.call("conversations.replies", fields)).get("messages")
        for message in found if isinstance(found, list) else []:
            if not isinstance(message, Mapping):
                continue
            ts = message.get("ts")
            if ts == target.thread_ts or client.posted(ts) or message.get("user") != me:
                continue
            if float(str(ts or 0)) > after - 1:
                return True
    return False


async def _save(thread_id: str, job: _Job) -> None:
    """Keep the thread's job and newest footer where the next process can read them."""
    if job.store is None:
        return
    footer = job.footer
    value = {
        "started": job.started,
        "usd": METER.summary(thread_id).usd - job.usd_base if job.started is not None else 0.0,
        "footer": {
            "channel": footer.channel,
            "ts": footer.ts,
            "trace": footer.trace,
            "text": footer.text,
            "live": footer.live,
        }
        if footer is not None
        else None,
        "at": time.time(),
    }
    try:
        await job.store.aput(FOOTER_NAMESPACE, thread_id, value)
    except Exception as error:  # noqa: BLE001 - a restart would lose the footer, not the run
        _LOGGER.warning("[footer] not saved: %s", type(error).__name__)


async def _adopt(store: Any, thread_id: str, client: SlackClient) -> _Job | None:
    """A thread's open job and footer as a process that is gone left them, if any."""
    if store is None:
        return None
    try:
        item = await store.aget(FOOTER_NAMESPACE, thread_id)
    except Exception as error:  # noqa: BLE001 - no footer to take over; the job starts afresh
        _LOGGER.warning("[footer] not read: %s", type(error).__name__)
        return None
    value = dict(getattr(item, "value", None) or {})
    started, at = value.get("started"), value.get("at")
    if (
        not isinstance(started, int | float)
        or not isinstance(at, int | float)
        or time.time() - at > ADOPT_SECONDS
    ):
        return None
    # This process met the thread after the one that saved it, so all it has metered for the
    # thread comes on top of what the job had cost when it was saved.
    job = _Job(client, store, started=float(started), usd_base=-float(value.get("usd") or 0.0))
    saved = value.get("footer")
    if isinstance(saved, Mapping) and saved.get("ts"):
        job.footer = _Footer(
            channel=str(saved.get("channel") or ""),
            ts=str(saved["ts"]),
            trace=str(saved.get("trace") or ""),
            text=str(saved.get("text") or ""),
            live=bool(saved.get("live")),
        )
    return job


class ReplyFooterMiddleware(AgentMiddleware[AgentState[Any], Any, Any]):
    """Puts the footer under each reply the lead writes in a Slack thread (module doc).

    Lead only. Place it after any middleware that ends a run in code from `before_agent`
    (`LeadSteeringMiddleware`), so a run ended there never registers here.
    """

    def __init__(self, surface: SlackSurface, *, footers: Footers | None = None) -> None:
        super().__init__()
        self._surface = surface
        self.footers = footers or Footers()
        #: Per thread: when the run began, and what the thread had cost by then.
        self._runs: dict[str, tuple[float, float]] = {}

    @property
    def name(self) -> str:
        return "DesignAgentReplyFooter"

    async def abefore_agent(self, state: AgentState[Any], runtime: Any) -> dict[str, Any] | None:  # noqa: ARG002 - hook signature
        thread_id = thread_of(runtime)
        if thread_id:
            self._runs[thread_id] = (time.time(), METER.summary(thread_id).usd)
        return None

    async def aafter_agent(self, state: AgentState[Any], runtime: Any) -> dict[str, Any] | None:
        thread_id = thread_of(runtime)
        began = self._runs.pop(thread_id, None)
        if began is None:
            return None
        reply = posted_reply(list(state.get("messages") or []))
        if not should_post(reply) or reply == QUIET:
            return None
        binding = await self._surface.bind(runtime)
        if binding is None:
            return None
        started, usd = began
        self.footers.after_run(
            thread_id,
            binding,
            root=current_root(),
            started=started,
            usd_at_start=usd,
            ended=time.time(),
            store=getattr(runtime, "store", None),
        )
        return None
