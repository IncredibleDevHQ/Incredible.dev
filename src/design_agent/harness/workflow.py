"""Pipelines as code: a production's order, gates and retries in Python; its judgment in helpers.

Run from instructions, one model turn per step, a long production lets the lead skip a review or
start assembling before an act was checked. A pipeline makes the flow code (which step runs when,
what waits for what, which review gates what) and leaves every creative call to the briefs its
helpers get.

A pipeline is an async function `fn(ctx, **args)`, registered by name with a `WorkflowRunner`:
- `ctx.agent(brief, effort=...)` runs one helper through the host's `HelperRunner` and returns its
  report. With a `schema` it returns the JSON the report ends with, validated; a report that doesn't
  match goes back to a helper with what is wrong, up to `attempts` times.
- `ctx.parallel(thunks)` runs steps at once and waits for all of them; a failure becomes None.
  `ctx.pipeline(items, *stages)` moves each item to its next stage as soon as its current stage
  finishes, with no barrier between stages.
- `ctx.phase(name)` and `ctx.note(text)` say where the run is; `ctx.ask(question, options)` parks the
  run until someone answers.

Every step is memoized in the store under its run, keyed by the sha256 of (brief, effort, schema,
label). A run is re-run from the top after an answer, after a restart, or when the lead resumes it,
and each step it already finished replays at once from the memo: only unfinished work runs again.
The key is the step's content, not its position (LangGraph's `@task` replays by position), so adding
or reordering steps keeps every unchanged step's result. A failed step is memoized too, so pipeline
code that handles a failure takes the same path on every replay; resuming a failed or cancelled run
clears those failures, and the steps run again.

What happens is published on the bus with `source=<run id>` and `label=<pipeline name>`:
- `TASK_STARTED` when the run starts (or resumes);
- `PIPELINE_STEP` when a step starts, retries, fails or finishes (with its report), and for each
  note: held for the lead's next wake-up;
- `JOB_PHASE` when a phase starts (recorded);
- `JOB_ATTENTION` for a question: it wakes the lead and pings a person;
- one `TASK_DONE` with the result (`data["report"]`), or `TASK_FAILED`, or `TASK_CANCELLED`;
- `TASK_INTERRUPTED` from `WorkflowRunner.sweep` when a restart ended the run (a run keeps a
  heartbeat on its record while a process drives it, as `harness.ledger` does for helpers).
So the lead is woken once, with the result, like any helper, and hears every step on the way. A
re-run publishes nothing for the steps it replays.

A pipeline must be deterministic: the same arguments and step results must produce the same briefs,
or their keys change and replay stops working. Don't read the clock, randomness or the environment
inside one; a brief carries durations ("stop within 45 minutes of starting"), not clock times.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from design_agent.harness import events as ev
from design_agent.harness.protocols import HelperResult, HelperRunner
from design_agent.harness.tasks import minutes

_LOGGER = logging.getLogger(__name__)

#: A run's memoized steps live under ("harness", "workflows", <run id>), one item per step key.
MEMO = ("harness", "workflows")
#: One record per run: its pipeline, arguments, status, questions and answers, and result.
RUNS = ("harness", "workflow_runs")
#: Helpers one run keeps in flight at once.
CONCURRENCY = 8
#: A running run's record is refreshed this often, so another process can tell it is alive.
HEARTBEAT_SECONDS = 60.0
#: A record still `running` whose refresh is older than this has no process driving it.
STALE_SECONDS = 180.0
#: Characters of a report carried in a step's event; the whole report stays in the memo.
EVENT_REPORT_CHARS = 1500

#: A pipeline: `async def fn(ctx: WorkflowContext, **args) -> result` (JSON-able).
Pipeline = Callable[..., Awaitable[Any]]

_ENDED = frozenset({"done", "failed", "cancelled"})


class WorkflowError(Exception):
    """A request the runner can't carry out: an unknown pipeline or run, bad arguments, nothing to
    answer. The message says why, for the lead."""


class StepFailed(Exception):
    """A step's helper failed, or its report never matched the schema."""

    def __init__(self, label: str, reason: str, *, task_id: str = "") -> None:
        super().__init__(f"{label}: {reason}")
        self.label = label
        self.reason = reason
        self.task_id = task_id


class Suspended(BaseException):  # a signal, like CancelledError, not an error
    """Raised by `WorkflowContext.ask` to park the run until someone answers.

    A BaseException, like `asyncio.CancelledError`, so a pipeline's `except Exception` can't
    swallow it and carry on without the answer.
    """

    def __init__(self, question: str) -> None:
        super().__init__(question)
        self.question = question


@dataclass(frozen=True)
class Step:
    """A finished step: the helper's report (or, with a schema, the JSON it ended with), the task
    that produced it, and whether it was replayed from the memo instead of run."""

    value: Any
    task_id: str
    cached: bool = False


@dataclass
class RunRecord:
    """One run of a pipeline, as the store keeps it (namespace `RUNS`, key: the run id)."""

    id: str
    name: str
    thread_id: str
    args: dict[str, Any] = field(default_factory=dict)
    #: running, waiting (for an answer), done, failed, cancelled, or interrupted (by a restart).
    status: str = "running"
    #: The phase the run last entered.
    phase: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    #: When a process last saved it; a running record that stops refreshing was interrupted.
    alive_at: float = field(default_factory=time.time)
    #: Steps a helper finished for this run (replays don't count).
    steps: int = 0
    #: Questions by ask key: question, options, asked_at, answer (None until answered), returned.
    asks: dict[str, dict[str, Any]] = field(default_factory=dict)
    result: Any = None
    error: str = ""
    #: Host data a later process needs (the wake target).
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def waiting(self) -> list[dict[str, Any]]:
        """Questions asked and not yet answered, oldest first."""
        pending = [ask for ask in self.asks.values() if ask.get("answer") is None]
        return sorted(pending, key=lambda ask: float(ask.get("asked_at") or 0))

    def to_value(self) -> dict[str, Any]:
        value: dict[str, Any] = _jsonable(asdict(self))
        return value

    @classmethod
    def from_value(cls, value: Mapping[str, Any]) -> RunRecord:
        data = _jsonable(dict(value))
        finished = data.get("finished_at")
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            thread_id=str(data.get("thread_id") or ""),
            args=dict(data.get("args") or {}),
            status=str(data.get("status") or "running"),
            phase=str(data.get("phase") or ""),
            started_at=float(data.get("started_at") or 0.0),
            finished_at=float(finished) if finished is not None else None,
            alive_at=float(data.get("alive_at") or 0.0),
            steps=int(data.get("steps") or 0),
            asks=dict(data.get("asks") or {}),
            result=data.get("result"),
            error=str(data.get("error") or ""),
            meta=dict(data.get("meta") or {}),
        )

    def describe(self) -> str:
        """One line for the lead (`check_tasks`), with the result when it is done."""
        head = f"{self.id} ({self.name})"
        if self.waiting:
            ask = self.waiting[0]
            options = " / ".join(ask.get("options") or [])
            return f"{head}: waiting for an answer to: {ask['question']}" + (
                f" Options: {options}." if options else ""
            )
        if self.status == "running":
            return f"{head}: running, phase {self.phase or 'starting'}, {self.steps} steps done."
        if self.status == "failed":
            return f"{head}: failed. {self.error}"
        if self.status == "done":
            return f"{head}: done.\n{report_text(self.result)}"
        return f"{head}: {self.status}."


def new_run_id() -> str:
    return f"p-{uuid.uuid4().hex[:6]}"


def _digest(parts: Sequence[Any]) -> str:
    payload = json.dumps(
        list(parts), sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def step_key(brief: str, effort: str, schema: Mapping[str, Any] | None, label: str) -> str:
    """A step's memo key: the sha256 of its content, so it holds when steps are added or moved."""
    return _digest([brief, effort, schema, label])


def ask_key(question: str, options: Sequence[str]) -> str:
    return _digest(["ask", question, list(options)])


def report_text(result: Any) -> str:
    """A pipeline's result as the text of its `TASK_DONE`, which is what the lead's notice shows."""
    if result is None:
        return "Finished."
    if isinstance(result, str):
        return result
    return json.dumps(result, indent=1, ensure_ascii=False, default=str)


# -- reading a report's JSON ------------------------------------------------------------------------

_FENCE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)


def last_json(text: str) -> Any:
    """The JSON a report ends with: the last fenced block that parses, or the last bare object.

    Whichever ends later wins, so a fenced example early in a report never shadows the object the
    report ends with. Raises ValueError when there is none.
    """
    best: tuple[int, Any] | None = None
    for match in _FENCE.finditer(text):
        try:
            best = (match.end(), json.loads(match.group(1)))
        except ValueError:
            continue
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            start = text.find("{", start + 1)
            continue
        if best is None or end > best[0]:
            best = (end, value)
        start = text.find("{", end)
    if best is None:
        raise ValueError("the report has no JSON object")
    return best[1]


def _where(path: Iterable[Any]) -> str:
    return "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in path)


def _show(value: Any) -> str:
    return repr(value)[:80]  # as jsonschema's messages quote values


_TYPES: Mapping[str, Callable[[Any], bool]] = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: (
        (isinstance(v, int) and not isinstance(v, bool))
        or (isinstance(v, float) and v.is_integer())
    ),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def basic_schema_errors(
    value: Any, schema: Mapping[str, Any], path: Sequence[Any] = ()
) -> list[str]:
    """What `value` breaks in `schema`, from JSON Schema's `type`, `enum`, `required`,
    `properties`, `items` and `minItems`: what a step's report needs, without `jsonschema`."""
    where = _where(path)
    kinds = schema.get("type")
    if kinds is not None:
        names = [kinds] if isinstance(kinds, str) else list(kinds)
        if not any(_TYPES.get(name, lambda _v: True)(value) for name in names):
            return [f"{where}: {_show(value)} is not of type {' or '.join(map(repr, names))}"]
    errors: list[str] = []
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{where}: {_show(value)} is not one of {list(schema['enum'])!r}")
    if isinstance(value, dict):
        errors += [
            f"{where}: {key!r} is a required property"
            for key in schema.get("required", ())
            if key not in value
        ]
        for key, sub in (schema.get("properties") or {}).items():
            if key in value and isinstance(sub, Mapping):
                errors += basic_schema_errors(value[key], sub, (*path, key))
    if isinstance(value, list):
        least = int(schema.get("minItems", 0))
        if len(value) < least:
            errors.append(f"{where}: {_show(value)} should have at least {least} item(s)")
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, item in enumerate(value):
                errors += basic_schema_errors(item, items, (*path, index))
    return errors


def schema_errors(value: Any, schema: Mapping[str, Any]) -> list[str]:
    """What `value` breaks in `schema`, one line each; empty when it matches. Uses `jsonschema`
    when the environment has it, the basic check otherwise."""
    try:
        from jsonschema.validators import validator_for  # optional dependency
    except ImportError:  # pragma: no cover - exercised directly in the tests
        return basic_schema_errors(value, schema)
    validator = validator_for(schema)(schema)
    found = sorted(validator.iter_errors(value), key=lambda e: [str(p) for p in e.absolute_path])
    return [f"{_where(error.absolute_path)}: {error.message}" for error in found]


def parse_report(report: str, schema: Mapping[str, Any]) -> Any:
    """The JSON a report ends with, checked against `schema`. Raises ValueError saying what's wrong."""
    value = last_json(report)
    errors = schema_errors(value, schema)
    if errors:
        raise ValueError("; ".join(errors[:6]))
    return value


def _retry_brief(brief: str, problem: str, schema: Mapping[str, Any], report: str) -> str:
    return (
        f"{brief}\n\n--- From the pipeline, about your last reply ---\n"
        f"Its JSON didn't match what this step needs: {problem}.\n"
        "Your work is done and on disk, so don't redo it. Reply again with your report, ending "
        f"with one JSON object that matches this schema:\n{json.dumps(schema)}\n\n"
        f"Your last reply ended:\n{report[-2000:]}"
    )


def _title(brief: str) -> str:
    lines = [line.strip() for line in brief.strip().splitlines() if line.strip()]
    return lines[0][:60] if lines else "step"


def _excerpt(text: str) -> str:
    text = text.strip()
    return text if len(text) <= EVENT_REPORT_CHARS else text[:EVENT_REPORT_CHARS] + " …"


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


# -- what a pipeline sees ------------------------------------------------------------------------


@dataclass
class _Live:
    """A run this process holds: driving it, or holding it while it waits for an answer."""

    record: RunRecord
    helpers: HelperRunner | None
    task: asyncio.Task[None] | None = None
    #: Steps whose helpers are in flight: step key -> label.
    running: dict[str, str] = field(default_factory=dict)


class WorkflowContext:
    """What a pipeline function gets: its run, and the step primitives (module doc).

    One context per execution. A re-run (after an answer, a restart or a resume) starts in replay:
    phases are recorded but not published and notes are dropped, until the first step that really
    runs or the first new answer, so the lead never hears the same thing twice.
    """

    def __init__(self, runner: WorkflowRunner, live: _Live, *, replaying: bool) -> None:
        self._runner = runner
        self._live = live
        self._replaying = replaying
        self._phase = ""
        self._slots = asyncio.Semaphore(runner.concurrency)

    @property
    def run_id(self) -> str:
        return self._live.record.id

    @property
    def thread_id(self) -> str:
        return self._live.record.thread_id

    @property
    def name(self) -> str:
        return self._live.record.name

    @property
    def args(self) -> Mapping[str, Any]:
        return dict(self._live.record.args)

    # -- steps ----------------------------------------------------------------------------------

    async def agent(
        self,
        brief: str,
        *,
        effort: str,
        label: str = "",
        phase: str = "",
        schema: Mapping[str, Any] | None = None,
        attempts: int = 3,
    ) -> Step:
        """Run one helper with `brief` at `effort`; return its report as a `Step`.

        With `schema`, the value is the JSON the report ends with, validated; a report that doesn't
        match is sent back with the problem appended, up to `attempts` runs in all. A helper that
        fails raises `StepFailed`. `label` names the step in events and status lines (default: the
        brief's first line); `phase` tags it (default: the current phase).

        The same brief, effort, schema and label is the same step: it replays from the memo. Give
        work you mean to repeat a distinct label, and carry an earlier step's result in the brief of
        a step that depends on it, so a change upstream reaches it.
        """
        key = step_key(brief, effort, schema, label)
        memo = await self._runner._memo_get(self.run_id, key)
        name = label or _title(brief)
        if memo is not None:
            task_id = str(memo.get("task_id") or "")
            if memo.get("status") == "failed":
                raise StepFailed(name, str(memo.get("error") or "failed"), task_id=task_id)
            return Step(memo.get("value"), task_id, cached=True)
        return await self._run(
            key,
            brief,
            effort=effort,
            label=name,
            phase=phase or self._phase,
            schema=schema,
            attempts=max(1, attempts),
        )

    async def _run(
        self,
        key: str,
        brief: str,
        *,
        effort: str,
        label: str,
        phase: str,
        schema: Mapping[str, Any] | None,
        attempts: int,
    ) -> Step:
        helpers = self._live.helpers
        if helpers is None:
            raise StepFailed(label, "this run has no helper runner")
        self._go_live()
        facts = {"step": label, "effort": effort, "phase": phase}
        async with self._slots:
            started = time.time()
            self._live.running[key] = label
            self._say(f"{label}: started ({effort}).", state="started", **facts)
            try:
                value, result, attempt = await self._attempts(
                    helpers, brief, effort=effort, label=label, schema=schema, attempts=attempts
                )
            except StepFailed as failure:
                failed = {
                    **facts,
                    "status": "failed",
                    "error": failure.reason,
                    "task_id": failure.task_id,
                    "started_at": started,
                    "finished_at": time.time(),
                }
                await self._runner._memo_put(self.run_id, key, failed)
                self._say(
                    f"{label}: failed after {minutes(time.time() - started)}. {failure.reason}",
                    state="failed",
                    failed=True,
                    task_id=failure.task_id,
                    **facts,
                )
                raise
            finally:
                self._live.running.pop(key, None)
        finished = time.time()
        done = {
            **facts,
            "status": "done",
            "task_id": result.task_id,
            "value": value,
            "attempts": attempt,
            "started_at": started,
            "finished_at": finished,
        }
        if schema is not None:
            done["report"] = result.report
        await self._runner._memo_put(self.run_id, key, done)
        record = self._live.record
        record.steps += 1
        await self._runner._save(record)
        shown = json.dumps(value, ensure_ascii=False) if schema is not None else result.report
        self._say(
            f"{label}: done in {minutes(finished - started)}. {_excerpt(shown)}",
            state="done",
            task_id=result.task_id,
            **facts,
        )
        return Step(value, result.task_id)

    async def _attempts(
        self,
        helpers: HelperRunner,
        brief: str,
        *,
        effort: str,
        label: str,
        schema: Mapping[str, Any] | None,
        attempts: int,
    ) -> tuple[Any, HelperResult, int]:
        prompt, problem, task_id = brief, "", ""
        for attempt in range(1, attempts + 1):
            try:
                result = await helpers.run(prompt, effort=effort, label=label, wave=self.run_id)
            except Exception as error:  # the host's error fails the step, not the run
                raise StepFailed(
                    label, f"its helper could not run: {type(error).__name__}: {error}"
                ) from error
            task_id = result.task_id
            if not result.ok:
                reason = f"its helper {result.status}: {result.error or 'no report'}"
                raise StepFailed(label, reason, task_id=task_id)
            if schema is None:
                return result.report, result, attempt
            try:
                return parse_report(result.report, schema), result, attempt
            except ValueError as error:
                problem = str(error)
            if attempt < attempts:
                self._say(
                    f"{label}: its report's JSON didn't match ({problem}); sent back, attempt "
                    f"{attempt + 1} of {attempts}.",
                    state="retry",
                    step=label,
                    task_id=task_id,
                )
                prompt = _retry_brief(brief, problem, schema, result.report)
        raise StepFailed(
            label, f"no valid JSON after {attempts} attempts: {problem}", task_id=task_id
        )

    async def parallel(self, thunks: Iterable[Any]) -> list[Any]:
        """Run every thunk (a function returning an awaitable, or an awaitable) at once, and wait
        for all of them. A thunk that fails gives None and the failure is published. An `ask` inside
        one parks the run once the others have settled, so their work is saved first."""
        outcomes = await asyncio.gather(
            *(self._branch(thunk) for thunk in thunks), return_exceptions=True
        )
        for kind in (asyncio.CancelledError, Suspended, BaseException):
            for outcome in outcomes:
                if isinstance(outcome, kind):
                    raise outcome
        return list(outcomes)

    async def _branch(self, thunk: Any) -> Any:
        try:
            value = thunk() if callable(thunk) else thunk
            if inspect.isawaitable(value):
                value = await value
            return value
        except StepFailed:
            return None  # published by the step when it failed
        except Exception as error:  # noqa: BLE001 - a failed branch is None, by contract
            if not self._replaying:
                self._say(
                    f"A branch failed with {type(error).__name__}: {error}. It counts as None.",
                    state="failed",
                    failed=True,
                )
            return None

    async def pipeline(self, items: Iterable[Any], *stages: Callable[[Any], Any]) -> list[Any]:
        """Run every item through `stages` in order, all items at once, with no barrier between
        stages: an item moves on as soon as its current stage finishes. Each stage gets the previous
        stage's result (the first gets the item). An item whose stage fails gives None and skips its
        later stages; the others go on. Returns the last stage's results, in item order."""

        def flow(item: Any) -> Callable[[], Awaitable[Any]]:
            async def run() -> Any:
                value = item
                for stage in stages:
                    value = stage(value)
                    if inspect.isawaitable(value):
                        value = await value
                return value

            return run

        return await self.parallel([flow(item) for item in items])

    # -- telling people ---------------------------------------------------------------------------

    def phase(self, name: str) -> None:
        """Enter a phase (`JOB_PHASE`, recorded)."""
        self._phase = name
        self._live.record.phase = name
        if not self._replaying:
            self._runner._publish(self._live.record, ev.JOB_PHASE, name, phase=name)

    def note(self, text: str) -> None:
        """Tell the lead something (`PIPELINE_STEP`, held for its next wake-up)."""
        if not self._replaying:
            self._say(text, note=True)

    async def ask(self, question: str, options: Sequence[str] = ()) -> str:
        """Ask a person, through the lead, and park the run until the answer comes.

        The first time, it publishes `JOB_ATTENTION` (the lead is woken, a person is pinged), saves
        the question and raises `Suspended`. `WorkflowRunner.answer` stores the answer and re-runs
        the pipeline from the top; finished steps replay, and this call returns the answer. The same
        question with the same options is the same ask: put what changed (a round, a score) in the
        question when you ask again.
        """
        record = self._live.record
        key = ask_key(question, options)
        asked = record.asks.get(key)
        if asked is not None and asked.get("answer") is not None:
            if not asked.get("returned"):
                asked["returned"] = True
                self._go_live()
            return str(asked["answer"])
        if asked is None:
            self._go_live()
            record.asks[key] = {
                "key": key,
                "question": question,
                "options": list(options),
                "asked_at": time.time(),
                "answer": None,
                "returned": False,
            }
            await self._runner._save(record)
            choices = f" Options: {' / '.join(options)}." if options else ""
            self._runner._publish(
                record,
                ev.JOB_ATTENTION,
                f"{question}{choices} Pipeline {record.id} waits for the answer.",
                ping=True,
                options=list(options),
                question=question,
            )
        raise Suspended(question)

    def _go_live(self) -> None:
        """Replay is over: from here on, what happens is new. Show the phase the run is in."""
        if self._replaying:
            self._replaying = False
            if self._phase:
                self._runner._publish(
                    self._live.record, ev.JOB_PHASE, self._phase, phase=self._phase
                )

    def _say(self, text: str, **data: Any) -> None:
        self._runner._publish(self._live.record, ev.PIPELINE_STEP, text, **data)


# -- the runner ------------------------------------------------------------------------------------


class WorkflowRunner:
    """Runs registered pipelines as background tasks of this process (module doc).

    `store` is a LangGraph `BaseStore` (the deployment's; `InMemoryStore` in tests). `runner` runs the
    helpers of any run that isn't given its own; a host can give each run its own, bound to the
    thread it belongs to. Events go to `bus`.
    """

    def __init__(
        self,
        store: Any,
        runner: HelperRunner | None = None,
        bus: ev.EventBus | None = None,
        *,
        concurrency: int = CONCURRENCY,
    ) -> None:
        self._store = store
        self._helpers = runner
        self._bus = bus or ev.BUS
        self.concurrency = max(1, concurrency)
        self._pipelines: dict[str, Pipeline] = {}
        self._runs: dict[str, _Live] = {}
        self._background: set[asyncio.Task[None]] = set()

    def register(self, name: str, fn: Pipeline) -> None:
        self._pipelines[name] = fn

    @property
    def pipelines(self) -> Mapping[str, Pipeline]:
        return dict(self._pipelines)

    # -- the lead's operations ------------------------------------------------------------------

    async def start(
        self,
        name: str,
        args: Mapping[str, Any] | None,
        thread_id: str,
        *,
        runner: HelperRunner | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> str:
        """Start pipeline `name` with `args` in the background; return its run id (`p-…`) at once.

        `runner` runs this run's helpers (default: the runner's own); `meta` is host data saved
        with the run. Raises `WorkflowError` for an unknown pipeline or arguments it can't take.
        """
        fn = self._pipelines.get(name)
        if fn is None:
            known = ", ".join(sorted(self._pipelines)) or "none"
            raise WorkflowError(f"No pipeline named {name!r}. Pipelines: {known}.")
        values = dict(args or {})
        try:
            inspect.signature(fn).bind(None, **values)
            json.dumps(values)
        except TypeError as error:
            raise WorkflowError(f"{name} can't run with these arguments: {error}.") from error
        helpers = runner or self._helpers
        if helpers is None:
            raise WorkflowError("No helper runner: pass one to start() or to the WorkflowRunner.")
        record = RunRecord(
            id=new_run_id(), name=name, thread_id=thread_id, args=values, meta=dict(meta or {})
        )
        await self._save(record)
        live = _Live(record, helpers)
        self._runs[record.id] = live
        self._publish(
            record,
            ev.TASK_STARTED,
            f"Started pipeline {name}.",
            args=values,
            started_at=record.started_at,
        )
        self._launch(live, replay=False)
        return record.id

    async def answer(
        self, run_id: str, text: str, *, runner: HelperRunner | None = None
    ) -> RunRecord:
        """Answer the oldest question the run is waiting on, and let it continue: it re-runs from
        the top, its finished steps replay, and the `ask` returns `text`."""
        live = self._runs.get(run_id)
        record = live.record if live is not None else await self._load(run_id)
        if record is None:
            raise WorkflowError(f"No pipeline run {run_id}.")
        pending = record.waiting
        if record.status in _ENDED or not pending:
            raise WorkflowError(f"{run_id} is {record.status}; nothing is waiting for an answer.")
        if record.name not in self._pipelines:
            raise WorkflowError(f"Pipeline {record.name!r} isn't registered in this process.")
        helpers = runner or (live.helpers if live is not None else None) or self._helpers
        if helpers is None:
            raise WorkflowError("No helper runner: pass one to answer().")
        ask = pending[0]
        ask["answer"], ask["answered_at"] = text, time.time()
        self._publish(
            record, ev.PIPELINE_STEP, f'Answered "{ask["question"]}": {text}', answered=True
        )
        if live is not None and live.task is not None and not live.task.done():
            # Other branches are still settling; the run goes on with the answer when they have.
            live.helpers = helpers
            await self._save(record)
            return record
        if record.waiting:  # another question is still open
            await self._save(record)
            self._runs[run_id] = live or _Live(record, helpers)
            return record
        record.status = "running"
        await self._save(record)
        live = _Live(record, helpers)
        self._runs[run_id] = live
        self._launch(live, replay=True)
        return record

    async def resume(
        self, run_id: str, *, runner: HelperRunner | None = None, reason: str = ""
    ) -> RunRecord:
        """Run `run_id` again from the top: after a restart ended it (interrupted), or after it
        failed or was cancelled. Finished steps replay from the memo; after a failure or a cancel,
        failed steps run again. A run that is done, running here, or waiting for an answer is left
        as it is."""
        live = self._runs.get(run_id)
        if live is not None and live.task is not None and not live.task.done():
            return live.record
        record = live.record if live is not None else await self._load(run_id)
        if record is None:
            raise WorkflowError(f"No pipeline run {run_id}.")
        if record.name not in self._pipelines:
            raise WorkflowError(f"Pipeline {record.name!r} isn't registered in this process.")
        if record.status == "done":
            return record
        if record.waiting:
            if record.status != "waiting":
                record.status = "waiting"
                await self._save(record)
            self._runs[run_id] = live or _Live(record, runner or self._helpers)
            return record
        helpers = runner or (live.helpers if live is not None else None) or self._helpers
        if helpers is None:
            raise WorkflowError("No helper runner: pass one to resume().")
        if record.status in ("failed", "cancelled"):
            await self._forget_failures(run_id)
        record.status, record.error, record.finished_at = "running", "", None
        await self._save(record)
        live = _Live(record, helpers)
        self._runs[run_id] = live
        self._publish(
            record,
            ev.TASK_STARTED,
            f"Resumed pipeline {record.name}{' ' + reason if reason else ''}: finished steps "
            "replay from memo, the rest runs.",
            resumed=True,
            started_at=record.started_at,
        )
        self._launch(live, replay=True)
        return record

    async def cancel(self, run_id: str) -> RunRecord:
        """Stop a run and the helpers it has in flight. Its finished steps stay saved."""
        live = self._runs.get(run_id)
        record = live.record if live is not None else await self._load(run_id)
        if record is None:
            raise WorkflowError(f"No pipeline run {run_id}.")
        if record.status not in _ENDED:
            self._stop(record, live)
            await self._save(record)
        return record

    async def status(self, run_id: str) -> RunRecord | None:
        live = self._runs.get(run_id)
        return live.record if live is not None else await self._load(run_id)

    async def wait(self, run_id: str) -> RunRecord:
        """Wait until the run stops: done, failed, cancelled, or parked on a question."""
        while True:
            live = self._runs.get(run_id)
            if live is None or live.task is None or live.task.done():
                break
            await asyncio.wait({live.task})
        record = await self.status(run_id)
        if record is None:
            raise WorkflowError(f"No pipeline run {run_id}.")
        return record

    async def steps(self, run_id: str) -> list[dict[str, Any]]:
        """The run's memoized steps, oldest first: label, effort, status, task id, value or error."""
        items = await self._store.asearch((*MEMO, run_id), limit=1000)
        values = [{**_jsonable(item.value or {}), "key": item.key} for item in items]
        return sorted(values, key=lambda value: float(value.get("finished_at") or 0))

    async def sweep(
        self,
        *,
        on_found: Callable[[RunRecord], Awaitable[None]] | None = None,
        now: float | None = None,
    ) -> list[RunRecord]:
        """Find the runs a restart ended (still `running`, but no process has refreshed them for
        `STALE_SECONDS`), mark each `interrupted` and publish `TASK_INTERRUPTED` for it, once.
        `on_found` runs before each is published, so the host can say where to wake its lead.
        The lead resumes each with `resume`. Called by the host's sweep, like `harness.ledger`'s."""
        now = time.time() if now is None else now
        items = await self._store.asearch(RUNS, filter={"status": "running"}, limit=200)
        found = []
        for item in items:
            record = RunRecord.from_value(item.value or {})
            last_seen = record.alive_at
            if record.id in self._runs or now - last_seen < STALE_SECONDS:
                continue
            record.status = "interrupted"
            await self._save(record)
            if on_found is not None:
                await on_found(record)
            self._publish(
                record,
                ev.TASK_INTERRUPTED,
                f"Pipeline {record.name} was in its {record.phase or 'first'} phase. Its finished "
                "steps are saved: resuming it runs only the rest.",
                started_at=record.started_at,
                finished_at=last_seen,
            )
            found.append(record)
        return found

    # -- hooks for the host's status lines and cancel tool ---------------------------------------

    def running_lines(self, thread_id: str) -> list[str]:
        """One line per run this process holds on the thread, for "still running" lists
        (`harness.notices.RUNNING_PROVIDERS`)."""
        now, lines = time.time(), []
        for live in self._runs.values():
            record = live.record
            if record.thread_id != thread_id:
                continue
            if record.waiting:
                question = record.waiting[0]["question"]
                lines.append(
                    f"{record.id} (pipeline {record.name}, waiting for an answer: {question})"
                )
            elif record.status == "running":
                steps = ", ".join(live.running.values())
                doing = f"{record.phase or 'starting'}{': ' + steps if steps else ''}"
                lines.append(
                    f"{record.id} (pipeline {record.name}, {doing}, {minutes(now - record.started_at)})"
                )
        return lines

    def canceller(self, task_id: str, thread_id: str) -> str | None:
        """Cancel a run this process holds on the thread; None when `task_id` isn't one (for the
        host's `cancel_task`, which asks each canceller in turn)."""
        live = self._runs.get(task_id)
        if live is None or live.record.thread_id != thread_id:
            return None
        record = live.record
        self._stop(record, live)
        self._spawn(self._save(record))
        return (
            f"Cancelled pipeline {task_id} ({record.name}) and the helpers it had running. Its "
            "finished steps stay saved: resuming it continues from them."
        )

    # -- internals --------------------------------------------------------------------------------

    def _launch(self, live: _Live, *, replay: bool) -> None:
        live.task = asyncio.get_running_loop().create_task(
            self._drive(live, replay=replay), name=f"pipeline {live.record.id}"
        )

    async def _drive(self, live: _Live, *, replay: bool) -> None:
        record = live.record
        fn = self._pipelines[record.name]
        beat = asyncio.get_running_loop().create_task(
            self._beat(record), name=f"pipeline heartbeat {record.id}"
        )
        try:
            while True:
                context = WorkflowContext(self, live, replaying=replay)
                try:
                    result = await fn(context, **record.args)
                except Suspended:
                    if record.waiting:
                        record.status = "waiting"
                        await self._save(record)
                        if record.waiting:
                            return
                        record.status = "running"  # answered while it was being saved
                    replay = True
                    continue
                except asyncio.CancelledError:
                    # A cancel has already recorded it; a shutdown leaves it running, for resume.
                    raise
                except Exception as error:  # noqa: BLE001 - reported to the lead, never raised
                    self._end(record, "failed", error=f"{type(error).__name__}: {error}"[:1500])
                    await self._save(record)
                    self._publish(
                        record,
                        ev.TASK_FAILED,
                        f"{record.error} Its finished steps are saved: resuming it runs only the "
                        "rest.",
                        error=record.error,
                        started_at=record.started_at,
                        finished_at=record.finished_at,
                    )
                    return
                self._end(record, "done", result=_jsonable(result))
                await self._save(record)
                self._publish(
                    record,
                    ev.TASK_DONE,
                    report_text(record.result),
                    report=record.result,
                    started_at=record.started_at,
                    finished_at=record.finished_at,
                )
                return
        finally:
            beat.cancel()

    def _end(self, record: RunRecord, status: str, *, result: Any = None, error: str = "") -> None:
        record.status, record.result, record.error = status, result, error
        record.finished_at = time.time()
        live = self._runs.get(record.id)
        if live is not None and live.record is record:
            del self._runs[record.id]

    def _stop(self, record: RunRecord, live: _Live | None) -> None:
        self._end(record, "cancelled")
        if live is not None and live.task is not None and not live.task.done():
            live.task.cancel()
        self._publish(
            record,
            ev.TASK_CANCELLED,
            "Cancelled.",
            started_at=record.started_at,
            finished_at=record.finished_at,
        )

    async def _beat(self, record: RunRecord) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await self._save(record)

    def _spawn(self, work: Awaitable[None]) -> None:
        async def run() -> None:
            await work

        task = asyncio.get_running_loop().create_task(run())
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def _publish(self, record: RunRecord, kind: str, text: str = "", **data: Any) -> None:
        self._bus.publish(
            ev.Event(
                kind,
                record.thread_id,
                record.id,
                label=record.name,
                text=text,
                data={"run_id": record.id, "pipeline": record.name, **data},
            )
        )

    async def _save(self, record: RunRecord) -> None:
        record.alive_at = time.time()
        try:
            await self._store.aput(RUNS, record.id, record.to_value())
        except Exception as error:  # noqa: BLE001 - the run goes on; only a restart would miss it
            _LOGGER.warning("[harness] saving %s failed: %s", record.id, type(error).__name__)

    async def _load(self, run_id: str) -> RunRecord | None:
        item = await self._store.aget(RUNS, run_id)
        return RunRecord.from_value(item.value) if item is not None and item.value else None

    async def _memo_get(self, run_id: str, key: str) -> dict[str, Any] | None:
        try:
            item = await self._store.aget((*MEMO, run_id), key)
        except Exception as error:  # noqa: BLE001 - a miss: the step runs again
            _LOGGER.warning(
                "[harness] reading a step of %s failed: %s", run_id, type(error).__name__
            )
            return None
        return _jsonable(item.value) if item is not None and item.value else None

    async def _memo_put(self, run_id: str, key: str, value: Mapping[str, Any]) -> None:
        try:
            await self._store.aput((*MEMO, run_id), key, _jsonable(dict(value)))
        except Exception as error:  # noqa: BLE001 - only a replay would miss it (and re-run it)
            _LOGGER.warning(
                "[harness] saving a step of %s failed: %s", run_id, type(error).__name__
            )

    async def _forget_failures(self, run_id: str) -> None:
        namespace = (*MEMO, run_id)
        for item in await self._store.asearch(namespace, filter={"status": "failed"}, limit=1000):
            await self._store.adelete(namespace, item.key)
