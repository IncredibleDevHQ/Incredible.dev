"""A scripted chat model: deterministic tool calls and prose through the real graph, no network."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

Step = Callable[[Sequence[BaseMessage]], AIMessage]


def tool_call(name: str, args: dict[str, Any], *, content: str = "") -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=[
            {"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:12]}", "type": "tool_call"}
        ],
    )


def tool_calls(*calls: tuple[str, dict[str, Any]], content: str = "") -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=[
            {"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:12]}", "type": "tool_call"}
            for name, args in calls
        ],
    )


def reply(text: str) -> AIMessage:
    return AIMessage(content=text)


def last_tool_results(messages: Sequence[BaseMessage]) -> list[ToolMessage]:
    """Tool messages since the last AI message, oldest first."""
    found: list[ToolMessage] = []
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            break
        if isinstance(message, ToolMessage):
            found.append(message)
    found.reverse()
    return found


def last_json(messages: Sequence[BaseMessage]) -> dict[str, Any]:
    """The first JSON object printed in the latest tool results (gate summaries print one)."""
    for message in last_tool_results(messages):
        for line in str(message.content).splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
    return {}


class ScriptedChatModel(BaseChatModel):
    """Runs a fixed list of steps. Each step sees the conversation and returns one AIMessage."""

    steps: list[Step]
    provider_name: str = "scripted"
    model_name: str = "demo"
    bound_tool_batches: list[list[dict[str, Any]]] = []
    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    def _get_ls_params(self, stop: list[str] | None = None, **kwargs: Any) -> Any:  # noqa: ARG002
        return {
            "ls_provider": self.provider_name,
            "ls_model_name": self.model_name,
            "ls_model_type": "chat",
        }

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,  # noqa: ARG002 - provider signature
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        formatted = [t if isinstance(t, dict) else convert_to_openai_tool(t) for t in tools]
        self.bound_tool_batches.append(formatted)
        return self.bind(tools=formatted, **kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,  # noqa: ARG002 - provider signature
        run_manager: CallbackManagerForLLMRun | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ChatResult:
        index = self.call_count
        self.call_count += 1
        message = (
            self.steps[index](messages)
            if index < len(self.steps)
            else AIMessage(content="Script exhausted.")
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


class RespondingChatModel(ScriptedChatModel):
    """Answers every call with the same function (helpers whose reply depends on their brief)."""

    respond: Step
    steps: list[Step] = []

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,  # noqa: ARG002 - provider signature
        run_manager: CallbackManagerForLLMRun | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ChatResult:
        self.call_count += 1
        return ChatResult(generations=[ChatGeneration(message=self.respond(messages))])
