"""End a turn with the answer so far at the graph's step limit, instead of `GraphRecursionError`.

LangGraph counts steps against `recursion_limit` and raises out of whichever node is running when
it is reached; the run then ends with nothing to show, though its renders sit in the sandbox.
deepagents compiles every graph with `recursion_limit=9_999` and MDA sets none, so a turn takes the
steps its work needs; this only ends it gracefully when the ceiling is a few steps away. Helpers
are their own graph runs and wrap up the same way, reporting to the lead.

The wrap-up is one more model call with tools off and a runtime notice, so the model says what is
finished (with paths), what is not, and the next step. The reply is marked partial in code
(`response_metadata["partial"] = "step_budget"`), never in prose alone, so channels and the next
turn can tell a step-limit stop from an answer. If that call fails too, a fixed note ends the turn.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, NotRequired

from langchain.agents.middleware import AgentMiddleware, AgentState, ModelRequest, ModelResponse
from langchain.agents.middleware.types import PrivateStateAttr
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphBubbleUp
from langgraph.managed.is_last_step import RemainingStepsManager

_LOGGER = logging.getLogger(__name__)

#: Graph steps kept in reserve for the wrap-up turn. Ending a turn from the model node still runs
#: the after-model hooks (HITL, todo list) before END; a full tool round trip costs four steps.
_WRAP_UP_RESERVE_STEPS = 12
PARTIAL_STOP_REASON = "step_budget"
_WRAP_UP_REQUEST = (
    "[Runtime notice, not from the user] This turn has reached the graph's step limit, so tools are "
    "off for this reply. Tell the user what is finished (with file paths), what is not, and the next step."
)
_PARTIAL_MARKER = (
    "_Partial answer: this turn hit the graph's step limit. Everything so far is saved in the thread; "
    "reply **continue** and I'll pick up from here._"
)
_PARTIAL_FALLBACK = "I ran out of steps for this turn before I could write a summary."
#: A helper has no person to say "continue": its reply goes back to the lead as its report, so the
#: marker tells the lead what the stop means instead.
DELEGATED_WRAP_UP_REQUEST = (
    "[Runtime notice] This task has reached the graph's step limit, so tools are off for this reply. Tell the "
    "lead what is finished (with file paths), what is not, and the next step, so the work can continue from "
    "your progress file."
)
DELEGATED_PARTIAL_MARKER = (
    "_Partial: this task hit the graph's step limit. Its progress is on disk; resume it (resume_task) or "
    "start a helper on what is left._"
)


class _StepBudgetState(AgentState):
    # The manager must be the LAST annotation for LangGraph to treat it as a managed value;
    # PrivateStateAttr keeps it out of the graph's input and output schemas.
    remaining_steps: NotRequired[Annotated[int, PrivateStateAttr, RemainingStepsManager]]


def _partial_message(message: AIMessage | None, marker: str = _PARTIAL_MARKER) -> AIMessage:
    """Keep the reply's text, drop any tool call, and mark the turn partial in code, not prose."""
    content = message.content if message is not None else []
    if isinstance(content, str):
        blocks: list[Any] = [{"type": "text", "text": content}] if content.strip() else []
    else:
        keep = {"text", "thinking", "redacted_thinking"}
        blocks = [b for b in content if isinstance(b, dict) and b.get("type") in keep]
    if not any(block.get("type") == "text" for block in blocks):
        blocks.append({"type": "text", "text": _PARTIAL_FALLBACK})
    blocks.append({"type": "text", "text": marker})
    metadata = {**(message.response_metadata if message else {}), "partial": PARTIAL_STOP_REASON}
    if message is None:
        return AIMessage(content=blocks, response_metadata=metadata)
    update = {"content": blocks, "tool_calls": [], "invalid_tool_calls": []}
    return message.model_copy(update={**update, "response_metadata": metadata})


def _no_tool_choice(model: Any) -> Any:
    """Tools off for one call. LangChain reads a bare "none" as a tool NAME for Anthropic (and then
    drops it under thinking), so Anthropic gets its native dict; OpenAI, and so the LangSmith
    gateway's OpenAI dialect, takes the string."""
    return {"type": "none"} if isinstance(model, ChatAnthropic) else "none"


class StepBudgetMiddleware(AgentMiddleware):
    """End the turn with the answer so far when the graph's step limit is nearly spent.

    The limit is the graph's `recursion_limit`, read from `remaining_steps`. There is no budget
    below it, for the agent's own turns or for a delegated worker's.
    """

    state_schema = _StepBudgetState

    def __init__(
        self,
        *,
        reserve_steps: int = _WRAP_UP_RESERVE_STEPS,
        delegated: bool = False,
    ) -> None:
        super().__init__()
        self.reserve_steps = reserve_steps
        # A helper's stop is read by the lead, not a person in the thread.
        self.wrap_up_request = DELEGATED_WRAP_UP_REQUEST if delegated else _WRAP_UP_REQUEST
        self.partial_marker = DELEGATED_PARTIAL_MARKER if delegated else _PARTIAL_MARKER

    def _spent(self, request: ModelRequest) -> tuple[bool, int]:
        """Whether the turn must wrap up now, with the steps remaining."""
        state = request.state if isinstance(request.state, dict) else {}
        remaining = state.get("remaining_steps")
        if not isinstance(remaining, int):
            return False, -1
        return remaining <= self.reserve_steps, remaining

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        spent, remaining = self._spent(request)
        if not spent:
            return await handler(request)
        _LOGGER.warning("[budget] %d graph step(s) left; ending the turn partial", remaining)
        wrap_up = request.override(
            tool_choice=_no_tool_choice(request.model),
            messages=[*request.messages, HumanMessage(content=self.wrap_up_request)],
        )
        try:
            response = await handler(wrap_up)
        except GraphBubbleUp:
            raise
        except Exception as error:  # noqa: BLE001 - the budget stop must end the turn, not raise
            _LOGGER.warning("[budget] wrap-up call failed (%s); fixed note", type(error).__name__)
            return ModelResponse(result=[_partial_message(None, self.partial_marker)])
        # The composed handler always hands middleware a ModelResponse (see langchain's
        # `_normalize_to_model_response`); keep only the reply, marked partial.
        reply = next((m for m in response.result if isinstance(m, AIMessage)), None)
        return ModelResponse(result=[_partial_message(reply, self.partial_marker)])
