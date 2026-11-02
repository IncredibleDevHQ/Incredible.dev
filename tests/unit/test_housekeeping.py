"""The housekeeping run sweeps, tidies expired schedules, and ends before any model call."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from langchain_core.messages import HumanMessage

from design_agent.middleware.housekeeping import MARK, HousekeepingMiddleware, tidy_schedules


class Schedules:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records
        self.deleted: list[str] = []

    async def list(
        self, *, owner: dict[str, str], limit: int, offset: int, include_expired: bool
    ) -> dict[str, Any]:
        page = self.records[offset : offset + limit]
        more = offset + limit < len(self.records)
        return {"items": page, "next_offset": offset + limit if more else None}

    async def delete(self, schedule_id: str, *, owner: dict[str, str]) -> None:
        self.deleted.append(schedule_id)


async def test_only_this_agents_expired_schedules_are_removed() -> None:
    records = [
        {"id": "a", "expired": True, "metadata": {"design_agent": "wake"}},
        {"id": "b", "expired": False, "metadata": {"design_agent": "watchdog"}},
        {"id": "c", "expired": True, "metadata": {}},
        *(
            {"id": f"w{i}", "expired": True, "metadata": {"design_agent": "check-in"}}
            for i in range(150)
        ),
    ]
    schedules = Schedules(records)
    assert await tidy_schedules(schedules) == 151
    assert "b" not in schedules.deleted and "c" not in schedules.deleted


async def test_the_housekeeping_run_ends_in_code() -> None:
    swept: list[object] = []

    class Services:
        async def sweep(self, store: object) -> int:
            swept.append(store)
            return 2

    middleware = HousekeepingMiddleware(Services())  # type: ignore[arg-type]
    runtime = SimpleNamespace(store=object(), schedules=Schedules([]))
    update = await middleware.abefore_agent({"messages": [HumanMessage(MARK)]}, runtime)  # type: ignore[arg-type]
    assert update is not None and update["jump_to"] == "end" and swept
    assert "2 background item(s) swept" in update["messages"][0].content
    assert (
        await middleware.abefore_agent({"messages": [HumanMessage("Make a card.")]}, runtime)
        is None
    )  # type: ignore[arg-type]
