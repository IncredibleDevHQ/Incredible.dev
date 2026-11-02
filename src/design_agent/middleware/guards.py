"""The model-call guards every agent carries, in one order.

Outermost first (each wraps everything after it):

1. `ImageClampMiddleware`: images are normalized before anything else reads the messages.
2. `ModelFailureBoundary` (the lead's alone): what the retry gave up on ends the turn with a line;
   a helper's failure reaches the lead as news instead.
3. `StepBudgetMiddleware`: outside the retry, so a wrap-up call that fails transiently is still
   retried and the step-limit decision is made once per call, not once per attempt.
4. `TransientModelRetryMiddleware`.
5. `SkillListMiddleware`: one line per skill in the resident list.
6. Tool disclosure (only with MCP servers): provider search or a bounded selector.
7. `ToolHistoryMiddleware`: innermost, so it checks history against the final tool list.
8. `UsageMeterMiddleware`: records each completed call.

Tool-call boundaries (`task`, `upload_files`, MCP tools) wrap tool calls, not model calls, so their
place in the list does not matter; they come last.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel

from design_agent.middleware.image_clamp import ImageClampMiddleware
from design_agent.middleware.meter import UsageMeterMiddleware
from design_agent.middleware.model_retry import ModelFailureBoundary, TransientModelRetryMiddleware
from design_agent.middleware.skill_list import SkillListMiddleware
from design_agent.middleware.step_budget import StepBudgetMiddleware
from design_agent.middleware.tool_disclosure import McpToolSelectorMiddleware, ToolSearchMiddleware
from design_agent.middleware.tool_error_boundary import (
    DelegatedTaskErrorBoundary,
    FileDeliveryErrorBoundary,
)
from design_agent.middleware.tool_history import ToolHistoryMiddleware
from design_agent.models.registry import ToolDisclosure
from design_agent.tools.mcp import McpServer, McpToolErrorBoundary


def disclosure_for(
    disclosure: ToolDisclosure,
    servers: Sequence[McpServer],
    selector_model: Callable[[], BaseChatModel],
    max_tools: int,
) -> AgentMiddleware[Any, Any, Any] | None:
    if not servers or disclosure is ToolDisclosure.ALL:
        return None
    names = [s.name for s in servers]
    if disclosure is ToolDisclosure.PROVIDER_NATIVE:
        return ToolSearchMiddleware(
            servers=names, always_shown=[s.name for s in servers if s.always_shown]
        )
    return McpToolSelectorMiddleware(servers=names, model=selector_model(), max_tools=max_tools)


def model_guards(
    *,
    role: str,
    lead: bool,
    summaries: dict[str, str],
    disclosure: AgentMiddleware[Any, Any, Any] | None,
    servers: Sequence[McpServer],
) -> list[AgentMiddleware[Any, Any, Any]]:
    """The ordered guards for one agent (module doc). A fresh instance each: one per graph."""
    guards: list[AgentMiddleware[Any, Any, Any]] = [ImageClampMiddleware()]
    if lead:
        guards.append(ModelFailureBoundary())
    guards += [
        StepBudgetMiddleware(delegated=not lead),
        TransientModelRetryMiddleware(),
        SkillListMiddleware(summaries),
    ]
    if disclosure is not None:
        guards.append(disclosure)
    guards += [ToolHistoryMiddleware(), UsageMeterMiddleware(role)]
    if lead:
        guards += [DelegatedTaskErrorBoundary(), FileDeliveryErrorBoundary()]
    if servers:
        guards.append(McpToolErrorBoundary([s.name for s in servers]))
    return guards
