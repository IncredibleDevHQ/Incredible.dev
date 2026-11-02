"""Real graph: a post-job review saves proposals for the skill, a later thread reads them, and a
rating moves the counts (SPEC §7.7)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from design_agent.harness import inbox as inbox_module
from design_agent.harness.learning import ObservationStore
from design_agent.harness.tasks import REGISTRY
from design_agent.testing.scripted_model import (
    RespondingChatModel,
    ScriptedChatModel,
    reply,
    tool_call,
)
from tests.contract.test_background_contracts import build

NOTE = "The person cuts any intro longer than two seconds; open on the product."


@pytest.fixture(autouse=True)
def fast(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(inbox_module, "COALESCE_SECONDS", 0.05)
    yield
    REGISTRY.clear()


def review(_messages: Sequence[BaseMessage]) -> AIMessage:
    proposal = {
        "skill": "launch-film",
        "observations": [{"text": NOTE, "evidence": ["v2 review: 'skip the intro'"]}],
    }
    return reply("Read the job.\n" + json.dumps(proposal))


async def test_a_job_review_is_saved_read_by_the_next_thread_and_rated(tmp_path: Path) -> None:
    read: list[str] = []

    def after_read(messages: Sequence[BaseMessage]) -> AIMessage:
        read.append(str(messages[-1].content))
        observation_id = re.search(r"\b(o-[0-9a-f]+)\b", read[0])
        assert observation_id, read[0]
        return tool_call(
            "rate_observation",
            {"skill": "launch-film", "id": observation_id.group(1), "helpful": True},
        )

    lead = ScriptedChatModel(
        steps=[
            lambda _m: tool_call(
                "learn_from_job",
                {
                    "skill": "launch-film",
                    "summary": "Made a 30 s launch film; the person cut the intro at v2.",
                },
            ),
            lambda _m: reply("Reviewing the job for next time."),
            lambda _m: reply("[quiet]"),
            lambda _m: tool_call("read_observations", {"skill": "launch-film"}),
            after_read,
            lambda m: reply("Rated." if isinstance(m[-1], ToolMessage) else "?"),
        ]
    )
    runtime, posted = build(tmp_path, lead, low=RespondingChatModel(respond=review))
    await runtime.ask("Wrap up the launch film job.", thread_id="job-1")
    assert await runtime.settle(timeout_seconds=30, poll_seconds=0.05)

    store = runtime.graph.store
    saved = await ObservationStore(store).list("launch-film")
    assert [o.text for o in saved] == [NOTE] and saved[0].status == "proposed"

    added = await runtime.ask("Start a new launch film.", thread_id="job-2")
    assert NOTE in read[0], "a later thread reads what the earlier job showed"
    assert added[-1].content == "Rated."
    (rated,) = await ObservationStore(store).list("launch-film")
    assert rated.helpful == 1 and rated.harmful == 0
    assert posted == [], "the review's end was [quiet]"


async def test_a_configured_learning_model_runs_the_review(tmp_path: Path) -> None:
    from design_agent.config import Settings
    from design_agent.runtime.local import build_local_runtime
    from design_agent.testing.fakes import folder_binding
    from tests.contract.test_background_contracts import ROOT

    lead = ScriptedChatModel(
        steps=[
            lambda _m: tool_call(
                "learn_from_job", {"skill": "launch-film", "summary": "A film; the intro was cut."}
            ),
            lambda _m: reply("Reviewing."),
            lambda _m: reply("[quiet]"),
        ]
    )
    reviewer = RespondingChatModel(respond=review)
    settings = Settings(
        _env_file=None, workspace_root=tmp_path / "ws", learning_model="anthropic:claude-haiku-5-5"
    )  # type: ignore[call-arg]
    runtime = build_local_runtime(
        settings,
        ROOT,
        model=lead,
        role_models={"learning": reviewer},
        binding=folder_binding(tmp_path / "sb", ROOT),
        replies=lambda *_: None,
    )
    await runtime.ask("Wrap up.", thread_id="job-3")
    assert await runtime.settle(timeout_seconds=30, poll_seconds=0.05)
    assert reviewer.call_count >= 1, "the review ran on the learning model"
    assert [o.text for o in await ObservationStore(runtime.graph.store).list("launch-film")] == [
        NOTE
    ]
