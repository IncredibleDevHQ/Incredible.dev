"""Real graph: detached render jobs wake the lead on exit, failure and stall (SPEC §7.7)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, BaseMessage

from design_agent.harness import inbox as inbox_module
from design_agent.harness.tasks import REGISTRY
from design_agent.middleware import watch_tools
from design_agent.testing.scripted_model import ScriptedChatModel, reply, tool_call
from tests.contract.test_background_contracts import build, latest_human


@pytest.fixture(autouse=True)
def fast(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(inbox_module, "COALESCE_SECONDS", 0.05)
    monkeypatch.setattr(watch_tools, "POLL_SECONDS", 0.05)
    yield
    REGISTRY.clear()


def lead_for(command: str, notices: list[str], **job: object) -> ScriptedChatModel:
    def on_wake(messages: Sequence[BaseMessage]) -> AIMessage:
        notices.append(latest_human(messages))
        return reply("noted")

    return ScriptedChatModel(
        steps=[
            lambda _m: tool_call(
                "start_render_job", {"command": command, "label": "teaser", **job}
            ),
            lambda _m: reply("Rendering the teaser."),
            on_wake,
        ]
    )


@pytest.mark.parametrize(
    ("command", "job", "expected"),
    [
        ("echo frame 1; echo frame 2", {"kind": "heartbeat"}, "finished"),
        ("echo boom >&2; exit 3", {"kind": "heartbeat"}, "exit"),
        ("sleep 30", {"kind": "heartbeat", "stall_minutes": 0.003}, "no progress"),
    ],
    ids=["exit-0", "failure", "stall"],
)
async def test_render_job_wakes_the_lead(
    tmp_path: Path, command: str, job: dict[str, object], expected: str
) -> None:
    notices: list[str] = []
    runtime, _ = build(tmp_path, lead_for(command, notices, **job))
    await runtime.ask("Render the teaser.", thread_id=f"job-{expected}")
    for _ in range(400):
        if notices:
            break
        await __import__("asyncio").sleep(0.025)
    for record in list(watch_tools.WATCHES.list(f"job-{expected}")):
        watch_tools.stop(record.id, f"job-{expected}")
    assert notices, "the lead was woken"
    assert "teaser" in notices[0]
    assert expected in notices[0].lower(), notices[0]
