"""An episode in the web app: started from material, planned in turns by a writer the person
picks, its pictures built and posed, its takes kept, its film rendered; and every agent run kept
in the house's own record, a local agent's session being only a shortcut to it."""

from __future__ import annotations

import asyncio
import io
import json
import re
import shlex
import sqlite3
import time
from collections.abc import AsyncGenerator, Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from design_agent.config import Settings
from design_agent.episode import picture
from design_agent.episode import plan as plans
from design_agent.surfaces.web import catalog, episode_desk, episode_models
from design_agent.surfaces.web.agent import AgentHost
from design_agent.surfaces.web.app import create_app
from design_agent.surfaces.web.episode_desk import (
    EPISODE,
    EpisodeDesk,
    _changed,
    _craft_notes,
    _guides,
    _plan_stages,
    _shape,
    _stages,
)
from design_agent.surfaces.web.episode_workers import (
    BUILTIN,
    DEMO,
    HYPERFRAMES_GUIDES,
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


@pytest.fixture(autouse=True)
def codex_catalog(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(episode_models, "CODEX_HOME", tmp_path)
    monkeypatch.setattr(
        episode_models,
        "codex_model_list",
        lambda: tuple(
            {
                "model": model,
                "supportedReasoningEfforts": [
                    {"reasoningEffort": effort}
                    for effort in ("low", "medium", "high", "xhigh", "max")
                ],
            }
            for model in ("gpt-6.1-sol", "gpt-6-sol", "gpt-5.6-sol", "account-model")
        ),
        raising=False,
    )


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
    monkeypatch.setattr(desk, "_motion_frames", lambda episode, unit, full, html: {})
    yield host
    await desk.close()


async def planned(host: AgentHost, **settings: Any) -> str:
    channel = host.store.channels()[0]["id"]
    view = host.episodes.create(
        channel, by="you", title="One idea", text=NOTES, settings={"writer": DEMO, **settings}
    )
    await settle(lambda: not host.episodes.planning(view["id"]))
    return str(view["id"])


async def test_stopped_plan_retries_the_same_stage_with_a_different_supported_model(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    eid = await planned(house)
    desk = house.episodes
    desk._worker_called("codex")
    episode = desk._episode(eid)
    house.store.update_episode(
        eid,
        status="failed",
        stage={"name": "script", "state": "failed"},
        settings={**episode["settings"], "writer": "codex", "writer_model": "gpt-6.1-terra"},
    )
    started = []
    monkeypatch.setattr(desk, "_start_plan", lambda eid, *, stage: started.append((eid, stage)))
    with pytest.raises(ValueError, match="supported model"):
        desk.again(eid, model="gpt-6.1-terra")
    assert not started
    retried = desk.again(eid, model="gpt-5.6-sol", effort="low")
    assert started == [(eid, "script")]
    assert retried["settings"]["writer_model"] == "gpt-5.6-sol"
    assert retried["settings"]["writer_effort"] == "low"
    assert desk._episode(eid)["material"] == episode["material"]
    reset = desk.again(eid, model="", effort="")
    assert not {"writer_model", "writer_effort"} & reset["settings"].keys()
    assert started == [(eid, "script"), (eid, "script")]


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


async def test_the_plans_page_times_each_stage_from_when_the_house_moved_to_it(
    house: AgentHost,
) -> None:
    episode_id = await planned(house)
    stages = house.episodes.view(episode_id)["plan_stages"]
    assert [(s["id"], s["state"]) for s in stages] == [
        ("brief", "done"),
        ("script", "done"),
        ("frames", "done"),
        ("check", "done"),
    ]
    # one after another, each ending where the next begins
    times = [t for s in stages for t in (s["started_at"], s["ended_at"])]
    assert all(t is not None for t in times) and times == sorted(times)
    assert all(a["ended_at"] == b["started_at"] for a, b in zip(stages, stages[1:], strict=False))


def test_a_plans_stages_run_and_stop_where_the_house_is() -> None:
    log = [{"name": "brief", "at": 10.0}, {"name": "script", "at": 20.0}]
    running = _plan_stages({"name": "script", "state": "working", "log": log}, [])
    assert [(s["id"], s["state"]) for s in running] == [
        ("brief", "done"),
        ("script", "running"),
        ("frames", "pending"),
        ("check", "pending"),
    ]
    assert running[0]["ended_at"] == 20.0 == running[1]["started_at"]
    stopped = _plan_stages({"name": "script", "state": "stopped", "log": log}, [])
    assert stopped[1]["state"] == "failed" and stopped[1]["ended_at"] is None
    # the checks after the writer's last framing turn are the house's own stage
    done = [*log, {"name": "frames", "at": 30.0}, {"name": "done", "at": 50.0}]
    turns = [{"started_at": 31.0, "ended_at": 44.0}]
    framed, checked = _plan_stages({"name": "done", "state": "done", "log": done}, turns)[2:]
    assert (framed["ended_at"], checked["started_at"], checked["ended_at"]) == (44.0, 44.0, 50.0)
    # a plan written before the house logged its stages has none to time
    assert _plan_stages({"name": "done", "state": "done"}, []) == []


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


def test_demo_house_offers_source_writers_and_requires_a_writer_for_custom_notes(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    desk = house.episodes
    monkeypatch.setattr(house.research, "ready", lambda name: name == "codex")
    choices = {w["id"]: w for w in desk.options()["writers"]}
    assert choices["codex"]["ready"] and not choices["claude"]["ready"]
    assert desk._settings({"writer": "codex"})["writer"] == "codex"
    house.settings = house.settings.model_copy(update={"episode_codex_model": "account-model"})
    worker = desk._worker_called("codex")
    assert isinstance(worker, LocalWorker) and worker.model == "account-model"
    with pytest.raises(ValueError, match="Choose a writer"):
        desk.create(house.store.channels()[0]["id"], by="you", text="Index useful memories.")


async def test_frame_review_refreshes_a_chapter_label_after_its_question_changes(
    house: AgentHost,
) -> None:
    eid = await planned(house)
    desk = house.episodes
    episode = desk._episode(eid)
    chapter = episode["plan"]["chapters"][0]
    chapter["question"] = "How do you decide which events are worth indexing?"
    house.store.update_episode(eid, plan=episode["plan"])
    assert not desk._merged(desk._episode(eid))["chapters"][0].get("type")
    await desk._read(eid, desk._worker(episode), ["frames", "design"], checks="all")
    assert desk._merged(desk._episode(eid))["chapters"][0].get("type")


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


@pytest.mark.parametrize("from_start", [False, True])
async def test_a_writer_that_gives_no_reply_stops_the_plan_and_it_can_be_picked_up(
    tmp_path: Path, house: AgentHost, from_start: bool
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
    restarted = house.episodes.again(episode_id, from_start=from_start)
    assert restarted["stage"]["name"] == ("brief" if from_start else "script")
    await settle(lambda: not house.episodes.planning(episode_id))
    assert house.episodes.view(episode_id)["status"] == "plan"
    with pytest.raises(ValueError, match="Only a stopped or failed draft"):
        house.episodes.again(episode_id, from_start=True)


# -- the studio: approval, picks, pictures --------------------------------------------------------


async def test_approving_the_plan_starts_its_pictures(house: AgentHost) -> None:
    episode_id = await planned(house)
    with pytest.raises(ValueError, match="Make a picture or record a chapter first"):
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


async def test_a_picture_is_made_by_name_before_the_rest_and_a_chapters_together(
    house: AgentHost,
) -> None:
    episode_id = await planned(house)
    desk = house.episodes
    units_at_first = desk.view(episode_id)["units"]
    first = units_at_first[0]
    with pytest.raises(ValueError, match="no picture to make there"):
        desk.make(episode_id, by="you", only=["nope"])
    desk.make(episode_id, by="you", only=[first["id"]])
    await settle(lambda: not desk._busy(episode_id))
    view = desk.view(episode_id)
    states = {u["id"]: u["picture"]["status"] for u in view["units"]}
    assert states[first["id"]] == "made" and set(states.values()) == {"made", "none"}
    # the studio is open and a draft can be rendered, though the plan's other pictures wait
    assert view["status"] == "studio" and not view["approved"]
    assert view["pictures"] == {"made": 1, "go": 0, "making": 0, "failed": 0}
    # a pick that touches nothing of an unasked picture starts none
    desk.choose(episode_id, by="you", change={"settings": {"voice": "live"}})
    assert not desk._busy(episode_id)
    # a chapter's pictures are asked for together; the one already made is left as it is
    chapter = next(u["chapter"] for u in units_at_first if u["chapter"] != first["chapter"])
    wanted = [u["id"] for u in units_at_first if u["chapter"] == chapter]
    kept = desk.store.picture(episode_id, first["id"])
    desk.make(episode_id, by="you", chapter=chapter)
    await settle(lambda: not desk._busy(episode_id))
    states = {u["id"]: u["picture"]["status"] for u in desk.view(episode_id)["units"]}
    assert all(states[u] == "made" for u in wanted)
    assert sum(1 for state in states.values() if state == "made") == 1 + len(wanted)
    assert desk.store.picture(episode_id, first["id"])["updated_at"] == kept["updated_at"]  # type: ignore[index]
    # approving the plan asks for every picture that is left
    desk.approve(episode_id, by="you")
    await settle(lambda: not desk._busy(episode_id))
    assert {u["picture"]["status"] for u in desk.view(episode_id)["units"]} == {"made"}


async def test_regenerate_chapter_rebuilds_current_visuals_with_an_optional_model(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    eid = await planned(house)
    desk = house.episodes
    desk.approve(eid, by="you")
    await settle(lambda: not desk._busy(eid))
    existing = {row["unit"]: row for row in house.store.pictures(eid)}
    found = [u for u in desk.view(eid)["units"] if u["kind"] == "picture"]
    chapter = found[0]["chapter"]
    wanted = {u["id"] for u in found if u["chapter"] == chapter}
    before = house.store.episode(eid)
    assert before is not None and wanted and existing.keys() - wanted

    desk.regenerate_chapter(eid, chapter, by="you")
    await settle(lambda: not desk._busy(eid))
    rebuilt = {row["unit"]: row for row in house.store.pictures(eid)}
    for key, row in rebuilt.items():
        if key in wanted:
            assert row["updated_at"] > existing[key]["updated_at"]
            assert row["status"] == "made" and row["level"] == existing[key]["level"]
            assert row["generation"]["model"] == "demo"
            # the version each picture was is kept, to look back at
            assert [(v["n"], v["stills"]) for v in row["versions"]] == [
                (1, existing[key]["stills"])
            ]
        else:
            assert row == existing[key]

    monkeypatch.setattr(house.research, "ready", lambda provider: provider == "codex")
    actual: dict[str, tuple[str, str, str]] = {}

    async def draw(worker: LocalWorker, episode: dict[str, Any], *, lane: str, **more: Any) -> Told:
        unit_id = lane.removeprefix("picture:")
        actual[unit_id] = (worker.id, worker.model, worker.effort)
        comp = picture.composition_id(unit_id)
        folder = worker.folder(episode)
        brief = json.loads((folder / f"pictures/{comp}.brief.json").read_text())
        (folder / brief["file"]).write_text((folder / f"pictures/{comp}.starter.html").read_text())
        return Told()

    monkeypatch.setattr(LocalWorker, "turn", draw)
    model = "gpt-6.1-sol"
    desk.regenerate_chapter(eid, chapter, by="you", provider="codex", model=model)
    await settle(lambda: not desk._busy(eid))
    assert actual == {key: ("codex", model, "") for key in wanted}
    after = desk.view(eid)
    assert {u["picture"]["generation"]["model"] for u in after["units"] if u["id"] in wanted} == {
        model
    }
    saved = house.store.episode(eid)
    assert saved is not None
    assert (saved["plan"], saved["picks"]) == (before["plan"], before["picks"])
    assert all(house.store.picture(eid, key) == existing[key] for key in existing.keys() - wanted)


async def test_regenerate_chapter_validates_before_queueing(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    eid = await planned(house)
    desk = house.episodes
    chapter = desk.view(eid)["units"][0]["chapter"]
    monkeypatch.setattr(house.research, "ready", lambda provider: provider == "codex")
    with pytest.raises(ValueError, match="chapter has no visuals"):
        desk.regenerate_chapter(eid, "missing", by="you")
    with pytest.raises(ValueError, match="isn't ready"):
        desk.regenerate_chapter(eid, chapter, by="you", provider="claude")
    with pytest.raises(ValueError, match="supported model"):
        desk.regenerate_chapter(eid, chapter, by="you", provider="codex", model="invalid")
    with pytest.raises(ValueError, match="provider"):
        desk.regenerate_chapter(eid, chapter, by="you", model="gpt-6.1-sol")
    assert house.store.pictures(eid) == []

    desk.regenerate_chapter(eid, chapter, by="you")
    queued = house.store.pictures(eid)
    with pytest.raises(ValueError, match="already being made"):
        desk.regenerate_chapter(eid, chapter, by="you")
    assert house.store.pictures(eid) == queued
    await settle(lambda: not desk._busy(eid))


async def test_one_picture_is_stopped_and_the_others_go_on(
    tmp_path: Path, house: AgentHost
) -> None:
    episode_id = await planned(house)
    desk = house.episodes
    slow, quick = (u["id"] for u in desk.view(episode_id)["units"][:2])

    class Uneven(DemoWorker):
        async def turn(self, episode: Any, *, lane: str, prompt: str, heard: Any) -> Told:
            if lane == f"picture:{slow}":
                await asyncio.sleep(30)
            return await super().turn(episode, lane=lane, prompt=prompt, heard=heard)

    desk.workers[DEMO] = Uneven(data_dir=tmp_path, script=SCRIPT, pause=0)
    desk.make(episode_id, by="you", only=[slow, quick])
    await settle(lambda: desk.store.picture(episode_id, quick)["status"] == "made")  # type: ignore[index]
    desk.stop(episode_id, slow)
    await settle(lambda: not desk._busy(episode_id))
    assert desk.store.picture(episode_id, slow)["failure"] == "Stopped."  # type: ignore[index]
    assert desk.store.picture(episode_id, quick)["status"] == "made"  # type: ignore[index]


async def test_a_rich_picture_is_planned_shot_by_shot_before_it_is_drawn(
    tmp_path: Path, house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    desk = house.episodes
    desk.workers[DEMO] = DemoWorker(data_dir=tmp_path, script=SCRIPT, pause=0, store=house.store)
    episode_id = await planned(house)
    unit = next(u for u in desk.view(episode_id)["units"] if len(u["frames"]) > 1)
    # what the computer would give its review: a frame from inside a move, and a measurement
    moving = f"01-{unit['frames'][0]}-cue1-moving"
    monkeypatch.setattr(desk, "_motion_frames", lambda episode, unit, full, html: {moving: PNG})
    desk._craft[(episode_id, unit["id"])] = ["dead_stretch: 4.2 s with nothing changing"]
    # its level is picked before it is asked for: nothing is drawn by the pick
    view = desk.choose(episode_id, by="you", change={"units": {unit["id"]: {"level": "rich"}}})
    picked = next(u for u in view["units"] if u["id"] == unit["id"])
    assert picked["level"] == "rich" and picked["level_by"] == "person"
    assert picked["picture"]["status"] == "none" and not desk._busy(episode_id)
    desk.make(episode_id, by="you", only=[unit["id"]])
    await settle(lambda: not desk._busy(episode_id))
    made = next(u for u in desk.view(episode_id)["units"] if u["id"] == unit["id"])["picture"]
    assert made["status"] == "go" and made["level"] == "rich" and made["builder"] == DEMO
    motion = made["motion"]
    assert motion["device"] in picture.DEVICES and motion["world"]
    assert [shot["frame"] for shot in motion["shots"]] == unit["frames"]
    assert all(shot["shot"] and shot["hero"] and shot["still"] for shot in motion["shots"])
    # the build stage by stage, each with when it began and ended: the stills are the house's,
    # taken between the drawing and the review, and the go waits for the person
    stages = made["stages"]
    assert [(s["id"], s["state"]) for s in stages] == [
        ("motion", "done"),
        ("draw", "done"),
        ("pose", "done"),
        ("review", "done"),
        ("go", "waiting"),
    ]
    assert all(s["started_at"] and s["ended_at"] for s in stages[:4])
    assert stages[2]["started_at"] == stages[1]["ended_at"]
    assert stages[2]["ended_at"] == stages[3]["started_at"]
    assert made["reviewed"] == "Nothing to change." and not made["steerable"]
    # the build's times are kept with the beat: in all, and stage by stage without the go,
    # which is the person's
    kept = house.store.picture(episode_id, unit["id"])["timing"]
    assert kept["ended_at"] >= kept["started_at"] == made["timing"]["started_at"]
    assert kept["seconds"] == made["timing"]["seconds"] >= 0
    assert [(s["id"], s["state"]) for s in kept["stages"]] == [
        (s["id"], s["state"]) for s in stages[:4]
    ]
    assert all(s["seconds"] is not None for s in kept["stages"])
    # a restart forgets the build the house held in memory; the beat's record still dates it
    desk._began.clear()
    after = next(u for u in desk.view(episode_id)["units"] if u["id"] == unit["id"])["picture"]
    assert after["stages"] == stages and after["timing"] == made["timing"]
    # the plan came first, the picture was built to it, and its builder then looked at it
    thread_id = desk.view(episode_id)["thread_id"]
    turns = [str(r["prompt"]) for r in house.store.runs(thread_id, f"picture:{unit['id']}")]
    assert [turn.split("\n")[0] for turn in turns[:2]] == ["Stage: motion plan.", "Stage: picture."]
    assert "Look at how" in turns[2] and "motion_plan" in turns[1]
    folder = desk.data_dir / "episodes" / episode_id / "pictures"
    comp = picture.composition_id(unit["id"])
    brief = json.loads((folder / f"{comp}.brief.json").read_text())
    assert brief["motion_plan"] == motion and brief["level"] == "rich"
    # each turn is sent to HyperFrames' own guides, beside the episode's brief for that turn
    assert all("skill/hyperframes/" in turn for turn in turns[:3])
    # the review has the stills, frames of the motion by name, and what the renderer measured
    assert f"pictures/{comp}.stills/" in turns[2] and f"pictures/{comp}.motion/" in turns[2]
    assert (folder / f"{comp}.motion" / f"{moving}.png").read_bytes() == PNG
    assert "What the renderer measured:\n- dead_stretch: 4.2 s with nothing changing" in turns[2]
    assert (episode_id, unit["id"]) not in desk._craft


async def test_a_note_left_while_a_picture_is_built_goes_in_with_the_builders_next_turn(
    tmp_path: Path, house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    desk = house.episodes
    episode_id = await planned(house)
    unit = next(u for u in desk.view(episode_id)["units"] if len(u["frames"]) > 1)
    monkeypatch.setattr(desk, "_motion_frames", lambda episode, unit, full, html: {})
    desk.choose(episode_id, by="you", change={"units": {unit["id"]: {"level": "rich"}}})
    seen: list[dict[str, Any]] = []

    class Steered(DemoWorker):
        async def turn(self, episode: Any, *, lane: str, prompt: str, heard: Any) -> Told:
            if prompt.startswith("Stage: motion plan.\n\nPlan how"):
                # the person writes while the shots are being planned, and takes one back
                desk.steer(episode_id, unit["id"], "Drop this one", by="you")
                view = desk.steer(
                    episode_id, unit["id"], " Use a stockroom,\n not boxes. ", by="you"
                )
                seen.append(next(u for u in view["units"] if u["id"] == unit["id"])["picture"])
                desk.unsteer(episode_id, unit["id"], seen[0]["queued"][0]["id"], by="you")
                live = next(u for u in desk.view(episode_id)["units"] if u["id"] == unit["id"])
                seen.append(live["picture"])
            return await super().turn(episode, lane=lane, prompt=prompt, heard=heard)

    desk.workers[DEMO] = Steered(data_dir=tmp_path, script=SCRIPT, pause=0, store=house.store)
    desk.make(episode_id, by="you", only=[unit["id"]])
    await settle(lambda: not desk._busy(episode_id))
    # while the plan was made, the notes waited, said once, and the build stood at its plan
    assert [n["text"] for n in seen[0]["queued"]] == [
        "Drop this one",
        "Use a stockroom, not boxes.",
    ]
    assert seen[0]["steerable"] and [n["text"] for n in seen[1]["queued"]] == [
        "Use a stockroom, not boxes."
    ]
    assert [(s["id"], s["state"]) for s in seen[1]["stages"][:2]] == [
        ("motion", "running"),
        ("draw", "pending"),
    ]
    # the build's own clock runs from when it began, whichever stage it is on
    assert seen[1]["timing"]["started_at"] and seen[1]["timing"]["ended_at"] is None
    # the note went in with the builder's next turn, the drawing, and with no other
    thread_id = desk.view(episode_id)["thread_id"]
    turns = [str(r["prompt"]) for r in house.store.runs(thread_id, f"picture:{unit['id']}")]
    assert turns[1].startswith("Stage: picture.\n\nBuild one picture")
    assert turns[1].endswith("Take them in:\n- Use a stockroom, not boxes.")
    assert sum("Use a stockroom" in t for t in turns) == 1
    assert not any("Drop this one" in t for t in turns)
    made = next(u for u in desk.view(episode_id)["units"] if u["id"] == unit["id"])["picture"]
    assert made["queued"] == []
    assert [(n["text"], n["stage"]) for n in made["steered"]] == [
        ("Use a stockroom, not boxes.", "draw")
    ]
    # a made picture, a simple one and a note already given have no turn left to take it
    assert not made["steerable"]
    with pytest.raises(ValueError, match="none to come"):
        desk.steer(episode_id, unit["id"], "Bigger", by="you")
    other = next(
        u
        for u in desk.view(episode_id)["units"]
        if u["kind"] == "picture" and u["id"] != unit["id"]
    )
    with pytest.raises(ValueError, match="none to come"):
        desk.steer(episode_id, other["id"], "Bigger", by="you")
    with pytest.raises(ValueError, match="already gone"):
        desk.unsteer(episode_id, unit["id"], made["steered"][0]["id"], by="you")


def test_a_build_reads_its_stages_from_how_each_turn_opens() -> None:
    def turn(prompt: str, start: float, end: float | None, state: str = "done") -> dict[str, Any]:
        return {
            "prompt": prompt,
            "started_at": start,
            "ended_at": end,
            "state": state,
            "answer": "",
        }

    old = turn("Stage: picture.\n\nBuild one picture of the episode.", 1.0, 5.0)
    plan = turn("Stage: motion plan.\n\nPlan how one picture moves.", 10.0, 20.0)
    fixed = turn("Stage: motion plan.\n\npics/p.motion.json can't be used yet", 20.0, 22.0)
    draw = turn("Stage: picture.\n\nBuild one picture of the episode.", 22.0, None, "working")
    asked = turn("Stage: change.\n\nSomething else on the lane.", 23.0, 24.0)
    making = {"status": "making"}
    # only the latest build counts, a plan put right counts as planning, and any other turn on
    # the lane is not a stage
    stages, reviewed = _stages([old, plan, fixed, draw, asked], making, "rich", None)
    assert [(s["id"], s["state"], s["started_at"], s["ended_at"]) for s in stages] == [
        ("motion", "done", 10.0, 22.0),
        ("draw", "running", 22.0, None),
        ("pose", "pending", None, None),
        ("review", "pending", None, None),
        ("go", "pending", None, None),
    ]
    assert reviewed == ""
    # between turns the house works on its own: the stills after a drawing is done
    drawn = {**draw, "state": "done", "ended_at": 30.0}
    posing = _stages([plan, drawn], {"status": "posing"}, "rich", None)[0]
    assert [(s["id"], s["state"]) for s in posing][1:3] == [("draw", "done"), ("pose", "running")]
    assert posing[2]["started_at"] == 30.0
    # the review's words are kept as plain words, without the marks of its markdown
    looked = turn("Stage: picture.\n\nLook at how pics/p.html came out", 31.0, 40.0)
    looked["answer"] = "I fixed **two** things in `pics/p.html`: the __label__ and pic_1."
    seen = _stages([plan, drawn, looked], {"status": "go"}, "rich", None)
    assert seen[1] == "I fixed two things in pics/p.html: the label and pic_1."
    assert [s["state"] for s in seen[0]] == ["done", "done", "done", "done", "waiting"]
    # a build that stopped is marked where it stopped; a waiting one has no turns yet
    stopped = {**draw, "state": "stopped", "ended_at": 25.0}
    failed = _stages([plan, stopped], {"status": "failed"}, "rich", None)[0]
    assert [s["state"] for s in failed] == ["done", "failed", "pending", "pending", "pending"]
    queued = _stages([plan, drawn], {"status": "queued"}, "rich", None)[0]
    assert {s["state"] for s in queued} == {"pending"}
    # while a build is under way, turns from before it began are not its own
    began = _stages([old, plan], making, "simple", 8.0)[0]
    assert [(s["id"], s["state"]) for s in began] == [("draw", "running"), ("pose", "pending")]
    assert _stages([plan], None, "rich", None) == ([], "")
    # an agent without a session of its own is retold the earlier turns first: its turn's stage
    # is read from what it was asked now
    told = [{"prompt": plan["prompt"], "answer": "Planned it."}]
    retold_draw = {**drawn, "prompt": retold(told, str(draw["prompt"]))}
    assert retold_draw["prompt"].startswith("Earlier turns of this work")
    stages = _stages([plan, retold_draw], {"status": "made"}, "rich", None)[0]
    assert [(s["id"], s["state"]) for s in stages][:2] == [("motion", "done"), ("draw", "done")]
    simple = _stages([old, retold_draw], {"status": "made"}, "simple", None)[0]
    assert simple[0]["started_at"] == 22.0


def test_a_pictures_motion_is_looked_at_inside_its_moves_and_its_quiet_stretches() -> None:
    own = {
        "seconds": 20.0,
        "lines": {"c1.b1.f1": [0.0, 9.0], "c1.b2.f1": [9.0, 20.0]},
        "cues": {"c1.b1.f1/0": 0.5, "c1.b1.f1/1": 6.5, "c1.b2.f1/0": 9.4, "c1.b2.f1/1": 9.45},
    }
    marks = picture.motion_times(own)
    names = [name for name, _ in marks]
    # every cue inside its move and once landed, in the order they play, numbered
    assert names[:2] == ["01-c1.b1.f1-cue1-moving", "02-c1.b1.f1-cue1-landed"]
    assert dict(marks)["01-c1.b1.f1-cue1-moving"] == 0.65
    # a stretch the cues leave quiet is looked at in its middle, on the line it falls in
    quiet = [(name, at) for name, at in marks if name.endswith("-quiet")]
    assert [name.split("-", 1)[1] for name, _ in quiet] == ["c1.b1.f1-quiet", "c1.b2.f1-quiet"]
    assert 1.25 < quiet[0][1] < 6.5 and 10.2 < quiet[1][1] < 20.0
    # two looks a few frames apart show the same thing; none falls outside the picture
    times = [at for _, at in marks]
    assert times == sorted(times) and all(
        b - a >= 0.1 for a, b in zip(times, times[1:], strict=False)
    )
    assert all(0.0 <= at <= 19.95 for at in times)
    assert picture.motion_times({"seconds": 0.0, "lines": {}, "cues": {}}) == []
    busy = {
        "seconds": 90.0,
        "lines": {"c1.b1.f1": [0.0, 90.0]},
        "cues": {f"c1.b1.f1/{n}": n * 5.0 for n in range(18)},
    }
    assert len(picture.motion_times(busy)) == picture.MOTION_FRAMES


def test_what_the_renderer_measures_is_kept_as_notes_for_the_review_never_as_faults() -> None:
    report = """
Lint
  ◇ 0 errors, 0 warnings

Runtime
  ◇ 0 errors, 0 warnings

Contrast
  ◇ 12/12 text checks pass WCAG AA

Craft
  ⚠ dead_stretch: nothing changes for 5.5 s
    index.html #root 20.9–26.4s
    Fix: add a change, or mark a deliberate hold with data-hold
  ⚠ film_silent: a film over 15 s has no sound
    index.html
  ⚠ text_below_floor: 22 px text is under 2.6% of the short side
    compositions/pic.html #pic-label 0–27.5s
  0 error(s), 3 warning(s), 0 info(s)

Snapshots
  ◇ disabled
"""
    notes = _craft_notes(report)
    assert notes == [
        "dead_stretch: nothing changes for 5.5 s (index.html #root 20.9–26.4s) "
        "(Fix: add a change, or mark a deliberate hold with data-hold)",
        "text_below_floor: 22 px text is under 2.6% of the short side "
        "(compositions/pic.html #pic-label 0–27.5s)",
    ]
    # an older renderer has no craft pass: nothing is said
    assert _craft_notes("Lint\n  ◇ 0 errors, 0 warnings\n\nSnapshots\n  ◇ disabled\n") == []
    # the engine's agent reads the vendored skill; a coding agent a copy beside its own
    assert _guides("/skills/episode") == "/skills/hyperframes/references"
    assert _guides("skill") == "skill/hyperframes"


async def test_a_coding_agent_is_handed_the_hyperframes_guides_its_briefs_name(
    tmp_path: Path, house: AgentHost
) -> None:
    worker = LocalWorker("kimi", store=house.store, data_dir=tmp_path, project_root=ROOT)
    episode = {"id": "ep_guides", "thread_id": "th_guides"}
    await worker.prepare(episode, {"pictures/pic.brief.json": "{}"})
    guides = worker.folder(episode) / "skill" / "hyperframes"
    for name in HYPERFRAMES_GUIDES:
        assert (guides / name).read_text() == (
            ROOT / "skills" / "hyperframes" / "references" / name
        ).read_text()
    # every guide the two briefs send a builder to is one it is handed
    briefs = "".join(
        (ROOT / "skills" / "episode" / "briefs" / name).read_text()
        for name in ("motion.md", "picture.md")
    )
    named = set(re.findall(r"`((?:types/)?[a-z]+\.md)`", briefs)) - {"motion.md", "picture.md"}
    assert named and named <= set(HYPERFRAMES_GUIDES) | {"motion.md"}


async def test_switching_a_made_picture_to_rich_with_a_yes_makes_it_again_that_way(
    tmp_path: Path, house: AgentHost
) -> None:
    desk = house.episodes
    desk.workers[DEMO] = DemoWorker(data_dir=tmp_path, script=SCRIPT, pause=0, store=house.store)
    episode_id = await planned(house)
    unit = next(u for u in desk.view(episode_id)["units"] if len(u["frames"]) > 1)
    desk.make(episode_id, by="you", only=[unit["id"]])
    await settle(lambda: not desk._busy(episode_id))
    # made simple by a build that kept no level, as pictures made before levels were kept, with
    # a clip of it as it was
    desk.store.set_picture(episode_id, unit["id"], level="", clip="f_was")
    made = next(u for u in desk.view(episode_id)["units"] if u["id"] == unit["id"])["picture"]
    assert made["status"] == "made" and made["motion"] is None
    # asked for as it stands, it is left as it is
    desk.make(episode_id, by="you", only=[unit["id"]])
    assert not desk._busy(episode_id)
    # switched to rich with a yes: the level is the person's, and it is made again that way
    view = desk.make(episode_id, by="you", only=[unit["id"]], level="rich")
    again = next(u for u in view["units"] if u["id"] == unit["id"])
    assert again["level"] == "rich" and again["level_by"] == "person"
    assert again["picture"]["status"] in ("queued", "making")
    await settle(lambda: not desk._busy(episode_id))
    rich = next(u for u in desk.view(episode_id)["units"] if u["id"] == unit["id"])["picture"]
    assert rich["status"] == "go" and rich["level"] == "rich" and rich["motion"]["shots"]
    # the clip of the picture as it was never plays for the one made again
    assert desk.store.picture(episode_id, unit["id"])["clip"] != "f_was"

    # Switching back starts a simple drawing and clears the previous rich shot sheet.
    desk.make(episode_id, by="you", only=[unit["id"]], level="simple")
    await settle(lambda: not desk._busy(episode_id))
    back = next(u for u in desk.view(episode_id)["units"] if u["id"] == unit["id"])
    assert back["level"] == "simple" and back["picture"]["level"] == "simple"
    assert back["picture"]["status"] == "made" and back["picture"]["motion"] is None


async def test_invalid_motion_plan_recovers_from_the_same_brief_after_one_retry(
    tmp_path: Path, house: AgentHost
) -> None:
    asked: list[str] = []

    class Vague(DemoWorker):
        async def turn(self, episode: Any, *, lane: str, prompt: str, heard: Any) -> Told:
            if "Stage: motion plan" in prompt:
                asked.append(prompt)
                target = self.folder(episode) / picture.motion_file(lane.removeprefix("picture:"))
                target.write_text(json.dumps({"device": "a slide", "shots": []}))
                return Told(answer="Planned it.")
            return await super().turn(episode, lane=lane, prompt=prompt, heard=heard)

    desk = house.episodes
    desk.workers[DEMO] = Vague(data_dir=tmp_path, script=SCRIPT, pause=0)
    episode_id = await planned(house, level="rich")
    unit = desk.view(episode_id)["units"][0]
    desk.make(episode_id, by="you", only=[unit["id"]])
    await settle(lambda: not desk._busy(episode_id))
    made = desk.view(episode_id)["units"][0]["picture"]
    assert made["status"] == "go", made["failure"]
    assert [s["frame"] for s in made["motion"]["shots"]] == unit["frames"]
    assert (
        made["motion"]["shots"][0]["still"]
        == lines_of(desk.view(episode_id))[unit["frames"][0]]["shows"]
    )
    assert len(asked) == 2 and "has no shot" in asked[1]
    assert unit["frames"][0] in asked[0] and '"hero"' in asked[0]


def test_a_motion_plan_keeps_one_shot_a_line_and_only_what_its_shape_names() -> None:
    unit = {"id": "c1.b1.f1", "frames": ["c1.b1.f1", "c1.b2.f1"]}
    shot = {
        "shot": "A drawer opens.",
        "hero": "The drawer  slides out.",
        "still": "The drawer, open.",
        "camera": "push",
    }
    text = json.dumps(
        {
            "device": "one diagram that grows",
            "world": "A bench.",
            "palette": "ink on paper",
            "shots": [{"frame": "c1.b2.f1", **shot}, {"frame": "c1.b1.f1", **shot}],
        }
    )
    plan, faults = picture.motion_plan(text, unit)
    assert not faults and set(plan) == {"device", "world", "shots"}
    # in the picture's own order, whatever order they were written in, and nothing extra
    assert [s["frame"] for s in plan["shots"]] == unit["frames"]
    assert plan["shots"][0] == {
        "frame": "c1.b1.f1",
        "shot": "A drawer opens.",
        "opens_on": "",
        "hero": "The drawer slides out.",
        "others": "",
        "still": "The drawer, open.",
        # how the shot is framed is part of a shot; what a plan leaves out is not invented
        "camera": "push",
    }
    assert "between" not in plan["shots"][0]
    # a plan written as a spec keeps its numbers and the treatments it weighed, three at most
    spec = {
        "look": "Ink  #000000 lines 3 px.",
        "objects": "A drawer with tabs.",
        "motion": "Arrive on expo.out, 0.6 s.",
        "banned": "A row of labelled boxes.",
        "treatments": ["Picked: the stockroom.", "The ledger.", "The relay.", "A fourth.", 5, " "],
    }
    plan, faults = picture.motion_plan(json.dumps({**json.loads(text), **spec}), unit)
    assert not faults and plan["look"] == "Ink #000000 lines 3 px."
    assert (plan["objects"], plan["motion"], plan["banned"]) == (
        "A drawer with tabs.",
        "Arrive on expo.out, 0.6 s.",
        "A row of labelled boxes.",
    )
    assert plan["treatments"] == ["Picked: the stockroom.", "The ledger.", "The relay."]
    assert "palette" not in plan
    assert picture.motion_plan("not json", unit)[1][0].startswith("the file is not JSON")
    assert picture.motion_plan("[]", unit)[1] == [
        'the file is one object with "device", "world" and a "shots" list'
    ]
    _, faults = picture.motion_plan(
        json.dumps({"device": "boxes", "shots": [{"frame": "c1.b1.f1"}, {"frame": "c9.b1.f1"}]}),
        unit,
    )
    assert 'the shot for line c1.b1.f1 needs "hero"' in faults
    assert "line c1.b2.f1 has no shot: write one shot for every line, in order" in faults
    assert "shots for lines the picture does not have: c9.b1.f1" in faults
    assert any(f.startswith('"device" is one of') for f in faults) and any(
        f.startswith('"world"') for f in faults
    )
    # the line a person reads beside the script is short; the builder's own detail is not cut
    wordy = {**shot, "shot": " ".join(["word"] * 30), "hero": "x" * 900}
    plan, faults = picture.motion_plan(
        json.dumps(
            {
                "device": "two sides",
                "world": "A bench.",
                "shots": [{"frame": f, **wordy} for f in unit["frames"]],
            }
        ),
        unit,
    )
    assert len(faults) == 2 and all("at most 20 words (it has 30)" in f for f in faults)
    assert len(plan["shots"][0]["hero"]) == 900


async def test_each_picture_can_be_built_by_another_agent(tmp_path: Path, house: AgentHost) -> None:
    class Other(DemoWorker):
        id = "codex"
        title = "Codex"

    desk = house.episodes
    desk.workers[DEMO] = DemoWorker(data_dir=tmp_path, script=SCRIPT, pause=0, store=house.store)
    desk.workers["codex"] = Other(data_dir=tmp_path, script=SCRIPT, pause=0, store=house.store)
    episode_id = await planned(house)
    mine, theirs = (u["id"] for u in desk.view(episode_id)["units"][:2])
    with pytest.raises(ValueError, match="isn't ready on this computer"):
        desk.choose(episode_id, by="you", change={"units": {theirs: {"builder": "kimi"}}})
    view = desk.choose(episode_id, by="you", change={"units": {theirs: {"builder": "codex"}}})
    builders = {u["id"]: u["builder"] for u in view["units"]}
    assert builders[theirs] == "codex" and builders[mine] == DEMO
    desk.make(episode_id, by="you", only=[mine, theirs])
    await settle(lambda: not desk._busy(episode_id))
    view = desk.view(episode_id)
    built = {u["id"]: u["picture"] for u in view["units"]}
    assert built[theirs]["status"] == "made" and built[theirs]["builder"] == "codex"
    assert built[mine]["builder"] == DEMO
    by_lane = {r["lane"]: r["harness"] for r in house.store.runs(view["thread_id"])}
    assert by_lane[f"picture:{theirs}"] == "codex" and by_lane[f"picture:{mine}"] == DEMO
    # a pick of its level keeps who builds it, and no builder gives it back to the film's writer
    view = desk.choose(episode_id, by="you", change={"units": {theirs: {"level": "simple"}}})
    assert next(u for u in view["units"] if u["id"] == theirs)["builder"] == "codex"
    view = desk.choose(episode_id, by="you", change={"units": {theirs: {"builder": None}}})
    assert next(u for u in view["units"] if u["id"] == theirs)["builder"] == DEMO
    # a chapter's pictures are built by the agent picked for the chapter, unless one of them
    # has its own; the film's writer builds the rest
    chapter = next(u["chapter"] for u in view["units"] if u["id"] == theirs)
    inside = [u["id"] for u in view["units"] if u["chapter"] == chapter]
    with pytest.raises(ValueError, match="isn't ready on this computer"):
        desk.choose(episode_id, by="you", change={"builders": {chapter: "kimi"}})
    view = desk.choose(episode_id, by="you", change={"builders": {chapter: "codex"}})
    assert view["builders"][chapter] == "codex"
    assert {u["builder"] for u in view["units"] if u["id"] in inside} == {"codex"}
    assert {b for c, b in view["builders"].items() if c != chapter} == {DEMO}
    assert {u["builder"] for u in view["units"] if u["id"] not in inside} == {DEMO}
    view = desk.choose(episode_id, by="you", change={"units": {inside[0]: {"builder": DEMO}}})
    assert next(u for u in view["units"] if u["id"] == inside[0])["builder"] == DEMO
    view = desk.choose(episode_id, by="you", change={"builders": {chapter: None}})
    assert view["builders"][chapter] == DEMO
    # the film's writer is changed the same way: it builds what no pick names from then on
    view = desk.choose(episode_id, by="you", change={"settings": {"writer": "codex"}})
    assert view["settings"]["writer"] == "codex" and view["builders"][chapter] == "codex"
    assert next(u for u in view["units"] if u["id"] == inside[0])["builder"] == DEMO


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
    house.store.update_episode(
        episode_id, film={"status": "rendering", "started_at": time.time() - 5}
    )
    house.episodes.restore()
    after = house.episodes.view(episode_id)
    film = after["film_state"]
    assert film["status"] == "failed" and film["ended_at"] >= film["started_at"]
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
    assert house.episodes.options()["narrator"] == {"ready": True, "usual": True}
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


async def test_a_narrators_voice_is_picked_for_an_episode_or_cloned_from_its_takes(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic import SecretStr

    from design_agent.tools import media

    house.settings = house.settings.model_copy(update={"elevenlabs_api_key": SecretStr("key")})
    assert house.episodes.options()["narrator"] == {"ready": True, "usual": False}
    spoke: list[str] = []
    sent: dict[str, Any] = {}

    async def speak(keys: Any, text: str, voice_id: str, **more: Any) -> media.Spoken:
        spoke.append(voice_id)
        return media.Spoken(b"mp3", 2.0, [])

    async def clone_voice(keys: Any, name: str, samples: Any, **more: Any) -> media.Cloned:
        sent.update(name=name, samples=list(samples), **more)
        return media.Cloned("clone1234567890", verify=False)

    async def voices(keys: Any) -> list[media.Voice]:
        return [
            media.Voice("clone1234567890", "My voice", "cloned"),
            media.Voice("premade123456", "Ada", "premade"),
        ]

    for name, fake in (("speak", speak), ("clone_voice", clone_voice), ("voices", voices)):
        monkeypatch.setattr(media, name, fake)
    episode_id = await planned(house, presenter="off", voice="narrator")
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    with pytest.raises(ValueError, match="needs a voice"):
        await house.episodes._narrate(episode_id)
    # A clone is the person's to ask for: they say the voice is theirs to clone, and there is
    # enough of their speech to make it from.
    with pytest.raises(ValueError, match="yours"):
        await house.episodes.clone(episode_id, by="you", name="My voice", consent=False)
    with pytest.raises(ValueError, match="30 seconds"):
        await house.episodes.clone(episode_id, by="you", name="My voice", consent=True)
    assert not sent, "nothing leaves this computer until both are so"
    view = house.episodes.view(episode_id)
    sound = house.save_file(view["thread_id"], "take-1.m4a", b"m4a", origin="episode")["id"]
    monkeypatch.setattr(
        house.episodes,
        "_cut",
        lambda episode, take_id, name, source: {
            "uhd": "",
            "video": "",
            "audio": sound,
            "seconds": 45.0,
        },
    )
    chapter = view["plan"]["chapters"][0]["id"]
    await house.episodes.add_take(
        episode_id, by="you", chapter=chapter, name="take.webm", source=io.BytesIO(b"webm")
    )
    view = await house.episodes.clone(episode_id, by="you", name="  My   voice ", consent=True)
    assert sent == {"name": "My voice", "samples": [("take-1.m4a", b"m4a")], "noisy": False}
    assert view["settings"]["voice"] == "narrator"
    assert view["settings"]["narrator"] == {"id": "clone1234567890", "name": "My voice"}
    said = [m["text"] for m in house.store.messages(view["thread_id"])]
    assert any(
        "Cloned a voice with ElevenLabs" in text and "theirs to clone" in text for text in said
    )
    # the clone says the lines the take does not cover, and only those
    await house.episodes._narrate(episode_id)
    recorded = {line["frame"] for line in view["clock"]["lines"] if line["chapter"] == chapter}
    assert spoke and set(spoke) == {"clone1234567890"}
    assert len(spoke) == len(view["clock"]["lines"]) - len(recorded)
    # the channel's clones stay in its library, separate from the account picker
    listed = (await house.episodes.voices())["voices"]
    assert [(v["id"], v["own"]) for v in listed] == [("premade123456", False)]
    assert view["channel_voices"] == [{"id": "clone1234567890", "name": "My voice"}]
    episode = house.store.episode(episode_id)
    assert episode is not None
    full = house.episodes._full(episode)
    assert full is not None
    before = house.episodes._film_sig(
        episode, full, house.store.pictures(episode_id), house.episodes._kept(episode_id)
    )
    picked = house.episodes.choose(
        episode_id,
        by="you",
        change={"settings": {"narrator": {"id": "premade123456", "name": "Ada"}}},
    )
    assert picked["settings"]["narrator"] == {"id": "premade123456", "name": "Ada"}
    assert picked["settings"]["cloned_voice"] == {"id": "clone1234567890", "name": "My voice"}
    restored = house.episodes.choose(
        episode_id, by="you", change={"settings": {"narrator": picked["settings"]["cloned_voice"]}}
    )
    assert restored["settings"]["narrator"] == picked["settings"]["cloned_voice"]
    library = house.episodes.choose(
        episode_id, by="you", change={"settings": {"voice": "narrator", "narrator": None}}
    )
    assert not library["settings"].get("narrator")
    assert library["settings"]["cloned_voice"] == picked["settings"]["cloned_voice"]
    house.episodes.choose(
        episode_id, by="you", change={"settings": {"narrator": picked["settings"]["narrator"]}}
    )
    episode = house.store.episode(episode_id)
    assert (
        episode is not None
        and house.episodes._film_sig(
            episode, full, house.store.pictures(episode_id), house.episodes._kept(episode_id)
        )
        != before
    )
    with pytest.raises(ValueError, match="ElevenLabs voice"):
        house.episodes.choose(
            episode_id, by="you", change={"settings": {"narrator": {"id": "no", "name": "x"}}}
        )
    # a recording brought for the clone is sent in place of the takes; a voice ElevenLabs wants
    # verified is marked so
    monkeypatch.setattr(
        media, "clone_voice", lambda *a, **k: _async(media.Cloned("other1234567890", verify=True))
    )
    view = await house.episodes.clone(
        episode_id, by="you", name="Other", consent=True, sample=("memo.m4a", b"memo")
    )
    assert view["settings"]["narrator"] == {
        "id": "other1234567890",
        "name": "Other",
        "verify": True,
    }


async def _async(value: Any) -> Any:
    return value


async def test_a_pick_is_kept_and_its_picture_is_out_of_date_until_the_picks_are_applied(
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
    # trying a frame out draws nothing: the picture is out of date until the picks are applied
    assert changed["level"] == "rich" and changed["picture"]["status"] == "made"
    assert changed["picture"]["stale"] and not house.episodes._busy(episode_id)
    # a picture already made is drawn again at its new level once applied: rich is planned shot
    # by shot and its stills wait for the go; simple again, it is drawn from the plan alone
    other = next(u for u in before["units"] if u["id"] != unit["id"])

    def of_other(view: dict[str, Any]) -> dict[str, Any]:
        found: dict[str, Any] = next(u for u in view["units"] if u["id"] == other["id"])["picture"]
        return found

    waits = house.episodes.choose(
        episode_id, by="you", change={"units": {other["id"]: {"level": "rich"}}}
    )
    assert of_other(waits)["status"] == "made" and of_other(waits)["stale"]
    assert not house.episodes._busy(episode_id)
    applied = house.episodes.apply(episode_id, by="you")
    assert of_other(applied)["status"] == "queued"
    await settle(lambda: not house.episodes._busy(episode_id))
    rich = of_other(house.episodes.view(episode_id))
    assert rich["status"] == "go" and rich["level"] == "rich"
    assert [shot["frame"] for shot in rich["motion"]["shots"]] == other["frames"]
    plain = house.episodes.choose(
        episode_id, by="you", change={"units": {other["id"]: {"level": "simple"}}}
    )
    assert of_other(plain)["status"] == "go" and of_other(plain)["stale"]
    house.episodes.apply(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    simple = of_other(house.episodes.view(episode_id))
    assert simple["status"] == "made" and simple["level"] == "simple" and simple["motion"] is None
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
    back = next(u for u in undone["units"] if u["id"] == unit["id"])
    assert back["layout"] == "corner-window" and back["picture"]["stale"]
    # nothing waits once every picture asked for is current
    house.episodes.apply(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    with pytest.raises(ValueError, match="every picture asked for is up to date"):
        house.episodes.apply(episode_id, by="you")


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
    assert {u["picture"]["stale"] for u in moved} == {True}, "each is out of date for its new box"
    assert not house.episodes._busy(episode_id), "and none is drawn until the picks are applied"
    applied = house.episodes.apply(episode_id, by="you")
    assert {
        u["picture"]["status"] for u in applied["units"] if u["id"] in {b["id"] for b in both}
    } == {"queued"}
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
    kinds, ways = before["options"]["pictures"], before["options"]["transitions"]
    assert kinds[0]["id"] == "diagram" and all(k["means"] for k in kinds)
    assert [w["id"] for w in ways] == ["cut", "push", "crossfade", "zoom-through"]
    assert [w["seconds"] for w in ways] == [0.0, 0.4, 0.4, 0.5]
    unit = next(u for u in before["units"] if u["kind_of_picture"] == "diagram")
    view = house.episodes.choose(
        episode_id, by="you", change={"frames": {unit["id"]: {"picture": "list"}}}
    )
    stale = {u["id"]: u["picture"]["stale"] for u in view["units"]}
    assert stale.pop(unit["id"]) and set(stale.values()) == {False}
    assert next(u for u in view["units"] if u["id"] == unit["id"])["kind_of_picture"] == "list"
    assert not house.episodes._busy(episode_id)
    applied = house.episodes.apply(episode_id, by="you")
    statuses = {u["id"]: u["picture"]["status"] for u in applied["units"]}
    assert statuses.pop(unit["id"]) == "queued" and set(statuses.values()) == {"made"}
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
    assert {u["picture"]["stale"] for u in moved["units"]} == {False}
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


class Designer(DemoWorker):
    """The demo's writer, able to plan a picture for a line a person gave one."""

    asked: list[str]

    async def turn(self, episode: Any, *, lane: str, prompt: str, heard: Any) -> Told:
        if lane == "plan" and "Stage: redo" in prompt:
            self.asked.append(prompt)
            target = self.folder(episode) / "plan.json"
            plan = json.loads(target.read_text())
            for ch in plan["chapters"]:
                for b in ch["beats"]:
                    line = f"{b['id']}.f1"
                    if line in prompt and not b.get("frames"):
                        word = b["says"].split()[0].strip(".,:;")
                        b["frames"] = [
                            {
                                "id": line,
                                "shows": "One card that names the headers.",
                                "focal": "o1",
                                "objects": [{"id": "o1", "what": "a card", "words": "Headers"}],
                                "cues": [{"at": word, "object": "o1", "does": "pops in"}],
                            }
                        ]
            target.write_text(json.dumps(plan))
            return Told(answer="Planned a picture for the line.")
        return await super().turn(episode, lane=lane, prompt=prompt, heard=heard)


async def test_a_pick_that_needs_the_writer_waits_until_the_picks_are_applied(
    tmp_path: Path, house: AgentHost
) -> None:
    desk = house.episodes
    episode_id = await planned(house)
    desk.approve(episode_id, by="you")
    await settle(lambda: not desk._busy(episode_id))
    writer = Designer(data_dir=tmp_path, script=SCRIPT, pause=0)
    writer.asked = []
    desk.workers[DEMO] = writer
    desk.demo = False  # the demo's desk never asks its writer to redo a pick
    line = "c2.b6.f1"
    pick = {"frames": {line: {"presence": "both", "layout": "corner-window"}}}
    view = desk.choose(episode_id, by="you", change=pick)
    # the line now needs a picture: that waits, and nothing is planned or drawn yet
    assert [w["line"] for w in view["waiting"]] == [line]
    assert "needs a picture" in view["waiting"][0]["do"]
    assert not desk._busy(episode_id) and not writer.asked
    assert next(u for u in view["units"] if line in u["frames"])["kind"] == "undesigned"
    # a pick taken back takes what it left the writer with it
    assert desk.choose(episode_id, by="you", change={"clear": [line]})["waiting"] == []
    desk.choose(episode_id, by="you", change=pick)
    # applied: the writer plans the line's picture, then the pictures follow, the new one too
    desk.apply(episode_id, by="you")
    assert desk.planning(episode_id)
    await settle(lambda: not desk._busy(episode_id), seconds=10)
    view = desk.view(episode_id)
    assert len(writer.asked) == 1 and line in writer.asked[0] and view["waiting"] == []
    unit = next(u for u in view["units"] if line in u["frames"])
    assert unit["kind"] == "picture" and unit["picture"]["status"] == "made"
    assert "writer" not in desk.store.episode(episode_id)["picks"]  # type: ignore[index]


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


def order_of(view: dict[str, Any]) -> list[dict[str, Any]]:
    return list(lines_of(view).values())


async def made(house: AgentHost) -> str:
    """An episode planned, approved, and with every picture made."""
    episode_id = await planned(house)
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    return episode_id


async def test_a_line_a_person_adds_to_camera_is_ready_at_once(house: AgentHost) -> None:
    episode_id = await made(house)
    before = house.episodes.view(episode_id)
    lines = order_of(before)
    # after a picture's last line, with another picture after it
    k = next(
        i
        for i, f in enumerate(lines[:-1])
        if f["presence"] != "person"
        and lines[i + 1]["presence"] != "person"
        and not lines[i + 1].get("hold")
    )
    view = house.episodes.add_line(
        episode_id, by="you", after=lines[k]["id"], text="  Now, said to you.  ", kind="camera"
    )
    assert not house.episodes._busy(episode_id), "no agent runs for it"
    now = order_of(view)
    new, nxt = now[k + 1], now[k + 2]
    assert new["vo"] == "Now, said to you." and new["by_person"]["was"] == ""
    assert (new["presence"], new["picture"]) == ("person", "camera")
    assert (new["relation"], new["transition"]) == ("swap", "cut")
    assert nxt["id"] == lines[k + 1]["id"] and (nxt["relation"], nxt["transition"]) == (
        "swap",
        "cut",
    )
    beat = next(
        b
        for ch in view["plan"]["chapters"]
        for b in ch["beats"]
        if b["frames"][0] is not None and b["frames"][0]["id"] == new["id"]
    )
    assert beat["subtype"] and beat["by"] == "person", "what it does is the beat's before it"
    assert not [r for r in view["checks"] if r["level"] == "must"]
    assert view["last_change"]["added"] == [new["id"]] and view["waiting"] == []
    assert {u["picture"]["status"] for u in view["units"]} == {"made"}
    assert not any(u["picture"]["stale"] for u in view["units"]), "no picture is out of date"
    back = house.episodes.undo(episode_id, by="you")
    assert [f["id"] for f in order_of(back)] == [f["id"] for f in lines]
    # a block goes after a picture's last line, and nobody is on camera when the presenter is off
    run = next(u for u in before["units"] if len(u["frames"]) > 1)
    with pytest.raises(ValueError, match="after a picture's last line"):
        house.episodes.add_line(
            episode_id, by="you", after=run["frames"][0], text="Hi.", kind="camera"
        )
    with pytest.raises(ValueError, match="goes on after another line"):
        house.episodes.add_line(episode_id, by="you", after="c1", text="Hi.", kind="more")
    with pytest.raises(ValueError, match="not in the plan"):
        house.episodes.add_line(episode_id, by="you", after="c9.b9.f9", text="Hi.", kind="camera")
    with pytest.raises(ValueError, match="needs words"):
        house.episodes.add_line(
            episode_id, by="you", after=lines[0]["id"], text="  ", kind="camera"
        )


async def test_a_line_said_over_a_picture_puts_it_out_of_date_and_a_split_is_one_change(
    house: AgentHost,
) -> None:
    episode_id = await made(house)
    before = house.episodes.view(episode_id)
    run = next(u for u in before["units"] if len(u["frames"]) > 1)
    view = house.episodes.add_line(
        episode_id, by="you", after=run["frames"][0], text="And it stays on screen.", kind="more"
    )
    unit = next(u for u in view["units"] if u["id"] == run["id"])
    assert len(unit["frames"]) == len(run["frames"]) + 1, "the line joins the picture"
    new = lines_of(view)[unit["frames"][1]]
    assert new["hold"] and new["presence"] == lines_of(before)[run["id"]]["presence"]
    assert unit["picture"]["stale"] and not house.episodes._busy(episode_id), (
        "out of date, not redrawn"
    )
    house.episodes.undo(episode_id, by="you")
    # Enter in the middle of a line: it keeps its first words, the rest is a new line, in one change
    first = order_of(before)[0]
    assert first["presence"] == "person"
    view = house.episodes.add_line(
        episode_id,
        by="you",
        after=first["id"],
        keep="The first half,",
        text="and the rest.",
        kind="more",
    )
    now = order_of(view)
    assert (now[0]["vo"], now[1]["vo"]) == ("The first half,", "and the rest.")
    assert now[1]["presence"] == "person"
    back = house.episodes.undo(episode_id, by="you")
    assert order_of(back)[0]["vo"] == first["vo"] and len(order_of(back)) == len(order_of(before))


async def test_a_line_added_with_a_picture_is_designed_by_the_writer_once_applied(
    tmp_path: Path, house: AgentHost
) -> None:
    episode_id = await made(house)
    worker = heard_by(house, tmp_path)
    before = house.episodes.view(episode_id)
    lines = order_of(before)
    k = next(
        i
        for i, f in enumerate(lines[:-1])
        if f["presence"] == "person" and not lines[i + 1].get("hold")
    )
    view = house.episodes.add_line(
        episode_id,
        by="you",
        after=lines[k]["id"],
        text="Here is the whole path at once.",
        kind="diagram",
    )
    assert not worker.turns, "picking a picture for a new line runs nothing"
    new = order_of(view)[k + 1]
    assert new["presence"] in ("both", "content") and new["picked"] == {"picture": "diagram"}
    assert [w["line"] for w in view["waiting"]] == [new["id"]]
    unit = next(u for u in view["units"] if u["id"] == new["id"])
    assert unit["kind"] == "undesigned"
    house.episodes.apply(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    (lane, told), *_ = worker.turns
    assert lane == "plan" and "Stage: redo" in told and new["id"] in told and "Diagram" in told
    after = house.episodes.view(episode_id)
    designed = lines_of(after)[new["id"]]
    assert designed["shows"] and designed["vo"] == "Here is the whole path at once."
    unit = next(u for u in after["units"] if u["id"] == new["id"])
    assert unit["kind"] == "picture" and unit["kind_of_picture"] == "diagram"
    assert unit["picture"]["status"] == "made", "and once designed it is drawn"
    assert after["waiting"] == []


async def test_a_picture_made_for_other_words_says_so_and_is_planned_or_drawn_again(
    tmp_path: Path, house: AgentHost
) -> None:
    episode_id = await made(house)
    before = house.episodes.view(episode_id)
    unit = next(u for u in before["units"] if lines_of(before)[u["id"]].get("cues"))
    line = lines_of(before)[unit["id"]]
    assert not unit["picture"]["reworded"]
    # words that keep every step's word: the picture is current, but made for other words
    words = "Said my way: " + " and ".join(c["at"] for c in line["cues"]) + "."
    view = house.episodes.edit(episode_id, by="you", frame=line["id"], text=words)
    now = next(u for u in view["units"] if u["id"] == unit["id"])
    assert now["picture"]["reworded"] and not now["picture"]["stale"]
    assert now["picture"]["made_for"] == {line["id"]: line["vo"]}, "what it was made for"
    assert not house.episodes._busy(episode_id), "nothing runs for it"
    assert all(not u["picture"]["reworded"] for u in view["units"] if u["id"] != unit["id"])
    # kept as it is: it stands for the new words, and nothing runs
    kept = house.episodes.keep_picture(episode_id, unit["id"], by="you")
    assert not next(u for u in kept["units"] if u["id"] == unit["id"])["picture"]["reworded"]
    assert not house.episodes._busy(episode_id)
    with pytest.raises(ValueError, match="no made picture"):
        house.episodes.keep_picture(episode_id, "c9.b9.f9", by="you")
    # spacing alone is no change, and words put back make it current again
    spaced = house.episodes.edit(episode_id, by="you", frame=line["id"], text=words + " Again.")
    assert next(u for u in spaced["units"] if u["id"] == unit["id"])["picture"]["reworded"]
    back = house.episodes.edit(episode_id, by="you", frame=line["id"], text=words)
    assert not next(u for u in back["units"] if u["id"] == unit["id"])["picture"]["reworded"]
    # drawn again by name, it is made for the words its lines say now
    house.episodes.make(episode_id, by="you", only=[unit["id"]])
    await settle(lambda: not house.episodes._busy(episode_id))
    drawn = next(u for u in house.episodes.view(episode_id)["units"] if u["id"] == unit["id"])
    assert drawn["picture"]["status"] == "made" and not drawn["picture"]["reworded"]
    # or planned again: the writer fits it to the words, then it is drawn again
    worker = heard_by(house, tmp_path)
    house.episodes.edit(episode_id, by="you", frame=line["id"], text="Nothing it landed on.")
    with pytest.raises(ValueError, match="no picture there"):
        house.episodes.replan(episode_id, by="you", pictures=["c9.b9.f9"])
    house.episodes.replan(episode_id, by="you", pictures=[unit["id"]])
    await settle(lambda: not house.episodes._busy(episode_id))
    told = [prompt for lane, prompt in worker.turns if lane == "plan"]
    assert len(told) == 1 and "Fit what the picture shows" in told[0] and unit["id"] in told[0]
    after = house.episodes.view(episode_id)
    fitted = lines_of(after)[line["id"]]
    assert {c["at"] for c in fitted["cues"]} == {"Nothing"}
    again = next(u for u in after["units"] if u["id"] == unit["id"])
    assert again["picture"]["status"] == "made" and not again["picture"]["reworded"]
    assert after["last_change"]["why"] == "Planned pictures for your words"
    # taken back, the picture is the one that stood before: made for the words before those
    back = house.episodes.undo(episode_id, by="you")
    kept = next(u for u in back["units"] if u["id"] == unit["id"])
    assert lines_of(back)[line["id"]]["vo"] == "Nothing it landed on."
    assert kept["picture"]["reworded"]
    # and taking back the words too, it is made for what its lines say
    first = house.episodes.undo(episode_id, by="you")
    assert not next(u for u in first["units"] if u["id"] == unit["id"])["picture"]["reworded"]
    # a picture made before its words were kept is judged by when a line was last changed
    house.episodes.store.set_picture(episode_id, unit["id"], words="")
    assert not next(u for u in house.episodes.view(episode_id)["units"] if u["id"] == unit["id"])[
        "picture"
    ]["reworded"]
    house.episodes.edit(episode_id, by="you", frame=line["id"], text="Nothing, said again.")
    late = next(u for u in house.episodes.view(episode_id)["units"] if u["id"] == unit["id"])
    assert late["picture"]["reworded"]


async def test_lines_are_cut_one_at_a_time_or_as_a_block_and_joined_within_a_block(
    house: AgentHost,
) -> None:
    episode_id = await made(house)
    before = house.episodes.view(episode_id)
    lines = order_of(before)
    run = next(u for u in before["units"] if len(u["frames"]) > 2)
    with pytest.raises(ValueError, match="brings its picture in"):
        house.episodes.cut_lines(episode_id, by="you", frames=[run["frames"][0]])
    with pytest.raises(ValueError, match="not in the plan"):
        house.episodes.cut_lines(episode_id, by="you", frames=["c9.b9.f9"])
    chapter = before["plan"]["chapters"][-1]
    every = [f["id"] for b in chapter["beats"] for f in b["frames"]]
    with pytest.raises(ValueError, match="A chapter needs a line"):
        house.episodes.cut_lines(episode_id, by="you", frames=every)
    # a held line goes, and its picture is out of date
    view = house.episodes.cut_lines(episode_id, by="you", frames=[run["frames"][-1]])
    assert run["frames"][-1] not in lines_of(view) and not house.episodes._busy(episode_id)
    assert next(u for u in view["units"] if u["id"] == run["id"])["picture"]["stale"]
    assert view["last_change"]["cut"][0]["says"] == lines_of(before)[run["frames"][-1]]["vo"]
    house.episodes.undo(episode_id, by="you")
    # the whole block goes with its picture
    view = house.episodes.cut_lines(episode_id, by="you", frames=run["frames"])
    assert not set(run["frames"]) & set(lines_of(view))
    assert run["id"] not in {u["id"] for u in view["units"]}
    assert not [r for r in view["checks"] if r["rule"] == "unclassified"], "nothing to read again"
    house.episodes.undo(episode_id, by="you")
    # a held line's words go on at the end of the line before it
    second = lines_of(before)[run["frames"][1]]
    view = house.episodes.cut_lines(episode_id, by="you", frames=[run["frames"][2]], join=True)
    joined = lines_of(view)[run["frames"][1]]
    assert joined["vo"] == f"{second['vo']} {lines_of(before)[run['frames'][2]]['vo']}"
    assert joined["by_person"]["was"] == second["vo"]
    house.episodes.undo(episode_id, by="you")
    # joined with the words the person had there, in one change
    view = house.episodes.cut_lines(
        episode_id, by="you", frames=[run["frames"][2]], join=True, words="Both, said my way."
    )
    assert lines_of(view)[run["frames"][1]]["vo"] == "Both, said my way."
    house.episodes.undo(episode_id, by="you")
    # never across blocks, nor across chapters
    k = next(
        i
        for i, f in enumerate(lines)
        if i and f["presence"] == "person" and lines[i - 1]["presence"] != "person"
    )
    with pytest.raises(ValueError, match="joins the line before it in its block"):
        house.episodes.cut_lines(episode_id, by="you", frames=[lines[k]["id"]], join=True)
    second_chapter = before["plan"]["chapters"][1]["beats"][0]["frames"][0]["id"]
    with pytest.raises(ValueError, match="joins the line before it in its block"):
        house.episodes.cut_lines(episode_id, by="you", frames=[second_chapter], join=True)


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
    """The demo's writer, able to fit a cue to a person's words when asked to."""

    fixed: list[str]

    async def turn(self, episode: Any, *, lane: str, prompt: str, heard: Any) -> Any:
        if lane == "plan" and "fit its cues" in prompt:
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


async def test_a_step_that_lost_its_word_is_fitted_by_the_writer_once_applied(
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
    # typing runs no agent: the fit waits, with the rest, for the person to apply
    assert not house.episodes._busy(episode_id) and not worker.fixed
    assert [w["line"] for w in view["waiting"]] == [line["id"]]
    assert "fit its cues" in view["waiting"][0]["do"]
    house.episodes.apply(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    assert len(worker.fixed) == 1 and line["id"] in worker.fixed[0]
    assert "Stage: redo" in worker.fixed[0] and "exactly as they are" in worker.fixed[0]
    after = house.episodes.view(episode_id)
    assert after["waiting"] == []
    now = lines_of(after)[line["id"]]
    assert now["vo"] == "Nothing here that a step landed on before."
    assert {c["at"] for c in now["cues"]} == {"Nothing"}
    assert not [r for r in after["checks"] if r["where"] == line["id"] and r["level"] == "must"]
    assert {u["picture"]["status"] for u in after["units"]} == {"made"}, "its picture stands"
    assert after["stage"]["state"] == "done"
    assert after["last_change"]["why"] == "Planned what your changes need"
    # the fit is taken back on its own: the person's words stay
    back = house.episodes.undo(episode_id, by="you")
    assert back["last_change"]["lines"] == [line["id"]]
    assert lines_of(back)[line["id"]]["vo"] == "Nothing here that a step landed on before."
    assert [item["line"] for item in back["waiting"]] == [line["id"]]


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


async def test_the_studio_sees_the_writers_steps_and_each_builders_step_as_they_happen(
    house: AgentHost,
) -> None:
    episode_id = await planned(house)
    view = house.episodes.view(episode_id)
    assert view["working"] is None, "nothing is under way once the plan is written"
    thread = view["thread_id"]
    unit = next(u for u in view["units"] if u["kind"] == "picture")
    store = house.store
    plan = store.add_run(
        thread_id=thread, lane="plan", harness="kimi", prompt="Stage: script.", session=""
    )
    events = [{"kind": "step", "text": f"Reading part {n}.md", "at": 100.0 + n} for n in range(20)]
    events.append({"kind": "note", "text": "I'm building one   continuing diagram.", "at": 130.0})
    store.update_run(str(plan["id"]), steps=events)
    built = store.add_run(
        thread_id=thread,
        lane=f"picture:{unit['id']}",
        harness="kimi",
        prompt="Stage: picture.",
        session="",
    )
    store.update_run(
        str(built["id"]), steps=[{"kind": "step", "text": "Editing compositions/p.html", "at": 1.0}]
    )
    view = house.episodes.view(episode_id)
    working = view["working"]
    assert working["harness"] == "kimi" and working["since"] == plan["started_at"]
    # the newest steps, the writer's own note last, with its words tidied
    assert len(working["events"]) == 14 and working["events"][-1] == {
        "kind": "note",
        "text": "I'm building one continuing diagram.",
        "at": 130.0,
    }
    pictures = {u["id"]: u["picture"] for u in view["units"]}
    assert pictures[unit["id"]]["doing"] == "Editing compositions/p.html"
    assert all(p["doing"] == "" for i, p in pictures.items() if i != unit["id"])
    # the picture being built streams its builder's turn as the plan does, its steps and notes
    assert pictures[unit["id"]]["live"] == {
        "harness": "kimi",
        "since": built["started_at"],
        # Kimi Code says nothing while it thinks, and nothing has been heard between steps
        "tells": False,
        "pulse": None,
        "events": [{"kind": "step", "text": "Editing compositions/p.html", "at": 1.0}],
    }
    assert all(p["live"] is None for i, p in pictures.items() if i != unit["id"])
    # between two steps: what the builder's model is doing now, and a stretch of thinking that
    # ended, which is a line of its turn and never the step it is on
    store.pulse(str(built["id"]), f"picture:{unit['id']}", "thinking", "Which way round?", 300)
    thought = {"kind": "thought", "text": "The cache box first.", "at": 2.0, "seconds": 41.5}
    store.update_run(str(built["id"]), steps=[*store.run(str(built["id"]))["steps"], thought])
    live = house.episodes.view(episode_id)["units"]
    live = next(u["picture"] for u in live if u["id"] == unit["id"])
    assert live["doing"] == "Editing compositions/p.html"
    assert live["live"]["events"][-1] == thought
    pulse = live["live"]["pulse"]
    assert (pulse["doing"], pulse["text"], pulse["amount"]) == ("thinking", "Which way round?", 300)
    assert pulse["since"] == pulse["at"] and "lane" not in pulse
    # Claude Code is one that says what its model is doing as it goes
    told = store.add_run(thread_id=thread, lane="plan", harness="claude", prompt="p", session="")
    assert house.episodes.view(episode_id)["working"]["tells"] is True
    store.update_run(str(told["id"]), state="done")
    store.pulses.clear()
    # a turn that ends is no longer under way
    store.update_run(str(plan["id"]), state="done")
    store.update_run(str(built["id"]), state="done")
    view = house.episodes.view(episode_id)
    assert view["working"] is None
    assert all(u["picture"]["doing"] == "" and u["picture"]["live"] is None for u in view["units"])


async def test_the_demos_writer_keeps_each_turn_in_the_record_as_a_writer_does(
    house: AgentHost, tmp_path: Path
) -> None:
    house.episodes.workers[DEMO] = DemoWorker(
        data_dir=tmp_path, script=SCRIPT, pause=0, store=house.store
    )
    episode_id = await planned(house)
    thread = house.episodes.view(episode_id)["thread_id"]
    turns = house.store.runs(thread, lane="plan")
    assert turns and all(t["state"] == "done" and t["harness"] == DEMO for t in turns)
    kinds = [e["kind"] for t in turns for e in t["steps"]]
    assert "step" in kinds and "note" in kinds
    # it reads, thinks (said to the studio as it goes, kept as one line once it ends), then notes
    first = turns[0]["steps"]
    assert [e["kind"] for e in first[:3]] == ["step", "thought", "note"]
    assert first[0]["text"] == "Reading the material" and "example" in first[1]["text"]
    assert house.episodes.view(episode_id)["working"] is None
    assert house.store.pulses == {}, "a turn that is over has no pulse"


async def test_the_studio_is_told_what_a_turn_is_doing_between_its_steps(
    house: AgentHost, tmp_path: Path
) -> None:
    """A sign of life is its own small event, so a model's long thought costs the studio no
    reading of the whole episode."""
    house.episodes.workers[DEMO] = DemoWorker(
        data_dir=tmp_path, script=SCRIPT, pause=0, store=house.store
    )
    house.hub.bind(asyncio.get_running_loop())
    told = house.hub.open()
    episode_id = await planned(house)
    pulses = []
    while not told.empty():
        event = told.get_nowait()
        if event["type"] == "episode.pulse":
            pulses.append(event)
    house.hub.close(told)
    assert pulses and all(e["id"] == episode_id for e in pulses)
    thinking = [e["pulse"] for e in pulses if e["pulse"]["doing"] == "thinking"]
    assert thinking and all(p["lane"] == "plan" and p["text"] for p in thinking)
    # the thought grows as it is thought
    assert len(thinking[0]["text"]) < len(thinking[-1]["text"]) or len(thinking) == 1


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
        lambda episode, take_id, name, source: {
            "uhd": "",
            "video": "",
            "audio": "",
            "seconds": 30.0,
        },
    )
    view = house.episodes.view(episode_id)
    chapter = view["plan"]["chapters"][0]
    lines = [f["id"] for b in chapter["beats"] for f in b["frames"]]
    marks = [{"frame": frame, "t": 3.0 * i} for i, frame in enumerate(lines)]
    take_id = chapter["id"]
    view = await house.episodes.add_take(
        episode_id,
        by="you",
        chapter=take_id,
        marks=marks,
        name="take.webm",
        source=io.BytesIO(b"webm"),
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
        episode_id, by="you", chapter=take_id, name="take.mp4", source=io.BytesIO(b"mp4")
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
            episode_id, by="you", chapter="c99", name="take.webm", source=io.BytesIO(b"x")
        )
    with pytest.raises(ValueError, match="empty"):
        await house.episodes.add_take(
            episode_id, by="you", chapter=take_id, name="take.webm", source=io.BytesIO(b"")
        )


async def test_a_takes_recording_is_kept_as_it_arrived_and_the_take_stands_without_it(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    from design_agent.tools import footage

    episode_id = await planned(house)
    monkeypatch.setattr(
        house.episodes,
        "_cut",
        lambda episode, take_id, name, source: {
            "uhd": "",
            "video": "",
            "audio": "",
            "seconds": 30.0,
        },
    )
    chapter = house.episodes.view(episode_id)["plan"]["chapters"][0]["id"]
    kept: list[tuple[str, bytes, str]] = []

    def put(self: footage.Bucket, key: str, source: Any, *, name: str = "") -> str:
        source.seek(0)
        kept.append((key, source.read(), name))
        return f"s3://{self.name}/{key}"

    def raw(take_id: str) -> str:
        row = house.store.take(take_id)
        assert row is not None
        return str(row["raw"])

    async def take(name: str, recording: bytes) -> dict[str, Any]:
        view = await house.episodes.add_take(
            episode_id, by="you", chapter=chapter, name=name, source=io.BytesIO(recording)
        )
        return dict(view["takes"][-1], thread_id=view["thread_id"])

    monkeypatch.setattr(footage.Bucket, "put", put)
    # with no bucket it is kept in the house's own footage folder, under its take's name
    first = await take("take.webm", b"one")
    folder = house.episodes.data_dir / "footage" / episode_id
    assert raw(first["id"]) == str(folder / f"{first['id']}-take.webm") and not kept
    assert Path(raw(first["id"])).read_bytes() == b"one" and first["kept_at"] == raw(first["id"])
    # or on a drive of its own, under its own name too
    drive = house.episodes.data_dir.parent / "ssd"
    house.settings = house.settings.model_copy(update={"footage_dir": drive})
    second = await take("C0002.MP4", b"two")
    assert raw(second["id"]) == str(drive / episode_id / f"{second['id']}-C0002.mp4")
    # a drive that isn't there does not lose the take: it stands, and the thread says so
    house.settings = house.settings.model_copy(update={"footage_dir": Path("/dev/null/ssd")})
    unplugged = await take("C0003.MP4", b"three")
    assert unplugged["kept"] and raw(unplugged["id"]) == ""
    said = [row["text"] for row in house.store.activity(unplugged["thread_id"])]
    assert any("was not kept in /dev/null/ssd" in text for text in said)
    house.settings = house.settings.model_copy(update={"footage_bucket": "footage"})
    second = await take("C0001.MP4", b"a camera's own")
    address = f"episodes/{episode_id}/takes/{second['id']}.mp4"
    assert kept == [(address, b"a camera's own", "C0001.MP4")]
    assert raw(second["id"]) == f"s3://footage/{address}"

    # a store that is down does not lose the take: it stands, and the thread says so
    def down(self: footage.Bucket, key: str, source: Any, *, name: str = "") -> str:
        raise footage.FootageError("EndpointConnectionError: Could not connect")

    monkeypatch.setattr(footage.Bucket, "put", down)
    third = await take("take.webm", b"three")
    assert third["kept"] and raw(third["id"]) == ""
    said = [row["text"] for row in house.store.activity(third["thread_id"])]
    assert any(
        "was not kept in the bucket" in text and "Could not connect" in text for text in said
    )


def test_a_takes_sound_is_set_to_the_films_loudness_by_one_gain() -> None:
    from design_agent.surfaces.web.episode_desk import _levelled

    def summary(loud: str, peak: str) -> str:
        return f"Integrated loudness:\n    I:   {loud} LUFS\n  True peak:\n    Peak:  {peak} dBFS\n"

    # quiet, with room above its peaks: turned up, nothing held
    assert _levelled(summary("-24.0", "-12.0")) == "volume=8.0dB"
    # quiet, but its peaks would pass the ceiling: turned up, and only the peaks held
    assert _levelled(summary("-33.8", "-17.0")) == (
        "volume=17.8dB,alimiter=limit=0.841:level=false:latency=true"
    )
    assert _levelled(summary("-9.0", "0.0")).startswith("volume=-7.0dB")
    # already there: left as it is
    assert _levelled(summary("-16.2", "-3.0")) == ""
    # silence has no voice to bring up, and a summary that can't be read changes nothing
    assert _levelled(summary("-70.0", "-inf")) == ""
    assert _levelled("ffmpeg: no such file") == ""
    # never more than the most gain, however quiet
    assert _levelled(summary("-48.0", "-30.0")).startswith("volume=24.0dB")


class CutComputer:
    """The thread's computer as a cut sees it: what ffprobe finds, ffmpeg's loudness, and a
    cut that ends at once with the copies it was asked for."""

    loud = "Integrated loudness:\n    I:   -30.0 LUFS\n  True peak:\n    Peak:  -20.0 dBFS\n"

    def __init__(self, streams: list[dict[str, Any]], zscale: int = 1) -> None:
        self.streams, self.zscale = streams, zscale
        self.put_at, self.sent, self.cut = "", b"", ""
        self.ran: list[str] = []
        self.runs = "12.5"

    def put_stream(self, path: str, source: Any, *, progress: Any = None) -> None:
        source.seek(0)
        self.put_at, self.sent = path, source.read()
        if progress is not None:
            progress(len(self.sent))

    def run(self, command: str, *, timeout: int = 600) -> Any:
        from design_agent.surfaces.web.computer import Ran

        self.ran.append(command)
        take = Path(self.put_at).name.split(".src.")[0]
        if "-show_entries stream=" in command:
            listed = json.dumps(
                {"streams": self.streams, "format": {"duration": "12.5"}}, separators=(",", ":")
            )
            return Ran(f"streams: {listed}\nzscale: {self.zscale}\n", 0)
        if "ebur128" in command:
            return Ran(self.loud, 0)
        if "nohup" in command:
            words = shlex.split(command)
            self.cut = words[words.index("-c") + 1]
            return Ran("", 0)
        if "exit: $(cat" in command:
            return Ran("exit: 0\nout_time_us=12500000\n", 0)
        if "format=duration" in command:
            made = [f"{take}.m4a {self.runs}"]
            if '"[hd]"' in self.cut:
                made.append(f"{take}.mp4 {self.runs}")
            if '"[uhd]"' in self.cut:
                made.append(f"{take}.uhd.mp4 {self.runs}")
            return Ran("\n".join(made) + "\n", 0)
        return Ran("", 0)

    def get_into(self, path: str, target: Any, *, timeout: int = 0) -> None:
        target.write(f"copy {Path(path).name}".encode())


async def test_a_recording_is_cut_for_what_is_in_it(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode_id = await planned(house)
    episode = house.store.episode(episode_id)
    assert episode is not None
    monkeypatch.setattr("design_agent.surfaces.web.episode_desk.time.sleep", lambda _s: None)

    def cut(computer: CutComputer, name: str, take_id: str = "tk_1") -> tuple[str, dict[str, Any]]:
        monkeypatch.setattr(house.episodes, "_computer", lambda episode: computer)
        made = house.episodes._cut(episode, take_id, name, io.BytesIO(b"recording"))
        assert made["seconds"] == 12.5 and made["audio"] and computer.sent == b"recording"
        return computer.cut, made

    # an iPhone's file: brought down to the film's range of light, size and rate, its sound up
    phone = CutComputer(
        [
            {"codec_type": "video", "color_transfer": "arib-std-b67", "height": 1080},
            {"codec_type": "audio", "channels": 2},
        ]
    )
    command, made = cut(phone, "IMG_0042.MOV")
    assert phone.put_at.endswith("/takes/tk_1.src.mov")
    assert "fps=30,scale=-2:'min(1080,ih)':flags=lanczos,zscale=t=linear" in command
    assert "-color_trc bt709" in command and "[0:a:0]volume=14.0dB[said]" in command
    assert "-ac 2" not in command and "-crf 18" in command and "[uhd]" not in command
    assert made["video"] and not made["uhd"]
    # without the filter for it (this machine's own ffmpeg), the picture is cut as it is
    assert "zscale" not in cut(CutComputer(phone.streams, zscale=0), "clip.mov", "tk_2")[0]
    # a camera's 4K: read once for both copies, the film's and one no taller than 2160, tagged
    # in the film's colours; its four inputs mixed to two
    camera = CutComputer(
        [
            {
                "codec_type": "video",
                "color_transfer": "bt709",
                "color_space": "bt709",
                "height": 2160,
                "avg_frame_rate": "30000/1001",
            },
            {"codec_type": "audio", "channels": 4},
        ]
    )
    command, made = cut(camera, "C0012.MP4", "tk_3")
    assert "fps=30,split=2[a][b];[a]scale=-2:'min(1080,ih)'" in command
    assert "[b]scale=-2:'min(2160,ih)':flags=lanczos[uhd]" in command
    assert '-map "[uhd]" -an' in command and "-colorspace bt709" in command and "-ac 2 " in command
    names = {kind: house.store.file(made[kind])["name"] for kind in ("video", "uhd", "audio")}
    assert names == {"video": "tk_3.mp4", "uhd": "tk_3-2160.mp4", "audio": "tk_3.m4a"}
    kept = house.store.file(made["uhd"])
    assert (house.files_dir / kept["rel_path"]).read_bytes() == b"copy tk_3.uhd.mp4"
    # sound alone
    command, made = cut(CutComputer([{"codec_type": "audio", "channels": 1}]), "memo.m4a", "tk_4")
    assert " -vn " in command and "libx264" not in command and not made["video"]
    # the file's name is the person's: nothing of it but letters and digits reaches a command
    sly = CutComputer([{"codec_type": "audio", "channels": 1}])
    cut(sly, "take.$(touch x);rm -rf", "tk_5")
    assert sly.put_at.endswith(".src.touch")
    assert "touch x" not in " ".join(sly.ran) and "rm -rf" not in " ".join(sly.ran)


class MatchComputer(CutComputer):
    """The thread's computer bringing a camera's clip in: the sound of the take and of the clip
    as loudness curves, and copies that stay on it between renders."""

    def __init__(self, streams: list[dict[str, Any]], curves: dict[str, list[float]]) -> None:
        super().__init__(streams)
        self.curves = curves
        self.puts: list[str] = []

    def put_stream(self, path: str, source: Any, *, progress: Any = None) -> None:
        self.puts.append(path)
        if ".src." in path:
            super().put_stream(path, source, progress=progress)

    def get(self, path: str) -> bytes | None:
        import array

        for ending, curve in self.curves.items():
            if path.endswith(ending):
                return array.array("f", curve).tobytes()
        return None


async def a_take_to_match(house: AgentHost, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Any]:
    """An episode with a take recorded in the studio: a minute of it, a line every 5 s."""
    episode_id = await planned(house)
    view = house.episodes.view(episode_id)
    chapter = view["plan"]["chapters"][0]
    lines = [f["id"] for b in chapter["beats"] for f in b["frames"]]
    sound = house.save_file(view["thread_id"], "take.m4a", b"m4a", origin="episode")["id"]
    monkeypatch.setattr(
        house.episodes,
        "_cut",
        lambda episode, take_id, name, source: {
            "uhd": "",
            "video": "",
            "audio": sound,
            "seconds": 60.0,
        },
    )
    marks = [{"frame": frame, "t": 5.0 * i} for i, frame in enumerate(lines)]
    view = await house.episodes.add_take(
        episode_id,
        by="you",
        chapter=chapter["id"],
        marks=marks,
        name="take.webm",
        source=io.BytesIO(b"webm"),
    )
    monkeypatch.setattr("design_agent.surfaces.web.episode_desk.time.sleep", lambda _s: None)
    return episode_id, view["takes"][0]


CAMERA_4K = [
    {"codec_type": "video", "color_space": "bt709", "height": 2160, "avg_frame_rate": "25/1"},
    {"codec_type": "audio", "channels": 2},
]


async def test_a_cameras_clip_is_matched_to_the_take_recorded_with_it(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tests.unit.test_episode_sync import heard, speech

    episode_id, guide = await a_take_to_match(house, monkeypatch)
    said = speech(60, seed=31)
    rolling = heard(speech(17, seed=32) + said + speech(25, seed=33), gain=1.4, seed=34)
    computer = MatchComputer(CAMERA_4K, {".take.env": said, ".camera.env": rolling})
    computer.runs = "60.0"
    monkeypatch.setattr(house.episodes, "_computer", lambda episode: computer)
    clip = tmp_path / "C0012.MP4"
    clip.write_bytes(b"a camera's own")
    view = house.episodes.bring_take(
        episode_id,
        by="you",
        chapter=guide["chapter"],
        name="C0012.MP4",
        source=clip,
        staged=False,
        guide=guide["id"],
        clip={"recorded_at": 1763600000.0, "look": "s-log3-cine"},
    )
    assert [(i["chapter"], i["state"], i["guide"]) for i in view["imports"]] == [
        (guide["chapter"], "copying", guide["id"])
    ]
    await settle(lambda: not house.episodes._busy(episode_id))
    view = house.episodes.view(episode_id)
    assert view["imports"] == []
    studio, camera = view["takes"]
    assert camera["kept"] and not studio["kept"] and camera["uhd"]
    # the copies start where the studio's take began, so its marks are the clip's
    assert camera["marks"] == guide["marks"] and camera["seconds"] == 60.0
    found = camera["recording"]["matched"]
    assert found["take"] == guide["id"] and found["start"] == pytest.approx(17.0, abs=0.02)
    assert "-ss 17.0" in computer.cut and "-t 60.0" in computer.cut
    # what the house noticed: a PAL rate, and a log picture
    note = camera["recording"]["note"]
    assert "25 fps" in note and "NTSC" in note and "S-Log3" in note
    assert camera["recording"]["kind"] == "camera" and camera["recording"]["at"] == 1763600000.0
    # the take's own sound was sent to the computer to be heard, and the clip read from the card
    assert any(p.endswith(f"/takes/{guide['id']}.m4a") for p in computer.puts)
    assert clip.read_bytes() == b"a camera's own"
    assert Path(camera["kept_at"]).read_bytes() == b"a camera's own"
    # and the studio's take is one press away
    view = house.episodes.keep_take(episode_id, guide["id"], keep=True)
    assert [t["kept"] for t in view["takes"]] == [True, False]


async def test_a_clip_unlike_its_take_is_refused_and_the_take_stays(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_episode_sync import heard, speech

    episode_id, guide = await a_take_to_match(house, monkeypatch)
    other = heard(speech(90, seed=40), gain=1.0, seed=41)
    computer = MatchComputer(CAMERA_4K, {".take.env": speech(60, seed=31), ".camera.env": other})
    monkeypatch.setattr(house.episodes, "_computer", lambda episode: computer)
    # an upload, the house's own copy of it
    staged = house.episodes.data_dir / "incoming" / "upload.mp4"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"someone else's")
    chapter = guide["chapter"]
    view = house.episodes.bring_take(
        episode_id,
        by="you",
        chapter=chapter,
        name="C0013.MP4",
        source=staged,
        staged=True,
        guide=guide["id"],
    )
    with pytest.raises(ValueError, match="already coming in"):
        house.episodes.bring_take(
            episode_id,
            by="you",
            chapter=chapter,
            name="C0013.MP4",
            source=staged,
            staged=True,
        )
    await settle(lambda: not house.episodes._busy(episode_id))
    view = house.episodes.view(episode_id)
    (refused,) = view["imports"]
    assert refused["state"] == "failed" and "doesn't sound like this take" in refused["failure"]
    assert [t["kept"] for t in view["takes"]] == [True] and not staged.exists()
    took = refused["take"]
    forgot = next(c for c in computer.ran if f"rm -f {took}.*" in c)
    # stopped by the process it runs as: a name to match would be in this very command
    assert f"cd /workspace/projects/{episode_id}/takes" in forgot and "pkill -f" not in forgot
    assert not any((house.episodes.data_dir / "footage").glob(f"*/{took}-*"))
    # put away, and a take that isn't there can't be a guide
    assert house.episodes.forget_import(episode_id, chapter)["imports"] == []
    with pytest.raises(KeyError):
        house.episodes.bring_take(
            episode_id,
            by="you",
            chapter=chapter,
            name="x.mp4",
            source=staged,
            staged=True,
            guide="tk_missing",
        )


async def test_a_recording_half_brought_in_when_the_house_stops_is_brought_in_again(
    house: AgentHost,
) -> None:
    episode_id = await planned(house)
    chapter = house.episodes.view(episode_id)["plan"]["chapters"][0]["id"]
    house.store.update_episode(
        episode_id, imports={chapter: {"state": "cutting", "name": "C0012.MP4", "take": "tk_9"}}
    )
    house.episodes.restore()
    (stopped,) = house.episodes.view(episode_id)["imports"]
    assert stopped["state"] == "failed" and "Bring it in again" in stopped["failure"]


async def test_a_film_in_4k_is_rendered_from_each_takes_copy_for_4k(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    from design_agent.surfaces.web.computer import Ran

    episode_id = await planned(house)
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    view = house.episodes.view(episode_id)
    chapters = [c["id"] for c in view["plan"]["chapters"][:2]]

    def saved(name: str) -> str:
        return str(house.save_file(view["thread_id"], name, name.encode(), origin="episode")["id"])

    camera = house.store.add_take(
        {
            "episode_id": episode_id,
            "chapter": chapters[0],
            "frame": "",
            "seconds": 10.0,
            "marks": [],
            "video": saved("a.mp4"),
            "audio": saved("a.m4a"),
            "uhd": saved("a-2160.mp4"),
            "kept": True,
            "added_by": "you",
        }
    )
    studio = house.store.add_take(
        {
            "episode_id": episode_id,
            "chapter": chapters[1],
            "frame": "",
            "seconds": 10.0,
            "marks": [],
            "video": saved("b.mp4"),
            "audio": saved("b.m4a"),
            "kept": True,
            "added_by": "you",
        }
    )

    class Computer:
        free = "999999999\n999999999\n"

        def __init__(self) -> None:
            self.ran: list[str] = []
            self.sent: list[str] = []

        def put(self, files: list[tuple[str, bytes]]) -> None:
            pass

        def put_stream(self, path: str, source: Any, *, progress: Any = None) -> None:
            self.sent.append(path)

        def run(self, command: str, *, timeout: int = 600) -> Ran:
            self.ran.append(command)
            if command.startswith("df "):
                return Ran(self.free, 0)
            if "render.exit" in command and "cat" in command:
                return Ran('0\n@hf-progress {"code":"encode","done":9,"total":10,"pct":90}', 0)
            return Ran("", 0)

        def get(self, path: str) -> bytes | None:
            return None

        def get_into(self, path: str, target: Any, *, timeout: int = 0) -> None:
            target.write(b"a film in 4K")

    computer = Computer()
    monkeypatch.setattr(house.episodes, "_computer", lambda episode: computer)
    monkeypatch.setattr("design_agent.surfaces.web.episode_desk.time.sleep", lambda _s: None)
    with pytest.raises(ValueError, match="HD or in 4K"):
        house.episodes.render(episode_id, by="you", size="8k")
    view = house.episodes.render(episode_id, by="you", size="4k")
    assert view["film_state"]["making"] == "4k"
    await settle(lambda: not house.episodes._busy(episode_id))
    film_state = house.episodes.view(episode_id)["film_state"]
    assert film_state["status"] == "done", film_state.get("failure")
    assert (film_state["size"], film_state["upscaled"]) == ("4k", 1)
    launched = next(c for c in computer.ran if "hyperframes render" in c)
    assert "--resolution 4k" in launched
    linked = next(c for c in computer.ran if "ln -f" in c)
    takes = f"/workspace/projects/{episode_id}/takes"
    assert f"ln -f {takes}/{camera['id']}.uhd.mp4 " in linked
    assert f"/takes/{camera['id']}.mp4 2>/dev/null" in linked
    # a take recorded no taller than the film is its own copy, scaled up by the render
    assert f"ln -f {takes}/{studio['id']}.mp4 " in linked
    # copies the computer doesn't have whole are sent from the house's files, once
    assert f"{takes}/{camera['id']}.uhd.mp4" in computer.sent
    assert f"{takes}/{camera['id']}.mp4" not in computer.sent
    # asked again with no size, it is the size asked for last; and it needs room to render in
    computer.free = "1024\n1024\n"
    house.episodes.render(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    failed = house.episodes.view(episode_id)["film_state"]
    assert failed["status"] == "failed" and "in 4K needs about" in failed["failure"]
    assert failed["file"]["name"].endswith(".mp4")
    # a take that is deleted takes its copies with it
    view = house.episodes.keep_take(episode_id, camera["id"], keep=False)
    assert house.store.file(camera["uhd"]) is None and house.store.file(camera["video"]) is None
    await settle(lambda: any(f"rm -f {camera['id']}.*" in c for c in computer.ran))


async def test_export_waits_for_picture_builds_and_rejects_empty_drafts(house: AgentHost) -> None:
    episode_id = await planned(house)
    house.episodes.approve(episode_id, by="you")
    with pytest.raises(ValueError, match="Wait for pictures"):
        house.episodes.render(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    for row in house.store.pictures(episode_id):
        house.store.set_picture(episode_id, row["unit"], status="failed")
    with pytest.raises(ValueError, match="Make a picture or record a chapter first"):
        house.episodes.render(episode_id, by="you")


@pytest.mark.parametrize("picture_changes_during_export", [False, True])
async def test_the_film_is_rendered_from_the_plan_the_pictures_and_the_takes(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch, picture_changes_during_export: bool
) -> None:
    episode_id = await planned(house)
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    projects: list[dict[str, bytes]] = []

    class Computer:
        def get_into(self, path: str, target: Any, *, timeout: int = 0) -> None:
            content = self.get(path)
            if not content:
                raise FileNotFoundError(path)
            target.write(content)

        def put(self, files: list[tuple[str, bytes]]) -> None:
            projects.append(dict(files))
            if picture_changes_during_export:
                row = house.store.pictures(episode_id)[0]
                house.store.set_picture(
                    episode_id, row["unit"], html=row["html"] + "<!-- revised -->"
                )

        def run(self, command: str, *, timeout: int = 600) -> Any:
            from design_agent.surfaces.web.computer import Ran

            if "render.exit" in command and "cat" in command:
                return Ran('0\n@hf-progress {"code":"encode","done":9,"total":10,"pct":90}', 0)
            return Ran("0 errors, 0 warnings", 0)

        def get(self, path: str) -> bytes | None:
            if path.endswith("poster.jpg") and not picture_changes_during_export:
                return b"poster"
            return b"mp4" if path.endswith("episode.mp4") else None

    monkeypatch.setattr(house.episodes, "_computer", lambda episode: Computer())
    monkeypatch.setattr("design_agent.surfaces.web.episode_desk.time.sleep", lambda _s: None)
    house.episodes.render(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    view = house.episodes.view(episode_id)
    film = view["film_state"]
    assert (
        film["status"] == "done"
        and film["stale"] == picture_changes_during_export
        and film["file"]["name"] == "one-idea.mp4"
    )
    poster = view["film"]["poster"]
    assert poster["mime"] == ("image/png" if picture_changes_during_export else "image/jpeg")
    assert view["film"]["seconds"] == film["seconds"]
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


@pytest.mark.parametrize("mode", ["narrator", "local"])
async def test_a_narrated_film_keeps_its_narration_once_it_is_rendered(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    from pydantic import SecretStr

    from design_agent.surfaces.web.computer import Ran
    from design_agent.tools import media

    house.settings = house.settings.model_copy(
        update={"elevenlabs_api_key": SecretStr("key"), "narrator_voice_id": "voice1234567890"}
    )
    from design_agent.tools import local_speech

    said: list[str] = []
    staged_voice = []

    async def speak(keys: Any, text: str, voice_id: str, **more: Any) -> media.Spoken:
        said.append(text)
        return media.Spoken(b"mp3", 2.0, [])

    class Computer:
        def get_into(self, path: str, target: Any, *, timeout: int = 0) -> None:
            content = self.get(path)
            if not content:
                raise FileNotFoundError(path)
            target.write(content)

        def put(self, files: list[tuple[str, bytes]]) -> None:
            staged_voice.extend(path for path, _ in files if "/voice/" in path)

        def run(self, command: str, *, timeout: int = 600) -> Ran:
            return Ran("0\n" if "render.exit" in command and "cat" in command else "", 0)

        def get(self, path: str) -> bytes | None:
            return b"mp4" if path.endswith("episode.mp4") else None

    def offline(words: str) -> media.Spoken:
        said.append(words)
        return media.Spoken(b"wave", 2.0, [])

    monkeypatch.setattr(local_speech, "engine", lambda: "say")
    monkeypatch.setattr(local_speech, "synthesize", offline)
    monkeypatch.setattr(media, "speak", speak)
    monkeypatch.setattr(house.episodes, "_computer", lambda episode: Computer())
    monkeypatch.setattr("design_agent.surfaces.web.episode_desk.time.sleep", lambda _s: None)
    episode_id = await planned(house, presenter="off", voice=mode)
    house.episodes.approve(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    house.episodes.render(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    view = house.episodes.view(episode_id)
    lines = view["clock"]["lines"]
    assert view["film_state"]["status"] == "done" and len(said) == len(lines)
    assert staged_voice and all(
        p.endswith(".wav" if mode == "local" else ".mp3") for p in staged_voice
    )
    # the film just rendered is the film as it stands: its lines are still the spoken ones
    assert {line["source"]["kind"] for line in lines} == {"voice"}
    assert not view["film_state"]["stale"]
    assert view["film_state"]["seconds"] == pytest.approx(view["clock"]["total"])
    # and rendering it again speaks nothing a second time
    house.episodes.render(episode_id, by="you")
    await settle(lambda: not house.episodes._busy(episode_id))
    assert len(said) == len(lines)


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


async def test_codex_brief_receives_the_saved_source_and_plan_format(tmp_path: Path) -> None:
    runner = Runner([[Event("answer", "Done.")]])
    worker, _, episode = local(tmp_path, runner, "codex")
    episode["material"] = "Index only the events needed for future queries."
    await worker.turn(episode, lane="plan", prompt="Stage: brief.", heard=lambda *_: None)
    prompt = runner.calls[0]["prompt"]
    assert episode["material"] in prompt and '"says"' in prompt
    assert "untrusted source" in prompt.lower()


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


async def test_a_turn_says_what_its_model_is_doing_between_its_steps(tmp_path: Path) -> None:
    """A pulse is kept in memory for the studio and never in the record; a long stretch of
    thinking is a line of the record with how long it took, a short one is not."""
    seen: list[dict[str, Any]] = []
    worker: LocalWorker
    store: Store

    def heard(kind: str, text: str) -> None:
        if kind == "pulse":
            seen.append(dict(store.pulses[text]))

    runner = Runner(
        [
            [
                Event("pulse", "thinking", detail="Which example carries it?", amount=400),
                Event("thought", "Which example carries it?", amount=2100, seconds=95.0),
                Event("thought", "A glance.", amount=40, seconds=1.2),
                Event("pulse", "step", detail="Writing plan.json", amount=1200),
                Event("step", "Writing plan.json"),
                Event("answer", "Done."),
            ]
        ]
    )
    worker, store, episode = local(tmp_path, runner)
    await worker.turn(episode, lane="plan", prompt="Stage: brief.", heard=heard)
    assert [(p["lane"], p["doing"], p["text"], p["amount"]) for p in seen] == [
        ("plan", "thinking", "Which example carries it?", 400),
        ("plan", "", "", 0),  # the short thought ended: nothing known until the next sign
        ("plan", "step", "Writing plan.json", 1200),
    ]
    run = store.runs("th_1", "plan")[0]
    assert [(s["kind"], s["text"], s.get("seconds")) for s in run["steps"]] == [
        ("thought", "Which example carries it?", 95.0),
        ("step", "Writing plan.json", None),
    ]
    assert run["steps"][0]["tokens"] == 2100 and store.pulses == {}


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
        assert {w["id"] for w in options["writers"]} == {DEMO, "claude", "codex", "kimi"}
        assert options["reader"] == "demo"
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
        unit_chapter = view["units"][0]["chapter"]
        regen = f"/api/episodes/{episode_id}/chapters/{unit_chapter}/regenerate"
        assert client.post(regen, json={"provider": "unknown"}).status_code == 422
        assert client.post(regen, json={"model": "gpt-6.1-sol"}).status_code == 422
        no_chapter = client.post(f"/api/episodes/{episode_id}/chapters/missing/regenerate", json={})
        assert no_chapter.status_code == 422 and "chapter has no visuals" in no_chapter.text
        assert client.post(f"/api/episodes/{episode_id}/stop").json() == {"ok": True}
        # nothing waits to be applied while no picture was asked for
        nothing = client.post(f"/api/episodes/{episode_id}/apply")
        assert nothing.status_code == 422 and "up to date" in nothing.text
        assert client.post("/api/episodes/ep_missing/apply").status_code == 404
        # a picture is asked for by name and stopped by name; who builds it must be ready here
        unit = view["units"][0]["id"]
        named = client.post(f"/api/episodes/{episode_id}/pictures", json={"units": ["nope"]})
        assert named.status_code == 422 and "no picture to make there" in named.text
        # a picture is made again only as simple or rich
        odd = client.post(
            f"/api/episodes/{episode_id}/pictures", json={"units": [unit], "level": "fancy"}
        )
        assert odd.status_code == 422
        assert client.post(f"/api/episodes/{episode_id}/stop", json={"unit": unit}).json() == {
            "ok": True
        }
        for builder, status in (("kimi", 422), ("gpt", 422), (DEMO, 200), (None, 200)):
            picked = client.post(
                f"/api/episodes/{episode_id}/choices", json={"units": {unit: {"builder": builder}}}
            )
            assert picked.status_code == status, picked.text
        chosen = client.post(
            f"/api/episodes/{episode_id}/choices", json={"settings": {"level": "rich"}}
        )
        assert chosen.status_code == 200 and chosen.json()["settings"]["level"] == "rich"
        bad = client.post(
            f"/api/episodes/{episode_id}/choices", json={"settings": {"level": "ornate"}}
        )
        assert bad.status_code == 422
        # a line added and cut by hand, each a change of its own
        added = client.post(
            f"/api/episodes/{episode_id}/lines",
            json={"after": line_id, "text": "Said to you.", "kind": "camera"},
        )
        assert added.status_code == 200, added.text
        new_line = added.json()["last_change"]["added"][0]
        for body in ({"after": line_id, "text": "Hi.", "kind": "table"}, {"after": line_id}):
            assert client.post(f"/api/episodes/{episode_id}/lines", json=body).status_code == 422
        assert (
            client.post("/api/episodes/ep_missing/lines", json={"after": line_id, "text": "Hi."})
        ).status_code == 404
        cut = client.post(f"/api/episodes/{episode_id}/cut", json={"frames": [new_line]})
        assert cut.status_code == 200 and new_line not in {
            f["id"]
            for ch in cut.json()["plan"]["chapters"]
            for b in ch["beats"]
            for f in b["frames"]
        }
        gone = client.post(f"/api/episodes/{episode_id}/cut", json={"frames": ["c9.b9.f9"]})
        assert gone.status_code == 422 and "not in the plan" in gone.text
        assert (
            client.post(f"/api/episodes/{episode_id}/cut", json={"frames": []}).status_code == 422
        )
        for _ in range(2):  # the cut, then the line, taken back
            assert client.post(f"/api/episodes/{episode_id}/undo").status_code == 200
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


def test_a_take_is_read_from_disk_and_a_voice_needs_a_key_and_a_yes(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, workspace_root=tmp_path / "workspace", sandbox="host")
    with TestClient(create_app(ROOT, settings, demo=True)) as client:
        channel = client.get("/api/channels").json()[0]["id"]
        made = client.post(
            f"/api/channels/{channel}/episodes",
            json={"title": "One idea", "text": NOTES, "settings": {"writer": DEMO}},
        )
        episode_id = made.json()["id"]
        until = time.time() + 30
        while time.time() < until:
            view = client.get(f"/api/episodes/{episode_id}").json()
            if view["status"] != "planning":
                break
            time.sleep(0.05)
        chapter = view["plan"]["chapters"][0]["id"]
        lines = [f["id"] for b in view["plan"]["chapters"][0]["beats"] for f in b["frames"]]
        desk = client.app.state.host.episodes  # type: ignore[attr-defined]
        got: dict[str, Any] = {}

        def cut(episode: Any, take_id: str, name: str, source: Any) -> dict[str, Any]:
            source.seek(0)
            got.update(name=name, data=source.read())
            return {"video": "", "audio": "", "uhd": "", "seconds": 20.0}

        desk._cut = cut
        url = f"/api/episodes/{episode_id}/takes"
        # larger than a form part is kept in memory, so it is read back from the disk
        recording = b"\x1aE\xdf\xa3" + b"0" * (2 * 1024 * 1024)
        sent = client.post(
            url,
            data={
                "chapter": chapter,
                "marks": json.dumps([{"frame": lines[0], "t": 0}]),
                "label": "Clear delivery",
                "started_at": "1763600000.5",
            },
            files={"file": ("take.webm", recording, "video/webm")},
        )
        assert sent.status_code == 200, sent.text
        studio = sent.json()["takes"][0]
        assert studio["seconds"] == 20.0 and studio["label"] == "Clear delivery"
        assert studio["recording"] == {"kind": "studio", "name": "take.webm", "at": 1763600000.5}
        assert got == {"name": "take.webm", "data": recording}

        # a file brought with no marks comes in while the studio goes on: from the house's own
        # copy of it, which is moved to where footage is kept once it is in
        def cut_in(episode: Any, take_id: str, name: str, source: Path, *more: Any) -> Any:
            got.update(staged=source.read_bytes())
            return episode_desk.Brought(None, "", take_id, "")  # type: ignore[arg-type]

        def cut_out(episode: Any, brought: Any, tell: Any = None) -> dict[str, Any]:
            return {"video": "", "audio": "", "uhd": "", "seconds": 30.0}

        desk._cut_in, desk._cut_out = cut_in, cut_out
        brought = client.post(
            url, data={"chapter": chapter}, files={"file": ("C0001.MP4", recording, "video/mp4")}
        )
        assert brought.status_code == 200, brought.text
        assert [i["chapter"] for i in brought.json()["imports"]] == [chapter]
        until = time.time() + 10
        while time.time() < until:
            view = client.get(f"/api/episodes/{episode_id}").json()
            if not view["imports"]:
                break
            time.sleep(0.05)
        camera = view["takes"][-1]
        assert len(view["takes"]) == 2 and camera["kept"] and camera["seconds"] == 30.0
        assert [m["frame"] for m in camera["marks"]] == lines
        assert camera["recording"]["kind"] == "file" and got["staged"] == recording
        assert Path(camera["kept_at"]).read_bytes() == recording
        assert not any((desk.data_dir / "incoming").iterdir())
        clip = {"file": ("a.webm", b"x", "video/webm")}
        assert (
            client.post(url, data={"chapter": chapter, "label": "x" * 121}, files=clip).status_code
            == 422
        )
        assert client.post(url, data={"chapter": chapter}).status_code == 422
        assert client.post(url, data={"chapter": "c99"}, files=clip).status_code == 404
        assert (
            client.post(url, data={"chapter": chapter, "marks": "{}"}, files=clip).status_code
            == 422
        )
        # a recording past the limit is refused by its stated size, before any of it is read
        stated = {
            "content-type": "multipart/form-data; boundary=x",
            "content-length": str(65 * 1024**3),
        }
        assert client.post(url, content=b"", headers=stated).status_code == 413
        # a narrator's voice is an ElevenLabs voice id; the account's voices need its key
        choices = f"/api/episodes/{episode_id}/choices"
        voice = {"id": "voice1234567890", "name": "Ada"}
        picked = client.post(choices, json={"settings": {"narrator": voice}})
        assert picked.status_code == 200 and picked.json()["settings"]["narrator"] == voice
        unchanged = client.post(choices, json={"settings": {"level": "simple"}})
        assert unchanged.json()["settings"]["narrator"] == voice
        reset = client.post(choices, json={"settings": {"narrator": None}})
        assert reset.status_code == 200 and not reset.json()["settings"].get("narrator")
        bad = client.post(choices, json={"settings": {"narrator": {"id": "a b", "name": "x"}}})
        assert bad.status_code == 422
        assert client.get("/api/voices").status_code == 422
        # a clone is refused without the person's yes, and without ElevenLabs' key
        clone = f"/api/episodes/{episode_id}/voice"
        refused = client.post(clone, data={"name": "My voice", "consent": "true"})
        assert refused.status_code == 422 and "ELEVENLABS_API_KEY" in refused.json()["detail"]
        assert client.post(clone, data={"consent": "true"}).status_code == 422
        assert (
            client.post(
                "/api/episodes/ep_missing/voice", data={"name": "x", "consent": "true"}
            ).status_code
            == 404
        )


def test_a_cards_clips_are_listed_and_only_those_are_brought_in(tmp_path: Path) -> None:
    from tests.unit.test_web_camera import movie

    card = tmp_path / "Volumes" / "UNTITLED" / "PRIVATE" / "M4ROOT" / "CLIP"
    card.mkdir(parents=True)
    (card / "C0001.MP4").write_bytes(movie(42.0, time.time() - 60))
    elsewhere = tmp_path / "C0002.MP4"
    elsewhere.write_bytes(movie(42.0, time.time()))
    settings = Settings(
        _env_file=None,
        workspace_root=tmp_path / "workspace",
        sandbox="host",
        camera_dirs=str(tmp_path / "Volumes"),
    )
    with TestClient(create_app(ROOT, settings, demo=True)) as client:
        listed = client.get("/api/camera").json()
        assert listed["folders"] == [str(tmp_path / "Volumes")]
        ((clip),) = listed["clips"]
        assert (clip["name"], clip["card"], clip["seconds"]) == ("C0001.MP4", "UNTITLED", 42.0)
        channel = client.get("/api/channels").json()[0]["id"]
        made = client.post(
            f"/api/channels/{channel}/episodes",
            json={"title": "One idea", "text": NOTES, "settings": {"writer": DEMO}},
        )
        episode_id = made.json()["id"]
        until = time.time() + 30
        while time.time() < until:
            view = client.get(f"/api/episodes/{episode_id}").json()
            if view["status"] != "planning":
                break
            time.sleep(0.05)
        chapter = view["plan"]["chapters"][0]["id"]
        desk = client.app.state.host.episodes  # type: ignore[attr-defined]
        held = asyncio.Event()

        async def imported(*given: Any, **more: Any) -> None:
            await held.wait()

        desk._imported = imported
        url = f"/api/episodes/{episode_id}/takes/camera"
        # a path that isn't one of the card's clips is never opened
        for path in (str(elsewhere), "/etc/hosts", str(card / ".." / "C0001.MP4")):
            assert client.post(url, json={"chapter": chapter, "path": path}).status_code == 404
        brought = client.post(url, json={"chapter": chapter, "path": clip["path"]})
        assert brought.status_code == 200, brought.text
        (coming,) = brought.json()["imports"]
        assert (coming["name"], coming["state"], coming["total"]) == (
            "C0001.MP4",
            "copying",
            clip["size"],
        )
        assert client.post(url, json={"chapter": chapter, "path": clip["path"]}).status_code == 422
        assert client.delete(f"/api/episodes/{episode_id}/imports/{chapter}").status_code == 422
        film = f"/api/episodes/{episode_id}/film"
        assert client.post(film, json={"size": "8k"}).status_code == 422


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
    # a recording is copied across from an open file, from its start, wherever it was left
    recording = io.BytesIO(b"a camera's own file")
    recording.seek(0, 2)
    sent: list[int] = []
    computer.put_stream(
        "/workspace/projects/ep_1/takes/take.src.mp4", recording, progress=sent.append
    )
    assert computer.get("/workspace/projects/ep_1/takes/take.src.mp4") == b"a camera's own file"
    assert sent == [len(b"a camera's own file")]
    # and a large file comes out the same way, into an open file, never as bytes in memory
    out = io.BytesIO()
    computer.get_into("/workspace/projects/ep_1/takes/take.src.mp4", out)
    assert out.getvalue() == b"a camera's own file"
    with pytest.raises(FileNotFoundError):
        computer.get_into("/workspace/projects/ep_1/missing", io.BytesIO())


def test_a_recording_reaches_the_container_as_a_file_or_as_bytes(tmp_path: Path) -> None:
    from design_agent.surfaces.web.computer import Computer

    class Runner:
        def __init__(self) -> None:
            self.calls: list[tuple[Any, ...]] = []

        def exec(self, thread_id: str, command: str, **more: Any) -> None:
            self.calls.append(("exec", command))

        def put_file(self, thread_id: str, path: str, source: Any, progress: Any = None) -> None:
            self.calls.append(("file", path, source.read()))
            if progress is not None:
                progress(9)

        def put_archive(self, thread_id: str, archive: bytes, *, root: bool) -> None:
            self.calls.append(("archive", len(archive) > 0))

    class Binding:
        runner = Runner()

    computer = Computer(Binding(), "th_1", tmp_path)  # type: ignore[arg-type]
    # a file on disk is handed to Docker as it is; its bytes are never read here
    on_disk = tmp_path / "C0001.MP4"
    on_disk.write_bytes(b"gigabytes")
    with on_disk.open("rb") as source:
        computer.put_stream("/workspace/projects/ep_1/takes/take.src.mp4", source)
    assert Binding.runner.calls == [
        ("exec", "mkdir -p /workspace/projects/ep_1/takes"),
        ("file", "/workspace/projects/ep_1/takes/take.src.mp4", b"gigabytes"),
    ]
    # and how much has gone is told to whoever is watching
    sent: list[int] = []
    with on_disk.open("rb") as source:
        computer.put_stream(
            "/workspace/projects/ep_1/takes/c.src.mp4", source, progress=sent.append
        )
    assert sent == [9]
    # bytes with no file behind them go the way small files do
    Binding.runner.calls.clear()
    computer.put_stream("/workspace/projects/ep_1/takes/small.src.webm", io.BytesIO(b"small"))
    assert [call[0] for call in Binding.runner.calls] == ["exec", "archive"]


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


async def test_picture_generation_settings_survive_build_and_validate_before_save(
    house: AgentHost,
) -> None:
    eid = await planned(house)
    desk = house.episodes
    unit = desk.view(eid)["units"][0]
    key = unit["id"]

    def pick(**fields: Any) -> Any:
        return desk.choose(eid, by="you", change={"units": {key: fields}})["units"][0]

    listed = pick(component="list", variant="horizontal", direction="Reveal the items in order")
    assert listed["visual"]["variant"] == "horizontal"
    assert listed["visual"]["variant_pick"] == "horizontal"
    assert listed["builder_pick"] is None
    assert not listed["picture"].get("generation")
    with pytest.raises(ValueError):
        pick(component="list", variant="swimlanes")
    with pytest.raises(ValueError):
        pick(model="unavailable-model")
    assert desk.view(eid)["units"][0]["visual"] == listed["visual"]
    with pytest.raises(ValueError, match="live provider"):
        await desk._build(eid, key)
    pick(direction="")
    desk.approve(eid, by="you")
    await settle(lambda: not desk._busy(eid))
    made = desk.view(eid)["units"][0]
    assert made["picture"]["generation"]["provider"] == "Scripted"
    assert made["picture"]["generation"]["model"] == "demo"
    assert 'data-variant="horizontal"' in house.store.picture(eid, key)["html"]
    changed = pick(component="list", variant="vertical")
    assert changed["picture"]["stale"]
    assert changed["picture"]["generation"] == made["picture"]["generation"]


async def test_catalog_choices_can_be_undone_without_mutating_other_units(house: AgentHost) -> None:
    ep = await planned(house)
    desk = house.episodes
    first = desk.view(ep)["units"][0]
    desk.choose(
        ep, by="you", change={"units": {first["id"]: {"component": "list", "variant": "grid"}}}
    )
    assert desk.undo(ep, by="you")["units"][0]["visual"] == first["visual"]
    assert desk.redo(ep, by="you")["units"][0]["visual"]["variant"] == "grid"


def test_generation_overrides_are_passed_to_new_and_resumed_local_turns(tmp_path: Path) -> None:
    from design_agent.surfaces.web import research

    for harness, model, effort in (
        ("codex", "gpt-6.1-sol", "medium"),
        ("claude", "claude-sonnet-5-5", "high"),
    ):
        for session in ("", "previous"):
            args, _ = research.command(
                research.HARNESSES[harness],
                harness,
                repo=tmp_path,
                prompt="draw",
                session=session,
                profile=tmp_path / "agent.md",
                writes=True,
                model=model,
                effort=effort,
            )
            assert args[args.index("--model") + 1] == model
            assert (
                f'model_reasoning_effort="{effort}"' in args
                if harness == "codex"
                else args[args.index("--effort") + 1] == effort
            )


async def test_builtin_picture_model_is_scoped_to_one_turn(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    house.settings = house.settings.model_copy(
        update={"model": "openai:gpt-6.1-sol", "model_effort": "low"}
    )
    thread = house.episodes.view(await planned(house))["thread_id"]
    runtime = house.runtime
    assert runtime is not None
    ask = runtime.ask
    seen: list[Any] = []

    async def record(text: str, *, model_settings: Settings | None = None, **kw: Any) -> Any:
        seen.append((model_settings.model, model_settings.model_effort) if model_settings else None)
        return await ask(text, **kw)

    monkeypatch.setattr(runtime, "ask", record)
    for scoped in (("gpt-6.1-sol", "medium"), None):
        answer, failure = await house.told(
            thread, by="you", text="Draw this picture", picture_model=scoped
        )
        assert answer and not failure
    assert seen == [("openai:gpt-6.1-sol", "medium"), None]
    assert house.settings.model_effort == "low"


async def test_renderer_disappearance_ends_attempt_and_allows_retry(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    from design_agent.surfaces.web.computer import Ran

    eid = await planned(house)
    house.episodes.approve(eid, by="you")
    await settle(lambda: not house.episodes._busy(eid))

    class Computer:
        state = "stopped"

        def get_into(self, path: str, target: Any, *, timeout: int = 0) -> None:
            content = self.get(path)
            if not content:
                raise FileNotFoundError(path)
            target.write(content)

        def put(self, files: list[tuple[str, bytes]]) -> None:
            pass

        def run(self, command: str, *, timeout: int = 60) -> Ran:
            if "cat render.exit" in command:
                return Ran(
                    self.state
                    + '\n@hf-progress {"code":"capture","done":120,"total":9240,"pct":26}',
                    0,
                )
            return Ran("", 0)

        def get(self, path: str) -> bytes:
            return b"mp4"

    computer = Computer()
    monkeypatch.setattr(house.episodes, "_computer", lambda episode: computer)
    monkeypatch.setattr("design_agent.surfaces.web.episode_desk.time.sleep", lambda _s: None)
    started = house.episodes.render(eid, by="you")["film_state"]
    assert started["started_at"] and started["phase"] == "prepare"
    await settle(lambda: not house.episodes._busy(eid))
    failed = house.episodes.view(eid)["film_state"]
    assert failed["status"] == "failed" and "stopped" in failed["failure"].lower()
    assert failed["ended_at"] >= started["started_at"]
    assert (failed["frames_done"], failed["frames_total"]) == (120, 9240)
    computer.state = "0"
    retry = house.episodes.render(eid, by="you")["film_state"]
    assert retry["started_at"] > failed["started_at"] and not retry.get("ended_at")
    assert not retry.get("frames_done")
    await settle(lambda: not house.episodes._busy(eid))
    done = house.episodes.view(eid)["film_state"]
    assert done["status"] == "done" and done["ended_at"] >= retry["started_at"]


def test_renderer_probe_distinguishes_dead_reused_and_completed_processes(tmp_path: Path) -> None:
    import subprocess

    from design_agent.surfaces.web.episode_render import probe

    script = probe(str(tmp_path), "render_ab12")

    def status() -> str:
        return subprocess.check_output(["sh", "-c", script], text=True).splitlines()[0]

    (tmp_path / "render.log").write_text(
        '@hf-progress {"code":"capture","done":120,"total":9240,"pct":26}\n'
    )
    (tmp_path / "render.pid").write_text("2147483647")
    assert status() == "stopped"
    with subprocess.Popen(["sh", "-c", "sleep 4; exit 0", "render_ab12"]) as child:
        try:
            (tmp_path / "render.pid").write_text(str(child.pid))
            assert status() == "running"
            wrong = probe(str(tmp_path), "render_ffff")
            assert (
                subprocess.check_output(["sh", "-c", wrong], text=True).splitlines()[0] == "stopped"
            )
        finally:
            child.terminate()
    assert status() == "stopped"
    (tmp_path / "render.exit").write_text("0")
    assert status() == "0"


@pytest.mark.parametrize(
    "line",
    [
        "@hf-progress {",
        '@hf-progress {"pct":true}',
        '@hf-progress {"pct":140}',
        '@hf-progress {"pct":null}',
        "@hf-progress []",
    ],
)
def test_invalid_render_progress_does_not_replace_last_measurement(line: str) -> None:
    from design_agent.surfaces.web.episode_render import progress

    assert progress("running\n" + line) == {}


async def test_local_voice_uses_cached_speech_and_does_not_need_elevenlabs(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    from design_agent.tools import local_speech, media

    said = []

    def synthesize(words: str) -> Any:
        said.append(words)
        return media.Spoken(b"wave", 2.5, [])

    monkeypatch.setattr(local_speech, "engine", lambda: "say")
    monkeypatch.setattr(local_speech, "synthesize", synthesize)
    ep = await planned(house)
    house.episodes.choose(ep, by="you", change={"settings": {"voice": "local"}})
    await house.episodes._narrate(ep)
    view = house.episodes.view(ep)
    assert view["settings"]["voice"] == "local" and all(
        line["source"]["kind"] == "voice" for line in view["clock"]["lines"]
    )
    assert all(line["audio_url"].startswith("/api/files/") for line in view["clock"]["lines"])
    count = len(said)
    await house.episodes._narrate(ep)
    assert count and len(said) == count
    changed = house.episodes.edit(
        ep, by="you", frame=view["clock"]["lines"][0]["frame"], text="Listen to this amended line."
    )
    assert "audio_url" not in changed["clock"]["lines"][0]
    assert all("audio_url" in row for row in changed["clock"]["lines"][1:])


async def test_demo_picture_retry_can_read_the_original_brief(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode = await planned(house)
    desk = house.episodes
    original = desk._pose
    calls = []

    def transient(*args: Any) -> Any:
        calls.append(True)
        if len(calls) == 1:
            return ["no still could be taken"], {}
        return original(*args)

    monkeypatch.setattr(desk, "_pose", transient)
    unit = desk.view(episode)["units"][0]["id"]
    desk.make(episode, by="you", only=[unit])
    await settle(lambda: not desk._busy(episode))
    assert desk.view(episode)["units"][0]["picture"]["status"] == "made"
    assert len(calls) == 2


@pytest.mark.parametrize("size", ["small", 43])
async def test_presenter_window_is_saved_for_one_line_and_used_by_film(
    house: AgentHost, size: str | int
) -> None:
    from design_agent.episode import film, geometry

    ep = await planned(house)
    view = house.episodes.choose(
        ep,
        by="you",
        change={"frames": {"c1.b2.f1": {"window_size": size, "window_shape": "circle"}}},
    )
    frame = next(
        f
        for c in view["plan"]["chapters"]
        for b in c["beats"]
        for f in b["frames"]
        if f["id"] == "c1.b2.f1"
    )
    region = geometry.for_frame(frame)
    assert region.person and region.person[2] == region.person[3] < 346
    assert region.person_radius == region.person[2] // 2
    assert frame["window"]["box"] == list(region.person)
    page = film.project(view["plan"], view["clock"], [], {})["index.html"]
    x, y, width, height = region.person
    assert (
        f"left: {x}px; top: {y}px; width: {width}px; height: {height}px; border-radius: {region.person_radius}px"
        in page
    )
    with pytest.raises(ValueError):
        house.episodes.choose(
            ep, by="you", change={"frames": {frame["id"]: {"window_size": "huge"}}}
        )
    cleared = house.episodes.choose(
        ep, by="you", change={"frames": {frame["id"]: {"window_size": None, "window_shape": None}}}
    )
    assert not any(
        f.get("window")
        for c in cleared["plan"]["chapters"]
        for b in c["beats"]
        for f in b["frames"]
    )


async def test_episode_background_reaches_the_picture_and_film_and_can_be_reset(
    house: AgentHost,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from design_agent.episode import film
    from design_agent.surfaces.web.episode_desk import _outdated

    eid = await planned(house)
    desk = house.episodes
    original = desk._look(desk._episode(eid))

    def unexpected_layout_change(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Changing the background must preserve approved frame layouts.")

    monkeypatch.setattr("design_agent.episode.override.apply", unexpected_layout_change)
    desk.choose(
        eid,
        by="you",
        change={"settings": {"background_color": "#152030", "background_texture": "dots"}},
    )
    view = desk.view(eid)
    look = desk._look(desk._episode(eid))
    assert view["background"]["color"] == look.palette["ground"] == "#152030"
    assert look.texture == "dots" and look.palette["ink"] != original.palette["ink"]
    unit = view["units"][0]
    legacy = {"status": "made", "sig": unit["sig"], "level": unit["level"]}
    assert _outdated(legacy, unit)
    assert picture.brief(unit, view["plan"], look=look)["look"]["texture"] == "dots"
    assert (
        "radial-gradient"
        in film.project(view["plan"], view["clock"], [], {}, look=look)["index.html"]
    )
    for invalid in ({"background_color": "red; url(x)"}, {"background_texture": "unknown"}):
        with pytest.raises(ValueError):
            desk.choose(eid, by="you", change={"settings": invalid})
    desk.choose(
        eid, by="you", change={"settings": {"background_color": "", "background_texture": "solid"}}
    )
    assert desk._look(desk._episode(eid)) == original
    assert not _outdated(legacy, desk.view(eid)["units"][0])


async def test_line_edit_uses_its_picture_model_but_a_chapter_edit_uses_the_writer(
    tmp_path: Path, house: AgentHost
) -> None:
    eid = await planned(house)
    desk = house.episodes
    writer = heard_by(house, tmp_path)
    selected = Heard(data_dir=tmp_path, script=SCRIPT, pause=0)
    selected.turns = []
    desk.workers["codex"] = selected
    unit = next(u for u in desk.view(eid)["units"] if len(u["frames"]) > 1)
    desk.choose(
        eid,
        by="you",
        change={
            "units": {unit["id"]: {"builder": "codex", "model": "gpt-6.1-sol", "effort": "medium"}}
        },
    )
    desk.ask(eid, by="you", scope="line", target=unit["frames"][1], text="Shorten this line.")
    await settle(lambda: not desk.planning(eid))
    assert any(lane == "plan" and "Shorten this line." in prompt for lane, prompt in selected.turns)
    assert not writer.turns
    desk.ask(eid, by="you", scope="chapter", target=unit["chapter"], text="Shorten this section.")
    await settle(lambda: not desk.planning(eid))
    assert any("Shorten this section." in prompt for _, prompt in writer.turns)


async def test_episode_presenter_portrait_is_saved_and_used_in_export(house: AgentHost) -> None:
    import base64

    from design_agent.episode import film

    eid = await planned(house)
    desk = house.episodes
    for name in film.PORTRAITS:
        view = desk.choose(eid, by="you", change={"settings": {"portrait": name}})
        assert desk.view(eid)["settings"]["portrait"] == name
        page = film.project(view["plan"], view["clock"], [], {}, portrait=name)["index.html"]
        data = base64.b64encode(film.portrait_path(name).read_bytes()).decode("ascii")
        assert f"data:image/jpeg;base64,{data}" in page
    with pytest.raises(ValueError, match="portrait"):
        desk.choose(eid, by="you", change={"settings": {"portrait": "../anything"}})
    assert desk.view(eid)["settings"]["portrait"] == film.PORTRAITS[-1]


async def test_redraw_uses_the_saved_beat_provider_model_and_effort(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    eid = await planned(house)
    desk = house.episodes
    desk.approve(eid, by="you")
    await settle(lambda: not desk._busy(eid))
    unit = desk.view(eid)["units"][0]
    key = unit["id"]
    assert unit["picture"]["builder"] == DEMO
    desk._worker_called("codex")
    desk.choose(
        eid,
        by="you",
        change={
            "units": {
                key: {
                    "builder": "codex",
                    "model": "gpt-6.1-sol",
                    "effort": "medium",
                    "level": "simple",
                }
            }
        },
    )
    calls = []

    async def draw(
        worker: LocalWorker, episode: dict[str, Any], *, lane: str, **kwargs: Any
    ) -> Told:
        calls.append((worker.id, worker.model, worker.effort, lane))
        folder = worker.folder(episode)
        comp = picture.composition_id(key)
        brief = json.loads((folder / f"pictures/{comp}.brief.json").read_text())
        (folder / brief["file"]).write_text((folder / f"pictures/{comp}.starter.html").read_text())
        return Told()

    monkeypatch.setattr(LocalWorker, "turn", draw)
    desk.make(eid, by="you", only=[key])
    await settle(lambda: not desk._busy(eid))
    result = desk.view(eid)["units"][0]["picture"]
    assert calls == [("codex", "gpt-6.1-sol", "medium", f"picture:{key}")]
    assert result["status"] == "made"
    assert result["generation"]["model"] == "gpt-6.1-sol"
    assert result["generation"]["effort"] == "medium"


async def test_the_films_agent_runs_on_the_model_and_effort_picked_for_the_film(
    house: AgentHost,
) -> None:
    eid = await planned(house)
    desk = house.episodes
    default_worker = desk._worker_called("codex")
    assert isinstance(default_worker, LocalWorker)
    before = (default_worker.model, default_worker.effort)
    # only what the agent offers is kept
    for pick in (
        {"writer_model": "gpt-nope"},
        {"writer_model": "gpt-6.1-sol", "writer_effort": "minimal"},
    ):
        with pytest.raises(ValueError, match="supported model and effort"):
            desk.choose(eid, by="you", change={"settings": {"writer": "codex", **pick}})
    assert desk.view(eid)["settings"]["writer"] == DEMO
    view = desk.choose(
        eid,
        by="you",
        change={
            "settings": {"writer": "codex", "writer_model": "gpt-6.1-sol", "writer_effort": "low"}
        },
    )
    assert view["settings"]["writer_model"] == "gpt-6.1-sol"
    assert view["settings"]["writer_effort"] == "low"
    worker = desk._worker(desk._episode(eid))
    assert isinstance(worker, LocalWorker)
    assert (worker.id, worker.model, worker.effort) == ("codex", "gpt-6.1-sol", "low")
    # the agent kept for the next film is left as it was
    assert (default_worker.model, default_worker.effort) == before
    # every picture the film's agent builds is built on it, and says so
    mine, other = view["units"][0], view["units"][1]
    assert mine["builder"] == "codex" and mine["model_pick"] == {"model": "", "effort": ""}
    assert mine["model_now"] == {"model": "gpt-6.1-sol", "effort": "low", "from": "film"}
    assert (mine["generation"]["model"], mine["generation"]["effort"]) == ("gpt-6.1-sol", "low")
    built = desk._builder(desk._episode(eid), mine)
    assert (built.model, built.effort) == ("gpt-6.1-sol", "low")  # type: ignore[union-attr]
    # a picture's own pick holds over the film's, and one built by another agent takes none of it
    view = desk.choose(
        eid,
        by="you",
        change={
            "units": {
                mine["id"]: {"model": "gpt-6-sol", "effort": "high"},
                other["id"]: {"builder": DEMO},
            }
        },
    )
    mine, other = view["units"][0], view["units"][1]
    assert mine["model_now"] == {"model": "gpt-6-sol", "effort": "high", "from": "beat"}
    assert other["builder"] == DEMO and other["model_now"]["from"] == ""
    assert other["generation"]["model"] == "demo"
    # a new model alone starts on its own default effort; nothing picked is the agent's default
    view = desk.choose(eid, by="you", change={"settings": {"writer_model": "gpt-6-sol"}})
    assert view["settings"]["writer_model"] == "gpt-6-sol"
    assert "writer_effort" not in view["settings"]
    view = desk.choose(eid, by="you", change={"settings": {"writer_effort": "high"}})
    assert (view["settings"]["writer_model"], view["settings"]["writer_effort"]) == (
        "gpt-6-sol",
        "high",
    )
    view = desk.choose(
        eid, by="you", change={"settings": {"writer_model": "", "writer_effort": ""}}
    )
    assert not {"writer_model", "writer_effort"} & view["settings"].keys()
    worker = desk._worker(desk._episode(eid))
    assert worker is desk.workers["codex"]
    # another agent has its own models: the last one's picks go with it
    desk.choose(eid, by="you", change={"settings": {"writer_model": "gpt-6.1-sol"}})
    view = desk.choose(eid, by="you", change={"settings": {"writer": DEMO}})
    assert view["settings"]["writer"] == DEMO and "writer_model" not in view["settings"]


async def test_a_pick_the_agent_no_longer_offers_falls_back_to_its_default(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(episode_models, "CODEX_HOME", tmp_path)
    eid = await planned(house)
    desk = house.episodes
    desk._worker_called("codex")
    view = desk.choose(
        eid,
        by="you",
        change={"settings": {"writer": "codex", "writer_model": "gpt-6.1-sol"}},
    )
    unit = view["units"][0]
    desk.choose(eid, by="you", change={"units": {unit["id"]: {"model": "gpt-6-sol"}}})
    # the agent's models are its own to change: these two are gone the next time it is asked
    monkeypatch.setattr(episode_models, "codex_model_list", lambda: ({"model": "gpt-5.6-sol"},))
    view = desk.view(eid)
    assert all(u["model_now"] == {"model": "", "effort": "", "from": ""} for u in view["units"])
    assert view["units"][0]["generation"]["model"] == "gpt-5.6-sol"
    worker = desk._worker(desk._episode(eid))
    assert isinstance(worker, LocalWorker) and worker.model == "gpt-5.6-sol"


async def test_local_chapter_preview_caches_only_its_lines_and_serializes_requests(
    house, monkeypatch
):
    from design_agent.tools import local_speech, media

    said = []

    def synth(words):
        said.append(words)
        return media.Spoken(b"wave", 2.5, [])

    monkeypatch.setattr(local_speech, "engine", lambda: "say")
    monkeypatch.setattr(local_speech, "synthesize", synth)
    ep = await planned(house, voice="local")
    desk = house.episodes
    chapter = desk.view(ep)["plan"]["chapters"][0]["id"]
    await asyncio.gather(desk.preview_voice(ep, chapter), desk.preview_voice(ep, chapter))
    lines = desk.view(ep)["clock"]["lines"]
    assert len(said) == sum(row["chapter"] == chapter for row in lines)
    assert all(bool(row.get("audio_url")) == (row["chapter"] == chapter) for row in lines)
    with pytest.raises(KeyError):
        await desk.preview_voice(ep, "unknown")
    assert not desk.view(ep)["film_state"]["file"]


async def test_speech_only_overrides_voice_similarity_when_requested(monkeypatch):
    import httpx

    from design_agent.tools import media

    requests = []

    async def request(key, path, name, body, output_format, *, timeout):
        requests.append((path, body))
        return httpx.Response(200, json={"audio_base64": "bXAz"})

    monkeypatch.setattr(media, "_elevenlabs_request", request)
    keys = media.MediaKeys.from_settings(Settings(_env_file=None))
    voice = "testvoice00001"
    assert isinstance(
        await media.speak(keys, "A sample", voice, similarity_boost=0.9), media.Spoken
    )
    assert isinstance(await media.speak(keys, "A sample", voice), media.Spoken)
    assert requests == [
        (
            f"text-to-speech/{voice}/with-timestamps",
            {
                "text": "A sample",
                "model_id": "eleven_v4",
                "voice_settings": {"similarity_boost": 0.9},
            },
        ),
        (f"text-to-speech/{voice}/with-timestamps", {"text": "A sample", "model_id": "eleven_v4"}),
    ]


async def test_cloned_voice_narrates_only_the_requested_chapter(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic import SecretStr

    from design_agent.tools import media

    house.settings = house.settings.model_copy(update={"elevenlabs_api_key": SecretStr("test")})
    ep = await planned(house)
    desk = house.episodes
    chapter = desk.view(ep)["plan"]["chapters"][0]["id"]
    voice_id = "voice1234567890"
    said: list[tuple[str, str]] = []

    async def clone(keys, name, samples, **unused):
        assert name == "My test voice" and samples == [("sample.wav", b"sample")]
        return media.Cloned(voice_id, False)

    async def speak(keys, words, selected, **options):
        assert options["similarity_boost"] == 0.9
        said.append((words, selected))
        return media.Spoken(b"mp3", 2.0, [])

    monkeypatch.setattr(media, "clone_voice", clone)
    monkeypatch.setattr(media, "speak", speak)
    await desk.clone(
        ep, by="you", name="My test voice", consent=True, sample=("sample.wav", b"sample")
    )
    planned_chapter = desk.view(ep)["plan"]["chapters"][0]
    line = planned_chapter["beats"][0]["frames"][0]
    house.store.update_episode(
        ep,
        film={
            "voice": {
                line["id"]: {
                    "file": "old-preview",
                    "seconds": 14.0,
                    "h": plans.digest(line["vo"], voice_id),
                }
            }
        },
    )
    assert not desk.view(ep)["clock"]["lines"][0].get("audio_url")
    view = await desk.preview_voice(ep, chapter)
    assert view["settings"]["cloned_voice"]["id"] == voice_id
    lines = view["clock"]["lines"]
    assert len(said) == sum(line["chapter"] == chapter for line in lines)
    assert all(voice == voice_id for _, voice in said)
    assert all(bool(line.get("audio_url")) == (line["chapter"] == chapter) for line in lines)
    await desk.preview_voice(ep, chapter)
    assert len(said) == sum(line["chapter"] == chapter for line in lines)
    assert not view["film_state"]["file"]


async def test_channel_clones_can_be_selected_and_sampled_once(house, monkeypatch):
    from pydantic import SecretStr

    from design_agent.tools import media

    house.settings = house.settings.model_copy(update={"elevenlabs_api_key": SecretStr("test")})
    desk = house.episodes
    first = await planned(house)
    second = await planned(house)
    other = desk.create(
        house.store.channels()[1]["id"], by="you", text=NOTES, settings={"writer": DEMO}
    )["id"]
    await settle(lambda: not desk.planning(other))
    ids = iter(("testvoice00001", "testvoice00002"))
    spoken = []

    async def clone(*args, **kwargs):
        return media.Cloned(next(ids), False)

    async def speak(keys, text, voice, **options):
        assert options["similarity_boost"] == 0.9
        spoken.append(voice)
        return media.Spoken(b"sample audio", 2, [])

    monkeypatch.setattr(media, "clone_voice", clone)
    monkeypatch.setattr(media, "speak", speak)
    for name in ("First voice", "Second voice"):
        await desk.clone(first, by="you", name=name, consent=True, sample=("sample.wav", b"audio"))
    saved = desk.view(second)["channel_voices"]
    assert {voice["name"] for voice in saved} == {"First voice", "Second voice"}
    assert not desk.view(other)["channel_voices"] and spoken == []
    voice = next(v for v in saved if v["name"] == "First voice")
    pick = {"settings": {"voice": "narrator", "narrator": {"id": voice["id"], "name": "Ignored"}}}
    assert (
        desk.choose(second, by="you", change=pick)["settings"]["narrator"]["name"] == "First voice"
    )
    with pytest.raises(ValueError, match="another channel"):
        desk.choose(other, by="you", change=pick)
    with pytest.raises(KeyError):
        await desk.preview_channel_voice(other, voice["id"])
    earlier = house.save_file("", f"voice-preview-{voice['id']}.mp3", b"old", origin="episode")
    house.store.save_voice_preview(voice["id"], earlier["id"])
    assert not any(v.get("preview") for v in desk.view(second)["channel_voices"])
    await asyncio.gather(*(desk.preview_channel_voice(second, voice["id"]) for _ in range(2)))
    assert spoken == [voice["id"]]
    assert any(v.get("preview") for v in desk.view(second)["channel_voices"])
    assert house.blobs.read(desk.channel_voice_file(second, voice["id"])) == b"sample audio"
    with pytest.raises(KeyError):
        desk.channel_voice_file(other, voice["id"])
    old = desk.view(second)
    legacy = {"id": "testoldvoice00", "name": "Legacy voice", "verify": True}
    house.store.update_episode(second, settings={**old["settings"], "cloned_voice": legacy})
    store = Store(house.store.path)
    try:
        persisted = store.channel_voice_clones(old["channel_id"])
        assert {row["id"] for row in persisted} == {v["id"] for v in saved} | {legacy["id"]}
        assert store.voice_clone(legacy["id"])["verify"] == 1
    finally:
        store.close()


def test_a_channel_voice_can_be_cloned_before_creating_an_episode(tmp_path, monkeypatch):
    from design_agent.tools import media

    settings = Settings(
        _env_file=None,
        workspace_root=tmp_path / "workspace",
        sandbox="host",
        elevenlabs_api_key="test-key",
    )
    calls = []

    async def clone(keys, name, samples, *, noisy):
        calls.append((name, samples, noisy))
        return media.Cloned("testvoice00001", False)

    monkeypatch.setattr(media, "clone_voice", clone)
    with TestClient(create_app(ROOT, settings, demo=True)) as client:
        first, second, *_ = client.get("/api/channels").json()
        url = f"/api/channels/{first['id']}/voices"
        other = f"/api/channels/{second['id']}/voices"
        assert client.get(url).json() == {"voices": []}
        assert client.get("/api/channels/missing/voices").status_code == 404
        file = {"file": ("sample.webm", b"recorded speech", "audio/webm")}
        assert client.post(url, data={"name": "Narrator"}, files=file).status_code == 422
        consent = {"name": " Narrator ", "consent": "true"}
        assert client.post(url, data=consent).status_code == 422
        empty = {"file": ("empty.webm", b"", "audio/webm")}
        assert client.post(url, data=consent, files=empty).status_code == 422
        assert (
            client.post("/api/channels/missing/voices", data=consent, files=file).status_code == 404
        )
        assert not calls
        made = client.post(url, data=consent, files=file)
        assert made.status_code == 200, made.text
        voice = {"id": "testvoice00001", "name": "Narrator"}
        assert made.json() == voice
        assert calls == [("Narrator", [("sample.webm", b"recorded speech")], False)]
        assert client.get(url).json() == {"voices": [voice]}
        assert client.get(other).json() == {"voices": []}
        assert client.app.state.host.store.all_episodes() == []

        body = {
            "text": NOTES,
            "settings": {"writer": DEMO, "voice": "narrator", "narrator": voice},
        }
        assert client.post(f"/api/channels/{second['id']}/episodes", json=body).status_code == 422
        episode = client.post(f"/api/channels/{first['id']}/episodes", json=body)
        assert episode.status_code == 200, episode.text
        assert episode.json()["settings"]["narrator"] == voice


def test_motion_plan_rejects_two_shots_for_one_frame():
    shot = {"frame": "a", "shot": "Show the path.", "hero": "Trace the path.", "still": "A path."}
    _, faults = picture.motion_plan(
        json.dumps({"device": "steps in order", "world": "A chart", "shots": [shot, shot]}),
        {"frames": ["a"]},
    )
    assert any("duplicate" in f for f in faults)


async def test_picture_preview_reuses_audio_mix_and_invalidates_on_edit(house, monkeypatch):
    from design_agent.tools import local_speech, media

    desk = house.episodes
    monkeypatch.setattr(local_speech, "engine", lambda: "say")
    monkeypatch.setattr(local_speech, "synthesize", lambda _: media.Spoken(b"wave", 2.5, []))
    ep = await planned(house, voice="local")
    unit = desk.view(ep)["units"][0]
    clip = house.save_file(desk._episode(ep)["thread_id"], "pic.mp4", b"video", origin="episode")
    desk.store.set_picture(
        ep, unit["id"], status="go", clip=clip["id"], generation={"model": "keep"}
    )
    mixes = []

    def mix(*args):
        mixes.append(args)
        return b"audio-video"

    monkeypatch.setattr(desk, "_mix_preview", mix)
    first = await desk.preview_clip(ep, unit["id"])
    assert first["id"] != clip["id"]
    assert (await desk.preview_clip(ep, unit["id"]))["id"] == first["id"]
    assert len(mixes) == 1
    desk.edit(ep, by="you", frame=unit["frames"][0], text="A changed line.")
    assert (await desk.preview_clip(ep, unit["id"]))["id"] != first["id"]
    assert len(mixes) == 2 and desk.store.picture(ep, unit["id"])["generation"]["model"] == "keep"


async def test_beat_history_keeps_saved_wording_and_visual_changes(house: AgentHost) -> None:
    eid = await made(house)
    desk = house.episodes
    frame = order_of(desk.view(eid))[0]
    fid = frame["id"]
    assert desk.line_history(eid, fid)["entries"] == []
    for words in ("First revision.", "Second revision."):
        desk.edit(eid, by="you", frame=fid, text=words)
    entries = desk.line_history(eid, fid)["entries"]
    assert [entry["changes"][0]["after"] for entry in entries] == [
        "Second revision.",
        "First revision.",
    ]
    assert entries[-1]["changes"][0]["before"] == frame["vo"]
    desk.undo(eid, by="you")
    assert len(desk.line_history(eid, fid)["entries"]) == 1
    before = desk._episode(eid)
    plan = json.loads(json.dumps(before["plan"]))
    target = plan["chapters"][0]["beats"][1]["frames"][0]
    old_direction = target["shows"]
    target["shows"] = "Zoom in on the receiver."
    desk._snapshot(eid, "More detail")
    house.store.update_episode(eid, plan=plan)
    history = desk.line_history(eid, target["id"])["entries"]
    assert history[0]["changes"] == [
        {"label": "Visual direction", "before": old_direction, "after": target["shows"]}
    ]
    assert len(desk.line_history(eid, fid)["entries"]) == 1
    visible = {f["id"] for f in order_of(desk.view(eid)) if f.get("has_history")}
    assert visible == {fid, target["id"]}
    with pytest.raises(KeyError):
        desk.line_history(eid, "unknown")


@pytest.mark.parametrize("off", [False, True])
def test_frames_writer_receives_only_the_selected_looks_layouts(
    house: AgentHost, off: bool
) -> None:
    settings = {"theme": "corner-window", "presenter": "off" if off else "on"}
    prompt = house.episodes._prompt(
        {"settings": settings}, house.episodes.workers[DEMO], "frames", [], ""
    )
    assert "layout_intent" in prompt
    assert ("corner-top-right" in prompt) is not off
    assert ("recording-fills" in prompt) is off


async def test_planned_layout_reaches_the_saved_episode_and_picture_builder(
    house: AgentHost, tmp_path: Path
) -> None:
    script = json.loads(json.dumps(SCRIPT))
    frame = next(
        frame
        for chapter in script["plan"]["chapters"]
        for beat in chapter["beats"]
        for frame in beat.get("frames", [])
        if frame.get("shows")
        and not frame.get("hold")
        and script["labels"]["frames"][frame["id"]]["presence"] == "both"
    )
    frame["layout_intent"] = "corner-top-right"
    house.episodes.workers[DEMO] = DemoWorker(data_dir=tmp_path, script=script, pause=0)
    episode_id = await planned(house)
    view = house.episodes.view(episode_id)
    line = next(
        f
        for ch in view["plan"]["chapters"]
        for b in ch["beats"]
        for f in b["frames"]
        if f["id"] == frame["id"]
    )
    assert line["layout"] == "corner-top-right"
    unit = next(u for u in view["units"] if frame["id"] in u["frames"])
    brief = picture.brief(unit, view["plan"])
    assert brief["layout"]["id"] == line["layout"]
    assert brief["keep_clear"]["top"] == 0
    assert view["options"]["geometry"]["layouts"][line["layout"]]["person"] == [1432, 28, 460, 258]


async def test_history_control_follows_saved_changes_undo_and_redo(house: AgentHost) -> None:
    eid = await made(house)
    desk = house.episodes
    original = order_of(desk.view(eid))[0]

    def visible(view: dict[str, Any]) -> set[str]:
        return {f["id"] for f in order_of(view) if f.get("has_history")}

    assert not visible(desk.edit(eid, by="you", frame=original["id"], text=original["vo"]))
    assert visible(desk.edit(eid, by="you", frame=original["id"], text="Edited.")) == {
        original["id"]
    }
    assert not visible(desk.undo(eid, by="you"))
    assert visible(desk.redo(eid, by="you")) == {original["id"]}
    # Returning to the original words by editing again retains both actual changes.
    assert visible(desk.edit(eid, by="you", frame=original["id"], text=original["vo"])) == {
        original["id"]
    }


async def test_transcript_edits_preserve_rich_artwork_and_original_animation_spans(
    house: AgentHost,
) -> None:
    eid = await made(house)
    desk = house.episodes
    view = desk.view(eid)
    unit = next(u for u in view["units"] if lines_of(view)[u["id"]].get("cues"))
    saved = house.store.picture(eid, unit["id"])
    clip = house.save_file(view["thread_id"], "animation.mp4", b"clip", origin="episode")
    generation = {**saved["generation"], "clip_lines": {unit["id"]: [0, 12]}}
    motion = {"device": "one diagram that grows", "shots": []}
    house.store.set_picture(
        eid, unit["id"], clip=clip["id"], generation=generation, motion=motion, level="rich"
    )
    for words in (
        "New words for this animation.",
        "A substantially longer rewrite that still uses the existing animated diagram.",
    ):
        after = desk.edit(eid, by="you", frame=unit["id"], text=words)
        current = next(u for u in after["units"] if u["id"] == unit["id"])
        assert current["picture"]["clip"]["id"] == clip["id"]
        assert current["picture"]["generation"]["clip_lines"] == generation["clip_lines"]
        assert current["picture"]["motion"] == motion
        assert house.store.picture(eid, unit["id"])["html"] == saved["html"]
        assert not desk._busy(eid)


async def test_applying_cue_word_changes_preserves_classified_artwork(
    house: AgentHost, tmp_path: Path
) -> None:
    eid = await made(house)
    desk = house.episodes
    worker = LocalWorker("codex", store=house.store, data_dir=tmp_path, project_root=ROOT)
    before = desk.view(eid)
    unit = next(u for u in before["units"] if lines_of(before)[u["id"]].get("cues"))
    desk.edit(eid, by="you", frame=unit["id"], text="New words for the animation.")
    episode = desk._episode(eid)
    original = desk._full(episode)
    raw = json.loads(json.dumps(episode["plan"]))
    _, _, frame = next((ch, b, f) for ch, b, f in plans.frames_of(raw) if f["id"] == unit["id"])
    for cue in frame["cues"]:
        cue["at"] = "New"
    await worker.prepare(episode, {"plan.json": json.dumps(raw)})
    assert not await desk._take_plan(eid, worker, "redo")
    fitted = desk._merged(desk._episode(eid))
    old = lines_of({"plan": original})[unit["id"]]
    new = lines_of({"plan": fitted})[unit["id"]]
    assert new.get("_designed"), "cue anchors alone must retain the picture's labels"
    assert new["objects"] == old["objects"]
    after = desk.view(eid)
    assert next(u for u in after["units"] if u["id"] == unit["id"])["sig"] == unit["sig"]
    assert [c["move"] for c in new["cues"]] == [c["move"] for c in old["cues"]]


async def test_a_picture_made_again_keeps_the_versions_before_to_look_back_at(
    tmp_path: Path, house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    desk = house.episodes
    desk.workers[DEMO] = DemoWorker(data_dir=tmp_path, script=SCRIPT, pause=0, store=house.store)
    episode_id = await planned(house)

    def picture_now(unit_id: str) -> dict[str, Any]:
        return next(u for u in desk.view(episode_id)["units"] if u["id"] == unit_id)["picture"]

    async def again(level: str) -> dict[str, Any]:
        desk.make(episode_id, by="you", only=[unit["id"]], level=level)
        await settle(lambda: not desk._busy(episode_id))
        return picture_now(unit["id"])

    def stills(version: dict[str, Any]) -> dict[str, str]:
        return {frame: still["id"] for frame, still in version["stills"].items()}

    unit = next(u for u in desk.view(episode_id)["units"] if u["kind"] == "picture")
    desk.make(episode_id, by="you", only=[unit["id"]])
    await settle(lambda: not desk._busy(episode_id))
    first = picture_now(unit["id"])
    # a picture made once is its first version, with nothing before it
    assert first["status"] == "made" and first["stills"]
    assert first["version"] == 1 and first["versions"] == []
    second = await again(first["level"] or "simple")
    # made again, it is the second version and keeps the first: its stills as they were, how
    # and by whom it was made, when, and how long its build took
    assert second["status"] == "made" and second["version"] == 2
    (kept,) = second["versions"]
    assert kept["n"] == 1 and stills(kept) == stills(first)
    assert kept["level"] == first["level"] and kept["builder"] == first["builder"]
    assert kept["made_at"] and kept["seconds"] == first["timing"]["seconds"]
    third = await again(second["level"])
    # the versions before stand newest first, each under the number it was made as
    assert third["version"] == 3 and [v["n"] for v in third["versions"]] == [2, 1]
    assert stills(third["versions"][0]) == stills(second)
    # one stopped before it was made again keeps no version of what was not made
    house.store.set_picture(episode_id, unit["id"], status="failed", failure="Stopped.")
    fourth = await again(third["level"])
    assert fourth["version"] == 3 and [v["n"] for v in fourth["versions"]] == [2, 1]
    # past what is kept, the oldest is dropped and the numbers run on
    monkeypatch.setattr(episode_desk, "VERSIONS", 2)
    fifth = await again(fourth["level"])
    assert fifth["version"] == 4 and [v["n"] for v in fifth["versions"]] == [3, 2]


async def test_a_kept_version_is_put_back_whole_and_a_redo_that_does_not_land_falls_back(
    tmp_path: Path, house: AgentHost
) -> None:
    desk = house.episodes
    episode_id = await planned(house)
    key = next(u for u in desk.view(episode_id)["units"] if u["kind"] == "picture")["id"]

    def row() -> dict[str, Any]:
        found = house.store.picture(episode_id, key)
        assert found is not None
        return found

    def numbers(found: Mapping[str, Any]) -> tuple[int, list[int]]:
        return found["version"], [kept["n"] for kept in found["versions"]]

    def ask_again() -> None:
        desk.make(episode_id, by="you", only=[key], level=row()["level"] or "simple")

    async def made_again() -> dict[str, Any]:
        ask_again()
        await settle(lambda: not desk._busy(episode_id))
        return row()

    class Picture(DemoWorker):
        """The demo's builder, slow or failing on this picture when told to."""

        mode = ""

        async def turn(self, episode: Any, *, lane: str, prompt: str, heard: Any) -> Told:
            if lane == f"picture:{key}" and self.mode == "slow":
                await asyncio.sleep(30)
            if lane == f"picture:{key}" and self.mode == "broken":
                raise RuntimeError("The  agent  fell over.")
            return await super().turn(episode, lane=lane, prompt=prompt, heard=heard)

    builder = Picture(data_dir=tmp_path, script=SCRIPT, pause=0, store=house.store)
    desk.workers[DEMO] = builder
    desk.make(episode_id, by="you", only=[key])
    await settle(lambda: not desk._busy(episode_id))
    first = row()
    second = await made_again()
    third = await made_again()
    assert numbers(third) == (3, [2, 1])
    # a version is kept whole: the picture as it was drawn, not only its stills
    assert third["versions"][1]["html"] == first["html"]
    assert third["versions"][1]["stills"] == first["stills"]
    # put back, the first stands again as it was made, and the third is kept in its place
    view = desk.use_version(episode_id, key, 1, by="you")
    back = row()
    assert (back["status"], back["html"], back["stills"]) == (
        first["status"],
        first["html"],
        first["stills"],
    )
    assert numbers(back) == (1, [3, 2]) and back["timing"] == first["timing"]
    shown = next(u for u in view["units"] if u["id"] == key)["picture"]
    assert shown["version"] == 1 and [v["n"] for v in shown["versions"]] == [3, 2]
    assert not shown["stale"]
    with pytest.raises(ValueError, match="isn't kept"):
        desk.use_version(episode_id, key, 1, by="you")
    # made again from there, it is numbered after every version there has been
    fourth = await made_again()
    assert numbers(fourth) == (4, [1, 3, 2])
    # a redo that fails goes back to the version before, which says why the new one wasn't made
    builder.mode = "broken"
    failed = await made_again()
    assert (failed["status"], failed["html"]) == (fourth["status"], fourth["html"])
    assert numbers(failed) == (4, [1, 3, 2]) and failed["failure"] == "The agent fell over."
    # one stopped goes back too, with nothing to explain
    builder.mode = "slow"
    ask_again()
    await settle(lambda: row()["status"] == "making")
    assert numbers(row()) == (5, [4, 1, 3, 2])
    desk.stop(episode_id, key)
    await settle(lambda: not desk._busy(episode_id))
    stopped = row()
    assert (stopped["html"], stopped["failure"]) == (fourth["html"], "")
    assert numbers(stopped) == (4, [1, 3, 2])
    # putting a version back while the beat is made again stops that build, which leaves the
    # version put back standing
    ask_again()
    await settle(lambda: row()["status"] == "making")
    desk.use_version(episode_id, key, 2, by="you")
    await settle(lambda: not desk._busy(episode_id))
    put = row()
    assert (put["status"], put["html"], put["failure"]) == (second["status"], second["html"], "")
    assert numbers(put) == (2, [4, 1, 3])
    # a version made another way brings its way with it, so it does not read as out of date
    house.store.set_picture(
        episode_id,
        key,
        versions=[{**k, "level": "rich"} if k["n"] == 3 else k for k in put["versions"]],
    )
    view = desk.use_version(episode_id, key, 3, by="you")
    rich = next(u for u in view["units"] if u["id"] == key)
    assert (rich["level"], rich["picture"]["level"], rich["picture"]["stale"]) == (
        "rich",
        "rich",
        False,
    )


def test_a_store_from_before_numbered_versions_keeps_none_of_the_ones_it_had(
    tmp_path: Path,
) -> None:
    path = tmp_path / "house.sqlite"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE pictures (id TEXT PRIMARY KEY, episode_id TEXT NOT NULL,"
            " unit TEXT NOT NULL, sig TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,"
            " html TEXT NOT NULL DEFAULT '', stills TEXT NOT NULL DEFAULT '{}',"
            " clip TEXT NOT NULL DEFAULT '', go_sig TEXT NOT NULL DEFAULT '',"
            " note TEXT NOT NULL DEFAULT '', failure TEXT NOT NULL DEFAULT '',"
            " updated_at REAL NOT NULL, versions TEXT NOT NULL DEFAULT '[]')"
        )
        db.execute(
            "INSERT INTO pictures (id, episode_id, unit, status, html, updated_at, versions)"
            " VALUES ('pic_1', 'ep', 'u1', 'made', '<p>2</p>', 0, ?)",
            (json.dumps([{"n": 1, "stills": {}, "clip": "", "made_at": 0}]),),
        )
    found = Store(path).picture("ep", "u1")
    assert found is not None and (found["version"], found["versions"]) == (1, [])


async def test_taking_a_change_back_puts_back_the_picture_it_had_and_keeps_the_one_since(
    house: AgentHost,
) -> None:
    desk = house.episodes
    episode_id = await planned(house)
    key = desk.view(episode_id)["units"][0]["id"]

    def drawn(variant: str) -> None:
        desk.choose(
            episode_id,
            by="you",
            change={"units": {key: {"component": "list", "variant": variant}}},
        )
        desk.make(episode_id, by="you", only=[key])

    def row() -> dict[str, Any]:
        found = house.store.picture(episode_id, key)
        assert found is not None
        return found

    drawn("horizontal")
    await settle(lambda: not desk._busy(episode_id))
    first = row()
    drawn("vertical")
    await settle(lambda: not desk._busy(episode_id))
    second = row()
    assert second["version"] == 2 and 'data-variant="vertical"' in second["html"]
    desk.undo(episode_id, by="you")
    back = row()
    assert (back["version"], back["html"]) == (1, first["html"])
    assert [k["n"] for k in back["versions"]] == [2]
    desk.redo(episode_id, by="you")
    again = row()
    assert (again["version"], again["html"]) == (2, second["html"])
    assert [k["n"] for k in again["versions"]] == [1]


async def test_named_recordings_persist_and_can_be_selected_without_losing_versions(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode_id = await planned(house)
    chapter = house.episodes.view(episode_id)["plan"]["chapters"][0]["id"]
    monkeypatch.setattr(
        house.episodes,
        "_cut",
        lambda *args: {"uhd": "", "video": "", "audio": "", "seconds": 5.0},
    )
    for label in ("  Calm delivery  ", "More energy"):
        view = await house.episodes.add_take(
            episode_id,
            by="you",
            chapter=chapter,
            label=label,
            name="take.webm",
            source=io.BytesIO(b"recording"),
        )
    first, second = view["takes"]
    assert [first["label"], second["label"]] == ["Calm delivery", "More energy"]
    reopened = Store(house.store.path)
    assert reopened.take(first["id"])["label"] == "Calm delivery"
    reopened.close()
    view = house.episodes.keep_take(episode_id, first["id"], keep=True)
    assert [t["kept"] for t in view["takes"]] == [True, False]
    assert len(view["takes"]) == 2
    with pytest.raises(KeyError):
        house.episodes.keep_take("another-episode", first["id"], keep=True)
    with pytest.raises(ValueError, match="120"):
        await house.episodes.add_take(
            episode_id,
            by="you",
            chapter=chapter,
            label="x" * 121,
            name="take.webm",
            source=io.BytesIO(b"recording"),
        )
    assert len(house.store.takes(episode_id)) == 2


# -- the production board -------------------------------------------------------------------------


class Held(DemoWorker):
    """The demo's writer, holding the turns named (an episode and a lane) until it is let go:
    each says the step it is on and begins a thought, as a slow model would."""

    def __init__(self, **given: Any) -> None:
        super().__init__(**given)
        self.held: set[tuple[str, str]] = set()
        self.holding: list[tuple[str, str]] = []
        self.release = asyncio.Event()

    async def _turn(self, episode: Any, *, lane: str, prompt: str, heard: Any) -> Told:
        turn = (str(episode["id"]), lane)
        if turn in self.held:
            heard("step", "Reading the brief")
            heard("thinking", "What comes first?")
            self.holding.append(turn)
            await self.release.wait()
        return await super()._turn(episode, lane=lane, prompt=prompt, heard=heard)


def jobs_of(board: dict[str, Any], episode_id: str) -> dict[str, dict[str, Any]]:
    """An episode's jobs on the production board, by unit (its script under "")."""
    return {j["unit"]: j for j in board["jobs"] if j["episode"] == episode_id}


def pictures_of(house: AgentHost, episode_id: str) -> list[str]:
    return [u["id"] for u in house.episodes.view(episode_id)["units"] if u["kind"] == "picture"]


async def test_the_production_board_lists_every_picture_as_a_job_with_where_it_stands(
    tmp_path: Path, house: AgentHost
) -> None:
    desk = house.episodes
    first = await made(house)
    second = await planned(house)
    posed, broken, drawn, other, queued, unasked = pictures_of(house, second)[:6]

    class Uneven(Held):
        async def _turn(self, episode: Any, *, lane: str, prompt: str, heard: Any) -> Told:
            if lane == f"picture:{broken}":
                return Told(failure="The model gave out.")
            return await super()._turn(episode, lane=lane, prompt=prompt, heard=heard)

    worker = Uneven(data_dir=tmp_path, script=SCRIPT, pause=0, store=house.store)
    worker.held = {(second, f"picture:{drawn}"), (second, f"picture:{other}")}
    desk.workers[DEMO] = worker
    # in the first episode, a made picture whose beat is now set another way, and one made for
    # words its line no longer says
    before = desk.view(first)
    old = before["units"][0]["id"]
    desk.choose(first, by="you", change={"units": {old: {"level": "rich"}}})
    said = next(u for u in before["units"][1:] if lines_of(before)[u["id"]].get("cues"))
    line = lines_of(before)[said["id"]]
    words = "Said my way: " + " and ".join(c["at"] for c in line["cues"]) + "."
    desk.edit(first, by="you", frame=line["id"], text=words)
    # in the second, one made as motion graphics, one that fails, two held while they are drawn
    # and one behind them; the rest is never asked for
    desk.choose(second, by="you", change={"units": {posed: {"level": "rich"}}})
    desk.make(second, by="you", only=[posed, broken, drawn, other, queued])
    await settle(lambda: len(worker.holding) == 2)
    board = desk.production()
    mine = jobs_of(board, second)
    stands = {posed: "go", broken: "failed", drawn: "running", other: "running", queued: "waiting"}
    assert {unit: mine[unit]["state"] for unit in stands} == stands
    assert {job["state"] for unit, job in mine.items() if unit not in stands} == {"todo"}
    # a plan in the studio with nothing of the writer's under way has no script to show
    assert set(mine) == set(pictures_of(house, second))
    never = mine[unasked]
    assert (never["what"], never["level"], never["stale"], never["still"]) == (
        "picture",
        "simple",
        False,
        None,
    )
    assert (never["agent"], never["model"], never["effort"], never["picked"]) == (
        DEMO,
        "",
        "",
        False,
    )
    assert [never[k] for k in ("asked_at", "started_at", "ended_at", "seconds")] == [None] * 4
    assert (never["tells"], never["heard_at"], never["pulse"]) == (True, None, None)
    # one waiting its turn says when it was asked for; one being drawn says its stage, the step
    # its builder is on and its turn's signs of life
    assert mine[queued]["asked_at"] and mine[queued]["started_at"] is None
    runs = mine[drawn]
    assert (runs["stage"], runs["doing"]) == ("draw", "Reading the brief")
    assert runs["asked_at"] <= runs["started_at"] and runs["ended_at"] is None
    pulse = runs["pulse"]
    assert (pulse["doing"], pulse["text"]) == ("thinking", "What comes first?")
    assert runs["tells"] and runs["heard_at"] == pulse["at"] and "lane" not in pulse
    # stills waiting on a go, and the one that stopped with why
    stills = mine[posed]
    assert stills["level"] == "rich" and stills["ended_at"] and stills["seconds"] is not None
    assert stills["still"].startswith("/api/files/") and stills["stage"] == ""
    assert (stills["agent"], stills["model"], stills["effort"]) == (DEMO, "demo", "Not applicable")
    assert mine[broken]["failure"] == "The model gave out." and mine[broken]["ended_at"]
    # the first episode's are made, but for the two that are out of date: those are to make again
    theirs = jobs_of(board, first)
    assert {unit for unit, job in theirs.items() if job["stale"]} == {old, said["id"]}
    assert {job["state"] for unit, job in theirs.items() if job["stale"]} == {"todo"}
    assert {job["state"] for unit, job in theirs.items() if not job["stale"]} == {"done"}
    # a picture is named by its episode and unit, with the beats of its chapter it plays over
    long = theirs["c2.b2.f1"]
    assert (long["id"], long["chapter"], long["kind"]) == (f"{first}:c2.b2.f1", "c2", "diagram")
    assert (long["beats"], long["lines"]) == ([2, 3, 4, 5], 4)
    assert long["shows"].startswith("A pipeline left to right")
    assert long["says"].startswith("A cache is a local store") and len(long["says"]) <= 160
    row = house.store.picture(first, "c2.b2.f1")
    assert row is not None and long["still"] == f"/api/files/{row['stills']['c2.b5.f1']}"
    assert [long[k] for k in ("started_at", "ended_at", "seconds")] == [
        row["timing"][k] for k in ("started_at", "ended_at", "seconds")
    ]
    # every episode, the newest first, with its channel and its chapters
    channel = house.store.channels()[0]
    assert [e["id"] for e in board["episodes"]] == [second, first]
    episode = board["episodes"][0]
    assert (episode["title"], episode["status"], episode["writer"]) == ("One idea", "studio", DEMO)
    assert (episode["channel_id"], episode["channel"]) == (channel["id"], channel["name"])
    asked = SCRIPT["plan"]["chapters"]
    assert episode["chapters"] == [
        {"id": c["id"], "n": n, "question": c["question"]} for n, c in enumerate(asked, 1)
    ]
    worker.release.set()
    await settle(lambda: not desk._busy(second))


async def test_the_production_board_shows_a_script_while_it_is_written_or_waits_on_the_person(
    tmp_path: Path, house: AgentHost
) -> None:
    class Moody(Held):
        fails = False

        async def _turn(self, episode: Any, *, lane: str, prompt: str, heard: Any) -> Told:
            if self.fails and lane == "plan":
                return Told(failure="It isn't signed in.")
            return await super()._turn(episode, lane=lane, prompt=prompt, heard=heard)

    desk = house.episodes
    worker = Moody(data_dir=tmp_path, script=SCRIPT, pause=0, store=house.store)
    desk.workers[DEMO] = worker
    approved = await made(house)
    ready = await planned(house)
    worker.fails = True
    stopped = await planned(house)
    worker.fails = False
    channel = house.store.channels()[0]["id"]
    writing = str(desk.create(channel, by="you", text=NOTES, settings={"writer": DEMO})["id"])
    worker.held = {(writing, "plan")}
    await settle(lambda: len(worker.holding) == 1)
    board = desk.production()
    scripts = {j["episode"]: j for j in board["jobs"] if j["what"] == "script"}
    # none for the plan that stands approved with nothing under way
    assert {episode_id: job["state"] for episode_id, job in scripts.items()} == {
        ready: "go",
        stopped: "failed",
        writing: "running",
    }
    waits = scripts[ready]
    assert (waits["id"], waits["kind"], waits["unit"], waits["chapter"]) == (
        f"{ready}:script",
        "script",
        "",
        "",
    )
    assert (waits["agent"], waits["model"], waits["effort"]) == (DEMO, "", "")
    assert waits["started_at"] == desk._episode(ready)["stage"]["at"]
    assert (waits["heard_at"], waits["pulse"], waits["failure"]) == (None, None, "")
    assert "signed in" in scripts[stopped]["failure"]
    # the one being written says the step its writer is on, and its turn's signs of life
    runs = scripts[writing]
    assert (runs["doing"], runs["tells"]) == ("Reading the brief", True)
    assert runs["pulse"]["doing"] == "thinking" and runs["heard_at"] == runs["pulse"]["at"]
    # only a plan in the studio has pictures to make
    assert {j["episode"] for j in board["jobs"] if j["what"] == "picture"} == {approved}
    # every episode is listed, the newest first, with its chapters once its plan has them
    assert [(e["id"], e["status"], len(e["chapters"])) for e in board["episodes"]] == [
        (writing, "planning", 0),
        (stopped, "failed", 0),
        (ready, "plan", 7),
        (approved, "studio", 7),
    ]
    # a change the writer makes to a plan that stands is its script under way, beside its pictures
    worker.held.add((approved, "plan"))
    desk.ask(approved, by="you", scope="film", text="Open faster.")
    await settle(lambda: len(worker.holding) == 2)
    changing = jobs_of(desk.production(), approved)
    assert changing[""]["state"] == "running" and changing[""]["doing"] == "Reading the brief"
    assert {job["what"] for unit, job in changing.items() if unit} == {"picture"}
    worker.release.set()
    await settle(lambda: not desk.planning(writing) and not desk.planning(approved))


async def test_a_job_under_way_says_when_its_turn_was_last_heard_from(house: AgentHost) -> None:
    desk = house.episodes
    episode_id = await made(house)
    unit = pictures_of(house, episode_id)[0]
    lane = f"picture:{unit}"
    thread = str(desk._episode(episode_id)["thread_id"])

    def job() -> dict[str, Any]:
        return jobs_of(desk.production(), episode_id)[unit]

    # as a build leaves it between two turns: under way, with no turn to hear from
    house.store.set_picture(episode_id, unit, status="making")
    assert (job()["state"], job()["heard_at"], job()["tells"]) == ("running", None, True)
    # a turn that has said nothing yet was heard from when it began
    turn = house.store.add_run(
        thread_id=thread, lane=lane, harness="kimi", prompt="Stage: picture.", session=""
    )
    began = turn["started_at"]
    quiet = job()
    assert (quiet["stage"], quiet["doing"], quiet["pulse"]) == ("draw", "", None)
    assert quiet["heard_at"] == began and not quiet["tells"], "Kimi Code says nothing as it thinks"
    # then at its newest event or its pulse, whichever is later
    step = {"kind": "step", "text": "Editing compositions/p.html", "at": began + 5}
    house.store.update_run(str(turn["id"]), steps=[step])
    house.store.pulses[str(turn["id"])] = {
        "lane": lane,
        "at": began + 3,
        "doing": "thinking",
        "text": "Which way round?",
        "amount": 300,
        "since": began + 3,
    }
    assert (job()["doing"], job()["heard_at"]) == ("Editing compositions/p.html", began + 5)
    house.store.pulses[str(turn["id"])]["at"] = began + 9
    heard = job()
    assert heard["heard_at"] == began + 9 and heard["pulse"] == {
        "at": began + 9,
        "doing": "thinking",
        "text": "Which way round?",
        "amount": 300,
        "since": began + 3,
    }
    # a turn that ended is no longer heard from
    house.store.update_run(str(turn["id"]), state="done")
    assert (job()["heard_at"], job()["pulse"], job()["doing"]) == (None, None, "")


async def test_the_production_board_counts_each_agents_jobs_and_says_how_long_its_pictures_take(
    tmp_path: Path, house: AgentHost
) -> None:
    desk = house.episodes
    first, second = await made(house), await made(house)
    # every made picture with how long its build took, each newer and slower than the one before
    built = [
        (episode_id, unit)
        for episode_id in (first, second)
        for unit in pictures_of(house, episode_id)
    ]
    for n, (episode_id, unit) in enumerate(built, 1):
        timing = {"started_at": 1000.0 * n, "ended_at": 1000.0 * n + n, "seconds": float(n)}
        house.store.set_picture(episode_id, unit, timing=timing)
    # stills waiting on a go were built too; a build that failed made no picture
    house.store.set_picture(*built[-2], status="go")
    house.store.set_picture(*built[-1], status="failed")
    # two pictures of a third episode held while they are drawn, three behind them, and a
    # fourth episode's script being written
    third = await planned(house)
    units = pictures_of(house, third)
    worker = Held(data_dir=tmp_path, script=SCRIPT, pause=0, store=house.store)
    worker.held = {(third, f"picture:{unit}") for unit in units[:2]}
    desk.workers[DEMO] = worker
    desk.make(third, by="you", only=units[:5])
    channel = house.store.channels()[0]["id"]
    fourth = str(desk.create(channel, by="you", text=NOTES, settings={"writer": DEMO})["id"])
    worker.held.add((fourth, "plan"))
    await settle(lambda: len(worker.holding) == 3)
    agents = {agent["id"]: agent for agent in desk.production()["agents"]}
    assert list(agents) == ["claude", "codex", "kimi", DEMO], "every agent, ready here or not"
    demo = agents[DEMO]
    # its jobs across the house; and the mean of its newest twenty made pictures (8 to 27)
    assert (demo["running"], demo["waiting"], demo["seconds"]) == (3, 3, 17.5)
    assert demo["ready"] and demo["title"] == "HTTP caching sample"
    assert demo["models"] == [{"id": "", "name": "demo", "efforts": []}]
    offered = desk.options()["generation_models"]
    for agent_id in ("claude", "codex", "kimi"):
        idle = agents[agent_id]
        assert (idle["running"], idle["waiting"], idle["seconds"]) == (0, 0, None)
        assert idle["models"] == offered[agent_id] and idle["title"] == HARNESSES[agent_id].title
    worker.release.set()
    await settle(lambda: not desk._busy(third) and not desk.planning(fourth))


async def test_the_production_board_is_one_light_read_however_many_pictures_there_are(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    desk = house.episodes
    first, second = await made(house), await made(house)
    asked: list[tuple[str, str]] = []
    listed: list[None] = []
    generation, options = desk._generation, desk.options

    def one_pick(builder: str, pick: Any) -> Any:
        asked.append((builder, pick.get("model", "")))
        return generation(builder, pick)

    def one_listing() -> Any:
        listed.append(None)
        return options()

    def studio(episode_id: str) -> Any:
        raise AssertionError("the board never reads an episode's whole studio")

    monkeypatch.setattr(desk, "_generation", one_pick)
    monkeypatch.setattr(desk, "options", one_listing)
    monkeypatch.setattr(desk, "view", studio)
    board = desk.production()
    assert len(board["jobs"]) == len(house.store.pictures(first)) + len(
        house.store.pictures(second)
    )
    # what the agents offer is listed once, and an agent is asked what a pick runs on once
    assert len(listed) == 1 and asked == [(DEMO, "")]


async def test_pictures_of_several_episodes_are_handed_to_an_agent_and_started(
    tmp_path: Path, house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Other(DemoWorker):
        id = "codex"
        title = "Codex"

    desk = house.episodes
    desk.workers["codex"] = Other(data_dir=tmp_path, script=SCRIPT, pause=0)
    one, two = await planned(house), await planned(house)
    a, b, c, d = pictures_of(house, one)[:4]

    def picks(episode_id: str) -> dict[str, Any]:
        return dict(desk._episode(episode_id)["picks"].get("units", {}))

    handed = desk.assign([(one, a), (one, b), (two, a)], by="you", agent="codex")
    assert handed == {"started": [f"{one}:{a}", f"{one}:{b}", f"{two}:{a}"], "refused": []}
    await settle(lambda: not desk._busy(one) and not desk._busy(two))
    rows = {(e, str(p["unit"])): p for e in (one, two) for p in house.store.pictures(e)}
    assert set(rows) == {(one, a), (one, b), (two, a)}, "the rest was never asked for"
    assert {(p["status"], p["builder"]) for p in rows.values()} == {("made", "codex")}
    # each took the agent alone as its own pick, so it runs on the agent's default
    assert picks(one) == {a: {"builder": "codex"}, b: {"builder": "codex"}}
    # made and up to date, a picture handed over again is left as it is
    assert desk.assign([(one, a)], by="you", agent="codex") == {"started": [], "refused": []}
    # an episode that refuses says why, and the others' pictures are started all the same
    mixed = desk.assign([(one, "c9.b9.f9"), (two, b), ("ep_gone", a)], by="you", agent="codex")
    assert mixed == {
        "started": [f"{two}:{b}"],
        "refused": [
            {"episode": one, "reason": "That picture is no longer in this episode."},
            {"episode": "ep_gone", "reason": "That episode is no longer here."},
        ],
    }
    await settle(lambda: not desk._busy(two))
    # with no agent each keeps the one it is set to, and is only started
    assert desk.assign([(one, c)], by="you") == {"started": [f"{one}:{c}"], "refused": []}
    await settle(lambda: not desk._busy(one))
    assert house.store.picture(one, c)["builder"] == DEMO and c not in picks(one)  # type: ignore[index]
    assert desk.assign([(one, "c9.b9.f9")], by="you") == {
        "started": [],
        "refused": [{"episode": one, "reason": "There is no picture to make there."}],
    }
    # a model and an effort picked on the board go with every picture handed over
    on = {"model": "gpt-6.1-sol", "effort": "high"}
    assert desk.assign([(one, d)], by="you", agent="codex", **on)["started"] == [f"{one}:{d}"]
    await settle(lambda: not desk._busy(one))
    assert picks(one)[d] == {"builder": "codex", **on}
    job = jobs_of(desk.production(), one)[d]
    assert (job["state"], job["agent"], job["picked"]) == ("done", "codex", True)
    assert (job["model"], job["effort"]) == ("gpt-6.1-sol", "high"), "what it was made on"
    # handed to the agent it is with and nothing picked, it keeps what it runs on: nothing to make
    assert desk.assign([(one, d)], by="you", agent="codex") == {"started": [], "refused": []}
    assert picks(one)[d] == {"builder": "codex", **on}
    # handed over with another model, it takes that one and is made again on it
    again = desk.assign([(one, d)], by="you", agent="codex", model="gpt-5.6-sol")
    assert again["started"] == [f"{one}:{d}"]
    await settle(lambda: not desk._busy(one))
    assert picks(one)[d] == {"builder": "codex", "model": "gpt-5.6-sol"}
    assert house.store.picture(one, d)["generation"]["model"] == "gpt-5.6-sol"  # type: ignore[index]
    # handed to another agent with nothing picked, it runs on that agent's default
    assert desk.assign([(one, d)], by="you", agent=DEMO, start=False)["started"] == []
    assert picks(one)[d] == {"builder": DEMO}
    # one handed over and not started is still to make, set to the agent on what was picked
    assert desk.assign([(two, c)], by="you", agent="codex", start=False, **on)["started"] == []
    todo = jobs_of(desk.production(), two)[c]
    assert (todo["state"], todo["agent"], todo["picked"]) == ("todo", "codex", True)
    assert (todo["model"], todo["effort"]) == ("gpt-6.1-sol", "high")
    # nothing to hand over, an agent that is not set up here, a model the agent does not offer
    monkeypatch.setattr(house.research, "ready", lambda name: False)
    with pytest.raises(ValueError, match="no picture to hand over"):
        desk.assign([], by="you", agent="codex")
    with pytest.raises(ValueError, match="isn't ready on this computer"):
        desk.assign([(one, a)], by="you", agent="kimi")
    with pytest.raises(ValueError, match="supported model"):
        desk.assign([(one, a)], by="you", agent="codex", model="gpt-0")
    assert picks(one)[a] == {"builder": "codex"}, "a refusal changes nothing"


async def test_one_agents_pictures_wait_their_turn_across_the_house_and_a_stopped_one_leaves_the_line(
    tmp_path: Path, house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(episode_desk, "HOUSE_AT_ONCE", 1)
    desk = house.episodes
    one, two = await planned(house), await planned(house)
    first, second, third = pictures_of(house, one)[:3]
    worker = Held(data_dir=tmp_path, script=SCRIPT, pause=0, store=house.store)
    worker.held = {(one, f"picture:{first}")}
    desk.workers[DEMO] = worker
    began: list[tuple[str, str]] = []
    inside: set[tuple[str, str]] = set()
    at_once: list[int] = []
    build = desk._build

    async def counted(episode_id: str, unit_id: str, note: str = "", **more: Any) -> None:
        began.append((episode_id, unit_id))
        inside.add((episode_id, unit_id))
        at_once.append(len(inside))
        try:
            await build(episode_id, unit_id, note, **more)
        finally:
            inside.discard((episode_id, unit_id))

    monkeypatch.setattr(desk, "_build", counted)

    def row(job: tuple[str, str]) -> dict[str, Any]:
        found = house.store.picture(*job)
        assert found is not None
        return found

    for episode_id in (one, two):
        desk.make(episode_id, by="you", only=[first, second, third])
    await settle(lambda: len(worker.holding) == 1)
    # one is being drawn; every other waits, whichever line it stands in, and says so
    board = desk.production()
    states = {(j["episode"], j["unit"]): j["state"] for j in board["jobs"]}
    asked = [(e, u) for e in (one, two) for u in (first, second, third)]
    assert [states[job] for job in asked] == ["running", *["waiting"] * 5]
    assert all(row(job)["status"] == "queued" for job in asked[1:])
    demo = next(agent for agent in board["agents"] if agent["id"] == DEMO)
    assert (demo["running"], demo["waiting"]) == (1, 5)
    # one stopped in the house's line, and one in its own episode's
    stopped = [(two, first), (one, third)]
    for job in stopped:
        desk.stop(*job)
    await settle(lambda: all(row(job)["status"] == "failed" for job in stopped))
    worker.release.set()
    await settle(lambda: not desk._busy(one) and not desk._busy(two))
    # never two of the agent's at once, each begun in the order it came to the line: an
    # episode's third joins it once one of its first two is out of the way
    assert max(at_once) == 1
    assert began == [(one, first), (one, second), (two, second), (two, third)]
    assert all(row(job)["failure"] == "Stopped." for job in stopped)
    assert all(row(job)["status"] == "made" for job in began)
    # the line moves on behind the ones that left it: asked for again, they are built
    for job in stopped:
        desk.make(job[0], by="you", only=[job[1]])
    await settle(lambda: not desk._busy(one) and not desk._busy(two))
    assert all(row(job)["status"] == "made" for job in asked) and max(at_once) == 1


def test_the_app_serves_the_production_board_and_hands_its_jobs_to_an_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(_env_file=None, workspace_root=tmp_path / "workspace", sandbox="host")
    with TestClient(create_app(ROOT, settings, demo=True)) as client:
        host = client.app.state.host  # type: ignore[attr-defined]
        desk = host.episodes
        # a writer that does not pause, pictures posed without a computer, and no coding agent
        # counted as installed here
        desk.workers[DEMO] = DemoWorker(
            data_dir=desk.data_dir, script=SCRIPT, pause=0, store=host.store
        )
        monkeypatch.setattr(desk, "_pose", lambda episode, unit, full, html, strict=True: ([], {}))
        monkeypatch.setattr(desk, "_clip", lambda episode, unit: "")
        monkeypatch.setattr(host.research, "ready", lambda name: False)

        def board(done: Any = None) -> dict[str, Any]:
            """The board as it is, or as it is once `done` holds."""
            until = time.time() + 30
            while True:
                read: dict[str, Any] = client.get("/api/production").json()
                if done is None or done(read) or time.time() > until:
                    return read
                time.sleep(0.05)

        empty = board()
        assert (empty["episodes"], empty["jobs"]) == ([], [])
        assert {a["id"]: a["ready"] for a in empty["agents"]} == {
            "claude": False,
            "codex": False,
            "kimi": False,
            DEMO: True,
        }
        channel = client.get("/api/channels").json()[0]
        made = client.post(
            f"/api/channels/{channel['id']}/episodes",
            json={"title": "One idea", "text": NOTES, "settings": {"writer": DEMO}},
        )
        episode_id = made.json()["id"]
        written = board(lambda read: jobs_of(read, episode_id).get("", {}).get("state") == "go")
        assert [j["id"] for j in written["jobs"]] == [f"{episode_id}:script"]
        (episode,) = written["episodes"]
        assert (episode["id"], episode["channel"]) == (episode_id, channel["name"])
        assert (episode["status"], len(episode["chapters"])) == ("plan", 7)
        unit = client.get(f"/api/episodes/{episode_id}").json()["units"][0]["id"]
        job = {"episode": episode_id, "unit": unit}
        # nothing named, an agent that is not set up here or not one at all, a model not offered
        hand = "/api/production/assign"
        assert client.post(hand, json={"jobs": []}).status_code == 422
        unready = client.post(hand, json={"jobs": [job], "agent": "kimi"})
        assert unready.status_code == 422 and "isn't ready" in unready.json()["detail"]
        assert client.post(hand, json={"jobs": [job], "agent": "gpt"}).status_code == 422
        unknown = client.post(hand, json={"jobs": [job], "agent": DEMO, "model": "gpt-0"})
        assert unknown.status_code == 422 and "supported model" in unknown.json()["detail"]
        # a job is handed over and started; an episode that is gone is refused by name
        handed = client.post(
            hand, json={"jobs": [job, {"episode": "ep_gone", "unit": unit}], "agent": DEMO}
        )
        assert handed.status_code == 200, handed.text
        assert handed.json() == {
            "started": [f"{episode_id}:{unit}"],
            "refused": [{"episode": "ep_gone", "reason": "That episode is no longer here."}],
        }
        drawn = board(lambda read: jobs_of(read, episode_id).get(unit, {}).get("state") == "done")
        mine = jobs_of(drawn, episode_id)
        assert mine[unit]["state"] == "done" and mine[unit]["agent"] == DEMO
        # the studio is open, so the script is no job any more and the other pictures are to make
        assert "" not in mine and {j["state"] for u, j in mine.items() if u != unit} == {"todo"}
        assert drawn["episodes"][0]["status"] == "studio"


async def test_the_built_in_agent_builds_one_picture_at_a_time_across_the_house(
    tmp_path: Path, house: AgentHost
) -> None:
    class BuiltIn(Held):
        id = BUILTIN

    desk = house.episodes
    worker = BuiltIn(data_dir=tmp_path, script=SCRIPT, pause=0)
    desk.workers[BUILTIN] = worker
    one, two = await planned(house), await planned(house)
    unit = pictures_of(house, one)[0]
    worker.held = {(one, f"picture:{unit}")}
    for episode_id in (one, two):
        handed = desk.assign([(episode_id, unit)], by="you", agent=BUILTIN)
        assert handed == {"started": [f"{episode_id}:{unit}"], "refused": []}
    await settle(lambda: len(worker.holding) == 1)
    # one at a time for this agent, whatever the house lets the others build at once
    board = desk.production()
    assert jobs_of(board, one)[unit]["state"] == "running"
    assert jobs_of(board, two)[unit]["state"] == "waiting"
    worker.release.set()
    await settle(lambda: not desk._busy(one) and not desk._busy(two))
    built = [house.store.picture(episode_id, unit) for episode_id in (one, two)]
    assert [(p["status"], p["builder"]) for p in built if p] == [("made", BUILTIN)] * 2


async def test_private_storage_keeps_original_take_under_its_account_and_refuses_failed_save(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    from design_agent.surfaces.web.blobs import BlobFiles, StorageUnavailable

    class Storage:
        def __init__(self):
            self.stored: dict[str, bytes] = {}
            self.offline = False

        def upload_fileobj(self, source, bucket, key, **kwargs):
            assert bucket == "recordings"
            if self.offline:
                raise OSError("offline")
            self.stored[key] = source.read()

    client = Storage()
    namespace = "a" * 32
    house.blobs = BlobFiles(
        Settings(_env_file=None, blob_backend="s3", s3_bucket="recordings"),
        house.files_dir,
        namespace,
        client=client,
    )
    episode_id = await planned(house)
    chapter = house.episodes.view(episode_id)["plan"]["chapters"][0]["id"]
    monkeypatch.setattr(
        house.episodes, "_cut", lambda *args: {"video": "", "audio": "", "uhd": "", "seconds": 15}
    )

    async def record(data: bytes):
        return await house.episodes.add_take(
            episode_id, by="you", chapter=chapter, name="original.mp4", source=io.BytesIO(data)
        )

    await record(b"original take")
    (take,) = house.store.takes(episode_id)
    (key,) = client.stored
    assert key.startswith(f"accounts/{namespace}/blobs/")
    assert take["raw"] == f"s3://recordings/{key}"
    assert client.stored[key] == b"original take"
    assert not list(house.files_dir.rglob("*.mp4"))

    client.offline = True
    with pytest.raises(StorageUnavailable):
        await record(b"failed retake")
    assert house.store.takes(episode_id) == [take]


async def test_episode_reads_material_and_take_audio_through_blob_storage(
    house: AgentHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    channel = house.store.channels()[0]["id"]
    material = house.save_file("", "source.md", b"Useful material", origin="upload")
    material_path = house.files_dir / material["rel_path"]
    material_path.unlink()
    monkeypatch.setattr(house.blobs, "read", lambda row: b"Useful material")
    view = house.episodes.create(
        channel, by="you", file_ids=[material["id"]], settings={"writer": DEMO}
    )
    assert "Useful material" in house.store.episode(view["id"])["material"]
    house.store.add_take(
        {
            "episode_id": view["id"],
            "chapter": "c1",
            "frame": "",
            "seconds": 8,
            "audio": material["id"],
            "added_by": "you",
        }
    )
    assert house.episodes._samples(view["id"]) == ([("source.md", b"Useful material")], 8)
