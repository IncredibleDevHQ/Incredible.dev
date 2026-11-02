"""MCP servers: declared once, loaded per process, isolated per server.

Servers are declared in `config/mcp.toml`:

    [servers.docs]
    url = "https://docs.example.com/mcp"
    transport = "http"                      # or "sse"; "stdio" with `command` instead of `url`
    headers_env = { Authorization = "DOCS_MCP_AUTH" }   # header -> host env var
    include_tools = ["search"]              # optional
    timeout = 30                            # seconds per request
    always_shown = false                    # keep its schemas bound instead of deferred

A server's tools are named `{server}_{tool}`. Server names are lowercase letters and digits only,
so a tool name splits on its first underscore without ambiguity (`tools/disclosure` relies on it).

Isolation:
- Loading: each server loads on its own with a deadline; one that fails is reported and left out,
  the rest load.
- Calling: a call that raises comes back as a tool error naming the server
  (`McpToolErrorBoundary`), so one service failing never ends a run.

Credentials stay on the host and out of artifacts: header values are read from the host
environment when the server loads. Nothing reaches the sandbox.

LangSmith's managed tool servers (`https://api.smith.langchain.com/v1/managed-tools/...`, such as
Parallel web search) need no credentials in the config: they are sent the workspace's
`LANGSMITH_API_KEY` as `x-api-key`.

Stdio servers (`transport = "stdio"`, a local app's own CLI) get the MCP SDK's short list of safe
variables (home, path, shell, user), not the host's environment, so provider keys never reach the
child process.
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
    command: tuple[str, ...] = ()
    """A stdio server's executable and arguments (`url` is empty)."""
    api_key: SecretStr | None = field(default=None, repr=False, compare=False)
    """Sent as `x-api-key`: the LangSmith key, for managed tool servers."""

    def headers(self, env: Mapping[str, str]) -> dict[str, str] | None:
        """The headers from the host environment; None when one it names is unset."""
        values = {header: env.get(var, "") for header, var in self.headers_env.items()}
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
    project_root: Path,
    settings: Settings,
    runtime: RuntimeName,  # noqa: ARG001 - every runtime serves the same servers
) -> list[McpServer]:
    """Every MCP server this process serves: `config/mcp.toml`'s.

    LangSmith's managed tool servers get the workspace key (module doc).
    """
    return [
        replace(server, api_key=settings.langsmith_api_key)
        if MANAGED_TOOLS.match(server.url) and not server.headers_env
        else server
        for server in declared_servers(project_root)
    ]


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
