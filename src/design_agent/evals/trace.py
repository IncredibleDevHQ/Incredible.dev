"""A run's trace: the person's turns, the agent's replies and every tool call, in order."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage


@dataclass(frozen=True)
class Call:
    index: int
    name: str
    args: dict[str, Any]
    ok: bool
    result: str

    @property
    def command(self) -> str:
        return str(self.args.get("command") or "") if self.name == "execute" else ""


#: How a turn the person did not start opens: the inbox's notice (`harness.notices`), and the
#: marker MDA's waker adds (`runtime.waker`).
WOKEN = re.compile(r"^\[Runtime notice, not from the user\]|<wake key=")


@dataclass
class Trace:
    calls: list[Call] = field(default_factory=list)
    replies: list[str] = field(default_factory=list)
    """The agent's final words of each turn the person saw (wake-up replies included)."""
    check_ins: list[str] = field(default_factory=list)
    """The final words of woken turns that delivered no files: check-ins and progress notes."""

    @classmethod
    def from_messages(
        cls, messages: Sequence[BaseMessage], extra_replies: Sequence[str] = ()
    ) -> Trace:
        results = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
        trace = cls()
        index = 0
        woken = delivered = False
        for position, message in enumerate(messages):
            if isinstance(message, HumanMessage):
                woken, delivered = bool(WOKEN.search(message.text)), False
            if isinstance(message, AIMessage):
                for call in message.tool_calls:
                    delivered |= call.get("name") == "upload_files"
                    result = results.get(str(call.get("id")))
                    trace.calls.append(
                        Call(
                            index=index,
                            name=str(call.get("name")),
                            args=dict(call.get("args") or {}),
                            ok=result is not None
                            and result.status != "error"
                            and "exit code 1" not in str(result.content)[-200:],
                            result=str(result.content) if result is not None else "",
                        )
                    )
                    index += 1
                following = messages[position + 1] if position + 1 < len(messages) else None
                if (
                    not message.tool_calls
                    and message.text.strip()
                    and (following is None or isinstance(following, HumanMessage))
                ):
                    trace.replies.append(message.text.strip())
                    if woken and not delivered:
                        trace.check_ins.append(message.text.strip())
        # A woken turn's final words are in the history and may also have been posted: once each.
        trace.replies.extend(reply for reply in extra_replies if reply not in trace.replies)
        return trace

    def first(self, predicate: Any) -> int | None:
        return next((c.index for c in self.calls if predicate(c)), None)

    def named(self, name: str) -> list[Call]:
        return [c for c in self.calls if c.name == name]
