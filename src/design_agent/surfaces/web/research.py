"""Research on the person's own computer: a question about one of their repositories, answered by
a coding agent they already use (Claude Code, Codex or Kimi Code), signed in as they are.

Each answer runs that agent's CLI in the repository, read-only: Claude Code in plan mode with its
editing tools off, Codex in its read-only sandbox, Kimi Code under a profile that can only read
(its one-shot mode writes files without asking otherwise). The CLI gets none of the house's own
environment: no API keys or base URLs, and none of the session variables of whatever launched the
house, so it runs as the person's own install does, on their own plan. It streams JSON lines, and
`parse` turns each into what the canvas shows: a step ("Reading src/session.go"), a note on the
way, the answer, or the session a follow-up resumes and a branch forks.

Between two steps a model may think for many minutes, or write one long file. `Watch` reads what
a stream says meanwhile, so the house can tell a run at work from one that has gone quiet: a
`pulse` (the model is thinking, and how much so far; the file or the words it is writing), a
`thought` once a stretch of thinking ends, and a step when the model's service has to be asked
again. Claude Code says all of these as it goes; Codex and Kimi Code tell only of whole steps,
so for them a pulse is a line of any kind.

The same agents write an episode (`episode_workers.py`): there a run is given one folder of its
own and may change files in it and nothing else (`writes`), under a guide of the caller's.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import select
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import IO, Any, Literal

#: How the house asks, whichever agent answers.
GUIDE = (
    "You are researching this repository for a team that makes short videos and posts about it. "
    "Answer the question from what the code and its docs actually say: name the files you read "
    "by their path in the repository (src/model.rs, never a link or a full path on this "
    "computer), quote short passages, and say plainly what you could not confirm. Write the "
    "answer in markdown, a one-line answer first, then a few short sections. Never change "
    "anything."
)
#: Kimi Code's profile for research: it can read the repository and nothing else.
KIMI_PROFILE = f"""---
name: researcher
description: Reads a repository to answer a question about it. Never changes anything.
tools: Read, Glob, Grep
---
{GUIDE}
"""
#: Claude Code's tools a research run may not use, on top of plan mode.
CLAUDE_BLOCKED = "Edit,Write,NotebookEdit,ExitPlanMode"
#: Claude Code's tools when a run writes in its folder: files, and no shell, web or helpers.
CLAUDE_WRITER_TOOLS = "Read,Write,Edit,Glob,Grep"
#: What a CLI keeps of the house's environment: enough to find itself and its sign-in.
KEPT_ENV = ("HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")
#: The variable Kimi Code reads how hard one run thinks from, over its own settings.
KIMI_EFFORT_ENV = "KIMI_MODEL_THINKING_EFFORT"
#: Where the CLIs' installers put them, ahead of whatever PATH the house was started with.
BIN_DIRS = ("~/.local/bin", "~/.kimi-code/bin", "/opt/homebrew/bin", "/usr/local/bin")
#: A research run's limit; a repository question rarely needs more.
RUN_SECONDS = 20 * 60
#: Claude Code's lines carry whole files it read.
LINE_LIMIT = 32 * 1024 * 1024
#: Seconds between two pulses of one run: the studio is told at most this often.
PULSE_EVERY = 1.0
#: How much of a thought's summary is kept, from its end: where the thinking has got to.
THOUGHT_KEPT = 600
#: How much of a tool call's arguments is read for what the call acts on (its file comes first).
CALL_HEAD = 4096
#: Claude Code's option for summaries of its thinking. It is the Agent SDK's own (`thinking.display`
#: there) and not in the CLI's reference, so a CLI that refuses it is run without (`run`).
CLAUDE_THOUGHTS = "--thinking-display"
#: Binaries that refused that option, for as long as the house runs.
_without_thoughts: set[str] = set()
#: Why Claude Code is asking the model's service again, by the error it names.
RETRY_WHY = {
    "rate_limit": "the plan's limit was reached",
    "overloaded": "the model's service is busy",
    "server_error": "the model's service had an error",
    "authentication_failed": "the sign-in was refused",
    "billing_error": "the account's billing stopped it",
}
#: Folders never searched for repositories.
SKIP_DIRS = frozenset({"node_modules", "venv", "dist", "build", "target", "vendor"})


class ResearchError(RuntimeError):
    """A run that could not start: its CLI isn't installed, or the repository is gone."""


@dataclass(frozen=True)
class Harness:
    id: str
    title: str
    #: Where its CLI may be: a name on PATH first, then where its installers put it.
    candidates: tuple[str, ...]
    #: Whether a follow-up resumes the agent's own session; otherwise it starts again, told what
    #: was said (Kimi Code's profile can't be combined with resuming).
    resumes: bool
    #: Whether a branch starts from a copy of its parent's session, knowing everything the parent
    #: read and said while the parent's own stays as it was; otherwise it starts again, told the
    #: answer it branched from.
    forks: bool
    #: Whether its stream says what the model is doing between steps (`Watch`): thinking, and
    #: the file it is writing. From one that does, a long silence means something is wrong;
    #: the others say nothing while they think.
    tells: bool = False

    def binary(self) -> str | None:
        for candidate in self.candidates:
            if "/" not in candidate:
                found = shutil.which(candidate, path=_search_path())
                if found:
                    return found
                continue
            path = Path(candidate).expanduser()
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
        return None


HARNESSES: dict[str, Harness] = {
    "claude": Harness(
        "claude",
        "Claude Code",
        ("claude", "~/.claude/local/claude"),
        resumes=True,
        forks=True,
        tells=True,
    ),
    "codex": Harness(
        "codex",
        "Codex",
        (
            "codex",
            "~/.codex/plugins/.plugin-appserver/codex-cli/bin/codex",
            "/Applications/Codex.app/Contents/Resources/codex",
        ),
        resumes=True,
        forks=True,
    ),
    "kimi": Harness("kimi", "Kimi Code", ("kimi",), resumes=False, forks=False),
}


@dataclass(frozen=True)
class Event:
    """What a run said, as the canvas shows it. A `pulse` is a sign of life between steps: its
    text is what the model is at ("thinking", "writing" its own words, "step" for a tool call it
    is writing, or nothing known), `detail` the newest words of the thought or the step the call
    will be, `amount` how much so far (tokens of thought, characters written). A `thought` is a
    stretch of thinking that ended: its summary where the CLI gives one, the tokens it took and
    how long it lasted."""

    kind: Literal["session", "step", "note", "answer", "error", "pulse", "thought"]
    text: str
    detail: str = ""
    amount: int = 0
    seconds: float = 0.0


#: How a research run is started; tests hand in their own.
Runner = Callable[..., AsyncGenerator[Event, None]]


def _search_path(environ: Mapping[str, str] = os.environ) -> str:
    dirs = [os.path.expanduser(d) for d in BIN_DIRS] + environ.get("PATH", "").split(os.pathsep)
    return os.pathsep.join(dict.fromkeys(d for d in dirs if d))


def clean_env(environ: Mapping[str, str] = os.environ) -> dict[str, str]:
    """The environment a CLI runs in: the person's, minus everything the house carries."""
    env = {key: environ[key] for key in KEPT_ENV if key in environ}
    env["PATH"] = _search_path(environ)
    env["TERM"] = "dumb"
    env["NO_COLOR"] = "1"
    return env


_codex_catalog_lock = threading.Lock()


def codex_model_list() -> tuple[dict[str, Any], ...]:
    """Ask the same local Codex sign-in Studio runs with, without creating a thread or turn."""
    binary = HARNESSES["codex"].binary()
    if binary is None:
        return ()
    with _codex_catalog_lock:
        return _codex_catalog(binary, int(time.monotonic() // 120))


@lru_cache(maxsize=2)
def _codex_catalog(binary: str, window: int) -> tuple[dict[str, Any], ...]:  # noqa: ARG001 - cache window
    argv = [binary, "app-server", "--listen", "stdio://"]
    try:
        with subprocess.Popen(  # noqa: S603 - the known local Codex binary, without a shell
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=clean_env(),
        ) as process:
            try:
                assert process.stdin is not None and process.stdout is not None  # noqa: S101
                return _listed_codex_models(process.stdin, process.stdout)
            finally:
                if process.poll() is None:
                    process.kill()
    except (OSError, ValueError, TimeoutError):
        return ()


def _listed_codex_models(stdin: IO[bytes], stdout: IO[bytes]) -> tuple[dict[str, Any], ...]:
    deadline = time.monotonic() + 5

    def send(message: dict[str, Any]) -> None:
        stdin.write(json.dumps(message).encode() + b"\n")
        stdin.flush()

    def receive(request: int) -> dict[str, Any]:
        pending = b""
        while time.monotonic() < deadline and len(pending) < 2 * 1024 * 1024:
            ready, _, _ = select.select([stdout], [], [], max(0.0, deadline - time.monotonic()))
            if not ready or not (chunk := os.read(stdout.fileno(), 65536)):
                break
            pending += chunk
            while b"\n" in pending:
                line, _, pending = pending.partition(b"\n")
                message = json.loads(line)
                if isinstance(message, dict) and message.get("id") == request:
                    result = message.get("result")
                    if isinstance(result, dict):
                        return result
                    raise ValueError("Codex did not return a model catalog.")
        raise TimeoutError("Codex model catalog did not respond.")

    send(
        {
            "method": "initialize",
            "id": 1,
            "params": {"clientInfo": {"name": "studio", "version": "1.0"}},
        }
    )
    receive(1)
    send({"method": "initialized"})
    send({"method": "model/list", "id": 2, "params": {"includeHidden": False, "limit": 100}})
    rows = receive(2).get("data")
    return tuple(row for row in rows if isinstance(row, dict)) if isinstance(rows, list) else ()


def run_env(
    harness_id: str, effort: str = "", environ: Mapping[str, str] = os.environ
) -> dict[str, str]:
    """The environment of one run: the clean one and, for Kimi Code, the effort asked for. Its
    CLI has no option for how hard a run thinks; it reads this variable over its own settings."""
    env = clean_env(environ)
    if harness_id == "kimi" and effort:
        env[KIMI_EFFORT_ENV] = effort
    return env


def command(
    harness: Harness,
    binary: str,
    *,
    repo: Path,
    prompt: str,
    session: str,
    profile: Path,
    fork: bool = False,
    guide: str = GUIDE,
    writes: bool = False,
    model: str = "",
    effort: str = "",
    watched: bool = False,
    thoughts: bool = False,
) -> tuple[list[str], str | None]:
    """The CLI's arguments for one run, and what goes in on stdin (so a prompt that starts with a
    dash is never read as an option). With `fork`, the run continues a copy of `session` under a
    new id and leaves the original as it was. With `writes`, the run may change files in `repo`
    (its own folder) and still has no shell and no network; `profile` is then Kimi Code's
    writing profile. With `watched`, Claude Code says what its model is doing as it goes, not
    only once a step is whole, and with `thoughts` it sends summaries of its thinking too."""
    if harness.id == "claude":
        argv = [binary, "-p", "--output-format", "stream-json", "--verbose"]
        if watched:
            argv += ["--include-partial-messages"]
        if thoughts:
            argv += [CLAUDE_THOUGHTS, "summarized"]
        if model:
            argv += ["--model", model]
        if effort:
            argv += ["--effort", effort]
        if writes:
            argv += ["--permission-mode", "acceptEdits", "--tools", CLAUDE_WRITER_TOOLS]
        else:
            argv += ["--permission-mode", "plan", f"--disallowedTools={CLAUDE_BLOCKED}"]
        argv += ["--append-system-prompt", guide]
        if session:
            argv += ["--resume", session] + (["--fork-session"] if fork else [])
        return argv, prompt
    if harness.id == "codex":
        selected = (["--model", model] if model else []) + (
            ["-c", f'model_reasoning_effort="{effort}"'] if effort else []
        )
        sandbox = "workspace-write" if writes else "read-only"
        if session:
            return [
                binary,
                "exec",
                "fork" if fork else "resume",
                *selected,
                "--json",
                "--skip-git-repo-check",
                "-c",
                f'sandbox_mode="{sandbox}"',
                session,
                "-",
            ], prompt
        return [
            binary,
            "exec",
            *selected,
            "--json",
            "--sandbox",
            sandbox,
            "--cd",
            str(repo),
            "--skip-git-repo-check",
            "-",
        ], f"{guide}\n\n{prompt}"
    # Kimi Code takes a model by its alias; how hard it thinks is not an option (`run_env`)
    return [
        binary,
        *(["--model", model] if model else []),
        "--agent-file",
        str(profile),
        f"--prompt={prompt}",
        "--output-format",
        "stream-json",
    ], None


async def run(
    harness_id: str,
    *,
    repo: Path,
    prompt: str,
    session: str = "",
    fork: bool = False,
    profile: Path,
    timeout: float = RUN_SECONDS,
    guide: str = GUIDE,
    writes: bool = False,
    model: str = "",
    effort: str = "",
    report_model: Callable[[str, str], None] | None = None,
) -> AsyncGenerator[Event, None]:
    """One run: the CLI in the repository (or, for a run that writes, in its own folder), its
    stream read as it comes, with what it says between its steps (`Watch`). Closing the iterator
    early (a stop) ends the CLI and anything it started."""
    harness = HARNESSES[harness_id]
    binary = harness.binary()
    if binary is None:
        raise ResearchError(f"{harness.title} isn't installed on this computer.")
    if not repo.is_dir():
        raise ResearchError(f"{repo} isn't on this computer any more.")
    while True:
        thoughts = harness.id == "claude" and binary not in _without_thoughts
        argv, stdin = command(
            harness,
            binary,
            repo=repo,
            prompt=prompt,
            session=session,
            profile=profile,
            fork=fork,
            guide=guide,
            writes=writes,
            model=model,
            effort=effort,
            watched=True,
            thoughts=thoughts,
        )
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(repo),
            env=run_env(harness.id, effort),
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=LINE_LIMIT,
            start_new_session=True,
        )
        reported_error = said_anything = False
        said: list[str] = []
        watch = Watch(harness_id, repo)
        drain = asyncio.create_task(_tail(process.stderr, said))
        try:
            if stdin is not None and process.stdin is not None:
                process.stdin.write(stdin.encode())
                await process.stdin.drain()
                process.stdin.close()
            if process.stdout is None:
                raise ResearchError(f"{harness.title} gave nothing to read.")
            async with asyncio.timeout(timeout):
                while True:
                    try:
                        line = await process.stdout.readline()
                    except ValueError:  # one line over the limit: skip it, keep reading
                        continue
                    if not line:
                        break
                    record = _record(line)
                    if record is None:
                        continue
                    if report_model and record.get("type") in (
                        "system",
                        "turn.started",
                        "session_meta",
                    ):
                        metadata = record.get("payload", record)
                        if isinstance(metadata, dict) and isinstance(metadata.get("model"), str):
                            used_effort = metadata.get("reasoning_effort") or metadata.get("effort")
                            report_model(
                                metadata["model"][:100],
                                used_effort[:16] if isinstance(used_effort, str) else "",
                            )
                    # what the line says of the model at work first, then what it carries; a
                    # line that carries something is its own sign of life
                    told = _events(harness_id, record, repo)
                    signs = [
                        e for e in watch.read(record) if e.text or e.kind != "pulse" or not told
                    ]
                    for event in (*signs, *told):
                        if event.kind == "error":
                            reported_error = True
                        said_anything = True
                        yield event
                code = await process.wait()
            if code and not reported_error:
                # the last of what it wrote to stderr says why
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(drain), 1.0)
                if thoughts and not said_anything and _refused(said, CLAUDE_THOUGHTS):
                    _without_thoughts.add(binary)
                    continue  # an older CLI: the same run, without summaries of its thinking
                last = next((s for s in reversed(said) if s.strip()), "")
                yield Event(
                    "error", last.strip()[:300] or f"{harness.title} stopped (exit {code})."
                )
        except TimeoutError:
            yield Event("error", f"{harness.title} took longer than {timeout // 60:.0f} minutes.")
        finally:
            _end(process)
            drain.cancel()
        return


def _refused(said: Sequence[str], option: str) -> bool:
    """Whether a CLI ended at once because it does not know one of the options it was given."""
    return any("unknown option" in line and option in line for line in said)


async def _tail(stream: asyncio.StreamReader | None, said: list[str]) -> None:
    """Keep the last lines a CLI wrote to stderr, so a pipe that fills never blocks it."""
    if stream is None:
        return
    with contextlib.suppress(ValueError):
        async for raw in stream:
            said.append(raw.decode(errors="replace"))
            del said[:-20]


def _end(process: asyncio.subprocess.Process) -> None:
    """End a CLI and everything it started (its own process group), firmly if it lingers."""
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGTERM)

    def force() -> None:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGKILL)

    with contextlib.suppress(RuntimeError):
        asyncio.get_running_loop().call_later(3.0, force)


# -- reading each CLI's stream --------------------------------------------------------------


def parse(harness_id: str, line: bytes | str, repo: Path) -> list[Event]:
    """One line of a CLI's JSON stream, as zero or more events: its steps, notes and answer.
    What it says between steps is `Watch`'s to read."""
    record = _record(line)
    return _events(harness_id, record, repo) if record is not None else []


def _record(line: bytes | str) -> dict[str, Any] | None:
    try:
        record = json.loads(line)
    except (ValueError, TypeError):
        return None
    return record if isinstance(record, dict) else None


def _events(harness_id: str, record: Mapping[str, Any], repo: Path) -> list[Event]:
    if harness_id == "claude":
        return _claude(record, repo)
    if harness_id == "codex":
        return _codex(record)
    return _kimi(record, repo)


class Watch:
    """One run's stream, read for what the model is doing between its steps.

    Claude Code sends partial messages: a block of thinking, of its own words or of a tool call
    opens, grows and closes. While one is open the watch gives a `pulse` (at most one each
    `PULSE_EVERY` seconds, and one at once when what the model is at changes): thinking with the
    tokens so far and the newest words of its summary, writing with the characters so far, or the
    step a tool call will be ("Writing plan.json") with how much of it is written. A block of
    thinking that closes is a `thought`, and a request the CLI has to make again is a step that
    says why. Codex tells of a stretch of reasoning once it is whole (a `thought`); every other
    line, from any CLI, is a pulse that says only that something was heard."""

    def __init__(
        self, harness_id: str, repo: Path, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.harness = harness_id
        self.repo = repo
        self.clock = clock
        self._pulsed = float("-inf")
        self._said = ""
        #: the block the model is writing (thinking, text, tool_use), when it opened, and so far
        #: its tokens or characters, the end of a thought's summary, and a tool call's start
        self._block = ""
        self._opened = 0.0
        self._amount = 0
        self._summary = ""
        self._tool = ""
        self._head = ""

    def read(self, record: Mapping[str, Any]) -> list[Event]:
        if self.harness == "claude":
            return self._claude(record)
        if self.harness == "codex":
            item = record.get("item")
            if (
                record.get("type") == "item.completed"
                and isinstance(item, dict)
                and item.get("type") == "reasoning"
            ):
                return [Event("thought", _plain(str(item.get("text") or ""))[-THOUGHT_KEPT:])]
        return self._pulse()

    def _claude(self, record: Mapping[str, Any]) -> list[Event]:
        kind = record.get("type")
        if kind == "system" and record.get("subtype") == "api_retry":
            return [Event("step", _retry(record))]
        if kind == "system" and record.get("subtype") == "thinking_tokens":
            if self._block != "thinking":
                self._open("thinking")
            self._amount = max(self._amount, _count(record.get("estimated_tokens")))
            return self._pulse()
        event = record.get("event") if kind == "stream_event" else None
        if not isinstance(event, dict):
            return self._pulse()
        what = event.get("type")
        if what == "content_block_start":
            block = event.get("content_block")
            block = block if isinstance(block, dict) else {}
            self._open(str(block.get("type") or ""), str(block.get("name") or ""))
            return self._pulse(now=True)
        if what == "content_block_delta":
            delta = event.get("delta")
            delta = delta if isinstance(delta, dict) else {}
            if delta.get("type") == "thinking_delta":
                self._summary = (self._summary + str(delta.get("thinking") or ""))[-THOUGHT_KEPT:]
                self._amount = max(self._amount, _count(delta.get("estimated_tokens")))
            elif delta.get("type") == "text_delta":
                self._amount += len(str(delta.get("text") or ""))
            elif delta.get("type") == "input_json_delta":
                part = str(delta.get("partial_json") or "")
                self._amount += len(part)
                self._head = (self._head + part)[:CALL_HEAD]
            return self._pulse()
        if what == "content_block_stop":
            thought = self._block == "thinking"
            done = Event(
                "thought",
                _plain(self._summary),
                amount=self._amount,
                seconds=round(self.clock() - self._opened, 1),
            )
            self._open("")
            return [done] if thought else self._pulse(now=True)
        return self._pulse()

    def _open(self, block: str, tool: str = "") -> None:
        self._block, self._tool = block, tool
        self._opened = self.clock()
        self._amount, self._summary, self._head = 0, "", ""

    def _pulse(self, *, now: bool = False) -> list[Event]:
        saying = {"thinking": "thinking", "text": "writing", "tool_use": "step"}.get(
            self._block, ""
        )
        at = self.clock()
        if not now and saying == self._said and at - self._pulsed < PULSE_EVERY:
            return []
        self._pulsed, self._said = at, saying
        detail = ""
        if saying == "thinking":
            detail = _plain(self._summary)
        elif saying == "step":
            detail = describe(self._tool, _started(self._head), self.repo)
        return [Event("pulse", saying, detail=detail, amount=self._amount if saying else 0)]


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _plain(text: str) -> str:
    """A model's own words on one line, without the marks it sets headings and stress in."""
    return " ".join(re.sub(r"[*_`#]+", "", text).split())


#: A whole string value near the start of a tool call's arguments, as they are being written.
_ARGUMENT = re.compile(
    r'"(file_path|path|notebook_path|pattern|query|command|url|description)"'
    r'\s*:\s*"((?:[^"\\]|\\.)*)"'
)


def _started(head: str) -> dict[str, str]:
    """What a tool call acts on, read from as much of its arguments as has been written."""
    found: dict[str, str] = {}
    for name, value in _ARGUMENT.findall(head):
        with contextlib.suppress(ValueError):
            found.setdefault(name, json.loads(f'"{value}"'))
    return found


def _retry(record: Mapping[str, Any]) -> str:
    """Claude Code asking the model's service again, as a step that says why and which try."""
    why = RETRY_WHY.get(str(record.get("error") or ""), "the request did not go through")
    tries = ""
    if _count(record.get("attempt")) and _count(record.get("max_retries")):
        tries = f" (try {record['attempt']} of {record['max_retries']})"
    return f"Asking again: {why}{tries}"


def _claude(record: Mapping[str, Any], repo: Path) -> list[Event]:
    kind = record.get("type")
    if kind == "system" and record.get("subtype") == "init" and record.get("session_id"):
        return [Event("session", str(record["session_id"]))]
    if kind == "assistant":
        out: list[Event] = []
        for part in (record.get("message") or {}).get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use":
                out.append(Event("step", describe(str(part.get("name")), part.get("input"), repo)))
            elif part.get("type") == "text" and str(part.get("text") or "").strip():
                out.append(Event("note", str(part["text"]).strip()))
        return out
    if kind == "result":
        text = str(record.get("result") or "").strip()
        if record.get("is_error") or record.get("subtype") != "success":
            return [Event("error", text[:300] or "It stopped before answering.")]
        return [Event("answer", text)] if text else []
    return []


def _codex(record: Mapping[str, Any]) -> list[Event]:
    kind = str(record.get("type") or "")
    if kind == "thread.started" and record.get("thread_id"):
        return [Event("session", str(record["thread_id"]))]
    if kind in ("turn.failed", "error"):
        failure = record.get("error") or {}
        message = failure.get("message") if isinstance(failure, dict) else failure
        reason = str(message or record.get("message") or "Codex stopped.")
        if reason.lstrip().startswith("{"):
            with contextlib.suppress(ValueError):
                body = json.loads(reason)
                error = body.get("error") if isinstance(body, dict) else None
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    reason = error["message"] or reason
        return [Event("error", reason[:300])]
    item = record.get("item") or {}
    if not isinstance(item, dict):
        return []
    what = item.get("type")
    if kind == "item.started" and what == "command_execution":
        return [Event("step", f"Running {_shell(str(item.get('command') or ''))}")]
    if kind == "item.started" and what == "web_search":
        return [Event("step", f"Searching the web for “{_clip(str(item.get('query') or ''))}”")]
    if kind == "item.started" and what == "mcp_tool_call":
        return [Event("step", f"Using {item.get('tool') or 'a tool'}")]
    if kind == "item.completed" and what == "file_change":
        paths = [str(c.get("path") or "") for c in item.get("changes") or [] if isinstance(c, dict)]
        named = ", ".join(Path(p).name for p in paths[:3] if p)
        return [Event("step", f"Writing {named or 'a file'}")]
    if kind == "item.completed" and what == "agent_message":
        text = str(item.get("text") or "").strip()
        return [Event("note", text)] if text else []
    return []


def _kimi(record: Mapping[str, Any], repo: Path) -> list[Event]:
    role = record.get("role")
    if role == "meta":
        if record.get("type") == "session.resume_hint" and record.get("session_id"):
            return [Event("session", str(record["session_id"]))]
        if "error" in str(record.get("type") or ""):
            return [Event("error", str(record.get("content") or "Kimi Code stopped."))]
        return []
    if role != "assistant":
        return []
    out: list[Event] = []
    for call in record.get("tool_calls") or []:
        called = call.get("function") if isinstance(call, dict) else None
        if not isinstance(called, dict):
            continue
        try:
            args = json.loads(called.get("arguments") or "{}")
        except ValueError:
            args = {}
        out.append(Event("step", describe(str(called.get("name")), args, repo)))
    content = record.get("content")
    if isinstance(content, list):
        content = "".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    if isinstance(content, str) and content.strip():
        out.append(Event("note", content.strip()))
    return out


def describe(tool: str, args: Any, repo: Path) -> str:
    """A tool call as a step anyone can read: "Reading src/session.go"."""
    given: Mapping[str, Any] = args if isinstance(args, Mapping) else {}
    name = tool.lower().replace("_", "")
    where = given.get("file_path") or given.get("path") or given.get("notebook_path") or ""
    place = _relative(str(where), repo) if where else ""
    if name in ("read", "readfile", "view", "cat"):
        return f"Reading {place or 'a file'}"
    if name in ("write", "writefile", "create"):
        return f"Writing {place or 'a file'}"
    if name in ("edit", "multiedit", "strreplace", "applypatch"):
        return f"Editing {place or 'a file'}"
    if name in ("grep", "search", "rg"):
        pattern = _clip(str(given.get("pattern") or given.get("query") or ""))
        return f"Searching for “{pattern}”" + (f" in {place}" if place else "")
    if name in ("glob", "ls", "list", "listdir", "find"):
        return f"Listing {given.get('pattern') or place or 'files'}"
    if name in ("bash", "shell", "exec", "run", "runcommand"):
        return f"Running {_shell(str(given.get('command') or ''))}"
    if name == "websearch":
        return f"Searching the web for “{_clip(str(given.get('query') or ''))}”"
    if name in ("webfetch", "fetch"):
        return f"Reading {_clip(str(given.get('url') or 'a page'), 60)}"
    if name in ("task", "agent"):
        return f"Asking a helper: {_clip(str(given.get('description') or 'a side question'), 60)}"
    if name in ("todowrite", "todo"):
        return "Planning its steps"
    return tool


def _relative(path: str, repo: Path) -> str:
    with contextlib.suppress(ValueError):
        return str(Path(path).resolve().relative_to(repo.resolve())) or "."
    return path


def _shell(command: str) -> str:
    """A command as typed, without the shell wrapper a CLI puts around it."""
    wrapped = re.fullmatch(r"\S*sh -l?c (['\"])(.*)\1", command.strip(), re.S)
    return _clip(wrapped.group(2) if wrapped else command, 60)


def _clip(text: str, limit: int = 48) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# -- the repositories on this computer -----------------------------------------------------


@dataclass(frozen=True)
class Repo:
    name: str
    path: Path
    branch: str
    touched: float

    def view(self) -> dict[str, Any]:
        return {"name": self.name, "path": str(self.path), "branch": self.branch}


def find_repos(roots: Sequence[Path], *, depth: int = 2) -> list[Repo]:
    """Every git repository under the roots (a root that is one counts), most recently worked in
    first. Hidden and dependency folders are never searched."""
    found: dict[Path, Repo] = {}

    def visit(folder: Path, level: int) -> None:
        if (folder / ".git").exists():
            resolved = folder.resolve()
            found.setdefault(resolved, _repo(resolved))
            return
        if level >= depth:
            return
        try:
            children = sorted(folder.iterdir())
        except OSError:
            return
        for child in children:
            if child.is_dir() and not child.name.startswith(".") and child.name not in SKIP_DIRS:
                visit(child, level + 1)

    for root in roots:
        if root.expanduser().is_dir():
            visit(root.expanduser(), 0)
    return sorted(found.values(), key=lambda r: -r.touched)


def _repo(path: Path) -> Repo:
    git = path / ".git"
    if git.is_file():  # a worktree: .git names where its own git folder is
        pointer = git.read_text(errors="replace").strip()
        if pointer.startswith("gitdir:"):
            git = (path / pointer.removeprefix("gitdir:").strip()).resolve()
    stamps = [p.stat().st_mtime for p in (git / "index", git / "HEAD") if p.exists()]
    return Repo(path.name, path, branch_of(git), max(stamps, default=0.0))


def repo_root(folder: Path) -> Path | None:
    """The repository a folder is in (the folder itself when it is one)."""
    for candidate in (folder, *folder.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def branch_of(git: Path) -> str:
    """The branch a git folder (or a repository, or a folder in one) is on, or its commit when
    detached."""
    if git.name != ".git" and not (git / "HEAD").is_file():
        root = repo_root(git)
        return _repo(root).branch if root is not None else ""
    try:
        head = (git / "HEAD").read_text(errors="replace").strip()
    except OSError:
        return ""
    if head.startswith("ref:"):
        return head.removeprefix("ref:").strip().removeprefix("refs/heads/")
    return head[:7]
