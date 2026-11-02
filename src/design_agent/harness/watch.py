"""The render watcher: a background loop that turns a job's log or status file into events.

A final render runs for minutes in the sandbox and prints nothing a person sees until it ends, so a
stuck render looks exactly like a slow one, and nothing tells the lead when a detached job ends.

A watch is a small loop in this process. Every `poll_seconds` it reads what is new from a source (a
growing log, a status file, a command's output), hands it to a parser, and publishes what changed:
- `WATCH_STARTED` once;
- `WATCH_PROGRESS` with `fraction` and `eta_seconds`, when the fraction moves a point, the phase
  changes, or at least every minute while output flows. It is recorded, and the running lines of
  `check_tasks` and every notice show the latest; the lead is not woken for it;
- `WATCH_DONE`, or `WATCH_ERROR` with the error lines, either of which ends the watch;
- `WATCH_STALLED` once when nothing has come for `stall_seconds` (default 5 minutes): no new output
  and no progress. Silence is not success: a render the OOM killer took prints nothing. The watch
  keeps reading, and if output resumes it says so with an urgent progress event, since the lead was
  told it stalled;
- `WATCH_STALLED` with `timeout` when an optional overall timeout passes, which ends the watch.

Sources and parsers are separate so each stays small. A source only fetches new text: byte offsets
over `SandboxExec` (`wc -c`, then `tail -c +N`), robust to a truncated log. A parser only knows a
format (`parser_for`): `hyperframes` (the `hyperframes render` CLI), `ffmpeg` (`-progress`), `json`
(a status file), `regex` (any N/M counter) or `heartbeat` (the default: any output is a sign of
life, a failure line ends it). The filter must match every terminal state (errors, kills, OOM), not
only success. `harness.offload` reuses the runner for detached jobs.

`WatchLedger` keeps each watch's record in the deployment store, so a restart neither loses an end
the lead had not heard nor a watch it cut off: that one is reported as interrupted and stays
resumable for `RESUMABLE_SECONDS` (a day).

Deep Agents' `execute` runs a command to completion inside the tool call, with no background
command and no watcher; this module would sit beside it upstream.
"""

from __future__ import annotations

import asyncio
import builtins
import inspect
import json
import logging
import math
import re
import shlex
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol, runtime_checkable

from design_agent.harness import events as ev
from design_agent.harness.ledger import HEARTBEAT_SECONDS, STALE_SECONDS
from design_agent.harness.protocols import SandboxExec
from design_agent.harness.tasks import minutes, new_id

_LOGGER = logging.getLogger(__name__)

#: A watch the lead stopped is recorded only. events.py has no watch kind for that yet,
#: so it goes out as `task.cancelled`, which has that delivery and ends its source; `data["watch"]`
#: marks it. Swap in a `watch.cancelled` kind once events.py and policy.py have one.
WATCH_CANCELLED = ev.TASK_CANCELLED

#: Progress events: when the fraction moves this much, or at least this often while output flows.
PROGRESS_STEP = 0.01
PROGRESS_EVERY_SECONDS = 60.0
#: The ETA is a straight line through the progress of this recent window.
ETA_WINDOW_SECONDS = 300.0
#: Lines kept for context (the error text, a stall, a failed job's report).
TAIL_LINES = 20
#: A read that takes longer is abandoned and counted as failed, so a hung call can't hide a stall.
READ_TIMEOUT_SECONDS = 120.0
#: Ended watches stay listed this long.
KEEP_ENDED_SECONDS = 24 * 3600.0

#: Lines that mean a job failed, for any log: every terminal state, not only success. `Error\b`
#: catches `TypeError:` but not `ErrorBoundary`.
FAILURE = (
    r"Error\b|error:|✖|Traceback|ENOENT|\bKilled\b|\bOOM\b|out of memory|Segmentation fault"
    r"|exited with code [1-9]"
)
#: The ffmpeg messages that end it. "Error while decoding" is routine and ffmpeg carries on.
FFMPEG_FAILURE = (
    r"(?i)conversion failed|error opening (?:input|output)|error initializing"
    r"|no such file or directory|unrecognized option|unknown encoder|invalid argument"
    r"|\bkilled\b|out of memory|exited with code [1-9]"
)

Pattern = str | re.Pattern[str]


# -- what a parser reads ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Update:
    """What a parser found in new output.

    `kind` is `progress` (a counter or status moved), `error` (a line that means it failed), `done`
    (a line that means it finished) or `line` (anything else, kept for context). `fraction` is 0-1
    when known; `eta_seconds` when the source states one; `phase` names the stage ("rendering",
    "encoding", a status file's `step`); `data` carries extra facts (`cost_usd`, `output`) into
    the event.
    """

    kind: Literal["progress", "error", "done", "line"]
    fraction: float | None = None
    eta_seconds: float | None = None
    text: str = ""
    phase: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class WatchSource(Protocol):
    """Where a watch reads from.

    `read` returns the text that is new since the last read, or "" when nothing is. `closed` turns
    true once nothing more can come. `note` says why the last read had nothing (the file does not
    exist yet, the JSON is torn), for the stall message.
    """

    closed: bool
    note: str

    async def read(self) -> str: ...


@runtime_checkable
class WatchParser(Protocol):
    def parse(self, text: str) -> list[Update]:
        """Updates for a source's new text. "" means the source was quiet this poll; a line parser
        then finishes a partial line it was holding."""
        ...


# -- parsers ----------------------------------------------------------------------------------------

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_BREAK = re.compile(r"\r\n|\r|\n")


def _patterns(value: Pattern | Sequence[Pattern] | None) -> list[re.Pattern[str]]:
    if value is None or isinstance(value, str | re.Pattern):
        value = [value] if value else []
    return [p if isinstance(p, re.Pattern) else re.compile(p) for p in value if p]


class LineParser:
    """Line-oriented output: split on newlines and carriage returns (a TTY progress bar redraws with
    `\\r`), colors stripped, a partial last line held until it completes or the source goes quiet.
    Each line is checked for done, then error, then progress (`progress`, which subclasses define).
    """

    def __init__(
        self,
        *,
        error: Pattern | Sequence[Pattern] | None = FAILURE,
        done: Pattern | Sequence[Pattern] | None = None,
    ) -> None:
        self._error = _patterns(error)
        self._done = _patterns(done)
        self._held = ""

    def parse(self, text: str) -> list[Update]:
        if text:
            pieces = _BREAK.split(self._held + text)
            self._held = pieces.pop()
        else:
            pieces, self._held = [self._held], ""
        updates: list[Update] = []
        for piece in pieces:
            line = _ANSI.sub("", piece).strip()
            if line:
                updates.extend(self.parse_line(line))
        return updates

    def parse_line(self, line: str) -> list[Update]:
        if any(p.search(line) for p in self._done):
            return [Update("done", fraction=1.0, text=line)]
        if any(p.search(line) for p in self._error):
            return [Update("error", text=line)]
        return self.progress(line)

    def progress(self, line: str) -> list[Update]:
        return [Update("line", text=line)]


def _counter(match: re.Match[str] | None) -> tuple[int, int] | None:
    """A done/total pair from a match, or None when it can't be a counter (0 total, done > total:
    a partial line)."""
    if match is None:
        return None
    done, total = int(match[1]), int(match[2])
    return (done, total) if 0 < total and 0 <= done <= total else None


class HeartbeatParser(LineParser):
    """Any log, read for signs of life only: each new line resets the stall timer and is kept for
    context, and a line that means failure (`FAILURE`) ends the watch. It reports no percentage.
    The default format: a detached job's exit code still says how it ended."""


#: What ends a HyperFrames render as failed: its error box (`✗  Render failed`, `✗  Not a
#: directory: …`), a `Failed:` or `Render cancelled` progress line, or the process being killed.
#: Generic `Error` lines are left out on purpose: a best-effort render logs the page's own script
#: errors as warnings and still finishes.
HYPERFRAMES_FAILURE = (
    r"^✗\s+\S",
    r"^[█░]*\s*\d{1,3}%\s+(?:Failed:|Render cancelled)",
    r"\bKilled\b|\bOOM\b|out of memory|Segmentation fault|exited with code [1-9]",
)

#: Phase names for HyperFrames' stage codes and progress-line labels, matched by keyword in order.
_HF_PHASES = (
    ("compil", "compiling"),
    ("extract", "extracting video"),
    ("audio", "processing audio"),
    ("start", "starting capture"),
    ("browser", "starting capture"),
    ("captur", "capturing frames"),
    ("stream", "capturing frames"),
    ("encod", "encoding"),
    ("assembl", "assembling"),
)
_COUNTS = re.compile(r"\([^)]*\)|\d+\s*/\s*\d+")
_FRAME_PHASES = frozenset({"capturing frames", "encoding"})


def _percent(value: object) -> float | None:
    """A percent (0-100) as a fraction (0-1); None when it is not a number."""
    number = _number(value)
    return None if number is None or number < 0 else min(1.0, number / 100)


def _hf_phase(stage: str) -> str:
    """One phase name for a stage, whether it came as a code (`capture`) or a label
    (`Streaming frame 12/60`), so the two forms of one step never read as a phase change."""
    lowered = stage.lower()
    for key, phase in _HF_PHASES:
        if key in lowered:
            return phase
    return " ".join(_COUNTS.sub("", lowered).replace("_", " ").split()) or "rendering"


class HyperFramesParser(LineParser):
    """`hyperframes render` output, as a detached job's log (no TTY) or a terminal's.

    Without a TTY the CLI writes `@hf-progress {"code": …, "pct": …, "done": …, "total": …}` for
    every step, beside a plain progress line (`████░░  42%  Streaming frame 25/60`); under a TTY
    only the progress line is drawn, redrawn with `\\r`. Either gives the fraction (`pct` / 100), a
    phase (compiling, capturing frames, encoding, assembling) and frame counts. Done at
    `100%  Render complete`, with the output path from the `◇  <path>` line after it (the done line
    waits one read for it, and a quiet poll gives up). Failed on `HYPERFRAMES_FAILURE`.
    """

    MACHINE = re.compile(r"^@hf-progress\s+(\{.*\})\s*$")
    BAR = re.compile(r"^[█░]+\s+(\d{1,3})%\s+(\S.*)$")
    COMPLETE = r"^[█░]*\s*100%\s+Render complete\b"
    OUTPUT = re.compile(r"^◇\s+(/\S.*)$")
    LOG_TAG = re.compile(r"\[[\w:-]+\]")
    GLYPHS = re.compile(r"^[█░]+\s+")

    def __init__(
        self,
        *,
        error: Pattern | Sequence[Pattern] | None = HYPERFRAMES_FAILURE,
        done: Pattern | Sequence[Pattern] | None = None,
    ) -> None:
        super().__init__(error=error, done=[self.COMPLETE, *_patterns(done)])
        #: A done line waiting one read for the output path that follows it.
        self._held_done: Update | None = None

    def parse(self, text: str) -> list[Update]:
        updates = [replace(u, text=self.GLYPHS.sub("", u.text)) for u in super().parse(text)]
        if self._held_done is not None:
            updates.insert(0, self._held_done)
            self._held_done = None
        for index, update in enumerate(updates):
            if update.kind != "done":
                continue
            for later in updates[index + 1 :]:
                found = self.OUTPUT.match(later.text)
                if found is not None:
                    data = {**update.data, "output": found[1]}
                    shown = f"Render complete: {found[1]}"
                    updates[index] = replace(update, text=shown, data=data)
                    break
            else:
                if text:  # the path may be in the next read; a quiet poll gives up on it
                    self._held_done = updates.pop(index)
            break
        return updates

    def progress(self, line: str) -> list[Update]:
        machine = self.MACHINE.match(line)
        if machine is not None:
            return self._machine(line, machine[1])
        bar = self.BAR.match(line)
        if bar is None:
            return [Update("line", text=line)]
        # Under a TTY the bar has no newline, so the next log line can land on the same line.
        stage = self.LOG_TAG.split(bar[2], maxsplit=1)[0].strip() or bar[2]
        phase = _hf_phase(stage)
        counts = _counter(re.search(r"(\d+)\s*/\s*(\d+)", stage))
        data = (
            {"frames": counts[0], "total_frames": counts[1]}
            if counts is not None and phase in _FRAME_PHASES
            else {}
        )
        return [Update("progress", _percent(bar[1]), text=stage, phase=phase, data=data)]

    def _machine(self, line: str, payload: str) -> list[Update]:
        try:
            value = json.loads(payload)
        except ValueError:
            return [Update("line", text=line)]
        if not isinstance(value, Mapping):
            return [Update("line", text=line)]
        phase = _hf_phase(str(value.get("code") or ""))
        done, total = value.get("done"), value.get("total")
        counted = isinstance(done, int) and isinstance(total, int) and 0 < total
        data = {"frames": done, "total_frames": total} if counted and phase in _FRAME_PHASES else {}
        text = f"{phase} {done}/{total}" if counted else phase
        return [Update("progress", _percent(value.get("pct")), text=text, phase=phase, data=data)]


def _number(value: object) -> float | None:
    try:
        number = float(str(value).strip().rstrip("x"))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _clock_seconds(value: str) -> float | None:
    parts = value.strip().split(":")
    if len(parts) != 3 or value.strip().startswith("-"):
        return None
    numbers = [_number(p) for p in parts]
    if any(n is None for n in numbers):
        return None
    hours, mins, secs = (n or 0.0 for n in numbers)
    return hours * 3600 + mins * 60 + secs


class FfmpegProgressParser(LineParser):
    """ffmpeg's `-progress` blocks (`frame=`, `out_time_us=`, `speed=`, ending `progress=continue`
    or `progress=end`, every half second), and its ordinary stats line as a fallback.

    The fraction needs `total_frames` or `duration_seconds`; without them progress carries the frame
    and time only. `progress=end` is reported done once a quiet poll confirms nothing follows it,
    because on a failure ffmpeg prints its last block before "Conversion failed!". Only messages
    that end ffmpeg count as errors (`FFMPEG_FAILURE`).
    """

    KEY = re.compile(r"^([a-z_0-9]+)=(\S*)$")
    STATS = re.compile(
        r"frame=\s*(\d+)(?:.*?fps=\s*([\d.]+))?.*?time=\s*(-?[\d:.]+)(?:.*?speed=\s*([\d.]+)x)?"
    )

    def __init__(
        self,
        total_frames: int | None = None,
        duration_seconds: float | None = None,
        *,
        error: Pattern | Sequence[Pattern] | None = FFMPEG_FAILURE,
        done: Pattern | Sequence[Pattern] | None = None,
    ) -> None:
        super().__init__(error=error, done=done)
        self._total = total_frames or None
        self._duration = duration_seconds or None
        self._block: dict[str, str] = {}
        self._ended = False

    def parse(self, text: str) -> list[Update]:
        updates = super().parse(text)
        if not text and self._ended:
            self._ended = False
            updates.append(Update("done", fraction=1.0, text="ffmpeg finished (progress=end)."))
        return updates

    def progress(self, line: str) -> list[Update]:
        key = self.KEY.match(line)
        if key is not None:
            self._block[key[1]] = key[2]
            if key[1] != "progress":
                return []
            block, self._block = self._block, {}
            if key[2] == "end":
                self._ended = True
            seconds = next(
                (
                    n / 1e6
                    for n in (_number(block.get("out_time_us")), _number(block.get("out_time_ms")))
                    if n is not None and n >= 0
                ),
                _clock_seconds(block.get("out_time", "")),
            )
            frame = _number(block.get("frame"))
            return [
                self._update(frame, seconds, _number(block.get("speed")), _number(block.get("fps")))
            ]
        stats = self.STATS.search(line)
        if stats is None:
            return [Update("line", text=line)]
        return [
            self._update(
                _number(stats[1]), _clock_seconds(stats[3]), _number(stats[4]), _number(stats[2])
            )
        ]

    def _update(
        self, frame: float | None, seconds: float | None, speed: float | None, fps: float | None
    ) -> Update:
        fraction = eta = None
        if self._total and frame is not None:
            fraction = min(1.0, frame / self._total)
            eta = max(0.0, (self._total - frame) / fps) if fps else None
        elif self._duration and seconds is not None:
            fraction = min(1.0, seconds / self._duration)
            eta = max(0.0, (self._duration - seconds) / speed) if speed else None
        parts = []
        if frame is not None:
            parts.append(f"frame {int(frame)}" + (f"/{self._total}" if self._total else ""))
        if seconds is not None:
            parts.append(f"{seconds:.1f}s" + (f" of {self._duration:g}s" if self._duration else ""))
        if speed:
            parts.append(f"{speed:g}x")
        data = {
            key: value
            for key, value in (("frame", frame), ("out_seconds", seconds), ("speed", speed))
            if value is not None
        }
        return Update("progress", fraction, eta, ", ".join(parts), phase="encoding", data=data)


def _fraction(value: object) -> float | None:
    number = _number(value)
    if number is None or number < 0:
        return None
    return min(1.0, number / 100 if number > 1 else number)


def _eta(value: object) -> float | None:
    if isinstance(value, str) and ":" in value:
        return _clock_seconds(value)
    if isinstance(value, str) and value.strip().endswith(("s", "m", "h")):
        number = _number(value.strip()[:-1])
        scale = {"s": 1, "m": 60, "h": 3600}[value.strip()[-1]]
        return number * scale if number is not None else None
    number = _number(value)
    return number if number is not None and number >= 0 else None


class JsonStatusParser:
    """A JSON status file, such as a project's run.json: `status`, `step`, `progress` or `fraction`
    (0-1, or a percent), `eta` (seconds, "90s", "3m" or "00:03:00"). A status of done, success,
    complete or finished ends the watch as done; failed or error, as an error with the file's
    `error` or `message`. A `cost` or `output` field rides along in the event."""

    DONE = frozenset({"done", "success", "succeeded", "complete", "completed", "finished"})
    FAILED = frozenset({"failed", "failure", "error", "errored"})

    def parse(self, text: str) -> list[Update]:
        if not text.strip():
            return []
        try:
            value = json.loads(text)
        except ValueError:
            return [Update("line", text=text.strip()[:300])]
        if not isinstance(value, Mapping):
            return [Update("line", text=text.strip()[:300])]
        status = str(value.get("status") or "").strip()
        step = str(value.get("step") or "").strip()
        data = {
            key: value[key]
            for key in ("cost", "cost_usd", "output")
            if value.get(key) not in (None, "")
        }
        summary = ", ".join(part for part in (status, step) if part) or text.strip()[:200]
        if status.lower() in self.DONE:
            return [Update("done", fraction=1.0, text=summary, data=data)]
        if status.lower() in self.FAILED:
            reason = str(value.get("error") or value.get("message") or "").strip()
            return [Update("error", text=f"{summary}: {reason}" if reason else summary, data=data)]
        fraction = _fraction(value.get("progress", value.get("fraction")))
        return [
            Update(
                "progress",
                fraction=fraction,
                eta_seconds=_eta(value.get("eta")),
                text=summary,
                phase=step or status,
                data=data,
            )
        ]


class RegexParser(LineParser):
    """Any log with a counter. `progress` has two groups (done, total) or one (a percent); the
    default reads "120/300", as in `render: 120/300 frames`. `error` and
    `done` are the lines that end the watch (by default errors are `FAILURE`, and nothing is done:
    such a job's end shows as a stall unless something prints a done line)."""

    def __init__(
        self,
        progress: Pattern | None = r"(\d+)\s*/\s*(\d+)",
        *,
        error: Pattern | Sequence[Pattern] | None = FAILURE,
        done: Pattern | Sequence[Pattern] | None = None,
    ) -> None:
        super().__init__(error=error, done=done)
        self._progress = _patterns(progress)

    def progress(self, line: str) -> list[Update]:
        match = next((m for p in self._progress if (m := p.search(line))), None)
        groups = [g for g in (match.groups() if match else ()) if g is not None]
        numbers = [_number(g) for g in groups[:2]]
        fraction = None
        if len(numbers) == 2 and numbers[0] is not None and numbers[1]:
            if 0 <= numbers[0] <= numbers[1]:
                fraction = numbers[0] / numbers[1]
        elif len(numbers) == 1 and numbers[0] is not None and 0 <= numbers[0] <= 100:
            fraction = numbers[0] / 100
        if fraction is None:
            return [Update("line", text=line)]
        return [Update("progress", fraction=fraction, text=line)]


# -- choosing a parser ------------------------------------------------------------------------------

ParserKind = Literal["hyperframes", "ffmpeg", "json", "regex", "heartbeat"]
PARSER_KINDS: tuple[ParserKind, ...] = ("hyperframes", "ffmpeg", "json", "regex", "heartbeat")
DEFAULT_PARSER: ParserKind = "heartbeat"


def parser_for(
    kind: str = DEFAULT_PARSER,
    *,
    total_frames: int = 0,
    duration_seconds: float = 0,
    progress_regex: str = "",
    error_regex: str = "",
    done_regex: str = "",
) -> WatchParser:
    """The parser for output of `kind` (`PARSER_KINDS`).

    `error_regex` replaces the lines that mean failure; `done_regex` adds a line that means done;
    `progress_regex` is the `regex` kind's counter; `total_frames` or `duration_seconds` give
    `ffmpeg` a percentage. `json` reads a status file, so its source is `SandboxJsonSource`.
    Raises `ValueError` for an unknown kind and `re.error` for a bad pattern.
    """
    done = done_regex or None
    if kind == "hyperframes":
        return HyperFramesParser(error=error_regex or HYPERFRAMES_FAILURE, done=done)
    if kind == "ffmpeg":
        return FfmpegProgressParser(
            total_frames or None,
            duration_seconds or None,
            error=error_regex or FFMPEG_FAILURE,
            done=done,
        )
    if kind == "json":
        return JsonStatusParser()
    if kind == "regex":
        return RegexParser(
            progress_regex or r"(\d+)\s*/\s*(\d+)", error=error_regex or FAILURE, done=done
        )
    if kind == "heartbeat":
        return HeartbeatParser(error=error_regex or FAILURE, done=done)
    raise ValueError(f"unknown kind {kind!r}; use {', '.join(PARSER_KINDS)}")


# -- sources ----------------------------------------------------------------------------------------

#: One read returns at most this many new bytes. A log that grew more between polls is read from its
#: last `READ_BYTES`: the newest output is what says how the job is doing.
READ_BYTES = 256 * 1024
#: Seconds one sandbox command may run.
EXEC_TIMEOUT = 60
_MARK = "@@watch"
_END = "@@watch-end"


class WatchReadError(RuntimeError):
    """A source could not read (its sandbox command failed). The watch keeps polling; the failure
    goes into the stall message if reads keep failing."""


def _after_mark(output: str) -> tuple[str, str]:
    """The header line after the marker, and everything after it."""
    at = output.find(_MARK)
    if at < 0:
        return "", output
    header, _, body = output[at:].partition("\n")
    return header.strip(), body


class SandboxFileSource:
    """New bytes of a growing file in the sandbox, by byte offset: `wc -c`, then `tail -c +N`.

    A file that shrank (truncated, or rewritten from the start) is read again from the top. A file
    that doesn't exist yet reads as nothing, so a watch can start before the job writes its log.
    The output ends with a marker so a trailing newline survives transport, and stderr is kept out
    of it (some sandbox backends append stderr to stdout).
    """

    def __init__(
        self,
        exec: SandboxExec,
        path: str,
        *,
        max_bytes: int = READ_BYTES,
        timeout: int = EXEC_TIMEOUT,
    ) -> None:
        self.path = path
        self.offset = 0
        self.closed = False
        self.note = ""
        self._exec = exec
        self._max = max_bytes
        self._timeout = timeout

    def command(self) -> str:
        return (
            f"f={shlex.quote(self.path)}; o={self.offset}; cap={self._max}\n"
            f'if [ ! -f "$f" ]; then echo "{_MARK} missing"; exit 0; fi\n'
            's=$( { wc -c < "$f"; } 2>/dev/null | tr -d " \\n"); s=${s:-0}\n'
            'if [ "$s" -lt "$o" ]; then o=0; fi\n'
            'if [ $((s - o)) -gt "$cap" ]; then o=$((s - cap)); fi\n'
            f'echo "{_MARK} $s $o"\n'
            'tail -c +$((o + 1)) "$f" 2>/dev/null | head -c $((s - o)) 2>/dev/null\n'
            "printf '\\n" + _END + "\\n'"
        )

    async def read(self) -> str:
        result = await self._exec.execute(self.command(), timeout=self._timeout)
        header, body = _after_mark(result.output)
        if header == f"{_MARK} missing":
            self.offset = 0  # a file that comes back is a new file
            self.note = f"{self.path} does not exist yet"
            return ""
        fields = header.split()
        end = body.rfind("\n" + _END)
        if len(fields) != 3 or end < 0 or not all(f.isdigit() for f in fields[1:]):
            raise WatchReadError(f"reading {self.path} failed: {result.output.strip()[-300:]}")
        body = body[:end]
        size, start = int(fields[1]), int(fields[2])
        truncated = size < self.offset
        if start > 0 and start != self.offset:
            body = body.partition("\n")[2]  # it starts mid-line after the skipped bytes
        self.offset = size
        self.note = f"{self.path} was truncated; reading it again from the top" if truncated else ""
        return body


class SandboxJsonSource:
    """A small JSON status file (a project's run.json), re-read each poll and returned, in
    canonical form, when its content changes. A torn or half-written file is skipped until it
    parses."""

    def __init__(
        self,
        exec: SandboxExec,
        path: str,
        *,
        max_bytes: int = 64 * 1024,
        timeout: int = EXEC_TIMEOUT,
    ) -> None:
        self.path = path
        self.closed = False
        self.note = ""
        self._exec = exec
        self._max = max_bytes
        self._timeout = timeout
        self._last: str | None = None

    def command(self) -> str:
        return (
            f"f={shlex.quote(self.path)}\n"
            f'if [ -f "$f" ]; then echo "{_MARK} file"; head -c {self._max} "$f" 2>/dev/null; '
            f'else echo "{_MARK} missing"; fi'
        )

    async def read(self) -> str:
        result = await self._exec.execute(self.command(), timeout=self._timeout)
        header, body = _after_mark(result.output)
        if header == f"{_MARK} missing":
            self.note = f"{self.path} does not exist yet"
            return ""
        if header != f"{_MARK} file":
            raise WatchReadError(f"reading {self.path} failed: {result.output.strip()[-300:]}")
        try:
            value = json.loads(body)
        except ValueError:
            self.note = f"{self.path} is not valid JSON (yet)"
            return ""
        self.note = ""
        text = json.dumps(value, sort_keys=True)
        if text == self._last:
            return ""
        self._last = text
        return text


class CommandSource:
    """A command's output, run each poll and returned when it differs from the last: a status
    endpoint, or a frame count (`echo "$(ls frames | wc -l)/300"`)."""

    def __init__(self, exec: SandboxExec, command: str, *, timeout: int = EXEC_TIMEOUT) -> None:
        self.command = command
        self.closed = False
        self.note = ""
        self._exec = exec
        self._timeout = timeout
        self._last: str | None = None

    async def read(self) -> str:
        result = await self._exec.execute(self.command, timeout=self._timeout)
        ok = result.exit_code in (0, None)
        self.note = "" if ok else f"the command exited with {result.exit_code}"
        if result.output == self._last:
            return ""
        self._last = result.output
        if not result.output.strip():
            return ""
        return result.output if result.output.endswith("\n") else result.output + "\n"


# -- the runner -------------------------------------------------------------------------------------

Status = Literal["watching", "done", "error", "timed_out", "cancelled", "interrupted"]
#: Called after every poll and once when the watch ends (not on a shutdown), so an adapter can keep
#: a heartbeat record.
Beat = Callable[["WatchRecord"], Awaitable[None] | None]


@dataclass
class WatchRecord:
    """One watch and what it has seen."""

    id: str
    thread_id: str
    label: str
    started_at: float
    poll_seconds: float
    stall_seconds: float
    timeout_seconds: float | None = None
    status: Status = "watching"
    fraction: float | None = None
    eta_seconds: float | None = None
    phase: str = ""
    #: The latest progress line.
    text: str = ""
    stalled: bool = False
    polls: int = 0
    last_output_at: float | None = None
    ended_at: float | None = None
    #: The event that ended it, for an adapter that keeps it until the lead has heard.
    final: ev.Event | None = None
    #: Adapter facts (the file, the parser kind, a job id), published with `WATCH_STARTED`.
    meta: dict[str, Any] = field(default_factory=dict)
    tail: deque[str] = field(default_factory=lambda: deque(maxlen=TAIL_LINES), repr=False)
    handle: asyncio.Task[None] | None = field(default=None, repr=False)
    #: Set by `cancel`, so a stop the lead asked for is told apart from a shutdown.
    cancel_requested: bool = False

    def describe(self) -> str:
        """One line: where it stands."""
        state = {
            "watching": "stalled" if self.stalled else "watching",
            "timed_out": "timed out",
        }.get(self.status, self.status)
        parts = [state]
        if self.fraction is not None:
            parts.append(f"{self.fraction * 100:.0f}%")
        if self.phase:
            parts.append(self.phase)
        if self.status == "watching" and self.eta_seconds is not None:
            parts.append(f"about {_duration(self.eta_seconds)} left")
        line = f"{self.id} ({self.label}): {', '.join(parts)}"
        return f"{line}; last line: {self.tail[-1]}" if self.tail else line


def _duration(seconds: float) -> str:
    return f"{max(1, round(seconds))} s" if seconds < 90 else minutes(seconds)


class _Eta:
    """A straight line through the recent (time, fraction) points."""

    def __init__(self, window: float) -> None:
        self._window = window
        self._points: deque[tuple[float, float]] = deque()

    def add(self, at: float, fraction: float) -> None:
        if self._points and fraction < self._points[-1][1]:
            self._points.clear()  # it went back: a new pass or a restarted job
        self._points.append((at, fraction))
        while len(self._points) > 2 and at - self._points[0][0] > self._window:
            self._points.popleft()

    def estimate(self) -> float | None:
        if len(self._points) < 2:
            return None
        (t0, f0), (t1, f1) = self._points[0], self._points[-1]
        if f1 <= f0 or t1 <= t0:
            return None
        return max(0.0, (1.0 - f1) * (t1 - t0) / (f1 - f0))


@dataclass
class _Loop:
    """A watch's working state, beside its public record."""

    eta: _Eta
    last_activity: float
    published_at: float = 0.0
    published_fraction: float | None = None
    published_phase: str = ""
    failure: str = ""


class WatchRunner:
    """Runs watches as asyncio tasks in this process (module doc). One runner per process is
    enough; an adapter keeps it at module level because a watch outlives the call that started it.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        progress_step: float = PROGRESS_STEP,
        progress_every_seconds: float = PROGRESS_EVERY_SECONDS,
        eta_window_seconds: float = ETA_WINDOW_SECONDS,
        read_timeout_seconds: float = READ_TIMEOUT_SECONDS,
    ) -> None:
        self._clock = clock
        self._step = progress_step
        self._every = progress_every_seconds
        self._window = eta_window_seconds
        self._read_timeout = read_timeout_seconds
        self._records: dict[str, WatchRecord] = {}

    def start(
        self,
        thread_id: str,
        *,
        label: str,
        source: WatchSource,
        parser: WatchParser,
        poll_seconds: float = 15.0,
        stall_seconds: float = 300.0,
        timeout_seconds: float | None = None,
        bus: ev.EventBus | None = None,
        on_beat: Beat | None = None,
        meta: Mapping[str, Any] | None = None,
        watch_id: str | None = None,
    ) -> str:
        """Start watching and return the watch id (`r-xxxxxx`) at once. Needs a running loop."""
        bus = bus or ev.BUS
        self._prune()
        record = WatchRecord(
            id=watch_id or new_id("r"),
            thread_id=thread_id,
            label=label,
            started_at=self._clock(),
            poll_seconds=poll_seconds,
            stall_seconds=stall_seconds,
            timeout_seconds=timeout_seconds or None,
            meta=dict(meta or {}),
        )
        self._records[record.id] = record
        bus.publish(
            ev.Event(
                ev.WATCH_STARTED,
                thread_id,
                record.id,
                label=label,
                text=f"Watching {label}.",
                data={
                    **record.meta,
                    "poll_seconds": poll_seconds,
                    "stall_seconds": stall_seconds,
                    "timeout_seconds": record.timeout_seconds,
                },
            )
        )
        record.handle = asyncio.get_running_loop().create_task(
            self._watch(record, source, parser, bus, on_beat), name=f"watch {record.id}"
        )
        return record.id

    def cancel(self, watch_id: str) -> bool:
        """Stop a running watch. Its end is recorded only; nothing wakes the lead."""
        record = self._records.get(watch_id)
        if record is None or record.status != "watching" or record.handle is None:
            return False
        if record.cancel_requested or record.handle.done():
            return False
        record.cancel_requested = True
        record.handle.cancel()
        return True

    def get(self, watch_id: str) -> WatchRecord | None:
        return self._records.get(watch_id)

    def running_lines(self, thread_id: str) -> builtins.list[str]:
        """One line per running watch, for notices and `check_tasks`:
        'r-1a2b3c (watch, final render, 42%, about 3 min left, 12 min)'."""
        now = self._clock()
        lines = []
        for record in self.list(thread_id):
            if record.status != "watching":
                continue
            parts = ["watch", record.label]
            if record.stalled:
                parts.append("stalled")
            if record.fraction is not None:
                parts.append(f"{record.fraction * 100:.0f}%")
            if record.eta_seconds is not None and not record.stalled:
                parts.append(f"about {_duration(record.eta_seconds)} left")
            parts.append(minutes(now - record.started_at))
            lines.append(f"{record.id} ({', '.join(parts)})")
        return lines

    def clear(self) -> None:
        """Stop every watch and forget them all (tests, shutdown)."""
        for record in self._records.values():
            if record.handle is not None and not record.handle.done():
                record.handle.cancel()
        self._records.clear()

    def _prune(self) -> None:
        cutoff = self._clock() - KEEP_ENDED_SECONDS
        for watch_id, record in builtins.list(self._records.items()):
            if record.ended_at is not None and record.ended_at < cutoff:
                del self._records[watch_id]

    # -- the loop -----------------------------------------------------------------------------

    async def _watch(
        self,
        record: WatchRecord,
        source: WatchSource,
        parser: WatchParser,
        bus: ev.EventBus,
        on_beat: Beat | None,
    ) -> None:
        loop = _Loop(eta=_Eta(self._window), last_activity=record.started_at)
        try:
            while not await self._poll(record, source, parser, bus, loop):
                await _beat(on_beat, record)
                await asyncio.sleep(record.poll_seconds)
        except asyncio.CancelledError:
            if record.status == "watching":
                record.ended_at = self._clock()
                if record.cancel_requested:
                    record.status = "cancelled"
                    record.final = self._publish(
                        bus, record, WATCH_CANCELLED, "Stopped watching.", {"watch": True}
                    )
                    await _beat(on_beat, record)
                else:
                    # A shutdown: the heartbeat record stays behind for the sweep to report.
                    record.status = "interrupted"
            raise
        except Exception as error:  # noqa: BLE001 - a watch that breaks says so, never silently
            _LOGGER.warning("[harness] watch %s broke: %s", record.id, type(error).__name__)
            self._end(
                record, bus, ev.WATCH_ERROR, "error", f"The watch itself failed: {error}"[:500]
            )
        await _beat(on_beat, record)

    async def _read(self, source: WatchSource, loop: _Loop) -> str:
        try:
            text = await asyncio.wait_for(source.read(), timeout=self._read_timeout)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - counted, reported with the stall
            loop.failure = f"{type(error).__name__}: {str(error)[:300]}"
            _LOGGER.info("[harness] a watch read failed: %s", loop.failure)
            return ""
        loop.failure = ""
        return text

    async def _poll(
        self,
        record: WatchRecord,
        source: WatchSource,
        parser: WatchParser,
        bus: ev.EventBus,
        loop: _Loop,
    ) -> bool:
        """One read and everything it calls for. True when the watch has ended."""
        text = await self._read(source, loop)
        now = self._clock()
        record.polls += 1
        updates = parser.parse(text)
        if source.closed:
            updates += parser.parse("")
        moved = any(
            u.kind == "progress" and u.fraction is not None and u.fraction != record.fraction
            for u in updates
        )
        silent_for = now - loop.last_activity
        resumed = record.stalled and bool(text or moved)
        if text or moved:
            loop.last_activity = now
            record.last_output_at = now
            record.stalled = False

        lines = [u.text for u in updates if u.text]
        record.tail.extend(lines)
        errors = [i for i, u in enumerate(updates) if u.kind == "error"]
        done = next((u for u in updates if u.kind == "done"), None)
        if errors:
            texts = [u.text for u in updates[errors[0] :] if u.text][:TAIL_LINES]
            data: dict[str, Any] = {"lines": texts, "tail": builtins.list(record.tail)}
            if done is not None:
                data["done_line"] = done.text
            self._end(record, bus, ev.WATCH_ERROR, "error", "\n".join(texts)[:2000], data)
            return True
        if done is not None:
            record.fraction = done.fraction if done.fraction is not None else 1.0
            data = {"took_seconds": round(now - record.started_at, 1), **done.data}
            self._end(record, bus, ev.WATCH_DONE, "done", done.text or "Finished.", data)
            return True

        self._progress(record, updates, now, bus, loop, resumed, silent_for)

        if source.closed:
            note = f" ({source.note})" if source.note else ""
            tail = "\n".join(record.tail)
            text = f"It ended without a done or error line{note}." + (
                f" Last lines:\n{tail}" if tail else ""
            )
            self._end(record, bus, ev.WATCH_ERROR, "error", text[:2000])
            return True
        if not record.stalled and now - loop.last_activity >= record.stall_seconds:
            record.stalled = True
            self._stalled(record, bus, loop, source, now)
        if record.timeout_seconds and now - record.started_at >= record.timeout_seconds:
            text = f"Stopped watching after {_duration(record.timeout_seconds)}" + self._where(
                record
            )
            data = {"timeout": True, "ended": True, "fraction": record.fraction}
            self._end(record, bus, ev.WATCH_STALLED, "timed_out", text, data)
            return True
        return False

    def _progress(
        self,
        record: WatchRecord,
        updates: Sequence[Update],
        now: float,
        bus: ev.EventBus,
        loop: _Loop,
        resumed: bool,
        silent_for: float,
    ) -> None:
        fresh = next((u for u in reversed(updates) if u.kind == "progress"), None)
        if fresh is None and not resumed:
            return
        data: dict[str, Any] = {}
        if fresh is not None:
            if fresh.fraction is not None:
                record.fraction = fresh.fraction
                loop.eta.add(now, fresh.fraction)
            record.phase = fresh.phase or record.phase
            record.text = fresh.text or record.text
            record.eta_seconds = (
                fresh.eta_seconds if fresh.eta_seconds is not None else loop.eta.estimate()
            )
            data.update(fresh.data)
        moved = record.fraction is not None and (
            loop.published_fraction is None
            or abs(record.fraction - loop.published_fraction) >= self._step - 1e-9
        )
        due = now - loop.published_at >= self._every
        if not (moved or record.phase != loop.published_phase or due or resumed):
            return
        text = self._state(record)
        if resumed:
            # The lead was woken to hear it stalled, so it hears this too.
            data.update({"resumed": True, "urgent": True, "silent_seconds": round(silent_for)})
            text = f"Output resumed after {_duration(silent_for)} of silence: {text}"
        data.update(
            {"fraction": record.fraction, "eta_seconds": record.eta_seconds, "phase": record.phase}
        )
        loop.published_at = now
        loop.published_fraction = record.fraction
        loop.published_phase = record.phase
        self._publish(bus, record, ev.WATCH_PROGRESS, text, data)

    def _stalled(
        self, record: WatchRecord, bus: ev.EventBus, loop: _Loop, source: WatchSource, now: float
    ) -> None:
        silent = now - loop.last_activity
        text = f"No new output for {_duration(silent)}" + self._where(record)
        if loop.failure:
            text += f" Reading it is failing: {loop.failure}."
        elif source.note:
            text += f" Note: {source.note}."
        data = {
            "fraction": record.fraction,
            "silent_seconds": round(silent),
            "last_line": record.tail[-1] if record.tail else "",
            "read_error": loop.failure,
        }
        self._publish(bus, record, ev.WATCH_STALLED, text, data)

    @staticmethod
    def _state(record: WatchRecord) -> str:
        parts = []
        if record.fraction is not None:
            parts.append(f"{record.fraction * 100:.0f}%")
        if record.phase:
            parts.append(record.phase)
        if record.eta_seconds is not None:
            parts.append(f"about {_duration(record.eta_seconds)} left")
        head = ", ".join(parts)
        if record.text and head:
            return f"{head} ({record.text})"
        return head or record.text

    @staticmethod
    def _where(record: WatchRecord) -> str:
        at = f" at {record.fraction * 100:.0f}%" if record.fraction is not None else ""
        last = f" Last line: {record.tail[-1]}" if record.tail else ""
        return f"{at}.{last}"

    def _end(
        self,
        record: WatchRecord,
        bus: ev.EventBus,
        kind: str,
        status: Status,
        text: str,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        record.status = status
        record.ended_at = self._clock()
        record.final = self._publish(bus, record, kind, text, data or {})

    def _publish(
        self,
        bus: ev.EventBus,
        record: WatchRecord,
        kind: str,
        text: str,
        data: Mapping[str, Any],
    ) -> ev.Event:
        event = ev.Event(
            kind, record.thread_id, record.id, label=record.label, text=text, data=data
        )
        bus.publish(event)
        return event

    def list(self, thread_id: str) -> builtins.list[WatchRecord]:
        """This thread's watches, running or ended, oldest first."""
        return [r for r in self._records.values() if r.thread_id == thread_id]


async def _beat(on_beat: Beat | None, record: WatchRecord) -> None:
    if on_beat is None:
        return
    try:
        result = on_beat(record)
        if inspect.isawaitable(result):
            await result
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 - a missed beat is retried next poll
        _LOGGER.warning("[harness] beat for %s failed: %s", record.id, type(error).__name__)


# -- surviving a restart ----------------------------------------------------------------------------

#: The store namespace each watch keeps its heartbeat record in, beside the helpers' ledger.
WATCH_LEDGER = ("background_watches",)
#: A watch a restart cut off can be resumed for this long after it was reported.
RESUMABLE_SECONDS = 24 * 3600.0

#: Called by `WatchLedger.sweep` with each record it found, before it publishes the record's event,
#: so the host can say where to wake that thread's lead.
OnFoundWatch = Callable[[str, dict[str, Any]], Awaitable[None]]


class WatchLedger:
    """Each watch's record in the deployment store, so a restart loses neither a watch nor its end.

    `beat(store, extra)` is a watch's `on_beat`. It writes the record every `heartbeat_seconds`
    while the watch runs: what it reads and how (`extra`, enough for the host to start it again
    under the same id), where it stands, and the host's wake data. After the watch ends the record
    stays, refreshed, until the lead has heard the end (`delivered`, an `Inbox.on_delivered`
    callback); a watch the lead stopped drops it at once.

    `sweep` handles what a restart left behind, for records no live watch holds whose heartbeat is
    older than `stale_seconds`: an end whose notice was lost is published again, and a watch the
    restart cut off is published as `TASK_INTERRUPTED` (marked `data["watch"]`) and kept, marked
    reported, so `resumable` finds it for `resumable_seconds`.
    """

    def __init__(
        self,
        watches: WatchRunner,
        *,
        clock: Callable[[], float] = time.time,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
        stale_seconds: float = STALE_SECONDS,
        resumable_seconds: float = RESUMABLE_SECONDS,
    ) -> None:
        self.watches = watches
        self._clock = clock
        self._heartbeat = heartbeat_seconds
        self._stale = stale_seconds
        self._resumable = resumable_seconds
        #: Ended watches whose end the lead has not heard: their records stay, refreshed.
        self._unheard: dict[str, tuple[Any, WatchRecord, dict[str, Any]]] = {}
        #: Ends the lead heard before their record was written: watch id -> its final event id.
        self._heard: dict[str, str] = {}
        self._refresh: asyncio.Task[None] | None = None

    def value(self, record: WatchRecord, extra: Mapping[str, Any]) -> dict[str, Any]:
        """The record as stored."""
        return {
            **record.meta,
            **extra,
            "thread_id": record.thread_id,
            "label": record.label,
            "status": record.status,
            "fraction": record.fraction,
            "started_at": record.started_at,
            "alive_at": self._clock(),
            "final": record.final.to_value() if record.final is not None else None,
        }

    async def _put(self, store: Any, record: WatchRecord, extra: Mapping[str, Any]) -> None:
        try:
            await store.aput(WATCH_LEDGER, record.id, self.value(record, extra))
        except Exception as error:  # noqa: BLE001 - a missed beat is retried next time
            _LOGGER.warning("[harness] record for %s failed: %s", record.id, type(error).__name__)

    async def _drop(self, store: Any, watch_id: str) -> None:
        try:
            await store.adelete(WATCH_LEDGER, watch_id)
        except Exception as error:  # noqa: BLE001 - a leftover is swept and reported once more
            _LOGGER.warning("[harness] dropping %s failed: %s", watch_id, type(error).__name__)

    def beat(self, store: Any, extra: Mapping[str, Any]) -> Beat:
        """A watch's `on_beat` that keeps its record in `store` (class doc)."""
        last = -math.inf
        kept = dict(extra)

        async def beat(record: WatchRecord) -> None:
            nonlocal last
            if store is None:
                return
            if record.status == "watching":
                if self._clock() - last >= self._heartbeat:
                    last = self._clock()
                    await self._put(store, record, kept)
            elif record.status == "cancelled":
                self._unheard.pop(record.id, None)
                await self._drop(store, record.id)
            elif record.final is not None and self._heard.get(record.id) == record.final.id:
                self._heard.pop(record.id, None)
                await self._drop(store, record.id)
            else:
                self._unheard[record.id] = (store, record, kept)
                await self._put(store, record, kept)
                if record.id in self._unheard:
                    self._ensure_refresh()
                else:  # heard while its record was being written
                    await self._drop(store, record.id)

        return beat

    def _ensure_refresh(self) -> None:
        if self._refresh is None or self._refresh.done():
            self._refresh = asyncio.get_running_loop().create_task(
                self._refresh_unheard(), name="watch records"
            )

    async def _refresh_unheard(self) -> None:
        while self._unheard:
            await asyncio.sleep(self._heartbeat)
            for watch_id, (store, record, extra) in builtins.list(self._unheard.items()):
                if watch_id not in self._unheard:
                    continue
                await self._put(store, record, extra)
                if watch_id not in self._unheard:  # heard while it was being refreshed
                    await self._drop(store, watch_id)

    async def delivered(self, batch: Sequence[ev.Event]) -> None:
        """Once the lead has heard how a watch ended, its record goes."""
        for event in batch:
            held = self._unheard.pop(event.source, None)
            if held is not None and held[1].final is not None and held[1].final.id == event.id:
                await self._drop(held[0], event.source)
                continue
            if held is not None:  # not its end: keep waiting for that
                self._unheard[event.source] = held
            record = self.watches.get(event.source)
            if record is not None and record.final is not None and record.final.id == event.id:
                self._heard[event.source] = event.id
                for gone in [w for w in self._heard if self.watches.get(w) is None]:
                    del self._heard[gone]

    async def sweep(
        self,
        store: Any,
        *,
        on_found: OnFoundWatch | None = None,
        bus: ev.EventBus | None = None,
        now: float | None = None,
    ) -> int:
        """Publish what a restart left behind (class doc) and return how many records it found.
        A reported record is told once, and deleted once it is past `resumable_seconds`."""
        now = self._clock() if now is None else now
        found = 0
        for item in await store.asearch(WATCH_LEDGER, limit=200):
            value = dict(item.value or {})
            if value.get("reported_at") is not None:
                if now - float(value["reported_at"]) > self._resumable:
                    await store.adelete(WATCH_LEDGER, item.key)
                continue
            record = self.watches.get(item.key)
            held = record is not None and (record.status == "watching" or item.key in self._unheard)
            if held or now - float(value.get("alive_at") or 0) < self._stale:
                continue
            if on_found is not None:
                await on_found(item.key, value)
            final = value.get("final")
            if isinstance(final, Mapping):
                await store.adelete(WATCH_LEDGER, item.key)
                event = ev.Event.from_value(final)
            else:
                await store.aput(
                    WATCH_LEDGER, item.key, {**value, "status": "interrupted", "reported_at": now}
                )
                event = interrupted_event(item.key, value)
            (bus or ev.BUS).publish(event)
            found += 1
        return found

    async def resumable(
        self, store: Any, watch_id: str, thread_id: str, *, now: float | None = None
    ) -> dict[str, Any] | None:
        """The record of a watch a restart cut off on this thread, for the host to watch it again
        under the same id; None when there is nothing to resume."""
        if store is None:
            return None
        item = await store.aget(WATCH_LEDGER, watch_id)
        value = dict(item.value or {}) if item is not None else {}
        reported = value.get("reported_at")
        if value.get("thread_id") != thread_id or reported is None:
            return None
        now = self._clock() if now is None else now
        return value if now - float(reported) <= self._resumable else None

    def stop(self) -> None:
        """Stop refreshing records and forget what is unheard (tests, shutdown)."""
        if self._refresh is not None and not self._refresh.done():
            self._refresh.cancel()
        self._unheard.clear()
        self._heard.clear()


def interrupted_event(watch_id: str, value: Mapping[str, Any]) -> ev.Event:
    """What the lead hears about a watch a restart cut off: `task.interrupted`, as for a helper or
    a pipeline, marked `data["watch"]`."""
    fraction = value.get("fraction")
    at = f" at {float(fraction) * 100:.0f}%" if isinstance(fraction, int | float) else ""
    log = str(value.get("log_path") or value.get("path") or "")
    job = bool(value.get("command"))
    where = f" The job itself may still be running: its log is {log}." if log else ""
    text = (
        f"The watch stopped{at} when the server restarted.{where} resume_task('{watch_id}') "
        f"watches it again, re-reading the log{' and the exit code' if job else ''}, so a job that "
        "ended meanwhile says how. Nothing read the sandbox while the server was down; a sandbox "
        "that stops when idle may have stopped the job with it."
    )
    return ev.Event(
        ev.TASK_INTERRUPTED,
        str(value.get("thread_id") or ""),
        watch_id,
        label=str(value.get("label") or watch_id),
        text=text,
        data={
            "watch": True,
            "fraction": fraction,
            "started_at": value.get("started_at"),
            "finished_at": value.get("alive_at"),
        },
    )
