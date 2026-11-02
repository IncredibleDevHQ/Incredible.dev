"""The Managed Deep Agents profile: MDA supplies the graph, sandbox, store, identity and Slack.

`agent.py` hands these components to `define_deep_agent`. Only public `managed_deepagents`
names are used anywhere in this package. MCP servers declared in `config/mcp.toml` reach MDA through
`tools/mcp.py` (MDA's convention for a static agent); MDA loads their tools at runtime, so the
components only need the server names (for disclosure and the call-time boundary).
"""

from __future__ import annotations

from pathlib import Path

from design_agent.assembly import AgentComponents, build_agent_components
from design_agent.config import Settings
from design_agent.runtime.profiles import mda_profile
from design_agent.tools.mcp import servers_for_runtime

AGENT_NAME = "design-agent"


def build_mda_components(settings: Settings, *, project_root: Path) -> AgentComponents:
    return build_agent_components(
        settings=settings,
        runtime=mda_profile(project_root, settings),
        mcp_servers=servers_for_runtime(project_root, settings, "mda"),
    )
