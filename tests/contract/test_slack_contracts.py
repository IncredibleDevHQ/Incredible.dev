"""Real graph, scripted models, a folder sandbox and a fake Slack: progress, footer and steering.

These pin SPEC §7.11 and §14.1: a run's steps stream as cards into one message that settles; a
`[quiet]` turn leaves no progress message; a person's follow-up while a helper works is passed to
that helper, which takes it at its next model call, and the helper streams a message of its own;
a reply while work runs gets a live footer.

The graph is the shared assembly with the Slack middleware added the way a runtime adapter adds
them (lead list and every helper's list), without changing the assembly.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, BaseMessage

from design_agent.assembly import build_agent_components
from design_agent.config import Settings
from design_agent.harness import inbox as inbox_module
from design_agent.harness.tasks import REGISTRY
from design_agent.middleware import footer as footer_module
from design_agent.middleware.background import BackgroundServices
from design_agent.middleware.footer import ReplyFooterMiddleware
from design_agent.middleware.steering import (
    RUNNING_NOTE,
)
from design_agent.runtime.local import LocalRuntime, compile_graph, local_profile
from design_agent.runtime.waker.local import InProcessWaker
from design_agent.surfaces.slack.target import SlackSurface
from design_agent.testing.fake_slack import BOT, FakeResolver, FakeSlack
from design_agent.testing.fakes import folder_binding
from design_agent.testing.scripted_model import ScriptedChatModel, reply, tool_call

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def fast(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(inbox_module, "COALESCE_SECONDS", 0.05)
    monkeypatch.setattr(inbox_module, "RETRY_SECONDS", (0.05, 0.05, 0.05))
    monkeypatch.setattr(footer_module, "REPLY_CHECKS", (0.3, 0.6))
    monkeypatch.setattr(footer_module, "REFRESH_SECONDS", 0.05)
    yield
    REGISTRY.clear()


def build(
    tmp_path: Path, fake: FakeSlack, lead: ScriptedChatModel, **roles: ScriptedChatModel
) -> tuple[LocalRuntime, ReplyFooterMiddleware]:
    """The local runtime with the Slack middleware wired in (module doc)."""
    settings = Settings(_env_file=None, workspace_root=tmp_path / "ws")  # type: ignore[call-arg]
    binding = folder_binding(tmp_path / "sandbox", ROOT)
    holder: list[LocalRuntime] = []

    async def run_turn(thread_id: str, message: str, started: asyncio.Event) -> None:
        await holder[0].wake_turn(thread_id, message, started)

    waker = InProcessWaker(run_turn)
    services = BackgroundServices(waker=waker, capture_target=waker.capture)
    surface = SlackSurface(FakeResolver(fake))
    profile = local_profile(ROOT, binding, tmp_path / "out", services, slack=surface, surface="cli")
    components = build_agent_components(
        settings=settings, runtime=profile, model=lead, role_models=roles
    )
    footer = next(m for m in components.middleware if isinstance(m, ReplyFooterMiddleware))
    runtime = LocalRuntime(
        settings=settings,
        project_root=ROOT,
        binding=binding,
        components=components,
        graph=compile_graph(components, binding),
        out_dir=tmp_path / "out",
        waker=waker,
        services=services,
        replies=lambda _thread, text: fake.thread.append(
            {"ts": f"{time.time():.6f}", "user": BOT, "text": text}
        ),
    )
    holder.append(runtime)
    return runtime, footer


async def test_a_runs_steps_stream_as_cards_in_one_message_that_settles(tmp_path: Path) -> None:
    fake = FakeSlack()
    lead = ScriptedChatModel(
        steps=[
            lambda _m: tool_call(
                "write_file",
                {"file_path": "/workspace/projects/launch-poster/BRIEF.md", "content": "a poster"},
                content="Writing the brief down first.",
            ),
            lambda _m: tool_call(
                "read_file", {"file_path": "/workspace/projects/launch-poster/BRIEF.md"}
            ),
            lambda _m: reply("Here is the plan for the poster."),
        ]
    )
    runtime, footer = build(tmp_path, fake, lead)

    added = await runtime.ask("Make a launch poster.", thread_id="t-slack1")

    assert added[-1].content == "Here is the plan for the poster."
    assert fake.methods().count("chat.startStream") == 1
    (message,) = fake.posted.values()
    assert not message.deleted and message.streaming
    steps = [(title, status) for _, title, status in fake.cards()]
    assert steps == [
        ("Drafting the notes", "in_progress"),
        ("Drafted the notes", "complete"),
        ("Reading the notes", "in_progress"),
        ("Read the notes", "complete"),
        ("Writing the reply", "in_progress"),
        ("Wrote the reply", "complete"),
    ]
    assert fake.said() == ["Writing the brief down first."]
    assert fake.headers()[-1] == "Done" and fake.methods()[-1] == "chat.stopStream"
    assert "launch-poster" not in json.dumps(fake.calls), "no argument text reaches Slack"
    await footer.footers.aclose()


async def test_a_quiet_turn_leaves_no_progress_message(tmp_path: Path) -> None:
    fake = FakeSlack()
    lead = ScriptedChatModel(
        steps=[
            lambda _m: tool_call(
                "schedule_wakeup",
                {"minutes": 1, "prompt": "See if anything changed.", "reason": "check"},
            ),
            lambda _m: reply("I'll check back in a minute."),
            lambda _m: tool_call("check_tasks", {}),
            lambda _m: reply("[quiet]"),
        ]
    )
    runtime, footer = build(tmp_path, fake, lead)

    async def instant(_delay: float) -> None:
        await asyncio.sleep(0)

    runtime.waker.sleep = instant  # one minute is the floor; fire the check-in at once
    await runtime.ask("Keep an eye on the render.", thread_id="t-slack2")
    assert await runtime.settle(timeout_seconds=10, poll_seconds=0.05)

    first, checked = fake.posted.values()
    assert not first.deleted, "the turn that answered keeps its steps"
    assert checked.deleted, "the [quiet] check-in's message is gone"
    assert fake.live() == [first]
    assert not any(c["type"] == "task_update" and c["id"] == "answer" for c in checked.chunks)
    await footer.footers.aclose()


async def test_a_follow_up_reaches_the_running_helper_and_the_lead_says_so(tmp_path: Path) -> None:
    """SPEC §20.3, steering into a running helper: the helper takes the note at its next model
    call; the lead acknowledges in a line; the helper streams its own message; the reply while
    it works gets a live footer."""
    fake = FakeSlack()
    steered = threading.Event()
    seen_by_lead: list[str] = []
    seen_by_helper: list[str] = []

    def held_first_step(_messages: Sequence[BaseMessage]) -> AIMessage:
        steered.wait(timeout=30)
        return tool_call(
            "write_file", {"file_path": "/workspace/projects/p/title.txt", "content": "Launch"}
        )

    def second_step(messages: Sequence[BaseMessage]) -> AIMessage:
        seen_by_helper.extend(str(m.content) for m in messages)
        return reply("Done; the title is blue now, as the person asked.")

    def steer(messages: Sequence[BaseMessage]) -> AIMessage:
        seen_by_lead.extend(
            str(m.content) for m in messages if str(m.id or "").startswith(RUNNING_NOTE)
        )
        (task_id,) = list(REGISTRY)
        return tool_call("steer_task", {"task_id": task_id, "note": "Make the title blue."})

    lead = ScriptedChatModel(
        steps=[
            lambda _m: tool_call(
                "start_task",
                {"description": "Fix the title card.", "effort": "low", "label": "fix pass"},
            ),
            lambda _m: reply("The fix pass is running; about five minutes."),
            steer,
            lambda _m: reply("I've added your notes to the fix pass that's already running."),
            lambda _m: reply("The fix pass is done, with the blue title."),
        ]
    )
    helper = ScriptedChatModel(steps=[held_first_step, second_step])
    runtime, footer = build(tmp_path, fake, lead, low=helper)

    def footers() -> list[str]:
        return [fields["text"] for method, fields in fake.calls if method == "chat.postMessage"]

    await runtime.ask("Fix the title card.", thread_id="t-slack3")
    fake.thread.append({"ts": f"{time.time():.6f}", "user": BOT, "text": "The fix pass is running"})
    acknowledged = await runtime.ask("Make the title blue.", thread_id="t-slack3")
    fake.thread.append({"ts": f"{time.time():.6f}", "user": BOT, "text": "I've added your notes"})
    for _ in range(100):  # each reply while the helper works gets its footer
        if len(footers()) == 2:
            break
        await asyncio.sleep(0.05)
    steered.set()
    assert await runtime.settle(timeout_seconds=30, poll_seconds=0.05)

    assert (
        acknowledged[-1].content == "I've added your notes to the fix pass that's already running."
    )
    assert seen_by_lead and "fix pass" in seen_by_lead[0], "the lead was told what runs"
    assert any(
        "Make the title blue." in text and "note from the lead" in text for text in seen_by_helper
    )
    assert (tmp_path / "sandbox/workspace/projects/p/title.txt").read_text() == "Launch"

    helper_headers = [h for h in fake.headers() if h.startswith("fix pass: ")]
    assert helper_headers == ["fix pass: Drafting the notes", "fix pass: Done"]
    assert any(title == "Passed your notes on" for _, title, _ in fake.cards())
    first, second = footers()[:2]
    assert first.startswith("1 agent running") and second.startswith("1 agent running")
    retired = [fields["text"] for method, fields in fake.calls if method == "chat.update"]
    assert retired[0] == "~$0.00 so far", "the newer reply's footer takes over"
    await footer.footers.aclose()
