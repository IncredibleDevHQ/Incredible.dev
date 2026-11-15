"""An episode in the web app: started from material, planned in turns by a writer the person
picks, its pictures built and posed, its takes kept, its film rendered; and every agent run kept
in the house's own record, a local agent's session being only a shortcut to it."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator, Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from design_agent.config import Settings
from design_agent.episode import picture
from design_agent.surfaces.web import catalog
from design_agent.surfaces.web.agent import AgentHost
from design_agent.surfaces.web.app import create_app
from design_agent.surfaces.web.episode_desk import EPISODE, EpisodeDesk, _changed, _shape
from design_agent.surfaces.web.episode_workers import (
    BUILTIN,
    DEMO,
    DemoWorker,
    LocalWorker,
    Told,
    retold,
)
from design_agent.surfaces.web.hub import Hub
from design_agent.surfaces.web.research import (
    CLAUDE_WRITER_TOOLS,
    HARNESSES,
    Event,
    command,
)
from design_agent.surfaces.web.research_desk import ResearchDesk
from design_agent.surfaces.web.store import Store
from tests.unit.test_web_surface import FakeBackend, FakeRuntime

ROOT = Path(__file__).resolve().parents[2]
SCRIPT: dict[str, Any] = json.loads(
    (ROOT / "src/design_agent/surfaces/web/demo_episode.json").read_text(encoding="utf8")
)
NOTES = "Notes on one idea.\n\nA second paragraph of the notes."
PNG = b"\x89PNG\r\n\x1a\nstill"


async def settle(done: Any, *, seconds: float = 5.0) -> None:
    """Wait for a background job the desk started."""
    for _ in range(int(seconds / 0.01)):
        if done():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the job did not finish")


@pytest.fixture
async def house(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AgentHost, None]:
    """A house whose episodes are written by the demo's writer and posed without a computer."""
    host = AgentHost(
        settings=Settings(_env_file=None),
        store=Store(tmp_path / "house.sqlite"),
        hub=Hub(),
        data_dir=tmp_path,
        demo=True,
        project_root=ROOT,
    )
    host.runtime = FakeRuntime(FakeBackend({}))  # type: ignore[assignment]
    desk = host.episodes
    desk.workers[DEMO] = DemoWorker(data_dir=tmp_path, script=SCRIPT, pause=0)

    def pose(
        episode: Any, unit: Any, full: Any, html: str, strict: bool = True
    ) -> tuple[list[str], dict[str, str]]:
        stills = {
            frame: str(
                host.save_file(episode["thread_id"], f"{frame}.png", PNG, origin="episode")["id"]
            )
            for frame in unit["frames"]
        }
        return [], stills

    monkeypatch.setattr(desk, "_pose", pose)
    monkeypatch.setattr(desk, "_clip", lambda episode, unit: "")
    yield host
    await desk.close()


async def planned(host: AgentHost, **settings: Any) -> str:
    channel = host.store.channels()[0]["id"]
    view = host.episodes.create(channel, by="you", title="One idea", text=NOTES, settings=settings)
    await settle(lambda: not host.episodes.planning(view["id"]))
    return str(view["id"])


# -- starting and planning ------------------------------------------------------------------------


async def test_an_episode_is_a_task_with_an_asset_and_a_plan_written_in_stages(
    house: AgentHost,
) -> None:
    episode_id = await planned(house)
    view = house.episodes.view(episode_id)
    assert view["status"] == "plan" and not view["approved"]
    assert view["plan"]["title"] == "One idea" and len(view["plan"]["chapters"]) >= 3
    assert view["clock"]["total"] == pytest.approx(view["plan"]["totals"]["seconds"], abs=0.5)
    thread = house.store.thread(view["thread_id"])
    assert thread is not None and thread["task"] and thread["kind"] == EPISODE
    assert thread["status"] == "needs_you", "a plan waits on the person's approval"
    asset = house.store.asset(view["asset_id"])
    assert asset is not None and asset["kind"] == EPISODE and asset["status"] == "review"
    task = next(
        t for t in house.canvas_view(thread["channel_id"]) if t["thread"]["id"] == thread["id"]
    )
    assert task["episodes"][0]["id"] == episode_id and task["material"]["text"] == NOTES
    # the writer's file is the writer's: the person's facts are laid over it, not written into it
    assert view["plan"]["brief"]["seconds"] == [300, 420]
    assert house.store.episode(episode_id)["plan"]["brief"] == SCRIPT["plan"]["brief"]  # type: ignore[index]


async def test_the_persons_facts_win_over_the_writers(house: AgentHost) -> None:
    episode_id = await planned(house, seconds=[420, 540], theme="panel-and-portrait")
    view = house.episodes.view(episode_id)
    plan = view["plan"]
    assert plan["brief"]["seconds"] == [420, 540] and plan["brief"]["theme"] == "panel-and-portrait"
    layouts = {f["layout"] for ch in plan["chapters"] for b in ch["beats"] for f in b["frames"]}
    assert "panel-and-portrait" in layouts and "corner-window" not in layouts
    # the demo's script is five minutes long: under the least asked for, and said so
    (length,) = [c for c in view["checks"] if c["rule"] == "length"]
    assert length["level"] == "must" and "add at least" in length["text"]


def test_a_length_is_a_least_and_a_most_with_room_between(house: AgentHost) -> None:
    desk = house.episodes
    assert desk.options()["seconds"] == {"least": 240, "most": 600, "usual": [300, 420], "gap": 30}
    assert desk._settings({})["seconds"] == [300, 420]
    for asked, kept in (
        ((300, 310), [300, 330]),  # never closer than the gap
        ((590, 600), [570, 600]),  # the gap is made downwards at the top
        ((60, 1200), [240, 600]),  # inside the limits
        ((420, 300), [300, 420]),  # the least first
        ("auto", "auto"),
    ):
        assert desk._settings({"seconds": asked})["seconds"] == kept


async def test_a_length_left_open_is_not_in_the_brief_and_is_never_checked(
    tmp_path: Path, house: AgentHost
) -> None:
    prompts: list[str] = []

    class Listening(DemoWorker):
        async def turn(self, episode: Any, *, lane: str, prompt: str, heard: Any) -> Told:
            prompts.append(prompt)
            return await super().turn(episode, lane=lane, prompt=prompt, heard=heard)

    house.episodes.workers[DEMO] = Listening(data_dir=tmp_path, script=SCRIPT, pause=0)
    asked = await planned(house, seconds=[300, 360])
    assert "between 300 and 360 seconds (`seconds`: [300, 360])" in prompts[0]
    assert not [c for c in house.episodes.view(asked)["checks"] if c["rule"] == "length"]

    prompts.clear()
    episode_id = await planned(house, seconds="auto")
    view = house.episodes.view(episode_id)
    assert "no length (leave `seconds` out of the brief" in prompts[0]
    assert view["settings"]["seconds"] == "auto" and "seconds" not in view["plan"]["brief"]
    assert not [c for c in view["checks"] if c["rule"] == "length"]


def test_an_episode_needs_material_and_a_writer_that_is_ready(house: AgentHost) -> None:
    channel = house.store.channels()[0]["id"]
    with pytest.raises(ValueError, match="starts from material"):
        house.episodes.create(channel, by="you", text="  ")
    with pytest.raises(ValueError, match="isn't ready"):
        house.episodes.create(channel, by="you", text=NOTES, settings={"writer": "kimi"})
    with pytest.raises(ValueError, match="no look"):
        house.episodes.create(channel, by="you", text=NOTES, settings={"theme": "sepia"})


def test_the_shape_of_a_plan_is_checked_before_any_of_it_is_read() -> None:
    assert _shape([], "brief") == ["plan.json must hold one JSON object."]
    assert _shape({"brief": {}, "material": [{"id": "m1", "text": "x"}]}, "brief") == []
    twice = {
        "brief": {},
        "material": [{"id": "m1", "text": "x"}],
        "chapters": [
            {
                "id": "c1",
                "question": "?",
                "beats": [{"id": "b", "says": "a"}, {"id": "b", "says": "b"}],
            }
        ],
    }
    assert any("used twice" in p for p in _shape(twice, "script"))
    assert any("at least one chapter" in p for p in _shape({"brief": {}, "material": []}, "script"))


async def test_a_plan_that_breaks_a_rule_goes_back_to_the_writer_with_the_report(
    tmp_path: Path, house: AgentHost
) -> None:
    prompts: list[str] = []

    class Stubborn(DemoWorker):
        async def turn(self, episode: Any, *, lane: str, prompt: str, heard: Any) -> Told:
            prompts.append(prompt)
            if "Stage: brief" in prompt and len(prompts) == 1:
                folder = self.folder(episode)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "plan.json").write_text('{"brief": {}, "material": [')
                return Told(answer="Wrote it.")
            return await super().turn(episode, lane=lane, prompt=prompt, heard=heard)

    house.episodes.workers[DEMO] = Stubborn(data_dir=tmp_path, script=SCRIPT, pause=0)
    episode_id = await planned(house)
    assert house.episodes.view(episode_id)["status"] == "plan"
    assert "Stage: fix (the brief stage)" in prompts[1] and "not valid JSON" in prompts[1]


async def test_a_writer_that_gives_no_reply_stops_the_plan_and_it_can_be_picked_up(
    tmp_path: Path, house: AgentHost
) -> None:
    class Silent(DemoWorker):
        fail = True

        async def turn(self, episode: Any, *, lane: str, prompt: str, heard: Any) -> Told:
            if self.fail and "Stage: script" in prompt:
                return Told(failure="It isn't signed in.")
            return await super().turn(episode, lane=lane, prompt=prompt, heard=heard)

    worker = Silent(data_dir=tmp_path, script=SCRIPT, pause=0)
    house.episodes.workers[DEMO] = worker
    episode_id = await planned(house)
    view = house.episodes.view(episode_id)
    assert view["status"] == "failed" and "signed in" in view["stage"]["said"]
    assert view["stage"]["name"] == "script" and view["written"]["material"] > 0
    assert house.store.thread(view["thread_id"])["status"] == "needs_you"  # type: ignore[index]
    assert house.store.asset(view["asset_id"])["status"] == "blocked"  # type: ignore[index]
    worker.fail = False
    house.episodes.again(episode_id)
    await settle(lambda: not house.episodes.planning(episode_id))
    assert house.episodes.view(episode_id)["status"] == "plan"


# -- the studio: approval, picks, pictures --------------------------------------------------------


async def test_approving_the_plan_starts_its_pictures(house: AgentHost) -> None:
    episode_id = await planned(house)
    with pytest.raises(ValueError, match="Approve the plan first"):
        house.episodes.render(episode_id, by="you")
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    view = house.episodes.view(episode_id)
    assert view["status"] == "studio" and view["approved"]
    assert view["units"] and {u["picture"]["status"] for u in view["units"]} == {"made"}
    one = view["units"][0]
    assert set(one["picture"]["stills"]) == set(one["frames"])
    assert one["picture"]["stills"][one["frames"][0]]["url"].startswith("/api/files/")
    assert house.store.thread(view["thread_id"])["status"] == "idle"  # type: ignore[index]


async def test_stop_reaches_the_pictures_and_the_ones_that_stopped_are_made_on_request(
    tmp_path: Path, house: AgentHost
) -> None:
    episode_id = await planned(house)
    # a writer slow enough for a stop to land while its pictures are being made
    house.episodes.workers[DEMO] = DemoWorker(data_dir=tmp_path, script=SCRIPT, pause=5)
    house.episodes.approve(episode_id, by="you")
    await asyncio.sleep(0.05)
    assert house.episodes.view(episode_id)["pictures"]["making"] > 0
    house.episodes.stop(episode_id)
    await settle(lambda: not house.episodes._busy(episode_id))
    view = house.episodes.view(episode_id)
    assert {u["picture"]["status"] for u in view["units"]} == {"failed"}
    assert {u["picture"]["failure"] for u in view["units"]} == {"Stopped."}
    assert view["pictures"] == {"made": 0, "go": 0, "making": 0, "failed": len(view["units"])}
    # nothing starts again by itself: a person asks
    house.episodes.workers[DEMO] = DemoWorker(data_dir=tmp_path, script=SCRIPT, pause=0)
    house.episodes.make(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    view = house.episodes.view(episode_id)
    assert {u["picture"]["status"] for u in view["units"]} == {"made"}
    with pytest.raises(ValueError, match="made or on its way"):
        house.episodes.make(episode_id, by="you")


async def test_a_restart_stops_what_was_under_way_and_the_card_says_where_it_stands(
    house: AgentHost,
) -> None:
    episode_id = await planned(house, level="rich")
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    view = house.episodes.view(episode_id)
    one, other = view["units"][0]["id"], view["units"][1]["id"]
    # as a process that died mid-work leaves it: a picture half made, the card still "making"
    house.store.set_picture(episode_id, one, status="making")
    house.set_asset(view["asset_id"], status="making")
    house.store.update_thread(view["thread_id"], status="working")
    house.episodes.restore()
    after = house.episodes.view(episode_id)
    stopped = next(u for u in after["units"] if u["id"] == one)["picture"]
    assert stopped["status"] == "failed" and "restarted" in stopped["failure"]
    assert next(u for u in after["units"] if u["id"] == other)["picture"]["status"] == "go"
    # stills still wait for a go, so the card is for review and the thread waits on a person
    assert house.store.asset(view["asset_id"])["status"] == "review"  # type: ignore[index]
    assert house.store.thread(view["thread_id"])["status"] == "needs_you"  # type: ignore[index]
    # a change that was under way when the house stopped is not left half made
    stood = house.store.episode(episode_id)
    assert stood is not None
    house.episodes._snapshot(episode_id, why="A change that never landed")
    half = json.loads(json.dumps(stood["plan"]))
    half["chapters"] = half["chapters"][:1]
    house.store.update_episode(
        episode_id, plan=half, stage={"name": "change", "state": "working", "said": "Writing"}
    )
    house.episodes.restore()
    again = house.episodes.view(episode_id)
    assert len(again["plan"]["chapters"]) == len(stood["plan"]["chapters"])
    assert again["status"] == "studio" and again["stage"]["state"] == "stopped"
    assert house.store.snapshot(episode_id) is None


async def test_a_line_that_loses_its_picture_takes_the_pictures_record_with_it(
    house: AgentHost,
) -> None:
    episode_id = await planned(house, level="rich")
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    before = house.episodes.view(episode_id)
    assert before["pictures"]["go"] == len(before["units"])
    # a picture the plan no longer has, still waiting for a go nobody can give
    house.store.set_picture(episode_id, "c9.b9.f9", status="go", sig="gone")
    assert (
        house.episodes.card(house.store.episode(episode_id) or {})["pictures"]["go"]
        == len(before["units"]) + 1
    )
    house.episodes._queue_pictures(episode_id)
    assert house.store.picture(episode_id, "c9.b9.f9") is None
    assert house.episodes.view(episode_id)["pictures"]["go"] == len(before["units"])


async def test_a_rich_picture_waits_for_the_persons_go_and_a_note_builds_it_again(
    house: AgentHost,
) -> None:
    episode_id = await planned(house, level="rich")
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    view = house.episodes.view(episode_id)
    assert {u["picture"]["status"] for u in view["units"]} == {"go"}
    assert view["pictures"]["go"] == len(view["units"])
    assert house.store.thread(view["thread_id"])["status"] == "needs_you"  # type: ignore[index]
    unit = view["units"][0]["id"]
    view = house.episodes.go(episode_id, unit, by="you")
    assert next(u for u in view["units"] if u["id"] == unit)["picture"]["status"] == "made"
    other = view["units"][1]["id"]
    with pytest.raises(ValueError, match="Say what to change"):
        house.episodes.send_back(episode_id, other, by="you", note=" ")
    house.episodes.send_back(episode_id, other, by="you", note="Make the first box larger.")
    await settle(lambda: not house.episodes._busy(episode_id))
    brief = json.loads(
        (
            house.episodes.data_dir
            / "episodes"
            / episode_id
            / "pictures"
            / f"{picture.composition_id(other)}.brief.json"
        ).read_text()
    )
    assert brief["note_from_the_person"] == "Make the first box larger."
    again = next(u for u in house.episodes.view(episode_id)["units"] if u["id"] == other)
    assert again["picture"]["status"] == "go"


async def test_a_rich_pictures_builder_looks_at_its_stills_once(
    tmp_path: Path, house: AgentHost
) -> None:
    looked: list[str] = []

    class Careful(DemoWorker):
        async def turn(self, episode: Any, *, lane: str, prompt: str, heard: Any) -> Told:
            if lane.startswith("picture:") and "Look at how" in prompt:
                shown = sorted((self.folder(episode) / "pictures").glob("*.stills/*.png"))
                looked.append(f"{lane}:{len(shown)}")
                if lane.endswith(first):
                    file = next((self.folder(episode) / "pictures").glob(f"{comp}.html"))
                    file.write_text(
                        file.read_text().replace("font-weight: 600", "font-weight: 700")
                    )
                    return Told(answer="Made the labels heavier.")
            return await super().turn(episode, lane=lane, prompt=prompt, heard=heard)

    house.episodes.workers[DEMO] = Careful(data_dir=tmp_path, script=SCRIPT, pause=0)
    episode_id = await planned(house, level="rich")
    units_before = house.episodes.view(episode_id)["units"]
    first = units_before[0]["id"]
    comp = picture.composition_id(first)
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    assert len(looked) == len(units_before) and all(not entry.endswith(":0") for entry in looked)
    assert "font-weight: 700" in house.store.picture(episode_id, first)["html"]  # type: ignore[index]
    other = house.store.picture(episode_id, units_before[1]["id"])
    assert other is not None and "font-weight: 600" in other["html"] and other["status"] == "go"


async def test_a_film_nobody_records_is_narrated_line_by_line(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic import SecretStr

    from design_agent.tools import media

    house.settings = house.settings.model_copy(
        update={"elevenlabs_api_key": SecretStr("key"), "narrator_voice_id": "voice1234567890"}
    )
    said: list[str] = []

    async def speak(keys: Any, text: str, voice_id: str, **more: Any) -> media.Spoken:
        said.append(text)
        return media.Spoken(b"mp3", 2.0, [{"word": "Now", "start": 0.0, "end": 0.2}])

    monkeypatch.setattr(media, "speak", speak)
    assert house.episodes.options()["narrator"]
    episode_id = await planned(house, presenter="off", voice="narrator")
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    await house.episodes._narrate(episode_id)
    view = house.episodes.view(episode_id)
    lines = view["clock"]["lines"]
    assert len(said) == len(lines) and {line["source"]["kind"] for line in lines} == {"voice"}
    assert view["clock"]["total"] == pytest.approx(len(lines) * 2.25 + 3 + 5, abs=0.01)
    await house.episodes._narrate(episode_id)
    assert len(said) == len(lines), "a line is spoken once, until its words change"
    assert "voice" not in view["film_state"], "the narration's files are not the studio's to draw"


async def test_a_pick_is_kept_and_a_new_layout_builds_the_picture_for_its_new_canvas(
    house: AgentHost,
) -> None:
    episode_id = await planned(house)
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    before = house.episodes.view(episode_id)
    unit = next(u for u in before["units"] if u["layout"] == "corner-window")
    first = unit["frames"][0]
    view = house.episodes.choose(
        episode_id,
        by="you",
        change={"frames": {first: {"layout": "split"}}, "units": {unit["id"]: {"level": "rich"}}},
    )
    changed = next(u for u in view["units"] if u["id"] == unit["id"])
    assert changed["layout"] == "split" and changed["canvas"] == [864, 960]
    assert changed["level"] == "rich" and changed["picture"]["status"] == "queued"
    # a picture already made, made rich: its stills wait for the go; simple again, they don't
    other = next(u for u in before["units"] if u["id"] != unit["id"])
    waits = house.episodes.choose(
        episode_id, by="you", change={"units": {other["id"]: {"level": "rich"}}}
    )
    assert next(u for u in waits["units"] if u["id"] == other["id"])["picture"]["status"] == "go"
    plain = house.episodes.choose(
        episode_id, by="you", change={"units": {other["id"]: {"level": "simple"}}}
    )
    assert next(u for u in plain["units"] if u["id"] == other["id"])["picture"]["status"] == "made"
    await settle(lambda: not house.episodes._busy(episode_id))
    rebuilt = next(u for u in house.episodes.view(episode_id)["units"] if u["id"] == unit["id"])
    assert rebuilt["picture"]["status"] == "go" and not rebuilt["picture"]["stale"]
    built = json.loads(
        (
            house.episodes.data_dir
            / "episodes"
            / episode_id
            / "pictures"
            / f"{picture.composition_id(unit['id'])}.brief.json"
        ).read_text()
    )
    assert built["canvas"] == {"width": 864, "height": 960}
    frame = next(
        f
        for ch in view["plan"]["chapters"]
        for b in ch["beats"]
        for f in b["frames"]
        if f["id"] == first
    )
    assert frame["override"]["layout"] == "split"
    undone = house.episodes.choose(episode_id, by="you", change={"clear": [first]})
    assert next(u for u in undone["units"] if u["id"] == unit["id"])["layout"] == "corner-window"


async def test_a_layout_is_used_for_the_film_and_a_picture_sits_beside_or_fills(
    house: AgentHost,
) -> None:
    episode_id = await planned(house)
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    before = house.episodes.view(episode_id)
    both = [u for u in before["units"] if u["layout"] == "corner-window"]
    assert len(both) > 2
    view = house.episodes.choose(
        episode_id, by="you", change={"all": {"layouts": {"both": "split"}}}
    )
    assert not house.episodes.planning(episode_id), "nobody's place changed: no turn for the writer"
    moved = [u for u in view["units"] if u["id"] in {b["id"] for b in both}]
    assert {u["layout"] for u in moved} == {"split"}
    assert {u["picture"]["status"] for u in moved} == {"queued"}, "each is drawn for its new box"
    lines = [f for ch in view["plan"]["chapters"] for b in ch["beats"] for f in b["frames"]]
    assert {
        f["override"]["scope"] for f in lines if f["layout"] == "split" and not f.get("hold")
    } == {"film"}
    await settle(lambda: not house.episodes._busy(episode_id))
    back = house.episodes.choose(episode_id, by="you", change={"all": {"layouts": {"both": None}}})
    assert {u["layout"] for u in back["units"]} == {u["layout"] for u in before["units"]}
    await settle(lambda: not house.episodes._busy(episode_id))
    # a whole picture goes full screen: every line of it, and the person leaves for those lines
    unit = next(u for u in back["units"] if len(u["frames"]) > 1)
    full_screen = house.episodes.choose(
        episode_id,
        by="you",
        change={"frames": {frame: {"presence": "content"} for frame in unit["frames"]}},
    )
    lines = {
        f["id"]: f
        for ch in full_screen["plan"]["chapters"]
        for b in ch["beats"]
        for f in b["frames"]
    }
    assert {lines[frame]["presence"] for frame in unit["frames"]} == {"content"}
    again = next(u for u in full_screen["units"] if u["id"] == unit["id"])
    assert again["layout"] == "graphic-on-ground" and again["canvas"] == [1920, 1080]
    with pytest.raises(ValueError, match="not a layout for both"):
        house.episodes.choose(
            episode_id, by="you", change={"all": {"layouts": {"both": "full-frame"}}}
        )


async def test_a_picture_type_redraws_one_picture_and_a_transition_only_the_film(
    house: AgentHost,
) -> None:
    episode_id = await planned(house)
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    before = house.episodes.view(episode_id)
    assert before["options"]["pictures"][0] == "diagram"
    assert before["options"]["transitions"] == ["cut", "push", "crossfade", "zoom-through"]
    unit = next(u for u in before["units"] if u["kind_of_picture"] == "diagram")
    view = house.episodes.choose(
        episode_id, by="you", change={"frames": {unit["id"]: {"picture": "list"}}}
    )
    statuses = {u["id"]: u["picture"]["status"] for u in view["units"]}
    assert statuses.pop(unit["id"]) == "queued" and set(statuses.values()) == {"made"}
    assert next(u for u in view["units"] if u["id"] == unit["id"])["kind_of_picture"] == "list"
    await settle(lambda: not house.episodes._busy(episode_id))
    brief = json.loads(
        (
            house.episodes.data_dir
            / "episodes"
            / episode_id
            / "pictures"
            / f"{picture.composition_id(unit['id'])}.brief.json"
        ).read_text()
    )
    assert brief["picture"]["kind"] == "list" and "kind_chosen_by" in brief["picture"]
    # how it comes in is the film's business: no picture is drawn again
    moved = house.episodes.choose(
        episode_id, by="you", change={"frames": {unit["id"]: {"transition": "zoom-through"}}}
    )
    assert {u["picture"]["status"] for u in moved["units"]} == {"made"}
    line = next(
        f
        for ch in moved["plan"]["chapters"]
        for b in ch["beats"]
        for f in b["frames"]
        if f["id"] == unit["id"]
    )
    assert line["picked"] == {"picture": "list", "transition": "zoom-through"}
    # one pick taken back leaves the other
    undone = house.episodes.choose(
        episode_id, by="you", change={"frames": {unit["id"]: {"picture": None}}}
    )
    line = next(
        f
        for ch in undone["plan"]["chapters"]
        for b in ch["beats"]
        for f in b["frames"]
        if f["id"] == unit["id"]
    )
    assert line["picked"] == {"transition": "zoom-through"}
    with pytest.raises(ValueError, match="no picture type"):
        house.episodes.choose(
            episode_id, by="you", change={"frames": {unit["id"]: {"picture": "terminal"}}}
        )


def lines_of(view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["id"]: f for ch in view["plan"]["chapters"] for b in ch["beats"] for f in b["frames"]}


async def test_a_persons_own_words_are_in_at_once_and_nothing_is_drawn_again(
    house: AgentHost,
) -> None:
    episode_id = await planned(house)
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    before = house.episodes.view(episode_id)
    unit = next(u for u in before["units"] if lines_of(before)[u["id"]].get("cues"))
    line = lines_of(before)[unit["id"]]
    landed = [c["at"] for c in line["cues"]]
    words = "Put plainly: " + " and then ".join(landed) + "."
    view = house.episodes.edit(episode_id, by="you", frame=line["id"], text=f"  {words}  ")
    assert not house.episodes._busy(episode_id), "no turn of the writer's, and no picture"
    now = lines_of(view)[line["id"]]
    assert now["vo"] == words and now["by_person"]["was"] == line["vo"]
    assert (now["presence"], now["layout"]) == (line["presence"], line["layout"])
    assert now["picture"] == line["picture"], "what the line does was not read again"
    assert {u["id"]: u["picture"]["status"] for u in view["units"]} == {
        u["id"]: "made" for u in before["units"]
    }
    assert view["last_change"]["lines"] == [line["id"]]
    assert view["clock"]["total"] != before["clock"]["total"], "code timed the new words"
    with pytest.raises(ValueError, match="needs words"):
        house.episodes.edit(episode_id, by="you", frame=line["id"], text="   ")
    with pytest.raises(ValueError, match="not in the plan"):
        house.episodes.edit(episode_id, by="you", frame="c9.b9.f9", text="Hello there.")
    # the same words again are not a change; the change is taken back whole
    same = house.episodes.edit(episode_id, by="you", frame=line["id"], text=words)
    assert same["last_change"]["lines"] == [line["id"]]
    back = house.episodes.undo(episode_id, by="you")
    assert lines_of(back)[line["id"]]["vo"] == line["vo"] and back["last_change"] is None
    assert "by_person" not in lines_of(back)[line["id"]]
    assert {u["picture"]["status"] for u in back["units"]} == {"made"}
    with pytest.raises(ValueError, match="nothing to take back"):
        house.episodes.undo(episode_id, by="you")


class Heard(DemoWorker):
    """The demo's writer, keeping every turn it was given."""

    turns: list[tuple[str, str]]

    async def turn(self, episode: Any, *, lane: str, prompt: str, heard: Any) -> Any:
        self.turns.append((lane, prompt))
        return await super().turn(episode, lane=lane, prompt=prompt, heard=heard)


def heard_by(house: AgentHost, tmp_path: Path) -> Heard:
    worker = Heard(data_dir=tmp_path, script=SCRIPT, pause=0)
    worker.turns = []
    house.episodes.workers[DEMO] = worker
    return worker


async def test_a_picture_made_before_words_stopped_counting_still_stands(
    house: AgentHost,
) -> None:
    episode_id = await planned(house)
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    episode = house.store.episode(episode_id)
    assert episode is not None
    full = house.episodes._full(episode)
    assert full is not None
    found = house.episodes._units(episode, full)
    # as a house that drew its pictures under the older signature left them
    for unit in found:
        house.store.set_picture(episode_id, unit["id"], sig=unit["sig_was"])
    house.episodes._queue_pictures(episode_id)
    view = house.episodes.view(episode_id)
    assert not house.episodes._busy(episode_id)
    assert {(u["picture"]["status"], u["picture"]["stale"]) for u in view["units"]} == {
        ("made", False)
    }


class Fitter(DemoWorker):
    """The demo's writer, able to fit a cue to a person's words when asked to fix a line."""

    fixed: list[str]

    async def turn(self, episode: Any, *, lane: str, prompt: str, heard: Any) -> Any:
        if lane == "plan" and "Stage: fix" in prompt:
            self.fixed.append(prompt)
            target = self.folder(episode) / "plan.json"
            plan = json.loads(target.read_text())
            for ch in plan["chapters"]:
                for b in ch["beats"]:
                    for f in b.get("frames") or []:
                        said = b["says"].lower()
                        for cue in f.get("cues", []):
                            if cue["at"].lower() not in said:
                                cue["at"] = b["says"].split()[0].strip(".,:;")
            target.write_text(json.dumps(plan))
            from design_agent.surfaces.web.episode_workers import Told

            return Told(answer="Fitted the cue to the new words.")
        return await super().turn(episode, lane=lane, prompt=prompt, heard=heard)


async def test_a_step_that_lost_its_word_is_fitted_by_the_writer_and_the_picture_stands(
    tmp_path: Path, house: AgentHost
) -> None:
    episode_id = await planned(house)
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    worker = Fitter(data_dir=tmp_path, script=SCRIPT, pause=0)
    worker.fixed = []
    house.episodes.workers[DEMO] = worker
    house.episodes.demo = False
    before = house.episodes.view(episode_id)
    unit = next(u for u in before["units"] if lines_of(before)[u["id"]].get("cues"))
    line = lines_of(before)[unit["id"]]
    view = house.episodes.edit(
        episode_id, by="you", frame=line["id"], text="Nothing here that a step landed on before."
    )
    assert house.episodes.planning(episode_id) and view["status"] == "studio"
    assert view["stage"]["name"] == "edit", "the studio stays open while the step is fitted"
    await settle(lambda: not house.episodes._busy(episode_id))
    assert len(worker.fixed) == 1 and line["id"] in worker.fixed[0]
    assert "stay exactly as they are" in worker.fixed[0]
    after = house.episodes.view(episode_id)
    now = lines_of(after)[line["id"]]
    assert now["vo"] == "Nothing here that a step landed on before."
    assert {c["at"] for c in now["cues"]} == {"Nothing"}
    assert not [r for r in after["checks"] if r["where"] == line["id"] and r["level"] == "must"]
    assert {u["picture"]["status"] for u in after["units"]} == {"made"}, "its picture stands"
    assert after["stage"]["state"] == "done" and after["last_change"]["lines"] == [line["id"]]


async def test_a_change_asked_in_words_is_made_by_the_writer_and_can_be_taken_back(
    tmp_path: Path, house: AgentHost
) -> None:
    episode_id = await planned(house)
    worker = heard_by(house, tmp_path)
    before = house.episodes.view(episode_id)
    # before the plan is approved: it is read, and shaped, first
    line = next(
        f for f in lines_of(before).values() if len(f["vo"].split()) > 12 and not f.get("cues")
    )
    with pytest.raises(ValueError, match="Say what should change"):
        house.episodes.ask(episode_id, by="you", scope="line", target=line["id"], text="  ")
    with pytest.raises(ValueError, match="not in the plan"):
        house.episodes.ask(episode_id, by="you", scope="line", target="c9.b9.f9", text="Shorter")
    view = house.episodes.ask(
        episode_id, by="you", scope="line", target=line["id"], text="Say it in fewer words."
    )
    assert view["status"] == "plan" and view["stage"]["name"] == "change"
    with pytest.raises(ValueError, match="still working"):
        house.episodes.ask(episode_id, by="you", scope="film", text="Shorter")
    with pytest.raises(ValueError, match="being written"):
        house.episodes.choose(episode_id, by="you", change={"settings": {"level": "rich"}})
    await settle(lambda: not house.episodes.planning(episode_id))
    after = house.episodes.view(episode_id)
    now = lines_of(after)[line["id"]]
    assert len(now["vo"].split()) < len(line["vo"].split())
    assert after["last_change"]["lines"] == [line["id"]]
    # what was asked is kept in the person's own words, and so is what the line said before
    assert after["last_change"]["why"] == "Say it in fewer words."
    assert after["last_change"]["was"] == {line["id"]: line["vo"]}
    assert after["last_change"]["earlier"] == 0 and after["undone"] is None
    assert after["stage"]["asked"] == {
        "scope": "line",
        "target": line["id"],
        "text": "Say it in fewer words.",
    }
    assert now["presence"] == line["presence"] and after["status"] == "plan"
    asked = next(p for lane, p in worker.turns if lane == "plan" and "Stage: change" in p)
    assert f"About line {line['id']}" in asked and "Never undo a pick" in asked
    # a pick made after the change stays when the change is taken back, and when it is put back
    other = next(
        f for f in lines_of(after).values() if f["id"] != line["id"] and f["presence"] == "both"
    )
    wide = "split" if other["layout"] != "split" else "corner-window"
    house.episodes.choose(episode_id, by="you", change={"frames": {other["id"]: {"layout": wide}}})
    back = house.episodes.undo(episode_id, by="you")
    assert lines_of(back)[line["id"]]["vo"] == line["vo"]
    assert lines_of(back)[other["id"]]["layout"] == wide, "the pick is not the change's"
    assert back["last_change"] is None and back["undone"]["why"] == "Say it in fewer words."
    again = house.episodes.redo(episode_id, by="you")
    assert lines_of(again)[line["id"]]["vo"] == now["vo"] and again["undone"] is None
    assert lines_of(again)[other["id"]]["layout"] == wide
    assert again["last_change"]["was"] == {line["id"]: line["vo"]}
    with pytest.raises(ValueError, match="nothing to put back"):
        house.episodes.redo(episode_id, by="you")
    # changes go back one at a time, newest first, and come back oldest first
    mine = house.episodes.edit(episode_id, by="you", frame=other["id"], text="My own words.")
    assert mine["last_change"]["earlier"] == 1 and mine["last_change"]["was"] == {
        other["id"]: other["vo"]
    }
    one = house.episodes.undo(episode_id, by="you")
    assert lines_of(one)[other["id"]]["vo"] == other["vo"]
    assert one["last_change"]["why"] == "Say it in fewer words."
    assert one["undone"]["why"] == "You changed a line"
    two = house.episodes.undo(episode_id, by="you")
    assert lines_of(two)[line["id"]]["vo"] == line["vo"] and two["last_change"] is None
    assert two["undone"]["why"] == "Say it in fewer words."
    with pytest.raises(ValueError, match="nothing to take back"):
        house.episodes.undo(episode_id, by="you")
    house.episodes.redo(episode_id, by="you")
    both = house.episodes.redo(episode_id, by="you")
    assert lines_of(both)[other["id"]]["vo"] == "My own words." and both["undone"] is None
    assert lines_of(both)[line["id"]]["vo"] == now["vo"]
    # a new change is the end of what could be put back
    house.episodes.undo(episode_id, by="you")
    fresh = house.episodes.edit(episode_id, by="you", frame=other["id"], text="Other words.")
    assert fresh["undone"] is None and fresh["last_change"]["earlier"] == 1
    house.episodes.undo(episode_id, by="you")
    back = house.episodes.undo(episode_id, by="you")
    assert lines_of(back)[line["id"]]["vo"] == line["vo"]
    # a turn that leaves the plan as it was is no change: it says so, and nothing is kept for it
    drawn = next(f for f in lines_of(back).values() if f.get("cues"))
    house.episodes.ask(episode_id, by="you", scope="line", target=drawn["id"], text="Shorter")
    await settle(lambda: not house.episodes.planning(episode_id))
    nothing = house.episodes.view(episode_id)
    assert nothing["stage"]["state"] == "done"
    assert nothing["stage"]["said"] == "The writer changed nothing."
    assert nothing["last_change"] is None and nothing["stage"]["asked"]["text"] == "Shorter"
    # a line that is cut is named with its words and the line it followed, and comes back whole
    ids = list(lines_of(nothing))
    gone = next(
        f
        for f in lines_of(nothing).values()
        if not f.get("cues") and not f.get("shows") and ids.index(f["id"]) > 0
    )
    house.episodes.ask(episode_id, by="you", scope="line", target=gone["id"], text="Cut this line")
    await settle(lambda: not house.episodes.planning(episode_id))
    cut = house.episodes.view(episode_id)
    assert gone["id"] not in lines_of(cut) and cut["last_change"]["removed"] == 1
    said = cut["last_change"]["cut"][0]
    assert said["says"] == gone["vo"] and said["chapter"] == gone["id"].split(".")[0]
    assert said["after"] in lines_of(cut) or said["after"] == ""
    assert lines_of(house.episodes.undo(episode_id, by="you"))[gone["id"]]["vo"] == gone["vo"]
    # a chapter, and the film, are asked the same way
    chapter = before["plan"]["chapters"][2]
    house.episodes.ask(episode_id, by="you", scope="chapter", target=chapter["id"], text="Shorter")
    await settle(lambda: not house.episodes.planning(episode_id))
    assert any(f"About chapter {chapter['id']}" in p for _, p in worker.turns)
    house.episodes.ask(episode_id, by="you", scope="film", text="Open faster.")
    await settle(lambda: not house.episodes.planning(episode_id))
    assert any("About the whole film" in p for _, p in worker.turns)


def test_what_a_change_did_names_the_old_words_and_the_lines_it_cut() -> None:
    before = SCRIPT["plan"]
    after = json.loads(json.dumps(before))
    chapter = after["chapters"][1]
    first, second, third = chapter["beats"][:3]
    said = {b["id"]: " ".join(b["says"].split()) for b in (first, second, third)}
    # the writer cuts the chapter's first line and its third, and says the second another way
    chapter["beats"] = [b for b in chapter["beats"] if b["id"] not in (first["id"], third["id"])]
    second["says"] = "Said another way."
    for f in second.get("frames") or []:
        f.pop("vo", None)
    did = _changed(before, after)
    line = f"{second['id']}.f1"
    assert did["lines"] == [line] and did["was"] == {line: said[second["id"]]}
    assert did["added"] == [] and did["removed"] == 2
    assert did["cut"] == [
        # the chapter's first line has no line before it there
        {"says": said[first["id"]], "chapter": chapter["id"], "after": ""},
        {"says": said[third["id"]], "chapter": chapter["id"], "after": line},
    ]
    assert _changed(before, before) == {
        "lines": [],
        "was": {},
        "added": [],
        "removed": 0,
        "cut": [],
        "pictures": [],
    }


class Silent(DemoWorker):
    async def turn(self, episode: Any, *, lane: str, prompt: str, heard: Any) -> Any:
        from design_agent.surfaces.web.episode_workers import Told

        if lane == "plan" and "Stage: change" in prompt:
            (self.folder(episode) / "plan.json").write_text("{}")  # half a change, left behind
            return Told(failure="the agent ran out of turns")
        return await super().turn(episode, lane=lane, prompt=prompt, heard=heard)


async def test_a_change_that_stops_leaves_the_plan_as_it_was_and_the_studio_open(
    tmp_path: Path, house: AgentHost
) -> None:
    episode_id = await planned(house)
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    first = next(iter(lines_of(house.episodes.view(episode_id)).values()))
    before = house.episodes.edit(episode_id, by="you", frame=first["id"], text="In my words.")
    house.episodes.workers[DEMO] = Silent(data_dir=tmp_path, script=SCRIPT, pause=0)
    house.episodes.ask(episode_id, by="you", scope="film", text="Make it funnier.")
    await settle(lambda: not house.episodes.planning(episode_id))
    after = house.episodes.view(episode_id)
    assert after["status"] == "studio", "a change that stops never fails the episode"
    assert after["stage"]["state"] == "stopped" and "as it was" in after["stage"]["said"]
    # what was asked is still known, to be sent again
    assert after["stage"]["asked"] == {"scope": "film", "target": "", "text": "Make it funnier."}
    assert lines_of(after).keys() == lines_of(before).keys()
    assert {k: v["vo"] for k, v in lines_of(after).items()} == {
        k: v["vo"] for k, v in lines_of(before).items()
    }
    # the change before it still stands, and is still the one to take back
    assert after["last_change"]["why"] == "You changed a line"
    assert after["last_change"]["earlier"] == 0
    assert {u["picture"]["status"] for u in after["units"]} == {"made"}
    # the next turn starts from the plan the house holds, not from what was left in the folder
    house.episodes.workers[DEMO] = DemoWorker(data_dir=tmp_path, script=SCRIPT, pause=0)
    house.episodes.ask(episode_id, by="you", scope="film", text="Open faster.")
    await settle(lambda: not house.episodes.planning(episode_id))
    assert house.episodes.view(episode_id)["stage"]["state"] == "done"


async def test_a_note_on_a_picture_goes_to_its_builder_or_to_the_writer_by_what_it_asks(
    tmp_path: Path, house: AgentHost
) -> None:
    episode_id = await planned(house)
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    worker = heard_by(house, tmp_path)
    view = house.episodes.view(episode_id)
    unit = next(u for u in view["units"] if len(u["frames"]) > 1)
    asked: list[Any] = []

    def reader(kind: str) -> Any:
        def ask(state: Any, questions: Any) -> Any:
            if "note" in questions:
                asked.append(state)
                return {"note": {"choice": kind, "confidence": 0.9}}
            return {
                k: {"choice": next(iter(q["criteria"])), "confidence": 1.0}
                for k, q in questions.items()
            }

        return ask

    # how it is drawn: its builder gets the note, the plan is not touched
    house.episodes.reader = reader("drawn")
    house.episodes.ask(
        episode_id,
        by="you",
        scope="picture",
        target=unit["frames"][1],
        text="The title is cut off.",
    )
    await settle(lambda: not house.episodes._busy(episode_id))
    assert asked[-1]["NOTE"] == "The title is cut off." and asked[-1]["picture_shows"]
    brief = json.loads(
        (
            house.episodes.data_dir
            / "episodes"
            / episode_id
            / "pictures"
            / f"{picture.composition_id(unit['id'])}.brief.json"
        ).read_text()
    )
    assert brief["note_from_the_person"] == "The title is cut off."
    assert not [p for lane, p in worker.turns if lane == "plan"], "the writer was not asked"
    # what it shows: the writer's, because the plan says what a picture shows
    house.episodes.reader = reader("shows")
    house.episodes.ask(
        episode_id, by="you", scope="picture", target=unit["id"], text="Show a table instead."
    )
    await settle(lambda: not house.episodes._busy(episode_id))
    turns = [p for lane, p in worker.turns if lane == "plan" and "Stage: change" in p]
    assert len(turns) == 1
    assert f"About the picture line {unit['id']} brings in" in turns[0]
    assert "“Show a table instead.”" in turns[0]
    with pytest.raises(ValueError, match="no picture yet"):
        to_camera = next(f for f in lines_of(view).values() if f["presence"] == "person")
        house.episodes.ask(episode_id, by="you", scope="picture", target=to_camera["id"], text="x")


async def test_the_film_has_one_look_voice_and_level_chosen_once(house: AgentHost) -> None:
    episode_id = await planned(house)
    view = house.episodes.choose(
        episode_id, by="you", change={"settings": {"theme": "framed-stage", "level": "rich"}}
    )
    assert view["settings"]["theme"] == "framed-stage"
    assert view["plan"]["brief"]["theme"] == "framed-stage" and {
        u["level"] for u in view["units"]
    } == {"rich"}
    off = house.episodes.choose(episode_id, by="you", change={"settings": {"presenter": "off"}})
    presences = {
        f["presence"] for ch in off["plan"]["chapters"] for b in ch["beats"] for f in b["frames"]
    }
    assert off["settings"]["theme"] == "voice-only" and presences == {"content"}


# -- takes and the film ---------------------------------------------------------------------------


async def test_a_take_sets_the_films_clock_for_its_chapter(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode_id = await planned(house)
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    monkeypatch.setattr(
        house.episodes,
        "_cut",
        lambda episode, name, content: {"video": "", "audio": "", "seconds": 30.0},
    )
    view = house.episodes.view(episode_id)
    chapter = view["plan"]["chapters"][0]
    lines = [f["id"] for b in chapter["beats"] for f in b["frames"]]
    marks = [{"frame": frame, "t": 3.0 * i} for i, frame in enumerate(lines)]
    view = await house.episodes.add_take(
        episode_id, by="you", chapter=chapter["id"], marks=marks, name="take.webm", content=b"webm"
    )
    take = view["takes"][0]
    assert take["kept"] and take["n"] == 1 and take["seconds"] == 30.0 and view["recorded"] == 1
    first = next(line for line in view["clock"]["lines"] if line["frame"] == lines[0])
    assert (
        first["source"] == {"kind": "take", "take": take["id"], "offset": 0.0}
        and first["seconds"] == 3.0
    )
    # a recording brought as a file has no marks: its lines are spread at the plan's pace
    view = await house.episodes.add_take(
        episode_id, by="you", chapter=chapter["id"], marks=[], name="take.mp4", content=b"mp4"
    )
    kept = [t for t in view["takes"] if t["kept"]]
    assert len(view["takes"]) == 2 and len(kept) == 1 and kept[0]["n"] == 2
    assert [m["frame"] for m in kept[0]["marks"]] == lines and kept[0]["marks"][-1]["t"] < 30.0
    view = house.episodes.keep_take(episode_id, view["takes"][0]["id"], keep=True)
    assert [t["kept"] for t in view["takes"]] == [True, False]
    view = house.episodes.keep_take(episode_id, view["takes"][1]["id"], keep=False)
    assert len(view["takes"]) == 1
    with pytest.raises(KeyError):
        await house.episodes.add_take(
            episode_id, by="you", chapter="c99", marks=[], name="take.webm", content=b"x"
        )


async def test_the_film_is_rendered_from_the_plan_the_pictures_and_the_takes(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode_id = await planned(house)
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    projects: list[dict[str, bytes]] = []

    class Computer:
        def put(self, files: list[tuple[str, bytes]]) -> None:
            projects.append(dict(files))

        def run(self, command: str, *, timeout: int = 600) -> Any:
            from design_agent.surfaces.web.computer import Ran

            if "render.exit" in command and "cat" in command:
                return Ran('0\n@hf-progress {"code":"encode","done":9,"total":10,"pct":90}', 0)
            return Ran("0 errors, 0 warnings", 0)

        def get(self, path: str) -> bytes | None:
            return b"mp4" if path.endswith("episode.mp4") else None

    monkeypatch.setattr(house.episodes, "_computer", lambda episode: Computer())
    monkeypatch.setattr("design_agent.surfaces.web.episode_desk.time.sleep", lambda _s: None)
    house.episodes.render(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    view = house.episodes.view(episode_id)
    film = view["film_state"]
    assert film["status"] == "done" and not film["stale"] and film["file"]["name"] == "one-idea.mp4"
    page = next(v for k, v in projects[0].items() if k.endswith("/film/index.html")).decode()
    assert f'data-duration="{view["clock"]["total"]:.3f}"' in page
    assert sum(1 for k in projects[0] if "/film/compositions/" in k) == len(view["units"])
    asset = house.asset_view(house.store.asset(view["asset_id"]))  # type: ignore[arg-type]
    assert asset["status"] == "done" and asset["files"][0]["name"] == "one-idea.mp4"
    # anything that changes the film afterwards asks for a new render
    unit = next(u for u in view["units"] if u["layout"] == "corner-window")
    changed = house.episodes.choose(
        episode_id, by="you", change={"frames": {unit["frames"][0]: {"presence": "content"}}}
    )
    assert changed["film_state"]["stale"]


# -- the house's record of every run --------------------------------------------------------------


class Runner:
    """A local agent's CLI, scripted: what each call was given, and what it says."""

    def __init__(self, replies: list[list[Event]]) -> None:
        self.replies = replies
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, harness: str, **given: Any) -> AsyncGenerator[Event, None]:
        self.calls.append({"harness": harness, **given})
        for event in self.replies[min(len(self.calls), len(self.replies)) - 1]:
            yield event


def local(
    tmp_path: Path, runner: Runner, harness: str = "claude"
) -> tuple[LocalWorker, Store, dict[str, Any]]:
    store = Store(tmp_path / "house.sqlite")
    worker = LocalWorker(harness, store=store, data_dir=tmp_path, project_root=ROOT, runner=runner)
    return worker, store, {"id": "ep_1", "thread_id": "th_1"}


async def test_a_local_writer_works_in_the_episodes_own_folder_with_the_skill(
    tmp_path: Path,
) -> None:
    runner = Runner(
        [[Event("session", "s-1"), Event("step", "Writing plan.json"), Event("answer", "Done.")]]
    )
    worker, store, episode = local(tmp_path, runner)
    await worker.prepare(episode, {"material/notes.md": NOTES})
    folder = tmp_path / "episodes" / "ep_1"
    assert (folder / "skill" / "SKILL.md").is_file() and (
        folder / "material/notes.md"
    ).read_text() == NOTES
    heard: list[str] = []
    told = await worker.turn(
        episode, lane="plan", prompt="Stage: brief.", heard=lambda k, t: heard.append(t)
    )
    assert told == Told(answer="Done.") and heard == ["Writing plan.json"]
    call = runner.calls[0]
    assert call["repo"] == folder and call["writes"] is True and call["session"] == ""
    run = store.runs("th_1", "plan")[0]
    assert (run["harness"], run["session"], run["state"]) == ("claude", "s-1", "done")
    assert run["prompt"] == "Stage: brief." and run["answer"] == "Done."
    assert [s["text"] for s in run["steps"]] == ["Writing plan.json"]
    assert await worker.read(episode, "material/notes.md") == NOTES
    assert await worker.read(episode, "nothing.json") is None


async def test_its_own_session_is_a_shortcut_the_record_is_what_carries_on(tmp_path: Path) -> None:
    runner = Runner(
        [
            [Event("session", "s-1"), Event("answer", "The brief is written.")],
            [Event("error", "No conversation found with session ID s-1")],
            [Event("session", "s-2"), Event("answer", "The script is written.")],
        ]
    )
    worker, store, episode = local(tmp_path, runner)
    await worker.turn(episode, lane="plan", prompt="Stage: brief.", heard=lambda k, t: None)
    told = await worker.turn(episode, lane="plan", prompt="Stage: script.", heard=lambda k, t: None)
    assert told.answer == "The script is written."
    resumed, again = runner.calls[1], runner.calls[2]
    assert resumed["session"] == "s-1" and resumed["prompt"] == "Stage: script."
    assert again["session"] == "" and "The brief is written." in again["prompt"]
    assert again["prompt"].endswith("Stage: script.")
    assert [r["state"] for r in store.runs("th_1", "plan")] == ["done", "failed", "done"]
    # another lane has its own history, and another agent is told this one's
    await worker.turn(episode, lane="picture:c1", prompt="Stage: picture.", heard=lambda k, t: None)
    assert runner.calls[3]["session"] == "" and runner.calls[3]["prompt"] == "Stage: picture."
    other = LocalWorker("kimi", store=store, data_dir=tmp_path, project_root=ROOT, runner=runner)
    await other.turn(episode, lane="plan", prompt="Stage: frames.", heard=lambda k, t: None)
    assert (
        runner.calls[4]["harness"] == "kimi"
        and "The script is written." in runner.calls[4]["prompt"]
    )


def test_what_is_retold_is_the_newest_turns_that_fit() -> None:
    runs = [{"prompt": f"ask {i}", "answer": "word " * 600} for i in range(6)]
    told = retold(runs, "Now this.")  # type: ignore[arg-type]
    assert told.endswith("Now this.") and "ask 5" in told and "ask 0" not in told
    assert retold([], "Only this.") == "Only this."
    assert retold([{"prompt": "x", "answer": ""}], "Only this.") == "Only this."  # type: ignore[list-item]


def test_a_run_that_writes_may_change_its_folder_and_nothing_else(tmp_path: Path) -> None:
    given: Mapping[str, Any] = {
        "repo": tmp_path,
        "prompt": "Write.",
        "session": "",
        "profile": tmp_path / "p.md",
    }
    argv, stdin = command(HARNESSES["claude"], "claude", **given, guide="Be a writer.", writes=True)
    assert stdin == "Write." and "plan" not in argv
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert (
        argv[argv.index("--tools") + 1] == CLAUDE_WRITER_TOOLS and "Bash" not in CLAUDE_WRITER_TOOLS
    )
    assert argv[argv.index("--append-system-prompt") + 1] == "Be a writer."
    argv, stdin = command(HARNESSES["codex"], "codex", **given, guide="Be a writer.", writes=True)
    assert (
        argv[argv.index("--sandbox") + 1] == "workspace-write" and stdin == "Be a writer.\n\nWrite."
    )
    resumed = {**given, "session": "s-1"}
    argv, _ = command(HARNESSES["codex"], "codex", **resumed, writes=True)
    assert 'sandbox_mode="workspace-write"' in argv
    argv, _ = command(HARNESSES["claude"], "claude", **given)
    assert argv[argv.index("--permission-mode") + 1] == "plan", (
        "research still reads and never writes"
    )


async def test_research_keeps_every_run_and_is_retold_when_a_session_is_gone(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "code" / "shop"
    (repo / ".git").mkdir(parents=True)
    runner = Runner(
        [
            [
                Event("session", "s-1"),
                Event("step", "Reading README.md"),
                Event("answer", "It caches."),
            ],
            [Event("error", "No conversation found with session ID s-1")],
            [Event("session", "s-9"), Event("answer", "For a year.")],
        ]
    )

    async def run(harness: str, **given: Any) -> AsyncGenerator[Event, None]:
        async for event in runner(harness, **given):
            yield event

    store = Store(tmp_path / "house.sqlite")
    desk = ResearchDesk(
        store=store,
        hub=Hub(),
        data_dir=tmp_path,
        roots=[tmp_path / "code"],
        runner=run,
        ready=lambda h: True,
    )
    channel = store.channels()[0]["id"]
    _, conversation = desk.open(
        channel, by="you", repo=str(repo), harness="claude", question="How does it cache?"
    )
    await settle(lambda: not desk.running(conversation["id"]))
    first = store.runs(conversation["id"])[0]
    assert (
        first["answer"] == "It caches." and first["session"] == "s-1" and first["state"] == "done"
    )
    assert [s["text"] for s in first["steps"]] == ["Reading README.md"]
    desk.follow_up(conversation["id"], by="you", text="For how long?")
    await settle(lambda: not desk.running(conversation["id"]))
    runs = store.runs(conversation["id"])
    assert [r["state"] for r in runs] == ["done", "failed", "done"]
    assert runner.calls[1]["session"] == "s-1" and runner.calls[2]["session"] == ""
    assert (
        "It caches." in runner.calls[2]["prompt"] and "For how long?" in runner.calls[2]["prompt"]
    )
    said = [m["text"] for m in store.messages(conversation["id"]) if m["kind"] == "agent"]
    assert said == ["It caches.", "For a year."]
    assert store.conversation(conversation["id"])["session"] == "s-9"  # type: ignore[index]
    assert not [m for m in store.messages(conversation["id"]) if m["kind"] == "notice"]


# -- the catalog and the app ----------------------------------------------------------------------


def test_an_episode_is_made_in_its_studio_never_asked_of_the_agent(house: AgentHost) -> None:
    made = catalog.capability(EPISODE)
    assert made is not None and made.studio and made.makes == "video"
    channel = house.store.channels()[0]["id"]
    message = house.post(
        channel_id=channel, author_id="maya", text="An episode", to_agent=False, kind=EPISODE
    )
    assert house.store.assets(message["thread_id"]) == []
    task = house.post(channel_id=channel, author_id="you", text="Notes", to_agent=False)
    house.store.update_thread(task["thread_id"])
    with pytest.raises((ValueError, KeyError)):
        house.request_asset(task["thread_id"], kind=EPISODE, by="you")


def test_the_built_in_writer_is_offered_beside_the_local_ones(tmp_path: Path) -> None:
    host = AgentHost(
        settings=Settings(_env_file=None),
        store=Store(tmp_path / "h.sqlite"),
        hub=Hub(),
        data_dir=tmp_path,
    )
    writers = {w["id"]: w for w in host.episodes.options()["writers"]}
    assert set(writers) == {"claude", "codex", "kimi", BUILTIN}
    assert not writers[BUILTIN]["ready"] and not writers[BUILTIN]["local"], "no runtime yet"
    assert all(writers[w]["local"] for w in ("claude", "codex", "kimi"))
    assert isinstance(host.episodes, EpisodeDesk)


def test_the_app_serves_an_episode_at_every_address(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, workspace_root=tmp_path / "workspace", sandbox="host")
    with TestClient(create_app(ROOT, settings, demo=True)) as client:
        options = client.get("/api/episodes/options").json()
        assert [w["id"] for w in options["writers"]] == [DEMO] and options["reader"] == "demo"
        assert set(options["geometry"]["layouts"]) >= {"corner-window", "full-frame"}
        channel = client.get("/api/channels").json()[0]["id"]
        assert (
            client.post(f"/api/channels/{channel}/episodes", json={"text": ""}).status_code == 422
        )
        # a length is a least and a most, or "auto": one number is neither
        for seconds in (300, [300], "long"):
            body = {"text": NOTES, "settings": {"seconds": seconds}}
            assert client.post(f"/api/channels/{channel}/episodes", json=body).status_code == 422
        made = client.post(
            f"/api/channels/{channel}/episodes",
            json={
                "title": "One idea",
                "text": NOTES,
                "settings": {"seconds": [300, 360], "writer": DEMO},
            },
        )
        assert made.status_code == 200, made.text
        episode_id = made.json()["id"]
        until = time.time() + 30
        while time.time() < until:
            view = client.get(f"/api/episodes/{episode_id}").json()
            if view["status"] != "planning":
                break
            time.sleep(0.05)
        assert view["status"] == "plan" and view["settings"]["seconds"] == [300, 360]
        line_id = next(
            f["id"] for ch in view["plan"]["chapters"] for b in ch["beats"] for f in b["frames"]
        )
        assert client.get("/api/episodes/ep_missing").status_code == 404
        assert client.post("/api/episodes/ep_missing/approve").status_code == 404
        assert client.post(f"/api/episodes/{episode_id}/film").status_code == 422
        # nothing stopped, so there is nothing to make again
        assert client.post(f"/api/episodes/{episode_id}/pictures").status_code == 422
        assert client.post("/api/episodes/ep_missing/pictures").status_code == 404
        assert client.post(f"/api/episodes/{episode_id}/stop").json() == {"ok": True}
        chosen = client.post(
            f"/api/episodes/{episode_id}/choices", json={"settings": {"level": "rich"}}
        )
        assert chosen.status_code == 200 and chosen.json()["settings"]["level"] == "rich"
        bad = client.post(
            f"/api/episodes/{episode_id}/choices", json={"settings": {"level": "ornate"}}
        )
        assert bad.status_code == 422
        # a change in words, a person's own words, and the way back
        said = client.post(
            f"/api/episodes/{episode_id}/lines/{line_id}", json={"text": "A line said my way."}
        )
        assert said.status_code == 200 and said.json()["last_change"]["lines"] == [line_id]
        assert client.post(f"/api/episodes/{episode_id}/undo").status_code == 200
        assert client.post(f"/api/episodes/{episode_id}/undo").status_code == 422
        put_back = client.post(f"/api/episodes/{episode_id}/redo")
        assert put_back.status_code == 200 and put_back.json()["undone"] is None
        assert client.post(f"/api/episodes/{episode_id}/redo").status_code == 422
        assert (
            client.post(
                f"/api/episodes/{episode_id}/ask", json={"scope": "scene", "text": "Shorter"}
            ).status_code
            == 422
        )
        asked = client.post(
            f"/api/episodes/{episode_id}/ask", json={"scope": "film", "text": "Open faster."}
        )
        assert asked.status_code == 200 and asked.json()["stage"]["name"] == "change"
        until = time.time() + 30
        while time.time() < until and client.get(f"/api/episodes/{episode_id}").json()["stage"][
            "state"
        ] in ("working", "reading"):
            time.sleep(0.05)
        kit = client.get("/api/episodes/options").json()["themes"][0]["kit"]
        assert {"layout": "corner-window", "presence": "both"} in kit
        # a null is a pick taken back: it reaches the desk as it was sent
        line = line_id
        for change in ({"transition": "push"}, {"transition": None}):
            sent = client.post(
                f"/api/episodes/{episode_id}/choices", json={"frames": {line: change}}
            )
            assert sent.status_code == 200, sent.text
        assert (
            client.post(
                f"/api/episodes/{episode_id}/choices",
                json={"frames": {line: {"transition": "wipe"}}},
            ).status_code
            == 422
        )
        canvas = client.get(f"/api/channels/{channel}/canvas").json()
        assert canvas[0]["episodes"][0]["id"] == episode_id
        kinds = {c["id"]: c for c in client.get("/api/catalog").json()["capabilities"]}
        assert kinds[EPISODE]["studio"] is True


def test_the_desks_computer_is_a_folder_and_this_machine_without_a_runner(tmp_path: Path) -> None:
    from design_agent.surfaces.web.computer import Computer

    class Binding:
        runner = None

    computer = Computer(Binding(), "th_1", tmp_path)  # type: ignore[arg-type]
    assert not computer.renders
    computer.put([("/workspace/projects/ep_1/film/index.html", b"<html>")])
    assert computer.get("/workspace/projects/ep_1/film/index.html") == b"<html>"
    assert computer.get("/workspace/projects/ep_1/missing") is None
    ran = computer.run("cat /workspace/projects/ep_1/film/index.html && exit 3")
    assert ran.output == "<html>" and ran.code == 3 and not ran.ok


def test_what_the_renderers_check_finds_is_sorted_into_what_breaks_and_what_it_flags() -> None:
    from design_agent.surfaces.web.episode_desk import _findings

    report = """◆  Checking pic
Lint
  ✗ [/x/compositions/pic.html:25:11] gsap_non_transform_motion: GSAP tween uses left.
    Fix: replace left with x.
Runtime
  ◇ 0 errors, 0 warnings
Layout
  ◇ 0 issues across 9 sample(s)
Contrast
  ✗ div > div:nth-of-type(2) 1.49:1 (need 3:1, t=5.272s)
    Try rgb(152,148,138); source compositions/pic.html
◇  Check failed
"""
    broken, flagged = _findings(report)
    assert broken == [
        "lint: gsap_non_transform_motion: GSAP tween uses left. (Fix: replace left with x.)"
    ]
    assert (
        len(flagged) == 1
        and flagged[0].startswith("contrast: div > div")
        and "Try rgb" in flagged[0]
    )
    assert _findings("Lint\n  ◇ 0 errors, 0 warnings\n◇  Check passed") == ([], [])


async def test_an_episode_wears_its_channels_brand(house: AgentHost) -> None:
    episode_id = await planned(house)
    look = house.episodes._look(house.store.episode(episode_id))  # type: ignore[arg-type]
    # the demo's house wears the sample brand: paper, ink and its signal colour, set in Geist
    assert look.palette["ground"] == "#f6f1e7" and look.palette["accent"] == "#ff5a36"
    assert (look.display, look.mono) == ("Geist", "Fragment Mono")
    house.episodes.brand_for = lambda thread_id: ROOT / "nowhere"
    house.settings = house.settings.model_copy(update={"brand_path": ROOT / "nowhere"})
    plain = house.episodes._look(house.store.episode(episode_id))  # type: ignore[arg-type]
    assert plain == picture.Look()
