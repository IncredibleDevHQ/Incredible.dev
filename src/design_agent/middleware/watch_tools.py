"""Watches and render jobs for the lead: `harness.watch` and `harness.offload`, bound to the
thread's sandbox, the background services and the store.

- **`watch_progress`** watches a log or status file in the thread's sandbox and returns a watch id
  at once.
- **`start_render_job`** runs a command detached in the sandbox (`setsid nohup`, output in a log,
  exit code beside it) and watches it until it exits.
- **`stop_watch`** stops one; `cancel_task` does the same for a watch id, and `check_tasks` and
  every notice list running watches.

A watch's events go on the bus; the inbox wakes the lead for a finish, a failure or a stall. A
watch loop outlives the tool call that started it, so `RuntimeSandboxExec` keeps a detached copy
of that call's runtime and resolves the thread's sandbox for every command. Its reads also keep an
idle sandbox from stopping while a render runs. Each watch keeps a heartbeat record
(`harness.watch.WatchLedger`), so a restart reports a cut-off watch as interrupted, and
`resume_task` watches it again under the same id for 24 hours.
"""

from __future__ import annotations

import asyncio
import logging
import posixpath
import re
import uuid
from collections.abc import Coroutine
from typing import Any, Literal

from langchain.agents.middleware import AgentMiddleware
from langchain.tools import ToolRuntime
from langchain_core.runnables.config import var_child_runnable_config
from langchain_core.tools import BaseTool, StructuredTool

from design_agent.harness import notices
from design_agent.harness.offload import OffloadRunner, SandboxDetachedRender
from design_agent.harness.protocols import ExecResult, WakeTarget
from design_agent.harness.tasks import minutes
from design_agent.harness.watch import (
    SandboxFileSource,
    SandboxJsonSource,
    WatchLedger,
    WatchParser,
    WatchRunner,
    WatchSource,
    parser_for,
)
from design_agent.middleware.background import (
    CANCELLERS,
    DESCRIBERS,
    RESUMERS,
    BackgroundServices,
    detached_config,
)
from design_agent.tools.files import BackendFor

_LOGGER = logging.getLogger(__name__)

POLL_SECONDS = 15.0
STALL_MINUTES = 5.0
RENDER_LOGS = "/workspace/.renders"

#: Every watch and outside job this process runs: a watch outlives the call and the graph that
#: started it.
WATCHES = WatchRunner()
OFFLOAD = OffloadRunner(WATCHES)
LEDGER = WatchLedger(WATCHES)

Kind = Literal["hyperframes", "ffmpeg", "json", "regex", "heartbeat"]
LogKind = Literal["hyperframes", "ffmpeg", "regex", "heartbeat"]


class RuntimeSandboxExec:
    """`harness.protocols.SandboxExec` over the thread's sandbox, from a tool call's runtime."""

    def __init__(self, runtime: Any, backend_for: BackendFor) -> None:
        self.runtime: ToolRuntime[Any, Any] = ToolRuntime(
            state={},
            context=runtime.context,
            config=detached_config(dict(runtime.config or {})),
            stream_writer=lambda *_args, **_kwargs: None,
            tool_call_id=None,
            store=runtime.store,
        )
        self._backend_for = backend_for
        if backend_for(runtime) is None:
            raise LookupError("no sandbox in this run")
        self._origin = runtime

    async def execute(self, command: str, *, timeout: int | None = None) -> ExecResult:
        token = var_child_runnable_config.set(self.runtime.config)
        try:
            backend: Any = self._backend_for(self._origin)
            response = await backend.aexecute(command, timeout=timeout)
        finally:
            var_child_runnable_config.reset(token)
        output = getattr(response, "output", "")
        return ExecResult(
            output=output if isinstance(output, str) else str(output or ""),
            exit_code=getattr(response, "exit_code", None),
        )


def _path(path: str) -> str | None:
    raw = path.strip()
    if not raw or "\x00" in raw:
        return None
    return posixpath.normpath(raw if raw.startswith("/") else f"/workspace/{raw}")


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40] or "job"


def _thread_id(runtime: Any) -> str:
    return str(
        ((getattr(runtime, "config", None) or {}).get("configurable") or {}).get("thread_id") or ""
    )


_SPAWNED: set[asyncio.Task[Any]] = set()


def _spawn(work: Coroutine[Any, Any, Any], name: str) -> None:
    task = asyncio.get_running_loop().create_task(work, name=name)
    _SPAWNED.add(task)
    task.add_done_callback(_SPAWNED.discard)


def stop(watch_id: str, thread_id: str) -> str | None:
    """Stop a watch on this thread, and the job it runs if `start_render_job` started one. None
    when the id is not a watch of this thread (so `cancel_task` asks the next canceller)."""
    record = WATCHES.get(watch_id)
    if record is None or record.thread_id != thread_id:
        return None
    if OFFLOAD.job(watch_id) is None:
        if not WATCHES.cancel(watch_id):
            return f"{watch_id} already ended ({record.status})."
        return f"Stopped watching {watch_id} ({record.label}); the job itself keeps running."
    if record.status in ("done", "error"):
        return f"{watch_id} already ended ({record.status})."
    WATCHES.cancel(watch_id)
    _spawn(OFFLOAD.cancel(watch_id), f"stop {watch_id}")
    return f"Stopped {watch_id} ({record.label}) and the command it was running."


def describe(watch_id: str, thread_id: str) -> str | None:
    record = WATCHES.get(watch_id)
    if record is None or record.thread_id != thread_id:
        return None
    return record.describe()


if stop not in CANCELLERS:
    CANCELLERS.append(stop)
if describe not in DESCRIBERS:
    DESCRIBERS.append(describe)
if WATCHES.running_lines not in notices.RUNNING_PROVIDERS:
    notices.RUNNING_PROVIDERS.append(WATCHES.running_lines)


class WatchToolsMiddleware(AgentMiddleware[Any, Any, Any]):
    """`watch_progress`, `start_render_job` and `stop_watch` for the lead (module doc)."""

    def __init__(self, services: BackgroundServices, backend_for: BackendFor) -> None:
        super().__init__()
        self.services = services
        self._backend_for = backend_for
        services.inbox.on_delivered(LEDGER.delivered)
        services.sweepers.append(self._sweep)
        RESUMERS[:] = [
            r
            for r in RESUMERS
            if not isinstance(getattr(r, "__self__", None), WatchToolsMiddleware)
        ]
        RESUMERS.append(self._resume)
        self.tools = self._build_tools()

    @property
    def name(self) -> str:
        return "DesignAgentWatchTools"

    async def _sweep(self, store: Any) -> int:
        async def on_found(_key: str, value: dict[str, Any]) -> None:
            thread_id = str(value.get("thread_id") or "")
            if thread_id and self.services.inbox.box(thread_id) is None:
                self.services.inbox.set_target(
                    thread_id, WakeTarget(thread_id, channel=value.get("wake"))
                )

        return await LEDGER.sweep(store, on_found=on_found)

    def _build_tools(self) -> list[BaseTool]:
        middleware = self

        async def watch_progress(
            path: str,
            label: str,
            runtime: ToolRuntime,
            kind: Kind = "heartbeat",
            stall_minutes: float = STALL_MINUTES,
            total_frames: int = 0,
            duration_seconds: float = 0,
            progress_regex: str = "",
            error_regex: str = "",
            done_regex: str = "",
            timeout_minutes: float = 0,
        ) -> str:
            """Watch a log or status file in this thread's computer, and hear when the job ends.

            For long work you started yourself. Returns a watch id at once; you are woken when
            the job finishes, fails, or shows nothing new for `stall_minutes`. Watching only reads
            the file, so stopping the watch leaves the job running; for a command not yet started,
            use start_render_job, which also knows its exit code.

            `kind`: `hyperframes` (HyperFrames render output with its progress lines), `ffmpeg`
            (`-progress` output or its stats line; pass `total_frames` or `duration_seconds`),
            `json` (a status file such as run.json: status, step, progress or fraction, eta),
            `regex` (`progress_regex` with groups done/total or a percent), or `heartbeat` (only
            that it is alive). `done_regex` adds a line that means done; `error_regex` replaces the
            lines that mean failure. `timeout_minutes` above 0 ends the watch after that long.
            """
            return await middleware.watch(
                runtime,
                path=path,
                label=label,
                kind=kind,
                stall_minutes=stall_minutes,
                total_frames=total_frames,
                duration_seconds=duration_seconds,
                progress_regex=progress_regex,
                error_regex=error_regex,
                done_regex=done_regex,
                timeout_minutes=timeout_minutes,
            )

        async def start_render_job(
            command: str,
            label: str,
            runtime: ToolRuntime,
            log_path: str = "",
            kind: LogKind = "hyperframes",
            workdir: str = "",
            stall_minutes: float = STALL_MINUTES,
            total_frames: int = 0,
            duration_seconds: float = 0,
            progress_regex: str = "",
        ) -> str:
            """Run a long command detached in this thread's computer and watch it until it exits.

            For renders and encodes that take minutes. It runs in `workdir` (default
            /workspace), outlives your turn, writes its output to `log_path` (default
            /workspace/.renders/<label>-<id>.log) and its exit code to `<log_path>.exit`. Returns
            an id at once; you are woken when it exits (with the end of its log on failure) or
            shows nothing new for `stall_minutes`. Progress is read from the log as `kind`.
            cancel_task with the id stops the command and the watch.
            """
            return await middleware.start_job(
                runtime,
                command=command,
                label=label,
                log_path=log_path,
                kind=kind,
                workdir=workdir,
                stall_minutes=stall_minutes,
                total_frames=total_frames,
                duration_seconds=duration_seconds,
                progress_regex=progress_regex,
            )

        async def stop_watch(watch_id: str, runtime: ToolRuntime) -> str:
            """Stop a watch by its id. A watch on a file only stops reading it; a command started
            with start_render_job is stopped too. Stopping one doesn't wake you."""
            return (
                stop(watch_id.strip(), _thread_id(runtime))
                or f"No watch {watch_id} on this thread."
            )

        return [
            StructuredTool.from_function(coroutine=f, name=f.__name__)
            for f in (watch_progress, start_render_job, stop_watch)
        ]

    async def _wake_data(self, runtime: Any) -> Any:
        target = await self.services.attach(runtime)
        return target.channel if target is not None else None

    async def _resume(self, watch_id: str, runtime: Any) -> str | None:
        """`resume_task` for a watch a restart cut off; None when the id is not a watch here."""
        if not watch_id.startswith("r-"):
            return None
        thread_id = _thread_id(runtime)
        live = WATCHES.get(watch_id)
        if live is not None and live.thread_id == thread_id and live.status == "watching":
            return f"{watch_id} is still being watched; it wakes you when the job ends."
        value = await LEDGER.resumable(getattr(runtime, "store", None), watch_id, thread_id)
        if value is None:
            if live is not None and live.thread_id == thread_id:
                return f"{watch_id} already ended ({live.status}); there is nothing to resume."
            return None
        common: dict[str, Any] = {
            "label": str(value.get("label") or ""),
            "kind": str(value.get("kind") or "heartbeat"),
            "stall_minutes": float(value.get("stall_minutes") or STALL_MINUTES),
            "total_frames": int(value.get("total_frames") or 0),
            "duration_seconds": float(value.get("duration_seconds") or 0),
            "progress_regex": str(value.get("progress_regex") or ""),
            "watch_id": watch_id,
        }
        if value.get("command"):
            pid = str(value.get("job_id") or "")
            return await self.start_job(
                runtime,
                command=str(value["command"]),
                log_path=str(value.get("log_path") or ""),
                workdir=str(value.get("workdir") or ""),
                attach=True,
                pid=int(pid) if pid.isdigit() else None,
                **common,
            )
        return await self.watch(
            runtime,
            path=str(value.get("path") or ""),
            error_regex=str(value.get("error_regex") or ""),
            done_regex=str(value.get("done_regex") or ""),
            timeout_minutes=float(value.get("timeout_minutes") or 0),
            **common,
        )

    async def watch(
        self,
        runtime: Any,
        *,
        path: str,
        label: str,
        kind: str,
        stall_minutes: float,
        total_frames: int,
        duration_seconds: float,
        progress_regex: str,
        error_regex: str,
        done_regex: str,
        timeout_minutes: float,
        watch_id: str | None = None,
    ) -> str:
        thread_id = _thread_id(runtime)
        if not thread_id:
            return "A watch needs a thread."
        target = _path(path)
        if target is None:
            return "Pass the path of a file in this thread's computer (relative paths are under /workspace)."
        try:
            sandbox = RuntimeSandboxExec(runtime, self._backend_for)
            parser: WatchParser = parser_for(
                kind,
                total_frames=total_frames,
                duration_seconds=duration_seconds,
                progress_regex=progress_regex,
                error_regex=error_regex,
                done_regex=done_regex,
            )
            source: WatchSource = (
                SandboxJsonSource(sandbox, target)
                if kind == "json"
                else SandboxFileSource(sandbox, target)
            )
        except LookupError:
            return "There is no sandbox in this run, so nothing to watch."
        except (re.error, ValueError) as error:
            return f"Nothing started: {error}."
        label = label.strip() or posixpath.basename(target)
        stall = (stall_minutes if stall_minutes > 0 else STALL_MINUTES) * 60
        extra = {
            "kind": kind,
            "path": target,
            "stall_minutes": stall_minutes,
            "total_frames": total_frames,
            "duration_seconds": duration_seconds,
            "progress_regex": progress_regex,
            "error_regex": error_regex,
            "done_regex": done_regex,
            "timeout_minutes": timeout_minutes,
            "wake": await self._wake_data(runtime),
        }
        watch_id = WATCHES.start(
            thread_id,
            label=label,
            source=source,
            parser=parser,
            poll_seconds=POLL_SECONDS,
            stall_seconds=stall,
            timeout_seconds=timeout_minutes * 60 if timeout_minutes > 0 else None,
            on_beat=LEDGER.beat(runtime.store, extra),
            meta={"kind": kind, "path": target},
            watch_id=watch_id,
        )
        return (
            f"Watching {target} as {watch_id} ({label}, read as {kind}). You are woken when it "
            f"finishes, fails or shows nothing new for {minutes(stall)}. cancel_task('{watch_id}') "
            "stops the watch; the job keeps running."
        )

    async def start_job(
        self,
        runtime: Any,
        *,
        command: str,
        label: str,
        log_path: str,
        kind: str,
        workdir: str,
        stall_minutes: float,
        total_frames: int,
        duration_seconds: float,
        progress_regex: str,
        watch_id: str | None = None,
        attach: bool = False,
        pid: int | None = None,
    ) -> str:
        """Start the command detached and watch it; with `attach`, watch one already running."""
        thread_id = _thread_id(runtime)
        if not thread_id:
            return "A render job needs a thread."
        if not command.strip():
            return "Pass the command to run."
        label = label.strip() or command.strip().split()[0]
        log = (
            _path(log_path) if log_path.strip() else None
        ) or f"{RENDER_LOGS}/{_slug(label)}-{uuid.uuid4().hex[:6]}.log"
        folder = (_path(workdir) if workdir.strip() else None) or "/workspace"
        try:
            sandbox = RuntimeSandboxExec(runtime, self._backend_for)
            parser = parser_for(
                kind,
                total_frames=total_frames,
                duration_seconds=duration_seconds,
                progress_regex=progress_regex,
            )
        except LookupError:
            return "There is no sandbox in this run, so nothing started."
        except (re.error, ValueError) as error:
            return f"Nothing started: {error}."
        job = SandboxDetachedRender(sandbox, command, log_path=log, workdir=folder, parser=parser)
        stall = (stall_minutes if stall_minutes > 0 else STALL_MINUTES) * 60
        extra = {
            "kind": kind,
            "log_path": log,
            "workdir": folder,
            "command": command[:2000],
            "stall_minutes": stall_minutes,
            "total_frames": total_frames,
            "duration_seconds": duration_seconds,
            "progress_regex": progress_regex,
            "wake": await self._wake_data(runtime),
        }
        watching: dict[str, Any] = {
            "label": label,
            "poll_seconds": POLL_SECONDS,
            "stall_seconds": stall,
            "on_beat": LEDGER.beat(runtime.store, extra),
            "meta": {"kind": kind, "log_path": log, "workdir": folder},
        }
        if attach:
            job.pid = pid
            watch_id = OFFLOAD.attach(
                thread_id, job, job_id=str(pid or ""), watch_id=watch_id, **watching
            )
            return (
                f"Watching {watch_id} ({label}) again: its log {log} and its exit code in {log}.exit. "
                f"You are woken when it exits (at once if it already has) or shows nothing new for "
                f"{minutes(stall)}. cancel_task('{watch_id}') stops it."
            )
        try:
            watch_id = await OFFLOAD.start(thread_id, job, **watching)
        except Exception as error:  # noqa: BLE001 - told to the lead, never raised
            return f"The command did not start: {str(error)[:500]}"
        return (
            f"Started {watch_id} ({label}): the command runs detached in {folder} (pid {job.pid}), "
            f"its output in {log} and its exit code in {log}.exit. You are woken when it exits, "
            f"with the end of its log if it failed, or when it shows nothing new for "
            f"{minutes(stall)}. cancel_task('{watch_id}') stops it."
        )
