"""The render watcher: sources, parsers and the runner's events, with fake sandboxes only.

Two fakes stand in for the sandbox. `Scripted` is a `WatchSource` that returns what a test feeds it,
one chunk per poll. `LocalShell` is a `SandboxExec` that runs the command in a local shell over a
temporary directory, with stderr after stdout as some sandbox backends return it, so the `wc -c` /
`tail -c +N` commands the sources send are exercised for real. The HyperFrames tests read real
`hyperframes render` output captured from the sandbox image (fixtures/hyperframes-*.log).
"""

from __future__ import annotations

import asyncio
import json
import re
import shlex
from collections.abc import Callable
from pathlib import Path

import pytest

from design_agent.harness import events as ev
from design_agent.harness.policy import Delivery, decide
from design_agent.harness.protocols import ExecResult
from design_agent.harness.watch import (
    DEFAULT_PARSER,
    PARSER_KINDS,
    CommandSource,
    FfmpegProgressParser,
    HeartbeatParser,
    HyperFramesParser,
    JsonStatusParser,
    RegexParser,
    SandboxFileSource,
    SandboxJsonSource,
    Update,
    WatchRecord,
    WatchRunner,
    parser_for,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_bytes().decode("utf-8")


def _hf(code: str, pct: int, done: int | None = None, total: int | None = None) -> str:
    """One `@hf-progress` line as `hyperframes render` writes it without a TTY."""
    counts = {} if done is None else {"done": done, "total": total}
    return "@hf-progress " + json.dumps({"code": code, **counts, "pct": pct}) + "\n"


class LocalShell:
    """A fake `SandboxExec`: the command runs in a local shell, as it would in the sandbox."""

    def __init__(self) -> None:
        self.commands: list[str] = []

    async def execute(self, command: str, *, timeout: int | None = None) -> ExecResult:
        self.commands.append(command)
        process = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await asyncio.wait_for(process.communicate(), timeout or 30)
        output = out.decode(errors="replace")
        if err:
            output += ("\n" if output else "") + err.decode(errors="replace")
        return ExecResult(output=output, exit_code=process.returncode)


class Scripted:
    """A `WatchSource` fed by the test: each read returns the next chunk, or "" when none waits."""

    def __init__(self, *chunks: str) -> None:
        self.chunks = list(chunks)
        self.closed = False
        self.note = ""
        self.close_when_empty = False
        self.fail_with: Exception | None = None

    def feed(self, *chunks: str) -> None:
        self.chunks.extend(chunks)

    async def read(self) -> str:
        if self.fail_with is not None:
            raise self.fail_with
        chunk = self.chunks.pop(0) if self.chunks else ""
        if self.close_when_empty and not self.chunks:
            self.closed = True
        return chunk


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


async def _ended(runner: WatchRunner, watch_id: str) -> WatchRecord:
    record = runner.get(watch_id)
    assert record is not None and record.handle is not None
    await asyncio.wait_for(record.handle, 5)
    return record


@pytest.fixture
def runner():
    watches = WatchRunner()
    yield watches
    watches.clear()


# -- the runner, over a real growing file ---------------------------------------------------------


async def test_a_growing_hyperframes_log_gives_rising_progress_with_an_eta(
    tmp_path, runner
) -> None:
    log = tmp_path / "render.log"
    bus, events = _collect()
    watch_id = runner.start(
        "t-1",
        label="final render",
        source=SandboxFileSource(LocalShell(), str(log)),
        parser=parser_for("hyperframes"),
        poll_seconds=0.01,
        stall_seconds=30,
        bus=bus,
    )
    assert watch_id.startswith("r-") and events[0].kind == ev.WATCH_STARTED

    for frames, pct in ((30, 30), (90, 40), (150, 50), (210, 60), (300, 75)):
        with log.open("a") as out:
            out.write(_hf("capture", pct, frames, 300))
        await _until(
            lambda want=pct / 100: any(
                round(e.data["fraction"], 6) == want for e in _kinds(events, ev.WATCH_PROGRESS)
            )
        )
    with log.open("a") as out:
        out.write(
            "  █████████████████████████  100%  Render complete\n\n◇  /workspace/out/film.mp4\n"
        )
    record = await _ended(runner, watch_id)

    progress = _kinds(events, ev.WATCH_PROGRESS)
    fractions = [e.data["fraction"] for e in progress]
    assert fractions == sorted(fractions) and len(fractions) == 5
    assert fractions[-1] == pytest.approx(0.75)
    assert progress[0].data["eta_seconds"] is None  # one point is no line yet
    assert all(e.data["eta_seconds"] is not None for e in progress[1:])
    assert progress[-1].data["phase"] == "capturing frames"
    assert progress[-1].data["frames"] == 300 and "capturing frames 300/300" in progress[-1].text
    assert all(decide(e).delivery is Delivery.LOG for e in progress)  # recorded, not the lead

    done = events[-1]
    assert done.kind == ev.WATCH_DONE and done.terminal
    assert done.text == "Render complete: /workspace/out/film.mp4"
    assert done.data["output"] == "/workspace/out/film.mp4"
    assert decide(done).delivery is Delivery.NOW
    assert record.status == "done" and record.fraction == 1.0 and record.final is done


async def test_an_error_line_ends_the_watch_with_the_error_lines(runner) -> None:
    bus, events = _collect()
    source = Scripted(
        "render: 10/100\n",
        "Error: ENOENT: no such file or directory, open 'shot-4.png'\n"
        "    at Scene (scene.mjs:12:7)\n",
        "render: 11/100\n",
    )
    watch_id = runner.start(
        "t-1", label="act 2", source=source, parser=HeartbeatParser(), poll_seconds=0.01, bus=bus
    )
    record = await _ended(runner, watch_id)

    error = events[-1]
    assert error.kind == ev.WATCH_ERROR and error.terminal
    assert error.text.splitlines() == [
        "Error: ENOENT: no such file or directory, open 'shot-4.png'",
        "at Scene (scene.mjs:12:7)",
    ]
    assert decide(error).delivery is Delivery.NOW
    assert record.status == "error" and source.chunks == ["render: 11/100\n"]  # never read again


async def test_a_stall_is_reported_once_and_re_arms_when_output_resumes(runner) -> None:
    bus, events = _collect()
    source = Scripted("render: 7/100\n")
    watch_id = runner.start(
        "t-1",
        label="final render",
        source=source,
        parser=RegexParser(done=r"^\+ out/"),
        poll_seconds=0.01,
        stall_seconds=0.05,
        bus=bus,
    )
    await _until(lambda: bool(_kinds(events, ev.WATCH_STALLED)))
    await asyncio.sleep(0.2)  # four stall periods of silence: still one report
    (stalled,) = _kinds(events, ev.WATCH_STALLED)
    assert decide(stalled).delivery is Delivery.NOW and not stalled.terminal
    assert "No new output" in stalled.text and "render: 7/100" in stalled.text
    assert stalled.data["fraction"] == pytest.approx(0.07)
    assert runner.get(watch_id).stalled

    source.feed("render: 28/100\n")
    await _until(lambda: any(e.data.get("resumed") for e in _kinds(events, ev.WATCH_PROGRESS)))
    resumed = next(e for e in _kinds(events, ev.WATCH_PROGRESS) if e.data.get("resumed"))
    # The lead heard it stalled, so it hears it moving again.
    assert decide(resumed).delivery is Delivery.NOW and "resumed" in resumed.text
    assert resumed.data["fraction"] == pytest.approx(0.28) and not runner.get(watch_id).stalled

    await _until(lambda: len(_kinds(events, ev.WATCH_STALLED)) == 2)  # quiet again: re-armed
    source.feed("+ out/final.mp4 12 MB\n")
    record = await _ended(runner, watch_id)
    assert record.status == "done" and len(_kinds(events, ev.WATCH_STALLED)) == 2


async def test_a_timeout_ends_the_watch_as_a_stall(runner) -> None:
    bus, events = _collect()
    watch_id = runner.start(
        "t-1",
        label="deploy",
        source=Scripted("render: 1/10\n"),
        parser=RegexParser(),
        poll_seconds=0.01,
        stall_seconds=60,
        timeout_seconds=0.05,
        bus=bus,
    )
    record = await _ended(runner, watch_id)
    timed_out = events[-1]
    assert timed_out.kind == ev.WATCH_STALLED and timed_out.data["timeout"] is True
    assert timed_out.data["ended"] is True and record.status == "timed_out"
    assert decide(timed_out).delivery is Delivery.NOW


async def test_a_source_that_closes_without_a_verdict_is_an_error(runner) -> None:
    bus, events = _collect()
    source = Scripted("render: 5/10\n", "cleaning up")
    source.close_when_empty = True
    watch_id = runner.start(
        "t-1", label="x", source=source, parser=HeartbeatParser(), poll_seconds=0.01, bus=bus
    )
    record = await _ended(runner, watch_id)
    assert events[-1].kind == ev.WATCH_ERROR and "without a done or error line" in events[-1].text
    assert "cleaning up" in events[-1].text and record.status == "error"


async def test_failing_reads_are_named_in_the_stall(runner) -> None:
    bus, events = _collect()
    source = Scripted()
    source.fail_with = RuntimeError("sandbox unreachable")
    runner.start(
        "t-1",
        label="x",
        source=source,
        parser=HeartbeatParser(),
        poll_seconds=0.01,
        stall_seconds=0.03,
        bus=bus,
    )
    await _until(lambda: bool(_kinds(events, ev.WATCH_STALLED)))
    stalled = _kinds(events, ev.WATCH_STALLED)[0]
    assert "sandbox unreachable" in stalled.text
    assert stalled.data["read_error"] == "RuntimeError: sandbox unreachable"


async def test_cancel_is_only_recorded_and_a_shutdown_leaves_the_record(runner) -> None:
    bus, events = _collect()
    beats: list[str] = []
    watch_id = runner.start(
        "t-1",
        label="x",
        source=Scripted(),
        parser=HeartbeatParser(),
        poll_seconds=0.01,
        bus=bus,
        on_beat=lambda record: beats.append(record.status),
    )
    await _until(lambda: bool(beats))
    assert runner.cancel(watch_id) and not runner.cancel(watch_id)
    with pytest.raises(asyncio.CancelledError):
        await runner.get(watch_id).handle
    cancelled = events[-1]
    assert cancelled.kind == ev.TASK_CANCELLED and cancelled.data["watch"] is True
    assert cancelled.terminal and decide(cancelled).delivery is Delivery.LOG
    assert beats[-1] == "cancelled"

    # A shutdown cancels the task without a request: no event and no final beat, so the
    # heartbeat record is left for the sweep to report.
    beats.clear()
    other = runner.start(
        "t-1",
        label="y",
        source=Scripted(),
        parser=HeartbeatParser(),
        poll_seconds=0.01,
        bus=bus,
        on_beat=lambda record: beats.append(record.status),
    )
    await _until(lambda: bool(beats))
    count = len(events)
    runner.get(other).handle.cancel()
    with pytest.raises(asyncio.CancelledError):
        await runner.get(other).handle
    assert len(events) == count and set(beats) == {"watching"}
    assert runner.get(other).status == "interrupted"


async def test_progress_is_throttled_to_a_point_or_a_minute(runner) -> None:
    bus, events = _collect()
    source = Scripted(*(f"frame {n}/1000\n" for n in range(1, 40)))
    source.feed("done!\n")
    watch_id = runner.start(
        "t-1",
        label="x",
        source=source,
        parser=RegexParser(done="done!"),
        poll_seconds=0.001,
        bus=bus,
    )
    await _ended(runner, watch_id)
    fractions = [e.data["fraction"] for e in _kinds(events, ev.WATCH_PROGRESS)]
    # 39 lines a thousandth apart: one event per point moved, not one per line.
    assert fractions == [0.001, 0.011, 0.021, 0.031]


async def test_running_lines_list_what_is_being_watched(runner) -> None:
    source = Scripted(_hf("capture", 35, 105, 300))
    watch_id = runner.start(
        "t-9", label="final render", source=source, parser=HyperFramesParser(), poll_seconds=0.01
    )
    await _until(lambda: runner.get(watch_id).fraction is not None)
    (line,) = runner.running_lines("t-9")
    assert line.startswith(f"{watch_id} (watch, final render, 35%") and line.endswith("min)")
    assert runner.running_lines("other-thread") == []
    assert "35%" in runner.get(watch_id).describe()


# -- sources over a local shell ------------------------------------------------------------------


async def test_the_file_source_reads_new_bytes_and_survives_truncation(tmp_path) -> None:
    log = tmp_path / "job.log"
    source = SandboxFileSource(LocalShell(), str(log))
    assert await source.read() == "" and "does not exist yet" in source.note

    log.write_text("one\ntwo\n")
    assert await source.read() == "one\ntwo\n"
    assert await source.read() == ""
    with log.open("a") as out:
        out.write("three")  # no newline yet: the bytes arrive as they are
    assert await source.read() == "three"

    log.write_text("fresh\n")  # rewritten shorter than what was read: from the top
    assert await source.read() == "fresh\n" and "truncated" in source.note
    assert source.offset == len("fresh\n")


async def test_the_file_source_skips_to_the_newest_output_when_far_behind(tmp_path) -> None:
    log = tmp_path / "noisy.log"
    log.write_text("".join(f"line {n}\n" for n in range(1000)))
    source = SandboxFileSource(LocalShell(), str(log), max_bytes=40)
    text = await source.read()
    # The last 40 bytes, from the first whole line.
    assert text.splitlines()[-1] == "line 999" and text.startswith("line 99")
    assert source.offset == log.stat().st_size


async def test_the_file_source_quotes_odd_paths(tmp_path) -> None:
    folder = tmp_path / "it's here; rm -rf x"
    folder.mkdir()
    log = folder / "render $(date).log"
    log.write_text("render: 1/2\n")
    assert await SandboxFileSource(LocalShell(), str(log)).read() == "render: 1/2\n"


async def test_a_command_source_reports_when_its_output_changes(tmp_path, runner) -> None:
    frames = tmp_path / "frames"
    frames.mkdir()
    shell = LocalShell()
    count = f'echo "$(ls {shlex.quote(str(frames))} | wc -l | tr -d " ")/3"'
    bus, events = _collect()
    watch_id = runner.start(
        "t-1",
        label="frames",
        source=CommandSource(shell, count),
        parser=RegexParser(done=r"^3/3$"),
        poll_seconds=0.01,
        bus=bus,
    )
    await _until(lambda: bool(_kinds(events, ev.WATCH_PROGRESS)))
    await _until(lambda: len(shell.commands) >= 4)  # the same "0/3" read again: nothing new
    assert len(_kinds(events, ev.WATCH_PROGRESS)) == 1
    (frames / "0.png").write_bytes(b"x")
    await _until(lambda: len(_kinds(events, ev.WATCH_PROGRESS)) == 2)
    (frames / "1.png").write_bytes(b"x")
    (frames / "2.png").write_bytes(b"x")
    await _ended(runner, watch_id)

    assert [e.data["fraction"] for e in _kinds(events, ev.WATCH_PROGRESS)] == pytest.approx(
        [0, 1 / 3]
    )
    assert events[-1].kind == ev.WATCH_DONE and events[-1].text == "3/3"


async def test_a_json_status_file_reports_its_changes(tmp_path, runner) -> None:
    status = tmp_path / "run.json"
    status.write_text(json.dumps({"status": "running", "step": "render", "progress": 0.25}))
    bus, events = _collect()
    watch_id = runner.start(
        "t-1",
        label="launch film",
        source=SandboxJsonSource(LocalShell(), str(status)),
        parser=JsonStatusParser(),
        poll_seconds=0.01,
        bus=bus,
    )
    await _until(lambda: bool(_kinds(events, ev.WATCH_PROGRESS)))
    first = _kinds(events, ev.WATCH_PROGRESS)[0]
    assert first.data["fraction"] == 0.25 and first.data["phase"] == "render"

    status.write_text('{"status": "running", "step": "enc')  # torn mid-write: skipped
    await asyncio.sleep(0.05)
    assert len(_kinds(events, ev.WATCH_PROGRESS)) == 1

    status.write_text(
        json.dumps({"status": "running", "step": "encode", "progress": 80, "eta": 30})
    )
    await _until(lambda: len(_kinds(events, ev.WATCH_PROGRESS)) == 2)
    second = _kinds(events, ev.WATCH_PROGRESS)[1]
    assert second.data["fraction"] == 0.8 and second.data["phase"] == "encode"
    assert second.data["eta_seconds"] == 30

    status.write_text(json.dumps({"status": "success", "step": "deliver", "cost": 1.25}))
    record = await _ended(runner, watch_id)
    assert events[-1].kind == ev.WATCH_DONE and events[-1].data["cost"] == 1.25
    assert record.status == "done"


# -- parsers ------------------------------------------------------------------------------------


def test_ffmpeg_progress_blocks_give_a_fraction_and_an_eta() -> None:
    by_frames = FfmpegProgressParser(total_frames=300)
    block = "frame=150\nfps=30.0\nout_time_us=5000000\nspeed=1.5x\nprogress=continue\n"
    (update,) = by_frames.parse(block)
    assert update.kind == "progress" and update.fraction == 0.5
    assert update.eta_seconds == pytest.approx(5.0)  # 150 frames left at 30 fps
    assert update.text == "frame 150/300, 5.0s, 1.5x"

    by_time = FfmpegProgressParser(duration_seconds=10)
    (update,) = by_time.parse(
        "frame=100\nout_time_us=N/A\nout_time=00:00:04.000000\nspeed=2x\nprogress=continue\n"
    )
    assert update.fraction == pytest.approx(0.4) and update.eta_seconds == pytest.approx(3.0)

    # Without a total there is no fraction, only what ffmpeg says.
    (update,) = FfmpegProgressParser().parse("frame=12\nprogress=continue\n")
    assert update.fraction is None and update.text == "frame 12"


def test_ffmpeg_stats_lines_count_too() -> None:
    parser = FfmpegProgressParser(duration_seconds=8)
    line = "frame=  120 fps= 30 q=28.0 size=     512kB time=00:00:04.00 bitrate=1048.6kbits/s speed=1.5x\r"
    (update,) = parser.parse(line + "\n")
    assert update.fraction == pytest.approx(0.5) and update.eta_seconds == pytest.approx(4 / 1.5)


def test_ffmpeg_end_is_done_only_once_nothing_follows_it() -> None:
    parser = FfmpegProgressParser(total_frames=10)
    ended = parser.parse("frame=10\nprogress=end\n")
    assert [u.kind for u in ended] == ["progress"]  # not yet: a failure prints after its last block
    assert [u.kind for u in parser.parse("")] == ["done"]

    failed = FfmpegProgressParser(total_frames=10)
    failed.parse("frame=4\nprogress=end\n")
    assert [u.kind for u in failed.parse("Conversion failed!\n")] == ["error"]
    # "Error while decoding" is routine: ffmpeg carries on.
    assert failed.parse("Error while decoding stream #0:0: Invalid data\n")[0].kind == "line"


@pytest.mark.parametrize(
    "line",
    [
        "TypeError: Cannot read properties of undefined (reading 'x')",
        "Traceback (most recent call last):",
        "sh: line 1:  4242 Killed                  node render.mjs",
        "FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory",
        "ffmpeg exited with code 1",
        "error: unknown option '--fps'",
    ],
)
def test_every_terminal_failure_is_an_error(line: str) -> None:
    assert HeartbeatParser().parse(line + "\n")[0].kind == "error"


@pytest.mark.parametrize("line", ["<ErrorBoundary> mounted", "0 errors, 2 warnings", "render: 3/9"])
def test_ordinary_lines_are_not_errors(line: str) -> None:
    assert HeartbeatParser().parse(line + "\n")[0].kind != "error"


def test_the_heartbeat_parser_keeps_lines_without_a_percentage() -> None:
    updates = HeartbeatParser().parse("bundling\nrender: 3/9 frames\n")
    assert [(u.kind, u.fraction, u.text) for u in updates] == [
        ("line", None, "bundling"),
        ("line", None, "render: 3/9 frames"),
    ]


def test_a_partial_line_waits_for_its_newline_or_a_quiet_poll() -> None:
    parser = RegexParser()
    assert parser.parse("render: 12") == []
    assert [u.fraction for u in parser.parse("0/300 frames\nrender: 15/300")] == [0.4]
    assert [u.fraction for u in parser.parse("")] == [0.05]  # quiet: the held line is whole


def test_the_regex_parser_reads_a_counter_or_a_percent() -> None:
    assert RegexParser().parse("render: 120/300 frames, 4.2 fps\n")[0].fraction == 0.4
    percent = RegexParser(r"(\d+(?:\.\d+)?)%", done=r"^all done$")
    assert percent.parse("upload 42.5%\n")[0].fraction == pytest.approx(0.425)
    assert percent.parse("all done\n")[0].kind == "done"
    assert RegexParser().parse("frame 400/300\n")[0].kind == "line"  # not a counter


def test_the_json_parser_reads_status_step_progress_and_eta() -> None:
    parser = JsonStatusParser()
    (update,) = parser.parse('{"status": "running", "step": "mux", "fraction": 0.5, "eta": "2m"}')
    assert (update.kind, update.fraction, update.eta_seconds, update.phase) == (
        "progress",
        0.5,
        120,
        "mux",
    )
    (update,) = parser.parse('{"status": "failed", "step": "audit", "error": "LUFS -9"}')
    assert update.kind == "error" and update.text == "failed, audit: LUFS -9"
    assert parser.parse('{"status": "done"}')[0].kind == "done"
    assert parser.parse("") == []


# -- HyperFrames, from real `hyperframes render` output -------------------------------------------

HF_PHASES = [
    "compiling",
    "extracting video",
    "processing audio",
    "starting capture",
    "capturing frames",
    "encoding",
    "assembling",
]


def _parse_all(parser: HyperFramesParser, text: str, chunk: int | None = None) -> list[Update]:
    """Everything the parser finds in `text`, fed whole or in `chunk`-byte reads, then a quiet
    poll, as a watch would."""
    pieces = [text] if chunk is None else [text[i : i + chunk] for i in range(0, len(text), chunk)]
    updates = [u for piece in pieces for u in parser.parse(piece)]
    return updates + parser.parse("")


def _phases(updates: list[Update]) -> list[str]:
    seen: list[str] = []
    for update in updates:
        if update.kind == "progress" and update.phase not in seen:
            seen.append(update.phase)
    return seen


@pytest.mark.parametrize("log", ["hyperframes-render.log", "hyperframes-render-tty.log"])
def test_a_hyperframes_render_reads_as_rising_progress_then_done(log: str) -> None:
    """Without a TTY (a detached job's log) the CLI writes `@hf-progress` lines and plain bars;
    under a TTY it redraws one colored bar with carriage returns. Both read the same."""
    updates = _parse_all(HyperFramesParser(), _fixture(log))

    progress = [u for u in updates if u.kind == "progress"]
    fractions = [u.fraction for u in progress]
    assert fractions and None not in fractions and fractions == sorted(fractions)
    assert fractions[0] == pytest.approx(0.05) and fractions[-1] == pytest.approx(0.99)
    assert _phases(updates) == HF_PHASES
    frames = [u.data for u in progress if u.phase == "capturing frames"]
    assert frames[0] == {"frames": 1, "total_frames": 60}
    assert frames[-1] == {"frames": 60, "total_frames": 60}
    # The label stops at the log line a TTY bar runs into.
    assert all("[" not in u.text for u in progress if not u.text.startswith("@hf"))
    assert not [u for u in updates if u.kind == "error"]
    (done,) = [u for u in updates if u.kind == "done"]
    assert done.text == "Render complete: /tmp/o.mp4" and done.data == {"output": "/tmp/o.mp4"}


def test_a_hyperframes_render_reads_the_same_in_any_chunking() -> None:
    text = _fixture("hyperframes-render.log")
    whole = _parse_all(HyperFramesParser(), text)
    for chunk in (7, 64, 1000):
        assert _parse_all(HyperFramesParser(), text, chunk) == whole


def test_a_failed_hyperframes_render_ends_at_its_failed_line_not_at_page_errors() -> None:
    """The page's own script errors (a 404 for gsap, a TypeError) are warnings in a best-effort
    render; the render fails at its `Failed:` line and error box."""
    text = _fixture("hyperframes-render-failed.log")
    assert "TypeError: Cannot read properties of null" in text  # logged before the verdict
    updates = _parse_all(HyperFramesParser(), text)

    errors = [u for u in updates if u.kind == "error"]
    assert [u.text for u in errors] == [
        "90%  Failed: Render blocked by 1 correctness warning:",
        "✗  Render failed",
    ]
    first = updates.index(errors[0])
    assert all(u.kind in ("progress", "line") for u in updates[:first])
    assert [u for u in updates[:first] if u.kind == "progress"][-1].phase == "encoding"
    assert not [u for u in updates if u.kind == "done"]


def test_a_hyperframes_usage_error_is_an_error() -> None:
    (update,) = _parse_all(HyperFramesParser(), _fixture("hyperframes-not-a-directory.log"))
    assert update.kind == "error" and update.text == "✗  Not a directory: /tmp/nope"


@pytest.mark.parametrize(
    ("line", "kind"),
    [
        ("  ████░░░░  16%  Render cancelled", "error"),
        ("sh: line 1:  4242 Killed                  hyperframes render .", "error"),
        ("[Browser:PAGEERROR] TypeError: Cannot read properties of null", "line"),
        (
            "[non-blocking] Failed to load resource: the server responded with a status of 404",
            "line",
        ),
        ('@hf-progress {"code":"capture","done":1,"total":60,"pct":1}', "progress"),
        ("@hf-progress {not json", "line"),
    ],
)
def test_hyperframes_lines(line: str, kind: str) -> None:
    (update,) = HyperFramesParser().parse(line + "\n")
    assert update.kind == kind
    if kind == "progress":  # pct is a percent even when it is 1
        assert update.fraction == pytest.approx(0.01) and update.phase == "capturing frames"


async def test_a_watched_hyperframes_job_ends_with_its_reason(tmp_path, runner) -> None:
    log = tmp_path / "render.log"
    bus, events = _collect()
    watch_id = runner.start(
        "t-1",
        label="act 1",
        source=SandboxFileSource(LocalShell(), str(log)),
        parser=parser_for("hyperframes"),
        poll_seconds=0.01,
        bus=bus,
    )
    text = _fixture("hyperframes-render-failed.log")
    cut = text.index("[WARN] Render completed capture")
    log.write_text(text[:cut])
    await _until(lambda: runner.get(watch_id).phase == "encoding")
    with log.open("a") as out:
        out.write(text[cut:])
    record = await _ended(runner, watch_id)

    error = events[-1]
    assert error.kind == ev.WATCH_ERROR and record.status == "error"
    assert error.text.splitlines()[0] == "90%  Failed: Render blocked by 1 correctness warning:"
    assert "sub_timeline_script_failure" in error.text
    assert decide(error).delivery is Delivery.NOW


# -- choosing a parser ----------------------------------------------------------------------------


def test_parser_for_names_every_kind_and_defaults_to_heartbeat() -> None:
    assert PARSER_KINDS == ("hyperframes", "ffmpeg", "json", "regex", "heartbeat")
    assert DEFAULT_PARSER == "heartbeat" and isinstance(parser_for(), HeartbeatParser)
    assert isinstance(parser_for("hyperframes"), HyperFramesParser)
    assert isinstance(parser_for("ffmpeg"), FfmpegProgressParser)
    assert isinstance(parser_for("json"), JsonStatusParser)
    assert isinstance(parser_for("regex"), RegexParser)
    with pytest.raises(ValueError, match="unknown kind 'remotion'; use hyperframes, ffmpeg"):
        parser_for("remotion")
    with pytest.raises(re.error):
        parser_for("regex", progress_regex="(")


def test_parser_for_passes_its_patterns_and_totals() -> None:
    regex = parser_for("regex", progress_regex=r"(\d+)%", done_regex="^ok$", error_regex="^bad")
    assert regex.parse("upload 40%\n")[0].fraction == pytest.approx(0.4)
    assert regex.parse("ok\n")[0].kind == "done" and regex.parse("bad thing\n")[0].kind == "error"
    assert parser_for("regex").parse("TypeError: x\n")[0].kind == "error"  # FAILURE by default
    ffmpeg = parser_for("ffmpeg", total_frames=100)
    assert ffmpeg.parse("frame=25\nprogress=continue\n")[0].fraction == 0.25
    heartbeat = parser_for("heartbeat", done_regex="^finished$", error_regex="^nope")
    assert heartbeat.parse("finished\n")[0].kind == "done"
    assert heartbeat.parse("TypeError: x\n")[0].kind == "line"  # replaced by error_regex
    hyperframes = parser_for("hyperframes", done_regex="^HF_OK$")
    assert [u.kind for u in hyperframes.parse("HF_OK\n") + hyperframes.parse("")] == ["done"]
    assert hyperframes.parse("✗  Render failed\n")[0].kind == "error"


def test_a_hyperframes_done_line_waits_one_read_for_its_output_path() -> None:
    parser = HyperFramesParser()
    assert parser.parse("  █████  100%  Render complete\n") == []
    (done, line) = parser.parse("\n◇  /workspace/out/film.mp4\n")
    assert done.kind == "done" and done.data == {"output": "/workspace/out/film.mp4"}
    assert line.text == "◇  /workspace/out/film.mp4"

    quiet = HyperFramesParser()
    assert quiet.parse("  █████  100%  Render complete\n") == []
    (done,) = quiet.parse("")  # nothing followed: done without a path
    assert done.kind == "done" and done.text == "100%  Render complete" and not done.data


def test_a_watch_stalls_after_five_minutes_of_silence_by_default() -> None:
    import inspect

    stall = inspect.signature(WatchRunner.start).parameters["stall_seconds"].default
    assert stall == 300.0
