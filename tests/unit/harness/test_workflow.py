"""The workflow runner (`harness/workflow.py`) with a fake helper runner and an in-memory store."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from langgraph.store.memory import InMemoryStore

from design_agent.harness import events as ev
from design_agent.harness.policy import Delivery, decide
from design_agent.harness.protocols import HelperResult, HelperRunner
from design_agent.harness.workflow import (
    STALE_SECONDS,
    StepFailed,
    WorkflowError,
    WorkflowRunner,
    basic_schema_errors,
    last_json,
    schema_errors,
    step_key,
)

THREAD = "thread-1"


@dataclass
class Call:
    brief: str
    effort: str
    label: str
    wave: str | None


class FakeHelpers:
    """A `HelperRunner` whose helpers answer with `reply(brief, label)`: a report, a coroutine, or a
    whole `HelperResult`. It records every call and how many ran at once."""

    def __init__(self, reply: Callable[[str, str], Any] | None = None) -> None:
        self.calls: list[Call] = []
        self._reply = reply or (lambda _brief, label: f"{label} report")
        self._in_flight = 0
        self.peak = 0

    async def start(
        self, brief: str, *, effort: str, label: str = "", wave: str | None = None
    ) -> str:
        raise NotImplementedError

    async def run(
        self, brief: str, *, effort: str, label: str = "", wave: str | None = None
    ) -> HelperResult:
        self.calls.append(Call(brief, effort, label, wave))
        self._in_flight += 1
        self.peak = max(self.peak, self._in_flight)
        try:
            out = self._reply(brief, label)
            if inspect.isawaitable(out):
                out = await out
        finally:
            self._in_flight -= 1
        if isinstance(out, HelperResult):
            return out
        return HelperResult(f"t-{len(self.calls)}", "done", str(out))

    @property
    def labels(self) -> list[str]:
        return [call.label for call in self.calls]


@pytest.fixture
def bus() -> ev.EventBus:
    return ev.EventBus()


@pytest.fixture
def seen(bus: ev.EventBus) -> list[ev.Event]:
    events: list[ev.Event] = []
    bus.subscribe(events.append)
    return events


def make(
    pipeline: Any,
    helpers: FakeHelpers,
    *,
    store: InMemoryStore | None = None,
    bus: ev.EventBus | None = None,
    concurrency: int = 8,
) -> WorkflowRunner:
    runner = WorkflowRunner(
        store or InMemoryStore(), helpers, bus or ev.EventBus(), concurrency=concurrency
    )
    runner.register("demo", pipeline)
    return runner


async def finish(runner: WorkflowRunner, run_id: str):
    return await asyncio.wait_for(runner.wait(run_id), 5)


async def until(check: Callable[[], Any]) -> None:
    async with asyncio.timeout(5):
        while not check():
            await asyncio.sleep(0.005)


def test_the_fake_is_a_helper_runner() -> None:
    assert isinstance(FakeHelpers(), HelperRunner)


# -- memo and replay --------------------------------------------------------------------------------


async def test_a_run_a_restart_ended_is_reported_once_and_replays_its_finished_steps(
    bus: ev.EventBus, seen: list[ev.Event]
) -> None:
    store = InMemoryStore()
    never = asyncio.Event()

    async def slow(brief: str, label: str) -> str:
        if label == "third":
            await never.wait()
        return f"{label} report"

    async def demo(ctx):
        first = await ctx.agent("brief one", effort="max", label="first")
        second = await ctx.agent(f"brief two, after: {first.value}", effort="xhigh", label="second")
        third = await ctx.agent("brief three", effort="low", label="third")
        return [first.value, second.value, third.value]

    before = FakeHelpers(slow)
    runner = make(demo, before, store=store)
    run_id = await runner.start("demo", {}, THREAD)
    await until(lambda: before.labels == ["first", "second", "third"])
    # The process dies mid-step: its task ends, and nobody records the run as ended.
    task = runner._runs[run_id].task
    assert task is not None
    task.cancel()
    await asyncio.wait({task})

    after = FakeHelpers()
    restarted = make(demo, after, store=store, bus=bus)
    assert await restarted.sweep() == []  # its heartbeat is still fresh
    woken: list[str] = []

    async def wake_here(record) -> None:
        woken.append(record.thread_id)

    later = time.time() + STALE_SECONDS + 1
    stale = await restarted.sweep(on_found=wake_here, now=later)
    assert [(record.id, record.status) for record in stale] == [(run_id, "interrupted")]
    assert woken == [THREAD]
    [interrupted] = [e for e in seen if e.kind == ev.TASK_INTERRUPTED]
    assert interrupted.source == run_id and decide(interrupted).delivery is Delivery.NOW
    assert await restarted.sweep(now=later) == []  # reported once

    await restarted.resume(run_id, reason="after a restart")
    record = await finish(restarted, run_id)

    assert record.status == "done"
    assert record.result == ["first report", "second report", "third report"]
    assert after.labels == ["third"]  # the two finished steps replayed from the memo
    memo = await store.asearch(("harness", "workflows", run_id), limit=10)
    assert step_key("brief one", "max", None, "first") in {item.key for item in memo}


async def test_a_handled_failure_replays_and_the_answer_does_not_rerun_it() -> None:
    tries: list[str] = []

    def reply(brief: str, label: str) -> Any:
        tries.append(label)
        if label == "flaky":
            return HelperResult("t-1", "failed", error="the API was overloaded")
        return f"{label} ok"

    async def demo(ctx):
        try:
            value = (await ctx.agent("flaky brief", effort="max", label="flaky")).value
        except StepFailed as failure:
            value = (await ctx.agent(f"after {failure.reason}", effort="max", label="plan b")).value
        answer = await ctx.ask("Go?", ["approve"])
        return [value, answer]

    helpers = FakeHelpers(reply)
    runner = make(demo, helpers)
    run_id = await runner.start("demo", {}, THREAD)
    assert (await finish(runner, run_id)).status == "waiting"
    await runner.answer(run_id, "approve")
    record = await finish(runner, run_id)

    assert record.result == ["plan b ok", "approve"]
    assert tries == ["flaky", "plan b"]  # the replay took the same path without asking again


async def test_resuming_a_failed_run_runs_its_failed_steps_again(
    bus: ev.EventBus, seen: list[ev.Event]
) -> None:
    broken = {"render": True}

    def reply(brief: str, label: str) -> Any:
        if label == "render" and broken["render"]:
            return HelperResult("t-2", "failed", error="out of disk")
        return f"{label} ok"

    async def demo(ctx):
        plan = await ctx.agent("plan brief", effort="max", label="plan")
        render = await ctx.agent("render brief", effort="low", label="render")
        return [plan.value, render.value]

    helpers = FakeHelpers(reply)
    runner = make(demo, helpers, bus=bus)
    run_id = await runner.start("demo", {}, THREAD)
    record = await finish(runner, run_id)
    assert record.status == "failed"
    [failed] = [e for e in seen if e.kind == ev.TASK_FAILED]
    assert "out of disk" in failed.text and decide(failed).delivery is Delivery.NOW

    broken["render"] = False
    await runner.resume(run_id)
    record = await finish(runner, run_id)

    assert record.status == "done"
    assert helpers.labels == ["plan", "render", "render"]


# -- parallel and pipeline ------------------------------------------------------------------------


async def test_parallel_turns_failures_into_none_and_publishes_them(
    bus: ev.EventBus, seen: list[ev.Event]
) -> None:
    def reply(brief: str, label: str) -> Any:
        if label == "render":
            return HelperResult("t-9", "failed", error="the render crashed")
        return "fine"

    async def broken() -> None:
        raise ValueError("no such act")

    async def demo(ctx):
        return await ctx.parallel(
            [
                lambda: ctx.agent("good brief", effort="low", label="good"),
                lambda: ctx.agent("render brief", effort="low", label="render"),
                broken,
            ]
        )

    runner = make(demo, FakeHelpers(reply), bus=bus)
    record = await finish(runner, await runner.start("demo", {}, THREAD))

    assert record.status == "done"
    assert record.result[1:] == [None, None]
    failures = [e.text for e in seen if e.kind == ev.PIPELINE_STEP and e.data.get("failed")]
    assert any("the render crashed" in text for text in failures)
    assert any("ValueError: no such act" in text for text in failures)


async def test_pipeline_moves_each_item_on_without_waiting_for_the_others() -> None:
    order: list[str] = []
    fast_is_in_stage_two = asyncio.Event()

    async def reply(brief: str, label: str) -> str:
        order.append(f"start {label}")
        if label == "fast 2":
            fast_is_in_stage_two.set()
        if label == "slow 1":
            await fast_is_in_stage_two.wait()  # behind a barrier, this would never happen
        order.append(f"end {label}")
        return label

    async def demo(ctx):
        async def one(item: str) -> str:
            await ctx.agent(f"{item}, stage one", effort="low", label=f"{item} 1")
            return item

        async def two(item: str) -> str:
            return (await ctx.agent(f"{item}, stage two", effort="low", label=f"{item} 2")).value

        return await ctx.pipeline(["slow", "fast"], one, two)

    runner = make(demo, FakeHelpers(reply))
    record = await finish(runner, await runner.start("demo", {}, THREAD))

    assert record.result == ["slow 2", "fast 2"]  # in item order
    assert order.index("end fast 2") < order.index("end slow 1")


async def test_a_run_keeps_at_most_its_concurrency_in_flight() -> None:
    async def reply(brief: str, label: str) -> str:
        await asyncio.sleep(0.01)
        return label

    helpers = FakeHelpers(reply)

    async def demo(ctx):
        steps = await ctx.parallel(
            [
                (lambda i=i: ctx.agent(f"brief {i}", effort="low", label=f"step {i}"))
                for i in range(6)
            ]
        )
        return [step.value for step in steps]

    runner = make(demo, helpers, concurrency=2)
    record = await finish(runner, await runner.start("demo", {}, THREAD))

    assert record.result == [f"step {i}" for i in range(6)]
    assert helpers.peak == 2


# -- schemas --------------------------------------------------------------------------------------

SCORE = {
    "type": "object",
    "required": ["score", "pass"],
    "properties": {"score": {"type": "number"}, "pass": {"type": "boolean"}},
}


async def test_a_report_that_misses_the_schema_goes_back_with_the_problem() -> None:
    replies = iter(
        [
            "I looked at it; it's good.",
            'Verdict: {"score": 4}',
            'Done.\n```json\n{"score": 4.5, "pass": true}\n```',
        ]
    )
    helpers = FakeHelpers(lambda _brief, _label: next(replies))

    async def demo(ctx):
        step = await ctx.agent("review act 2", effort="xhigh", label="review", schema=SCORE)
        return step.value

    runner = make(demo, helpers)
    record = await finish(runner, await runner.start("demo", {}, THREAD))

    assert record.result == {"score": 4.5, "pass": True}
    assert len(helpers.calls) == 3
    assert all(call.brief.startswith("review act 2") for call in helpers.calls)
    assert "no JSON object" in helpers.calls[1].brief
    assert "'pass' is a required property" in helpers.calls[2].brief


async def test_a_step_whose_report_never_matches_fails_the_run(
    bus: ev.EventBus, seen: list[ev.Event]
) -> None:
    helpers = FakeHelpers(lambda _brief, _label: '{"score": "high"}')

    async def demo(ctx):
        return (await ctx.agent("review", effort="xhigh", schema=SCORE, attempts=2)).value

    runner = make(demo, helpers, bus=bus)
    record = await finish(runner, await runner.start("demo", {}, THREAD))

    assert record.status == "failed"
    assert "no valid JSON after 2 attempts" in record.error
    assert len(helpers.calls) == 2
    assert [e.kind for e in seen][-1] == ev.TASK_FAILED


def test_last_json_takes_what_the_report_ends_with() -> None:
    example_then_answer = 'Example:\n```json\n{"a": 1}\n```\nFinal: {"a": 2, "b": {"c": 3}} (done)'
    assert last_json(example_then_answer) == {"a": 2, "b": {"c": 3}}
    assert last_json('{"a": 1}\nThe list:\n```\n[1, 2]\n```') == [1, 2]
    assert last_json('I used {braces} in prose, then: {"ok": true}') == {"ok": True}
    with pytest.raises(ValueError):
        last_json("nothing to read here {oops")


def test_both_validators_find_the_same_problems() -> None:
    schema = {
        "type": "object",
        "required": ["acts", "rig"],
        "properties": {
            "acts": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "effort": {"enum": ["xhigh", "max"]},
                    },
                },
            },
            "rig": {"type": "string"},
        },
    }
    good = {"acts": [{"name": "Act 1", "effort": "max"}], "rig": "the ring"}
    bad = {"acts": [{"name": 3, "effort": "low"}, {}]}

    assert basic_schema_errors(good, schema) == []
    assert schema_errors(good, schema) == []
    expected = [
        "$: 'rig' is a required property",
        "$.acts[0].name: 3 is not of type 'string'",
        "$.acts[0].effort: 'low' is not one of ['xhigh', 'max']",
        "$.acts[1]: 'name' is a required property",
    ]
    assert basic_schema_errors(bad, schema) == expected
    assert sorted(schema_errors(bad, schema)) == sorted(expected)
    assert basic_schema_errors({"acts": [], "rig": ""}, schema) == [
        "$.acts: [] should have at least 1 item(s)"
    ]


# -- ask and answer -------------------------------------------------------------------------------


async def test_ask_parks_the_run_and_the_answer_continues_it_even_after_a_restart(
    bus: ev.EventBus, seen: list[ev.Event]
) -> None:
    store = InMemoryStore()

    async def demo(ctx):
        ctx.phase("draft")
        draft = await ctx.agent("draft brief", effort="max", label="draft")
        ctx.note("drafted")
        ctx.phase("approval")
        answer = await ctx.ask("Ship it?", ["approve", "changes"])
        ctx.phase("ship")
        shipped = await ctx.agent(f"ship, the operator said {answer}", effort="low", label="ship")
        return {"draft": draft.value, "answer": answer, "ship": shipped.value}

    helpers = FakeHelpers()
    runner = make(demo, helpers, store=store, bus=bus)
    run_id = await runner.start("demo", {}, THREAD)
    record = await finish(runner, run_id)

    assert record.status == "waiting"
    assert helpers.labels == ["draft"]
    [attention] = [e for e in seen if e.kind == ev.JOB_ATTENTION]
    assert attention.data["ping"] is True
    assert attention.data["run_id"] == run_id
    assert attention.data["options"] == ["approve", "changes"]
    assert run_id in attention.text  # the lead's notice shows the text, not the source
    assert decide(attention).delivery is Delivery.NOW and decide(attention).ping
    assert runner.running_lines(THREAD) == [
        f"{run_id} (pipeline demo, waiting for an answer: Ship it?)"
    ]

    # The answer reaches a process that never ran the pipeline.
    later = FakeHelpers()
    restarted = make(demo, later, store=store, bus=bus)
    await restarted.answer(run_id, "approve")
    record = await finish(restarted, run_id)

    assert record.status == "done"
    assert record.result == {"draft": "draft report", "answer": "approve", "ship": "ship report"}
    assert later.labels == ["ship"]  # the draft replayed
    assert [e.text for e in seen].count("drafted") == 1  # a replay says nothing twice
    with pytest.raises(WorkflowError, match="nothing is waiting"):
        await restarted.answer(run_id, "again")


async def test_an_answer_while_other_branches_still_run_continues_once_they_settle(
    bus: ev.EventBus, seen: list[ev.Event]
) -> None:
    slow_may_finish = asyncio.Event()

    async def reply(brief: str, label: str) -> str:
        if label == "slow":
            await slow_may_finish.wait()
        return f"{label} report"

    async def demo(ctx):
        async def question() -> str:
            return await ctx.ask("Which cut?", ["short", "long"])

        answer, slow = await ctx.parallel(
            [question, lambda: ctx.agent("slow brief", effort="max", label="slow")]
        )
        return [answer, slow.value]

    helpers = FakeHelpers(reply)
    runner = make(demo, helpers, bus=bus)
    run_id = await runner.start("demo", {}, THREAD)
    await until(lambda: any(e.kind == ev.JOB_ATTENTION for e in seen))
    await runner.answer(run_id, "short")  # the slow branch is still working
    slow_may_finish.set()
    record = await finish(runner, run_id)

    assert record.status == "done"
    assert record.result == ["short", "slow report"]
    assert helpers.labels == ["slow"]  # saved while the question waited, then replayed


async def test_cancelling_a_run_that_waits_for_an_answer(
    bus: ev.EventBus, seen: list[ev.Event]
) -> None:
    async def demo(ctx):
        return await ctx.ask("Go?", ["approve", "changes"])

    runner = make(demo, FakeHelpers(), bus=bus)
    run_id = await runner.start("demo", {}, THREAD)
    assert (await finish(runner, run_id)).status == "waiting"

    record = await runner.cancel(run_id)

    assert record.status == "cancelled"
    assert seen[-1].kind == ev.TASK_CANCELLED
    assert runner.running_lines(THREAD) == []
    with pytest.raises(WorkflowError, match="cancelled"):
        await runner.answer(run_id, "approve")


# -- events, status and cancel ----------------------------------------------------------------------


async def test_a_run_publishes_its_start_phases_steps_notes_and_result(
    bus: ev.EventBus, seen: list[ev.Event]
) -> None:
    async def demo(ctx, topic: str):
        ctx.phase("draft")
        step = await ctx.agent(f"draft {topic}", effort="xhigh", label="draft")
        ctx.note("drafted")
        ctx.phase("polish")
        polished = await ctx.agent(f"polish {step.value}", effort="low", label="polish")
        return {"final": polished.value}

    runner = make(demo, FakeHelpers(), bus=bus)
    run_id = await runner.start("demo", {"topic": "the launch"}, THREAD)
    await finish(runner, run_id)

    assert [(e.kind, e.data.get("state") or e.text) for e in seen] == [
        (ev.TASK_STARTED, "Started pipeline demo."),
        (ev.JOB_PHASE, "draft"),
        (ev.PIPELINE_STEP, "started"),
        (ev.PIPELINE_STEP, "done"),
        (ev.PIPELINE_STEP, "drafted"),
        (ev.JOB_PHASE, "polish"),
        (ev.PIPELINE_STEP, "started"),
        (ev.PIPELINE_STEP, "done"),
        (ev.TASK_DONE, '{\n "final": "polish report"\n}'),
    ]
    assert {(e.source, e.label, e.thread_id) for e in seen} == {(run_id, "demo", THREAD)}
    done = seen[-1]
    assert done.data["report"] == {"final": "polish report"}
    assert "draft: done" in seen[3].text and "draft report" in seen[3].text
    # The lead is woken once, by the result; steps wait for its next wake-up; phases are only recorded.
    assert [decide(e).delivery for e in seen if e.kind == ev.TASK_DONE] == [Delivery.NOW]
    assert {decide(e).delivery for e in seen if e.kind == ev.PIPELINE_STEP} == {Delivery.NEXT}
    assert {decide(e).delivery for e in seen if e.kind == ev.JOB_PHASE} == {Delivery.LOG}


async def test_cancel_stops_the_run_and_the_helpers_it_has_in_flight(
    bus: ev.EventBus, seen: list[ev.Event]
) -> None:
    stopped = asyncio.Event()

    async def forever(brief: str, label: str) -> str:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopped.set()
            raise
        return ""

    async def demo(ctx):
        ctx.phase("build")
        await ctx.agent("build it", effort="max", label="act 1")

    runner = make(demo, FakeHelpers(forever), bus=bus)
    run_id = await runner.start("demo", {}, THREAD)
    await until(lambda: "act 1" in "".join(runner.running_lines(THREAD)))
    assert runner.running_lines(THREAD)[0].startswith(f"{run_id} (pipeline demo, build: act 1, ")

    assert runner.canceller(run_id, "another-thread") is None
    assert runner.canceller("t-123456", THREAD) is None
    assert "Cancelled pipeline" in (runner.canceller(run_id, THREAD) or "")
    await asyncio.wait_for(stopped.wait(), 5)
    record = await finish(runner, run_id)

    assert record.status == "cancelled"
    assert seen[-1].kind == ev.TASK_CANCELLED
    assert runner.running_lines(THREAD) == []


async def test_start_refuses_unknown_pipelines_and_arguments() -> None:
    async def demo(ctx, *, project: str) -> str:
        return project

    runner = make(demo, FakeHelpers())
    with pytest.raises(WorkflowError, match="No pipeline named 'nope'"):
        await runner.start("nope", {}, THREAD)
    with pytest.raises(WorkflowError, match="missing a required .*'project'"):
        await runner.start("demo", {}, THREAD)
    with pytest.raises(WorkflowError, match="unexpected keyword"):
        await runner.start("demo", {"project": "x", "slug": "y"}, THREAD)
