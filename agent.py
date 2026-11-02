"""Managed Deep Agents entry. Thin: it only hands the shared components to `define_deep_agent`."""

from __future__ import annotations

from pathlib import Path

from managed_deepagents import define_deep_agent

from design_agent.config import Settings
from design_agent.middleware.tracing import template_marker
from design_agent.runtime.mda import build_mda_components

_settings = Settings()
_components = build_mda_components(_settings, project_root=Path(__file__).parent)

agent = define_deep_agent(
    name="design-agent",
    model=_components.model,
    tools=list(_components.tools),
    middleware=list(_components.middleware),
    subagents=list(_components.subagents) or None,
    interrupt_on=dict(_components.interrupt_on) or None,
    metadata=template_marker() if _settings.template_telemetry else None,
)
