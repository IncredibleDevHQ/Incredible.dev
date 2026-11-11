"""Research on the person's own computer: a question about one of their repositories, answered by
a coding agent they already use (Claude Code, Codex or Kimi Code), signed in as they are.

Each answer runs that agent's CLI in the repository, read-only: Claude Code in plan mode with its
editing tools off, Codex in its read-only sandbox, Kimi Code under a profile that can only read
(its one-shot mode writes files without asking otherwise). The CLI gets none of the house's own
environment: no API keys or base URLs, and none of the session variables of whatever launched the
house, so it runs as the person's own install does, on their own plan. It streams JSON lines, and
`parse` turns each into what the canvas shows: a step ("Reading src/session.go"), a note on the
way, the answer, or the session a follow-up resumes and a branch forks.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import signal
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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
#: What a CLI keeps of the house's environment: enough to find itself and its sign-in.
KEPT_ENV = ("HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")
#: Where the CLIs' installers put them, ahead of whatever PATH the house was started with.
BIN_DIRS = ("~/.local/bin", "~/.kimi-code/bin", "/opt/homebrew/bin", "/usr/local/bin")
#: A research run's limit; a repository question rarely needs more.
RUN_SECONDS = 20 * 60
#: Claude Code's lines carry whole files it read.
LINE_LIMIT = 32 * 1024 * 1024
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
        "claude", "Claude Code", ("claude", "~/.claude/local/claude"), resumes=True, forks=True
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
    """What a run said, as the canvas shows it."""

    kind: Literal["session", "step", "note", "answer", "error"]
    text: str


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


def command(
    harness: Harness,
    binary: str,
    *,
    repo: Path,
    prompt: str,
    session: str,
    profile: Path,
    fork: bool = False,
) -> tuple[list[str], str | None]:
    """The CLI's arguments for one run, and what goes in on stdin (so a prompt that starts with a
    dash is never read as an option). With `fork`, the run continues a copy of `session` under a
    new id and leaves the original as it was."""
    if harness.id == "claude":
        argv = [
            binary,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "plan",
            f"--disallowedTools={CLAUDE_BLOCKED}",
            "--append-system-prompt",
            GUIDE,
        ]
        if session:
            argv += ["--resume", session] + (["--fork-session"] if fork else [])
        return argv, prompt
    if harness.id == "codex":
        if session:
            return [
                binary,
                "exec",
                "fork" if fork else "resume",
                "--json",
                "--skip-git-repo-check",
                "-c",
                'sandbox_mode="read-only"',
                session,
                "-",
            ], prompt
        return [
            binary,
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--cd",
            str(repo),
            "--skip-git-repo-check",
            "-",
        ], f"{GUIDE}\n\n{prompt}"
    return [
        binary,
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
) -> AsyncGenerator[Event, None]:
    """One research run: the CLI in the repository, its stream read as it comes. Closing the
    iterator early (a stop) ends the CLI and anything it started."""
    harness = HARNESSES[harness_id]
    binary = harness.binary()
    if binary is None:
        raise ResearchError(f"{harness.title} isn't installed on this computer.")
    if not repo.is_dir():
        raise ResearchError(f"{repo} isn't on this computer any more.")
    argv, stdin = command(
        harness, binary, repo=repo, prompt=prompt, session=session, profile=profile, fork=fork
    )
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(repo),
        env=clean_env(),
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=LINE_LIMIT,
        start_new_session=True,
    )
    said: list[str] = []
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
                for event in parse(harness_id, line, repo):
                    yield event
            code = await process.wait()
        if code:
            last = next((s for s in reversed(said) if s.strip()), "")
            yield Event("error", last.strip()[:300] or f"{harness.title} stopped (exit {code}).")
    except TimeoutError:
        yield Event("error", f"{harness.title} took longer than {timeout // 60:.0f} minutes.")
    finally:
        _end(process)
        drain.cancel()


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
    """One line of a CLI's JSON stream, as zero or more events."""
    try:
        record = json.loads(line)
    except (ValueError, TypeError):
        return []
    if not isinstance(record, dict):
        return []
    if harness_id == "claude":
        return _claude(record, repo)
    if harness_id == "codex":
        return _codex(record)
    return _kimi(record, repo)


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
        return [Event("error", str(message or record.get("message") or "Codex stopped."))]
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
