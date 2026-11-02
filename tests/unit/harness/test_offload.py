"""Outside jobs: the runner over a fake job, and a detached render in a local shell. No sandbox."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from design_agent.harness import events as ev
from design_agent.harness.offload import JobProgress, OffloadRunner, SandboxDetachedRender
from design_agent.harness.policy import Delivery, decide
from design_agent.harness.protocols import ExecResult
from design_agent.harness.watch import RegexParser, WatchRunner, parser_for


class LocalShell:
    """A fake `SandboxExec`: the command runs in a local shell, as it would in the sandbox."""

    async def execute(self, command: str, *, timeout: int | None = None) -> ExecResult:
        process = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await asyncio.wait_for(process.communicate(), timeout or 30)
        output = out.decode(errors="replace")
        if err:
            output += ("\n" if output else "") + err.decode(errors="replace")
        return ExecResult(output=output, exit_code=process.returncode)


class FakeJob:
    """An outside job that reports the given states, one per poll, then the last one again."""

    def __init__(self, *states: JobProgress) -> None:
        self.states = list(states)
        self.cancelled = False

    async def submit(self) -> str:
        return "job-1"

    async def poll(self) -> JobProgress:
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    async def cancel(self) -> None:
        self.cancelled = True


def _collect() -> tuple[ev.EventBus, list[ev.Event]]:
    bus, seen = ev.EventBus(), []
    bus.subscribe(seen.append)
    return bus, seen


def _kinds(events: list[ev.Event], kind: str) -> list[ev.Event]:
    return [e for e in events if e.kind == kind]


async def _until(check: Callable[[], bool], timeout: float = 5.0) -> None:
    async def wait() -> None:
        while not check():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(wait(), timeout)


@pytest.fixture
def offload():
    runner = OffloadRunner(WatchRunner())
    yield runner
    runner.watches.clear()


async def _ended(offload: OffloadRunner, watch_id: str) -> None:
    record = offload.watches.get(watch_id)
    assert record is not None and record.handle is not None
    await asyncio.wait_for(record.handle, 10)


# -- the runner ---------------------------------------------------------------------------------


async def test_an_outside_job_publishes_the_same_events_as_a_watch(offload) -> None:
    bus, events = _collect()
    job = FakeJob(
        JobProgress("queued", note="waiting for a render slot"),
        JobProgress("running", 0.5, cost_usd=0.02, note="600/1200 frames rendered, $0.02"),
        JobProgress("done", 1.0, output="s3://bucket/renders/abc/out.mp4", cost_usd=0.04),
    )
    watch_id = await offload.start("t-1", job, label="remote final", poll_seconds=0.01, bus=bus)
    await _ended(offload, watch_id)

    started, queued, running, done = events
    assert started.kind == ev.WATCH_STARTED and started.data["job_id"] == "job-1"
    assert queued.kind == ev.WATCH_PROGRESS and queued.data["phase"] == "queued"
    assert running.data["fraction"] == 0.5 and running.data["cost_usd"] == 0.02
    assert "600/1200 frames" in running.text
    assert done.kind == ev.WATCH_DONE and done.text == "Output: s3://bucket/renders/abc/out.mp4"
    assert done.data["cost_usd"] == 0.04 and decide(done).delivery is Delivery.NOW
    assert offload.list("t-1")[0].id == watch_id


async def test_a_failed_job_is_an_error_and_a_stuck_one_can_be_stopped(offload) -> None:
    bus, events = _collect()
    failed = FakeJob(JobProgress("failed", 0.3, error="The render failed: chunk 4 timed out"))
    watch_id = await offload.start("t-1", failed, label="x", poll_seconds=0.01, bus=bus)
    await _ended(offload, watch_id)
    assert events[-1].kind == ev.WATCH_ERROR and "chunk 4 timed out" in events[-1].text
    assert await offload.cancel(watch_id) and not failed.cancelled  # it had already ended

    stuck = FakeJob(JobProgress("running", 0.1))
    watch_id = await offload.start("t-1", stuck, label="y", poll_seconds=0.01, bus=bus)
    await _until(lambda: offload.watches.get(watch_id).polls > 1)
    assert await offload.cancel(watch_id) and stuck.cancelled
    await asyncio.sleep(0.02)
    assert events[-1].kind == ev.TASK_CANCELLED and events[-1].source == watch_id
    assert not await offload.cancel("r-nothing")


async def test_a_submit_that_fails_raises_and_starts_nothing(offload) -> None:
    class Refused(FakeJob):
        async def submit(self) -> str:
            raise RuntimeError("no credentials")

    with pytest.raises(RuntimeError, match="no credentials"):
        await offload.start("t-1", Refused(JobProgress("running")), label="x")
    assert offload.watches.list("t-1") == []


# -- a command detached in the sandbox (a local shell here) -------------------------------------


async def test_a_detached_render_that_exits_0_is_done(tmp_path, offload) -> None:
    bus, events = _collect()
    log = tmp_path / "renders" / "final.log"
    first = '@hf-progress {"code":"capture","done":1,"total":4,"pct":30}'
    last = '@hf-progress {"code":"encode","done":4,"total":4,"pct":90}'
    job = SandboxDetachedRender(
        LocalShell(),
        f"echo '{first}'; sleep 0.2; echo '{last}'; echo '  ██  100%  Render complete'; "
        "echo; echo '◇  /workspace/out/final.mp4'",
        log_path=str(log),
        workdir=str(tmp_path),
        parser=parser_for("hyperframes"),
    )
    watch_id = await offload.start("t-1", job, label="final", poll_seconds=0.02, bus=bus)
    assert job.pid is not None and events[0].data["job_id"] == str(job.pid)
    await _ended(offload, watch_id)

    progress = _kinds(events, ev.WATCH_PROGRESS)
    fractions = [e.data["fraction"] for e in progress if e.data["fraction"] is not None]
    assert fractions and fractions == sorted(fractions)
    assert events[-1].kind == ev.WATCH_DONE and "out/final.mp4" in events[-1].text
    assert (tmp_path / "renders" / "final.log.exit").read_text().strip() == "0"


async def test_a_detached_job_reads_its_log_as_a_heartbeat_by_default(tmp_path, offload) -> None:
    """Without a format the log only shows the job is alive; its exit code is the verdict."""
    bus, events = _collect()
    job = SandboxDetachedRender(
        LocalShell(),
        "echo 'bundling'; sleep 0.1; echo 'wrote out/cut.mp4'",
        log_path=str(tmp_path / "cut.log"),
        workdir=str(tmp_path),
    )
    watch_id = await offload.start("t-1", job, label="cut", poll_seconds=0.02, bus=bus)
    await _ended(offload, watch_id)

    assert all(e.data["fraction"] is None for e in _kinds(events, ev.WATCH_PROGRESS))
    assert events[-1].kind == ev.WATCH_DONE and events[-1].text == "wrote out/cut.mp4"


async def test_a_detached_render_that_exits_1_fails_with_the_end_of_its_log(
    tmp_path, offload
) -> None:
    bus, events = _collect()
    log = tmp_path / "act2.log"
    command = "echo 'render: 2/4 frames'; echo 'render: shot 3 is missing' >&2; exit 1"
    job = SandboxDetachedRender(
        LocalShell(), command, log_path=str(log), workdir=str(tmp_path), parser=RegexParser()
    )
    watch_id = await offload.start("t-1", job, label="act 2", poll_seconds=0.02, bus=bus)
    await _ended(offload, watch_id)

    failed = events[-1]
    assert failed.kind == ev.WATCH_ERROR and failed.terminal
    assert failed.text.startswith("It exited with code 1. Last lines of")
    assert "render: 2/4 frames" in failed.text and "render: shot 3 is missing" in failed.text
    assert decide(failed).delivery is Delivery.NOW


async def test_a_detached_render_that_is_stopped_ends_its_process(tmp_path, offload) -> None:
    shell = LocalShell()
    job = SandboxDetachedRender(
        shell, "sleep 5", log_path=str(tmp_path / "long.log"), workdir=str(tmp_path)
    )
    watch_id = await offload.start("t-1", job, label="long", poll_seconds=0.02)
    assert await offload.cancel(watch_id)

    async def alive() -> bool:
        return (await shell.execute(f"kill -0 {job.pid} 2>/dev/null")).exit_code == 0

    for _ in range(200):
        if not await alive():
            break
        await asyncio.sleep(0.01)
    assert not await alive()


def test_the_start_command_quotes_everything_and_keeps_the_exit_code() -> None:
    job = SandboxDetachedRender(
        LocalShell(),
        "hyperframes render . --output 'out/it'\"'\"'s.mp4' # final",
        log_path="/workspace/p/build/final render.log",
        workdir="/workspace/p",
    )
    command = job.start_command()
    assert "'/workspace/p/build/final render.log'" in command
    assert "setsid" in command and "nohup" in command and "< /dev/null &" in command
    # The command runs in a subshell, so its own `exit` or a trailing comment can't skip the
    # exit file.
    assert "( hyperframes render" in command and "# final\n); echo $? >" in command
