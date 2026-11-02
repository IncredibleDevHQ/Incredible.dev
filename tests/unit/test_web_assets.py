"""The canvas's assets: the kinds of work and the templates, asking for them, filing a task's
boards and files under them, sign-offs that unblock the next, and the demo lead working a
template in order."""

from __future__ import annotations

import asyncio
from pathlib import Path

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
