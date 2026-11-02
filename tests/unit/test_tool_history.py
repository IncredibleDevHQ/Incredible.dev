"""History repair against the two provider rules about the latest assistant turn.

Anthropic reads every message after the last human one as one assistant message: a tool search
left at the end of that turn's last reply is answered at the start of the next reply, and that
turn's thinking must be sent exactly as written. Earlier turns can be rewritten.
"""

from __future__ import annotations

from typing import Any

import anthropic
import httpx
import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from design_agent.middleware.tool_history import (
    StaleHistoryError,
    ToolHistoryMiddleware,
    repair_history,
    sanitize_history,
)

TOOLS = frozenset({"ls", "read_file", "tool_search_tool_bm25"})


def thinking(text: str) -> dict[str, Any]:
    return {"type": "thinking", "thinking": text, "signature": f"sig-{text}"}


def search(call_id: str) -> dict[str, Any]:
    return {
        "type": "server_tool_use",
        "id": call_id,
        "name": "tool_search_tool_bm25",
        "input": {"query": "paper"},
    }


def search_result(call_id: str, *names: str) -> dict[str, Any]:
    refs = [{"type": "tool_reference", "tool_name": name} for name in names]
    return {
        "type": "tool_search_tool_result",
        "tool_use_id": call_id,
        "content": {"type": "tool_search_tool_search_result", "tool_references": refs},
    }


def tool_use(call_id: str, name: str) -> dict[str, Any]:
    return {"type": "tool_use", "id": call_id, "name": name, "input": {}}


def reply(*blocks: dict[str, Any]) -> AIMessage:
    calls = [
        {"id": b["id"], "name": b["name"], "args": {}, "type": "tool_call"}
        for b in blocks
        if b["type"] == "tool_use"
    ]
    return AIMessage(content=list(blocks), tool_calls=calls)


def result(call_id: str, text: str = "ok") -> ToolMessage:
    return ToolMessage(content=text, tool_call_id=call_id)


def server_ids(messages: list[BaseMessage]) -> list[str]:
    return [
        b["id"]
        for m in messages
        if isinstance(m.content, list)
        for b in m.content
        if isinstance(b, dict) and b.get("type") == "server_tool_use"
    ]


def deferred_search_turn() -> list[BaseMessage]:
    """A first reply that ran two tools and left a search for the next reply, as in prod."""
    return [
        HumanMessage("make the deck"),
        reply(thinking("plan"), tool_use("c1", "ls"), tool_use("c2", "read_file"), search("s1")),
        result("c1"),
        result("c2"),
    ]


def test_a_search_left_at_the_end_of_the_open_turn_is_sent_for_the_provider_to_answer() -> None:
    messages = deferred_search_turn()
    sent, report = sanitize_history(messages, TOOLS)
    assert sent == messages and not report.changed


def test_a_human_message_after_the_tool_results_closes_the_turn_and_drops_the_search() -> None:
    messages = [*deferred_search_turn(), HumanMessage("also make it blue")]
    sent, report = sanitize_history(messages, TOOLS)
    assert server_ids(sent) == [] and report.dropped_server_blocks == 1
    assert [b["type"] for b in sent[1].content] == ["thinking", "tool_use", "tool_use"]  # type: ignore[union-attr]


def test_a_later_reply_means_the_earlier_unanswered_search_will_never_be_answered() -> None:
    messages = [
        *deferred_search_turn(),
        reply(thinking("next"), tool_use("c3", "ls")),
        result("c3"),
    ]
    sent, _ = sanitize_history(messages, TOOLS)
    assert server_ids(sent) == []


def test_references_to_missing_tools_are_dropped_and_bound_ones_kept() -> None:
    messages = [
        HumanMessage("hi"),
        reply(search("s1"), search_result("s1", "read_file", "paper_gone")),
        HumanMessage("next"),
    ]
    sent, report = sanitize_history(messages, TOOLS)
    refs = sent[1].content[1]["content"]["tool_references"]  # type: ignore[index]
    assert [r["tool_name"] for r in refs] == ["read_file"]
    assert report.dropped_references == ["paper_gone"]


def latest_turn_with_interleaved_searches() -> list[BaseMessage]:
    return [
        HumanMessage("first ask"),
        reply(search("old"), search_result("old", "read_file"), tool_use("c0", "gone_tool")),
        result("c0", "earlier output"),
        HumanMessage("second ask"),
        reply(
            thinking("a"),
            search("s1"),
            search_result("s1", "read_file"),
            thinking("b"),
            search("s2"),
            search_result("s2", "ls"),
            thinking("c"),
            tool_use("c1", "ls"),
        ),
        result("c1"),
    ]


def test_the_repair_leaves_the_latest_turn_exactly_as_written() -> None:
    messages = latest_turn_with_interleaved_searches()
    sent, report = repair_history(messages, TOOLS)
    assert sent[-2:] == messages[-2:]
    assert sent[-2] is messages[-2], "the latest reply's thinking reaches the provider as written"
    assert "old" not in server_ids(sent) and report.dropped_server_blocks == 2


def test_the_repair_folds_answered_calls_to_missing_tools_only_before_the_latest_turn() -> None:
    messages = latest_turn_with_interleaved_searches()
    sent, report = repair_history(messages, TOOLS)
    assert report.folded_calls == ["gone_tool"]
    assert not any(isinstance(m, ToolMessage) and m.tool_call_id == "c0" for m in sent)
    note = sent[1].content[0]["text"]  # type: ignore[index]
    assert "gone_tool" in note and "earlier output" in note


def rejection(message: str) -> anthropic.BadRequestError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(400, request=request)
    body = {"error": {"type": "invalid_request_error", "message": message}}
    return anthropic.BadRequestError(message, response=response, body=body)


class FakeRequest:
    def __init__(self, messages: list[BaseMessage]) -> None:
        self.messages = messages
        self.tools = [{"name": name} for name in sorted(TOOLS)]

    def override(self, **changes: Any) -> FakeRequest:
        return FakeRequest(changes.get("messages", self.messages))


async def test_a_thread_already_repairing_keeps_its_latest_turn_whole_on_the_first_try() -> None:
    middleware = ToolHistoryMiddleware()
    messages = latest_turn_with_interleaved_searches()
    seen: list[list[BaseMessage]] = []

    async def provider(request: Any) -> str:
        seen.append(request.messages)
        latest = request.messages[-2]
        if latest is not messages[-2]:
            raise rejection(
                "messages.3.content.7: thinking blocks in the latest assistant message cannot be modified"
            )
        if "old" in server_ids(request.messages):
            raise rejection("messages.1: tool reference 'read_file' needs a repair")
        return "ok"

    assert await middleware.awrap_model_call(FakeRequest(messages), provider) == "ok"  # type: ignore[arg-type]
    assert len(seen) == 2, "one rejection, one repaired retry"
    seen.clear()
    assert await middleware.awrap_model_call(FakeRequest(messages), provider) == "ok"  # type: ignore[arg-type]
    assert len(seen) == 1, "the repair stays on for the thread and passes first time"


async def test_a_history_the_repair_cannot_fix_raises_fixed_text() -> None:
    async def provider(_request: Any) -> str:
        raise rejection("messages.0: something about tool_use the repair cannot fix")

    with pytest.raises(StaleHistoryError, match="even after repair"):
        await ToolHistoryMiddleware().awrap_model_call(
            FakeRequest(latest_turn_with_interleaved_searches()),  # type: ignore[arg-type]
            provider,
        )
