"""The housekeeping run: sweep, tidy, end in code before any model call.

A deployment-level schedule (`schedules/housekeeping.py` on MDA; the self-hosted process runs the
same sweep on a timer) starts a run whose whole prompt is `<housekeeping>`. This middleware, first
in the list, recognizes it in `before_agent` and:

- sweeps the ledger (`BackgroundServices.sweep`): helpers, watches and pipelines a restart killed
  are published as interrupted, and finished work whose notice a restart swallowed is published
  again, so each thread's lead hears of it on its next turn (on MDA a thread's own sentinel
  schedule is what wakes it; a housekeeping run cannot schedule into another thread);
- deletes this agent's expired one-time schedules (wake-ups, check-ins, sentinels), which no
  longer count against the per-owner cap but would otherwise pile up in listings;

then ends the run with a one-line summary that no channel receives. A person who types the marker
gets the same: a sweep and no model call, which is harmless.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from design_agent.middleware.background import BackgroundServices
from design_agent.middleware.quiet import latest_human

_LOGGER = logging.getLogger(__name__)

MARK = "<housekeeping>"
#: Agent-owned schedules this agent creates carry this metadata key (`runtime/waker/mda.py`).
METADATA_KEY = "design_agent"


async def tidy_schedules(schedules: Any, *, owner: dict[str, str] | None = None) -> int:
    """Delete this agent's expired one-time schedules; returns how many."""
    owner = owner or {"type": "agent"}
    removed, offset = 0, 0
    while True:
        page = await schedules.list(owner=owner, limit=100, offset=offset, include_expired=True)
        for record in page.get("items", []):
            if record.get("expired") and METADATA_KEY in (record.get("metadata") or {}):
                try:
                    await schedules.delete(record["id"], owner=owner)
                    removed += 1
                except Exception as error:  # noqa: BLE001 - the next pass tries again
                    _LOGGER.warning(
                        "[housekeeping] a schedule was not deleted: %s", type(error).__name__
                    )
        offset = page.get("next_offset") or 0
        if not offset:
            return removed


class HousekeepingMiddleware(AgentMiddleware[AgentState[Any], Any, Any]):
    """Recognize the housekeeping run and do it in code (module doc)."""

    def __init__(self, services: BackgroundServices | None) -> None:
        super().__init__()
        self._services = services

    @property
    def name(self) -> str:
        return "DesignAgentHousekeeping"

    @hook_config(can_jump_to=["end"])
    async def abefore_agent(
        self, state: AgentState[Any], runtime: Runtime[Any]
    ) -> dict[str, Any] | None:
        if latest_human(list(state.get("messages") or [])).strip() != MARK:
            return None
        swept = tidied = 0
        store = getattr(runtime, "store", None)
        if self._services is not None and store is not None:
            try:
                swept = await self._services.sweep(store)
            except Exception as error:  # noqa: BLE001 - the next pass tries again
                _LOGGER.warning("[housekeeping] the sweep failed: %s", type(error).__name__)
        schedules = getattr(runtime, "schedules", None)
        if schedules is not None:
            try:
                tidied = await tidy_schedules(schedules)
            except Exception as error:  # noqa: BLE001 - listing can fail outside a channel; harmless
                _LOGGER.warning(
                    "[housekeeping] schedules were not tidied: %s", type(error).__name__
                )
        summary = (
            f"Housekeeping: {swept} background item(s) swept, {tidied} expired schedule(s) removed."
        )
        return {"messages": [AIMessage(content=summary)], "jump_to": "end"}
