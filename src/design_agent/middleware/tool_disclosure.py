"""Progressive schema disclosure: MCP tool schemas load on demand, host tools stay bound.

Every tool stays registered with the graph; this changes what the model sees on each call, never
what it may run. Approval (`interrupt_on`) and policy act on a tool call's name, not its schema, so
a deferred tool is gated exactly as a bound one is. Selection is not authorization.

The rule is evaluated per request against `request.tools`, because Managed Deep Agents appends
connector tools at runtime: a tool named `{server}_{tool}` for a declared MCP server
(`tools/mcp.py`) is disclosed on demand; host tools and the framework's own are always bound.

- Models with provider-native tool search (verified Anthropic and OpenAI models in the capability
  registry): MCP tools are marked `defer_loading` and the provider's search tool is added. Search
  is lexical over names and descriptions and does not split a name into words, so each deferred
  tool's description opens with a header naming it in plain words ("search sound effects"),
  whatever its server wrote. Servers marked `always_shown` stay bound.
- Other models: a bounded `LLMToolSelectorMiddleware` picks at most `max_tools` MCP tools per call
  from the latest request, using the tool-selector role's model. Host tools are never candidates,
  so they are never dropped.
- No MCP tools in the request: nothing changes.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from typing import Any

from langchain.agents.middleware import LLMToolSelectorMiddleware, ProviderToolSearchMiddleware
from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from design_agent.tools.mcp import server_of

#: The keys Anthropic accepts back on a `tool_search_tool_result` block. The streamed block carries
#: fields the API rejects on the way in, so they are stripped before it re-enters history.
TOOL_SEARCH_RESULT_SEND_KEYS = frozenset({"type", "content", "tool_use_id", "cache_control"})
_WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def search_header(tool_name: str, server: str) -> str:
    """What search matches a deferred tool on: its bare name, that name as words, and its full name.
    `docs_SearchPages` on server `docs` gives "SearchPages: docs search pages (docs_SearchPages)."
    """
    bare = tool_name[len(server) + 1 :] or tool_name
    words = " ".join(_WORD.findall(f"{server} {bare.replace('_', ' ')}")).lower()
    return f"{bare}: {words} ({tool_name})."


def sanitize_tool_search_results(messages: Sequence[Any]) -> tuple[list[Any], bool]:
    """Strip stream-only fields before Anthropic search result blocks re-enter request history.
    Returns the messages and whether anything changed; untouched messages keep their identity."""
    sanitized: list[Any] = []
    changed = False
    for message in messages:
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            sanitized.append(message)
            continue
        new_content: list[Any] = []
        message_changed = False
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_search_tool_result":
                cleaned = {k: v for k, v in block.items() if k in TOOL_SEARCH_RESULT_SEND_KEYS}
                new_content.append(cleaned)
                message_changed |= cleaned != block
            else:
                new_content.append(block)
        if message_changed:
            sanitized.append(message.model_copy(update={"content": new_content}))
            changed = True
        else:
            sanitized.append(message)
    return sanitized, changed


class ToolSearchMiddleware(ProviderToolSearchMiddleware):
    """Defer declared servers' tools behind provider-native search, decided per request."""

    def __init__(self, *, servers: Collection[str], always_shown: Collection[str] = ()) -> None:
        super().__init__()
        self._servers = frozenset(servers)
        self._always_shown = frozenset(always_shown)

    def _server(self, tool: BaseTool | dict[str, Any]) -> str | None:
        return server_of(tool.name, self._servers) if isinstance(tool, BaseTool) else None

    def _defers(self, tool: BaseTool | dict[str, Any]) -> bool:
        server = self._server(tool)
        return server is not None and server not in self._always_shown

    def _prepare_request(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        messages, changed = sanitize_tool_search_results(request.messages)
        if changed:
            request = request.override(messages=messages)
        if any(self._defers(tool) for tool in request.tools):
            request = request.override(
                tools=[
                    self._deferred(tool) if self._defers(tool) else tool for tool in request.tools
                ]
            )
        return super()._prepare_request(request)

    def _deferred(self, tool: BaseTool | dict[str, Any]) -> BaseTool | dict[str, Any]:
        """A copy marked `defer_loading` whose description opens with its search header."""
        if not isinstance(tool, BaseTool):
            return tool
        server = self._server(tool) or ""
        header = search_header(tool.name, server)
        description = (
            tool.description
            if tool.description.startswith(header)
            else f"{header}\n{tool.description}"
        )
        extras = {**(tool.extras or {}), "defer_loading": True}
        return tool.model_copy(update={"description": description, "extras": extras})


class McpToolSelectorMiddleware(LLMToolSelectorMiddleware):
    """Pick at most `max_tools` MCP tools per call; host tools are never candidates (module doc)."""

    def __init__(
        self, *, servers: Collection[str], model: BaseChatModel, max_tools: int = 8
    ) -> None:
        super().__init__(model=model, max_tools=max_tools)
        self._servers = frozenset(servers)

    def _mcp(self, tool: Any) -> bool:
        return isinstance(tool, BaseTool) and server_of(tool.name, self._servers) is not None

    def _prepare_selection_request(self, request: ModelRequest[Any]) -> Any:
        candidates = [tool for tool in request.tools if self._mcp(tool)]
        if len(candidates) <= (self.max_tools or 0):
            return None
        return super()._prepare_selection_request(request.override(tools=candidates))

    def _process_selection_response(
        self,
        response: dict[str, Any],
        available_tools: list[BaseTool],
        valid_tool_names: list[str],
        request: ModelRequest[Any],
        *,
        apply_max_tools: bool = True,
    ) -> ModelRequest[Any]:
        chosen = super()._process_selection_response(
            response, available_tools, valid_tool_names, request, apply_max_tools=apply_max_tools
        )
        picked = {tool.name for tool in chosen.tools if isinstance(tool, BaseTool)}
        # The request's own order, so the tools array stays stable for the prompt cache.
        return chosen.override(
            tools=[
                t
                for t in request.tools
                if not self._mcp(t) or (isinstance(t, BaseTool) and t.name in picked)
            ]
        )
