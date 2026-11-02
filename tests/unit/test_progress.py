"""One live progress message in the thread, showing the work, never at the run's expense."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents.middleware import ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from design_agent.harness import tasks
from design_agent.middleware import progress as progress_module
from design_agent.middleware.progress import HelperProgressMiddleware, ThreadProgressMiddleware
from design_agent.surfaces.slack import stream as stream_module
from design_agent.surfaces.slack.phrasebook import services
from design_agent.surfaces.slack.target import SlackSurface
from design_agent.testing.fake_slack import (
    BOT,
    PERSON,
    TEAM,
    THREAD_TS,
    FakeResolver,
    FakeSlack,
    slack_target,
)

RUNTIME = SimpleNamespace(config={"configurable": {"thread_id": "t-lead"}})
ANSWERED = {"messages": [HumanMessage("make it blue"), AIMessage(content="Here it is.")]}


def lead(fake: FakeSlack, **kwargs: Any) -> ThreadProgressMiddleware:
    return ThreadProgressMiddleware(
        SlackSurface(FakeResolver(fake)), servers=services(["paper"]), **kwargs
    )


def call(
    name: str,
    args: dict[str, Any] | None = None,
    call_id: str = "c1",
    runtime: Any = RUNTIME,
    known: bool = True,
) -> Any:
    return SimpleNamespace(
        tool_call={"name": name, "args": args or {}, "id": call_id},
        runtime=runtime,
        tool=object() if known else None,
    )


async def ran(_request: Any) -> ToolMessage:
    return ToolMessage(content="ok", tool_call_id="c1")


def slow(seconds: float) -> Any:
    async def handler(_request: Any) -> ToolMessage:
        await asyncio.sleep(seconds)
        return ToolMessage(content="ok", tool_call_id="c1")

    return handler


def model(*messages: AIMessage) -> Any:
    async def handler(_request: Any) -> ModelResponse:
        return ModelResponse(result=list(messages))

    return handler


@pytest.fixture
def fast_beat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stream_module, "HEARTBEAT_SECONDS", 0.01)


async def test_the_run_streams_its_steps_as_cards() -> None:
    """One stream, a card per step, each rewritten in place when the step finishes."""
    fake = FakeSlack()
    middleware = lead(fake)

    await middleware.abefore_agent({}, RUNTIME)
    await middleware.awrap_tool_call(call("start_task", call_id="c1"), ran)
    await middleware.awrap_tool_call(call("paper_write_html", call_id="c2"), ran)
    await middleware.aafter_agent(ANSWERED, RUNTIME)

    assert fake.cards() == [
        ("c1", "Putting a helper on it", "in_progress"),
        ("c1", "Put a helper on it", "complete"),
        ("c2", "Writing HTML in Paper", "in_progress"),
        ("c2", "Wrote HTML in Paper", "complete"),
    ]
    (opened,) = [fields for method, fields in fake.calls if method == "chat.startStream"]
    assert opened["task_display_mode"] == "plan"
    assert opened["thread_ts"] == THREAD_TS
    assert (opened["recipient_user_id"], opened["recipient_team_id"]) == (PERSON, TEAM)
    # One collapsible group, titled with the step the run is on, settling to "Done".
    assert fake.headers() == [
        "Working: Putting a helper on it",
        "Working: Writing HTML in Paper",
        "Done",
    ]
    assert fake.methods()[-1] == "chat.stopStream"


async def test_parallel_steps_share_one_message() -> None:
    """A model that calls two tools at once must not open two messages."""
    fake = FakeSlack()
    middleware = lead(fake)

    await middleware.abefore_agent({}, RUNTIME)
    await asyncio.gather(
        middleware.awrap_tool_call(
            call("read_file", {"file_path": "/workspace/brand/tokens.json"}, "a"), ran
        ),
        middleware.awrap_tool_call(call("look", {"paths": ["x.png", "y.png"]}, "b"), ran),
    )
    await middleware.aafter_agent(ANSWERED, RUNTIME)

    assert fake.methods().count("chat.startStream") == 1
    assert fake.methods().count("chat.stopStream") == 1
    assert sorted(fake.cards()) == sorted(
        [
            ("a", "Studying the brand book", "in_progress"),
            ("a", "Studied the brand book", "complete"),
            ("b", "Looking over the frames", "in_progress"),
            ("b", "Looked over the frames", "complete"),
        ]
    )


async def test_narration_reaches_the_thread_and_the_answer_does_not() -> None:
    """A turn that ends in tool calls is narration; the turn that does not is the answer, which
    the platform posts itself (streaming it here too would put it in the thread twice)."""
    fake = FakeSlack()
    middleware = lead(fake)
    request = SimpleNamespace(runtime=RUNTIME)
    narrated = AIMessage(
        content="Reading the brand book first.",
        tool_calls=[{"name": "read_file", "args": {}, "id": "c1"}],
    )

    await middleware.abefore_agent({}, RUNTIME)
    await middleware.awrap_model_call(request, model(narrated))
    await middleware.awrap_model_call(request, model(AIMessage(content="Here is the answer.")))
    await middleware.aafter_agent(ANSWERED, RUNTIME)

    assert fake.said() == ["Reading the brand book first."]
    assert [c for c in fake.cards() if c[0] == "answer"] == [
        ("answer", "Writing the reply", "in_progress"),
        ("answer", "Wrote the reply", "complete"),
    ]
    assert fake.headers() == ["Working: Writing the reply", "Done"]


async def test_narration_cannot_ping_the_channel() -> None:
    fake = FakeSlack()
    middleware = lead(fake)
    narrated = AIMessage(
        content="<!channel> rendering now", tool_calls=[{"name": "execute", "args": {}, "id": "c1"}]
    )
    await middleware.awrap_model_call(SimpleNamespace(runtime=RUNTIME), model(narrated))
    assert fake.said() == ["@channel rendering now"]


async def test_a_step_that_failed_or_raised_says_so_on_its_card() -> None:
    fake = FakeSlack()
    middleware = lead(fake)

    async def failed(_request: Any) -> ToolMessage:
        return ToolMessage(content="no", tool_call_id="c1", status="error")

    async def exploded(_request: Any) -> ToolMessage:
        raise RuntimeError("the tool died")

    await middleware.awrap_tool_call(call("generate_image", call_id="c1"), failed)
    with pytest.raises(RuntimeError):
        await middleware.awrap_tool_call(call("transcribe_audio", call_id="c2"), exploded)

    assert fake.cards()[1] == ("c1", "Generated the image", "error")
    assert fake.cards()[-1] == ("c2", "Transcribed the audio", "error")


async def test_no_argument_of_a_call_reaches_the_card() -> None:
    """A card is the one surface nobody reviews, and arguments carry paths and people's words."""
    fake = FakeSlack()
    secret, file_id = "/workspace/attachments/board.png", "01TESTDRAFT00000000000000"
    await lead(fake).awrap_tool_call(
        call("paper_write_html", {"html": secret, "fileId": file_id}), ran
    )
    sent = json.dumps(fake.calls)
    assert fake.calls and secret not in sent and file_id not in sent


async def test_a_tool_the_agent_does_not_have_reads_as_a_generic_step() -> None:
    """A made-up tool name is the model's own words: it never reaches a card."""
    fake = FakeSlack()
    await lead(fake).awrap_tool_call(call("email_the_whole_company", known=False), ran)
    assert {title for _, title, _ in fake.cards()} == {"Working on a step", "Worked on a step"}


async def test_slack_failing_stops_the_stream_and_not_the_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Presentation is never worth a run: the tool still runs and the failure is not raised."""
    fake = FakeSlack(refuse={"chat.startStream": "ratelimited"})
    middleware = lead(fake)
    handled: list[str] = []

    async def run(request: Any) -> ToolMessage:
        handled.append(request.tool_call["name"])
        return ToolMessage(content="ok", tool_call_id="c1")

    result = await middleware.awrap_tool_call(call("generate_image"), run)
    await middleware.awrap_tool_call(call("generate_music", call_id="c2"), run)
    await middleware.aafter_agent(ANSWERED, RUNTIME)

    assert isinstance(result, ToolMessage) and result.content == "ok"
    assert handled == ["generate_image", "generate_music"]
    assert "ratelimited" in caplog.text
    # One attempt, then nothing: the answer still arrives as its own message.
    assert fake.methods() == ["chat.startStream"]


async def test_without_streaming_the_cards_go_in_one_updated_message() -> None:
    """A workspace that refuses `chat.startStream` gets one `chat.postMessage` redrawn with
    `chat.update`, and later runs on the same client skip the refused call."""
    fake = FakeSlack(refuse={"chat.startStream": "unknown_method"})
    middleware = lead(fake)
    stream_min = stream_module.MIN_UPDATE_SECONDS
    stream_module.MIN_UPDATE_SECONDS = 0.0
    try:
        await middleware.abefore_agent({}, RUNTIME)
        await middleware.awrap_tool_call(call("start_task", call_id="c1"), ran)
        await middleware.awrap_tool_call(call("generate_image", call_id="c2"), ran)
        await middleware.aafter_agent(ANSWERED, RUNTIME)
        await middleware.abefore_agent({}, RUNTIME)
        await middleware.awrap_tool_call(call("generate_image", call_id="c3"), ran)
        await middleware.aafter_agent(ANSWERED, RUNTIME)
    finally:
        stream_module.MIN_UPDATE_SECONDS = stream_min

    assert fake.methods().count("chat.startStream") == 1
    first, second = list(fake.posted.values())
    body = json.dumps(first.blocks)
    assert "*Done*" in body
    # A closed message folds its steps away, as the native stream does.
    assert "Put a helper on it" not in body and ":heavy_check_mark:" not in body
    assert "in_progress" not in body and ":hourglass" not in body
    assert first.text == "Done" and not first.deleted and second.text == "Done"


async def test_a_message_without_a_team_streams_to_the_tokens_own_workspace() -> None:
    """Some events carry no team (a file upload), and Slack refuses a channel stream without one:
    the stream names the token's own workspace instead of falling back."""
    fake = FakeSlack()
    surface = SlackSurface(FakeResolver(fake, slack_target(team_id="")))
    middleware = ThreadProgressMiddleware(surface, servers=services(["paper"]))

    await middleware.abefore_agent({}, RUNTIME)
    await middleware.awrap_tool_call(call("start_task"), ran)
    await middleware.aafter_agent(ANSWERED, RUNTIME)

    (opened,) = [fields for method, fields in fake.calls if method == "chat.startStream"]
    assert (opened["recipient_user_id"], opened["recipient_team_id"]) == (PERSON, TEAM)
    assert "chat.postMessage" not in fake.methods()


async def test_a_refusal_about_one_message_leaves_streaming_on_for_the_next() -> None:
    """`missing_recipient_team_id` is about that message's fields, not the workspace: one
    refusal must not turn every later card in the process into the fallback."""
    fake = FakeSlack(refuse={"chat.startStream": "missing_recipient_team_id"})
    middleware = lead(fake)

    await middleware.abefore_agent({}, RUNTIME)
    await middleware.awrap_tool_call(call("start_task"), ran)
    await middleware.aafter_agent(ANSWERED, RUNTIME)
    fake.refuse.clear()
    await middleware.abefore_agent({}, RUNTIME)
    await middleware.awrap_tool_call(call("generate_image", call_id="c2"), ran)
    await middleware.aafter_agent(ANSWERED, RUNTIME)

    assert fake.methods().count("chat.startStream") == 2
    assert fake.methods()[-1] == "chat.stopStream"


async def test_the_fallback_merges_repeats_and_shows_only_the_latest_steps() -> None:
    fake = FakeSlack(refuse={"chat.startStream": "unknown_method"})
    progress = stream_module.SlackProgress(fake.client(), slack_target(), min_update=0.0)
    titles = ["Read the brief", *["Read an image"] * 3, "Ran a script", "Shot stills", "Fonts"]
    for i, title in enumerate(titles):
        await progress.step(stream_module.card(f"c{i}", title, "complete"))

    (message,) = fake.posted.values()
    working = json.dumps(message.blocks, ensure_ascii=False)
    assert "… 1 earlier step" in working and "Read the brief" not in working
    assert "Read an image ×3" in working and "Fonts" in working

    await progress.close("Done")
    closed = json.dumps(message.blocks, ensure_ascii=False)
    assert "*Done*" in closed and "Read an image" not in closed


async def test_a_stream_slack_ended_carries_on_as_an_updated_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Slack ends long or idle streams (`message_not_in_streaming_state`, issue 41): the same
    message keeps showing the work through `chat.update` instead of going dark."""
    fake = FakeSlack()
    middleware = lead(fake)
    stream_min = stream_module.MIN_UPDATE_SECONDS
    stream_module.MIN_UPDATE_SECONDS = 0.0
    try:
        await middleware.abefore_agent({}, RUNTIME)
        await middleware.awrap_tool_call(call("start_task", call_id="c1"), ran)
        fake.refuse.update(
            {
                "chat.appendStream": "message_not_in_streaming_state",
                "chat.stopStream": "message_not_in_streaming_state",
            }
        )
        await middleware.awrap_tool_call(call("generate_image", call_id="c2"), ran)
        await middleware.aafter_agent(ANSWERED, RUNTIME)
    finally:
        stream_module.MIN_UPDATE_SECONDS = stream_min

    (message,) = fake.posted.values()
    assert "chat.update" in fake.methods()
    assert message.text == "Done" and not message.deleted
    assert "progress stopped" not in caplog.text


async def test_a_run_with_no_slack_thread_says_nothing() -> None:
    """A schedule fire, a CLI ask or a Studio session has no thread to post in, and must not try."""
    fake = FakeSlack()
    resolver = FakeResolver(fake)
    resolver.target_for_runs = None  # type: ignore[assignment]
    middleware = ThreadProgressMiddleware(SlackSurface(resolver))

    await middleware.abefore_agent({}, RUNTIME)
    await middleware.awrap_model_call(
        SimpleNamespace(runtime=RUNTIME), model(AIMessage(content="hi"))
    )
    result = await middleware.awrap_tool_call(call("generate_image"), ran)
    await middleware.aafter_agent(ANSWERED, RUNTIME)

    assert isinstance(result, ToolMessage)
    assert fake.calls == []


async def test_the_plan_is_its_own_cards_shown_as_steps_start() -> None:
    """`write_todos` draws the plan: a step appears when it starts, is ticked off in place, and an
    unchanged step is not sent again."""
    fake = FakeSlack()
    middleware = lead(fake)

    def plan(*statuses: str) -> Any:
        todos = [
            {"content": "Pull the brand tokens", "status": statuses[0]},
            {"content": "Draft three layouts", "status": statuses[1]},
            {"content": "Render the stills", "status": statuses[2]},
        ]
        return call("write_todos", {"todos": todos}, call_id="t")

    await middleware.abefore_agent({}, RUNTIME)
    await middleware.awrap_tool_call(plan("in_progress", "pending", "pending"), ran)
    await middleware.awrap_tool_call(plan("completed", "in_progress", "pending"), ran)
    await middleware.aafter_agent(ANSWERED, RUNTIME)

    assert fake.cards() == [
        ("todo-0", "Pull the brand tokens", "in_progress"),
        ("todo-0", "Pull the brand tokens", "complete"),
        ("todo-1", "Draft three layouts", "in_progress"),
    ]
    assert fake.headers() == [
        "Working: Pull the brand tokens",
        "Working: Draft three layouts",
        "Done",
    ]
    assert not any(title == "Planning the work" for _, title, _ in fake.cards())


async def test_the_group_is_titled_once_per_step() -> None:
    """The header rides with the card rather than costing its own call."""
    fake = FakeSlack()
    middleware = lead(fake)
    await middleware.awrap_tool_call(call("generate_image", call_id="c1"), ran)
    await middleware.awrap_tool_call(call("generate_image", call_id="c2"), ran)
    assert fake.headers() == ["Working: Generating the image"]
    assert len([m for m in fake.methods() if m in ("chat.startStream", "chat.appendStream")]) == 4


async def test_a_quiet_step_is_resent_so_slack_keeps_the_stream(fast_beat: None) -> None:
    """A long step sends nothing for minutes, and Slack ends a quiet stream. The running card is
    re-sent in place until the step finishes, and never after it."""
    fake = FakeSlack()
    middleware = lead(fake)

    await middleware.abefore_agent({}, RUNTIME)
    await middleware.awrap_tool_call(call("start_render_job", call_id="c1"), slow(0.1))
    await middleware.aafter_agent(ANSWERED, RUNTIME)

    running = [c for c in fake.cards() if c == ("c1", "Starting the render", "in_progress")]
    assert len(running) >= 2
    assert fake.cards()[-1] == ("c1", "Started the render", "complete")
    assert fake.methods()[-1] == "chat.stopStream"


def test_a_long_step_says_how_long_it_has_run() -> None:
    assert stream_module.elapsed("Rolling the render", 30) == "Rolling the render"
    assert stream_module.elapsed("Rolling the render", 125) == "Rolling the render · 2 min"


async def test_a_follow_up_mid_run_gets_eyes_and_one_line(fast_beat: None) -> None:
    """A mention that arrives mid-run waits for this run; its sender gets a reaction at once and
    one line saying what happens to it. Chatter and the bot's own posts are left alone."""
    after = f"{float(THREAD_TS) + 1:.6f}"
    thread = [
        {"ts": THREAD_TS, "user": PERSON, "text": f"<@{BOT}> make a poster"},
        {"ts": after, "user": PERSON, "text": f"<@{BOT}> make it blue too"},
        {"ts": f"{float(THREAD_TS) + 2:.6f}", "user": "U0TESTUSER2", "text": "nice"},
    ]
    for steering, line in ((True, progress_module.STEERED), (False, progress_module.QUEUED)):
        fake = FakeSlack(thread=thread)
        middleware = lead(fake, steering=steering)
        await middleware.abefore_agent({}, RUNTIME)
        await middleware.awrap_tool_call(call("start_render_job", call_id="c1"), slow(0.1))
        await middleware.aafter_agent(ANSWERED, RUNTIME)

        eyes = [fields for method, fields in fake.calls if method == "reactions.add"]
        assert eyes == [{"channel": "C0TESTCHAN1", "timestamp": after, "name": "eyes"}]
        assert fake.said().count(line) == 1


async def test_a_stop_mid_run_is_told_it_stops(fast_beat: None) -> None:
    after = f"{float(THREAD_TS) + 1:.6f}"
    fake = FakeSlack(
        thread=[{"ts": after, "user": PERSON, "text": f"<@{BOT}> stop, do the deck instead"}]
    )
    middleware = lead(fake)
    await middleware.awrap_tool_call(call("start_render_job"), slow(0.1))
    assert fake.said() == [progress_module.STOPPING]


async def test_a_cancelled_step_closes_its_stream(fast_beat: None) -> None:
    """A cancelled run never reaches `after_agent`; its message settles to "Stopped"."""
    fake = FakeSlack()
    middleware = lead(fake)

    async def cancelled(_request: Any) -> ToolMessage:
        raise asyncio.CancelledError

    await middleware.abefore_agent({}, RUNTIME)
    with pytest.raises(asyncio.CancelledError):
        await middleware.awrap_tool_call(call("start_render_job"), cancelled)

    assert middleware._runs == {}
    assert fake.headers()[-1] == "Stopped"
    assert fake.methods()[-1] == "chat.stopStream"


async def test_a_run_cancelled_while_the_model_thinks_says_stopped() -> None:
    fake = FakeSlack()
    middleware = lead(fake)

    async def cancelled(_request: Any) -> ModelResponse:
        raise asyncio.CancelledError

    await middleware.abefore_agent({}, RUNTIME)
    await middleware.awrap_tool_call(call("generate_image"), ran)
    with pytest.raises(asyncio.CancelledError):
        await middleware.awrap_model_call(SimpleNamespace(runtime=RUNTIME), cancelled)

    assert middleware._runs == {}
    assert fake.headers()[-1] == "Stopped"


async def test_a_cancel_before_anything_was_shown_posts_nothing() -> None:
    fake = FakeSlack()
    middleware = lead(fake)

    async def cancelled(_request: Any) -> ModelResponse:
        raise asyncio.CancelledError

    await middleware.abefore_agent({}, RUNTIME)
    with pytest.raises(asyncio.CancelledError):
        await middleware.awrap_model_call(SimpleNamespace(runtime=RUNTIME), cancelled)
    assert fake.calls == []


@pytest.mark.parametrize("reply", ["[quiet]", "", [{"type": "text", "text": " [quiet] "}]])
async def test_a_turn_with_nothing_to_say_leaves_nothing_in_the_thread(reply: Any) -> None:
    """A check-in with nothing new replies `[quiet]`, and nothing is posted: the message its steps
    opened is deleted rather than settled to a bare "Done"."""
    fake = FakeSlack()
    middleware = lead(fake)

    await middleware.abefore_agent({}, RUNTIME)
    await middleware.awrap_tool_call(call("check_tasks"), ran)
    await middleware.awrap_model_call(
        SimpleNamespace(runtime=RUNTIME), model(AIMessage(content=reply))
    )
    await middleware.aafter_agent({"messages": [AIMessage(content=reply)]}, RUNTIME)

    assert fake.methods()[-2:] == ["chat.stopStream", "chat.delete"]
    assert fake.live() == []
    assert "Done" not in fake.headers()
    assert "answer" not in [card[0] for card in fake.cards()]


async def test_a_turn_with_nothing_to_say_and_no_steps_posts_nothing() -> None:
    fake = FakeSlack()
    middleware = lead(fake)
    await middleware.abefore_agent({}, RUNTIME)
    await middleware.aafter_agent({"messages": [AIMessage(content="[quiet]")]}, RUNTIME)
    assert fake.calls == []


async def test_a_last_turn_with_no_words_keeps_the_message_the_platform_posts_for() -> None:
    """The platform posts the newest assistant message that has words, reaching past a final turn
    that only thought. That reply is seen, so the steps that led to it stay."""
    fake = FakeSlack()
    middleware = lead(fake)
    state = {
        "messages": [
            HumanMessage("three sizes please"),
            AIMessage(
                content="Rendering the three sizes now.",
                tool_calls=[{"name": "execute", "args": {}, "id": "c1"}],
            ),
            ToolMessage(content="ok", tool_call_id="c1"),
            AIMessage(content=[{"type": "thinking", "thinking": "done", "signature": "s"}]),
        ]
    }
    await middleware.abefore_agent({}, RUNTIME)
    await middleware.awrap_tool_call(call("execute", {"command": "npx hyperframes render"}), ran)
    await middleware.aafter_agent(state, RUNTIME)
    assert "chat.delete" not in fake.methods() and fake.methods()[-1] == "chat.stopStream"
    assert fake.headers()[-1] == "Done"


# -- background helpers -------------------------------------------------------------------------


@pytest.fixture
def helper_surface() -> Iterator[tuple[FakeSlack, SlackSurface, Any]]:
    """A Slack thread the lead's run resolved, and a way to make a helper the one in flight."""
    fake = FakeSlack()
    surface = SlackSurface(FakeResolver(fake))

    def start(task_id: str, label: str) -> None:
        record = tasks.TaskRecord(
            id=task_id,
            thread_id="t-lead",
            effort="low",
            label=label,
            wave=None,
            started_at=time.time(),
        )
        tasks.REGISTRY[task_id] = record
        # Set in the test's own context, which ends with it.
        tasks.CURRENT.set(record)

    yield fake, surface, start
    for task_id in [k for k, r in tasks.REGISTRY.items() if r.thread_id == "t-lead"]:
        del tasks.REGISTRY[task_id]


DETACHED = SimpleNamespace(config={"configurable": {"thread_id": "t-lead"}})


async def test_a_background_helper_streams_its_steps_as_a_message_of_its_own(
    helper_surface: Any,
) -> None:
    """A helper works after the lead's turn ended, so its steps stream into the thread that asked,
    headed with its label, on the client the lead's run resolved, without its words."""
    fake, surface, start = helper_surface
    await surface.bind(RUNTIME)
    start("t-test01", "act 3")
    middleware = HelperProgressMiddleware(surface)

    async def reported(_request: Any) -> str:
        return "the model's response"

    await middleware.abefore_agent({}, DETACHED)
    said = await middleware.awrap_model_call(SimpleNamespace(runtime=DETACHED), reported)
    await middleware.awrap_tool_call(call("generate_image", runtime=DETACHED), ran)
    await middleware.aafter_agent({"messages": [AIMessage(content="")]}, DETACHED)

    assert said == "the model's response"
    assert fake.headers() == ["act 3: Generating the image", "act 3: Done"]
    assert fake.said() == []
    assert "chat.delete" not in fake.methods() and fake.methods()[-1] == "chat.stopStream"


async def test_helpers_side_by_side_keep_separate_messages(helper_surface: Any) -> None:
    fake, surface, start = helper_surface
    await surface.bind(RUNTIME)
    middleware = HelperProgressMiddleware(surface)
    start("t-test01", "act 3")
    await middleware.awrap_tool_call(call("generate_image", runtime=DETACHED), ran)
    start("t-test02", "cover")
    await middleware.awrap_tool_call(call("generate_image", runtime=DETACHED), ran)
    assert fake.methods().count("chat.startStream") == 2


async def test_a_helper_run_inside_the_leads_turn_stays_silent(helper_surface: Any) -> None:
    """Run with `task`, a helper is no background task: the lead's own message shows it."""
    fake, surface, _start = helper_surface
    await surface.bind(RUNTIME)
    middleware = HelperProgressMiddleware(surface)
    await middleware.awrap_tool_call(call("generate_image", runtime=DETACHED), ran)
    await middleware.aafter_agent(ANSWERED, DETACHED)
    assert fake.calls == []


async def test_a_helper_cancelled_while_its_model_thinks_says_stopped(helper_surface: Any) -> None:
    fake, surface, start = helper_surface
    await surface.bind(RUNTIME)
    start("t-test03", "act 3")
    middleware = HelperProgressMiddleware(surface)

    async def cancelled(_request: Any) -> ModelResponse:
        raise asyncio.CancelledError

    await middleware.awrap_tool_call(call("generate_image", runtime=DETACHED), ran)
    with pytest.raises(asyncio.CancelledError):
        await middleware.awrap_model_call(SimpleNamespace(runtime=DETACHED), cancelled)
    assert middleware._runs == {}
    assert fake.headers()[-1] == "act 3: Stopped"
