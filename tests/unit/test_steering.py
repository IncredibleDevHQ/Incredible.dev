"""A follow-up reaches the running work: a helper takes the lead's note at its next model call,
and the lead's own busy run takes a Slack thread's follow-up at its next step, after which the
run the platform queued for that message ends at once."""

from __future__ import annotations

import time
import warnings
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from design_agent.harness import tasks
from design_agent.middleware.background import CHECK_IN_MARK
from design_agent.middleware.steering import (
    RUNNING_NOTE,
    STOPPED,
    TAKEN,
    HelperSteeringMiddleware,
    LeadSteeringMiddleware,
    SteeringToolsMiddleware,
    SteerNotes,
    steer_id,
)
from design_agent.runtime.waker import wake_marker
from design_agent.surfaces.slack.followups import FollowUpReader, is_stop
from design_agent.surfaces.slack.target import SlackSurface
from design_agent.testing.fake_slack import (
    BOT,
    CHANNEL,
    PERSON,
    THREAD_TS,
    FakeResolver,
    FakeSlack,
    slack_target,
)
from design_agent.testing.fakes import FolderSandbox
from design_agent.testing.scripted_model import ScriptedChatModel, reply, tool_call

THREAD = "t-steer"
RUNTIME = SimpleNamespace(config={"configurable": {"thread_id": THREAD}})
LATER = f"{float(THREAD_TS) + 1:.6f}"


def mention(ts: str, text: str, user: str = PERSON, **extra: Any) -> dict[str, Any]:
    return {"ts": ts, "user": user, "text": f"<@{BOT}> {text}", **extra}


def state(*messages: Any) -> dict[str, Any]:
    return {"messages": list(messages)}


@pytest.fixture
def helper() -> Any:
    record = tasks.TaskRecord(
        id="t-steer1",
        thread_id=THREAD,
        effort="xhigh",
        label="fix pass",
        wave=None,
        started_at=time.time(),
    )
    tasks.REGISTRY[record.id] = record
    yield record
    tasks.REGISTRY.pop(record.id, None)


# -- background helpers ------------------------------------------------------------------------


async def test_a_note_for_a_running_helper_reaches_its_next_model_call_once(
    helper: tasks.TaskRecord,
) -> None:
    notes = SteerNotes()
    lead = SteeringToolsMiddleware(notes)
    said = lead.steer(helper.id, "Make the title blue, the person asked.", THREAD)
    assert "fix pass" in said and helper.id in said

    tasks.CURRENT.set(helper)
    worker = HelperSteeringMiddleware(notes)
    update = await worker.abefore_model(state(HumanMessage("brief")), RUNTIME)
    (note,) = update["messages"]
    assert isinstance(note, HumanMessage) and "Make the title blue" in note.content
    assert await worker.abefore_model(state(HumanMessage("brief"), note), RUNTIME) is None


async def test_a_note_that_came_too_late_is_named_in_the_helpers_report(
    helper: tasks.TaskRecord,
) -> None:
    """A helper that ended before its next model call never read the note: its report says so,
    so the lead can start the change as new work instead of claiming it was made."""
    notes = SteerNotes()
    SteeringToolsMiddleware(notes).steer(helper.id, "Make the title blue.", THREAD)
    tasks.CURRENT.set(helper)
    final = AIMessage(content="Rendered the title card.", id="final")
    update = await HelperSteeringMiddleware(notes).aafter_agent(
        state(HumanMessage("brief"), final), RUNTIME
    )
    (report,) = update["messages"]
    assert report.id == "final" and report.content.startswith("Rendered the title card.")
    assert "Not applied" in report.content and "Make the title blue." in report.content


async def test_steering_refuses_what_it_cannot_reach(helper: tasks.TaskRecord) -> None:
    lead = SteeringToolsMiddleware(SteerNotes())
    assert "not a helper" in lead.steer("p-abc123", "x", THREAD)
    assert "No running task" in lead.steer("t-nope00", "x", THREAD)
    assert "No running task" in lead.steer(helper.id, "x", "another-thread")
    assert "empty" in lead.steer(helper.id, "   ", THREAD)
    helper.status = "done"
    assert "already done" in lead.steer(helper.id, "x", THREAD)


async def test_a_persons_turn_while_helpers_run_notes_what_is_running(
    helper: tasks.TaskRecord,
) -> None:
    """So the lead can pass a correction on instead of starting the work again."""
    lead = SteeringToolsMiddleware(SteerNotes())
    update = await lead.abefore_agent(
        state(AIMessage("Started the fix pass."), HumanMessage("make it blue")), RUNTIME
    )
    (note,) = update["messages"]
    assert str(note.id).startswith(RUNNING_NOTE)
    assert helper.id in note.content and "fix pass" in note.content and "steer_task" in note.content


@pytest.mark.parametrize(
    "text",
    [f"news\n\n{wake_marker('k1')}", f'{CHECK_IN_MARK} reason="x">\nlook', "<watchdog>\nrestart"],
)
async def test_no_running_note_on_a_turn_no_person_started(
    helper: tasks.TaskRecord, text: str
) -> None:
    lead = SteeringToolsMiddleware(SteerNotes())
    assert await lead.abefore_agent(state(HumanMessage(text)), RUNTIME) is None


async def test_no_running_note_when_nothing_runs() -> None:
    lead = SteeringToolsMiddleware(SteerNotes())
    assert await lead.abefore_agent(state(HumanMessage("make it blue")), RUNTIME) is None


# -- the lead's own run, in a Slack thread -----------------------------------------------------


def lead_steering(fake: FakeSlack, **target: Any) -> LeadSteeringMiddleware:
    return LeadSteeringMiddleware(SlackSurface(FakeResolver(fake, slack_target(**target))))


async def test_a_follow_up_joins_the_conversation_once_as_the_persons_message() -> None:
    fake = FakeSlack(thread=[mention(THREAD_TS, "make a poster"), mention(LATER, "make it blue")])
    steering = lead_steering(fake)

    update = await steering.abefore_model(state(HumanMessage("make a poster", id="in")), RUNTIME)

    (added,) = update["messages"]
    assert isinstance(added, HumanMessage) and added.id == steer_id(CHANNEL, LATER)
    assert added.content == "While you were working, the person added: make it blue"
    assert await steering.abefore_model(state(HumanMessage("x", id="in"), added), RUNTIME) is None


async def test_stop_ends_the_run_instead_of_steering_it() -> None:
    fake = FakeSlack(thread=[mention(LATER, "stop, do the deck instead")])
    update = await lead_steering(fake).abefore_model(state(HumanMessage("x")), RUNTIME)
    assert update["jump_to"] == "end"
    assert [m.content for m in update["messages"]] == [STOPPED]


async def test_a_failed_read_leaves_the_run_unsteered() -> None:
    fake = FakeSlack(refuse={"conversations.replies": "ratelimited"})
    assert await lead_steering(fake).abefore_model(state(HumanMessage("x")), RUNTIME) is None


async def test_the_queued_run_for_a_taken_follow_up_ends_at_once() -> None:
    taken = HumanMessage("make it blue", id=steer_id(CHANNEL, LATER))
    queued = lead_steering(FakeSlack(), message_ts=LATER)
    update = await queued.abefore_agent(state(HumanMessage("make a poster"), taken), RUNTIME)
    assert update["jump_to"] == "end"
    assert [m.content for m in update["messages"]] == [TAKEN]
    # A message nobody took runs as usual.
    fresh = lead_steering(FakeSlack(), message_ts=f"{float(THREAD_TS) + 9:.6f}")
    assert await fresh.abefore_agent(state(taken), RUNTIME) is None


async def test_a_follow_ups_files_are_staged_in_the_sandbox(tmp_path: Path) -> None:
    url = "https://files.slack.com/files-pri/T0TESTTEAM1-F0TEST0001/brief.pdf"
    ref = {"id": "F0TEST0001", "name": "brief v2.pdf", "size": 3, "url_private_download": url}
    fake = FakeSlack(thread=[mention(LATER, "use this brief", files=[ref])], files={url: b"pdf"})
    sandbox = FolderSandbox(tmp_path)
    steering = LeadSteeringMiddleware(
        SlackSurface(FakeResolver(fake)), backend_for=lambda _runtime: sandbox
    )

    update = await steering.abefore_model(state(HumanMessage("x")), RUNTIME)

    (added,) = update["messages"]
    assert "(attached: /workspace/attachments/F0TEST0001__brief_v2.pdf)" in added.content
    assert (tmp_path / "workspace/attachments/F0TEST0001__brief_v2.pdf").read_bytes() == b"pdf"
    assert "Bearer xoxb-test-token" in fake.authorizations


async def test_follow_ups_follow_the_channels_rule_for_starting_a_run() -> None:
    """In a channel, a mention; in a DM, any message; never the bot's own or another bot's. One
    read serves every caller for a moment."""
    thread = [
        mention(THREAD_TS, "make a poster"),
        mention(LATER, "make it blue"),
        {"ts": f"{float(THREAD_TS) + 2:.6f}", "user": "U0TESTUSER2", "text": "love it"},
        {"ts": f"{float(THREAD_TS) + 3:.6f}", "user": BOT, "text": "On it."},
        {
            "ts": f"{float(THREAD_TS) + 4:.6f}",
            "user": "U0TESTBOT02",
            "bot_id": "B0TEST0001",
            "text": f"<@{BOT}> bot",
        },
        {
            "ts": f"{float(THREAD_TS) + 5:.6f}",
            "user": "U0TESTUSER2",
            "subtype": "channel_join",
            "text": f"<@{BOT}>",
        },
    ]
    fake = FakeSlack(thread=thread)
    client, reader = fake.client(), FollowUpReader()
    found = await reader.read(client, slack_target(), THREAD_TS)
    assert [(f.ts, f.text) for f in found] == [(LATER, "make it blue")]
    assert await reader.read(client, slack_target(), THREAD_TS) == found
    assert fake.methods().count("conversations.replies") == 1

    in_dm = await FollowUpReader().read(client, slack_target(channel="D0TESTDM001"), THREAD_TS)
    assert [f.ts for f in in_dm] == [LATER, f"{float(THREAD_TS) + 2:.6f}"]
    every = await FollowUpReader(mention_required=False).read(client, slack_target(), THREAD_TS)
    assert len(every) == 2


@pytest.mark.parametrize(
    ("text", "stop"),
    [
        ("stop", True),
        ("Stop, do the deck instead", True),
        ("cancel that", True),
        ("never mind", True),
        ("make it stop flickering", False),
        ("don't stop", False),
    ],
)
def test_only_a_follow_up_that_leads_with_stop_is_one(text: str, stop: bool) -> None:
    assert is_stop(text) is stop


@tool
def render(scene: str) -> str:
    """Render a scene."""
    return "rendered"


class _Seen(AgentMiddleware):
    """What each model call was given, in order."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[list[str]] = []

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        self.calls.append([str(message.content) for message in request.messages])
        return await handler(request)


async def test_in_the_agent_loop_the_next_step_sees_it_and_the_queued_copy_does_no_work() -> None:
    """The real deepagents loop: a follow-up posted during the first step is in the second model
    call, and the run queued for the same message ends without calling the model."""
    saver, config = InMemorySaver(), {"configurable": {"thread_id": THREAD}}
    fake = FakeSlack(thread=[mention(THREAD_TS, "make a logo")])

    def first_step(_messages: Any) -> AIMessage:
        fake.thread.append(mention(LATER, "make it blue"))  # sent while the render runs
        return tool_call("render", {"scene": "logo"})

    seen = _Seen()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        graph = create_deep_agent(
            model=ScriptedChatModel(
                steps=[first_step, lambda _m: reply("Rendered, and it's blue.")]
            ),
            backend=StateBackend(),
            tools=[render],
            middleware=[LeadSteeringMiddleware(SlackSurface(FakeResolver(fake))), seen],
            checkpointer=saver,
        )
    # The follow-up read is shared for a moment: a run's first read must not hide the second.
    from design_agent.surfaces.slack import followups

    followups_ttl, followups.TTL_SECONDS = followups.TTL_SECONDS, 0.0
    try:
        result = await graph.ainvoke({"messages": [HumanMessage("make a logo")]}, config)
    finally:
        followups.TTL_SECONDS = followups_ttl

    assert result["messages"][-1].content == "Rendered, and it's blue."
    assert not any("make it blue" in content for content in seen.calls[0])
    assert any("the person added: make it blue" in content for content in seen.calls[1])

    never = _Seen()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        queued = create_deep_agent(
            model=ScriptedChatModel(steps=[lambda _m: reply("should never be said")]),
            backend=StateBackend(),
            tools=[render],
            middleware=[
                LeadSteeringMiddleware(
                    SlackSurface(FakeResolver(fake, slack_target(message_ts=LATER)))
                ),
                never,
            ],
            checkpointer=saver,
        )
    again = await queued.ainvoke({"messages": [HumanMessage("make it blue")]}, config)
    assert again["messages"][-1].content == TAKEN
    assert never.calls == []
