"""An episode's plan as data: its sections, what code derives from them, and its checks.

An episode is planned in words before any picture (`skills/episode-plan`): the brief and its
ledger of claims, then the spine, the chapter list, the sound and the look, then each chapter's
beats and, from those beats, its shots. The model writes the words and how long each part runs.
Everything a reader is told as a number (the clock, the word counts, whether a line fits its shot)
is worked out here, so a plan never states a number nobody measured.

Shots are written from beats, never beside them. A chapter's beats arrive as one section and its
shots as another: `with_shots` puts a shot only under a beat the chapter already has, and
`with_beats` marks the shots of a beat whose words changed as stale until they are written again.

The voice is written with the beat, by the writer who has the material open: a beat carries the
passage it says (`says`), and its shots cut that passage into lines without changing a word. The
checks that read what a line says (`_voice`) look for the faults that keep coming back: a line
that credits the source where it should explain, a second word for made-up material, a caption
read aloud, a figure left for the voice to read, a part with no short sentence in it. The chapter
list is held to rules of the same kind (`top_flags`): one question a part, and a last line that
lands the idea without saying the brief's sentence again.
"""

from __future__ import annotations

import copy
import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: A voice reads about this many words a second.
WORDS_PER_SECOND = 2.2
#: The least air a shot keeps after its narration ends.
SPARE_SECONDS = 0.5
#: On-screen words hold this long a word, plus a moment to find them.
READ_SECONDS_PER_WORD = 0.3
READ_SETTLE_SECONDS = 0.5
#: A shot holds about this many spoken words, and never more than the cap.
SHOT_WORDS = 19
SHOT_WORDS_MOST = 26
#: The separate things one beat may ask the viewer to work out.
DEMANDS_MOST = 2
#: How long an episode runs.
SHORTEST_SECONDS, LONGEST_SECONDS = 240, 600
#: A spoken sentence under this many words is a punch or a question; a part of them is captions
#: read aloud. A part keeps this many, or one in this many of its sentences, whichever is more.
SENTENCE_WORDS = 6
SHORT_SENTENCES_MOST = 2
SHORT_SENTENCES_ONE_IN = 3
#: How often one part names whoever its facts come from.
SOURCE_NAMES_MOST = 1
#: A part of this many sentences or more keeps one under this many words: a voice that never
#: shortens its stride is a lecture.
BREATH_SENTENCES = 6
BREATH_WORDS = 9
#: A chapter of this many beats or more lands them in more than one way: no technique carries
#: over half of them.
MIX_BEATS = 4
#: The film's last line is one a viewer could repeat.
LAST_WORDS_MOST = 16
#: The share of the last line's words (the small ones aside) that may come from the brief's idea
#: before it reads as that sentence said again.
LANDING_SHARED_MOST = 2 / 3

#: A section's kind (`section`). A `list` and the `claims` are the brief; a `spine`, the
#: `chapters` and a `list` are the plan's top layer; a `chapter` holds one chapter's beats, and
#: `shots` the shots written from them.
LIST, CLAIMS, SPINE, CHAPTERS, CHAPTER, SHOTS = (
    "list",
    "claims",
    "spine",
    "chapters",
    "chapter",
    "shots",
)
KINDS = (LIST, CLAIMS, SPINE, CHAPTERS, CHAPTER, SHOTS)
TOP_LAYER, CHAPTER_LAYER = "top", "chapter"

#: Where a claim stands: the material says it, it is made up for the example, or the film wants
#: to say it and the material does not.
STATED, ILLUSTRATIVE, UNCONFIRMED = "stated", "illustrative", "unconfirmed"
STATUSES = (STATED, ILLUSTRATIVE, UNCONFIRMED)
#: The rows a brief holds; `label` joins them when a claim is illustrative.
BRIEF_ROWS = ("idea", "gap", "for", "length", "source")
#: How the film's first line earns the next ten seconds: the open names one.
HOOKS = (
    "question",
    "surprising number",
    "counterintuitive claim",
    "shared pain",
    "metaphor",
    "scenario",
    "stakes",
)
#: How the film's last line lands the idea: the close names one.
LANDINGS = ("callback", "distillation", "generalization", "invitation")
#: How a beat makes its point land: each beat names one.
TECHNIQUES = (
    "worked example",
    "analogy",
    "cause and effect",
    "contrast",
    "counterexample",
    "build-up",
    "demonstration",
    "number made visible",
    "question and answer",
    "callback",
    "distillation",
)
#: The techniques that put the idea in the viewer's hands. A film with neither explains in the
#: abstract from its first beat to its last.
CONCRETE = ("worked example", "analogy")

#: The checks that only reading the words shows. What they find goes back to the writer once and
#: is said to the team, but it does not hold a chapter's shots back: a line can be mended after.
STYLE = frozenset({"credit", "label", "said", "caption", "breath", "mix"})

#: What a beat says, in the words `skills/storyboard`'s beat row uses. Its exact on-screen words,
#: read window and sound accent are its shots', so a beat does not repeat them.
BEAT_WORDS = ("takeaway", "focal", "change", "result", "enters", "leaves")
#: A plan is read before it is built, so each field stays short enough to take in: the most
#: words a field runs to, by the row it is on. Anything longer belongs a level down.
MOST_WORDS: dict[str, dict[str, int]] = {
    "row": {"text": 80, "detail": 80},
    "claim": {"claim": 35, "quote": 60},
    "chapter": {
        "asks": 40,
        "ends": 45,
        "shape": 12,
        "covers": 80,
        "handoff": 45,
        "cue": 25,
        "first": SHOT_WORDS_MOST,
        "last": LAST_WORDS_MOST,
        "turn": 30,
    },
    "beat": {
        "takeaway": 35,
        "says": 70,
        "focal": 20,
        "change": 80,
        "result": 45,
        "enters": 30,
        "leaves": 30,
        "claim": 60,
    },
    "shot": {"move": 6, "shows": 60, "on": 16, "sound": 20},
}
#: A position or a size in pixels: a plan says where a thing is in words, and the storyboard,
#: which has the frame in front of it, measures it.
_PIXELS = re.compile(r"\b\d+(?:\.\d+)?\s?px\b|\b[xy]\s?=\s?\d", re.IGNORECASE)
#: Keys code adds to a row; they are not the row's own words.
_DERIVED = frozenset({"shots", "stale", "time", "start", "speaks", "reads", "found"})
_TOLERANCE = 0.05
_NOT_A_STEM = re.compile(r"[^a-z0-9]+")
#: A line that points at the material as a document, where it should say what the material found.
_PAPER = r"(?:article|blog post|post|paper|write-?up|essay|report|study)(?![\w-])"
_WHOSE = r"(?:the|this|that|their|its|an?|[A-Z][\w.-]*['’]s)"
_CREDIT = re.compile(
    r"\baccording to\b|\bparaphras\w*"
    r"|\bas (?:reported|described|published|written|stated) (?:by|in)\b"
    rf"|\b(?:in|from|per) {_WHOSE} (?:\w+ ){{0,2}}?{_PAPER}"
    rf"|\b{_WHOSE} (?:\w+ ){{0,2}}?{_PAPER} (?:says|said|states|stated|describes|described|"
    r"reports|reported|notes|noted|explains|explained|calls|called|shows|showed|argues|argued|"
    r"gives|gave|lists|listed|puts|found)\b"
    r"|\bthe authors?\b",
    re.IGNORECASE,
)
#: The words a film reaches for to say a thing is made up. The picture carries one label for it
#: (the brief's `label` row); anything else is a second word for the same thing, or the voice
#: spending a line on it. The list grows with every film that finds a new one.
_MADE_UP = re.compile(
    r"\b(?:illustrative|for illustration|fictional|fictitious|hypothetical|placeholder|stand-?in|"
    r"imagined|imaginary|invented|made[- ]up(?! of)|mock(?:ed)?(?:[- ]up)?|reconstructed|"
    r"not real)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?…])[\"”’')\]]*\s+")
#: A second question joined to the first: the mark of a part that is two steps.
_SECOND_QUESTION = re.compile(
    r"\band\s+(?:what|how|why|when|where|who|which|whether|does|do|did|is|are|can|could|should|"
    r"will|would)\b",
    re.IGNORECASE,
)
#: A figure as it is typed: digits, with the marks a number carries. A voice has to decide how
#: to say it, and a count of words takes it for one.
_FIGURE = re.compile(r"[$€£]?\d[\d.,:/×x%–-]*(?:st|nd|rd|th|s|k|m|bn)?", re.IGNORECASE)
_EDGES = " \t\"'“”‘’()[]{}.,;:!?…"
#: Words too small to carry an idea: left out when two sentences are compared for what they say.
_LITTLE = frozenset(
    "a an the of to in on at by for from with and or but so as is are was were be been it its "
    "this that these those not no do does did how what when where why who which you your we our "
    "they their them than then there here into over under up down out if can could will would "
    "should may might just very more most each every one".split()
)
_SPACE = re.compile(r"\s+")
_NOT_SPOKEN = re.compile(r"[^\w]+")
#: What a page's markup adds around its words: emphasis, headings, links.
_MARKUP = re.compile(r"\(https?://[^)\s]*\)|[*_`#>\[\]]")
_CUT = re.compile(r"\s*(?:\[\s*(?:…|\.{3})\s*\]|…|\.{3})\s*")
_TYPED = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "\u00a0": " "})

Section = dict[str, Any]


def read(content: bytes) -> Section:
    """One section of a plan, from the JSON a frame of its board is published from."""
    try:
        parsed = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("a plan's frame is a JSON file holding one section") from error
    if not isinstance(parsed, dict) or not isinstance(parsed.get("section"), str):
        raise ValueError("a plan's frame is a JSON object with a `section` name")
    parsed["layer"] = CHAPTER_LAYER if parsed["section"] in (CHAPTER, SHOTS) else TOP_LAYER
    if parsed["section"] == CHAPTERS:
        # A note sits on a row by its id; a chapter that gives none is known by its name.
        for row in _rows(parsed):
            row.setdefault("id", stem(_said(row, "label")))
    return parsed


def stem(name: str) -> str:
    """A name as a file stem and a row id: lower case, with a hyphen for anything else."""
    return _NOT_A_STEM.sub("-", name.lower()).strip("-")


def words(text: Any) -> int:
    """The words a voice says or an eye reads: tokens with a letter or a digit in them."""
    return sum(1 for token in str(text or "").split() if any(c.isalnum() for c in token))


def clock(seconds: float) -> str:
    """Seconds as m:ss, with a tenth when there is one."""
    tenths = round(seconds * 10)
    whole, tenth = divmod(tenths, 10)
    return f"{whole // 60}:{whole % 60:02d}" + (f".{tenth}" if tenth else "")


def span(start: float, length: float) -> str:
    return f"{clock(start)}–{clock(start + length)}"


def seconds_of(part: Mapping[str, Any]) -> float:
    """A part's length; 0 when it has none that reads as a number."""
    value = part.get("seconds")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return float(value) if value > 0 else 0.0


def _rows(section: Mapping[str, Any], key: str = "rows") -> list[dict[str, Any]]:
    value = section.get(key)
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _said(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    return value.strip() if isinstance(value, str) else ""


def _named(row: Mapping[str, Any], position: int, what: str) -> str:
    return _said(row, "id") or _said(row, "label") or f"{what} {position + 1}"


def _repeats(names: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    twice: list[str] = []
    for name in names:
        if name in seen and name not in twice:
            twice.append(name)
        seen.add(name)
    return twice


# -- one section, as written -------------------------------------------------------------------


def faults(section: Mapping[str, Any]) -> list[str]:
    """What is wrong with one section as it was written, in words its writer can act on. Empty
    when the section can go on the board."""
    kind = section.get("section")
    if kind == LIST:
        return _list_faults(section)
    if kind == CLAIMS:
        return _claims_faults(section)
    if kind == SPINE:
        return _spine_faults(section)
    if kind == CHAPTERS:
        return _chapters_faults(section)
    if kind == CHAPTER:
        return _beats_faults(section)
    if kind == SHOTS:
        return _shots_faults(section)
    return [f"`section` is {kind!r}; a plan's sections are {', '.join(KINDS)}"]


def _missing(row: Mapping[str, Any], name: str, keys: Sequence[str]) -> list[str]:
    absent = [key for key in keys if not _said(row, key)]
    return [f"{name} has no {' or '.join(absent)}"] if absent else []


def _in_words(row: Mapping[str, Any], name: str, kind: str) -> list[str]:
    """What keeps a row from being read at a glance: a field that runs long, or one that gives
    positions and sizes in pixels."""
    found: list[str] = []
    for key, value in row.items():
        text = " ".join(str(v) for v in value) if isinstance(value, list) else value
        if not isinstance(text, str):
            continue
        most = MOST_WORDS[kind].get(key)
        if most is not None and words(text) > most:
            found.append(f"{name}: `{key}` runs to {words(text)} words; say it in {most} or fewer")
        if _PIXELS.search(text):
            found.append(
                f"{name}: `{key}` gives positions or sizes in pixels; a plan says it in words, "
                "and the storyboard measures it"
            )
    return found


def _list_faults(section: Mapping[str, Any]) -> list[str]:
    rows = _rows(section)
    if not rows:
        return ["`rows` is empty: a list holds rows of `id`, `label` and `text`"]
    found = [
        m
        for i, row in enumerate(rows)
        for m in (
            *_missing(row, _named(row, i, "row"), ("id", "label", "text")),
            *_in_words(row, _named(row, i, "row"), "row"),
        )
    ]
    return found + [
        f"two rows are called {name}" for name in _repeats([_said(r, "id") for r in rows])
    ]


def _claims_faults(section: Mapping[str, Any]) -> list[str]:
    rows = _rows(section)
    if not rows:
        return ["`rows` is empty: the ledger holds one row per claim the film may state"]
    found: list[str] = []
    for position, row in enumerate(rows):
        name = f"claim {_said(row, 'id') or position + 1}"
        found += _missing(row, name, ("id", "claim"))
        status = row.get("status")
        if status not in STATUSES:
            found.append(f"{name}: `status` is {status!r}; it is {_listed(STATUSES, 'or')}")
        elif status == STATED and not _said(row, "quote"):
            found.append(f"{name} is stated with no `quote`: the material's own words for it")
        found += _in_words(row, name, "claim")
    return found + [
        f"two claims are called {name}" for name in _repeats([_said(r, "id") for r in rows])
    ]


def brief_faults(brief: Mapping[str, Any], claims: Mapping[str, Any] | None) -> list[str]:
    """What a brief lacks as a whole: a row every later level leans on, a length an episode can
    run, the names the voice would credit, the material's files, and the one label for what is
    made up when the ledger marks a claim illustrative."""
    rows = {_said(row, "id"): row for row in _rows(brief)}
    found = [f"the brief has no `{key}` row" for key in BRIEF_ROWS if key not in rows]
    length = rows.get("length")
    if length is not None and not SHORTEST_SECONDS <= seconds_of(length) <= LONGEST_SECONDS:
        found.append(
            f"`length` needs `seconds` between {SHORTEST_SECONDS} and {LONGEST_SECONDS}: how "
            "long the episode runs"
        )
    source = rows.get("source")
    if source is not None:
        if not isinstance(source.get("names"), list):
            found.append(
                "`source` needs `names`: what the voice would call whoever the facts come from, "
                "as a list (empty when the material is the team's own)"
            )
        if not _texts(source.get("files")):
            found.append("`source` needs `files`: the material's paths under /workspace")
    label = _said(rows.get("label") or {}, "text")
    if words(label) > 3:
        found.append("`label` is the word itself, three words at most")
    made_up = any(row.get("status") == ILLUSTRATIVE for row in _rows(claims or {}))
    if made_up and not label:
        found.append(
            "a claim is illustrative and the brief has no `label` row: the one word the "
            "picture carries for made-up material"
        )
    return found


def material(brief: Mapping[str, Any]) -> list[str]:
    """The paths of the material a brief says it is made from."""
    return next(
        (_texts(row.get("files")) for row in _rows(brief) if _said(row, "id") == "source"), []
    )


def _texts(value: Any) -> list[str]:
    return [str(v).strip() for v in value if str(v).strip()] if isinstance(value, list) else []


def _spine_faults(section: Mapping[str, Any]) -> list[str]:
    rows = _rows(section)
    found = [
        m
        for i, row in enumerate(rows)
        for m in (
            *_missing(row, _named(row, i, "candidate"), ("id", "label", "text")),
            *_in_words(row, _named(row, i, "candidate"), "row"),
        )
    ]
    if len(rows) < 2:
        found.append("a spine is picked from candidates: give at least two, three for choice")
    picked = [row for row in rows if row.get("picked") is True]
    if len(picked) != 1:
        found.append(f"{len(picked)} candidates are `picked`; exactly one is")
    return found


def _chapters_faults(section: Mapping[str, Any]) -> list[str]:
    rows = _rows(section)
    if not rows:
        return ["`rows` is empty: the chapter list holds one row per chapter"]
    found: list[str] = []
    for position, row in enumerate(rows):
        name = _named({"id": _said(row, "label")}, position, "chapter")
        found += _missing(row, name, ("label", "title", "asks", "ends", "covers"))
        if not seconds_of(row):
            found.append(f"{name} has no `seconds`: how long it runs, as a number")
        if position and not _said(row, "handoff"):
            found.append(f"{name} has no `handoff`: what crosses the cut into it")
        if not position:
            if not _said(row, "first"):
                found.append(f"{name} has no `first`: the film's first spoken line, word for word")
            if row.get("hook") not in HOOKS:
                found.append(
                    f"{name}: `hook` is {row.get('hook')!r}; it names how the first line "
                    f"earns the next ten seconds: {_listed(HOOKS, 'or')}"
                )
        if position == len(rows) - 1:
            if not _said(row, "last"):
                found.append(f"{name} has no `last`: the film's last spoken line, word for word")
            if row.get("landing") not in LANDINGS:
                found.append(
                    f"{name}: `landing` is {row.get('landing')!r}; it names how the last line "
                    f"lands the idea: {_listed(LANDINGS, 'or')}"
                )
        found += _in_words(row, name, "chapter")
    found += [f"two chapters are called {n}" for n in _repeats([_said(r, "label") for r in rows])]
    if len(rows) > 2:
        turns = [_said(row, "label") for row in rows if _said(row, "turn")]
        if len(turns) != 1 or turns[0] in (_said(rows[0], "label"), _said(rows[-1], "label")):
            found.append(
                f"`turn` is on {_listed(turns) if turns else 'no part'}; exactly one chapter "
                "between the open and the close carries it: the one thing the film pivots on, "
                "as the viewer sees it happen"
            )
    return found


def _beats_faults(section: Mapping[str, Any]) -> list[str]:
    beats = _rows(section, "beats")
    if not beats:
        return ["`beats` is empty: a chapter holds its beats"]
    found: list[str] = []
    for position, beat in enumerate(beats):
        name = f"beat {_named(beat, position, 'number')}"
        found += _missing(beat, name, ("id", "title", *BEAT_WORDS))
        if not seconds_of(beat):
            found.append(f"{name} has no `seconds`: how long it runs, as a number")
        if not isinstance(beat.get("says"), str):
            found.append(
                f"{name} has no `says`: the words the voice says over it, or an empty string "
                "for a beat that plays in silence"
            )
        if beat.get("technique") not in TECHNIQUES:
            found.append(
                f"{name}: `technique` is {beat.get('technique')!r}; it names how the beat "
                f"makes its point land: {_listed(TECHNIQUES, 'or')}"
            )
        demands = beat.get("demands")
        if not isinstance(demands, list) or not [d for d in demands if str(d).strip()]:
            found.append(f"{name} lists no `demands`: each thing the viewer must work out")
        found += _in_words(beat, name, "beat")
        if "shots" in beat:
            found.append(
                f"{name} carries shots: a chapter's beats are published without them, and its "
                "shots come in their own section, written from the beats"
            )
    found += [f"two beats are called {n}" for n in _repeats([_said(b, "id") for b in beats])]
    if not found and not any(_said(beat, "says") for beat in beats):
        found.append("no beat says anything: an episode is led by its voice")
    return found


def _shots_faults(section: Mapping[str, Any]) -> list[str]:
    shots = _rows(section, "shots")
    if not shots:
        return ["`shots` is empty: the section holds every shot of the chapter"]
    found: list[str] = []
    for position, shot in enumerate(shots):
        name = f"shot {_named(shot, position, 'number')}"
        found += _missing(shot, name, ("id", "beat", "move", "shows"))
        length = seconds_of(shot)
        if not length:
            found.append(f"{name} has no `seconds`: how long it runs, as a number")
        at = shot.get("at", 0)
        if (
            isinstance(at, bool)
            or not isinstance(at, int | float)
            or at < 0
            or (length and at >= length)
        ):
            found.append(f"{name}: `at` is when its words land, in seconds from its start")
        found += _in_words(shot, name, "shot")
    found += [f"two shots are called {n}" for n in _repeats([_said(s, "id") for s in shots])]
    return found


# -- shots go under beats ----------------------------------------------------------------------


def _own_words(beat: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in beat.items() if key not in _DERIVED}


def with_beats(new: Mapping[str, Any], old: Mapping[str, Any] | None) -> Section:
    """A chapter's beats as newly written, on top of the chapter as it stood. A beat that reads
    as it did keeps its shots. One whose words or length changed keeps them marked `stale`: they
    were written from the beat as it was, and stay stale until they are written again."""
    merged: Section = copy.deepcopy(dict(new))
    before = {str(b.get("id")): b for b in _rows(old or {}, "beats")}
    for beat in _rows(merged, "beats"):
        was = before.get(str(beat.get("id")))
        if was is None or not was.get("shots"):
            continue
        beat["shots"] = copy.deepcopy(was["shots"])
        if was.get("stale") or _own_words(was) != _own_words(beat):
            beat["stale"] = True
    return merged


def with_shots(chapter: Mapping[str, Any], shots: Mapping[str, Any]) -> Section:
    """The chapter with these shots under its beats. A shot goes only under a beat the chapter
    already has; every beat the section writes shots for has all of its shots replaced, and is no
    longer stale. Raises ValueError for a shot whose beat is not there."""
    merged: Section = copy.deepcopy(dict(chapter))
    beats = {str(b.get("id")): b for b in _rows(merged, "beats")}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for shot in _rows(shots, "shots"):
        beat = str(shot.get("beat") or "")
        if beat not in beats:
            raise ValueError(
                f"shot {shot.get('id')} is under beat {beat or '(none)'}, which the chapter does "
                f"not have (its beats: {', '.join(beats) or 'none'})"
            )
        grouped.setdefault(beat, []).append({k: v for k, v in shot.items() if k != "beat"})
    for beat, lines in grouped.items():
        beats[beat]["shots"] = lines
        beats[beat].pop("stale", None)
    return merged


def changed(now: Mapping[str, Any], before: Mapping[str, Any] | None) -> list[str]:
    """The rows of a section whose words differ from the version before it, by id: a list's
    rows, or a chapter's beats and shots. A row the earlier version did not have is new, not
    changed."""
    if before is None:
        return []
    was = _by_id(before)
    return sorted(
        key
        for key, row in _by_id(now).items()
        if key in was and _own_words(was[key]) != _own_words(row)
    )


def _by_id(section: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if section.get("section") != CHAPTER:
        return {str(row.get("id")): row for row in _rows(section)}
    rows: dict[str, dict[str, Any]] = {}
    for beat in _rows(section, "beats"):
        rows[str(beat.get("id"))] = beat
        rows.update({str(shot.get("id")): shot for shot in _rows(beat, "shots")})
    return rows


def written(chapter: Mapping[str, Any] | None) -> bool:
    """Whether a chapter is written in full: every beat has shots written from it as it stands."""
    beats = _rows(chapter or {}, "beats")
    return bool(beats) and all(b.get("shots") and not b.get("stale") for b in beats)


# -- what code derives -------------------------------------------------------------------------


def _chapter_rows(sections: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    return next((_rows(s) for s in sections.values() if s.get("section") == CHAPTERS), [])


def _chapters(sections: Mapping[str, Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {name: s for name, s in sections.items() if s.get("section") == CHAPTER}


def timed(sections: Mapping[str, Mapping[str, Any]]) -> dict[str, Section]:
    """The sections with their clock filled in: when each chapter, beat and shot starts and ends,
    and how much of a chapter is spoken. `sections` is keyed by name as the board names them; a
    chapter starts where the row of the chapter list that carries its name puts it."""
    out: dict[str, Section] = {name: copy.deepcopy(dict(s)) for name, s in sections.items()}
    starts: dict[str, tuple[float, float]] = {}
    at = 0.0
    for row in _chapter_rows(out):
        length = seconds_of(row)
        row["time"], row["start"] = span(at, length), at
        starts[_said(row, "label")] = (at, length)
        at += length
    for name, chapter in out.items():
        if chapter.get("section") != CHAPTER:
            continue
        beats = _rows(chapter, "beats")
        start, length = starts.get(name, (0.0, sum(seconds_of(b) for b in beats)))
        chapter["time"], chapter["start"], chapter["seconds"] = span(start, length), start, length
        cursor, spoken = start, 0
        for beat in beats:
            beat["time"], beat["start"] = span(cursor, seconds_of(beat)), cursor
            inner = cursor
            for shot in _rows(beat, "shots"):
                shot["time"], shot["start"] = span(inner, seconds_of(shot)), inner
                shot["speaks"] = round(words(shot.get("vo")) / WORDS_PER_SECOND, 1)
                shown = words(shot.get("on"))
                shot["reads"] = (
                    round(READ_SECONDS_PER_WORD * shown + READ_SETTLE_SECONDS, 1) if shown else 0.0
                )
                inner += seconds_of(shot)
            # The passage is the beat's; its shots only cut it, so the count is the same.
            lines = _said(beat, "says") or " ".join(_said(s, "vo") for s in _rows(beat, "shots"))
            beat["speaks"] = round(words(lines) / WORDS_PER_SECOND, 1)
            spoken += words(lines)
            cursor += seconds_of(beat)
        if spoken:
            said = round(spoken / WORDS_PER_SECOND)
            chapter["words"] = f"{spoken} words · {said} s of {_whole(length)} s"
    return out


def _whole(value: float) -> str:
    return str(int(value)) if abs(value - round(value)) < _TOLERANCE else f"{value:.1f}"


@dataclass
class _Tally:
    """What the checks count across the chapters they are given."""

    beats: int = 0
    shots: int = 0
    #: Beats whose shots were held against their passage, and parts with a word spoken.
    voiced: int = 0
    spoken: int = 0
    #: Which of the film's two edges were looked at: its first line, its last.
    edges: set[str] = field(default_factory=set)
    slack: list[float] = field(default_factory=list)
    reads: list[float] = field(default_factory=list)
    long: list[str] = field(default_factory=list)
    #: How the beats explain: each technique and the beats that name it.
    ways: Counter[str] = field(default_factory=Counter)
    flags: dict[str, list[str]] = field(default_factory=dict)

    def flag(self, check: str, text: str) -> None:
        self.flags.setdefault(check, []).append(text)


def _tally(tally: _Tally, name: str, chapter: Mapping[str, Any], length: float | None) -> None:
    beats = _rows(chapter, "beats")
    tally.beats += len(beats)
    total = sum(seconds_of(b) for b in beats)
    if length is not None and abs(total - length) > _TOLERANCE:
        tally.flag("clock", f"{name}: its beats add up to {_whole(total)} s of {_whole(length)} s")
    bare = [str(b.get("id")) for b in beats if not b.get("shots")]
    if bare:
        tally.flag(
            "unwritten",
            f"{name}: {_listed(bare)} {'has' if len(bare) == 1 else 'have'} no shots yet",
        )
    named = Counter(str(b.get("technique")) for b in beats if b.get("technique") in TECHNIQUES)
    tally.ways.update(named)
    if sum(named.values()) >= MIX_BEATS:
        most, count = named.most_common(1)[0]
        if count * 2 > sum(named.values()):
            tally.flag(
                "mix",
                f"{name}: {count} of its {sum(named.values())} beats explain by {most}; land "
                "some of them another way",
            )
    for beat in beats:
        demands = [d for d in beat.get("demands") or [] if str(d).strip()]
        if len(demands) > DEMANDS_MOST:
            tally.flag("demands", f"{beat.get('id')}: {len(demands)} demands")
        shots = _rows(beat, "shots")
        if not shots:
            _tally_passage(tally, beat)
            continue
        if beat.get("stale"):
            tally.flag("stale", f"{beat.get('id')}: its shots were written from the beat as it was")
            continue
        tally.shots += len(shots)
        if isinstance(beat.get("says"), str):
            tally.voiced += 1
            apart = _apart(beat["says"], " ".join(_said(s, "vo") for s in shots))
            if apart:
                tally.flag("voice", f"{beat.get('id')}: {apart}")
        inside = sum(seconds_of(s) for s in shots)
        if abs(inside - seconds_of(beat)) > _TOLERANCE:
            tally.flag(
                "clock",
                f"{beat.get('id')}: its shots add up to {_whole(inside)} s of "
                f"{_whole(seconds_of(beat))} s",
            )
        for shot in shots:
            _tally_shot(tally, shot)


def _tally_passage(tally: _Tally, beat: Mapping[str, Any]) -> None:
    """A beat with no shots yet: whether its passage can be said in the time the beat has, cut
    into as few shots as the words allow, each with its air."""
    spoken, length = words(beat.get("says")), seconds_of(beat)
    need = spoken / WORDS_PER_SECOND + SPARE_SECONDS * math.ceil(spoken / SHOT_WORDS_MOST)
    if spoken and need > length + _TOLERANCE:
        tally.flag(
            "fits", f"{beat.get('id')}: its {spoken} words need {need:.1f} s of {_whole(length)} s"
        )


def _flat(text: str) -> str:
    """A passage as it is shown: one space between words, and the quotes a keyboard types."""
    return _SPACE.sub(" ", text.translate(_TYPED)).strip()


def _spoken(text: str) -> list[str]:
    """The words a voice says, as they are compared: no case and no punctuation, because a
    capital or a comma moved at a cut changes nothing anyone hears."""
    said = (_NOT_SPOKEN.sub("", word).lower() for word in _flat(text).split())
    return [word for word in said if word]


def _apart(passage: str, lines: str) -> str:
    """Where a beat's shots leave its passage, with the words either side; empty when the shots
    say the passage word for word."""
    said, cut = _spoken(passage), _spoken(lines)
    if said == cut:
        return ""
    at = next((i for i, (a, b) in enumerate(zip(said, cut, strict=False)) if a != b), None)
    at = min(len(said), len(cut)) if at is None else at
    here = " ".join(said[max(0, at - 3) : at + 4]) or "its end"
    there = " ".join(cut[max(0, at - 3) : at + 4]) or "nothing"
    return f"its shots leave its passage at “{here}” (they say “{there}”)"


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_END.split(text) if part.strip()]


@dataclass(frozen=True)
class Given:
    """What every chapter is held to from the levels above it: the names the voice would credit
    and the one label for made-up material (the brief), and the film's first and last spoken
    lines with the parts that carry them (the chapter list)."""

    names: tuple[str, ...] = ()
    label: str = ""
    opens: str = ""
    first: str = ""
    closes: str = ""
    last: str = ""


def given(sections: Mapping[str, Mapping[str, Any]]) -> Given:
    """What the sections at hand hold every chapter to (`Given`)."""
    names: list[str] = []
    label = ""
    for section in sections.values():
        if section.get("section") != LIST:
            continue
        for row in _rows(section):
            if _said(row, "id") == "source":
                names = _texts(row.get("names"))
            elif _said(row, "id") == "label":
                label = _said(row, "text")
    rows = _chapter_rows(sections)
    first, last = (rows[0], rows[-1]) if rows else ({}, {})
    return Given(
        names=tuple(names),
        label=label,
        opens=_said(first, "label"),
        first=_said(first, "first"),
        closes=_said(last, "label"),
        last=_said(last, "last"),
    )


def _voice(tally: _Tally, name: str, chapter: Mapping[str, Any], held: Given, part: str) -> None:
    """What a chapter's voice gets wrong that only reading it shows. `name` is how the chapter
    is called in what is found; `part` is its name in the chapter list."""
    beats = _rows(chapter, "beats")
    spoken = [(str(b.get("id")), _said(b, "says")) for b in beats if _said(b, "says")]
    if not spoken:
        return
    tally.spoken += 1
    if held.first and part == held.opens:
        tally.edges.add("first")
        first = _spoken(held.first)
        if _spoken(spoken[0][1])[: len(first)] != first:
            tally.flag("edges", f"{name}: it does not open on the first line (“{held.first}”)")
    if held.last and part == held.closes:
        tally.edges.add("last")
        last = _spoken(held.last)
        if _spoken(spoken[-1][1])[-len(last) :] != last:
            tally.flag("edges", f"{name}: it does not close on the last line (“{held.last}”)")
    for key, text in spoken:
        for hit in _CREDIT.finditer(text):
            tally.flag("credit", f"{key}: “{hit.group(0)}” points at the source; say what it found")
        for hit in _MADE_UP.finditer(text):
            tally.flag(
                "label",
                f"{key}: the voice says “{hit.group(0)}”; the picture's label carries what is "
                "made up",
            )
    named = [
        hit
        for _, text in spoken
        for who in held.names
        for hit in re.findall(rf"\b{re.escape(who)}\b", text, re.IGNORECASE)
    ]
    if len(named) > SOURCE_NAMES_MOST:
        tally.flag("credit", f"{name}: it names {named[0]} {len(named)} times; once is enough")
    for beat in beats:
        for shot in _rows(beat, "shots"):
            shown = _said(shot, "on")
            if _MADE_UP.search(shown) or (held.label and held.label.lower() in shown.lower()):
                tally.flag(
                    "label",
                    f"{shot.get('id')}: “{shown}” is on screen; the look's one label already "
                    "says what is made up",
                )
    for key, text in spoken:
        for figure in _figures(text):
            tally.flag(
                "said",
                f"{key}: the voice is left to read “{figure}”; write it the way it is said, and "
                "let the picture carry the figure",
            )
    said = [s for _, text in spoken for s in _sentences(text)]
    lengths = [words(s) for s in said]
    if len(said) >= BREATH_SENTENCES and min(lengths) >= BREATH_WORDS:
        run = f"{min(lengths)} to {max(lengths)}" if min(lengths) < max(lengths) else min(lengths)
        tally.flag(
            "breath",
            f"{name}: its {len(said)} sentences all run {run} words; give it one under "
            f"{BREATH_WORDS} where a point lands",
        )
    short = [s for s in said if words(s) < SENTENCE_WORDS]
    if len(short) > max(SHORT_SENTENCES_MOST, len(said) // SHORT_SENTENCES_ONE_IN):
        quoted = ", ".join(f"“{line}”" for line in short)
        tally.flag(
            "caption",
            f"{name}: {len(short)} of its {len(said)} sentences run under {SENTENCE_WORDS} "
            f"words ({quoted})",
        )


def _figures(text: str) -> list[str]:
    """The figures a passage leaves for the voice to read: tokens that are digits and number
    marks. A small whole number after a name ("Apollo 11") is part of the name, and stays."""
    found: list[str] = []
    before = ""
    for token in text.split():
        core = token.strip(_EDGES)
        named = core.isdigit() and len(core) <= 2 and before[:1].isupper()
        if _FIGURE.fullmatch(core) and not named:
            found.append(core)
        before = core
    return found


def _content(text: str) -> list[str]:
    """A sentence's words that carry what it says: the small ones left out."""
    return [word for word in _spoken(text) if word not in _LITTLE]


def top_flags(sections: Mapping[str, Mapping[str, Any]]) -> dict[str, list[str]]:
    """What reading the chapter list shows that its form does not: a part that asks two
    questions (`one`), and a last line that is the brief's idea said again (`landing`). Keyed by
    the check each belongs to; empty when the list holds."""
    rows = _chapter_rows(sections)
    found: dict[str, list[str]] = {}
    for row in rows:
        asks = _said(row, "asks")
        if asks.count("?") > 1 or _SECOND_QUESTION.search(asks):
            found.setdefault("one", []).append(
                f"{_said(row, 'label')} asks more than one question (“{asks}”); a part is one "
                "step, and what does not fit is left out"
            )
    idea = next(
        (
            _said(row, "text")
            for s in sections.values()
            if s.get("section") == LIST
            for row in _rows(s)
            if _said(row, "id") == "idea"
        ),
        "",
    )
    last = _content(_said(rows[-1], "last")) if rows else []
    if idea and last:
        heard = set(_content(idea))
        shared = sum(1 for word in last if word in heard)
        if shared > len(last) * LANDING_SHARED_MOST:
            found.setdefault("landing", []).append(
                f"the last line is the brief's idea said again ({shared} of its {len(last)} "
                "words are the brief's); land it in a line the film has earned"
            )
    return found


def ways(chapter: Mapping[str, Any]) -> dict[str, int]:
    """How a chapter's beats explain: each technique they name, and how many beats name it."""
    named = Counter(
        str(b.get("technique")) for b in _rows(chapter, "beats") if b.get("technique") in TECHNIQUES
    )
    return dict(named.most_common())


def _tally_shot(tally: _Tally, shot: Mapping[str, Any]) -> None:
    name, length = str(shot.get("id")), seconds_of(shot)
    spoken = words(shot.get("vo"))
    if spoken:
        need = spoken / WORDS_PER_SECOND
        tally.slack.append(length - need)
        if length - need < SPARE_SECONDS - _TOLERANCE:
            tally.flag("fits", f"{name}: {spoken} words need {need:.1f} s of {_whole(length)} s")
        if spoken > SHOT_WORDS_MOST:
            tally.flag("load", f"{name}: {spoken} words")
        elif spoken > SHOT_WORDS:
            tally.long.append(f"{name} ({spoken})")
    shown = words(shot.get("on"))
    if shown:
        at = shot.get("at", 0)
        window = length - (
            float(at) if isinstance(at, int | float) and not isinstance(at, bool) else 0.0
        )
        need = READ_SECONDS_PER_WORD * shown + READ_SETTLE_SECONDS
        tally.reads.append(window - need)
        if window + _TOLERANCE < need:
            tally.flag(
                "read",
                f"{name} “{shot.get('on')}”: {shown} words need {need:.1f} s, get {window:.1f} s",
            )


def _listed(names: Sequence[str], joiner: str = "and") -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} {joiner} {names[-1]}"


def chapter_faults(
    chapter: Mapping[str, Any],
    seconds: float | None = None,
    *,
    shots: bool = True,
    held: Given | None = None,
    part: str = "",
    style: bool = True,
) -> list[str]:
    """What the checks find in one chapter, for whoever wrote it: each line names the beat or
    shot and the numbers. `seconds` is the chapter's length in the chapter list, when the caller
    knows it. With `shots` false the chapter is its beats alone, which have no shots yet. `held`
    is what the levels above hold it to, and `part` its name in the chapter list. With `style`
    false, what only reading the words shows (`STYLE`) is left out: what remains is what its
    shots cannot be written over."""
    tally = _Tally()
    _tally(tally, "the chapter", chapter, seconds)
    _voice(tally, "the chapter", chapter, held or Given(), part)
    if not shots:
        tally.flags.pop("unwritten", None)
    return [
        text
        for check, flags in tally.flags.items()
        if style or check not in STYLE
        for text in flags
    ]


def checks(sections: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The plan's checks, worked out from its sections as they stand: one row each with what it
    checks (`rule`), what it found (`text`) and its `state`: pass, fail, or wait when there is
    nothing written to check yet."""
    rows = _chapter_rows(sections)
    lengths = {_said(row, "label"): seconds_of(row) for row in rows}
    chapters = _chapters(sections)
    held = given(sections)
    tally = _Tally()
    for name, chapter in chapters.items():
        _tally(tally, name, chapter, lengths.get(name))
        _voice(tally, name, chapter, held, name)
    total = sum(lengths.values())
    stated = next(
        (
            seconds_of(row)
            for s in sections.values()
            if s.get("section") == LIST
            for row in _rows(s)
            if _said(row, "id") == "length"
        ),
        0.0,
    )
    if rows and stated and abs(stated - total) > _TOLERANCE:
        tally.flag(
            "clock", f"the chapters add up to {clock(total)}, and the brief says {clock(stated)}"
        )
    if rows and not SHORTEST_SECONDS <= total <= LONGEST_SECONDS:
        tally.flag(
            "clock",
            f"the chapters add up to {clock(total)}; an episode runs {clock(SHORTEST_SECONDS)} to "
            f"{clock(LONGEST_SECONDS)}",
        )
    done = sum(1 for name in lengths if written(chapters.get(name)))
    parts = f"{len(rows)} part{'s' if len(rows) != 1 else ''} add up to {clock(total)}"
    inside = (
        f", with {tally.beats} beats and {tally.shots} shots inside them" if tally.shots else ""
    )
    progress = f" {done} of {len(rows)} chapters are written." if rows and done < len(rows) else ""
    waiting = "No shots are written yet."
    silent = "No beats are written yet."
    over = f" Over {SHOT_WORDS}: {', '.join(tally.long)}." if tally.long else ""
    todo = tally.flags.get("unwritten", [])
    edges = {
        "first": "The open starts on its first line.",
        "last": "The close ends on its last line.",
    }
    credited = f", and no part names {_listed(held.names, 'or')} twice" if held.names else ""
    labelled = f": the label “{held.label}” carries it" if held.label else ""
    top = top_flags(sections)
    landing = str(rows[-1].get("landing") or "last line") if rows else ""
    counted = ", ".join(f"{way} {count}" for way, count in tally.ways.most_common())
    if (
        rows
        and all(name in chapters for name in lengths)
        and not any(tally.ways[way] for way in CONCRETE)
    ):
        tally.flag(
            "mix",
            f"no beat explains by {_listed(CONCRETE, 'or')}: nothing puts the idea in the "
            "viewer's hands",
        )
    return [
        _check(
            "clock",
            "The clock is covered once",
            "Chapters, beats and shots tile the episode with no gap and no overlap.",
            tally.flags.get("clock", []),
            f"{parts}{inside}.{progress}" if rows else "",
            "The chapter list is not written yet.",
        ),
        _check(
            "fits",
            "The narration fits its shot",
            f"At {WORDS_PER_SECOND} words a second, each line ends at least {SPARE_SECONDS} s "
            "before its shot does.",
            tally.flags.get("fits", []),
            f"All {len(tally.slack)} lines fit; the tightest keeps {min(tally.slack):.1f} s spare."
            if tally.slack
            else "",
            waiting,
        ),
        _check(
            "load",
            "No shot carries too many words",
            f"A shot holds about {SHOT_WORDS} spoken words, and never more than {SHOT_WORDS_MOST}.",
            tally.flags.get("load", []),
            f"None is over {SHOT_WORDS_MOST}.{over}" if tally.shots else "",
            waiting,
        ),
        _check(
            "read",
            "On-screen words stay long enough to read",
            f"Each holds {READ_SECONDS_PER_WORD} s a word plus {READ_SETTLE_SECONDS} s.",
            tally.flags.get("read", []),
            (
                f"All {len(tally.reads)} hold; the tightest has {min(tally.reads):.1f} s spare."
                if tally.reads
                else "No shot puts words on screen."
            )
            if tally.shots
            else "",
            waiting,
        ),
        _check(
            "one",
            "A chapter answers one question",
            "Each part asks one question; what does not fit is left out, not packed in.",
            top.get("one", []),
            f"All {len(rows)} parts ask one question." if rows else "",
            "The chapter list is not written yet.",
        ),
        _check(
            "landing",
            "The last line lands the idea, it does not repeat it",
            f"The film ends on a line of {LAST_WORDS_MOST} words or fewer that is not the "
            "brief's sentence again.",
            top.get("landing", []),
            f"The last line is a {landing} of {words(held.last)} words." if held.last else "",
            "The chapter list gives no last line.",
        ),
        _check(
            "demands",
            "A beat asks for two things at most",
            "Each beat lists one or two things the viewer must work out.",
            tally.flags.get("demands", []),
            f"All {tally.beats} beats list one or two." if tally.beats else "",
            "No beats are written yet.",
        ),
        _check(
            "stale",
            "Shots are written from the beat as it stands",
            "A beat whose words changed has its shots written again before the plan is approved.",
            tally.flags.get("stale", []),
            (
                f"Every one of the {tally.beats} beats has its shots."
                if not todo
                else " ".join(f"{text}." for text in todo)
            )
            if tally.beats
            else "",
            "No beats are written yet.",
            pending=bool(todo),
        ),
        _check(
            "voice",
            "Each shot says its beat's words",
            "A beat's passage is written with the material open; its shots cut it into lines "
            "and change no word.",
            tally.flags.get("voice", []),
            f"The shots of all {tally.voiced} beats add up to their passages."
            if tally.voiced
            else "",
            waiting,
        ),
        _check(
            "edges",
            "It opens and closes on the lines in the chapter list",
            "The open starts on the list's first line, and the close ends on its last.",
            tally.flags.get("edges", []),
            " ".join(text for key, text in edges.items() if key in tally.edges),
            "The open and the close are not written yet."
            if held.first or held.last
            else "The chapter list gives no first or last line.",
            pending=len(tally.edges) < len(edges),
        ),
        _check(
            "credit",
            "The voice explains, it does not credit",
            "No line points at the material as a document, and a part names where its facts "
            f"come from {'once' if SOURCE_NAMES_MOST == 1 else SOURCE_NAMES_MOST} at most.",
            tally.flags.get("credit", []),
            f"No line credits the source{credited}." if tally.spoken else "",
            silent,
        ),
        _check(
            "label",
            "What is made up is marked once, on the picture",
            "The voice never says a thing is made up, and no shot puts a word for it on screen.",
            tally.flags.get("label", []),
            f"Nothing spoken or on screen says a thing is made up{labelled}."
            if tally.spoken
            else "",
            silent,
        ),
        _check(
            "said",
            "The voice is written as it is said",
            "A figure in the voice is spelled the way it is spoken; the picture carries the "
            "digits.",
            tally.flags.get("said", []),
            "No line leaves a figure for the voice to read." if tally.spoken else "",
            silent,
        ),
        _check(
            "caption",
            "A line is a sentence, not a caption",
            f"A part keeps {SHORT_SENTENCES_MOST} sentences under {SENTENCE_WORDS} words, or one "
            f"in {SHORT_SENTENCES_ONE_IN} of its sentences, whichever is more.",
            tally.flags.get("caption", []),
            "No part reads as captions." if tally.spoken else "",
            silent,
        ),
        _check(
            "breath",
            "A part is not one long breath",
            f"A part of {BREATH_SENTENCES} sentences or more has one under {BREATH_WORDS} words.",
            tally.flags.get("breath", []),
            "Every long part has a short sentence in it." if tally.spoken else "",
            silent,
        ),
        _check(
            "mix",
            "The film explains in more than one way",
            f"No technique carries over half the beats of a chapter of {MIX_BEATS} or more, and "
            f"some beat explains by {_listed(CONCRETE, 'or')}.",
            tally.flags.get("mix", []),
            f"The {tally.beats} beats explain by {counted}." if counted else "",
            silent,
        ),
    ]


def quoted(claims: Mapping[str, Any], material: str) -> Section:
    """The ledger with every stated row marked `found`: whether its quote is in the material,
    word for word. A quote cut with … is found when each piece is there, in order. Markup, case
    and spacing are not words, so they are not compared."""
    text = _plain(material)
    marked: Section = copy.deepcopy(dict(claims))
    for row in _rows(marked):
        if row.get("status") != STATED:
            continue
        at = 0
        pieces = [_plain(piece).strip(" \"'.,;:") for piece in _CUT.split(_said(row, "quote"))]
        for piece in [piece for piece in pieces if piece]:
            at = text.find(piece, at)
            if at < 0:
                break
            at += len(piece)
        row["found"] = at >= 0 and any(pieces)
    return marked


def brief_checks(sections: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """A brief's checks, worked out from its sections as they stand: whether each quote in the
    ledger is in the material, and whether the film would state something the material does
    not."""
    rows = next((_rows(s) for s in sections.values() if s.get("section") == CLAIMS), [])
    stated = [row for row in rows if row.get("status") == STATED]
    looked = [row for row in stated if isinstance(row.get("found"), bool)]
    made_up = sum(1 for row in rows if row.get("status") == ILLUSTRATIVE)
    counted = f"{len(stated)} stated, {made_up} illustrative, none unconfirmed."
    return [
        _check(
            "quotes",
            "Every quote is in the material",
            "A stated claim carries the material's own words, and each is looked up there.",
            [
                f"{row.get('id')}: its quote is not in the material"
                for row in looked
                if not row["found"]
            ],
            f"All {len(looked)} quotes are in the material." if looked else "",
            "The material could not be read, so no quote was looked up."
            if stated
            else "The ledger is not written yet.",
            pending=len(looked) < len(stated),
        ),
        _check(
            "stated",
            "The film states only what the material says",
            "A claim the material does not make is left out, or sourced before the plan is "
            "written.",
            [f"{row.get('id')} is unconfirmed" for row in rows if row.get("status") == UNCONFIRMED],
            counted if rows else "",
            "The ledger is not written yet.",
        ),
    ]


def _plain(text: str) -> str:
    plain = _MARKUP.sub("", unicodedata.normalize("NFKC", text).translate(_TYPED))
    return _SPACE.sub(" ", plain).lower().strip()


#: What each check is about, so a long list reads in parts: the clock, the plan's structure, the
#: words the voice says, and the brief's facts.
_GROUPS = {
    **dict.fromkeys(("clock", "fits", "load", "read"), "time"),
    **dict.fromkeys(("one", "landing", "demands", "stale", "voice", "edges"), "structure"),
    **dict.fromkeys(("credit", "label", "said", "caption", "breath", "mix"), "words"),
    **dict.fromkeys(("quotes", "stated"), "facts"),
}


def _check(
    key: str,
    label: str,
    rule: str,
    flags: Sequence[str],
    found: str,
    nothing: str,
    *,
    pending: bool = False,
) -> dict[str, Any]:
    row = {"id": key, "label": label, "rule": rule, "group": _GROUPS.get(key, "")}
    if flags:
        return {**row, "state": "fail", "text": " · ".join(flags)}
    if not found or pending:
        return {**row, "state": "wait", "text": found or nothing}
    return {**row, "state": "pass", "text": found}
