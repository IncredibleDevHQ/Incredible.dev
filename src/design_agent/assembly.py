"""One shared agent assembly. Runtime adapters compose these components; they never fork them.

`build_agent_components` performs no network calls and holds no process-global mutable state.
Per-run objects (sandbox handles, task tools, runtime handles) are resolved per call through the
runtime profile, never cached on a middleware instance.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepagents import SubAgent
from langchain.agents.middleware import AgentMiddleware, InterruptOnConfig, TodoListMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from design_agent.brand.schema import BrandPack, load_brand_pack
from design_agent.config import ModelSpec, Settings
from design_agent.harness.cache import StaggerGate
from design_agent.harness.durable import TranscriptCheckpointMiddleware
from design_agent.harness.tasks import running
from design_agent.middleware.background import (
    BackgroundHelpers,
    BackgroundTaskMiddleware,
    WorkerProgressMiddleware,
    helper_store,
)
from design_agent.middleware.budget import JobBudgetMiddleware
from design_agent.middleware.footer import Footers, ReplyFooterMiddleware
from design_agent.middleware.guards import disclosure_for, model_guards
from design_agent.middleware.housekeeping import HousekeepingMiddleware
from design_agent.middleware.learning_tools import LearningToolsMiddleware
from design_agent.middleware.look import LookMiddleware
from design_agent.middleware.looks_tools import LooksToolsMiddleware, sandbox_exec_for
from design_agent.middleware.meter import StaggerMiddleware
from design_agent.middleware.paper_scope import PaperScopeMiddleware
from design_agent.middleware.pipeline_tools import PipelineToolsMiddleware
from design_agent.middleware.progress import HelperProgressMiddleware, ThreadProgressMiddleware
from design_agent.middleware.quiet import QuietReplyMiddleware
from design_agent.middleware.skill_list import load_summaries
from design_agent.middleware.steering import (
    HelperSteeringMiddleware,
    LeadSteeringMiddleware,
    SteeringToolsMiddleware,
)
from design_agent.middleware.today import TodayMiddleware, ZoneFor, fixed_zone
from design_agent.middleware.tracing import RunTagsMiddleware, TraceLinks, template_marker
from design_agent.middleware.watch_tools import WatchToolsMiddleware
from design_agent.middleware.workspace import WorkspaceStagerMiddleware
from design_agent.models.factory import Role, build_chat_model, resolve_model
from design_agent.models.registry import ToolDisclosure, capabilities_for
from design_agent.pipelines import PIPELINES
from design_agent.runtime.profiles import RuntimeProfile
from design_agent.runtime.sandbox.docker import current_thread_id
from design_agent.subagents import build_subagents
from design_agent.surfaces.slack.phrasebook import services
from design_agent.tools.delivery import (
    DeliveryLedgerMiddleware,
    UploadFallbackMiddleware,
    build_upload_tool,
)
from design_agent.tools.fetch import build_fetch_tool
from design_agent.tools.mcp import McpServer
from design_agent.tools.media import build_media_tools
from design_agent.tools.paper import SERVER as PAPER
from design_agent.tools.paper import PaperPolicy
from design_agent.tools.projects import build_project_tools
from design_agent.tools.traces import build_trace_tools
from design_agent.workspace.manifest import Manifest, build_manifest

SKILLS_ROOT = "/skills/"


@dataclass(frozen=True)
class AgentComponents:
    model: BaseChatModel
    tools: tuple[BaseTool, ...]
    middleware: tuple[AgentMiddleware[Any, Any, Any], ...]
    subagents: tuple[SubAgent, ...]
    interrupt_on: Mapping[str, bool | InterruptOnConfig]
    system_prompt: str
    skills: tuple[str, ...]
    brand: BrandPack
    manifest: Manifest
    pipelines: Mapping[str, Any] = field(default_factory=dict)
    mcp_servers: tuple[McpServer, ...] = ()


def _disclosure(settings: Settings, role: Any, injected: BaseChatModel | None) -> ToolDisclosure:
    """How tools reach the model that will actually run: the configured one, or an injected one
    (the scripted demo and tests), read from its provider and model name."""
    if injected is None:
        return capabilities_for(resolve_model(settings, role).spec).disclosure
    try:
        spec = ModelSpec.parse(
            f"{getattr(injected, 'provider_name', '')}:{getattr(injected, 'model_name', '')}"
        )
        return capabilities_for(spec).disclosure
    except ValueError:
        return ToolDisclosure.ALL


def load_instructions(project_root: Path) -> str:
    return (project_root / "instructions.md").read_text(encoding="utf-8")


def build_agent_components(
    *,
    settings: Settings,
    runtime: RuntimeProfile,
    model: BaseChatModel | None = None,
    role_models: Mapping[str, BaseChatModel] | None = None,
    mcp_servers: Sequence[McpServer] = (),
    mcp_tools: Sequence[BaseTool] = (),
    zone_for: ZoneFor | None = None,
) -> AgentComponents:
    """Model, tools, middleware, subagents and policy for every runtime.

    `model` replaces the lead's model and `role_models` the models of `look` and the helpers (keyed
    by role or effort), for the scripted demo and the tests. `mcp_servers` are the declared MCP
    servers (their tools reach the graph as `mcp_tools` locally, or from the platform on MDA).
    `zone_for` decides whose timezone a turn's date note is in (default: `DESIGN_AGENT_TIMEZONE`).
    """
    root = runtime.project_root
    brand = load_brand_pack(settings.resolved_brand_path(root), project_root=root)
    manifest = build_manifest(root, brand)
    lead = model if model is not None else build_chat_model(settings, "lead", project_root=root)
    overrides = dict(role_models or {})

    tools: list[BaseTool] = [
        *build_media_tools(settings, runtime.backend_for),
        *build_project_tools(runtime.backend_for),
        build_fetch_tool(runtime.backend_for),
        *build_trace_tools(settings, runtime.backend_for, runtime.thread_id_for),
        *mcp_tools,
    ]
    if runtime.delivery is not None:
        tools.append(
            build_upload_tool(
                adapter=runtime.delivery,
                backend_for=runtime.backend_for,
                thread_id_for=runtime.thread_id_for,
            )
        )

    summaries = load_summaries(root)

    def selector() -> BaseChatModel:
        return overrides.get("tool_selector") or build_chat_model(
            settings, "tool_selector", project_root=root
        )

    paper = (
        PaperPolicy.from_settings(settings) if any(s.name == PAPER for s in mcp_servers) else None
    )

    def guards(
        role: str, *, lead_agent: bool, disclosure: Any
    ) -> list[AgentMiddleware[Any, Any, Any]]:
        # Paper's policy sits outside disclosure, so search only ever sees admitted Paper tools.
        scope: list[AgentMiddleware[Any, Any, Any]] = (
            [
                PaperScopeMiddleware(
                    paper,
                    backend_for=runtime.backend_for,
                    local_exports=settings.paper_mode == "local",
                )
            ]
            if paper
            else []
        )
        return [
            *scope,
            *model_guards(
                role=role,
                lead=lead_agent,
                summaries=summaries,
                disclosure=disclosure_for(
                    disclosure, mcp_servers, selector, settings.mcp_max_tools
                ),
                servers=mcp_servers,
            ),
        ]

    # Housekeeping first: its run ends in `before_agent`, before staging touches the sandbox.
    # Quiet next, so its after_agent runs last of ours and rewrites a final `[quiet]` after every
    # other hook has seen the reply (middleware/quiet.py).
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        HousekeepingMiddleware(runtime.services),
        QuietReplyMiddleware(
            lambda thread: bool(running(thread)), current_thread_id, runtime.quiet_status
        ),
        WorkspaceStagerMiddleware(manifest, runtime.staging_for),
        DeliveryLedgerMiddleware(runtime.backend_for, thread_id_for=runtime.thread_id_for),
        *(
            [
                UploadFallbackMiddleware(
                    build_upload_tool(
                        adapter=runtime.fallback_delivery,
                        backend_for=runtime.backend_for,
                        thread_id_for=runtime.thread_id_for,
                    ),
                    thread_id_for=runtime.thread_id_for,
                )
            ]
            if runtime.delivery is None and runtime.fallback_delivery is not None
            else []
        ),
        TodoListMiddleware(),
        TodayMiddleware(zone_for=zone_for or fixed_zone(settings.timezone)),
        RunTagsMiddleware(
            surface=runtime.surface,
            template=template_marker() if settings.template_telemetry else None,
        ),
    ]
    slack = runtime.slack
    servers = services([s.name for s in mcp_servers])
    if slack is not None:
        # Steering reads follow-ups before progress draws the turn; both sit outside the model
        # guards, so a retried call shows as one step and a boundary's line counts as the reply.
        if settings.enable_steering:
            middleware.append(LeadSteeringMiddleware(slack, backend_for=runtime.backend_for))
        if settings.enable_progress:
            middleware.append(
                ThreadProgressMiddleware(slack, servers=servers, steering=settings.enable_steering)
            )
        if settings.enable_footer:
            traces = TraceLinks(settings.trace_host) if settings.trace_host else None
            inbox = runtime.services.inbox if runtime.services is not None else None
            middleware.append(
                ReplyFooterMiddleware(slack, footers=Footers(traces=traces, inbox=inbox))
            )
    subagents: list[SubAgent] = []
    if runtime.services is not None:
        background = BackgroundTaskMiddleware(runtime.services)

        def helpers(call_runtime: Any) -> BackgroundHelpers:
            return BackgroundHelpers(background, call_runtime)

        look_spec = resolve_model(settings, "look")
        look_model = overrides.get("look") or (
            lambda: build_chat_model(settings, "look", project_root=root)
        )
        middleware += [
            background,
            *([SteeringToolsMiddleware()] if settings.enable_steering else []),
            WatchToolsMiddleware(runtime.services, runtime.backend_for),
            PipelineToolsMiddleware(background=background),
            LooksToolsMiddleware(
                exec_factory=sandbox_exec_for(runtime.backend_for), runner_factory=helpers
            ),
            LookMiddleware(
                model=look_model, model_name=str(look_spec.spec), backend_for=runtime.backend_for
            ),
        ]
        if settings.enable_learning:
            review = "learning" if settings.learning_model else "low"
            middleware.append(LearningToolsMiddleware(runner_factory=helpers, review_effort=review))

        stagger = StaggerGate()
        helper_disclosure = _disclosure(settings, "helper", overrides.get("helper"))

        def helper_middleware(role: str) -> list[AgentMiddleware[Any, Any, Any]]:
            # Steering notes land before the transcript checkpoint, so a resumed helper keeps them.
            return [
                WorkerProgressMiddleware(),
                *([HelperSteeringMiddleware()] if settings.enable_steering else []),
                TranscriptCheckpointMiddleware(helper_store),
                TodayMiddleware(),
                StaggerMiddleware(stagger),
                *(
                    [HelperProgressMiddleware(slack, servers=servers)]
                    if slack is not None and settings.enable_progress
                    else []
                ),
                *guards(role, lead_agent=False, disclosure=helper_disclosure),
            ]

        def helper_model(
            settings_: Settings, role: Role, *, effort: str | None = None, **kwargs: Any
        ) -> Any:
            override = overrides.get(effort or role) or overrides.get("helper")
            if override is not None:
                return override
            return build_chat_model(settings_, role, effort=effort, project_root=root, **kwargs)

        subagents = build_subagents(
            settings, middleware=helper_middleware, build_model=helper_model
        )
    if settings.job_budget_usd is not None:
        middleware.append(JobBudgetMiddleware(settings.job_budget_usd))
    middleware += guards("lead", lead_agent=True, disclosure=_disclosure(settings, "lead", model))

    return AgentComponents(
        model=lead,
        tools=tuple(tools),
        middleware=tuple(middleware),
        subagents=tuple(subagents),
        interrupt_on={},
        system_prompt=load_instructions(root),
        skills=(SKILLS_ROOT,),
        brand=brand,
        manifest=manifest,
        pipelines=dict(PIPELINES),
        mcp_servers=tuple(mcp_servers),
    )
