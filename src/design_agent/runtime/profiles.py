"""What a runtime supplies to the shared assembly: sandbox access, staging, identity, delivery,
presentation.

Adapters provide these; they never fork tools, prompts, skills or policy. Every accessor takes
the run's runtime object and resolves per call, so nothing per-run is cached on a tool or
middleware instance.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepagents.backends.protocol import BackendProtocol
from langgraph.config import get_config

from design_agent.config import RuntimeName
from design_agent.middleware.background import BackgroundServices
from design_agent.middleware.workspace import StagingTarget
from design_agent.surfaces.presenter import Presenter
from design_agent.tools.delivery import DeliveryAdapter


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
    """Where `upload_files` sends files; None leaves the tool out."""
    services: BackgroundServices | None = None
    """The process's wake-up plumbing; None turns background work off (a one-shot run)."""
    quiet_status: Callable[[str], str] | None = None
    """Set where the platform posts every scheduled run's reply: what a `[quiet]` becomes."""
    presenter: Presenter | None = None
    """The channel UI that shows each turn's work and carries follow-ups in; None runs headless."""
    surface: str = "cli"
    """How runs reach the agent when no channel says so (trace tags): `cli`, `api`, `web`."""
