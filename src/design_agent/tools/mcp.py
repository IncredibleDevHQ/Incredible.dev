"""MCP servers: declared once, loaded per runtime, isolated per server.

Servers are declared in `config/mcp.toml`; Paper adds its own from `PAPER_*` (`tools/paper.py`),
and `servers_for_runtime` returns both:

    [servers.docs]
    url = "https://docs.example.com/mcp"
    transport = "http"                      # or "sse"; "stdio" with `command` instead of `url`
    headers_env = { Authorization = "DOCS_MCP_AUTH" }   # local/self-hosted: header -> host env var
    connection = "docs-token"               # MDA: a workspace connection (Agent Auth)
    owner = "agent"                         # MDA: "agent" (one shared account) or "user" (each person's own)
    include_tools = ["search"]              # optional
    timeout = 30                            # seconds per request
    always_shown = false                    # keep its schemas bound instead of deferred

A server's tools are named `{server}_{tool}` on every runtime, as Managed Deep Agents names them.
Server names are lowercase letters and digits only, so a tool name splits on its first underscore
without ambiguity (`tools/disclosure` relies on it).

Isolation:
- Loading: locally and self-hosted, each server loads on its own with a deadline; one that fails is
  reported and left out, the rest load. On MDA the declaration sets `throw_on_load_error=False`,
  which warns and omits a server whose discovery fails.
- Calling: a call that raises (MDA 0.9 lets invocation failures propagate) comes back as a tool
  error naming the server (`McpToolErrorBoundary`), so one service failing never ends a run.

Credentials stay on the host and out of artifacts. Locally and self-hosted, header values are read
from the host environment when the server loads (a `bearer` comes from typed settings, masked). On
MDA the declaration is compiled into the deployment, so header values are never put in it: a server
that needs credentials names a workspace connection (`connection`), which MDA resolves at call time;
one that names only `headers_env` or a `bearer` is left out on MDA with a warning. A connection is
owned by the deployment (`owner = "agent"`: one account everyone's requests use) or by each person
(`owner = "user"`: MDA's credential gate asks a person who has not connected yet to sign in, with a
connect link, before the run starts). Per-person connections exist only on MDA, so local and
self-hosted runtimes leave those servers out with a warning. Nothing reaches the sandbox.

LangSmith's managed tool servers (`https://api.smith.langchain.com/v1/managed-tools/...`, such as
Parallel web search) need no credentials in the config: MDA authenticates them itself, and locally
and self-hosted they are sent the workspace's `LANGSMITH_API_KEY` as `x-api-key`.

Stdio servers (`transport = "stdio"`, a local app's own CLI) run locally and self-hosted only: MDA's
`define_mcp` speaks HTTP and SSE, so they are left out of its declaration with a warning. The child
process gets the MCP SDK's short list of safe variables (home, path, shell, user), not the host's
environment, so provider keys never reach it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tomllib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command
from pydantic import SecretStr

if TYPE_CHECKING:
    from design_agent.config import RuntimeName, Settings

_LOGGER = logging.getLogger(__name__)

SERVER_NAME = re.compile(r"[a-z][a-z0-9]{0,30}")
#: LangSmith's managed tool servers, in any region (module doc).
MANAGED_TOOLS = re.compile(r"https://(?:[a-z]+\.)?api\.smith\.langchain\.com/v1/managed-tools/")
Owner = Literal["agent", "user"]
CONFIG = Path("config") / "mcp.toml"


class McpConfigError(ValueError):
    """`config/mcp.toml` declares something this loader will not run."""


@dataclass(frozen=True)
class McpServer:
    name: str
    url: str
    transport: Literal["http", "sse", "stdio"] = "http"
    headers_env: Mapping[str, str] = field(default_factory=dict)
    include_tools: tuple[str, ...] | None = None
    timeout: float = 30.0
    always_shown: bool = False
    connection: str | None = None
    owner: Owner = "agent"
    """Who the connection belongs to on MDA: the deployment, or each person (module doc)."""
    command: tuple[str, ...] = ()
    """A stdio server's executable and arguments (`url` is empty)."""
    bearer: SecretStr | None = field(default=None, repr=False, compare=False)
    """Sent as `Authorization: Bearer …` locally and self-hosted; MDA uses `connection` instead."""
    api_key: SecretStr | None = field(default=None, repr=False, compare=False)
    """Sent as `x-api-key` locally and self-hosted: the LangSmith key, for managed tool servers."""

    def headers(self, env: Mapping[str, str]) -> dict[str, str] | None:
        """The headers from the host environment; None when one it names is unset."""
        values = {header: env.get(var, "") for header, var in self.headers_env.items()}
        if self.bearer is not None:
            values["Authorization"] = f"Bearer {self.bearer.get_secret_value()}"
        if self.api_key is not None:
            values["x-api-key"] = self.api_key.get_secret_value()
        return None if any(not v for v in values.values()) else values


def declared_servers(project_root: Path) -> list[McpServer]:
    path = project_root / CONFIG
    if not path.is_file():
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    servers: list[McpServer] = []
    for name, entry in dict(data.get("servers") or {}).items():
        if not SERVER_NAME.fullmatch(name):
            raise McpConfigError(f"MCP server name {name!r}: use lowercase letters and digits only")
        transport = entry.get("transport", "http")
        if transport not in ("http", "sse", "stdio"):
            raise McpConfigError(f"MCP server {name}: transport must be http, sse or stdio")
        url = str(entry.get("url") or "")
        command = tuple(str(part) for part in entry.get("command") or ())
        if transport == "stdio":
            if not command or url:
                raise McpConfigError(
                    f"MCP server {name}: a stdio server takes a command and no url"
                )
        elif not url.startswith("https://") and not url.startswith("http://127.0.0.1"):
            raise McpConfigError(
                f"MCP server {name}: url must be https (or http://127.0.0.1 for a local app)"
            )
        include = entry.get("include_tools")
        owner = entry.get("owner", "agent")
        if owner not in ("agent", "user"):
            raise McpConfigError(f"MCP server {name}: owner must be agent or user")
        if owner == "user" and not entry.get("connection"):
            raise McpConfigError(
                f'MCP server {name}: owner = "user" needs a connection for each person to sign in to'
            )
        servers.append(
            McpServer(
                name=name,
                url=url,
                transport=transport,
                command=command,
                headers_env={
                    str(k): str(v) for k, v in dict(entry.get("headers_env") or {}).items()
                },
                include_tools=tuple(str(t) for t in include) if include is not None else None,
                timeout=float(entry.get("timeout", 30)),
                always_shown=bool(entry.get("always_shown", False)),
                connection=str(entry["connection"]) if entry.get("connection") else None,
                owner=owner,
            )
        )
    return servers


def server_of(tool_name: str, servers: Sequence[str] | frozenset[str]) -> str | None:
    """The declared server a tool belongs to, or None for a host or framework tool."""
    server, separator, rest = tool_name.partition("_")
    return server if separator and rest and server in servers else None


@dataclass
class McpLoad:
    tools: list[BaseTool]
    failed: dict[str, str]


def servers_for_runtime(
    project_root: Path, settings: Settings, runtime: RuntimeName
) -> list[McpServer]:
    """Every MCP server this runtime declares: `config/mcp.toml`'s, then Paper's from `PAPER_*`.

    A Paper setting that cannot be served here leaves Paper out with a warning, never the rest;
    `tools.paper.paper_server` raises the same reason for `doctor` to show.
    """
    from design_agent.tools.paper import SERVER, PaperConfigError, paper_server

    servers = declared_servers(project_root)
    if runtime != "mda":
        for server in servers:
            if server.owner == "user":
                _LOGGER.warning(
                    "[mcp] %s left out: per-person connections need Managed Deep Agents",
                    server.name,
                )
        servers = [server for server in servers if server.owner != "user"]
        servers = [
            replace(server, api_key=settings.langsmith_api_key)
            if MANAGED_TOOLS.match(server.url) and not server.headers_env
            else server
            for server in servers
        ]
    if any(s.name == SERVER for s in servers):
        raise McpConfigError(
            f"config/mcp.toml declares `{SERVER}`; Paper is configured with PAPER_MODE instead"
        )
    try:
        paper = paper_server(settings, runtime=runtime)
    except PaperConfigError as error:
        _LOGGER.warning("[mcp] %s left out: %s", SERVER, error)
        return servers
    return [*servers, paper] if paper is not None else servers


def _transport(server: McpServer, env: Mapping[str, str]) -> Any:
    from fastmcp.client.transports import SSETransport, StdioTransport, StreamableHttpTransport

    if server.transport == "stdio":
        # env=None: the SDK passes only its safe default variables to the child (module doc).
        return StdioTransport(server.command[0], list(server.command[1:]), env=None)
    headers = server.headers(env)
    if headers is None:
        raise McpConfigError("a header it needs is not set in the environment")
    transport_type = StreamableHttpTransport if server.transport == "http" else SSETransport
    return transport_type(server.url, headers=headers)


async def _load_one(server: McpServer, env: Mapping[str, str]) -> list[BaseTool]:
    from langchain.mcp import MCPAdapter

    transport = _transport(server, env)
    async with MCPAdapter(transport) as adapter:
        tools = await adapter.list_tools()
    if server.include_tools is not None:
        tools = [t for t in tools if t.name in server.include_tools]
    return [t.model_copy(update={"name": f"{server.name}_{t.name}"}) for t in tools]


async def load_mcp_tools(
    servers: Sequence[McpServer],
    *,
    env: Mapping[str, str] | None = None,
    loader: Callable[[McpServer, Mapping[str, str]], Awaitable[list[BaseTool]]] = _load_one,
) -> McpLoad:
    """Load every server at once, each with its own deadline; a failure leaves out that one."""
    environ = os.environ if env is None else env

    async def guarded(server: McpServer) -> list[BaseTool] | str:
        try:
            return await asyncio.wait_for(loader(server, environ), timeout=server.timeout)
        except TimeoutError:
            return f"did not answer within {server.timeout:.0f} s"
        except Exception as error:  # noqa: BLE001 - one server never stops the rest
            return str(error) if isinstance(error, McpConfigError) else type(error).__name__

    results = await asyncio.gather(*(guarded(s) for s in servers))
    load = McpLoad(tools=[], failed={})
    for server, result in zip(servers, results, strict=True):
        if isinstance(result, str):
            _LOGGER.warning("[mcp] %s left out: %s", server.name, result)
            load.failed[server.name] = result
        else:
            load.tools.extend(result)
    return load


def mda_declaration(servers: Sequence[McpServer]) -> Any:
    """The `define_mcp` declaration for Managed Deep Agents (`tools/mcp.py`), or None."""
    if not servers:
        return None
    from managed_deepagents import connections, define_mcp

    declared: dict[str, Any] = {}
    for server in servers:
        if server.transport == "stdio":
            _LOGGER.warning(
                "[mcp] %s left out on MDA: it runs over stdio, which MDA does not serve",
                server.name,
            )
            continue
        if (server.headers_env or server.bearer is not None) and server.connection is None:
            _LOGGER.warning(
                "[mcp] %s left out on MDA: name a workspace connection for its credentials",
                server.name,
            )
            continue
        entry: dict[str, Any] = {
            "transport": server.transport,
            "url": server.url,
            "timeout": server.timeout,
        }
        if server.connection is not None:
            entry["connection"] = connections.get(server.connection, {"type": server.owner})
        if server.include_tools is not None:
            entry["include_tools"] = list(server.include_tools)
        declared[server.name] = entry
    return define_mcp(servers=declared, throw_on_load_error=False) if declared else None


class McpToolErrorBoundary(AgentMiddleware[Any, Any, Any]):
    """A call to a declared server's tool that raises comes back as a tool error (module doc)."""

    def __init__(self, servers: Sequence[str]) -> None:
        super().__init__()
        self._servers = frozenset(servers)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        name = str(request.tool_call.get("name") or "")
        server = server_of(name, self._servers)
        if server is None:
            return await handler(request)
        try:
            return await handler(request)
        except GraphBubbleUp:
            raise
        except Exception as error:  # noqa: BLE001 - one service failing never ends the run
            kind = type(error).__name__
            _LOGGER.warning("[mcp] %s raised %s; returned as a tool error", name, kind)
            return ToolMessage(
                content=(
                    f"The {server} service failed on this call ({kind}). Other tools still work; "
                    "try again later or do this step another way."
                ),
                tool_call_id=str(request.tool_call["id"]),
                name=name,
                status="error",
            )
