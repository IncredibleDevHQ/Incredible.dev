"""MCP servers for Managed Deep Agents, from `config/mcp.toml` (src/design_agent/tools/mcp.py).

MDA reads the module-level `mcp`: `config/mcp.toml`'s servers and, with PAPER_MODE=bridged, Paper's
bridge. Servers that need credentials name a workspace connection.
"""

from pathlib import Path

from design_agent.config import Settings
from design_agent.tools.mcp import mda_declaration, servers_for_runtime

mcp = mda_declaration(servers_for_runtime(Path(__file__).resolve().parents[1], Settings(), "mda"))
