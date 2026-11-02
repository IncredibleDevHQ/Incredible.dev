"""What a runtime supplies to the shared assembly: sandbox access, staging, identity, delivery.

Adapters provide these; they never fork tools, prompts, skills or policy. Every accessor takes
the run's runtime object and resolves per call, so nothing per-run is cached on a tool or
middleware instance.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from deepagents.backends.protocol import BackendProtocol
from langgraph.config import get_config

from design_agent.config import Settings
from design_agent.middleware.background import BackgroundServices
from design_agent.middleware.workspace import BackendTarget, StagingTarget
from design_agent.tools.delivery import DeliveryAdapter

RuntimeName = Literal["local", "mda", "self_hosted"]


def thread_id_from_config(runtime: Any = None) -> str:
    """The run's thread id: from a tool runtime's config, else the ambient run config."""
    config = getattr(runtime, "config", None)
    if not isinstance(config, dict):
        try:
            config = get_config()
        except RuntimeError:
            return "local"
    thread_id = (config.get("configurable") or {}).get("thread_id")
    return str(thread_id) if thread_id else "local"


@dataclass(frozen=True)
class RuntimeProfile:
    name: RuntimeName
    project_root: Path
    backend_for: Callable[[Any], BackendProtocol | None]
    """The thread's sandbox backend, for host tools that move files in and out."""
    staging_for: Callable[[Any], StagingTarget | None]
    thread_id_for: Callable[[Any], str] = thread_id_from_config
    delivery: DeliveryAdapter | None = None
    """None means the platform brings `upload_files` (MDA's Slack channel)."""
    fallback_delivery: DeliveryAdapter | None = None
    """Where files go on runs the platform's `upload_files` is missing from (MDA without Slack)."""
    services: BackgroundServices | None = None
    """The process's wake-up plumbing; None turns background work off (a one-shot run)."""
    quiet_status: Callable[[str], str] | None = None
    """Set where the platform posts every scheduled run's reply: what a `[quiet]` becomes."""
    slack: Any = None
    """A `surfaces.slack.SlackSurface` when runs answer in Slack: live progress, footer, steering."""
    surface: str = "cli"
    """How runs reach the agent when no channel says so (trace tags): `cli`, `api`, `studio`."""


def mda_profile(project_root: Path, settings: Settings | None = None) -> RuntimeProfile:
    """Managed Deep Agents: the sandbox and delivery tool come from the managed runtime; wake-ups
    are runtime schedules on the thread."""
    from design_agent.middleware.quiet import running_status
    from design_agent.runtime.waker.mda import MdaScheduleWaker
    from design_agent.surfaces.slack import MdaSlackResolver, SlackSurface
    from design_agent.tools.delivery import TraceAttachmentAdapter

    settings = settings or Settings()

    waker = MdaScheduleWaker()

    def backend_for(runtime: Any) -> BackendProtocol | None:
        backend = getattr(runtime, "backend", None)
        return backend if isinstance(backend, BackendProtocol) else None

    def staging_for(runtime: Any) -> StagingTarget | None:
        backend = backend_for(runtime)
        return BackendTarget(backend) if backend is not None else None

    services = BackgroundServices(
        waker=waker,
        capture_target=waker.capture,
        watchdog=waker.watchdog,
        on_turn_start=waker.on_turn_start,
    )
    return RuntimeProfile(
        name="mda",
        project_root=project_root,
        backend_for=backend_for,
        staging_for=staging_for,
        services=services,
        quiet_status=running_status,
        fallback_delivery=TraceAttachmentAdapter(),
        slack=SlackSurface(
            MdaSlackResolver(), mention_required=not settings.slack_trigger_on_all_messages
        ),
        surface="studio",
    )
