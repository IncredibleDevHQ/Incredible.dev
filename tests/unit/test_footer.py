"""The footer under the lead's replies while it has work in the background (middleware/footer.py)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.store.memory import InMemoryStore

from design_agent.harness import events as ev
from design_agent.harness import tasks
from design_agent.middleware import footer
from design_agent.middleware.footer import Footers, ReplyFooterMiddleware, footer_line
from design_agent.middleware.meter import METER
from design_agent.middleware.tracing import TraceLinks, TraceRoot
from design_agent.surfaces.slack.target import SlackSurface
from design_agent.testing.fake_slack import BOT, THREAD_TS, FakeResolver, FakeSlack, binding

THREAD = "thread-footer"
TRACE = "https://smith.example.com/r/1"


def test_the_line_reads_as_the_mock() -> None:
    live = footer_line(
        TRACE, "live", usd=12.4, running=2, progress="render 45%, ~6 min left", minutes=12
    )
    assert (
        live
        == f"<{TRACE}|Trace> • 2 agents running • render 45%, ~6 min left • 12 min • ~$12.40 so far"
    )
    assert (
        footer_line(TRACE, "done", usd=18.2, agents=3, minutes=14)
        == f"<{TRACE}|Trace> • 3 agents • 14 min • ~$18.20 total"
    )
    assert footer_line("", "snapshot", usd=3.1) == "~$3.10 so far"
    assert "1 agent running" in footer_line("", "live", usd=0, running=1)
    # A job watched in the sandbox, with no agent of its own, says nothing about agents.
    assert footer_line("", "live", usd=0.06, progress="teaser 44%") == "teaser 44% • ~$0.06 so far"
    assert footer_line("", "done", usd=0, agents=1, minutes=0) == "1 agent • 1 min • ~$0.00 total"


@pytest.fixture
def fast(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(footer, "REPLY_CHECKS", (0.0,))
    monkeypatch.setattr(footer, "REFRESH_SECONDS", 0.01)
    monkeypatch.setattr(footer, "SETTLE_SECONDS", 0.05)
    yield
    tasks.REGISTRY.pop("t-f00001", None)
    METER.forget(THREAD)


class _Links(TraceLinks):
    def __init__(self) -> None:
        super().__init__("https://smith.example.com")

    async def url(self, root: TraceRoot | None) -> str:
        return TRACE


def _helper(started: float) -> tasks.TaskRecord:
    record = tasks.TaskRecord(
        id="t-f00001", thread_id=THREAD, effort="low", label="render", wave=None, started_at=started
    )
    tasks.REGISTRY[record.id] = record
    return record


def _spend(usd: float) -> None:
    METER.record(ev.Event(ev.USAGE, THREAD, "lead", data={"usd": usd}))


async def _run_ends(
    fake: FakeSlack, footers: Footers, started: float, *, store: Any = None, replied: bool = True
) -> None:
    ended = time.time()
    if replied:  # the platform posts the run's reply into the thread
        fake.thread.append({"ts": f"{ended + 0.5:.6f}", "user": BOT, "text": "the reply"})
    footers.after_run(
        THREAD,
        binding(fake),
        root=None,
        started=started,
        usd_at_start=0.0,
        ended=ended,
        store=store,
    )
    await asyncio.gather(*list(footers._pending))


def _posts(fake: FakeSlack) -> list[str]:
    return [fields["text"] for method, fields in fake.calls if method == "chat.postMessage"]


def _draws(fake: FakeSlack) -> list[tuple[str, str]]:
    return [
        (fields["ts"], fields["text"]) for method, fields in fake.calls if method == "chat.update"
    ]


async def _until(check: Callable[[], bool], seconds: float = 2.0) -> None:
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline, "timed out"
        await asyncio.sleep(0.01)


async def test_a_reply_with_agents_running_gets_a_live_footer_that_settles_to_totals(
    fast: None,
) -> None:
    fake, footers = FakeSlack(), Footers(traces=_Links())
    started = time.time()
    helper = _helper(started)
    _spend(2.0)

    await _run_ends(fake, footers, started)

    assert _posts(fake) == [f"<{TRACE}|Trace> • 1 agent running • ~$2.00 so far"]
    (posted,) = fake.posted.values()
    assert posted.thread_ts == THREAD_TS and posted.blocks[0]["type"] == "context"
    _spend(1.5)
    await _until(lambda: any("$3.50 so far" in text for _, text in _draws(fake)))
    helper.status, helper.delivered = "done", True
    await _until(lambda: bool(_draws(fake)) and "total" in _draws(fake)[-1][1])
    assert _draws(fake)[-1] == (posted.ts, f"<{TRACE}|Trace> • 1 agent • 1 min • ~$3.50 total")
    await footers.aclose()


async def test_a_newer_reply_takes_the_footer_over_and_the_last_one_closes_the_job(
    fast: None,
) -> None:
    fake, footers = FakeSlack(), Footers(traces=_Links())
    started = time.time()
    helper = _helper(started)
    _spend(1.0)
    await _run_ends(fake, footers, started)
    first = list(fake.posted)[0]

    # The person asks something while the agent works: the new reply gets the live footer, and
    # the older one keeps what the job had cost by then.
    await _run_ends(fake, footers, time.time())
    assert len(_posts(fake)) == 2 and "running" in _posts(fake)[1]
    assert (first, f"<{TRACE}|Trace> • ~$1.00 so far") in _draws(fake)

    # The wake-up that reports the finish is the job's last reply: its footer settles under it.
    helper.status, helper.delivered = "done", True
    await _run_ends(fake, footers, time.time())
    assert _posts(fake)[2] == f"<{TRACE}|Trace> • ~$1.00 so far"
    await _until(lambda: bool(_draws(fake)) and "total" in _draws(fake)[-1][1])
    assert _draws(fake)[-1] == (
        list(fake.posted)[-1],
        f"<{TRACE}|Trace> • 1 agent • 1 min • ~$1.00 total",
    )
    await footers.aclose()


async def test_the_job_stays_open_while_a_helpers_news_is_on_its_way(fast: None) -> None:
    """A helper the lead has not heard about yet keeps the job open: the totals go under the
    reply that delivers its work, not the one before."""
    fake, footers = FakeSlack(), Footers()
    started = time.time()
    helper = _helper(started)
    await _run_ends(fake, footers, started)
    helper.status = "done"  # ended, and the wake-up that tells the lead is on its way

    await asyncio.sleep(footer.SETTLE_SECONDS * 4)
    assert not any("total" in text for _, text in _draws(fake))

    helper.delivered = True
    await _until(lambda: bool(_draws(fake)) and "total" in _draws(fake)[-1][1])
    await footers.aclose()


async def test_after_a_restart_the_job_keeps_its_cost_and_the_dead_footer_is_retired(
    fast: None,
) -> None:
    """A restart kills the process holding the footer: the next one counts on from what the job
    had cost, and the dead footer stops saying an agent is running."""
    store, fake = InMemoryStore(), FakeSlack()
    started = time.time()
    _helper(started)
    _spend(2.0)
    before = Footers()
    await _run_ends(fake, before, started, store=store)
    dead = list(fake.posted)[0]
    assert _posts(fake) == ["1 agent running • ~$2.00 so far"]

    # The process dies with its footers and its meter; a new one takes over the thread.
    await before.aclose()
    METER.forget(THREAD)
    _spend(0.5)
    after = Footers()
    await _run_ends(fake, after, time.time(), store=store)

    assert _draws(fake)[0] == (dead, "~$2.50 so far")
    assert _posts(fake)[1] == "1 agent running • ~$2.50 so far"
    await after.aclose()


async def test_a_turn_with_nothing_in_the_background_gets_no_footer_and_reads_nothing(
    fast: None,
) -> None:
    fake = FakeSlack()
    _spend(0.84)
    await _run_ends(fake, Footers(), time.time())
    assert fake.calls == []


async def test_a_run_that_posted_no_reply_gets_no_footer(fast: None) -> None:
    fake = FakeSlack()
    started = time.time()
    _helper(started)
    await _run_ends(fake, Footers(), started, replied=False)
    assert "chat.postMessage" not in fake.methods() and "conversations.replies" in fake.methods()


async def test_the_trace_link_names_the_root_run_on_the_configured_host() -> None:
    looked_up: list[str] = []

    def project_ids(name: str) -> tuple[str, str]:
        looked_up.append(name)
        return "0000aaaa", "1111bbbb"

    links = TraceLinks("https://smith.example.com/", project_ids=project_ids)
    root = TraceRoot(run_id="r-1", trace_id="r-1", project="design-agent")

    url = await links.url(root)

    assert (
        url
        == "https://smith.example.com/o/0000aaaa/projects/p/1111bbbb/r/r-1?trace_id=r-1&poll=true"
    )
    assert await links.url(root) == url and looked_up == ["design-agent"]
    assert await links.url(None) == ""
    assert await TraceLinks("").url(root) == ""


class _Noted(Footers):
    def __init__(self) -> None:
        super().__init__()
        self.after: list[str] = []

    def after_run(self, thread_id: str, *_args: Any, **_kwargs: Any) -> None:
        self.after.append(thread_id)


async def test_only_a_reply_of_the_jobs_own_gets_a_footer() -> None:
    """A run that ended in code before this saw it start (a follow-up already worked in) and a
    `[quiet]` turn wrote no reply of the job's: the live footer stays where it is."""
    noted = _Noted()
    middleware = ReplyFooterMiddleware(SlackSurface(FakeResolver(FakeSlack())), footers=noted)
    runtime = SimpleNamespace(config={"configurable": {"thread_id": THREAD}})
    answered = {"messages": [AIMessage(content="Here it is.")]}

    await middleware.aafter_agent(answered, runtime)
    assert noted.after == []
    await middleware.abefore_agent({"messages": []}, runtime)
    await middleware.aafter_agent({"messages": [AIMessage(content="[quiet]")]}, runtime)
    assert noted.after == []
    await middleware.abefore_agent({"messages": []}, runtime)
    await middleware.aafter_agent(answered, runtime)
    assert noted.after == [THREAD]
