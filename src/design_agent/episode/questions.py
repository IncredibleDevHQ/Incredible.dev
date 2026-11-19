"""The typed questions the classifier is asked, built in one place.

A plan never carries a label its writer chose. The writer writes words; these questions
ask the classifier what those words are. The closed lists live in reference/types.json.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any

Row = dict[str, Any]

#: The closed lists every label comes from, and the numbers the checks use.
TYPES: Row = json.loads(Path(__file__).with_name("types.json").read_text(encoding="utf8"))


def table(name: str) -> dict[str, Row]:
    return {row["id"]: row for row in TYPES[name]}


def options(name: str, only: Collection[str] | None = None) -> dict[str, str]:
    """{id: 'Name: what the classifier should look for'} for one closed list."""
    return {
        row["id"]: f"{row['name']}: {row['reads_as']}"
        for row in TYPES[name]
        if only is None or row["id"] in only
    }


def choice(instructions: str, opts: Mapping[str, str]) -> Row:
    return {"type": "choice", "instructions": instructions, "criteria": opts}


def noul(instructions: str, yes: str, no: str) -> Row:
    return {"type": "noul", "instructions": instructions, "criteria": {"true": yes, "false": no}}


def score(instructions: str, levels: list[str]) -> Row:
    return {"type": "score", "instructions": instructions, "criteria": levels}


BEAT_TYPES = {
    "open": "Open: earns the next minute. A hook, a promise of what the viewer will learn, the need, a greeting, why to trust the speaker, the agenda, a go line.",
    "explain": "Explain: makes it understood. A definition, an analogy, a mechanism, a worked example, a step, code read out, a list of items, a contrast, a story of how it came about.",
    "prove": "Prove: makes it believed. A demo run and read out, a finished result shown, a figure or benchmark given as proof, someone else vouching.",
    "turn": "Turn: gives a reason to go on. A question asked aloud, the obvious way that fails, a problem appearing, a doubt answered, an opinion, what the thing just explained buys you, a rule.",
    "guide": "Guide: says where we are. A signpost to what comes next, a bridge between parts, a milestone, a recap of an earlier episode, a map of the series.",
    "close": "Close: leaves something to keep. A recap, a tip for the viewer, where to get it, the ask, the goodbye, the line that lands the idea, what the next video covers.",
}


def beat_state(
    idea: str, chapter_question: str, before: str, passage: str, after: str, place: str
) -> Row:
    return {
        "video": {"kind": "a technical concept explainer with a voice-over", "idea": idea},
        "chapter_question": chapter_question,
        "place_in_video": place,
        "sentence_before": before,
        "PASSAGE": passage,
        "sentence_after": after,
    }


BEAT_ASK = (
    "A script is cut into passages, each doing one job for the viewer. Judge only PASSAGE; "
    "sentence_before and sentence_after are context. Which one job does PASSAGE do? "
    "Pick by what the words do, not by their topic. Telling close jobs apart: a promise says "
    "what the viewer gets, an agenda lists the parts, a signpost is the same move later, a "
    "bridge looks back and forward in one line. A definition says what it is, a mechanism how "
    "it works, a list names several items, a contrast needs two sides. A worked example is a "
    "concrete case with particulars, an analogy compares with another world. A so-what is the "
    "gain from what was just explained, a judgment is the speaker's opinion, a principle is a "
    "rule, advice is a tip to the viewer. A recap repeats content, a landing lands the main "
    "idea once, an ask requests an action, a sign-off says goodbye."
)


def beat_questions() -> Row:
    qs: Row = {
        "type": choice(BEAT_ASK, BEAT_TYPES),
        "subtype": choice(BEAT_ASK, options("beat_subtypes")),
    }
    subs = TYPES["beat_subtypes"]
    for t in BEAT_TYPES:
        only = [s["id"] for s in subs if s["type"] == t]
        qs["in_" + t] = choice(
            BEAT_ASK
            + f" The passage is known to {BEAT_TYPES[t].split(':')[1].strip().split('.')[0].lower()}.",
            options("beat_subtypes", only),
        )
    return qs


CHAPTER_ASK = (
    "A chapter of an explainer answers one question. From its question, its words and its "
    "place among the video's other chapters, what kind of chapter is this? Pick by what the "
    "chapter does for the viewer. When the video walks through several options, patterns or "
    "designs one chapter at a time, each of those chapters is options-compared, even if it "
    "defines its option or explains how it works. A chapter that only says what one thing is "
    "is a concept; one that walks through the inner workings of the video's single subject is "
    "how-it-works."
)


def chapter_questions(allowed: Collection[str] | None = None, series: bool = False) -> Row:
    qs: Row = {
        "type": choice(CHAPTER_ASK, options("chapter_types", allowed)),
        "one_question": noul(
            "Does this chapter answer the one question given as chapter_question, and only that question?",
            "The words answer that one question.",
            "The words answer a different question, or two questions.",
        ),
    }
    if series:
        # An episode's chapter explains something, so it reads as what it explains. Whether it
        # is about another episode is a separate yes or no, not a rival type.
        qs["episode"] = noul(
            "This video belongs to a series. Is this chapter about one OTHER episode of the series: what that episode covered, or what it will cover?",
            "The chapter is about another episode of the series, or about the series as a whole.",
            "The chapter is about this video's own subject.",
        )
    return qs


PRESENCE_ASK = (
    "A presenter records this explainer. For PASSAGE, who should have the frame while it is "
    "said? Decide from what the words need the viewer to see."
)


def presence_questions() -> Row:
    return {"presence": choice(PRESENCE_ASK, options("presence"))}
