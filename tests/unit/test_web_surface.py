"""The web surface: the store, the bridge's boards and feedback, steering, the demo lead, and the
app at every address."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest
from deepagents.backends.protocol import FileDownloadResponse
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from design_agent.config import Settings
from design_agent.harness import tasks
from design_agent.middleware.meter import METER
from design_agent.surfaces.web import demo
from design_agent.surfaces.web.agent import AgentHost, worked_seconds
from design_agent.surfaces.web.app import create_app
from design_agent.surfaces.web.hub import Hub
from design_agent.surfaces.web.store import AGENT_ID, Store

PNG = b"\x89PNG\r\n\x1a\nframe"


class FakeBackend:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return [
            FileDownloadResponse(
                path=p,
                content=self.files.get(p),
                error=None if p in self.files else "file_not_found",
            )
            for p in paths
        ]


class FakeBinding:
    name = "fake"
    runner = None

    def __init__(self, backend: FakeBackend) -> None:
        self._backend = backend

    def backend_for(self, runtime: Any) -> FakeBackend:
        return self._backend


class FakeRuntime:
    """Records each turn; a turn can be held open to test follow-ups."""

    def __init__(self, backend: FakeBackend) -> None:
        self.binding = FakeBinding(backend)
        self.asked: list[tuple[str, str]] = []
        self.release = asyncio.Event()
        self.release.set()

    async def ask(self, text: str, *, thread_id: str, configurable: Any = None) -> list[Any]:
        self.asked.append((thread_id, text))
        await self.release.wait()
        return [AIMessage(content="On it.")]

    async def attach(self, thread_id: str, files: list[tuple[str, bytes]]) -> list[str]:
        return [f"/workspace/attachments/{name}" for name, _ in files]


@pytest.fixture
def host(tmp_path: Path) -> tuple[AgentHost, FakeRuntime]:
    store = Store(tmp_path / "house.sqlite")
    runtime = FakeRuntime(
        FakeBackend({f"/workspace/projects/t/board/poses/b{i}.png": PNG for i in (1, 2, 3)})
    )
    agent = AgentHost(settings=Settings(), store=store, hub=Hub(), data_dir=tmp_path, demo=True)
    agent.runtime = runtime  # type: ignore[assignment]
    return agent, runtime


def test_a_fresh_store_has_a_workspace(tmp_path: Path) -> None:
    store = Store(tmp_path / "house.sqlite")
    assert {p["id"] for p in store.people()} >= {"you", "maya", AGENT_ID}
    assert [c["name"] for c in store.channels()] == ["launch", "brand"]


async def test_a_message_to_the_agent_starts_a_task(host: tuple[AgentHost, FakeRuntime]) -> None:
    agent, runtime = host
    channel = agent.store.channels()[0]["id"]
    message = agent.post(
        channel_id=channel, author_id="you", text="A teaser, please", to_agent=True, kind="video"
    )
    await asyncio.sleep(0.05)
    thread = agent.store.thread(message["thread_id"])
    assert thread is not None and thread["task"] and thread["kind"] == "video"
    assert runtime.asked[0][0] == message["thread_id"]
    assert "What they want back: a video or animation" in runtime.asked[0][1]
    replies = [m for m in agent.store.messages(message["thread_id"]) if m["kind"] == "agent"]
    assert replies[-1]["text"] == "On it."


async def test_a_team_message_starts_no_turn(host: tuple[AgentHost, FakeRuntime]) -> None:
    agent, runtime = host
    channel = agent.store.channels()[0]["id"]
    agent.post(channel_id=channel, author_id="maya", text="Lunch?", to_agent=False)
    await asyncio.sleep(0.02)
    assert runtime.asked == []


async def test_follow_ups_wait_for_the_running_turn_and_stop_ends_it(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, runtime = host
    channel = agent.store.channels()[0]["id"]
    runtime.release.clear()
    root = agent.post(channel_id=channel, author_id="you", text="Make it", to_agent=True)
    await asyncio.sleep(0.02)
    thread = root["thread_id"]
    agent.post(
        channel_id=channel,
        author_id="maya",
        text="Use the moss green",
        to_agent=True,
        thread_id=thread,
    )
    agent.post(channel_id=channel, author_id="you", text="stop", to_agent=True, thread_id=thread)
    assert agent.stop_requested(thread) is True
    taken = agent.take_followups(thread)
    assert [f.text for f in taken] == ["Use the moss green"]
    states = [m["data"].get("state") for m in agent.store.messages(thread) if m["kind"] == "person"]
    assert "folded" in states and "stop" in states
    runtime.release.set()
    await asyncio.sleep(0.02)


async def test_a_board_takes_notes_and_a_new_version_answers_them(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, _ = host
    channel = agent.store.channels()[0]["id"]
    root = agent.post(channel_id=channel, author_id="you", text="Storyboard it", to_agent=True)
    await asyncio.sleep(0.02)
    thread = root["thread_id"]
    frames = [
        {"path": f"/workspace/projects/t/board/poses/b{i}.png", "name": f"Beat {i}"}
        for i in (1, 2, 3)
    ]
    said = await agent.publish_board(
        None,
        thread,
        project="t",
        title="Storyboard",
        kind="storyboard",
        frames=frames,
        replaces=None,
        answers=[],
    )
    board = agent.store.boards(thread)[0]
    assert board["id"] in said and board["status"] == "review"
    beat2 = next(f for f in agent.store.frames(board["id"]) if f["name"] == "Beat 2")
    note = agent.add_comment(beat2["id"], author_id="maya", text="Bigger line", x=0.5, y=0.6)
    feedback = agent.feedback_text(thread, board["id"])
    assert note["id"] in feedback and "Maya Chen: Bigger line" in feedback

    sent = agent.send_board(board["id"], by="maya", approve=False)
    assert "Beat 2 (1 note)" in sent["text"] and sent["to_agent"]
    assert "notes on “Storyboard”" in sent["text"]  # the board's own title, never recased
    await asyncio.sleep(0.02)

    said = await agent.publish_board(
        None,
        thread,
        project="t",
        title="Storyboard",
        kind="storyboard",
        frames=[frames[1]],
        replaces=board["id"],
        answers=[note["id"]],
    )
    assert "Version 2" in said and "answering 1 note" in said
    view = agent.board_view(board["id"])
    beat2_view = next(f for f in view["frames"] if f["name"] == "Beat 2")
    assert beat2_view["version"] == 2 and [v["v"] for v in beat2_view["versions"]] == [1, 2]
    assert beat2_view["comments"][0]["answered_in"] == 2


async def test_a_board_frame_outside_the_workspace_is_refused(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, _ = host
    channel = agent.store.channels()[0]["id"]
    root = agent.post(channel_id=channel, author_id="you", text="Go", to_agent=True)
    await asyncio.sleep(0.02)
    said = await agent.publish_board(
        None,
        root["thread_id"],
        project="t",
        title="x",
        kind="storyboard",
        frames=[{"path": "/etc/passwd", "name": "nope"}],
        replaces=None,
        answers=[],
    )
    assert said.startswith("Nothing was published")
    assert agent.store.boards(root["thread_id"]) == []


async def test_the_hub_delivers_events_published_from_another_thread() -> None:
    hub = Hub()
    hub.bind(asyncio.get_running_loop())
    stream = hub.stream()
    pending = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0)
    await asyncio.to_thread(hub.publish, "ping", n=1)
    event = await asyncio.wait_for(pending, 1)
    assert event["type"] == "ping" and event["n"] == 1
    await stream.aclose()


# -- the demo lead ------------------------------------------------------------------------------


def _calls(message: AIMessage) -> list[str]:
    return [c["name"] for c in message.tool_calls]


def test_the_demo_lead_storyboards_first() -> None:
    first = demo.next_step([HumanMessage("A teaser for the launch")])
    assert "write_todos" in _calls(first) and "write_file" in _calls(first)


def test_the_demo_lead_reads_notes_then_builds_after_approval() -> None:
    published = ToolMessage(
        content="“Storyboard” is on the canvas as board b_0123456789ab with 3 frames.",
        tool_call_id="x",
    )
    history = [
        HumanMessage("A teaser"),
        AIMessage(content="", tool_calls=[{"name": "canvas_publish_board", "args": {}, "id": "x"}]),
        published,
        AIMessage(content="On the canvas."),
    ]
    notes = demo.next_step(
        [*history, HumanMessage("I left notes on the storyboard: Beat 2 (1 note).")]
    )
    assert (
        _calls(notes) == ["canvas_read_feedback"]
        and notes.tool_calls[0]["args"]["board"] == "b_0123456789ab"
    )
    film = demo.next_step([*history, HumanMessage("Approved the storyboard. Go ahead.")])
    assert "write_todos" in _calls(film)


def test_the_demo_lead_finishes_when_the_render_wakes_it() -> None:
    step = demo.next_step([HumanMessage("[Runtime notice, not from the user] the film finished.")])
    assert _calls(step) == ["execute"]


def test_the_demo_lead_answers_about_the_board_it_just_published() -> None:
    def call(name: str) -> AIMessage:
        return AIMessage(
            content="", tool_calls=[{"name": name, "args": {}, "id": name, "type": "tool_call"}]
        )

    turn = [
        HumanMessage("A teaser for the launch"),
        call("write_todos"),
        ToolMessage(content="ok", tool_call_id="write_todos"),
        call("write_file"),
        ToolMessage(content="ok", tool_call_id="write_file"),
        call("execute"),
        ToolMessage(content="ok", tool_call_id="execute"),
        call("canvas_publish_board"),
        ToolMessage(
            content="“Storyboard” is on the canvas as board b_0123456789ab with 3 frames.",
            tool_call_id="canvas_publish_board",
        ),
    ]
    answer = demo.next_step(turn)
    assert not answer.tool_calls and "storyboard is on the canvas" in str(answer.content).lower()


def test_the_brand_page_reads_colours_type_and_logos() -> None:
    from design_agent.config import SAMPLE_BRAND, project_root
    from design_agent.surfaces.web.app import brand_view

    view = brand_view(project_root() / SAMPLE_BRAND)
    colors = {c["name"]: c["value"] for c in view["colors"]}
    assert colors["ink"] == "#14161a" and colors["signal"] == "#ff5a36"
    geist = next(f for f in view["families"] if f["family"] == "Geist")
    assert geist["required"] and len(geist["styles"]) == 2
    assert "mark.svg" in view["logos"] and view["sample"]


def test_the_skills_page_lists_every_skill_once() -> None:
    from design_agent.config import project_root
    from design_agent.surfaces.web.app import skills_view

    skills = skills_view(project_root())
    names = [s["name"] for s in skills]
    assert len(names) == len(set(names)) and {"media-production", "canvas", "storyboard"} <= set(
        names
    )
    assert "paper-design" not in names
    assert any(s["vendored"] for s in skills if s["name"].startswith("hyperframes"))


def test_the_lead_is_shown_by_its_models_logo() -> None:
    from design_agent.surfaces.web.agent import model_mark

    assert model_mark(Settings(model="anthropic:claude-opus-5-5"), demo=False) == "claude"
    assert model_mark(Settings(model="langsmith:anthropic/claude-opus-5-5"), demo=False) == "claude"
    assert model_mark(Settings(model="openai:gpt-5.5"), demo=False) == "codex"
    assert model_mark(Settings(model="anthropic:claude-opus-5-5"), demo=True) == "house"


async def test_nothing_spins_in_a_turn_that_has_ended(host: tuple[AgentHost, FakeRuntime]) -> None:
    agent, runtime = host
    channel = agent.store.channels()[0]["id"]
    runtime.release.clear()
    root = agent.post(channel_id=channel, author_id="you", text="Go", to_agent=True)
    await asyncio.sleep(0.02)
    thread = root["thread_id"]
    agent.turn_started(thread)
    agent.turn_step(thread, "todo-1", "Pose the beats", "running")
    agent.turn_step(thread, "call-9", "Rendering", "running")
    agent.turn_ended(thread, outcome="done")
    turn = next(m for m in agent.store.messages(thread) if m["kind"] == "turn")
    steps = {s["id"]: s["status"] for s in turn["data"]["steps"]}
    assert steps == {"stage": "done", "todo-1": "pending", "call-9": "failed"}
    runtime.release.set()
    await asyncio.sleep(0.02)


async def test_a_turn_background_news_woke_reads_as_working_until_it_ends(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, _ = host
    channel = agent.store.channels()[0]["id"]
    thread = agent.store.add_thread(
        thread_id="th_woken", channel_id=channel, task=True, title="Teaser", kind="", by="you"
    )["id"]
    agent.turn_started(thread)  # the waker's turn: no person started it
    agent._settle_status(thread)  # the footer ticker's recount mid-turn
    assert agent.store.thread(thread)["status"] == "working"  # type: ignore[index]
    assert agent.footer(thread)["live"] is True
    agent.turn_ended(thread, outcome="done")
    assert agent.store.thread(thread)["status"] == "idle"  # type: ignore[index]


def test_worked_time_counts_overlaps_once() -> None:
    assert worked_seconds([(0, 300), (100, 200), (600, 900), (850, 1000)]) == 700
    assert worked_seconds([]) == 0


def test_the_footer_counts_time_worked_not_time_since_the_thread_opened(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, _ = host
    channel = agent.store.channels()[0]["id"]
    thread = agent.store.add_thread(
        thread_id="th_night", channel_id=channel, task=True, title="Teaser", kind="video", by="you"
    )["id"]
    now = time.time()
    # Yesterday: a five-minute turn. Then the thread sat; today a helper has run ten minutes.
    agent.store.add_message(
        channel_id=channel,
        thread_id=thread,
        author_id=AGENT_ID,
        kind="turn",
        data={"state": "done", "started_at": now - 9 * 3600, "ended_at": now - 9 * 3600 + 300},
    )
    agent.store.upsert_work("t-night", thread, "helper", started_at=now - 600)
    tasks.REGISTRY["t-night"] = tasks.TaskRecord(
        id="t-night",
        thread_id=thread,
        effort="xhigh",
        label="teaser build",
        wave=None,
        started_at=now - 600,
    )
    try:
        footer = agent.footer(thread)
    finally:
        tasks.REGISTRY.pop("t-night", None)
    assert footer["live"] and footer["agents"] == 1
    assert footer["minutes"] == 15


def test_a_restart_keeps_each_jobs_spend_and_recounts_its_footer(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, _ = host
    channel = agent.store.channels()[0]["id"]
    thread = agent.store.add_thread(
        thread_id="th_spent", channel_id=channel, task=True, title="Teaser", kind="video", by="you"
    )["id"]
    now = time.time()
    agent.store.add_message(
        channel_id=channel,
        thread_id=thread,
        author_id=AGENT_ID,
        kind="turn",
        data={"state": "done", "started_at": now - 9 * 3600, "ended_at": now - 9 * 3600 + 300},
    )
    agent.store.update_thread(thread, footer={"usd": 5.17, "minutes": 575})
    placed = agent.store.thread(thread)["updated_at"]  # type: ignore[index]
    agent.restore()
    agent.restore()  # the spend is fed in once, however often it runs
    assert METER.summary(thread).usd == pytest.approx(5.17)
    after = agent.store.thread(thread)
    assert after is not None and after["footer"]["minutes"] == 5 and after["footer"]["usd"] == 5.17
    assert after["updated_at"] == placed


def test_a_restart_replays_every_priced_call_with_spend_an_older_footer_lost(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    # A live thread: its first $1.14 fell out of the footer at a restart before calls were kept.
    agent, _ = host
    channel = agent.store.channels()[0]["id"]
    thread = agent.store.add_thread(
        thread_id="th_replayed", channel_id=channel, task=True, title="Teaser", kind="", by="you"
    )["id"]
    for source, role, usd in (
        ("lead", "lead", 1.14),
        ("t-build", "xhigh", 4.61),
        ("lead", "lead", 0.56),
    ):
        agent.store.add_activity(
            {
                "thread_id": thread,
                "kind": "usage",
                "source": source,
                "label": role,
                "data": {
                    "usd": usd,
                    "model": "gpt-5.6-sol",
                    "role": role,
                    "usage": {"input_tokens": 1000, "output_tokens": 10},
                },
                "at": time.time(),
            }
        )
    agent.store.update_thread(thread, footer={"usd": 5.17})
    agent.restore()
    agent.restore()
    spent = METER.summary(thread)
    assert spent.usd == pytest.approx(6.31) and spent.calls == 3
    assert spent.by_source["t-build"].usd == pytest.approx(4.61)
    assert agent.store.thread(thread)["footer"]["usd"] == 6.31  # type: ignore[index]


def test_every_address_in_the_app_opens_the_app(tmp_path: Path) -> None:
    """A channel, its canvas, a card on it or a page, linked or reloaded, gets the app."""
    built = tmp_path / "web" / "dist"
    (built / "assets").mkdir(parents=True)
    (built / "index.html").write_text("<!doctype html><title>Creative House</title>")
    settings = Settings(_env_file=None, workspace_root=tmp_path / "workspace")  # type: ignore[call-arg]
    client = TestClient(create_app(tmp_path, settings))
    for address in (
        "/c/lily",
        "/c/lily/canvas",
        "/c/lily/canvas/th_frame/as_card?thread=th_frame",
        "/brand/new?for=lily",
        "/needs-you",
    ):
        page = client.get(address)
        assert page.status_code == 200, address
        assert "<title>Creative House</title>" in page.text, address
