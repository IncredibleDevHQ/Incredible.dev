"""Outside jobs: work that runs somewhere other than a helper's turn, tracked like a watch.

A render can run detached in the sandbox or on any service with a submit and a status call. To the
lead they should all look the same: a percentage, an ETA, a cost when there is one, and an event
when the job finishes, fails or goes quiet. So an outside job is three calls, `submit`, `poll` and
`cancel` (the `OutsideJob` protocol), and `OffloadRunner` tracks it with the watcher
(`harness.watch`): each poll becomes a small JSON document (a `WatchSource`), read by one parser. A
job therefore publishes the same `WATCH_*` events as a watched log, with the same stall timer, and
the attention rule treats every render alike.

`SandboxDetachedRender` runs a command under `nohup` (and `setsid` when the image has it) in the
thread's sandbox, with its output in a log and its exit code in `<log>.exit`. Progress comes from a
parser reading the log (`harness.watch.parser_for`; `hyperframes` for `hyperframes render`, the
heartbeat parser by default); the exit code is the verdict.

Deep Agents has no outside-job primitive; upstream, this would be a task type beside background
subagents: submit, poll (or a webhook) and cancel, emitting the same events.
"""

from __future__ import annotations

import builtins
import json
import posixpath
import shlex
from collections import deque
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from design_agent.harness import events as ev
from design_agent.harness.protocols import SandboxExec
from design_agent.harness.watch import (
    EXEC_TIMEOUT,
    TAIL_LINES,
    Beat,
    HeartbeatParser,
    SandboxFileSource,
    Update,
    WatchParser,
    WatchRecord,
    WatchRunner,
)

JobState = Literal["queued", "running", "done", "failed", "cancelled"]
ENDED = frozenset({"done", "failed", "cancelled"})


@dataclass(frozen=True)
class JobProgress:
    """Where an outside job stands.

    `output` is what it made (a file path, a URL) once done; `error` why it failed; `cost_usd` what
    it has cost so far when the provider says; `note` its latest status line (a log
    line).
    """

    state: JobState
    fraction: float | None = None
    eta_seconds: float | None = None
    output: str = ""
    error: str = ""
    cost_usd: float | None = None
    note: str = ""


@runtime_checkable
class OutsideJob(Protocol):
    async def submit(self) -> str:
        """Start the job and return its id with the provider (a pid, a render id)."""
        ...

    async def poll(self) -> JobProgress:
        """Where it stands now. Raising counts as a failed read; the watch polls again."""
        ...

    async def cancel(self) -> None:
        """Stop it, as far as the provider allows."""
        ...


class JobSource:
    """An outside job as a `WatchSource`: each read polls it and returns its progress as one JSON
    line when anything changed, so a job that stops moving trips the stall timer like a quiet log.
    It closes once the job has ended."""

    def __init__(self, job: OutsideJob) -> None:
        self.job = job
        self.closed = False
        self.note = ""
        self._last: str | None = None

    async def read(self) -> str:
        progress = await self.job.poll()
        self.closed = progress.state in ENDED
        text = json.dumps(asdict(progress), sort_keys=True)
        if text == self._last:
            return ""
        self._last = text
        return text + "\n"


class JobParser:
    """`JobSource`'s lines as updates: done with its output, failed or cancelled as an error with
    its reason, anything else as progress (the state is the phase, so queued to running shows)."""

    def parse(self, text: str) -> list[Update]:
        if not text.strip():
            return []
        value = json.loads(text)
        state = str(value.get("state") or "running")
        data = {
            key: value[key] for key in ("output", "cost_usd") if value.get(key) not in (None, "")
        }
        note = str(value.get("note") or "")
        if state == "done":
            output = str(value.get("output") or "")
            return [Update("done", 1.0, text=f"Output: {output}" if output else note, data=data)]
        if state in ENDED:
            reason = str(value.get("error") or f"The job was {state}.")
            return [Update("error", text=reason, data=data)]
        return [
            Update(
                "progress",
                fraction=value.get("fraction"),
                eta_seconds=value.get("eta_seconds"),
                text=note,
                phase=state,
                data=data,
            )
        ]


class OffloadRunner:
    """Submits outside jobs and watches them with a `WatchRunner` (module doc)."""

    def __init__(self, watches: WatchRunner | None = None) -> None:
        self.watches = watches or WatchRunner()
        self._jobs: dict[str, OutsideJob] = {}

    async def start(
        self,
        thread_id: str,
        job: OutsideJob,
        *,
        label: str,
        poll_seconds: float = 15.0,
        stall_seconds: float = 300.0,
        timeout_seconds: float | None = None,
        bus: ev.EventBus | None = None,
        on_beat: Beat | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> str:
        """Submit the job, start watching it, and return the watch id. A submit that fails raises,
        so the caller can say so at once."""
        job_id = await job.submit()
        return self.attach(
            thread_id,
            job,
            job_id=job_id,
            label=label,
            poll_seconds=poll_seconds,
            stall_seconds=stall_seconds,
            timeout_seconds=timeout_seconds,
            bus=bus,
            on_beat=on_beat,
            meta=meta,
        )

    def attach(
        self,
        thread_id: str,
        job: OutsideJob,
        *,
        job_id: str,
        label: str,
        poll_seconds: float = 15.0,
        stall_seconds: float = 300.0,
        timeout_seconds: float | None = None,
        bus: ev.EventBus | None = None,
        on_beat: Beat | None = None,
        meta: Mapping[str, Any] | None = None,
        watch_id: str | None = None,
    ) -> str:
        """Watch a job that is already running (submitted earlier, or before a restart), under
        `watch_id` when given. Returns the watch id."""
        for known in [w for w in self._jobs if self.watches.get(w) is None]:
            del self._jobs[known]
        watch_id = self.watches.start(
            thread_id,
            label=label,
            source=JobSource(job),
            parser=JobParser(),
            poll_seconds=poll_seconds,
            stall_seconds=stall_seconds,
            timeout_seconds=timeout_seconds,
            bus=bus,
            on_beat=on_beat,
            meta={**(meta or {}), "job_id": job_id},
            watch_id=watch_id,
        )
        self._jobs[watch_id] = job
        return watch_id

    def job(self, watch_id: str) -> OutsideJob | None:
        return self._jobs.get(watch_id)

    async def cancel(self, watch_id: str) -> bool:
        """Stop watching, and stop the job unless it already finished. False when there is no
        such job."""
        job = self._jobs.get(watch_id)
        if job is None:
            return False
        record = self.watches.get(watch_id)
        self.watches.cancel(watch_id)
        if record is None or record.status not in ("done", "error"):
            await job.cancel()
        return True

    def list(self, thread_id: str) -> builtins.list[WatchRecord]:
        return [r for r in self.watches.list(thread_id) if r.id in self._jobs]


# -- a command detached in the sandbox ---------------------------------------------------------

_SIGNALS = {130: "SIGINT", 137: "SIGKILL, often out of memory", 143: "SIGTERM"}


def exit_text(code: int) -> str:
    signal = _SIGNALS.get(code)
    return f"It exited with code {code}" + (f" ({signal})." if signal else ".")


class SandboxDetachedRender:
    """A long command run detached in the sandbox; its exit code decides done or failed.

    `submit` starts `nohup sh -c '( <command> ); echo $? > <log>.exit' > <log> 2>&1 &` in
    `workdir`, under `setsid` when the image has it so the job gets its own process group (and
    `cancel` stops all of it). The subshell keeps an `exit` inside the command from skipping the
    exit file. Each `poll` reads the new log with `parser` for progress (`HeartbeatParser` by
    default), then looks for the exit file: 0 is done; anything else is failed, with the last
    lines of the log.
    """

    def __init__(
        self,
        exec: SandboxExec,
        command: str,
        *,
        log_path: str,
        workdir: str = "/workspace",
        parser: WatchParser | None = None,
        timeout: int = EXEC_TIMEOUT,
    ) -> None:
        self.command = command
        self.workdir = workdir
        self.log_path = log_path
        self.exit_path = f"{log_path}.exit"
        self.pid: int | None = None
        self._exec = exec
        self._timeout = timeout
        self._log = SandboxFileSource(exec, log_path, timeout=timeout)
        self._parser = parser or HeartbeatParser()
        self._fraction: float | None = None
        self._eta: float | None = None
        self._lines: deque[str] = deque(maxlen=TAIL_LINES)

    def start_command(self) -> str:
        script = f"( {self.command}\n); echo $? > {shlex.quote(self.exit_path)}"
        folder = posixpath.dirname(self.log_path) or "."
        return (
            f"mkdir -p {shlex.quote(folder)} && rm -f {shlex.quote(self.exit_path)} "
            f"&& cd {shlex.quote(self.workdir)} || exit 1\n"
            "S=; command -v setsid >/dev/null 2>&1 && S=setsid\n"
            f"nohup $S sh -c {shlex.quote(script)} > {shlex.quote(self.log_path)} 2>&1 < /dev/null &\n"
            'echo "@@pid $!"'
        )

    async def submit(self) -> str:
        result = await self._exec.execute(self.start_command(), timeout=self._timeout)
        for line in result.output.splitlines():
            if line.startswith("@@pid ") and line[6:].strip().isdigit():
                self.pid = int(line[6:].strip())
                return str(self.pid)
        raise RuntimeError(f"The command did not start: {result.output.strip()[-500:]}")

    async def poll(self) -> JobProgress:
        await self._read_log()
        code = await self._exit_code()
        if code is None:
            return JobProgress("running", self._fraction, self._eta, note=self._last_line())
        await self._read_log()  # what it printed between the read above and its exit
        if code == 0:
            return JobProgress("done", 1.0, note=self._last_line())
        tail = await self._tail()
        return JobProgress(
            "failed",
            self._fraction,
            error=f"{exit_text(code)} Last lines of {self.log_path}:\n{tail}".strip(),
            note=self._last_line(),
        )

    async def cancel(self) -> None:
        if self.pid is None:
            return
        pid = self.pid
        await self._exec.execute(
            f"kill -TERM -- -{pid} 2>/dev/null || "
            f"{{ pkill -TERM -P {pid} 2>/dev/null; kill -TERM {pid} 2>/dev/null; }}; true",
            timeout=self._timeout,
        )

    async def _read_log(self) -> None:
        for update in self._parser.parse(await self._log.read()):
            if update.text:
                self._lines.append(update.text)
            if update.kind == "progress":
                if update.fraction is not None:
                    self._fraction = update.fraction
                self._eta = update.eta_seconds

    async def _exit_code(self) -> int | None:
        path = shlex.quote(self.exit_path)
        result = await self._exec.execute(
            f'if [ -s {path} ]; then echo "@@exit $(cat {path})"; fi', timeout=self._timeout
        )
        for line in result.output.splitlines():
            if line.startswith("@@exit "):
                value = line[7:].strip()
                return int(value) if value.lstrip("-").isdigit() else -1
        return None

    async def _tail(self) -> str:
        result = await self._exec.execute(
            f"tail -n {TAIL_LINES} {shlex.quote(self.log_path)} 2>/dev/null", timeout=self._timeout
        )
        return result.output.strip() or "\n".join(self._lines)

    def _last_line(self) -> str:
        return self._lines[-1] if self._lines else ""
