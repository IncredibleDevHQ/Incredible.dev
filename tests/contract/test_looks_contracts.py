"""Real graph: `start_looks` fans one helper out per direction, the last one's end asks the person
to pick, and `pick_look` merges the chosen look and records why (SPEC §7.6)."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from design_agent.harness import inbox as inbox_module
from design_agent.harness.learning import ObservationStore
from design_agent.harness.tasks import REGISTRY
from design_agent.middleware import looks_tools
from design_agent.testing.scripted_model import RespondingChatModel, reply, tool_call, tool_calls
from tests.contract.test_background_contracts import build, latest_human


@pytest.fixture(autouse=True)
def fast(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(inbox_module, "COALESCE_SECONDS", 0.05)
    yield
    REGISTRY.clear()
    looks_tools.WATCHES.clear()


def make_look(messages: Sequence[BaseMessage]) -> AIMessage:
    if isinstance(messages[-1], ToolMessage):
        return reply("The look is in its folder with a still and look.json.")
    brief = next(str(m.content) for m in messages if isinstance(m, HumanMessage))
    look_json = re.search(r"(/workspace/projects/poster/looks/(\w+))/look\.json", brief)
    assert look_json, brief
    folder, look_id = look_json.group(1), look_json.group(2)
    return tool_calls(
        ("write_file", {"file_path": f"{folder}/style.css", "content": f"/* look {look_id} */"}),
        ("write_file", {"file_path": f"{folder}/out/still.txt", "content": "still"}),
        (
            "write_file",
            {
                "file_path": f"{folder}/look.json",
                "content": json.dumps(
                    {"id": look_id, "summary": f"look {look_id}", "stills": ["out/still.txt"]}
                ),
            },
        ),
    )


async def test_looks_fan_out_ping_the_person_and_merge_the_pick(tmp_path: Path) -> None:
    project = tmp_path / "sandbox/workspace/projects/poster"
    project.mkdir(parents=True)
    (project / "index.html").write_text("<h1>poster</h1>")
    pings: list[str] = []
    merged: list[str] = []

    def lead_turn(messages: Sequence[BaseMessage]) -> AIMessage:
        last = messages[-1]
        if isinstance(last, ToolMessage) and last.name == "start_looks":
            return reply(
                "Two looks are being made."
                if "Started 2 looks" in str(last.content)
                else f"FAILED {last.content}"
            )
        if isinstance(last, ToolMessage) and last.name == "pick_look":
            merged.append(str(last.content))
            return reply("Merged look b.")
        notice = latest_human(messages)
        if "ready to compare" in notice and not pings:
            pings.append(notice)
            return tool_call(
                "pick_look",
                {"project_slug": "poster", "look_id": "b", "reason": "calmer, more room"},
            )
        if notice.startswith("Make two looks"):
            return tool_call(
                "start_looks",
                {
                    "project_slug": "poster",
                    "directions": ["kinetic type on black", "quiet grid on paper"],
                    "effort": "xhigh",
                },
            )
        return reply("[quiet]")

    lead = RespondingChatModel(respond=lead_turn)
    runtime, posted = build(tmp_path, lead, xhigh=RespondingChatModel(respond=make_look))
    added = await runtime.ask("Make two looks for the poster.", thread_id="looks")
    assert added[-1].content == "Two looks are being made."
    for _ in range(600):
        if merged:
            break
        await asyncio.sleep(0.02)
    assert await runtime.settle(timeout_seconds=30, poll_seconds=0.05)

    assert pings and "a (kinetic type" in pings[0] and "b (quiet grid" in pings[0]
    assert merged and "Merged look b" in merged[0] and "style.css" in merged[0]
    assert (project / "style.css").read_text() == "/* look b */"
    assert not (project / "look.json").exists() and not (project / "out").exists()
    assert any(p.name.startswith("_backup-") for p in (project / "looks").iterdir())
    observations = await ObservationStore(runtime.graph.store).list("looks")  # type: ignore[arg-type]
    assert any(
        "quiet grid on paper" in o.text and "calmer, more room" in o.text for o in observations
    )
    assert ("looks", "Merged look b.") in posted
