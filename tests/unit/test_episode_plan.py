"""An episode's plan: what code derives from its sections, and the pipeline that writes it level
by level (`design_agent.episode`, `pipelines/episode_plan.py`), with the demo's scripted writers
standing in for the helpers."""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from design_agent import episode
from design_agent.harness import events as ev
from design_agent.harness.workflow import WorkflowRunner, parse_report
from design_agent.pipelines import PIPELINES
from design_agent.pipelines.episode_plan import SHOTS_SCHEMA, WITHIN, _shots_brief
from design_agent.surfaces.web import demo_episode as sample
from tests.unit.harness.test_workflow import FakeHelpers, finish, make

THREAD = "thread-1"


def _section(value: dict[str, Any]) -> dict[str, Any]:
    return episode.read(json.dumps(value).encode())


def _plan() -> dict[str, dict[str, Any]]:
    """The sample plan as its boards hold it: the brief it is checked against, the top layer,
    and every chapter's beats."""
    sections = {f"brief: {name}": _section(sample.top(name)) for name in sample.BRIEF}
    sections |= {name: _section(sample.top(name)) for name in sample.TOP}
    for name in sample.lengths():
        sections[name] = episode.with_beats(_section(sample.beats(name)), None)
    return sections


def _with_shots(sections: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        name: episode.with_shots(s, _section(sample.shots(name))) if name in sample.lengths() else s
        for name, s in sections.items()
    }


# -- the plan as data ----------------------------------------------------------------------------


def test_the_sample_plan_passes_every_check_once_its_shots_are_in() -> None:
    beats_only = episode.checks(_plan())
    states = {row["id"]: row["state"] for row in beats_only}
    # The words are the beats', so what only reading them shows is checked before any shot.
    assert {key for key, state in states.items() if state == "pass"} == {
        "clock",
        "one",
        "landing",
        "demands",
        "edges",
        "credit",
        "label",
        "said",
        "caption",
        "breath",
        "mix",
    }
    assert {key for key, state in states.items() if state == "wait"} == {
        "fits",
        "load",
        "read",
        "stale",
        "voice",
    }

    whole = {row["id"]: row for row in episode.checks(_with_shots(_plan()))}
    assert {row["state"] for row in whole.values()} == {"pass"}
    assert (
        whole["clock"]["text"] == "6 parts add up to 5:00, with 17 beats and 33 shots inside them."
    )
    assert whole["fits"]["text"] == "All 33 lines fit; the tightest keeps 0.6 s spare."
    assert whole["load"]["text"] == "None is over 26. Over 19: 3C.2 (24), C2.1 (20)."
    assert whole["voice"]["text"] == "The shots of all 17 beats add up to their passages."
    assert whole["edges"]["text"] == (
        "The open starts on its first line. The close ends on its last line."
    )
    assert whole["label"]["text"] == (
        "Nothing spoken or on screen says a thing is made up: the label “Illustrative” carries it."
    )
    assert whole["one"]["text"] == "All 6 parts ask one question."
    assert whole["landing"]["text"] == "The last line is a distillation of 12 words."
    assert whole["mix"]["text"].startswith(
        "The 17 beats explain by demonstration 3, worked example 3, counterexample 2,"
    )
    # A long list reads in parts: the clock, the plan's structure, the words.
    assert [row["group"] for row in episode.checks(_plan())] == (
        ["time"] * 4 + ["structure"] * 6 + ["words"] * 6
    )


def test_the_clock_and_the_word_counts_are_worked_out_from_the_lengths() -> None:
    timed = episode.timed(_with_shots(_plan()))
    assert [row["time"] for row in timed["Chapters"]["rows"]][:3] == [
        "0:00–0:20",
        "0:20–1:15",
        "1:15–2:20",
    ]
    chapter = timed["Chapter 2"]
    assert chapter["time"] == "1:15–2:20" and chapter["words"] == "94 words · 43 s of 65 s"
    assert chapter["beats"][1]["time"] == "1:31–1:47"
    assert chapter["beats"][1]["shots"][1]["time"] == "1:39–1:47"
    # The numbers a timeline is drawn from: where each part starts, how long a line takes to
    # say and how long its words on screen take to read.
    assert chapter["start"] == 75.0 and chapter["beats"][1]["start"] == 91.0
    first = chapter["beats"][0]["shots"][0]
    assert (first["start"], first["speaks"], first["reads"]) == (75.0, 5.5, 1.1)
    # A beat carries its passage, so the count is known before its shots are written.
    assert episode.timed(_plan())["Chapter 2"]["words"] == "94 words · 43 s of 65 s"


def test_a_shot_goes_only_under_a_beat_the_chapter_has() -> None:
    chapter = _plan()["Chapter 2"]
    stray = _section({"section": "shots", "shots": [{"beat": "9Z", "id": "9Z.1", "seconds": 4}]})
    with pytest.raises(ValueError, match="under beat 9Z, which the chapter does not have"):
        episode.with_shots(chapter, stray)
    with_shots = episode.with_shots(chapter, _section(sample.shots("Chapter 2")))
    assert [s["id"] for s in with_shots["beats"][0]["shots"]] == ["2A.1", "2A.2"]
    assert "beat" not in with_shots["beats"][0]["shots"][0]
    assert episode.written(with_shots) and not episode.written(chapter)


def test_a_beat_that_changes_marks_its_shots_stale_until_they_are_written_again() -> None:
    before = _with_shots(_plan())["Chapter 2"]
    rewritten = sample.beats("Chapter 2", ["2B"])
    after = episode.with_beats(_section(rewritten), before)
    stale = {beat["id"]: bool(beat.get("stale")) for beat in after["beats"]}
    assert stale == {"2A": False, "2B": True, "2C": False, "2D": False}
    assert after["beats"][0]["shots"] == before["beats"][0]["shots"]  # 2A reads as it did
    assert not episode.written(after)
    assert episode.chapter_faults(after, 65) == [
        "2B: its shots were written from the beat as it was"
    ]
    row = next(r for r in episode.checks({"Chapter 2": after}) if r["id"] == "stale")
    assert row["state"] == "fail"

    # Its shots written again, and only its: the chapter is whole.
    again = {
        "section": "shots",
        "shots": [s for s in sample.shots("Chapter 2", ["2B"])["shots"] if s["beat"] == "2B"],
    }
    whole = episode.with_shots(after, _section(again))
    assert episode.written(whole)
    assert episode.changed(whole, before) == ["2B", "2B.1"]


def test_the_checks_name_the_shot_and_the_numbers() -> None:
    chapter = _with_shots(_plan())["Chapter 2"]
    shot = chapter["beats"][0]["shots"][0]
    shot["vo"] = " ".join(["word"] * 30)  # 13.6 s of speech in an 8 s shot
    chapter["beats"][0]["says"] = f"{shot['vo']} {chapter['beats'][0]['shots'][1]['vo']}"
    shot["on"], shot["at"] = "nine words that nobody could read in one second", 7
    chapter["beats"][1]["demands"] = ["one", "two", "three"]
    chapter["beats"][2]["seconds"] = 20  # its shots still add up to 16
    assert episode.chapter_faults(chapter, 65) == [
        "the chapter: its beats add up to 69 s of 65 s",
        "2C: its shots add up to 16 s of 20 s",
        "2A.1: 30 words need 13.6 s of 8 s",
        "2A.1: 30 words",
        "2A.1 “nine words that nobody could read in one second”: 9 words need 3.2 s, get 1.0 s",
        "2B: 3 demands",
    ]


def test_a_section_says_what_is_wrong_with_it() -> None:
    beats = sample.beats("Chapter 2")
    beats["beats"][0]["shots"] = []
    del beats["beats"][1]["focal"]
    found = episode.faults(_section(beats))
    assert any("2A carries shots" in fault for fault in found)
    assert "beat 2B has no focal" in found
    listed = sample.top("Chapters")
    del listed["rows"][2]["handoff"]
    listed["rows"][3]["seconds"] = "long"
    assert episode.faults(_section(listed)) == [
        "Chapter 2 has no `handoff`: what crosses the cut into it",
        "Chapter 3 has no `seconds`: how long it runs, as a number",
    ]
    spine = sample.top("Spine")
    spine["rows"][1]["picked"] = True
    assert episode.faults(_section(spine)) == ["2 candidates are `picked`; exactly one is"]
    assert episode.faults({"section": "poster"})[0].startswith("`section` is 'poster'")


HELD = episode.Given(
    names=("Example Studio",),
    label="Illustrative",
    opens="Open",
    first="You type three words into a docs search.",
    closes="Close",
    last="Search doesn't look for your words. It looks for your meaning, nearby.",
)


def test_the_voice_is_held_to_what_only_reading_it_shows() -> None:
    """The faults a first real plan had and every count passed: lines that credit the source,
    a second word for what is made up, and captions read aloud."""
    beats = _section(sample.beats("Chapter 2"))
    assert episode.chapter_faults(beats, 65, shots=False, held=HELD, part="Chapter 2") == []
    beats["beats"][0]["says"] = (
        "According to the article, Example Studio hands your question to a model. "
        "Example Studio calls the result an embedding."
    )
    beats["beats"][1]["says"] = "These coordinates are mock data. A map. One spot. Pinned there."
    assert episode.chapter_faults(beats, 65, shots=False, held=HELD, part="Chapter 2") == [
        "2A: “According to” points at the source; say what it found",
        "the chapter: it names Example Studio 2 times; once is enough",
        "2B: the voice says “mock”; the picture's label carries what is made up",
        "the chapter: 5 of its 11 sentences run under 6 words (“These coordinates are mock "
        "data.”, “A map.”, “One spot.”, “Pinned there.”, “Account recovery.”)",
    ]
    # A word for what is made up on screen is a second label, whichever word it is.
    whole = episode.with_shots(
        _section(sample.beats("Chapter 2")), _section(sample.shots("Chapter 2"))
    )
    whole["beats"][0]["shots"][0]["on"] = "Illustrative model"
    whole["beats"][1]["shots"][0]["on"] = "A stand-in map"
    assert episode.chapter_faults(whole, 65, held=HELD, part="Chapter 2") == [
        "2A.1: “Illustrative model” is on screen; the look's one label already says what is "
        "made up",
        "2B.1: “A stand-in map” is on screen; the look's one label already says what is made up",
    ]


def test_a_beats_shots_say_its_passage_and_nothing_else() -> None:
    chapter = _with_shots(_plan())["Chapter 2"]
    assert episode.chapter_faults(chapter, 65) == []
    chapter["beats"][0]["shots"][1]["vo"] = "Out comes a list of figures. A few hundred of them."
    assert episode.chapter_faults(chapter, 65) == [
        "2A: its shots leave its passage at “a list of numbers a few hundred” (they say "
        "“a list of figures a few hundred”)"
    ]
    # A capital or a comma moved at a cut is not a changed word.
    chapter["beats"][0]["shots"][1]["vo"] = "out comes a list of numbers; a few hundred of them"
    assert episode.chapter_faults(chapter, 65) == []
    # Before its shots are written, a passage is held to the time its beat has.
    beats = _section(sample.beats("Chapter 2"))
    beats["beats"][0]["says"] = " ".join(["word"] * 40)
    assert episode.chapter_faults(beats, 65, shots=False) == [
        "2A: its 40 words need 19.2 s of 16 s"  # two shots at least, each with its air
    ]


def test_the_film_opens_and_closes_on_the_lines_in_the_chapter_list() -> None:
    opening = _section(sample.beats("Open"))
    assert episode.chapter_faults(opening, 20, shots=False, held=HELD, part="Open") == []
    opening["beats"][0]["says"] = "This film explains how a docs search works."
    assert episode.chapter_faults(opening, 20, shots=False, held=HELD, part="Open") == [
        "the chapter: it does not open on the first line (“You type three words into a docs "
        "search.”)"
    ]
    closing = _section(sample.beats("Close"))
    closing["beats"][1]["says"] += " Thanks for watching."
    [found] = episode.chapter_faults(closing, 35, shots=False, held=HELD, part="Close")
    assert found.startswith("the chapter: it does not close on the last line")
    # The first line is the open's alone: no other chapter is held to it.
    assert episode.chapter_faults(closing, 35, shots=False, held=HELD, part="Chapter 4") == []
    # The chapter list has to give both, with the kind of hook the first one is.
    listed = sample.top("Chapters")
    del listed["rows"][0]["first"], listed["rows"][-1]["last"]
    listed["rows"][0]["hook"] = "intro"
    found = episode.faults(_section(listed))
    assert found[0] == "Open has no `first`: the film's first spoken line, word for word"
    assert found[1].startswith("Open: `hook` is 'intro'; it names how the first line earns")
    assert found[2] == "Close has no `last`: the film's last spoken line, word for word"


def test_the_chapter_list_names_one_turn_and_lands_its_last_line() -> None:
    """What a second real plan got wrong above its chapters, with every count passing: a chapter
    that asked two questions, no moment the film pivots on, and a last line that was the brief's
    sentence again."""
    assert episode.faults(_section(sample.top("Chapters"))) == []
    assert episode.top_flags(_plan()) == {}
    # Exactly one chapter between the open and the close holds the turn.
    listed = sample.top("Chapters")
    del listed["rows"][1]["turn"]
    [found] = episode.faults(_section(listed))
    assert found.startswith("`turn` is on no part; exactly one chapter between the open and")
    listed["rows"][0]["turn"] = "The search box, empty."
    assert episode.faults(_section(listed))[0].startswith("`turn` is on Open;")
    listed = sample.top("Chapters")
    listed["rows"][3]["turn"] = "The search measures every distance, and the clock runs out."
    assert episode.faults(_section(listed))[0].startswith("`turn` is on Chapter 1 and Chapter 3;")
    # The last line names how it lands, in a line short enough to repeat.
    listed = sample.top("Chapters")
    listed["rows"][-1]["landing"] = "recap"
    listed["rows"][-1]["last"] = " ".join(["word"] * 17)
    found = episode.faults(_section(listed))
    assert found[0].startswith("Close: `landing` is 'recap'; it names how the last line lands")
    assert found[1] == "Close: `last` runs to 17 words; say it in 16 or fewer"

    # What only reading the list shows: a part that is two steps, and the idea recited.
    sections = _plan()
    rows = sections["Chapters"]["rows"]
    rows[3]["asks"] = "What can hold the batch, and what does the fast way cost?"
    rows[-1]["last"] = "Search finds the page you mean by comparing where meanings sit."
    assert episode.top_flags(sections) == {
        "one": [
            "Chapter 3 asks more than one question (“What can hold the batch, and what does the "
            "fast way cost?”); a part is one step, and what does not fit is left out"
        ],
        "landing": [
            "the last line is the brief's idea said again (7 of its 7 words are the brief's); "
            "land it in a line the film has earned"
        ],
    }
    checks = {row["id"]: row["state"] for row in episode.checks(sections)}
    assert (checks["one"], checks["landing"]) == ("fail", "fail")
    rows[2]["asks"] = "Could a meaning have a place? Could search compare places?"
    assert len(episode.top_flags(sections)["one"]) == 2  # two question marks are two questions


def test_the_voice_is_written_to_be_said_and_explains_in_more_than_one_way() -> None:
    """What reading the second real plan showed: a year the voice had to read, a chapter with no
    short sentence in it, and chapters that landed most of their beats the same way."""
    beats = _section(sample.beats("Chapter 2"))
    beats["beats"][0]["says"] = (
        "In 2025 a model turns your question into 384 numbers. Atlas 4 reads it whole."
    )
    assert episode.chapter_faults(beats, 65, shots=False, held=HELD, part="Chapter 2") == [
        "2A: the voice is left to read “2025”; write it the way it is said, and let the picture "
        "carry the figure",
        "2A: the voice is left to read “384”; write it the way it is said, and let the picture "
        "carry the figure",
    ]  # a small number after a name is part of the name
    # A part of six sentences or more keeps a short one.
    beats = _section(sample.beats("Chapter 2"))
    long = " ".join(["word"] * 10) + "."
    for beat in beats["beats"]:
        beat["says"] = f"{long} {long}"
    assert episode.chapter_faults(beats, 65, shots=False, held=HELD, part="Chapter 2") == [
        "the chapter: its 8 sentences all run 10 words; give it one under 9 where a point lands"
    ]
    # No technique carries over half of a chapter of four beats or more.
    beats = _section(sample.beats("Chapter 2"))
    for beat in beats["beats"][:3]:
        beat["technique"] = "demonstration"
    found = episode.chapter_faults(beats, 65, shots=False, held=HELD, part="Chapter 2")
    assert found == [
        "the chapter: 3 of its 4 beats explain by demonstration; land some of them another way"
    ]
    # These are the words' faults: left out, what remains is what shots cannot be written over.
    assert (
        episode.chapter_faults(beats, 65, shots=False, held=HELD, part="Chapter 2", style=False)
        == []
    )
    assert episode.ways(beats) == {"demonstration": 3, "worked example": 1}
    # A film in which nothing is made concrete says so once every chapter is written.
    sections = _plan()
    for name in sample.lengths():
        for beat in sections[name]["beats"]:
            if beat["technique"] in episode.CONCRETE:
                beat["technique"] = "contrast"
    mix = next(row for row in episode.checks(sections) if row["id"] == "mix")
    assert mix["state"] == "fail"
    assert "no beat explains by worked example or analogy" in mix["text"]


def test_a_brief_is_held_to_its_ledger_and_its_quotes_to_the_material() -> None:
    brief, claims = _section(sample.top("Brief")), _section(sample.top("Claims"))
    assert episode.faults(brief) == episode.faults(claims) == []
    assert episode.brief_faults(brief, claims) == []
    marked = episode.quoted(claims, sample.MATERIAL)
    assert all(row["found"] for row in marked["rows"] if row["status"] == "stated")
    assert "found" not in marked["rows"][-1]  # what is made up has no quote to look for
    checks = {row["id"]: row for row in episode.brief_checks({"Brief": brief, "Claims": marked})}
    assert checks["quotes"]["text"] == "All 13 quotes are in the material."
    assert checks["stated"]["text"] == "13 stated, 1 illustrative, none unconfirmed."

    # A quote that is not the material's words, a claim nobody can source, a missing label.
    claims["rows"][4]["quote"] = "turns a piece of text into a list of 512 numbers"
    claims["rows"][5]["status"] = "unconfirmed"
    marked = episode.quoted(claims, sample.MATERIAL)
    checks = {row["id"]: row for row in episode.brief_checks({"Brief": brief, "Claims": marked})}
    assert (checks["quotes"]["state"], checks["quotes"]["text"]) == (
        "fail",
        "c4: its quote is not in the material",
    )
    assert (checks["stated"]["state"], checks["stated"]["text"]) == ("fail", "c5 is unconfirmed")
    unread = {row["id"]: row for row in episode.brief_checks({"Brief": brief, "Claims": claims})}
    assert unread["quotes"]["state"] == "wait"  # nothing was looked up, so nothing is claimed
    brief["rows"] = [row for row in brief["rows"] if row["id"] not in ("label", "for", "gap")]
    next(row for row in brief["rows"] if row["id"] == "source")["names"] = "Example Studio"
    del claims["rows"][0]["quote"]
    assert episode.faults(claims) == [
        "claim c0 is stated with no `quote`: the material's own words for it"
    ]
    assert episode.brief_faults(brief, claims) == [
        "the brief has no `gap` row",
        "the brief has no `for` row",
        "`source` needs `names`: what the voice would call whoever the facts come from, as a "
        "list (empty when the material is the team's own)",
        "a claim is illustrative and the brief has no `label` row: the one word the picture "
        "carries for made-up material",
    ]


# -- the pipeline ----------------------------------------------------------------------------------


def _writer(brief: str, _label: str) -> str:
    """A helper's report, from the demo's scripted writer for that brief."""
    return str(sample.next_step([HumanMessage(brief), AIMessage("")]).content)


def _runner(helpers: FakeHelpers) -> WorkflowRunner:
    runner = make(lambda ctx: None, helpers)
    runner.register("episode_plan", PIPELINES["episode_plan"])
    return runner


async def test_the_brief_is_written_first_from_the_material() -> None:
    helpers = FakeHelpers(_writer)
    runner = _runner(helpers)
    material = ["/workspace/attachments/post.md", "/workspace/attachments/notes.md"]
    asked = {"project": "search", "material": material}  # the brief is where a plan starts
    record = await finish(runner, await runner.start("episode_plan", asked, THREAD))
    assert record.status == "done", record.error
    assert helpers.labels == ["brief"] and helpers.calls[0].effort == "max"
    for path in material:
        assert f"- {path}" in helpers.calls[0].brief
    result = record.result
    assert result["stage"] == "brief" and result["open"] == []
    assert [(f["name"], f["path"].rsplit("/", 1)[1]) for f in result["publish"]] == [
        ("Brief", "brief.json"),
        ("Claims", "claims.json"),
    ]
    assert result["idea"].startswith("Search finds the page you mean")
    assert 'kind "brief"' in result["next"] and "nothing is planned before it" in result["next"]


async def test_a_brief_that_marks_a_claim_made_up_names_the_label_for_it() -> None:
    def writer(brief: str, label: str) -> str:
        if label == "brief":
            first = sample.top("Brief")
            first["rows"] = [row for row in first["rows"] if row["id"] != "label"]
            return "Brief.\n" + json.dumps({"brief": first, "claims": sample.top("Claims")})
        return _writer(brief, label)

    helpers = FakeHelpers(writer)
    runner = _runner(helpers)
    asked = {"project": "search", "material": ["/workspace/attachments/post.md"]}
    record = await finish(runner, await runner.start("episode_plan", asked, THREAD))
    assert helpers.labels == ["brief", "brief, fix"]
    assert "a claim is illustrative and the brief has no `label` row" in helpers.calls[1].brief
    assert record.result["open"] == []  # the second pass names it


async def test_the_top_layer_is_written_spine_first_then_the_chapter_list_from_it() -> None:
    helpers = FakeHelpers(_writer)
    runner = _runner(helpers)
    run = await runner.start("episode_plan", {"project": "search", "stage": "top"}, THREAD)
    record = await finish(runner, run)
    assert record.status == "done", record.error
    assert helpers.labels == ["spine", "chapter list"]
    assert [call.effort for call in helpers.calls] == ["max", "xhigh"]
    # The spine is picked from the brief as the team signed it off, which no step rewrites.
    assert "Change neither" in helpers.calls[0].brief
    # The chapter list's writer is handed the brief and the spine as they were returned.
    picked = next(row for row in sample.top("Spine")["rows"] if row["picked"])
    assert picked["text"] in helpers.calls[1].brief and "/plan/" in helpers.calls[1].brief
    assert sample.top("Brief")["rows"][0]["text"] in helpers.calls[1].brief
    result = record.result
    assert [f["name"] for f in result["publish"]] == list(sample.TOP)
    assert result["publish"][0]["path"] == "/workspace/projects/search/plan/spine.json"
    assert result["chapters"] == sample.lengths() and result["open"] == []


async def test_a_spine_is_not_picked_without_a_brief_to_pick_it_from() -> None:
    def writer(brief: str, label: str) -> str:
        if label.startswith("spine"):
            spine = sample.top("Spine")
            unread = {"section": "list", "rows": []}
            return "No brief.\n" + json.dumps({"brief": unread, "spine": spine})
        return _writer(brief, label)

    helpers = FakeHelpers(writer)
    runner = _runner(helpers)
    run = await runner.start("episode_plan", {"project": "search", "stage": "top"}, THREAD)
    await finish(runner, run)
    assert helpers.labels[:2] == ["spine", "spine, fix"]
    assert "if there is none in the plan folder, say so and stop" in helpers.calls[1].brief


async def test_a_chapters_shots_are_written_after_its_beats_and_from_them() -> None:
    helpers = FakeHelpers(_writer)
    runner = _runner(helpers)
    wanted = {"Chapter 1": 55, "Chapter 2": 65}
    run = await runner.start(
        "episode_plan", {"project": "search", "stage": "chapters", "chapters": wanted}, THREAD
    )
    record = await finish(runner, run)
    assert record.status == "done", record.error
    labels = helpers.labels
    assert sorted(labels) == [
        "Chapter 1: beats",
        "Chapter 1: shots",
        "Chapter 2: beats",
        "Chapter 2: shots",
        "reader",
        "the top as it stands",
    ]
    # What the levels above hold a chapter to is read back first; the reader comes last.
    assert labels[0] == "the top as it stands" and labels[-1] == "reader"
    assert helpers.calls[0].effort == "low" and helpers.calls[-1].effort == "xhigh"
    for name in wanted:
        assert labels.index(f"{name}: beats") < labels.index(f"{name}: shots")
        shots = next(call for call in helpers.calls if call.label == f"{name}: shots")
        for beat in sample.beats(name)["beats"]:  # every word of every beat is in the brief
            assert json.dumps(beat["takeaway"], ensure_ascii=False) in shots.brief
            assert json.dumps(beat["change"], ensure_ascii=False) in shots.brief
            assert json.dumps(beat["says"], ensure_ascii=False) in shots.brief
    # Published in the order the board needs: a chapter's beats, then its shots.
    assert [(f["name"], f["path"].rsplit("/", 1)[1]) for f in record.result["publish"]] == [
        ("Chapter 1", "chapter-1.beats.json"),
        ("Chapter 1", "chapter-1.shots.json"),
        ("Chapter 2", "chapter-2.beats.json"),
        ("Chapter 2", "chapter-2.shots.json"),
    ]
    assert record.result["open"] == {} and record.result["failed"] == []
    # The reader names both chapters it was given, and sends neither back.
    assert "“Chapter 1”, “Chapter 2”" in helpers.calls[-1].brief
    reader = record.result["reader"]
    # It quotes each chapter's weakest line, whether or not the chapter goes back.
    assert list(reader.pop("weakest")) == ["Chapter 1", "Chapter 2"]
    assert reader == {
        "verdict": "pass",
        "sent_back": {},
        "left": {},
        "keep": [sample.PLAN["reader"]["keep"]],
        "top": [],
        "file": "/workspace/projects/search/plan/reader.json",
    }


async def test_a_chapter_the_first_reader_sends_back_is_written_once_more() -> None:
    helpers = FakeHelpers(_writer)
    runner = _runner(helpers)
    wanted = {"Chapter 2": 65, "Chapter 3": 65}
    asked = {"project": "search", "stage": "chapters", "chapters": wanted}
    record = await finish(runner, await runner.start("episode_plan", asked, THREAD))
    assert record.status == "done", record.error
    labels = helpers.labels
    assert labels[-3:] == ["reader", "Chapter 3: beats, again", "Chapter 3: shots, again"]
    again = helpers.calls[-2].brief
    note = sample.PLAN["reader"]["note"]
    assert f"Fix these, and only these:\n- {note}" in again
    assert f"Keep what works; the reader named it:\n- {sample.PLAN['reader']['keep']}" in again
    # Its shots are written from the beats as the second pass left them.
    rewritten = sample.beats("Chapter 3", ["3A"])["beats"][0]
    assert rewritten["says"] != sample.beats("Chapter 3")["beats"][0]["says"]
    assert json.dumps(rewritten["says"], ensure_ascii=False) in helpers.calls[-1].brief
    assert record.result["reader"]["sent_back"] == {"Chapter 3": [note]}
    assert record.result["reader"]["verdict"] == "fix" and record.result["open"] == {}
    # Each chapter is published once, the one written again as it now stands.
    assert [f["path"].rsplit("/", 1)[1] for f in record.result["publish"]] == [
        "chapter-2.beats.json",
        "chapter-2.shots.json",
        "chapter-3.beats.json",
        "chapter-3.shots.json",
    ]


async def test_the_reader_sends_back_three_chapters_at_most_and_only_ones_just_written() -> None:
    def writer(brief: str, label: str) -> str:
        if label == "reader":
            names = [*sample.lengths(), "Chapter 9"]
            titled = {"Open": "Open: The question", "Chapter 1": "Chapter 1 · Matching words"}
            verdict = {
                "verdict": "fix",
                "keep": [],
                "weakest": {},
                # A reader may add a chapter's title to its name; it is still that chapter.
                "chapters": {titled.get(name, name): [f"“{name}”: say why."] for name in names},
                "top": ["The chapter list repeats itself."],
            }
            return "Rework.\n" + json.dumps(verdict)
        return _writer(brief, label)

    helpers = FakeHelpers(writer)
    runner = _runner(helpers)
    asked = {"project": "search", "stage": "chapters", "chapters": sample.lengths()}
    record = await finish(runner, await runner.start("episode_plan", asked, THREAD))
    assert record.status == "done", record.error
    reader = record.result["reader"]
    assert list(reader["sent_back"]) == ["Open", "Chapter 1", "Chapter 2"]
    # What it could not send back is said, for the team: the rest, and a chapter not in the run.
    assert list(reader["left"]) == ["Chapter 3", "Chapter 4", "Close", "Chapter 9"]
    assert reader["top"] == ["The chapter list repeats itself."]
    assert sum(label.endswith("beats, again") for label in helpers.labels) == 3
    assert "`reader` is what a first reader made of it" in record.result["next"]


async def test_the_reader_alone_reads_what_stands_and_writes_only_what_it_sends_back() -> None:
    helpers = FakeHelpers(_writer)
    runner = _runner(helpers)
    asked = {"project": "search", "stage": "review", "chapters": sample.lengths()}
    record = await finish(runner, await runner.start("episode_plan", asked, THREAD))
    assert record.status == "done", record.error
    # No chapter is written before the reader: each one's beats are read back as they stand, so
    # how they explain can be counted for it. The one it sends back is written after.
    stood = [f"{name}: beats as they stand" for name in sample.lengths()]
    assert helpers.labels[0] == "the top as it stands"
    assert sorted(helpers.labels[1:7]) == sorted(stood)
    assert helpers.labels[7:] == ["reader", "Chapter 3: beats, again", "Chapter 3: shots, again"]
    assert "- Chapter 3: number made visible 1, build-up 1, demonstration 1" in (
        helpers.calls[7].brief
    )
    assert list(record.result["reader"]["weakest"]) == list(sample.lengths())
    assert [f["path"].rsplit("/", 1)[1] for f in record.result["publish"]] == [
        "chapter-3.beats.json",
        "chapter-3.shots.json",
    ]
    assert record.result["bare"] == [] and record.result["failed"] == []
    # With one chapter to read, the sample's reader sends nothing back, and nothing is published.
    alone = {"project": "search", "stage": "review", "chapters": {"Chapter 3": 65}}
    record = await finish(runner, await runner.start("episode_plan", alone, THREAD))
    assert record.result["publish"] == [] and "publish nothing" in record.result["next"]


async def test_a_part_a_person_asked_for_has_no_reader_but_them() -> None:
    helpers = FakeHelpers(_writer)
    runner = _runner(helpers)
    asked = {
        "project": "search",
        "stage": "chapters",
        "chapters": {"Chapter 2": 65, "Chapter 3": 65},
        "review": False,
    }
    record = await finish(runner, await runner.start("episode_plan", asked, THREAD))
    assert "reader" not in helpers.labels and "reader" not in record.result


async def test_shots_that_do_not_pass_go_back_once_with_what_is_wrong() -> None:
    tried: list[str] = []

    def writer(brief: str, label: str) -> str:
        if label == "Chapter 2: shots":
            tried.append(brief)
            crowded = copy.deepcopy(sample.shots("Chapter 2"))
            crowded["shots"][0]["vo"] = " ".join(["word"] * 30)
            return "Shots.\n" + json.dumps(crowded)
        return _writer(brief, label)

    helpers = FakeHelpers(writer)
    runner = _runner(helpers)
    run = await runner.start(
        "episode_plan",
        {"project": "search", "stage": "chapters", "chapters": {"Chapter 2": 65}},
        THREAD,
    )
    record = await finish(runner, run)
    assert helpers.labels == [
        "the top as it stands",
        "Chapter 2: beats",
        "Chapter 2: shots",
        "Chapter 2: shots, fix",
        "reader",
    ]
    assert "2A.1: 30 words need 13.6 s of 8 s" in helpers.calls[3].brief
    # The words were the beat's: a shot that says its own is told where it left them.
    assert "2A: its shots leave its passage at" in helpers.calls[3].brief
    assert "Change only what these lines name" in helpers.calls[3].brief
    # The writer's second pass is sound, so nothing is left open.
    assert record.result["open"] == {} and record.result["bare"] == []
    assert len(tried) == 1 and record.status == "done"


async def test_beats_that_do_not_add_up_get_no_shots() -> None:
    def writer(brief: str, label: str) -> str:
        if label.startswith("Chapter 2: beats"):
            short = copy.deepcopy(sample.beats("Chapter 2"))
            short["beats"][0]["seconds"] = 4
            return "Beats.\n" + json.dumps(short)
        return _writer(brief, label)

    helpers = FakeHelpers(writer)
    runner = _runner(helpers)
    run = await runner.start(
        "episode_plan",
        {"project": "search", "stage": "chapters", "chapters": {"Chapter 2": 65}},
        THREAD,
    )
    record = await finish(runner, run)
    assert helpers.labels == ["the top as it stands", "Chapter 2: beats", "Chapter 2: beats, fix"]
    assert record.result["bare"] == ["Chapter 2"] and "reader" not in record.result
    assert record.result["open"] == {
        "Chapter 2": [
            "the chapter: its beats add up to 53 s of 65 s",
            "2A: its 23 words need 11.0 s of 4 s",
        ]
    }
    assert [f["path"].rsplit("/", 1)[1] for f in record.result["publish"]] == [
        "chapter-2.beats.json"
    ]


async def test_what_only_reading_shows_is_said_and_does_not_hold_the_shots_back() -> None:
    def writer(brief: str, label: str) -> str:
        if label.startswith("Chapter 2: beats"):
            same = copy.deepcopy(sample.beats("Chapter 2"))
            for beat in same["beats"]:
                beat["technique"] = "demonstration"
            return "Beats.\n" + json.dumps(same)
        return _writer(brief, label)

    helpers = FakeHelpers(writer)
    runner = _runner(helpers)
    asked = {
        "project": "search",
        "stage": "chapters",
        "chapters": {"Chapter 2": 65},
        "review": False,
    }
    record = await finish(runner, await runner.start("episode_plan", asked, THREAD))
    assert record.status == "done", record.error
    # The beats go back once for it; the shots are written all the same, and are not sent
    # back for what only the beats' writer could mend.
    assert helpers.labels == [
        "the top as it stands",
        "Chapter 2: beats",
        "Chapter 2: beats, fix",
        "Chapter 2: shots",
    ]
    assert record.result["bare"] == []
    assert record.result["open"] == {
        "Chapter 2": [
            "the chapter: 4 of its 4 beats explain by demonstration; land some of them another way"
        ]
    }


async def test_a_chapter_list_goes_back_for_what_only_reading_it_shows() -> None:
    def writer(brief: str, label: str) -> str:
        if label == "chapter list":
            listed = sample.top("Chapters")
            listed["rows"][3]["asks"] = "What holds the batch, and what does the fast way cost?"
            listed["rows"][-1]["last"] = "Search finds the page by comparing where meanings sit."
            return "List.\n" + json.dumps(
                {"chapters": listed, "sound": sample.top("Sound and look")}
            )
        return _writer(brief, label)

    helpers = FakeHelpers(writer)
    runner = _runner(helpers)
    run = await runner.start("episode_plan", {"project": "search", "stage": "top"}, THREAD)
    record = await finish(runner, run)
    assert helpers.labels == ["spine", "chapter list", "chapter list, fix"]
    again = helpers.calls[2].brief
    assert "- Chapters: Chapter 3 asks more than one question" in again
    assert "- Chapters: the last line is the brief's idea said again" in again
    assert record.result["open"] == []  # the second pass is the sample's own list


async def test_the_reader_is_handed_the_counts_and_its_verdict_outlives_the_run() -> None:
    bus = ev.EventBus()
    seen: list[ev.Event] = []
    bus.subscribe(seen.append)
    helpers = FakeHelpers(_writer)
    runner = make(lambda ctx: None, helpers, bus=bus)
    runner.register("episode_plan", PIPELINES["episode_plan"])
    wanted = {"Chapter 2": 65, "Chapter 3": 65}
    asked = {"project": "search", "stage": "chapters", "chapters": wanted}
    record = await finish(runner, await runner.start("episode_plan", asked, THREAD))
    assert record.status == "done", record.error
    reader = next(call for call in helpers.calls if call.label == "reader").brief
    # Code counts how the beats explain; the reader weighs it.
    assert "HOW THE BEATS EXPLAIN (counted from each beat's `technique`)" in reader
    assert "- Chapter 2: demonstration 1, analogy 1, build-up 1, worked example 1" in reader
    assert "- The film: demonstration 2, build-up 2, analogy 1," in reader
    assert "WHAT THE CHECKS STILL FLAG" not in reader  # nothing is still flagged
    # Its verdict is a file, and a note the moment it reports: a run stopped while the chapter
    # it sent back is being written again has still said what it found.
    assert "- reader.json: your verdict, the same JSON object you report." in reader
    notes = [e.text for e in seen if e.kind == ev.PIPELINE_STEP and e.data.get("note")]
    assert notes == [
        "The first reader sent back Chapter 3, now being written again. Its verdict, with each "
        "chapter's weakest line, is in /workspace/projects/search/plan/reader.json."
    ]
    said = [e.text for e in seen if e.kind == ev.PIPELINE_STEP]
    assert said.index(notes[0]) < next(
        i for i, text in enumerate(said) if text.startswith("Chapter 3: beats, again: started")
    )
    assert record.result["reader"]["file"] == "/workspace/projects/search/plan/reader.json"


async def test_a_writer_that_goes_quiet_is_stopped_and_its_step_given_to_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(WITHIN, "xhigh", 0.05)
    stopped: list[str] = []

    async def writer(brief: str, label: str) -> str:
        if label == "Chapter 2: beats":
            try:
                await asyncio.Event().wait()  # a model call that never comes back
            except asyncio.CancelledError:
                stopped.append(label)
                raise
        return _writer(brief, label)

    helpers = FakeHelpers(writer)
    runner = _runner(helpers)
    asked = {
        "project": "search",
        "stage": "chapters",
        "chapters": {"Chapter 2": 65},
        "review": False,
    }
    record = await finish(runner, await runner.start("episode_plan", asked, THREAD))
    assert record.status == "done", record.error
    assert stopped == ["Chapter 2: beats"]
    assert helpers.labels == [
        "the top as it stands",
        "Chapter 2: beats",
        "Chapter 2: beats, resumed",
        "Chapter 2: shots",
    ]
    assert (
        "did not finish it (its helper gave no report within 1 min and was stopped)"
        in helpers.calls[2].brief
    )
    assert record.result["failed"] == [] and record.result["bare"] == []


async def test_notes_reach_every_writer_of_a_part_written_again() -> None:
    helpers = FakeHelpers(_writer)
    runner = _runner(helpers)
    asked = {
        "project": "search",
        "stage": "chapters",
        "chapters": {"Chapter 2": 65},
        "notes": "“Chapter 2”, at beat 2B",
        "review": False,
    }
    record = await finish(runner, await runner.start("episode_plan", asked, THREAD))
    assert record.status == "done", record.error
    _, beats, shots = helpers.calls
    assert "NOTES FROM THE LEAD\n“Chapter 2”, at beat 2B" in beats.brief
    assert (
        "Those numbers are coordinates: they pin the text" in shots.brief
    )  # the beat as rewritten
    assert "NOTES FROM THE LEAD" in shots.brief
    # Notes never claim an earlier pass: a writer with no files yet takes them as guidance.
    assert "If they are not there, this is the first pass: write them fresh" in beats.brief


@pytest.mark.parametrize(
    ("args", "wrong"),
    [
        ({"project": "../etc"}, "project is a folder name"),
        ({"project": "p", "stage": "poses"}, 'stage is "brief", "top", "chapters", "shots" or'),
        ({"project": "p"}, "material is the paths of what the episode is made from"),
        ({"project": "p", "material": ["notes.md"]}, "material is the paths"),
        ({"project": "p", "stage": "chapters"}, "chapters is an object"),
        ({"project": "p", "stage": "chapters", "chapters": {"Chapter 1": 0}}, "needs its length"),
        ({"project": "p", "stage": "chapters", "chapters": {"A b": 5, "a-b": 5}}, "its own name"),
    ],
)
async def test_arguments_that_cannot_run_fail_the_run_with_the_reason(
    args: dict[str, Any], wrong: str
) -> None:
    runner = _runner(FakeHelpers(_writer))
    record = await finish(runner, await runner.start("episode_plan", args, THREAD))
    assert record.status == "failed" and wrong in record.error


# -- the demo's writers answer the pipeline's briefs ----------------------------------------------


def test_a_scripted_writer_writes_its_file_then_reports_it() -> None:
    brief = _shots_brief(
        "/workspace/projects/episode-as_01", "Chapter 2", 65, sample.beats("Chapter 2"), ""
    )
    first = sample.next_step([HumanMessage(brief)])
    [call] = first.tool_calls
    assert call["name"] == "write_file"
    assert (
        call["args"]["file_path"] == "/workspace/projects/episode-as_01/plan/chapter-2.shots.json"
    )
    report = sample.next_step([HumanMessage(brief), first])
    assert not report.tool_calls
    section = parse_report(str(report.content), SHOTS_SCHEMA)
    assert section == json.loads(call["args"]["content"]) == sample.shots("Chapter 2")


async def test_a_writer_whose_report_is_not_the_json_is_reissued_with_the_brief() -> None:
    """A first helper that misread its brief leaves no files: the second one is told to look and
    to write what is missing, never that the work is done."""
    seen: list[str] = []

    def writer(brief: str, label: str) -> str:
        seen.append(brief)
        if label == "spine":
            return 'Neither file exists.\n{"brief": null, "spine": null}'
        return _writer(brief, label)

    helpers = FakeHelpers(writer)
    runner = _runner(helpers)
    notes = "Source is sources/post.md. Choose one worked example."
    asked = {"project": "search", "stage": "top", "notes": notes}
    record = await finish(runner, await runner.start("episode_plan", asked, THREAD))
    assert record.status == "done", record.error
    assert helpers.labels == ["spine", "spine, resumed", "chapter list"]
    assert "write whatever the brief asks for that is not there" in seen[1]
    assert "Your work is done and on disk" not in seen[1]
    assert "this is the first pass: write them fresh" in seen[0]


async def test_the_shots_stage_reads_the_beats_back_and_writes_only_shots() -> None:
    helpers = FakeHelpers(_writer)
    runner = _runner(helpers)
    asked = {"project": "search", "stage": "shots", "chapters": {"Chapter 2": 65}}
    record = await finish(runner, await runner.start("episode_plan", asked, THREAD))
    assert record.status == "done", record.error
    assert helpers.labels == [
        "the top as it stands",
        "Chapter 2: beats as they stand",
        "Chapter 2: shots",
    ]
    assert [call.effort for call in helpers.calls] == ["low", "low", "xhigh"]
    assert "You change nothing and write nothing" in helpers.calls[1].brief
    # The shots writer is handed the beats exactly as they were read back.
    for beat in sample.beats("Chapter 2")["beats"]:
        assert json.dumps(beat["change"], ensure_ascii=False) in helpers.calls[2].brief
    assert record.result["stage"] == "shots"
    assert [f["path"].rsplit("/", 1)[1] for f in record.result["publish"]] == [
        "chapter-2.shots.json"
    ]


async def test_the_shots_stage_writes_nothing_from_beats_that_do_not_add_up() -> None:
    def writer(brief: str, label: str) -> str:
        if label.endswith("beats as they stand"):
            short = copy.deepcopy(sample.beats("Chapter 2"))
            short["beats"][0]["seconds"] = 4
            return json.dumps(short)
        return _writer(brief, label)

    helpers = FakeHelpers(writer)
    runner = _runner(helpers)
    asked = {"project": "search", "stage": "shots", "chapters": {"Chapter 2": 65}}
    record = await finish(runner, await runner.start("episode_plan", asked, THREAD))
    assert helpers.labels == ["the top as it stands", "Chapter 2: beats as they stand"]
    assert record.result["publish"] == [] and record.result["bare"] == ["Chapter 2"]
    assert record.result["open"] == {
        "Chapter 2": [
            "the chapter: its beats add up to 53 s of 65 s",
            "2A: its 23 words need 11.0 s of 4 s",
        ]
    }


def test_a_plan_is_said_in_words_short_enough_to_read() -> None:
    """What the first run on a real post wrote: pixel positions in a handoff, a paragraph for a
    shape, and every claim listed in one row. Each is sent back with what to do instead."""
    listed = sample.top("Chapters")
    listed["rows"][2]["handoff"] = (
        "The question card arrives unchanged at x=192, y=112, 1536 × 160 px."
    )
    listed["rows"][3]["shape"] = " ".join(["word"] * 40)
    del listed["rows"][4]["covers"]
    assert episode.faults(_section(listed)) == [
        "Chapter 2: `handoff` gives positions or sizes in pixels; a plan says it in words, and "
        "the storyboard measures it",
        "Chapter 3: `shape` runs to 40 words; say it in 12 or fewer",
        "Chapter 4 has no covers",
    ]
    brief = sample.top("Brief")
    next(row for row in brief["rows"] if row["id"] == "leaves")["text"] = " ".join(["topic"] * 300)
    assert episode.faults(_section(brief)) == [
        "leaves: `text` runs to 300 words; say it in 80 or fewer"
    ]
    ledger = sample.top("Claims")
    ledger["rows"][1]["quote"] = " ".join(["word"] * 90)
    assert episode.faults(_section(ledger)) == [
        "claim c1: `quote` runs to 90 words; say it in 60 or fewer"
    ]
    beats = sample.beats("Chapter 2")
    beats["beats"][0]["focal"] = "the white card, ink Geist 400 at 40 px"
    shots = sample.shots("Chapter 2")
    shots["shots"][0]["shows"] = "A box 648 × 336 px wide."
    assert (
        "beat 2A: `focal` gives positions or sizes in pixels" in episode.faults(_section(beats))[0]
    )
    assert (
        "shot 2A.1: `shows` gives positions or sizes in pixels"
        in episode.faults(_section(shots))[0]
    )
    # A frame's size in the length row is not a position: 1920 × 1080 stays.
    assert episode.faults(_section(sample.top("Brief"))) == []
