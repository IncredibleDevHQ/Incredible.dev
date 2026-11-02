"""Generic tags on a run's LangSmith trace: what started it, where, and what it delivered.

An operator filtering traces wants three one-click answers without opening each run, so the
trace's root carries tags (and the same facts as metadata):

- `trigger:<kind>`: `message` (a person's message, or a CLI/API ask), `wakeup` (background news
  woke the lead), `check_in` (a `schedule_wakeup` came due), `watchdog` (the restart sentinel),
  `schedule` (any other platform schedule, such as housekeeping), `resume` (the turn after an
  approval or a prompt answer), `helper` (a background helper's own trace);
- `surface:<name>`: the channel provider (`slack`), else the runtime's default (`cli`, `api`);
- `delivered:<kind>`: one per kind of file `upload_files` sent (`image`, `video`, `audio`, `pdf`,
  `other`), on the root when it is still running and on the tool call's own run otherwise;
- `template:langchain-ai/design-agent`, with `ls_template` and `ls_template_version` metadata: the
  repository and version every deployment runs, however it is renamed, so LangChain can count
  adopters. `DESIGN_AGENT_TEMPLATE_TELEMETRY=0` leaves it off.

No user ids, names, channels or message text go on a trace from here.

LangChain's tracer holds each run until it ends, then sends what it carries; LangSmith ignores
tags sent for a run that already ended. So labels are written onto runs still in the tracer's
hands: the root is the entry under the trace's id in the tracer's `run_map`. Nothing here may
cost a run anything: a failure is logged by class name and the run goes on unlabeled.

`TraceLinks` builds the footer's link to a run's trace from a host the operator configures
(`DESIGN_AGENT_TRACE_HOST`); with none, there is no link, since a trace URL names the workspace,
project and run.
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib import metadata as package_metadata
from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tracers.langchain import LangChainTracer
from langgraph.config import get_config
from langgraph.types import Command
from langsmith import RunTree
from langsmith.run_helpers import get_current_run_tree

from design_agent import __version__
from design_agent.harness import tasks
from design_agent.middleware.background import CHECK_IN_MARK
from design_agent.middleware.quiet import SENTINEL_MARK
from design_agent.middleware.today import DATE_NOTE
from design_agent.runtime.waker import wake_key
from design_agent.tools.delivery import UPLOAD_TOOL, UPLOADED

_LOGGER = logging.getLogger(__name__)

TRIGGER, SURFACE, DELIVERED = "trigger:{}", "surface:{}", "delivered:{}"
#: The kind a delivered file counts as, by the start of its MIME type.
DELIVERED_KINDS = (
    ("image/", "image"),
    ("video/", "video"),
    ("audio/", "audio"),
    ("application/pdf", "pdf"),
)
#: Human messages the runtime writes, not a person: the date note and the running-work note.
NOTE_IDS = (DATE_NOTE, "running:")
TEMPLATE = "langchain-ai/design-agent"


def template_marker() -> dict[str, str]:
    """The template and its version (module doc): nothing about the deployment or its people."""
    try:
        version = package_metadata.version("design-agent")
    except package_metadata.PackageNotFoundError:
        version = __version__
    return {"ls_template": TEMPLATE, "ls_template_version": version}


@dataclass(frozen=True)
class TraceRoot:
    """The trace a reply came from: its root run and the project it is traced to."""

    run_id: str
    trace_id: str
    project: str


def trace_runs() -> tuple[RunTree | None, RunTree | None]:
    """The run this code is inside, and its trace's root while the tracer still holds it."""
    current = get_current_run_tree()
    if current is None:
        return None, None
    try:
        callbacks = get_config().get("callbacks")
    except RuntimeError:
        return current, None
    handlers = callbacks if isinstance(callbacks, list) else getattr(callbacks, "handlers", [])
    for handler in handlers or []:
        if isinstance(handler, LangChainTracer):
            root = handler.run_map.get(str(current.trace_id))
            if isinstance(root, RunTree) and root.end_time is None:
                return current, root
    return current, None


def current_root() -> TraceRoot | None:
    """This run's trace root, while the tracer still holds it (call it inside the run)."""
    try:
        _, root = trace_runs()
    except Exception as error:  # noqa: BLE001 - a link is never worth a run
        _LOGGER.warning("[trace] root not read: %s", type(error).__name__)
        return None
    if root is None or not root.session_name:
        return None
    return TraceRoot(str(root.id), str(root.trace_id), str(root.session_name))


def stamp(
    run: RunTree, tags: Iterable[str] = (), metadata: Mapping[str, object] | None = None
) -> None:
    """Add tags, and metadata the run does not carry yet, to a run the tracer still holds."""
    fresh = [tag for tag in dict.fromkeys(tags) if tag not in (run.tags or [])]
    if fresh:
        run.add_tags(fresh)
    missing = {key: value for key, value in (metadata or {}).items() if key not in run.metadata}
    if missing:
        run.add_metadata(missing)


def _asked(messages: Sequence[object]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage) and not str(message.id or "").startswith(NOTE_IDS):
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


def trigger_of(runtime: Any, messages: Sequence[object]) -> str:
    """What started this run (module doc). Read from markers this agent writes into its own
    wake-up prompts and from the platform's event type; a tag, never an authority."""
    if tasks.CURRENT.get() is not None:
        return "helper"
    asked = _asked(messages)
    if wake_key(asked):
        return "wakeup"
    if CHECK_IN_MARK in asked:
        return "check_in"
    if SENTINEL_MARK in asked:
        return "watchdog"
    event = getattr(getattr(runtime, "channel", None), "event", None)
    kind = event.get("type") if isinstance(event, Mapping) else None
    if kind == "schedule":
        return "schedule"
    if kind in ("interrupt_resume", "user_prompt_response"):
        return "resume"
    return "message"


def delivered_kind(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or ""
    return next((kind for start, kind in DELIVERED_KINDS if mime.startswith(start)), "other")


class RunTagsMiddleware(AgentMiddleware[AgentState[Any], Any, Any]):
    """Tag the run's trace with its trigger, surface and deliveries (module doc).

    `surface` names runs that come through no platform channel (`cli` locally, `api` on the
    self-hosted API), or is a function of the runtime for adapters that know better. `template`
    is `template_marker()`, or empty when the operator turned it off.
    """

    def __init__(
        self,
        *,
        surface: str | Callable[[Any], str] = "api",
        template: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__()
        self._surface = surface
        self._template = dict(template or {})

    @property
    def name(self) -> str:
        return "DesignAgentRunTags"

    def _surface_of(self, runtime: Any) -> str:
        provider = getattr(getattr(runtime, "channel", None), "provider", None)
        if isinstance(provider, str) and provider:
            return provider
        return self._surface(runtime) if callable(self._surface) else self._surface

    async def abefore_agent(self, state: AgentState[Any], runtime: Any) -> dict[str, Any] | None:
        try:
            _, root = trace_runs()
            if root is not None:
                trigger = trigger_of(runtime, list(state.get("messages") or []))
                surface = self._surface_of(runtime)
                tags = [TRIGGER.format(trigger), SURFACE.format(surface)]
                if self._template:
                    tags.append(f"template:{self._template['ls_template']}")
                stamp(root, tags, {"trigger": trigger, "surface": surface, **self._template})
        except Exception as error:  # noqa: BLE001 - a label is never worth a run
            _LOGGER.warning("[trace] run not labeled: %s", type(error).__name__)
        return None

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        result = await handler(request)
        if request.tool_call.get("name") != UPLOAD_TOOL:
            return result
        if not isinstance(result, ToolMessage) or str(result.content).strip() != UPLOADED:
            return result
        try:
            paths = (request.tool_call.get("args") or {}).get("paths") or []
            kinds = sorted({delivered_kind(str(path)) for path in paths})
            current, root = trace_runs()
            target = root or current
            if target is not None and kinds:
                had = list(target.metadata.get("delivered") or [])
                stamp(target, [DELIVERED.format(kind) for kind in kinds])
                target.add_metadata({"delivered": sorted({*had, *kinds})})
        except Exception as error:  # noqa: BLE001 - the file reached the person either way
            _LOGGER.warning("[trace] delivery not labeled: %s", type(error).__name__)
        return result


#: Reads a LangSmith project's (workspace id, project id) by name.
ProjectIds = Callable[[str], tuple[str, str]]


def _read_project(name: str) -> tuple[str, str]:
    from langsmith import Client

    project = Client().read_project(project_name=name)
    return str(project.tenant_id), str(project.id)


class TraceLinks:
    """The URL of a run's trace on `host`, with its project's ids looked up once per process."""

    def __init__(
        self, host: str, *, project_ids: ProjectIds = _read_project, timeout: float = 10.0
    ) -> None:
        self._host = host.rstrip("/")
        self._project_ids = project_ids
        self._timeout = timeout
        self._known: dict[str, tuple[str, str]] = {}

    async def url(self, root: TraceRoot | None) -> str:
        """The link, or "" when it cannot be named (the footer goes out without it)."""
        if root is None or not self._host:
            return ""
        ids = self._known.get(root.project)
        if ids is None:
            try:
                ids = await asyncio.wait_for(
                    asyncio.to_thread(self._project_ids, root.project), self._timeout
                )
            except Exception as error:  # noqa: BLE001 - the footer goes out without the link
                _LOGGER.warning("[trace] no trace link: %s", type(error).__name__)
                return ""
            self._known[root.project] = ids
        workspace, project = ids
        return f"{self._host}/o/{workspace}/projects/p/{project}/r/{root.run_id}?trace_id={root.trace_id}&poll=true"
