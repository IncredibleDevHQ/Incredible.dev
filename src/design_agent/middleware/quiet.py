"""`[quiet]`: a wake-up turn with nothing worth saying.

A wake-up's reply is posted by whoever started the turn, and the runtimes differ in what they
can leave unsaid:

- Local and self-hosted runtimes post a wake-up's reply themselves and drop a reply of exactly
  `[quiet]` (`harness.notices.should_post`). Nothing here is needed for that.
- Managed Deep Agents 0.9.3 posts a scheduled run's reply from its own `after_agent` hook, which it
  installs ahead of every authored middleware, so it runs last and cannot be skipped: a jump to
  "end" from an `after_agent` hook re-enters the `after_agent` chain in langchain 1.4, and the
  hook posts the newest non-empty assistant text in the thread, so an empty reply would repost an
  earlier one. On that runtime a final `[quiet]` is rewritten, in code, into one line about the
  work still running (`status`), which is what the person sees instead of a bare marker.

A restart watchdog (sentinel) turn on a thread whose work still runs in this process has nothing
to report either: it ends before the model is called, with `[quiet]`, which the above handles.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from design_agent.harness import tasks
from design_agent.harness.notices import QUIET

SENTINEL_MARK = "<watchdog"
_MARK = re.compile(r"<watchdog\b[^>]*>")


def latest_human(messages: list[Any]) -> str:
    """The newest input's text, passing over date notes (`middleware/today.py`)."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage) and str(message.id or "").startswith("today:"):
            continue
        if isinstance(message, HumanMessage):
            return message.text if isinstance(message.text, str) else str(message.content)
        if isinstance(message, AIMessage):
            return ""
    return ""


def final_reply(messages: list[Any]) -> str:
    if messages and isinstance(messages[-1], AIMessage) and not messages[-1].tool_calls:
        return str(messages[-1].text).strip()
    return ""


def is_watchdog_turn(messages: list[Any]) -> bool:
    return bool(_MARK.search(latest_human(messages)))


def running_status(thread_id: str) -> str:
    """One line about the thread's running helpers, for a quiet turn that must still post."""
    now = time.time()
    running = tasks.running(thread_id)
    if not running:
        return "Nothing new since my last message."
    parts = [f"{r.label} ({max(1, round((now - r.started_at) / 60))} min)" for r in running[:4]]
    more = f" and {len(running) - 4} more" if len(running) > 4 else ""
    return f"Still working: {', '.join(parts)}{more}. I'll post when it lands."


class QuietReplyMiddleware(AgentMiddleware[AgentState[Any], Any, Any]):
    """Ends quiet turns cheaply, and rewrites `[quiet]` where the runtime always posts (module doc).

    `still_running(thread_id)` says whether this process still runs work for the thread.
    `status(thread_id)`, when given, replaces a final `[quiet]`.
    """

    def __init__(
        self,
        still_running: Callable[[str], bool],
        thread_of: Callable[[], str],
        status: Callable[[str], str] | None = None,
    ) -> None:
        super().__init__()
        self._still_running = still_running
        self._thread_of = thread_of
        self._status = status

    @property
    def name(self) -> str:
        return "DesignAgentQuietReply"

    @hook_config(can_jump_to=["end"])
    def before_agent(self, state: AgentState[Any], runtime: Runtime[Any]) -> dict[str, Any] | None:  # noqa: ARG002 - hook signature
        messages = list(state.get("messages") or [])
        if is_watchdog_turn(messages) and self._still_running(self._thread_of()):
            return {"messages": [AIMessage(content=QUIET)], "jump_to": "end"}
        return None

    async def abefore_agent(
        self, state: AgentState[Any], runtime: Runtime[Any]
    ) -> dict[str, Any] | None:
        return self.before_agent(state, runtime)

    def after_agent(self, state: AgentState[Any], runtime: Runtime[Any]) -> dict[str, Any] | None:  # noqa: ARG002 - hook signature
        if self._status is None:
            return None
        messages = list(state.get("messages") or [])
        if final_reply(messages) != QUIET:
            return None
        return {
            "messages": [AIMessage(content=self._status(self._thread_of()), id=messages[-1].id)]
        }

    async def aafter_agent(
        self, state: AgentState[Any], runtime: Runtime[Any]
    ) -> dict[str, Any] | None:
        return self.after_agent(state, runtime)
