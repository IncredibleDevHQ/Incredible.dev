"""An episode's plan as code handles it: the three hands kept apart, the reading, the checks,
the clock, a person's picks, the built pictures and the film's page."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from design_agent.episode import (
    check,
    classifier,
    classify,
    derive,
    film,
    geometry,
    layouts,
    override,
    picture,
    sketch,
    timeline,
    units,
)
from design_agent.episode import plan as plans
from design_agent.episode import questions as Q
from design_agent.episode.doc import types_markdown

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "src" / "design_agent" / "surfaces" / "web" / "demo_episode.json"
Row = dict[str, Any]


@pytest.fixture(scope="module")
def script() -> Row:
    loaded: Row = json.loads(FIXTURE.read_text(encoding="utf8"))
    return loaded


@pytest.fixture
def merged(script: Row) -> Row:
    return plans.merged(script["plan"], script["labels"])


@pytest.fixture
def full(merged: Row) -> Row:
    return derive.full(merged)


def first_option(state: Any, questions: Row) -> Row:
    """A reader that takes the first option of every question."""
    out: Row = {}
    for key, question in questions.items():
        if question["type"] == "noul":
            out[key] = {"noul": 0.9}
        else:
            first = next(iter(question["criteria"]))
            out[key] = {"choice": first, "confidence": 0.9, "probabilities": {first: 0.9}}
    return out


# -- the three hands ------------------------------------------------------------------------------


def test_merging_never_changes_the_writers_plan(script: Row) -> None:
    before = copy.deepcopy(script["plan"])
    merged = plans.merged(script["plan"], script["labels"])
    merged["brief"]["idea"] = "changed"
    assert script["plan"] == before


def test_labels_survive_a_round_trip_and_drop_when_words_change(script: Row) -> None:
    merged = plans.merged(script["plan"], script["labels"])
    assert plans.labels_of(merged) == script["labels"]
    edited = copy.deepcopy(script["plan"])
    beat = edited["chapters"][0]["beats"][0]
    beat["says"] += " And one more sentence."
    again = plans.merged(edited, script["labels"])
    changed = again["chapters"][0]["beats"][0]
    assert "subtype" not in changed, "a line that changed is unlabelled until it is read again"
    assert "subtype" in again["chapters"][0]["beats"][1]


def test_the_demo_plan_passes_its_own_checks(merged: Row) -> None:
    rows = check.check(merged, "all")
    assert not check.musts(rows), check.lines(rows, "all")


def test_a_script_lands_inside_the_length_asked_for_or_no_length_is_checked(merged: Row) -> None:
    words = sum(len(plans.toks(b.get("says", ""))) for _, b in plans.beats_of(merged))

    def with_length(seconds: list[int] | None) -> Row:
        plan = copy.deepcopy(merged)
        plan["brief"].pop("seconds")
        if seconds:
            plan["brief"]["seconds"] = seconds
        return plan

    def length(seconds: list[int] | None) -> list[Row]:
        return [r for r in check.check(with_length(seconds), "script") if r["rule"] == "length"]

    # the least and the most, less the five-second end card, at 2.6 words a second
    assert merged["brief"]["seconds"] == [300, 420]
    assert layouts.word_budget(merged) == (767, 1079) and 767 <= words <= 1079
    assert not length([300, 420])
    assert "is 767 to 1079 words; the script has" in classify.budget(merged)
    (short,) = length([420, 540])
    assert short["level"] == "must" and f"add at least {1079 - words}" in short["text"]
    (long,) = length([240, 270])
    assert long["level"] == "must" and f"cut at least {words - 689}" in long["text"]
    # left to the material: no budget, and nothing about length is checked
    assert layouts.word_budget(with_length(None)) is None and not length(None)
    assert classify.budget(with_length(None)).startswith("no length was asked for")


def test_the_page_a_writer_reads_is_the_lists_the_classifier_is_asked() -> None:
    page = (ROOT / "skills" / "episode" / "references" / "types.md").read_text(encoding="utf8")
    assert page == types_markdown()


# -- reading the words ----------------------------------------------------------------------------


def test_a_plan_is_read_stage_by_stage_and_only_what_is_new_is_asked(script: Row) -> None:
    asked: list[str] = []

    def reader(state: Any, questions: Row) -> Row:
        asked.extend(questions)
        return first_option(state, questions)

    merged = plans.merged(script["plan"], {})
    said = classify.classify(merged, "material", reader)
    assert any(line.startswith("route:") for line in said)
    assert all("kind" in m for m in merged["material"])
    count = len(asked)
    classify.classify(merged, "material", reader)
    assert len(asked) == count, "what is already labelled is not asked again"


def test_a_reader_that_takes_many_items_is_given_them_together(script: Row) -> None:
    batches: list[int] = []

    def many(jobs: list[tuple[str, Any, Row]]) -> dict[str, Row]:
        batches.append(len(jobs))
        return {key: first_option(state, qs) for key, state, qs in jobs}

    first_option.many = many  # type: ignore[attr-defined]
    try:
        merged = plans.merged(script["plan"], {})
        classify.classify(merged, "material", first_option)
    finally:
        del first_option.many  # type: ignore[attr-defined]
    assert batches and batches[0] == len(script["plan"]["material"])


def test_the_model_reader_holds_answers_to_the_lists() -> None:
    questions = {
        "kind": Q.choice("What is it?", {"fact": "A fact", "step": "A step"}),
        "ok": Q.noul("Is it?", "yes", "no"),
    }
    reply = json.dumps({"kind": {"top": [["step", 0.7], ["nonsense", 0.9]]}, "ok": {"yes": 0.8}})
    answers = classifier.model(lambda _prompt: f"```json\n{reply}\n```")({"note": "x"}, questions)
    assert (
        answers["kind"]["choice"] == "step" and "nonsense" not in answers["kind"]["probabilities"]
    )
    assert answers["ok"] == {"noul": 0.8}
    with pytest.raises(classifier.ClassifierError):
        classifier.model(lambda _prompt: '{"kind": {"top": [["nonsense", 1]]}, "ok": {"yes": 1}}')(
            {}, questions
        )


def test_the_model_reader_batches_and_reports_an_item_it_could_not_read() -> None:
    questions = {"kind": Q.choice("What is it?", {"fact": "A fact", "step": "A step"})}
    prompts: list[str] = []

    def complete(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps({"a": {"kind": {"top": [["fact", 0.9]]}}})

    reader = classifier.model(complete, batch=5)
    out = reader.many([("a", {"n": 1}, questions), ("b", {"n": 2}, questions)])  # type: ignore[attr-defined]
    assert len(prompts) == 1 and prompts[0].count("Q1:") == 1, "one prompt, each question set once"
    assert out["a"]["kind"]["choice"] == "fact" and "error" in out["b"]


def test_jev_is_asked_with_the_key_and_never_says_it() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"answers": {"kind": {"choice": "fact", "confidence": 1}}})

    ask = classifier.jev("secret-key", transport=httpx.MockTransport(handler))
    assert ask({"note": "x"}, {"kind": {"type": "choice"}})["kind"]["choice"] == "fact"
    assert seen["auth"] == "Bearer secret-key" and seen["body"]["state"] == {"note": "x"}
    refused = classifier.jev(
        "secret-key", transport=httpx.MockTransport(lambda _r: httpx.Response(401)), tries=1
    )
    with pytest.raises(classifier.ClassifierError) as failure:
        refused({}, {})
    assert "secret-key" not in str(failure.value)


# -- the clock ------------------------------------------------------------------------------------


def test_code_writes_every_time(full: Row) -> None:
    totals = full["totals"]
    frames = [f for ch in full["chapters"] for b in ch["beats"] for f in b["frames"]]
    assert totals["frames"] == len(frames) and all("start" in f and "seconds" in f for f in frames)
    assert frames[0]["start"] <= frames[1]["start"]
    cues = [c for f in frames for c in f.get("cues", [])]
    assert cues and all("t" in c for c in cues)
    assert not any(key.startswith("_") for key in full), "working keys stay out of the full plan"


def test_the_plans_clock_gives_way_to_a_takes(full: Row) -> None:
    planned = timeline.schedule(full)
    chapter = full["chapters"][1]
    lines = [f for b in chapter["beats"] for f in b["frames"]]
    marks = [{"frame": f["id"], "t": 2.0 * i} for i, f in enumerate(lines)]
    take = {
        "id": "tk_1",
        "chapter": chapter["id"],
        "frame": "",
        "seconds": 2.0 * len(lines),
        "marks": marks,
    }
    clock = timeline.schedule(full, [take])
    for i, f in enumerate(lines):
        line = timeline.line_of(clock, f["id"])
        assert line is not None and line["seconds"] == pytest.approx(2.0)
        assert line["source"] == {"kind": "take", "take": "tk_1", "offset": pytest.approx(2.0 * i)}
    first = timeline.line_of(clock, full["chapters"][0]["beats"][0]["frames"][0]["id"])
    assert first is not None and first["source"]["kind"] == "plan"
    assert clock["total"] != planned["total"]
    # a cue keeps its place in its line, however long the line was said for
    with_cue = next(f for f in lines if f.get("cues"))
    line = timeline.line_of(clock, with_cue["id"])
    assert line is not None
    at = clock["cues"][f"{with_cue['id']}/0"]
    assert line["start"] <= at <= line["start"] + line["seconds"]


def test_a_line_of_its_own_wins_over_its_chapters_take_and_narration_lands_on_words(
    full: Row,
) -> None:
    chapter = full["chapters"][1]
    lines = [f for b in chapter["beats"] for f in b["frames"]]
    whole = {
        "id": "tk_1",
        "chapter": chapter["id"],
        "frame": "",
        "seconds": 60.0,
        "marks": [{"frame": f["id"], "t": 3.0 * i} for i, f in enumerate(lines)],
    }
    own = {
        "id": "tk_2",
        "chapter": chapter["id"],
        "frame": lines[1]["id"],
        "seconds": 7.5,
        "marks": [],
    }
    clock = timeline.schedule(full, [whole, own])
    line = timeline.line_of(clock, lines[1]["id"])
    assert line is not None and line["source"]["take"] == "tk_2" and line["seconds"] == 7.5

    spoken_line = next(
        f for ch in full["chapters"] for b in ch["beats"] for f in b["frames"] if f.get("cues")
    )
    cue_word = plans.toks(spoken_line["cues"][0]["at"])[0]
    words = [
        {"word": "Well", "start": 0.0, "end": 0.3},
        {"word": cue_word, "start": 1.5, "end": 1.9},
    ]
    voiced = timeline.schedule(full, [], {spoken_line["id"]: {"seconds": 4.0, "words": words}})
    line = timeline.line_of(voiced, spoken_line["id"])
    assert line is not None and line["source"]["kind"] == "voice"
    if len(plans.toks(spoken_line["cues"][0]["at"])) == 1:
        assert voiced["cues"][f"{spoken_line['id']}/0"] == pytest.approx(
            line["start"] + 1.5 - timeline.LEAD
        )


# -- a person's picks -----------------------------------------------------------------------------


def test_a_pick_is_kept_beside_the_plan_and_says_what_it_leaves_the_writer(script: Row) -> None:
    merged = plans.merged(script["plan"], script["labels"])
    to_camera = next(
        f for _, _, f in plans.frames_of(merged) if f["presence"] == "person" and not f.get("hold")
    )
    feedback = override.apply(merged, {"frames": {to_camera["id"]: {"presence": "content"}}})
    changed = next(x for x in feedback if x["where"] == to_camera["id"])
    assert changed["now"].startswith("content") and override.redo(feedback) == [changed]
    labels = plans.labels_of(merged)
    again = plans.merged(script["plan"], labels)
    frame = next(f for _, _, f in plans.frames_of(again) if f["id"] == to_camera["id"])
    assert frame["presence"] == "content" and frame["override"]["was"]["presence"] == "person"
    cleared = plans.merged(script["plan"], labels)
    override.apply(cleared, {"clear": [to_camera["id"]]})
    frame = next(f for _, _, f in plans.frames_of(cleared) if f["id"] == to_camera["id"])
    assert frame["presence"] == "person" and "override" not in frame


def test_a_layout_for_the_chapter_or_the_film_reaches_the_lines_of_one_presence(
    script: Row,
) -> None:
    merged = plans.merged(script["plan"], script["labels"])
    before = {f["id"]: (f["presence"], f["layout"]) for _, _, f in plans.frames_of(merged)}
    chapter = next(
        ch
        for ch in merged["chapters"]
        if sum(1 for b in ch["beats"] for f in b["frames"] if f["presence"] == "both") > 1
    )
    feedback = override.apply(merged, {"chapters": {chapter["id"]: {"layouts": {"both": "split"}}}})
    assert override.redo(feedback) == [], "nobody's place changes, so the writer has nothing to do"
    inside = {f["id"] for b in chapter["beats"] for f in b["frames"]}
    for _, _, f in plans.frames_of(merged):
        was_presence, was_layout = before[f["id"]]
        assert f["presence"] == was_presence
        if f["id"] in inside and was_presence == "both":
            assert f["layout"] == "split"
            if not f.get("hold"):
                assert f["override"]["scope"] == "chapter"
                assert f["override"]["was"]["layout"] == was_layout
        else:
            assert f["layout"] == was_layout
    # the film's reaches every chapter; a line's own pick still wins; null takes one back
    own = next(
        f["id"]
        for _, _, f in plans.frames_of(merged)
        if f["id"] not in inside and f["presence"] == "both" and not f.get("hold")
    )
    kept = plans.merged(script["plan"], plans.labels_of(merged))
    override.apply(
        kept,
        {
            "all": {"layouts": {"both": "split"}},
            "chapters": {chapter["id"]: {"layouts": {"both": None}}},
            "frames": {own: {"layout": "corner-window"}},
        },
    )
    for _, _, f in plans.frames_of(kept):
        if f["presence"] == "both" and not f.get("hold"):
            assert f["layout"] == ("corner-window" if f["id"] == own else "split")
            if f["id"] != own:
                assert f["override"]["scope"] == "film"
    assert chapter["id"] not in kept["_overrides"].get("chapters", {})
    override.apply(kept, {"all": {"layouts": {"both": None}}, "clear": [own]})
    assert "all" not in kept["_overrides"]
    after = {f["id"]: (f["presence"], f["layout"]) for _, _, f in plans.frames_of(kept)}
    assert after == before
    # a layout the film's look does not have is left alone, and one for another presence refused
    override.apply(kept, {"all": {"layouts": {"both": "glass-card"}}})
    assert all(f["layout"] != "glass-card" for _, _, f in plans.frames_of(kept))
    with pytest.raises(ValueError, match="not a layout for both"):
        override.refuse({"all": {"layouts": {"both": "full-frame"}}})


def test_a_picked_type_and_transition_sit_beside_the_plans_reading(script: Row, full: Row) -> None:
    unit = next(u for u in units.units(full) if u["picture"] == "diagram")
    lead = unit["id"]
    labels = copy.deepcopy(script["labels"])
    labels["overrides"] = override.merge(
        labels.get("overrides", {}),
        {"frames": {lead: {"picture": "list", "transition": "crossfade"}}},
    )
    merged = plans.merged(script["plan"], labels)
    frame = next(f for _, _, f in plans.frames_of(merged) if f["id"] == lead)
    assert frame["picture"] == "diagram", "the reading is the plan's and stays"
    assert plans.picture_of(frame) == "list" and plans.transition_of(frame) == "crossfade"
    assert plans.labels_of(merged)["frames"][lead]["picture"] == "diagram"
    picked = next(u for u in units.units(derive.full(merged)) if u["id"] == lead)
    assert picked["picture"] == "list" and picked["arrangement"] == "stack"
    assert picked["sig"] != unit["sig"], "a new type is a new picture to draw"
    brief = picture.brief(picked, derive.full(merged))
    assert brief["picture"]["kind"] == "list" and "the person" in brief["picture"]["kind_chosen_by"]
    assert "kind_chosen_by" not in picture.brief(unit, full)["picture"]
    # a transition alone never sends a picture back to its builder
    labels["overrides"] = override.merge(labels["overrides"], {"frames": {lead: {"picture": None}}})
    assert labels["overrides"]["frames"][lead] == {"transition": "crossfade"}
    again = next(
        u for u in units.units(derive.full(plans.merged(script["plan"], labels))) if u["id"] == lead
    )
    assert again["sig"] == unit["sig"]
    for bad in ({"picture": "terminal"}, {"transition": "none"}, {"layout": "sideways"}):
        with pytest.raises(ValueError, match="There is no"):
            override.refuse({"frames": {lead: bad}})


def test_a_picture_comes_in_by_its_move_and_the_one_before_leaves_by_it(full: Row) -> None:
    found = units.units(full)
    pictures = {u["id"]: sketch.built(picture.brief(u, full)) for u in found}
    clock = timeline.schedule(full, [])
    frames = {f["id"]: f for _, _, f in plans.frames_of(full)}
    pushed = next(u for u in found if frames[u["id"]].get("transition") == "push")
    before = found[found.index(pushed) - 1]
    page = film.project(full, clock, found, pictures)["index.html"]
    comp, prior = picture.composition_id(pushed["id"]), picture.composition_id(before["id"])
    start = timeline.line_of(clock, pushed["id"])["start"]  # type: ignore[index]
    enters = next(m for m in page.splitlines() if f'tl.fromTo("#wrap-{comp}"' in m)
    leaves = next(m for m in page.splitlines() if f'tl.to("#wrap-{prior}"' in m)
    assert enters.rstrip().endswith(f"{start:.3f});") and leaves.rstrip().endswith(f"{start:.3f});")
    assert "opacity: 0" in enters and "opacity: 1, duration: 0.4" in enters
    # the one before stays mounted for as long as the move takes
    own = picture.clock(before, clock)
    assert f'data-duration="{own["seconds"] + 0.4:.3f}" data-track-index' in page
    # a cut is set at an instant, and the person's pick wins over the plan's
    cut = next(u for u in found if frames[u["id"]].get("transition") == "cut")
    assert f'tl.set("#wrap-{picture.composition_id(cut["id"])}"' in page
    for move, seconds in (("zoom-through", 0.5), ("crossfade", 0.4), ("cut", 0)):
        other = copy.deepcopy(full)
        lead = next(f for _, _, f in plans.frames_of(other) if f["id"] == pushed["id"])
        lead["picked"] = {"transition": move}
        again = film.project(other, clock, found, pictures)["index.html"]
        line = next(m for m in again.splitlines() if f'"#wrap-{comp}"' in m)
        if seconds:
            assert "tl.fromTo(" in line and f"duration: {seconds}" in line
        else:
            assert "tl.set(" in line and f'tl.to("#wrap-{prior}"' not in again


def test_a_persons_words_keep_what_the_line_does_and_what_was_drawn_for_it(
    script: Row, full: Row
) -> None:
    unit = next(u for u in units.units(full) if len(u["frames"]) > 1)
    lead, held = unit["frames"][0], unit["frames"][1]
    before = script["plan"]
    after = copy.deepcopy(before)
    was = plans.reword(after, lead, "Other words for the same job.", at=1.0)
    line = next(f for _, _, f in plans.frames_of(plans.merged(before, {})) if f["id"] == lead)
    assert was == line["vo"] and before != after, "the plan handed in is never touched"
    labels = plans.carried(script["labels"], before, after)
    merged = plans.merged(after, labels)
    now = {f["id"]: f for _, _, f in plans.frames_of(merged)}
    old = {f["id"]: f for _, _, f in plans.frames_of(plans.merged(before, script["labels"]))}
    assert now[lead]["vo"] == "Other words for the same job."
    assert now[lead]["by_person"]["was"] == was
    assert now[lead]["by_person"]["cues"] == [c["at"] for c in old[lead].get("cues", [])]
    for key in ("presence", "layout", "picture", "arrangement", "transition"):
        assert now[lead].get(key) == old[lead].get(key), key
    assert [o.get("type") for o in now[lead].get("objects", [])] == [
        o.get("type") for o in old[lead].get("objects", [])
    ]
    assert plans.labels_of(merged)["frames"][lead]["h"] != script["labels"]["frames"][lead]["h"]
    # every other line is as it was, and code times the new words
    assert {k: v.get("presence") for k, v in now.items()} == {
        k: v.get("presence") for k, v in old.items()
    }
    again = next(u for u in units.units(derive.full(merged)) if u["id"] == unit["id"])
    assert again["sig"] == unit["sig"], "words alone never send a picture back"
    assert again["seconds"] != unit["seconds"]
    # a second change keeps the writer's words, not the person's first ones
    plans.reword(after, lead, "A third way to say it.", at=2.0)
    found = plans.beat_of(after, lead)
    assert found is not None
    marked = found[2] if found[2] is not None and "by_person" in found[2] else found[1]
    assert marked["by_person"]["was"] == was and marked["by_person"]["at"] == 2.0
    # a line cut from a longer beat keeps the beat's words joined, and a missing line is named
    assert plans.beat_of(after, held) is not None
    with pytest.raises(KeyError):
        plans.reword(after, "c9.b9.f9", "Nothing.", at=3.0)


def test_a_person_adds_and_cuts_lines_and_every_other_line_keeps_its_id_and_words() -> None:
    plan: Row = {
        "chapters": [
            {
                "id": "c1",
                "question": "Why?",
                "beats": [
                    {"id": "c1.b1", "says": "One line alone."},
                    {
                        "id": "c1.b2",
                        "says": "First part. Second part. Third part.",
                        # a writer may leave a beat's line ids to their places
                        "frames": [
                            {"vo": "First part."},
                            {"vo": "Second part."},
                            {"vo": "Third part."},
                        ],
                    },
                ],
            },
            {"id": "c2", "question": "How?", "beats": [{"id": "c2.b1", "says": "Only line."}]},
        ]
    }
    after = copy.deepcopy(plan)
    # inside a beat it joins the beat, and the lines after it keep the ids they had
    middle = plans.add_line(after, "c1.b2.f1", "A new middle.", at=5.0)
    beat = after["chapters"][0]["beats"][1]
    assert middle == "c1.b2.f4"
    assert [f["id"] for f in beat["frames"]] == ["c1.b2.f1", middle, "c1.b2.f2", "c1.b2.f3"]
    assert beat["says"] == "First part. A new middle. Second part. Third part."
    assert beat["frames"][1]["by_person"] == {"was": "", "cues": [], "at": 5.0}
    # after a beat's last line it is a beat of its own, with an id nothing has used
    held = plans.add_line(after, "c1.b2.f3", "Over the same picture.", at=6.0, hold=True)
    own = after["chapters"][0]["beats"][2]
    assert held == "c1.b3.f1" and own["says"] == "Over the same picture."
    assert own["frames"][0]["hold"] and own["by_person"]["was"] == ""
    # first in a chapter, by the chapter's id
    assert plans.add_line(after, "c2", "Opening.", at=7.0) == "c2.b2.f1"
    assert [b["id"] for b in after["chapters"][1]["beats"]] == ["c2.b2", "c2.b1"]
    # a line cut from a longer beat leaves the others as they were, its words joined again
    assert plans.cut_line(after, "c1.b2.f2") == "Second part."
    assert [f["id"] for f in beat["frames"]] == ["c1.b2.f1", middle, "c1.b2.f3"]
    assert beat["says"] == "First part. A new middle. Third part."
    # a beat's only line takes the beat with it
    assert plans.cut_line(after, "c1.b1.f1") == "One line alone."
    assert [b["id"] for b in after["chapters"][0]["beats"]] == ["c1.b2", "c1.b3"]
    with pytest.raises(KeyError):
        plans.add_line(after, "c9.b9.f9", "Nowhere.", at=8.0)
    with pytest.raises(KeyError):
        plans.cut_line(after, "c9.b9.f9")
    assert plan["chapters"][0]["beats"][1]["frames"][0] == {"vo": "First part."}, "untouched"


def test_a_change_keeps_the_frame_of_every_line_it_does_not_redesign(script: Row) -> None:
    before = script["plan"]
    was = {f["id"]: f for _, _, f in plans.frames_of(plans.merged(before, script["labels"]))}
    plain = next(f for f in was.values() if f["presence"] == "person" and not f.get("hold"))
    drawn = next(f for f in was.values() if f.get("cues"))
    after = copy.deepcopy(before)
    # the writer says one line another way, and gives another line a new step
    said = plans.beat_of(after, plain["id"])
    assert said is not None
    said[1]["says"] = "So how long can a copy be trusted?"
    redone = plans.beat_of(after, drawn["id"])
    assert redone is not None and redone[2] is not None
    redone[2]["cues"][0]["does"] = "wipes in from the left"
    labels = plans.carried(script["labels"], before, after, frames_only=True)
    now = {f["id"]: f for _, _, f in plans.frames_of(plans.merged(after, labels))}
    assert now[plain["id"]]["presence"] == "person", "said another way, it is still the person's"
    assert now[plain["id"]]["layout"] == plain["layout"]
    assert "subtype" not in next(
        b for _, b in plans.beats_of(plans.merged(after, labels)) if b["id"] == said[1]["id"]
    ), "what the line does is read again"
    redesigned = now[drawn["id"]]
    assert not redesigned.get("_designed"), "what the writer redesigned is read as new"
    assert "move" not in redesigned["cues"][0] and "picture" not in redesigned
    untouched = [k for k in was if k not in (plain["id"], drawn["id"])]
    assert all(now[k].get("presence") == was[k].get("presence") for k in untouched)


def test_a_change_taken_back_leaves_the_picks_made_since(script: Row) -> None:
    then = plans.merged(script["plan"], {})
    gone, stays, later = [f["id"] for _, _, f in plans.frames_of(then)][:3]
    chapter = then["chapters"][0]["id"]
    # as the plan stands, the change has cut a line
    now = copy.deepcopy(then)
    for _, b in plans.beats_of(now):
        b["frames"] = [f for f in b["frames"] if f["id"] != gone]
    as_then = {
        "frames": {gone: {"layout": "split"}, stays: {"layout": "split"}},
        "chapters": {chapter: {"presence": "both"}},
    }
    as_now = {
        "frames": {stays: {"layout": "full-frame"}, later: {"layout": "split"}},
        "all": {"layouts": {"both": "split"}},
        "presenter": "off",
    }
    kept = plans.picks_kept(as_then, as_now, then, now)
    assert kept == {
        # the line that comes back brings its pick; the others are picked as they stand now
        "frames": {
            gone: {"layout": "split"},
            stays: {"layout": "full-frame"},
            later: {"layout": "split"},
        },
        # the chapter's pick was taken back since, and stays taken back
        "all": {"layouts": {"both": "split"}},
        "presenter": "off",
    }
    # a pick that is itself what goes back is as it was then: here, not made
    taken = {"frames": {later: {"layout": "split"}}, "all": {"layouts": {"both": "split"}}}
    assert plans.picks_kept(as_then, as_now, then, now, taken) == {
        "frames": {gone: {"layout": "split"}, stays: {"layout": "full-frame"}},
        "presenter": "off",
    }
    # and the other way, when the change is put back: the cut line takes its pick with it
    assert plans.picks_kept(as_now, kept, now, then)["frames"] == {
        stays: {"layout": "full-frame"},
        later: {"layout": "split"},
    }


def test_a_picture_is_drawn_from_what_it_shows_never_from_the_words_said_over_it(
    full: Row,
) -> None:
    unit = next(
        u
        for u in units.units(full)
        if any(f.get("cues") for _, _, f in plans.frames_of(full) if f["id"] == u["id"])
    )
    said = copy.deepcopy(full)
    lead = next(f for _, _, f in plans.frames_of(said) if f["id"] == unit["id"])
    lead["vo"] = "The same thing, said another way by the writer."
    lead["cues"][0]["at"] = "same thing"
    reworded = next(u for u in units.units(said) if u["id"] == unit["id"])
    assert reworded["sig"] == unit["sig"], "the words only move the picture's clock"
    assert reworded["sig_was"] != unit["sig_was"]
    # a picture made before the words were left out still stands, until its words change
    assert units.same(unit["sig_was"], unit) and units.same(unit["sig"], unit)
    assert not units.same(unit["sig_was"], reworded) and not units.same("", unit)
    # what it shows, or what a step does, is another picture
    shown = copy.deepcopy(full)
    next(f for _, _, f in plans.frames_of(shown) if f["id"] == unit["id"])["cues"][0]["does"] = (
        "spins"
    )
    assert next(u for u in units.units(shown) if u["id"] == unit["id"])["sig"] != unit["sig"]


def test_no_speaker_takes_everyone_off_screen(script: Row) -> None:
    merged = plans.merged(script["plan"], script["labels"])
    override.apply(merged, {"presenter": "off"})
    assert merged["brief"]["theme"] == "voice-only"
    assert {f["presence"] for _, _, f in plans.frames_of(merged)} == {"content"}


# -- built pictures -------------------------------------------------------------------------------


def test_a_picture_runs_from_the_line_that_shows_it_through_the_lines_that_hold_it(
    full: Row,
) -> None:
    found = units.units(full)
    assert found and all(u["kind"] == "picture" for u in found)
    frames = {f["id"]: f for ch in full["chapters"] for b in ch["beats"] for f in b["frames"]}
    for unit in found:
        first, *rest = (frames[i] for i in unit["frames"])
        assert first.get("shows") and not first.get("hold")
        assert all(f.get("hold") for f in rest)
        assert unit["canvas"] == list(geometry.canvas(first["layout"]))
    by = units.by_frame(found)
    assert all(by[f]["id"] == u["id"] for u in found for f in u["frames"])


def test_a_pictures_level_is_the_persons_pick_then_the_films(full: Row) -> None:
    one = units.units(full)[0]["id"]
    assert {u["level"] for u in units.units(full, level="rich")} == {"rich"}
    picked = units.units(full, {"units": {one: {"level": "rich"}}})
    assert [u["level"] for u in picked if u["id"] == one] == ["rich"]
    assert units.units(full)[0]["sig"] == picked[0]["sig"], "its level is not what it is built from"


def test_a_take_never_sends_a_picture_back_to_its_builder(full: Row) -> None:
    unit = next(u for u in units.units(full) if len(u["frames"]) > 1)
    html = sketch.built(picture.brief(unit, full))
    assert picture.faults(html, unit, full) == []
    planned = picture.clock(unit, timeline.schedule(full))
    assert set(planned["lines"]) == set(unit["frames"]) and planned["seconds"] > 0
    chapter = next(ch for ch in full["chapters"] if ch["id"] == unit["chapter"])
    lines = [f for b in chapter["beats"] for f in b["frames"]]
    take = {
        "id": "tk_1",
        "chapter": chapter["id"],
        "frame": "",
        "seconds": 3.0 * len(lines),
        "marks": [{"frame": f["id"], "t": 3.0 * i} for i, f in enumerate(lines)],
    }
    recorded = picture.clock(unit, timeline.schedule(full, [take]))
    assert recorded["seconds"] == pytest.approx(3.0 * len(unit["frames"]))
    timed = picture.with_clock(html, recorded)
    assert json.dumps(recorded, separators=(",", ":")) in timed
    assert picture.CLOCK.sub("", timed) == picture.CLOCK.sub("", html), "only its clock changed"
    stills = picture.still_times(recorded)
    assert all(recorded["lines"][f][0] <= at <= recorded["lines"][f][1] for f, at in stills.items())


@pytest.mark.parametrize(
    ("change", "fault"),
    [
        (
            lambda h, c: h.replace("<template>", "<div>").replace("</template>", "</div>"),
            "no <template>",
        ),
        (
            lambda h, c: h.replace(f'data-composition-id="{c}"', 'data-composition-id="other"'),
            "data-composition-id",
        ),
        (lambda h, c: h.replace(f'__timelines["{c}"]', '__timelines["x"]'), "one paused timeline"),
        (lambda h, c: h.replace(f'id="{c}-clock"', 'id="clock"'), "keep the clock"),
        (lambda h, c: h.replace("gsap.timeline", "Math.random(); gsap.timeline"), "Math.random"),
        (lambda h, c: h.replace("<style>", '<style>@import "x.css";'), "@import"),
        (
            lambda h, c: h.replace("font-family: 'Inter'", "font-family: Papyrus"),
            "not on the rendering computer",
        ),
    ],
)
def test_a_file_that_breaks_the_contract_is_named(full: Row, change: Any, fault: str) -> None:
    unit = units.units(full)[0]
    html = sketch.built(picture.brief(unit, full))
    broken = change(html, picture.composition_id(unit["id"]))
    assert any(fault in f for f in picture.faults(broken, unit, full)), picture.faults(
        broken, unit, full
    )


def test_a_cue_that_is_never_used_is_a_fault(full: Row) -> None:
    unit = next(u for u in units.units(full) if picture.cue_keys(u, full))
    html = sketch.built(picture.brief(unit, full))
    key = picture.cue_keys(unit, full)[0]
    assert any(key in f for f in picture.faults(html.replace(key, "gone"), unit, full))


def test_the_person_window_is_kept_clear_only_where_it_sits_on_the_picture() -> None:
    assert geometry.keep_clear("corner-window") is not None
    assert geometry.keep_clear("panel-and-portrait") is None
    assert geometry.keep_clear("graphic-on-ground") is None
    x, y, scale = geometry.fit((1344, 756), geometry.FULL)
    assert (x, y) == (0, 0) and scale == pytest.approx(1920 / 1344, abs=1e-4)
    x, y, scale = geometry.fit((1920, 1080), (58, 162, 1344, 756))
    assert scale == pytest.approx(0.7) and (x, y) == (58, 162)


# -- the film -------------------------------------------------------------------------------------


def test_the_film_is_one_page_written_by_code(full: Row) -> None:
    found = units.units(full)
    pictures = {u["id"]: sketch.built(picture.brief(u, full)) for u in found}
    chapter = full["chapters"][0]
    lines = [f for b in chapter["beats"] for f in b["frames"]]
    take = {
        "id": "tk_1",
        "chapter": chapter["id"],
        "frame": "",
        "seconds": 4.0 * len(lines),
        "marks": [{"frame": f["id"], "t": 4.0 * i} for i, f in enumerate(lines)],
    }
    clock = timeline.schedule(full, [take])
    files = film.project(
        full,
        clock,
        found,
        pictures,
        takes={"tk_1": {"video": "takes/tk_1.mp4", "audio": "takes/tk_1.m4a"}},
    )
    page = files["index.html"]
    assert f'data-duration="{clock["total"]:.3f}"' in page
    assert len([p for p in files if p.startswith("compositions/")]) == len(found)
    assert 'src="takes/tk_1.mp4" muted' in page and 'src="takes/tk_1.m4a"' in page
    assert film.STAND_IN in page, "a chapter nobody recorded shows a stand-in"
    for move in page.splitlines():
        if "tl.to(" in move or "tl.fromTo(" in move:
            assert not any(k in move for k in ("left:", "top:", "width:", "height:")), (
                "a box is moved by transform and opacity, never by its geometry"
            )
    for unit in found:
        comp = picture.composition_id(unit["id"])
        own = picture.clock(unit, clock)
        built = files[f"compositions/{comp}.html"]
        held = json.loads(picture.CLOCK.search(built).group("body"))  # type: ignore[union-attr]
        assert held["lines"] == own["lines"] and held["cues"] == own["cues"]
        assert held["seconds"] >= own["seconds"], "it may stay a moment longer, to leave by a move"
        assert "@font-face { font-family: 'Fraunces'; src: local('Fraunces'); }" in built
        assert f'data-composition-src="compositions/{comp}.html"' in page
    assert '<script src="gsap.min.js">' in page and "http" not in page.replace("http-equiv", "")


def test_a_film_wears_the_brands_colours_and_type(full: Row) -> None:
    look = picture.Look(
        palette={**picture.PALETTE, "ground": "#f6f1e7", "accent": "#ff5a36"},
        display="Geist",
        text="Geist",
        mono="Fragment Mono",
    )
    unit = units.units(full)[0]
    brief = picture.brief(unit, full, look=look)
    assert brief["look"]["palette"]["accent"] == "#ff5a36"
    assert brief["look"]["fonts"] == {"display": "Geist", "text": "Geist", "mono": "Fragment Mono"}
    html = sketch.built(brief)
    assert "font-family: 'Geist'" in html and "#f6f1e7" in html
    assert picture.faults(html, unit, full, look) == []
    assert any("not on the rendering computer" in f for f in picture.faults(html, unit, full))
    page = film.project(full, timeline.schedule(full), [unit], {unit["id"]: html}, look=look)
    assert "font-family: 'Geist'; src: local('Geist')" in page["index.html"]
    assert "background: #f6f1e7" in page["index.html"]


def test_catalog_choices_bind_to_brand_and_cue_clock(full: Row) -> None:
    from design_agent.episode import catalog

    assert len(catalog.COMPONENTS) == 13
    unit = units.units(full)[0]
    look = picture.Look(palette={**picture.PALETTE, "accent": "#ff0077"}, text="Inter")
    for variant in ("horizontal", "vertical", "grid"):
        chosen = units.units(
            full, {"units": {unit["id"]: {"component": "list", "variant": variant}}}
        )[0]
        brief = picture.brief(chosen, full, look=look)
        html = sketch.built(brief)
        assert f'data-variant="{variant}"' in html
        assert "#ff0077" in html and picture.faults(html, chosen, full, look) == []


def test_component_eligibility_uses_only_grounded_data() -> None:
    from design_agent.episode import catalog

    invalid = [
        {"words": "a", "value": False, "unit": "ms"},
        {"words": "b", "value": float("nan"), "unit": "ms"},
    ]
    assert "bar-chart" not in catalog.available(invalid)
    assert "sequence-diagram" not in catalog.available([])
    assert "sequence-diagram" in catalog.available([{"from": "Buyer", "to": "Shop"}])
    data = [{"words": "a", "value": 0, "unit": "ms"}, {"words": "b", "value": 20, "unit": "ms"}]
    assert catalog.available(data)["bar-chart"] == ["vertical", "horizontal"]
    assert "bar-chart" not in catalog.available([data[0], {**data[1], "unit": "bytes"}])


def test_catalog_scene_is_redressed_for_the_export_theme(full: Row) -> None:
    unit = units.units(full)[0]
    original = picture.brief(unit, full)
    html = sketch.built(original)
    look = picture.Look(palette={**picture.PALETTE, "accent": "#eca100"}, text="Geist")
    rendered = picture.dressed(html, {"seconds": 3}, look)
    start = rendered.index("data-episode-theme>") + len("data-episode-theme>")
    end = rendered.index("</script>", start)
    tokens = json.loads(rendered[start:end])
    assert tokens["palette"]["accent"] == "#eca100" and tokens["fonts"]["text"] == "Geist"


def test_component_reader_reuses_a_scene_until_its_held_data_changes() -> None:
    first = {"id": "a", "presence": "content", "shows": "Two measurements", "vo": "First"}
    held = {
        "id": "b",
        "hold": True,
        "presence": "content",
        "vo": "Second",
        "objects": [{"id": "n", "what": "value", "value": 1}],
    }
    plan = {"chapters": [{"id": "ch", "beats": [{"id": "b", "frames": [first, held]}]}]}
    questions: list[set[str]] = []

    def read(state: Any, qs: Row) -> Row:
        questions.append(set(qs))
        return first_option(state, qs)

    classify.stage_design(plan, [], False, read)
    assert any({"picture", "component"} <= group for group in questions)
    questions.clear()
    classify.stage_design(plan, [], False, read)
    assert not questions
    held["objects"][0]["value"] = 7
    classify.stage_design(plan, [], False, read)
    assert questions == [{"component"}]
    questions.clear()
    first["_component_picked"] = True
    classify.stage_design(plan, [], True, read)
    assert all("component" not in group for group in questions)


def test_presenter_morph_keeps_a_continuous_take_and_bounds_short_lines(full: Row) -> None:
    chapter = full["chapters"][0]
    frames = [f for beat in chapter["beats"] for f in beat["frames"]]
    for f, layout in zip(frames, ["full-frame", "avatar-bubble", "corner-window"], strict=True):
        f.update(layout=layout, presence="person" if layout == "full-frame" else "both")
    marks = [0, 1, 1.4]
    take = {
        "id": "camera",
        "chapter": chapter["id"],
        "frame": "",
        "seconds": 2.2,
        "marks": [{"frame": f["id"], "t": t} for f, t in zip(frames, marks, strict=True)],
    }
    page = film.project(
        full,
        timeline.schedule(full, [take]),
        [],
        {},
        takes={"camera": {"video": "cam.mp4", "audio": "cam.m4a"}},
    )["index.html"]
    assert page.count('src="cam.mp4"') == page.count('src="cam.m4a"') == 1
    assert 'tl.fromTo("#window-0"' in page
    assert '"duration": 0.4' in page
    assert '"borderRadius": 135' in page


def test_window_percentage_and_saved_presets() -> None:
    base = {"layout": "corner-window"}
    for pick, width in [(37, 142), ("small", 276), (100, 384), ("large", 480)]:
        frame = {**base, "picked": {"window_size": pick}}
        assert geometry.for_frame(frame).person[2] == width
    for invalid in (0, 126, True, "75", 50.5):
        with pytest.raises(ValueError):
            override.refuse({"frames": {"f": {"window_size": invalid}}})


def test_timeline_keeps_chronology_when_events_have_links() -> None:
    from design_agent.episode import catalog

    frame = {
        "id": "first",
        "arrangement": "timeline",
        "objects": [
            {"id": "launch", "words": "Launch"},
            {"id": "renew", "words": "Renewal"},
            {"id": "after", "from": "launch", "to": "renew", "words": "Later"},
        ],
    }
    choice = catalog.select(frame, [frame], {}, "diagram", 1400)
    assert (choice["component"], choice["variant"]) == ("timeline", "horizontal")
    assert (
        catalog.select(frame, [frame], {"component": "flowchart"}, "diagram", 1400)["component"]
        == "flowchart"
    )


def test_automatic_chart_requires_comparable_measurements() -> None:
    from design_agent.episode import catalog

    first = {
        "objects": [
            {"id": "a", "words": "North", "value": 8, "unit": "orders"},
            {"id": "b", "words": "South", "value": 4, "unit": "orders"},
        ]
    }
    assert catalog.select(first, [first], {}, "diagram", 1000)["component"] == "bar-chart"
    first["objects"][1]["unit"] = "days"
    assert catalog.select(first, [first], {}, "diagram", 1000)["component"] != "bar-chart"
