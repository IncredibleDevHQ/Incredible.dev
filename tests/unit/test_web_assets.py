"""The canvas's assets: the kinds of work and the templates, asking for them, filing a task's
boards and files under them, sign-offs that unblock the next, and the demo lead working a
template in order."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from design_agent.config import Settings, project_root
from design_agent.surfaces.web import catalog, demo
from design_agent.surfaces.web.agent import BOARD_KINDS, AgentHost
from design_agent.surfaces.web.hub import Hub
from design_agent.surfaces.web.store import AGENT_ID, Store
from design_agent.tools.delivery import DeliveredFile
from tests.unit.test_web_surface import PNG, FakeBackend, FakeRuntime

MP4 = b"\x00\x00\x00\x18ftypmp42film"
FRAMES = [f"/workspace/projects/t/board/poses/b{i}.png" for i in (1, 2, 3)]
FILM = "/workspace/projects/t/renders/teaser.mp4"
CARDS = [f"/workspace/projects/t/cards/card-{n}.png" for n in (1, 2)]


@pytest.fixture
def host(tmp_path: Path) -> tuple[AgentHost, FakeRuntime]:
    files = {path: PNG for path in [*FRAMES, *CARDS]} | {FILM: MP4}
    runtime = FakeRuntime(FakeBackend(files))
    agent = AgentHost(
        settings=Settings(), store=Store(tmp_path / "house.sqlite"), hub=Hub(), data_dir=tmp_path
    )
    agent.runtime = runtime  # type: ignore[assignment]
    return agent, runtime


def _channel(agent: AgentHost) -> str:
    return str(agent.store.channels()[0]["id"])


def _by_title(agent: AgentHost, thread: str) -> dict[str, dict]:  # type: ignore[type-arg]
    return {a["title"]: a for a in agent.store.assets(thread)}


async def _board(
    agent: AgentHost, thread: str, *, kind: str = "storyboard", asset: str | None = None
) -> str:
    frames = [{"path": p, "name": f"Beat {i}"} for i, p in enumerate(FRAMES, 1)]
    await agent.publish_board(
        None,
        thread,
        project="t",
        title="Storyboard",
        kind=kind,
        frames=frames,
        replaces=None,
        answers=[],
        asset=asset,
    )
    return str(agent.store.boards(thread)[-1]["id"])


# -- the catalog ----------------------------------------------------------------------------------


def test_every_kind_of_work_is_made_by_a_real_skill() -> None:
    ids = [c.id for c in catalog.CAPABILITIES]
    assert len(ids) == len(set(ids))
    for made in catalog.CAPABILITIES:
        assert (project_root() / "skills" / made.skill / "SKILL.md").is_file(), made.skill
        assert made.review in (*BOARD_KINDS, "")
        assert made.makes in catalog.MEDIA
        assert set(made.accepts) <= set(catalog.MEDIA) - {"frames"}
        assert set(made.takes) <= {catalog.MATERIAL, *catalog.MEDIA}
    assert set(catalog.BOARD_CAPABILITY) == set(BOARD_KINDS)


def test_every_template_wires_slots_that_can_be_made_from_their_sources() -> None:
    for chosen in catalog.TEMPLATES:
        assert catalog.ordered(chosen.slots), chosen.id
        slots = {s.key: s for s in chosen.slots}
        for slot in chosen.slots:
            made = catalog.capability(slot.kind)
            assert made is not None, (chosen.id, slot.key)
            # A slot made from earlier slots takes what they make; one made from the start takes
            # everything the template can start from.
            wanted = [catalog.capability(slots[s].kind).makes for s in slot.sources] or list(  # type: ignore[union-attr]
                chosen.starts_from
            )
            assert set(wanted) <= set(made.takes), (chosen.id, slot.key)
            assert slot.brief.endswith("."), (chosen.id, slot.key)


def test_every_template_says_what_you_get_and_its_shapes() -> None:
    # A template's card draws each piece at its shape and lists what the person gets.
    for chosen in catalog.TEMPLATES:
        assert any(not s.gate for s in chosen.slots), chosen.id
        for slot in chosen.slots:
            assert slot.gets and not slot.gets.endswith("."), (chosen.id, slot.key)
            assert slot.shape, (chosen.id, slot.key)
            for shape in slot.shape:
                width, height = shape.split(":")
                assert float(width) > 0 and float(height) > 0, (chosen.id, slot.key, shape)


# -- asking for work ------------------------------------------------------------------------------


async def test_a_kind_ask_puts_its_asset_on_the_canvas(host: tuple[AgentHost, FakeRuntime]) -> None:
    agent, runtime = host
    root = agent.post(
        channel_id=_channel(agent),
        author_id="you",
        text="Thumbnails for our talk",
        to_agent=True,
        kind="thumbs",
    )
    await asyncio.sleep(0.05)
    [asset] = agent.store.assets(root["thread_id"])
    assert (asset["kind"], asset["title"], asset["status"]) == ("thumbs", "Thumbnails", "planned")
    assert root["data"]["assets"] == [asset["id"]]
    asked = runtime.asked[0][1]
    assert "What they want back: thumbnails (an A/B set)" in asked
    assert f"On the canvas it is {asset['id']}" in asked


async def test_a_template_places_its_assets_and_tells_the_lead(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, runtime = host
    message = agent.place_template(
        _channel(agent), "launch-kit", by="maya", text="Our launch note: one pass, every size."
    )
    await asyncio.sleep(0.05)
    thread = message["thread_id"]
    assert message["text"].splitlines()[0] == "Launch kit from my notes"
    assert agent.store.thread(thread)["title"] == "Launch kit from my notes"  # type: ignore[index]
    assets = _by_title(agent, thread)
    assert list(assets) == ["Storyboard", "Teaser", "Thumbnails", "GIF", "Social cards"]
    board, teaser = assets["Storyboard"], assets["Teaser"]
    assert board["gate"] and board["sources"] == [] and teaser["sources"] == [board["id"]]
    assert assets["Thumbnails"]["sources"] == [teaser["id"]]
    assert assets["Social cards"]["sources"] == [board["id"]]
    assert {a["template"] for a in assets.values()} == {"launch-kit"}
    asked = runtime.asked[0][1]
    assert "file each asset's work under its id" in asked
    assert f"- {board['id']} “Storyboard”, a storyboard" in asked
    assert "The team signs it off on the canvas" in asked
    assert f"Made from {board['id']} “Storyboard”" in asked


async def test_a_template_needs_something_to_start_from(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, _ = host
    with pytest.raises(ValueError, match="Bring what it starts from"):
        agent.place_template(_channel(agent), "launch-kit", by="you")
    with pytest.raises(ValueError, match="starts from a finished video"):
        agent.place_template(_channel(agent), "social-pack", by="you", text="Our post")
    with pytest.raises(KeyError):
        agent.place_template(_channel(agent), "no-such-template", by="you", text="x")


async def test_a_template_onto_a_finished_video_joins_its_task(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, runtime = host
    root = agent.post(
        channel_id=_channel(agent), author_id="you", text="A teaser", to_agent=True, kind="video"
    )
    await asyncio.sleep(0.05)
    thread = root["thread_id"]
    [video] = agent.store.assets(thread)
    agent.store.update_asset(video["id"], status="done")
    message = agent.place_template(_channel(agent), "social-pack", by="leo", from_asset=video["id"])
    await asyncio.sleep(0.05)
    assert message["thread_id"] == thread and message["text"] == "Social pack for “Video”"
    added = [a for a in agent.store.assets(thread) if a["id"] != video["id"]]
    assert [a["title"] for a in added] == ["Thumbnails", "GIF", "Vertical short", "Social cards"]
    assert all(a["sources"] == [video["id"]] for a in added)
    assert f"Made from {video['id']} “Video”" in runtime.asked[-1][1]
    cards = added[-1]
    with pytest.raises(ValueError, match="starts from a finished video"):
        agent.place_template(_channel(agent), "social-pack", by="leo", from_asset=cards["id"])


async def test_an_added_asset_names_what_it_is_made_from(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, runtime = host
    root = agent.post(
        channel_id=_channel(agent), author_id="you", text="A teaser", to_agent=True, kind="video"
    )
    await asyncio.sleep(0.05)
    thread = root["thread_id"]
    [video] = agent.store.assets(thread)
    asset = agent.request_asset(
        thread, kind="gif", by="maya", sources=[video["id"]], note="Loop the payoff."
    )
    await asyncio.sleep(0.05)
    message = agent.store.messages(thread)[-1]
    said = [m for m in agent.store.messages(thread) if m["kind"] == "person"][-1]
    assert said["text"] == "Add “GIF”, made from “Video”.\n\nLoop the payoff."
    assert said["data"]["assets"] == [asset["id"]] and message["thread_id"] == thread
    assert f"- {asset['id']} “GIF”, a GIF. Made from {video['id']} “Video”." in runtime.asked[-1][1]
    with pytest.raises(ValueError, match="isn't made from"):
        agent.request_asset(thread, kind="chart", by="maya", sources=[video["id"]])


# -- filing work under assets ----------------------------------------------------------------------


async def test_a_board_is_filed_under_its_asset_and_a_sign_off_unblocks_the_next(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, _ = host
    message = agent.place_template(
        _channel(agent), "launch-kit", by="maya", text="Our launch note."
    )
    await asyncio.sleep(0.05)
    thread = message["thread_id"]
    board_id = await _board(agent, thread)  # no id: the storyboard asset, not the teaser
    assets = _by_title(agent, thread)
    assert (
        assets["Storyboard"]["board_id"] == board_id and assets["Storyboard"]["status"] == "review"
    )
    assert assets["Teaser"]["board_id"] == ""
    approved = agent.send_board(board_id, by="maya", approve=True)
    assert approved["text"] == "Approved “Storyboard”. Go ahead with “Teaser” and “Social cards”."
    assert _by_title(agent, thread)["Storyboard"]["status"] == "approved"


async def test_notes_on_a_board_mark_its_asset(host: tuple[AgentHost, FakeRuntime]) -> None:
    agent, _ = host
    root = agent.post(
        channel_id=_channel(agent), author_id="you", text="A teaser", to_agent=True, kind="video"
    )
    await asyncio.sleep(0.05)
    thread = root["thread_id"]
    board_id = await _board(agent, thread)  # a video's review is its storyboard
    [video] = agent.store.assets(thread)
    assert video["board_id"] == board_id and video["status"] == "review"
    frame = agent.store.frames(board_id)[0]
    agent.add_comment(frame["id"], author_id="maya", text="Bigger", x=0.5, y=0.5)
    agent.send_board(board_id, by="maya", approve=False)
    assert agent.store.asset(video["id"])["status"] == "changes"  # type: ignore[index]


async def test_finished_files_land_on_their_asset_once(host: tuple[AgentHost, FakeRuntime]) -> None:
    agent, _ = host
    message = agent.place_template(
        _channel(agent), "launch-kit", by="maya", text="Our launch note."
    )
    await asyncio.sleep(0.05)
    thread = message["thread_id"]
    teaser = _by_title(agent, thread)["Teaser"]
    said = await agent.deliver_asset(
        None, thread, asset_id=teaser["id"], paths=[FILM], note="Four seconds."
    )
    assert "Delivered 1 file to “Teaser”" in said
    again = await agent.deliver_asset(None, thread, asset_id=teaser["id"], paths=[FILM], note="")
    assert "already on" in again
    view = agent.asset_view(agent.store.asset(teaser["id"]))  # type: ignore[arg-type]
    assert view["status"] == "done" and view["note"] == "Four seconds."
    assert [(f["name"], f["path"]) for f in view["files"]] == [("teaser.mp4", FILM)]
    assert len(agent._delivered[thread]) == 1  # rides on the turn's reply, once
    missing = await agent.deliver_asset(None, thread, asset_id="as_nope", paths=[FILM], note="")
    assert missing.startswith("No asset")


async def test_a_draft_waits_for_its_sign_off_before_the_final(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, runtime = host
    message = agent.place_template(
        _channel(agent), "launch-kit", by="maya", text="Our launch note."
    )
    await asyncio.sleep(0.05)
    thread = message["thread_id"]
    teaser = _by_title(agent, thread)["Teaser"]
    said = await agent.deliver_asset(
        None, thread, asset_id=teaser["id"], paths=[CARDS[0]], note="The timing.", draft=True
    )
    assert "up for review on “Teaser”" in said
    view = agent.asset_view(agent.store.asset(teaser["id"]))  # type: ignore[arg-type]
    assert view["status"] == "review" and view["note"] == "The timing."
    assert agent._waiting_on_people(thread)

    approved = agent.approve_draft(teaser["id"], by="maya")
    await asyncio.sleep(0.05)
    assert approved["text"] == "Approved the draft of “Teaser”. Go ahead with the final."
    assert agent.store.asset(teaser["id"])["status"] == "making"  # type: ignore[index]
    assert runtime.asked[-1][0] == thread
    with pytest.raises(KeyError):
        agent.approve_draft(teaser["id"], by="maya")  # signed off once
    await agent.deliver_asset(None, thread, asset_id=teaser["id"], paths=[FILM], note="")
    assert agent.store.asset(teaser["id"])["status"] == "done"  # type: ignore[index]

    # A final that lands while its draft still waits reads delivered, not for review.
    runtime.binding._backend.files["/workspace/projects/t/renders/cut-2.mp4"] = MP4 + b"2"
    runtime.binding._backend.files["/workspace/projects/t/renders/cut-3.mp4"] = MP4 + b"3"
    paths = ["/workspace/projects/t/renders/cut-2.mp4", "/workspace/projects/t/renders/cut-3.mp4"]
    await agent.deliver_asset(
        None, thread, asset_id=teaser["id"], paths=paths[:1], note="", draft=True
    )
    assert agent.store.asset(teaser["id"])["status"] == "review"  # type: ignore[index]
    await agent.deliver_asset(None, thread, asset_id=teaser["id"], paths=paths[1:], note="")
    assert agent.store.asset(teaser["id"])["status"] == "done"  # type: ignore[index]


async def test_upload_files_finds_the_asset_under_way_or_makes_one(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, _ = host
    root = agent.post(
        channel_id=_channel(agent), author_id="you", text="A teaser", to_agent=True, kind="video"
    )
    await asyncio.sleep(0.05)
    thread = root["thread_id"]
    board_id = await _board(agent, thread)
    agent.send_board(board_id, by="you", approve=True)
    agent.uploading(thread, [FILM])
    agent.deliver(thread, [DeliveredFile("teaser.mp4", MP4)])
    [video] = agent.store.assets(thread)
    assert video["status"] == "done" and video["files"][0]["path"] == FILM

    plain = agent.post(channel_id=_channel(agent), author_id="you", text="A card", to_agent=True)
    await asyncio.sleep(0.05)
    agent.deliver(plain["thread_id"], [DeliveredFile("card.png", PNG)])
    [card] = agent.store.assets(plain["thread_id"])
    assert (card["kind"], card["title"], card["status"]) == ("still", "Stills", "done")


async def test_notes_follow_their_file_and_never_finish_an_asset_waiting_for_sign_off(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    # A live run: the board's sheet and notes went up, then the revised notes on their own.
    agent, _ = host
    message = agent.place_template(
        _channel(agent), "launch-kit", by="maya", text="Our launch note."
    )
    await asyncio.sleep(0.05)
    thread = message["thread_id"]
    await _board(agent, thread)
    sheet, notes = "/workspace/projects/t/board/sheet.png", "/workspace/projects/t/storyboard.md"
    agent.uploading(thread, [sheet, notes])
    agent.deliver(thread, [DeliveredFile("sheet.png", PNG), DeliveredFile("storyboard.md", b"v1")])
    agent.uploading(thread, [notes])
    agent.deliver(thread, [DeliveredFile("storyboard.md", b"v2")])
    agent.uploading(thread, ["/workspace/projects/t/handoffs.md"])
    agent.deliver(thread, [DeliveredFile("handoffs.md", b"beats")])

    sheet_id, v1, v2, handoffs = agent._delivered[thread]
    assets = _by_title(agent, thread)
    assert assets["Storyboard"]["status"] == "review"
    assert [f["id"] for f in assets["Storyboard"]["files"]] == [sheet_id, v1, v2]
    assert assets["Social cards"]["status"] == "planned" and assets["Social cards"]["files"] == []
    [task] = agent.canvas_view(_channel(agent))
    assert len(task["assets"]) == 5 and [f["id"] for f in task["files"]] == [handoffs]


async def test_a_new_film_beside_a_signed_off_storyboard_is_made_from_it(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, _ = host
    root = agent.post(channel_id=_channel(agent), author_id="you", text="Board it", to_agent=True)
    await asyncio.sleep(0.05)
    thread = root["thread_id"]
    board_id = await _board(agent, thread)
    agent.send_board(board_id, by="you", approve=True)
    agent.deliver(thread, [DeliveredFile("teaser.mp4", MP4)])
    board, film = agent.store.assets(thread)
    assert board["kind"] == "board" and board["status"] == "approved"
    assert film["kind"] == "video" and film["sources"] == [board["id"]]


async def test_the_lead_says_where_an_asset_stands(host: tuple[AgentHost, FakeRuntime]) -> None:
    agent, _ = host
    message = agent.place_template(_channel(agent), "pitch", by="you", text="Our notes.")
    await asyncio.sleep(0.05)
    thread = message["thread_id"]
    charts = _by_title(agent, thread)["Charts"]
    assert "reads making" in agent.mark_asset(thread, charts["id"], status="making", note="")
    assert agent.mark_asset(thread, charts["id"], status="done", note="").startswith("Set one of")
    agent.mark_asset(thread, charts["id"], status="blocked", note="Which year's numbers?")
    assert agent.store.asset(charts["id"])["note"] == "Which year's numbers?"  # type: ignore[index]
    agent._settle_status(thread)
    assert agent.store.thread(thread)["status"] == "needs_you"  # type: ignore[index]


def test_older_boards_and_files_are_filed_into_assets(host: tuple[AgentHost, FakeRuntime]) -> None:
    agent, _ = host
    channel = _channel(agent)
    thread = agent.store.add_thread(
        thread_id="th_old", channel_id=channel, task=True, title="Old", kind="board", by="you"
    )["id"]
    board = agent.store.add_board(
        {
            "thread_id": thread,
            "project": "t",
            "title": "Storyboard",
            "kind": "storyboard",
            "version": 1,
            "status": "approved",
        }
    )
    sheet = agent.save_file(thread, "sheet.png", PNG, origin="delivered")
    agent.store.add_message(
        channel_id=channel,
        thread_id=thread,
        author_id=AGENT_ID,
        kind="agent",
        data={"files": [agent.file_view(sheet)]},
    )
    agent.restore()
    agent.restore()
    [asset] = agent.store.assets(thread)
    assert asset["board_id"] == board["id"] and asset["status"] == "approved"
    assert [f["id"] for f in asset["files"]] == [sheet["id"]]
    assert agent.task_view(agent.store.thread(thread))["files"] == []  # type: ignore[arg-type]


# -- the demo lead works a template in order -------------------------------------------------------


def _ask_template() -> HumanMessage:
    return HumanMessage(
        "Launch kit from my notes\n\n(On the canvas, file each asset's work under its id, as the "
        "`canvas` skill says:\n"
        "- as_01 “Storyboard”, a storyboard (pose frames on one sheet): Beats. Made from what this "
        "task started from. The team signs it off on the canvas before anything is made from it.\n"
        "- as_02 “Teaser”, a video or animation: 15 seconds. Made from as_01 “Storyboard”.\n"
        "- as_03 “Thumbnails”, thumbnails (an A/B set): Two arms. Made from as_02 “Teaser”.\n"
        "- as_04 “GIF”, a GIF: A loop. Made from as_02 “Teaser”.\n"
        "- as_05 “Social cards”, a still or ad set (image, banner, sizes, PDF): Cards. Made from "
        "as_01 “Storyboard”.\n- as_06 “Hero art”, a generated image (illustration, texture, plate). "
        "Made from what this task started from.)"
    )


def _play(messages: list[BaseMessage], results: dict[str, str] | None = None) -> list[AIMessage]:
    """Run the demo lead through one turn, answering each tool call (a canned result per tool)."""
    said: list[AIMessage] = []
    for _ in range(40):
        step = demo.next_step(messages)
        said.append(step)
        messages.append(step)
        if not step.tool_calls:
            return said
        for call in step.tool_calls:
            content = (results or {}).get(call["name"], "exit code 0")
            if call["name"] == "canvas_publish_board":
                content = f"“{call['args']['title']}” is on the canvas as board b_{call['args']['asset'][3:]}0."
            elif call["name"] == "canvas_deliver":
                content = "Delivered 1 file."
            messages.append(ToolMessage(content, tool_call_id=call["id"]))
    raise AssertionError("the turn never ended")


def _calls(said: list[AIMessage]) -> list[tuple[str, str]]:
    return [
        (c["name"], str(c["args"].get("asset", "")))
        for m in said
        for c in m.tool_calls
        if c["name"].startswith(("canvas_", "start_render"))
    ]


def test_the_demo_lead_works_a_template_in_order() -> None:
    messages: list[BaseMessage] = [_ask_template()]
    first = _play(messages)
    assert ("canvas_publish_board", "as_01") in _calls(first)
    assert ("canvas_update_asset", "as_06") in _calls(first)  # a kind it doesn't make: skipped
    assert not any(asset in ("as_02", "as_05") for _, asset in _calls(first))  # wait for sign-off

    messages.append(
        HumanMessage("Approved “Storyboard”. Go ahead with “Teaser” and “Social cards”.")
    )
    second = _calls(_play(messages))
    assert ("start_render_job", "") in second and ("canvas_publish_board", "as_05") in second
    assert not any(asset in ("as_03", "as_04") for _, asset in second)  # wait for the film

    messages.append(
        HumanMessage(
            "[Runtime notice, not from the user] A watched job finished.\n- r-1 (Teaser) finished."
        )
    )
    third = _calls(_play(messages, {"execute": '{"ok": true}\nexit code 0'}))
    assert third[0] == ("canvas_deliver", "as_02")
    assert ("canvas_publish_board", "as_03") in third and ("canvas_deliver", "as_04") in third

    messages.append(HumanMessage("Approved “Social cards”. Go ahead."))
    fourth = _calls(_play(messages))
    assert fourth == [("canvas_deliver", "as_05")]


def test_the_demo_lead_answers_notes_on_a_templates_storyboard() -> None:
    messages: list[BaseMessage] = [_ask_template()]
    _play(messages)
    messages.append(HumanMessage("I left notes on “Storyboard”: Beat 2 (1 note). Board b_010."))
    feedback = (
        "Board b_010, “Storyboard”, version 1, changes. Notes are people's feedback on the work.\n"
        "- Beat 2 · The rule draws (v1)\n    cm_aa Maya Chen: Bigger\n"
        '{"board": "b_010", "status": "changes", "frames": [{"frame": "Beat 2 · The rule draws", '
        '"verdict": "", "open": ["cm_aa"]}]}'
    )
    said = _play(messages, {"canvas_read_feedback": feedback})
    published = [c for m in said for c in m.tool_calls if c["name"] == "canvas_publish_board"]
    assert published[0]["args"]["replaces"] == "b_010"
    assert published[0]["args"]["answers"] == ["cm_aa"] and published[0]["args"]["asset"] == "as_01"
    assert [f["name"] for f in published[0]["args"]["frames"]] == ["Beat 2 · The rule draws"]
    assert "answers the notes" in said[-1].content


# -- an episode's brief and plan: words before pictures, each signed off before the next ----------


def _beat(key: str, seconds: int, takeaway: str, says: str) -> dict[str, Any]:
    return {
        "id": key,
        "title": f"Beat {key}",
        "seconds": seconds,
        "takeaway": takeaway,
        "technique": "demonstration",
        "says": says,
        "focal": "the query",
        "demands": ["the words"],
        "change": "The chip splits into its words.",
        "result": "Three words in a row.",
        "enters": "the query chip",
        "leaves": "three words",
    }


LISTED: dict[str, Any] = {
    "section": "chapters",
    "rows": [
        {
            "label": "Chapter 1",
            "title": "Matching words",
            "seconds": 20,
            "asks": "Why not match the words?",
            "ends": "The right page is missed.",
            "covers": "Keyword search and where it fails.",
            "first": "The classic way splits the question into words.",
            "hook": "scenario",
        },
        {
            "label": "Chapter 2",
            "title": "Meaning",
            "seconds": 12,
            "asks": "What else is there?",
            "ends": "A map.",
            "covers": "Embeddings as positions.",
            "handoff": "The query chip crosses the cut.",
            "last": "A map.",
            "landing": "distillation",
        },
    ],
}
BEATS: dict[str, Any] = {
    "section": "chapter",
    "title": "Matching words",
    "beats": [
        _beat(
            "1A",
            12,
            "Search splits the question.",
            SAID := "The classic way splits the question into words.",
        ),
        _beat("1B", 8, "It misses.", "The right page never shows."),
    ],
}
SHOTS: dict[str, Any] = {
    "section": "shots",
    "shots": [
        {
            "beat": "1A",
            "id": "1A.1",
            "seconds": 12,
            "move": "Split",
            "shows": "The chip splits.",
            "vo": SAID,
        },
        {
            "beat": "1B",
            "id": "1B.1",
            "seconds": 8,
            "move": "Sort",
            "shows": "The list sorts.",
            "vo": "The right page never shows.",
            "on": "No match",
        },
    ],
}
BEATS_2: dict[str, Any] = {
    "section": "chapter",
    "title": "Meaning",
    "beats": [_beat("2A", 12, "Meaning has a place.", "A map.")],
}
SHOTS_2: dict[str, Any] = {
    "section": "shots",
    "shots": [
        {
            "beat": "2A",
            "id": "2A.1",
            "seconds": 12,
            "move": "Morph",
            "shows": "A dot.",
            "vo": "A map.",
        }
    ],
}


async def _plan(
    host: tuple[AgentHost, FakeRuntime],
    thread: str,
    *sections: tuple[str, dict[str, Any] | bytes],
    replaces: str = "",
    answers: tuple[str, ...] = (),
    kind: str = "plan",
) -> str:
    """Publish these sections of a plan (or of a brief), each under its name, in the order
    given."""
    agent, runtime = host
    frames = []
    for position, (name, section) in enumerate(sections):
        path = f"/workspace/projects/t/plan/{len(runtime.binding._backend.files)}-{position}.json"
        content = section if isinstance(section, bytes) else json.dumps(section).encode()
        runtime.binding._backend.files[path] = content
        frames.append({"path": path, "name": name})
    return await agent.publish_board(
        None,
        thread,
        project="t",
        title=kind.capitalize(),
        kind=kind,
        frames=frames,
        replaces=replaces or None,
        answers=list(answers),
    )


MATERIAL = "/workspace/attachments/how-our-docs-search-works.md"


async def _episode(host: tuple[AgentHost, FakeRuntime], listed: dict[str, Any]) -> tuple[str, str]:
    """An Episode template placed, its brief signed off, and its plan's chapter list on the
    board: the thread, and the plan's board."""
    agent, runtime = host
    message = agent.place_template(_channel(agent), "episode", by="maya", text="Notes on search.")
    await asyncio.sleep(0.05)
    thread = str(message["thread_id"])
    runtime.binding._backend.files[MATERIAL] = demo.sample.MATERIAL.encode()
    sections = [(name, demo.sample.top(name)) for name in demo.sample.BRIEF]
    await _plan(host, thread, *sections, kind="brief")
    agent.send_board(str(agent.store.boards(thread)[-1]["id"]), by="maya", approve=True)
    await asyncio.sleep(0.05)
    await _plan(host, thread, ("Chapters", listed))
    return thread, str(agent.store.boards(thread)[-1]["id"])


def _one(listed: dict[str, Any]) -> dict[str, Any]:
    """The list with its first chapter alone, which then carries the last line as well."""
    last = {"last": "The right page never shows.", "landing": "callback"}
    return {**listed, "rows": [{**listed["rows"][0], **last}]}


def _sections(agent: AgentHost, board: str) -> dict[str, dict[str, Any]]:
    return {f["name"]: f["data"] for f in agent.board_view(board)["frames"]}


async def test_a_plan_is_signed_off_layer_by_layer(host: tuple[AgentHost, FakeRuntime]) -> None:
    agent, _ = host
    thread, board = await _episode(host, _one(LISTED))
    assert agent.store.board(board)["kind"] == "plan"
    assert _by_title(agent, thread)["Plan"]["status"] == "review"
    [row] = _sections(agent, board)["Chapters"]["rows"]
    assert row["id"] == "chapter-1" and row["time"] == "0:00–0:20"  # the clock is worked out

    # The top layer signed off: the chapters are written next, and the storyboard still waits.
    top = agent.send_board(board, by="maya", approve=True)
    assert top["text"] == (
        "Approved the top layer of “Plan”. Write its chapters in full: “Chapter 1” (20 s). "
        f"Board {board}."
    )
    assets = _by_title(agent, thread)
    assert assets["Plan"]["status"] == "making" and assets["Storyboard"]["status"] == "planned"

    said = await _plan(host, thread, ("Chapter 1", BEATS), ("Chapter 1", SHOTS), replaces=board)
    assert said.startswith("Version 2 of “Plan”")
    assert _by_title(agent, thread)["Plan"]["status"] == "review"
    chapter = _sections(agent, board)["Chapter 1"]
    assert chapter["words"] == "13 words · 6 s of 20 s"
    assert [b["time"] for b in chapter["beats"]] == ["0:00–0:12", "0:12–0:20"]
    assert chapter["beats"][1]["shots"][0]["time"] == "0:12–0:20"

    # A note sits on a row, and the agent is told which.
    frame = agent.board_view(board)["frames"][-1]
    agent.add_comment(frame["id"], author_id="maya", text="Shorter.", x=None, y=None, anchor="1A.1")
    feedback = agent.feedback_text(thread, board)
    assert "[1A.1] Shorter." in feedback and '"rows": ["1A.1"]' in feedback

    done = agent.send_board(board, by="maya", approve=True)
    assert done["text"] == "Approved “Plan”. Go ahead with “Storyboard”."
    assert _by_title(agent, thread)["Plan"]["status"] == "approved"

    # A plan's frame is a section in words, never a picture.
    refused = await _plan(host, thread, ("Chapter 1", PNG), replaces=board)
    assert refused.startswith("Nothing was published: a plan's frame is a JSON file")


async def test_shots_go_on_the_board_only_under_beats_that_are_there(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, _ = host
    thread, board = await _episode(host, _one(LISTED))

    # Shots with no beats to go under, and beats that bring their own shots, are both refused.
    early = await _plan(host, thread, ("Chapter 1", SHOTS), replaces=board)
    assert early == (
        "Nothing was published: “Chapter 1” has no beats on the board. Publish its beats first: "
        "shots are written from them and go under them."
    )
    beside = {**BEATS, "beats": [{**BEATS["beats"][0], "shots": SHOTS["shots"][:1]}]}
    inline = await _plan(host, thread, ("Chapter 1", beside), replaces=board)
    assert "beat 1A carries shots" in inline and "written from the beats" in inline
    assert list(_sections(agent, board)) == ["Chapters"]  # nothing of either went up

    # Beats alone: the chapter is on the board, and not yet written.
    await _plan(host, thread, ("Chapter 1", BEATS), replaces=board)
    assert "shots" not in _sections(agent, board)["Chapter 1"]["beats"][0]
    waiting = agent.send_board(board, by="maya", approve=True)
    assert waiting["text"] == (
        "Approved the top layer of “Plan”. Write only the frames of “Chapter 1” (20 s), from the "
        f"beats as they stand. Board {board}."
    )
    # Asked for on its own, the same: its beats are on the board, so only its frames are written.
    alone = agent.write_chapter(board, "Chapter 1", by="maya")
    assert alone["text"] == (
        "Write only the frames of “Chapter 1” (20 s) of “Plan”, from its beats as they stand. "
        f"Board {board}."
    )

    # A shot under a beat the chapter does not have is refused, and names it.
    stray = {"section": "shots", "shots": [{**SHOTS["shots"][0], "beat": "9Z"}]}
    refused = await _plan(host, thread, ("Chapter 1", stray), replaces=board)
    assert "shot 1A.1 is under beat 9Z, which the chapter does not have" in refused

    await _plan(host, thread, ("Chapter 1", SHOTS), replaces=board)
    chapter = _sections(agent, board)["Chapter 1"]
    assert [s["id"] for b in chapter["beats"] for s in b["shots"]] == ["1A.1", "1B.1"]
    checks = {row["id"]: row["state"] for row in agent.board_view(board)["checks"]}
    assert checks["stale"] == checks["fits"] == checks["read"] == "pass"


async def test_a_beat_that_changes_holds_the_plan_until_its_shots_are_written_again(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, _ = host
    thread, board = await _episode(host, _one(LISTED))
    await _plan(host, thread, ("Chapter 1", BEATS), ("Chapter 1", SHOTS), replaces=board)

    rewritten = _beat("1B", 8, "The right page is missed.", "It never shows.")
    changed = {**BEATS, "beats": [BEATS["beats"][0], rewritten]}
    await _plan(host, thread, ("Chapter 1", changed), replaces=board)
    view = agent.board_view(board)
    beats = {b["id"]: b for b in view["frames"][-1]["data"]["beats"]}
    assert beats["1B"]["stale"] is True and "stale" not in beats["1A"]
    assert beats["1B"]["shots"][0]["id"] == "1B.1"  # still there to read, marked as out of date
    assert view["frames"][-1]["data"]["changed"] == ["1B"]
    stale = next(row for row in view["checks"] if row["id"] == "stale")
    assert stale["state"] == "fail" and stale["text"].startswith("1B: its shots were written")

    # The plan is not whole, so an approval is the top layer's and asks for the chapter again.
    held = agent.send_board(board, by="maya", approve=True)
    assert held["text"].startswith(
        "Approved the top layer of “Plan”. Write only the frames of “Chapter 1” (20 s), from"
    )
    assert _by_title(agent, thread)["Storyboard"]["status"] == "planned"

    again = {"section": "shots", "shots": [{**SHOTS["shots"][1], "vo": "It never shows."}]}
    await _plan(host, thread, ("Chapter 1", again), replaces=board)
    beats = {b["id"]: b for b in _sections(agent, board)["Chapter 1"]["beats"]}
    assert "stale" not in beats["1B"] and beats["1B"]["shots"][0]["vo"] == "It never shows."
    assert beats["1A"]["shots"][0]["id"] == "1A.1"  # the other beat's shots were left alone
    done = agent.send_board(board, by="maya", approve=True)
    assert done["text"] == "Approved “Plan”. Go ahead with “Storyboard”."


async def test_one_part_of_a_plan_is_refined_or_written_alone(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, _ = host
    thread, board = await _episode(host, _one(LISTED))
    [chapters] = agent.board_view(board)["frames"]

    # One row refined: kept as a note on that row, sent at once, and scoped in words.
    asked = agent.refine_plan(
        board, chapters["id"], by="maya", text="Name the map", row="chapter-1"
    )
    assert asked["text"] == (
        "Refine only “Chapters” of “Plan”, at chapter-1: Name the map. Leave every other section "
        f"as it is. Board {board}."
    )
    [note] = agent.board_view(board)["frames"][0]["comments"]
    assert note["anchor"] == "chapter-1"
    assert agent.store.frame(chapters["id"])["verdict"] == "changes"

    # One chapter written early: only a chapter the plan lists, and only once.
    with pytest.raises(KeyError):
        agent.write_chapter(board, "Chapter 9", by="maya")
    early = agent.write_chapter(board, "Chapter 1", by="maya")
    assert early["text"] == (
        f"Write “Chapter 1” (20 s) of “Plan” in full now, before the rest. Board {board}."
    )
    await _plan(host, thread, ("Chapter 1", BEATS), ("Chapter 1", SHOTS), replaces=board)
    with pytest.raises(ValueError, match="already written"):
        agent.write_chapter(board, "Chapter 1", by="maya")

    # A refine says what kind of row it is on: a beat, or one of its frames (a shot).
    chapter = agent.board_view(board)["frames"][-1]
    on_beat = agent.refine_plan(board, chapter["id"], by="maya", text="Plainer", row="1B")
    assert "of “Plan”, at beat 1B: Plainer." in on_beat["text"]
    on_frame = agent.refine_plan(board, chapter["id"], by="maya", text="Shorter", row="1B.1")
    assert "of “Plan”, at frame 1B.1: Shorter." in on_frame["text"]

    # A storyboard is not refined part by part.
    other = await _board(agent, thread)
    [frame, *_] = agent.board_view(other)["frames"]
    with pytest.raises(ValueError, match="Only a brief or a plan"):
        agent.refine_plan(other, frame["id"], by="maya", text="Bigger")


async def test_a_brief_is_signed_off_before_its_plan_is_started(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, runtime = host
    message = agent.place_template(_channel(agent), "episode", by="maya", text="Notes on search.")
    await asyncio.sleep(0.05)
    thread = str(message["thread_id"])
    assets = _by_title(agent, thread)
    assert list(assets) == ["Brief", "Plan", "Storyboard", "Episode", "Shorts"]
    assert assets["Brief"]["gate"] and assets["Plan"]["sources"] == [assets["Brief"]["id"]]

    # A brief that marks a claim made up and names no label for it is not one yet.
    brief, claims = demo.sample.top("Brief"), demo.sample.top("Claims")
    bare = {**brief, "rows": [row for row in brief["rows"] if row["id"] != "label"]}
    refused = await _plan(host, thread, ("Brief", bare), ("Claims", claims), kind="brief")
    assert refused.startswith(
        "Nothing was published: the brief does not pass: a claim is illustrative and the brief "
        "has no `label` row"
    )

    # Its quotes are looked up in the material its source row names.
    runtime.binding._backend.files[MATERIAL] = demo.sample.MATERIAL.encode()
    await _plan(host, thread, ("Brief", brief), ("Claims", claims), kind="brief")
    board = str(agent.store.boards(thread)[-1]["id"])
    assert agent.store.board(board)["kind"] == "brief"
    assert _by_title(agent, thread)["Brief"]["status"] == "review"
    view = agent.board_view(board)
    ledger = view["frames"][1]["data"]["rows"]
    assert all(row["found"] for row in ledger if row["status"] == "stated")
    checks = {row["id"]: (row["state"], row["text"]) for row in view["checks"]}
    assert checks["quotes"] == ("pass", "All 13 quotes are in the material.")

    # A quote that is not the material's words goes up marked, for the team to see.
    wrong = {**claims, "rows": [dict(row) for row in claims["rows"]]}
    wrong["rows"][4]["quote"] = "turns a piece of text into a list of 512 numbers"
    said = await _plan(host, thread, ("Claims", wrong), kind="brief", replaces=board)
    assert "Its checks flag: c4: its quote is not in the material. Mend the ledger now" in said
    quotes = next(row for row in agent.board_view(board)["checks"] if row["id"] == "quotes")
    assert (quotes["state"], quotes["text"]) == ("fail", "c4: its quote is not in the material")
    assert agent.board_view(board)["frames"][1]["data"]["changed"] == ["c4"]

    # One row of it is refined on its own, like a plan's.
    frame = agent.board_view(board)["frames"][1]
    asked = agent.refine_plan(board, frame["id"], by="maya", text="Use its words", row="c4")
    assert asked["text"] == (
        "Refine only “Claims” of “Brief”, at c4: Use its words. Leave every other section as it "
        f"is. Board {board}."
    )
    await _plan(host, thread, ("Claims", claims), kind="brief", replaces=board)

    # Signed off: only now is the plan started, and the plan's review carries the brief.
    assert _by_title(agent, thread)["Plan"]["status"] == "planned"
    done = agent.send_board(board, by="maya", approve=True)
    assert done["text"] == "Approved “Brief”. Go ahead with “Plan”."
    assert _by_title(agent, thread)["Brief"]["status"] == "approved"
    await _plan(host, thread, ("Chapters", _one(LISTED)))
    plan = agent.board_view(str(agent.store.boards(thread)[-1]["id"]))
    assert plan["kind"] == "plan" and plan["brief"] == {
        "board_id": board,
        "frame_id": view["frames"][0]["id"],
        "status": "approved",
        "idea": brief["rows"][0]["text"],
    }
    # The plan's clock is held to the length the brief gives.
    clock = next(row for row in plan["checks"] if row["id"] == "clock")
    assert clock["state"] == "fail" and "the brief says 5:00" in clock["text"]


async def test_the_top_layer_sign_off_leaves_a_chapter_written_early(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, _ = host
    thread, board = await _episode(host, LISTED)
    await _plan(host, thread, ("Chapter 1", BEATS), ("Chapter 1", SHOTS), replaces=board)
    top = agent.send_board(board, by="maya", approve=True)
    assert top["text"] == (
        "Approved the top layer of “Plan”. Write its chapters in full: “Chapter 2” (12 s). "
        f"Board {board}."
    )
    verdicts = {f["name"]: f["verdict"] for f in agent.board_view(board)["frames"]}
    assert verdicts == {"Chapters": "approved", "Chapter 1": ""}
    assert agent.store.board(board)["status"] == "review"

    await _plan(host, thread, ("Chapter 2", BEATS_2), ("Chapter 2", SHOTS_2), replaces=board)
    done = agent.send_board(board, by="maya", approve=True)
    assert done["text"].startswith("Approved “Plan”.")


async def test_a_pipelines_steps_show_on_its_job(host: tuple[AgentHost, FakeRuntime]) -> None:
    from design_agent.harness import events as ev

    agent, _ = host
    thread, _board_id = await _episode(host, _one(LISTED))

    def step(name: str, state: str, task: str = "") -> None:
        agent._on_event(
            ev.Event(
                kind=ev.PIPELINE_STEP,
                thread_id=thread,
                source="p-1a2b3c",
                label="episode_plan",
                text=f"{name}: {state}.",
                data={"step": name, "state": state, "task_id": task},
            )
        )

    step("Chapter 1: beats", "started")
    # The helper that runs the step shows its own steps; the pipeline's step says when it ended.
    agent.store.upsert_work("t-9f8e7d", thread, "helper", label="Chapter 1: beats")
    step("Chapter 1: beats", "done", "t-9f8e7d")
    step("Chapter 1: shots", "started")
    job, helper = agent.store.work(thread)
    assert job["kind"] == "pipeline" and job["steps"] == [
        {"id": "Chapter 1: beats", "title": "Chapter 1: beats", "status": "done"},
        {"id": "Chapter 1: shots", "title": "Chapter 1: shots", "status": "running"},
    ]
    assert helper["status"] == "done" and helper["finished_at"]

    # A step stopped for running past its time never learned its helper's id: the helper is the
    # one still running under the step's name, and it ends with the step.
    step("Chapter 2: beats", "started")
    agent.store.upsert_work("t-5a6b7c", thread, "helper", label="Chapter 2: beats")
    step("Chapter 2: beats", "failed")
    quiet = agent.store.work_item("t-5a6b7c")
    assert quiet["status"] == "failed" and quiet["finished_at"]

    # A pipeline that is cancelled takes its running step and that step's helper with it: no
    # step event says so, and a row left running reads as work still under way.
    agent.store.upsert_work("t-1c2d3e", thread, "helper", label="Chapter 1: shots")
    agent._on_event(
        ev.Event(
            kind=ev.TASK_CANCELLED,
            thread_id=thread,
            source="p-1a2b3c",
            label="episode_plan",
            text="Cancelled.",
        )
    )
    job, *_, stopped = agent.store.work(thread)
    assert job["status"] == "cancelled"
    assert [step["status"] for step in job["steps"]] == ["done", "failed", "failed"]
    assert stopped["status"] == "cancelled" and stopped["finished_at"]


def test_the_canvas_can_stop_a_pipeline_run_as_well_as_a_helper(
    host: tuple[AgentHost, FakeRuntime], monkeypatch: pytest.MonkeyPatch
) -> None:
    from design_agent.middleware import background

    agent, _ = host
    asked: list[tuple[str, str]] = []

    def stop(task_id: str, thread_id: str) -> str | None:
        asked.append((task_id, thread_id))
        return "Cancelled pipeline p-1a2b3c." if task_id.startswith("p-") else None

    monkeypatch.setattr(background, "CANCELLERS", [*background.CANCELLERS, stop])
    monkeypatch.setattr("design_agent.surfaces.web.agent.CANCELLERS", background.CANCELLERS)
    assert agent.cancel_work("th_1", "p-1a2b3c") == "Cancelled pipeline p-1a2b3c."
    # What no canceller knows is a helper's to answer for.
    assert agent.cancel_work("th_1", "t-000000") == "No task t-000000 on this thread."
    assert asked[-1] == ("t-000000", "th_1")


def _ask_episode() -> HumanMessage:
    return HumanMessage(
        "Episode from my notes\n\n(On the canvas, file each asset's work under its id, as the "
        "`canvas` skill says:\n"
        "- as_01 “Brief”, a brief (an episode's idea, who it is for, its length and a ledger of "
        "what it may state, in words): The idea. Made from what this task started from. The team "
        "signs it off on the canvas before anything is made from it.\n"
        "- as_02 “Plan”, a plan (an episode's spine, chapters, beats and shots, in words): Spine "
        "first. Made from as_01 “Brief”. The team signs it off on the canvas before anything is "
        "made from it.\n"
        "- as_03 “Storyboard”, a storyboard (pose frames on one sheet): Poses. Made from as_02 "
        "“Plan”. The team signs it off on the canvas before anything is made from it.\n"
        "- as_04 “Episode”, a video or animation: The film. Made from as_03 “Storyboard”.)"
    )


def _planned() -> list[BaseMessage]:
    """An episode whose brief is signed off and whose plan's top layer is on the canvas."""
    messages: list[BaseMessage] = [_ask_episode()]
    _play(messages, RUNNING)
    messages.append(_landed(_report("brief")))
    _play(messages, RUNNING)
    messages.append(HumanMessage("Approved “Brief”. Go ahead with “Plan”."))
    _play(messages, RUNNING)
    messages.append(_landed(_report("top")))
    _play(messages, RUNNING)
    return messages


def _published(said: list[AIMessage]) -> list[dict[str, Any]]:
    return [c["args"] for m in said for c in m.tool_calls if c["name"] == "canvas_publish_board"]


def _runs(said: list[AIMessage]) -> list[dict[str, Any]]:
    """The `episode_plan` runs a turn started, as their arguments."""
    return [
        json.loads(c["args"]["args_json"])
        for m in said
        for c in m.tool_calls
        if c["name"] == "run_pipeline" and c["args"]["name"] == "episode_plan"
    ]


def _landed(report: dict[str, Any]) -> HumanMessage:
    """The notice that wakes the lead when an `episode_plan` run ends, with its report."""
    return HumanMessage(
        "[Runtime notice, not from the user] A background job ended.\n"
        "- p-1a2b3c (episode_plan): done in 1 min. Its report:\n" + json.dumps(report, indent=1)
    )


def _report(stage: str, *names: str) -> dict[str, Any]:
    folder = "/workspace/projects/episode-as_01/plan"
    if stage in ("brief", "top"):
        sections = demo.sample.BRIEF if stage == "brief" else demo.sample.TOP
        files = [{"name": n, "path": f"{folder}/{f}"} for n, (_, f) in sections.items()]
    else:
        files = [
            {"name": n, "path": f"{folder}/{demo.sample.stem(n)}.{part}.json"}
            for n in names
            for part in ("beats", "shots")
        ]
    return {"project": "episode-as_01", "stage": stage, "publish": files, "open": {}, "failed": []}


RUNNING = {"run_pipeline": "Started p-1a2b3c (episode_plan) in the background."}


def test_the_demo_lead_writes_the_brief_first_and_plans_only_once_it_is_signed_off() -> None:
    messages: list[BaseMessage] = [_ask_episode()]
    first = _play(messages, RUNNING)
    # The material is kept as a file, so each quote in the ledger can be looked up in it.
    [kept] = [c["args"] for m in first for c in m.tool_calls if c["name"] == "write_file"]
    assert kept["file_path"] == "/workspace/projects/episode-as_01/material.md"
    assert _runs(first) == [
        {"project": "episode-as_01", "stage": "brief", "material": [kept["file_path"]]}
    ]
    assert not _published(first) and "nothing is planned before it" in first[-1].content

    # The run ends: its two sections go up as the brief's board, and the plan is not started.
    messages.append(_landed(_report("brief")))
    second = _play(messages, RUNNING)
    [brief] = _published(second)
    assert brief["kind"] == "brief" and brief["asset"] == "as_01" and "replaces" not in brief
    assert [f["name"] for f in brief["frames"]] == ["Brief", "Claims"]
    assert not _runs(second) and "Nothing is planned before you sign it off" in second[-1].content

    # A row of the brief refined: a small edit the lead makes itself, on the brief's board.
    messages.append(
        HumanMessage(
            "Refine only “Claims” of “Brief”, at c7: Plainer. Leave every other section as it "
            "is. Board b_010."
        )
    )
    feedback = (
        "Board b_010, “Brief”, version 1, changes. Notes are people's feedback on the work.\n"
        '{"board": "b_010", "status": "changes", "frames": [{"frame": "Claims", '
        '"verdict": "changes", "open": ["cm_aa"], "rows": ["c7"]}]}'
    )
    said = _play(messages, {**RUNNING, "canvas_read_feedback": feedback})
    [edited] = [c["args"] for m in said for c in m.tool_calls if c["name"] == "write_file"]
    assert edited["file_path"].endswith("/episode-as_01/plan/claims.json")
    rows = {row["id"]: row for row in json.loads(edited["content"])["rows"]}
    assert rows["c7"]["claim"].startswith("Measuring the distance to every passage")
    [again] = _published(said)
    assert again["kind"] == "brief" and again["replaces"] == "b_010" and not _runs(said)

    # Signed off: the plan's top layer is written, in the brief's folder.
    messages.append(HumanMessage("Approved “Brief”. Go ahead with “Plan”."))
    third = _play(messages, RUNNING)
    assert _runs(third) == [{"project": "episode-as_01", "stage": "top"}]
    assert "the spine first" in third[-1].content


def test_the_demo_lead_runs_the_plan_pipeline_and_publishes_what_it_wrote() -> None:
    messages = _planned()
    [top] = [
        b
        for b in _published([m for m in messages if isinstance(m, AIMessage)])
        if b["kind"] == "plan"
    ]
    assert top["asset"] == "as_02" and "replaces" not in top
    assert [f["name"] for f in top["frames"]] == ["Spine", "Chapters", "Sound and look"]
    assert top["frames"][0]["path"].endswith("/episode-as_01/plan/spine.json")
    assert "No chapter is written before you sign it off" in str(messages[-1].content)

    # The top layer signed off: the chapters it names go to the pipeline, with their lengths.
    messages.append(
        HumanMessage(
            "Approved the top layer of “Plan”. Write its chapters in full: “Open” (20 s), "
            "“Chapter 3” (65 s). Board b_020."
        )
    )
    third = _play(messages, RUNNING)
    assert _runs(third) == [
        {
            "project": "episode-as_01",
            "stage": "chapters",
            "chapters": {"Open": 20.0, "Chapter 3": 65.0},
        }
    ]
    assert "its beats first, then its frames" in third[-1].content

    # The run ends: each chapter's beats, then its shots, on the same board, and what the first
    # reader sent back is said.
    report = _report("chapters", "Open", "Chapter 3")
    report["reader"] = {"verdict": "fix", "sent_back": {"Chapter 3": ["Say why."]}, "left": {}}
    messages.append(_landed(report))
    said = _play(messages, {**RUNNING, "canvas_read_feedback": "No open notes."})
    [chapters] = _published(said)
    assert chapters["replaces"] == "b_020" and chapters["asset"] == "as_02"
    assert [(f["name"], f["path"].rsplit(".", 2)[1]) for f in chapters["frames"]] == [
        ("Open", "beats"),
        ("Open", "shots"),
        ("Chapter 3", "beats"),
        ("Chapter 3", "shots"),
    ]
    assert "A first reader sent “Chapter 3” back once" in said[-1].content

    messages.append(HumanMessage("Approved “Plan”. Go ahead with “Storyboard”."))
    assert ("canvas_publish_board", "as_03") in _calls(_play(messages))


def test_the_demo_lead_sends_a_beat_back_through_the_pipeline_and_edits_a_frame_itself() -> None:
    messages = _planned()

    # One chapter written early.
    messages.append(
        HumanMessage(
            "Write “Chapter 3” (65 s) of “Plan” in full now, before the rest. Board b_020."
        )
    )
    assert _runs(_play(messages, RUNNING)) == [
        {"project": "episode-as_01", "stage": "chapters", "chapters": {"Chapter 3": 65.0}}
    ]
    messages.append(_landed(_report("chapters", "Chapter 3")))
    _play(messages, {**RUNNING, "canvas_read_feedback": "No open notes."})

    # A beat refined: it goes back through the pipeline, so its shots are written from it again.
    messages.append(
        HumanMessage(
            "Refine only “Chapter 3” of “Plan”, at beat 3A: Plainer. Leave every other section as "
            "it is. Board b_020."
        )
    )
    said = _play(messages, RUNNING)
    [run] = _runs(said)
    assert run["chapters"] == {"Chapter 3": 65.0} and run["notes"] == "“Chapter 3”, at beat 3A"
    assert run["review"] is False  # the person who asked is its reader
    assert not _published(said) and "the beat first, then the frames" in said[-1].content
    messages.append(_landed(_report("chapters", "Chapter 3")))
    feedback = (
        "Board b_020, “Plan”, version 3, changes. Notes are people's feedback on the work.\n"
        '{"board": "b_020", "status": "changes", "frames": [{"frame": "Chapter 3", '
        '"verdict": "changes", "open": ["cm_aa"], "rows": ["3A"]}]}'
    )
    [again] = _published(_play(messages, {**RUNNING, "canvas_read_feedback": feedback}))
    assert again["answers"] == ["cm_aa"] and again["replaces"] == "b_020"

    # A frame refined: a small edit the lead makes itself. The words a frame says are its
    # beat's, so the beats go up with the shots, and before them.
    messages.append(
        HumanMessage(
            "Refine only “Chapter 3” of “Plan”, at frame 3B.1: Shorter. Leave every other section "
            "as it is. Board b_020."
        )
    )
    feedback = feedback.replace("cm_aa", "cm_bb").replace('"3A"', '"3B.1"')
    said = _play(messages, {**RUNNING, "canvas_read_feedback": feedback})
    assert not _runs(said)
    beats, written = [c["args"] for m in said for c in m.tool_calls if c["name"] == "write_file"]
    assert beats["file_path"].endswith("/episode-as_01/plan/chapter-3.beats.json")
    assert written["file_path"].endswith("/episode-as_01/plan/chapter-3.shots.json")
    shots = {s["id"]: s for s in json.loads(written["content"])["shots"]}
    # It keeps what the beat's rewrite changed (3A.1 was written again with 3A).
    assert shots["3A.1"]["vo"].startswith("Finding the nearest dot sounds easy: measure")
    said_by = {b["id"]: b["says"] for b in json.loads(beats["content"])["beats"]}
    assert said_by["3A"].startswith(shots["3A.1"]["vo"])
    [refined] = _published(said)
    assert [f["name"] for f in refined["frames"]] == ["Chapter 3", "Chapter 3"]
    assert refined["answers"] == ["cm_bb"]
    assert [f["path"].rsplit(".", 2)[1] for f in refined["frames"]] == ["beats", "shots"]


def test_the_demo_lead_edits_a_row_of_the_top_layer_itself() -> None:
    messages = _planned()
    messages.append(HumanMessage("I left notes on “Plan”: Chapters (1 note). Board b_020."))
    feedback = (
        "Board b_020, “Plan”, version 1, changes. Notes are people's feedback on the work.\n"
        "- Chapters (v1)\n    cm_aa Maya Chen: [ch2] Name the map\n"
        '{"board": "b_020", "status": "changes", "frames": [{"frame": "Chapters", '
        '"verdict": "", "open": ["cm_aa"], "rows": ["ch2"]}]}'
    )
    said = _play(messages, {**RUNNING, "canvas_read_feedback": feedback})
    [rewritten] = [c["args"] for m in said for c in m.tool_calls if c["name"] == "write_file"]
    rows = {row["id"]: row for row in json.loads(rewritten["content"])["rows"]}
    assert rows["ch2"]["asks"].endswith("have a place on a map that search can compare?")
    assert rows["ch1"]["asks"] == "Why can't search just match the words?"  # left as it was
    [revised] = _published(said)
    assert revised["replaces"] == "b_020" and revised["answers"] == ["cm_aa"]
    assert [f["name"] for f in revised["frames"]] == ["Chapters"] and not _runs(said)


def test_the_demo_lead_writes_only_the_frames_of_a_chapter_whose_beats_stand() -> None:
    messages = _planned()
    messages.append(
        HumanMessage(
            "Approved the top layer of “Plan”. Write its chapters in full: “Open” (20 s). Write "
            "only the frames of “Chapter 1” (55 s), “Chapter 2” (65 s), from the beats as they "
            "stand. Board b_020."
        )
    )
    said = _play(messages, RUNNING)
    assert _runs(said) == [
        {"project": "episode-as_01", "stage": "chapters", "chapters": {"Open": 20.0}},
        {
            "project": "episode-as_01",
            "stage": "shots",
            "chapters": {"Chapter 1": 55.0, "Chapter 2": 65.0},
        },
    ]
    messages.append(
        HumanMessage(
            "Write only the frames of “Chapter 3” (65 s) of “Plan”, from its beats as they stand. "
            "Board b_020."
        )
    )
    [run] = _runs(_play(messages, RUNNING))
    assert run["stage"] == "shots" and run["chapters"] == {"Chapter 3": 65.0}
