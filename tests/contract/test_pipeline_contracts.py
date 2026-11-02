"""Real graph: the launch-film pipeline runs its steps as helpers, asks the person before the
final render, and replays finished steps from its memo after the answer (SPEC §7.5)."""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from design_agent.harness import inbox as inbox_module
from design_agent.harness.tasks import REGISTRY
from design_agent.testing.scripted_model import (
    RespondingChatModel,
    ScriptedChatModel,
    reply,
    tool_call,
)
from tests.contract.test_background_contracts import build, latest_human


@pytest.fixture(autouse=True)
def fast(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(inbox_module, "COALESCE_SECONDS", 0.05)
    yield
    REGISTRY.clear()


def first_brief(messages: Sequence[BaseMessage]) -> str:
    return next((str(m.content) for m in messages if isinstance(m, HumanMessage)), "")


ROLES: Counter[str] = Counter()


def helper(messages: Sequence[BaseMessage]) -> AIMessage:
    brief = first_brief(messages)
    if brief.startswith("ROLE\nYou plan the production"):
        ROLES["plan"] += 1
        plan = {
            "acts": [
                {"name": "Act 1: Open", "seconds": 4, "effort": "max", "brief": "briefs/act-1.md"},
                {
                    "name": "Act 2: Proof",
                    "seconds": 4,
                    "effort": "xhigh",
                    "brief": "briefs/act-2.md",
                },
            ],
            "rig": "the stage, the type scale and the timing grid",
        }
        return reply("Planned two acts.\n" + json.dumps(plan))
    if "You are the critic" in brief:
        ROLES["review"] += 1
        return reply('Looks right.\n{"score": 4.5, "pass": true, "issues": []}')
    for role, marker in (
        ("lead", "You are the lead builder"),
        ("render", "You render the approved"),
        ("assembly", "assembl"),
    ):
        if marker in brief:
            ROLES[role] += 1
            break
    else:
        ROLES["other"] += 1
    return reply("Done; files are in the project.")


async def test_launch_film_asks_before_the_final_render_and_replays_after_the_answer(
    tmp_path: Path,
) -> None:
    ROLES.clear()
    questions: list[str] = []

    def on_question(messages: Sequence[BaseMessage]) -> AIMessage:
        notice = latest_human(messages)
        questions.append(notice)
        run_id = re.search(r"\b(p-[0-9a-f]+)\b", notice)
        assert run_id, notice
        return tool_call("answer_pipeline", {"run_id": run_id.group(1), "answer": "approve"})

    finished: list[str] = []

    def on_finish(messages: Sequence[BaseMessage]) -> AIMessage:
        finished.append(latest_human(messages))
        return reply("The final is rendered.")

    lead = ScriptedChatModel(
        steps=[
            lambda _m: tool_call(
                "run_pipeline", {"name": "launch_film", "args_json": '{"project": "teaser"}'}
            ),
            lambda m: reply(
                "Production started."
                if "Started p-" in str(m[-1].content)
                else f"FAILED: {m[-1].content}"
            ),
            on_question,
            lambda m: reply("Approved; rendering." if isinstance(m[-1], ToolMessage) else "?"),
            on_finish,
        ]
    )
    responder = RespondingChatModel(respond=helper)
    runtime, posted = build(tmp_path, lead, max=responder, xhigh=responder, low=responder)
    added = await runtime.ask("Make the launch film.", thread_id="film")
    assert added[-1].content == "Production started."
    for _ in range(600):
        if finished:
            break
        await asyncio.sleep(0.02)
    assert await runtime.settle(timeout_seconds=30, poll_seconds=0.05)
    assert questions and "approve" in questions[0].lower()
    assert finished, "the pipeline woke the lead when it finished"
    assert ROLES["plan"] == 1, "the plan ran once: after the answer it replayed from the memo"
    assert ROLES["lead"] == 1 and ROLES["render"] == 1
    assert ROLES["review"] >= 3, "every act and the final cut were reviewed"
    assert ("film", "The final is rendered.") in posted
