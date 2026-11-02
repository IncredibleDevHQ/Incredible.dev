"""`start_looks` and `pick_look`: several creative looks in parallel, and the person's pick merged.

The Design Agent side of `harness.branches`. Projects live in `/workspace/projects/<slug>/`, the
sandbox is the thread's own (`runtime.backend`), and helpers are the lead's background helpers
(`middleware/background.py`'s `BackgroundHelpers`). The helper runner and the sandbox reach these
tools through factories the agent wires, so the tools run against fakes in tests.

- `start_looks` copies the project once per direction into `looks/<id>/`, starts one helper per
  look in one wave, and returns at once. Each helper's end wakes the lead as any helper's does.
  When the last one has ended, `LookWatch` publishes `JOB_ATTENTION` with a ping, so the person
  comes to pick: choosing needs a person, since vision-language judges trail people by more than
  30 points on video pairs.
- `pick_look` merges the chosen look into the project after a backup, and records the pick and the
  person's reason as an observation (`harness.learning`), so later jobs see what they chose and why.

A watch lives in this process: after a restart the looks' helpers are reported interrupted like any
helper, and no ping follows. The looks' folders stay on disk, so they can still be picked.
"""

from __future__ import annotations

import logging
import posixpath
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from langchain.agents.middleware import AgentMiddleware
from langchain.tools import ToolRuntime, tool

from design_agent.harness import events as ev
from design_agent.harness.branches import (
    LookResult,
    Looks,
    LooksError,
    LookSpec,
    LookWatch,
    next_ids,
)
from design_agent.harness.learning import ObservationStore
from design_agent.harness.protocols import ExecResult, HelperRunner, SandboxExec
from design_agent.tools.files import BackendFor, WorkspaceError, require_backend
from design_agent.tools.projects import PROJECT_SLUG, PROJECTS_ROOT

_LOGGER = logging.getLogger(__name__)

#: Builds the helper runner for one tool call from its runtime.
RunnerFactory = Callable[[Any], HelperRunner]
#: Builds the sandbox command runner for one tool call from its runtime.
ExecFactory = Callable[[Any], SandboxExec]

#: The skill a pick is recorded under when the lead names none.
DEFAULT_SKILL = "looks"

#: Rounds of looks whose helpers this process is waiting on, by (thread id, project folder).
WATCHES: dict[tuple[str, str], list[LookWatch]] = {}


@dataclass(frozen=True)
class BackendExec:
    """`SandboxExec` over a deepagents sandbox backend's `aexecute`."""

    backend: Any

    async def execute(self, command: str, *, timeout: int | None = None) -> ExecResult:
        try:
            result = await self.backend.aexecute(command, timeout=timeout)
        except Exception:  # noqa: BLE001 - re-raised as the tool's own error, without sandbox detail
            raise WorkspaceError("a sandbox command failed to run.") from None
        return ExecResult(
            output=str(getattr(result, "output", "") or ""),
            exit_code=getattr(result, "exit_code", None),
        )


def sandbox_exec_for(backend_for: BackendFor) -> ExecFactory:
    """The `ExecFactory` over the profile's sandbox accessor: resolved per call, never cached."""

    def factory(runtime: Any) -> SandboxExec:
        backend = require_backend(backend_for, runtime)
        if not callable(getattr(backend, "aexecute", None)):
            raise WorkspaceError("this run's sandbox cannot run commands.")
        return BackendExec(backend)

    return factory


def _thread_id(runtime: Any) -> str:
    configurable = (getattr(runtime, "config", None) or {}).get("configurable") or {}
    if isinstance(configurable, Mapping):
        return str(configurable.get("thread_id") or "")
    return str(getattr(configurable, "thread_id", "") or "")


def _project(slug: str) -> str | None:
    return f"{PROJECTS_ROOT}/{slug}" if PROJECT_SLUG.fullmatch(slug) else None


def _short(text: str, limit: int = 120) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[: limit - 1].rstrip() + "…"


def _running(thread_id: str, project: str) -> dict[str, str]:
    """Looks in this project whose helpers are still running: look id -> task id."""
    key = (thread_id, project)
    live = [watch for watch in WATCHES.get(key, []) if not watch.fired]
    if live:
        WATCHES[key] = live
    else:
        WATCHES.pop(key, None)
    return {look_id: task_id for watch in live for look_id, task_id in watch.pending().items()}


def _picked_from(thread_id: str, project: str, look_id: str) -> None:
    """The person has picked from this look's round: its other helpers still wake the lead as
    they end, and still cannot be picked while they run, but nobody is pinged to pick again."""
    for watch in WATCHES.get((thread_id, project), []):
        if look_id in watch.look_ids:
            watch.silence()


class LooksToolsMiddleware(AgentMiddleware):
    """`start_looks` and `pick_look` for the lead (module doc).

    `runner_factory(runtime)` returns the `HelperRunner` for a call; without one, `start_looks`
    says background helpers are unavailable. `exec_factory(runtime)` returns the `SandboxExec`; the
    default runs commands in the thread's sandbox.
    """

    def __init__(
        self,
        *,
        exec_factory: ExecFactory,
        runner_factory: RunnerFactory | None = None,
        bus: ev.EventBus | None = None,
    ) -> None:
        super().__init__()
        self._runner_factory = runner_factory
        self._exec_factory = exec_factory
        self._bus = bus
        self.tools = self._tools()

    def _tools(self) -> list[Any]:
        middleware = self

        @tool
        async def start_looks(
            project_slug: str,
            directions: list[str],
            runtime: ToolRuntime,
            effort: Literal["low", "high", "xhigh", "max"] = "xhigh",
            context: str = "",
        ) -> str:
            """Make several looks for a project at once, one background helper per direction, so
            the person can compare them side by side and pick one to build.

            Each look is a copy of /workspace/projects/<project_slug>/ in its `looks/<id>/` folder
            (ids are letters: a, b, c, then d onward for a later round). Its helper makes the look
            in the project's own files, renders a few stills or a storyboard into
            `looks/<id>/out/`, and writes `looks/<id>/look.json` ({id, direction, summary,
            stills}). This is the cheap stage: stills, not a render. Choosing is the person's:
            vision-language judges trail people by more than 30 points on video pairs.

            `directions`: one short line per look, each a different direction ("kinetic type on
            black, one accent"; "glass UI over product footage"). `context`: what every look
            shares (the ask, the audience, the files to read first), written once. `effort` is the
            helpers'.

            It returns at once. Each helper's end wakes you as any helper's does. When the last
            has ended, the person is pinged to pick: show them each look's stills and summary side
            by side, then merge their choice with pick_look.
            """
            return await middleware._start(project_slug, directions, effort, context, runtime)

        @tool
        async def pick_look(
            project_slug: str,
            look_id: str,
            reason: str,
            runtime: ToolRuntime,
            skill: str = DEFAULT_SKILL,
        ) -> str:
            """Merge the look the person picked into the project, and record their pick.

            The project is backed up first to `looks/_backup-<time>/`. Then the look's files are
            copied over it (not its look.json or out/), except files the project changed more
            recently than the look did. The other looks stay in `looks/`.

            `reason` is the person's own words for why they picked it ("" if they gave none).
            With the directions, it is recorded as an observation under `skill`: the skill this
            job runs under (launch-film, stills, thumbnails…), so the next job in
            it reads what they chose and why.
            """
            return await middleware._pick(project_slug, look_id, reason, skill, runtime)

        return [start_looks, pick_look]

    async def _start(
        self, slug: str, directions: list[str], effort: str, context: str, runtime: Any
    ) -> str:
        project = _project(slug)
        if project is None:
            return "Project name is not allowed; use one project directory name."
        wanted = [" ".join(d.split()) for d in directions if d and d.strip()]
        if not wanted:
            return "Give at least one direction."
        thread_id = _thread_id(runtime)
        if not thread_id:
            return "Looks run in the background, which needs a thread; none was started."
        if self._runner_factory is None:
            return "Background helpers are unavailable in this run, so no looks were started."
        try:
            looks = Looks(self._exec_factory(runtime))
            runner = self._runner_factory(runtime)
            existing = [result.id for result in await looks.collect(project)]
        except (WorkspaceError, LooksError) as error:
            return f"No looks were started: {error}"
        ids = next_ids(existing, len(wanted))
        specs = [LookSpec(look_id, d) for look_id, d in zip(ids, wanted, strict=True)]
        # Listening starts before the first helper does: a quick one could end before `start`
        # returns.
        watch = LookWatch(thread_id, slug, bus=self._bus)
        failure = ""
        try:
            started = await looks.start(project, specs, runner, effort, context=context)
        except LooksError as error:
            started, failure = error.started, str(error)
        except WorkspaceError as error:
            started, failure = {}, str(error)
        except BaseException:
            watch.close()
            raise
        watch.expect(started, specs)
        if started:
            WATCHES.setdefault((thread_id, project), []).append(watch)
        if failure:
            if not started:
                return f"No looks were started: {failure}"
            running = ", ".join(f"{i} ({t})" for i, t in started.items())
            return f"{failure}. Already running: {running}; each wakes you when it ends."
        rows = "\n".join(
            f"- {spec.id} ({started[spec.id]}): {_short(spec.direction)}" for spec in specs
        )
        return (
            f"Started {len(started)} looks for {slug} ({effort}, one wave):\n{rows}\n"
            f"Each works in {project}/looks/<id>/ and ends with stills in its out/ and a "
            "look.json. Each one's end wakes you; when the last has ended, the person is pinged "
            "to pick. Tell them what is being made and when to expect it, then end your turn."
        )

    async def _pick(self, slug: str, look_id: str, reason: str, skill: str, runtime: Any) -> str:
        project = _project(slug)
        if project is None:
            return "Project name is not allowed; use one project directory name."
        wanted = look_id.strip()
        thread_id = _thread_id(runtime)
        running = {look.lower(): task for look, task in _running(thread_id, project).items()}
        task = running.get(wanted.lower())
        if task is not None:
            return (
                f"Look {wanted} is still being made ({task}). Pick it once it has ended, "
                f"or cancel_task {task} first."
            )
        try:
            looks = Looks(self._exec_factory(runtime))
            results = await looks.collect(project)
            chosen = next((r for r in results if r.id == wanted), None) or next(
                (r for r in results if r.id.lower() == wanted.lower()), None
            )
            if chosen is None:
                there = ", ".join(r.id for r in results) or "none yet"
                return f"No look {wanted!r} in {slug}. Its looks: {there}."
            picked = await looks.pick(project, chosen.id)
        except (WorkspaceError, LooksError) as error:
            return f"Nothing was merged: {error}"
        _picked_from(thread_id, project, chosen.id)
        backup = posixpath.relpath(picked.backup, project)
        name = f"look {chosen.id}"
        if chosen.direction:
            name += f' ("{_short(chosen.direction, 80)}")'
        if picked.changed:
            count = len(picked.changed)
            listed = ", ".join(picked.changed[:20])
            more = f", and {count - 20} more" if count > 20 else ""
            lines = [
                f"Merged {name} into {slug}: {count} file{'' if count == 1 else 's'} changed "
                f"({listed}{more}). The version before is in {backup}/."
            ]
        else:
            lines = [
                f"Merged {name} into {slug}: no file differed from the project's, so nothing "
                f"changed. The version before is in {backup}/."
            ]
        if not chosen.ready:
            lines.append(
                "It had no readable look.json, so its helper may not have finished it: check "
                "the project before building on it."
            )
        lines.append(await _record(runtime, skill, slug, chosen, results, reason))
        return "\n".join(lines)


async def _record(
    runtime: Any,
    skill: str,
    slug: str,
    chosen: LookResult,
    results: list[LookResult],
    reason: str,
) -> str:
    """Record the pick as an observation: the direction that won, over the other looks the person
    could compare (those with a look.json), and why."""
    store = getattr(runtime, "store", None)
    if store is None:
        return "The pick was not recorded: this run has no store."
    others = [
        f'"{_short(r.direction, 80)}"'
        for r in results
        if r.id != chosen.id and r.ready and r.direction
    ]
    text = f'The person picked the look "{_short(chosen.direction or chosen.id, 120)}"'
    if others:
        text += f" over {', '.join(others)}"
    said = " ".join(reason.split())
    if said:
        text += f', saying "{_short(said, 200)}"'
    evidence = [f"{slug}, {time.strftime('%Y-%m-%d', time.gmtime())}: look {chosen.id}"]
    try:
        observation, merged = await ObservationStore(store).add(
            skill or DEFAULT_SKILL, text, evidence, status="kept"
        )
    except ValueError as error:
        return f"The pick was not recorded: {error}"
    except Exception as error:  # noqa: BLE001 - the merge happened; only the record failed
        _LOGGER.warning("[looks] recording the pick failed: %s", type(error).__name__)
        return "The pick was not recorded: the store did not take it."
    if merged:
        return (
            f"Recorded under {observation.skill}: it matches an earlier pick ({observation.id}), "
            f"now +{observation.helpful}/−{observation.harmful}."
        )
    return f"Recorded the pick and reason under {observation.skill} ({observation.id})."
