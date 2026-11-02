"""Keep checkpointed history valid against the tools each model request actually carries.

A thread's history is immutable once checkpointed, but the tool surface changes with every deploy
and every MCP server that does or does not load. Anthropic rejects the whole request when history
names a tool that is not in `tools` ("Tool reference '…' not found in available tools"): provider
tool search writes tool names into history, in `tool_search_tool_result` blocks and in
`tool_reference` items inside a `tool_result`, and returns references to bound tools too, so
removing any tool would poison every thread that ever searched. A retry cannot help.

`ToolHistoryMiddleware` sends a valid view of the checkpoint; the checkpoint itself is never
rewritten. On every call it drops references the request cannot satisfy and any server tool call
the provider will never answer (`sanitize_history`). If the provider still rejects the history,
one deeper repair (`repair_history`) removes every server-tool block pair and tool reference
before the latest assistant turn, and folds each answered call to a missing tool there, with an
excerpt of its result, into a text note; the call is retried once, and the repair stays on for
that thread. Only the repair folds calls: a tool can be missing for one run (an MCP server that
did not load), and folding then would cut that server's earlier results down to an excerpt.

The latest assistant turn is every message after the last human one; Anthropic reads its replies
and tool results as one assistant message, and two rules apply to it:
- A tool search made beside client tool calls ends its reply unanswered; the provider runs it at
  the start of the next reply, but only while the turn is open. A human message after the tool
  results (a steer, a budget note) closes the turn, and the search then 400s as a
  `server_tool_use` without its result. So every call drops a server call that can no longer be
  answered: any unanswered one except at the end of the open turn's last reply.
- Its thinking must be sent as the model wrote it ("thinking blocks in the latest assistant
  message cannot be modified"), so the repair leaves that turn as written. Dropping the turn
  instead would make the model redo calls it already made.

A provider 400 is read in-process to tell a history fault (`messages.N`, a tool reference,
`input[N]`) from a code fault (a bad tool schema). `StaleHistoryError` carries fixed text, so the
provider's message never reaches the model or the channel.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

import anthropic
import openai
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.exceptions import ContextOverflowError, ModelInvalidRequestError
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, SystemMessage, ToolMessage
from langgraph.config import get_config

from design_agent.middleware.model_retry import exception_chain

_LOGGER = logging.getLogger(__name__)

# Server-tool blocks are pairs matched by id: the model's call and the provider-produced result.
_SERVER_BLOCK_TYPES = frozenset(
    {
        "server_tool_use",
        "mcp_tool_use",
        "tool_search_tool_result",
        "web_search_tool_result",
        "web_fetch_tool_result",
        "code_execution_tool_result",
        "bash_code_execution_tool_result",
        "text_editor_code_execution_tool_result",
        "mcp_tool_result",
    }
)
_SERVER_CALL_TYPES = frozenset({"server_tool_use", "mcp_tool_use"})
_THINKING_TYPES = frozenset({"thinking", "redacted_thinking"})
_EXCERPT_CHARS = 400
_NO_REFERENCES_TEXT = "No matching tools are available."
# Where a provider's 400 points when history, not code, is the problem: Anthropic locates it under
# `messages.N` or names the tool reference; OpenAI's Responses API points into `input[N]` or at an
# unanswered function call. A bad tool schema (`tools.N...`) or a policy refusal matches none.
_HISTORY_ERROR_MARKERS = ("messages.", "tool reference", "tool_use", "tool_result", "input[")
#: How many threads' "repair up front" flags one process remembers. The graph is compiled once
#: per process in MDA, so the flag is scoped by thread, not by middleware instance.
_REPAIRING_THREADS = 512


@dataclass
class HistoryReport:
    """What one pass changed. An unchanged report means the history was sent as checkpointed."""

    dropped_references: list[str] = field(default_factory=list)
    folded_calls: list[str] = field(default_factory=list)
    dropped_server_blocks: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.dropped_references or self.folded_calls or self.dropped_server_blocks)


def available_tool_names(tools: Iterable[Any]) -> frozenset[str]:
    """Every tool name the request carries, bound or deferred, in LangChain or provider form."""
    names: set[str] = set()
    for tool in tools:
        if isinstance(tool, dict):
            function = tool.get("function")
            name = tool.get("name") or (
                function.get("name") if isinstance(function, dict) else None
            )
        else:
            name = getattr(tool, "name", None)
        if isinstance(name, str) and name:
            names.add(name)
    return frozenset(names)


def sanitize_history(
    messages: Sequence[BaseMessage], available: frozenset[str]
) -> tuple[list[BaseMessage], HistoryReport]:
    """Drop tool references the request cannot satisfy and server calls nothing will answer."""
    return _Rewrite(messages, available, repair=False).run()


def repair_history(
    messages: Sequence[BaseMessage], available: frozenset[str]
) -> tuple[list[BaseMessage], HistoryReport]:
    """Before the latest turn, drop server-tool pairs and references and fold calls to missing
    tools; the latest turn gets only what `sanitize_history` does."""
    return _Rewrite(messages, available, repair=True).run()


class _Rewrite:
    """One pass over a message list. Unchanged messages are passed through by identity."""

    def __init__(
        self, messages: Sequence[BaseMessage], available: frozenset[str], *, repair: bool
    ) -> None:
        self.messages = list(messages)
        self.available = available
        self.repair = repair
        self.deep = False  # whether the message being rewritten gets the repair
        self.report = HistoryReport()
        # The latest assistant turn starts right after the last human message.
        self.turn = next(
            (i + 1 for i in reversed(range(len(self.messages))) if _human(self.messages[i])), 0
        )
        last_reply = max(
            (i for i, m in enumerate(self.messages) if isinstance(m, AIMessage)), default=-1
        )
        blocks = [
            (i, block)
            for i, message in enumerate(self.messages)
            if isinstance(message.content, list)
            for block in message.content
            if isinstance(block, dict)
        ]
        results = {b.get("tool_use_id") for _, b in blocks if b.get("type") in _SERVER_BLOCK_TYPES}
        # A server call with no result will never get one, unless it ends the open turn's last
        # reply: the provider runs that one at the start of the next reply.
        self.unanswered = {
            b.get("id")
            for i, b in blocks
            if b.get("type") in _SERVER_CALL_TYPES
            and b.get("id") not in results
            and not (i == last_reply and i >= self.turn)
        }
        answered = {m.tool_call_id: m for m in self.messages if isinstance(m, ToolMessage)}
        # Only the repair folds, and only answered calls before the latest turn: a call awaiting
        # its result is the tail of an in-flight turn, and folding it would strand that result.
        self.folded: dict[str, ToolMessage] = {}
        if repair:
            for message in self.messages[: self.turn]:
                if not isinstance(message, AIMessage):
                    continue
                for call in message.tool_calls:
                    call_id = call.get("id")
                    if (
                        isinstance(call_id, str)
                        and call.get("name") not in available
                        and call_id in answered
                    ):
                        self.folded[call_id] = answered[call_id]

    def run(self) -> tuple[list[BaseMessage], HistoryReport]:
        out: list[BaseMessage] = []
        for index, message in enumerate(self.messages):
            if isinstance(message, ToolMessage) and message.tool_call_id in self.folded:
                continue  # its content rides in the note that replaced the call
            self.deep = self.repair and index < self.turn
            written = message
            if isinstance(message, AIMessage) and self.folded:
                message = self._fold_calls(message)
            if isinstance(message.content, list):
                rewrite = self._items if isinstance(message, ToolMessage) else self._blocks
                blocks = rewrite(message.content)
                if blocks is not message.content:
                    message = message.model_copy(update={"content": blocks})
            # A reply this pass left without content is omitted, never sent blank; one in the
            # latest turn is kept, since that turn's thinking must reach the provider as written.
            if (
                index < self.turn
                and isinstance(message, AIMessage)
                and self._emptied(message, written)
            ):
                continue
            out.append(message)
        return (out if self.report.changed else self.messages), self.report

    def _fold_calls(self, message: AIMessage) -> AIMessage:
        folded = [call for call in message.tool_calls if call.get("id") in self.folded]
        if not folded:
            return message
        content = message.content
        blocks = (
            list(content)
            if isinstance(content, list)
            else ([{"type": "text", "text": content}] if content.strip() else [])
        )
        folded_ids = {call["id"] for call in folded}
        noted = {b.get("id") for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"}
        blocks = [
            self._note(b["id"], str(b.get("name")))
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id") in folded_ids
            else b
            for b in blocks
        ]
        # A call recorded only in `tool_calls` (string content) still leaves with its result.
        blocks += [
            self._note(str(c["id"]), str(c.get("name"))) for c in folded if c["id"] not in noted
        ]
        kept = [call for call in message.tool_calls if call.get("id") not in folded_ids]
        return message.model_copy(update={"content": blocks, "tool_calls": kept})

    def _emptied(self, message: AIMessage, written: BaseMessage) -> bool:
        return (
            (self.deep or message is not written)
            and not message.tool_calls
            and isinstance(message.content, list)
            and all(
                isinstance(b, dict) and b.get("type") in _THINKING_TYPES for b in message.content
            )
        )

    def _items(self, items: list[Any]) -> list[Any]:
        """A tool result's content, rewritten but never left empty."""
        new = self._blocks(items)
        return new if new is items or new else [{"type": "text", "text": _NO_REFERENCES_TEXT}]

    def _blocks(self, blocks: list[Any]) -> list[Any]:
        """Rewrite one content list; return the same list object when nothing changed."""
        out: list[Any] = []
        changed = False
        for block in blocks:
            new = self._block(block) if isinstance(block, dict) else block
            changed |= new is not block
            if new is not None:
                out.append(new)
        return out if changed else blocks

    def _block(self, block: dict[str, Any]) -> dict[str, Any] | None:
        block_type = block.get("type")
        unanswered = block_type in _SERVER_CALL_TYPES and block.get("id") in self.unanswered
        if unanswered or (self.deep and block_type in _SERVER_BLOCK_TYPES):
            self.report.dropped_server_blocks += 1
            return None
        if block_type == "tool_reference":
            return None if self._drops(block) else block
        if block_type == "tool_search_tool_result":
            result = block.get("content")
            if isinstance(result, dict):
                refs = result.get("tool_references")
                if isinstance(refs, list):
                    kept = [ref for ref in refs if not self._drops(ref)]
                    if len(kept) != len(refs):
                        return {**block, "content": {**result, "tool_references": kept}}
            return block
        if block_type == "tool_result" and isinstance(block.get("content"), list):
            items = self._items(block["content"])
            return block if items is block["content"] else {**block, "content": items}
        return block

    def _drops(self, ref: Any) -> bool:
        """Record and drop a reference the request cannot satisfy (every one the repair reaches)."""
        name = ref.get("tool_name") if isinstance(ref, dict) else None
        if not isinstance(name, str) or (name in self.available and not self.deep):
            return False
        self.report.dropped_references.append(name)
        return True

    def _note(self, call_id: str, name: str) -> dict[str, str]:
        """A plain-text record of a missing tool's call and result, so history stays truthful."""
        self.report.folded_calls.append(name)
        note = f"[Earlier call to `{name}`, a tool that is not available now."
        excerpt = _text_of(self.folded[call_id].content).strip()
        if len(excerpt) > _EXCERPT_CHARS:
            excerpt = excerpt[:_EXCERPT_CHARS].rstrip() + "…"
        if excerpt:
            note += f" It returned: {excerpt}"
        return {"type": "text", "text": note + "]"}


def _human(message: BaseMessage) -> bool:
    """A message the provider sends as user content of its own, not as a tool result."""
    return not isinstance(message, AIMessage | ToolMessage | SystemMessage)


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return " ".join(
        item if isinstance(item, str) else str(item.get("text", ""))
        for item in content
        if isinstance(item, str) or (isinstance(item, dict) and item.get("type") == "text")
    )


class StaleHistoryError(RuntimeError):
    """The provider rejects this thread's history, and the one deeper repair did not fix it.

    Fixed text, raised `from None`: the provider's message is recorded on the failed model call in
    the trace, and must never reach the model or the Slack thread.
    """

    def __init__(self) -> None:
        super().__init__("the model provider rejects this thread's history, even after repair")


def _history_rejection(error: BaseException) -> bool:
    """Whether the provider rejected the request because of its history.

    Reads the provider's message in-process to tell a history fault from a code fault; the text is
    never logged, forwarded, or kept. Context overflow has its own owner (summarization).
    """
    for candidate in exception_chain(error):
        if isinstance(candidate, ContextOverflowError):
            return False
        if isinstance(
            candidate, ModelInvalidRequestError | anthropic.BadRequestError | openai.BadRequestError
        ):
            body = getattr(candidate, "body", None)
            detail = body.get("error", body) if isinstance(body, dict) else None
            parts = [str(getattr(candidate, "message", ""))]
            if isinstance(detail, dict):
                parts += [str(detail.get("message", "")), str(detail.get("param", ""))]
            text = " ".join(parts).lower()
            return any(marker in text for marker in _HISTORY_ERROR_MARKERS)
    return False


def _thread_key() -> str | None:
    """The thread this call belongs to, from the ambient LangGraph config; None outside a graph."""
    try:
        configurable = get_config().get("configurable") or {}
    except RuntimeError:
        return None
    thread_id = configurable.get("thread_id")
    return thread_id if isinstance(thread_id, str) and thread_id else None


class ToolHistoryMiddleware(AgentMiddleware):
    """Send a history the provider accepts; repair and retry once if it still refuses.

    Register it innermost, after anything that changes the tool list, so it compares history
    with the final tool list. MDA compiles the graph once per process, so the "repair already
    needed" flag is kept per thread (bounded): a thread that needed the deep repair gets it up
    front on its later calls instead of a 400 on each, and no other thread pays for it.
    """

    def __init__(self) -> None:
        super().__init__()
        self._repairing: OrderedDict[str | None, bool] = OrderedDict()

    def _repairs(self, key: str | None) -> bool:
        return self._repairing.get(key, False)

    def _remember(self, key: str | None) -> None:
        self._repairing[key] = True
        self._repairing.move_to_end(key)
        while len(self._repairing) > _REPAIRING_THREADS:
            self._repairing.popitem(last=False)

    def _rewrite(self, request: ModelRequest, *, repair: bool) -> ModelRequest:
        rewrite = repair_history if repair else sanitize_history
        try:
            messages, report = rewrite(request.messages, available_tool_names(request.tools))
        except Exception:
            _LOGGER.warning("[history] %s skipped (non-fatal)", rewrite.__name__, exc_info=True)
            return request
        if not report.changed:
            return request
        _LOGGER.info(
            "[history] %s: %d tool reference(s) %s, %d server block(s), %d folded call(s) %s",
            rewrite.__name__,
            len(report.dropped_references),
            sorted(set(report.dropped_references))[:10],
            report.dropped_server_blocks,
            len(report.folded_calls),
            sorted(set(report.folded_calls))[:10],
        )
        return request.override(messages=cast("list[AnyMessage]", messages))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        key = _thread_key()
        repairing = self._repairs(key)
        request = self._rewrite(request, repair=repairing)
        try:
            return await handler(request)
        except Exception as error:
            if not _history_rejection(error):
                raise
            _LOGGER.warning(
                "[history] the provider rejected the history (%s)", type(error).__name__
            )
        # Outside the except block, so nothing logged below can chain the provider's error.
        repaired = None if repairing else self._rewrite(request, repair=True)
        if repaired is None or repaired is request:
            raise StaleHistoryError() from None
        try:
            response = await handler(repaired)
        except Exception as error:
            if not _history_rejection(error):
                raise
            raise StaleHistoryError() from None
        self._remember(key)
        return response
