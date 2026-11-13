"""The demo's sample plan, and the scripted writers that hand it to the `episode_plan` pipeline.

The demo runs the real pipeline (`design_agent.pipelines.episode_plan`): its order, its checks and
what it sends back are the product's. Only the words are canned. Each writer here answers one of
the pipeline's briefs the way a helper would, by writing its file and reporting it: the brief and
its ledger, the spine, the chapter list, one chapter's beats, and that chapter's shots, and the
first reader's verdict, which sends one chapter back when it has read several. Two more only
report: the ones that read the top layer and a chapter's beats back. The plan is one sample
(`demo_plan.json`, a five-minute explainer on how a docs search works), whatever the material.

A part written again takes the sample's prepared rewrite of the rows the team named, so a second
pass reads differently from the first; rows with no prepared rewrite come back as they were. A
beat's passage is the lines of its shots, joined, so a rewrite of either keeps the two the same.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from design_agent.testing.scripted_model import reply, tool_calls

#: The sample: the top layer's four sections, each chapter's beats and shots by its name, and the
#: prepared rewrites by section and row.
PLAN: dict[str, Any] = json.loads(
    Path(__file__).with_name("demo_plan.json").read_text(encoding="utf-8")
)
#: The brief's sections and the plan's top layer, as their boards name them: the key in the
#: sample, and the file.
BRIEF: dict[str, tuple[str, str]] = {
    "Brief": ("brief", "brief.json"),
    "Claims": ("claims", "claims.json"),
}
TOP: dict[str, tuple[str, str]] = {
    "Spine": ("spine", "spine.json"),
    "Chapters": ("chapters", "chapters.json"),
    "Sound and look": ("sound", "sound-look.json"),
}
#: Every row of a section, for a part written again as a whole.
ALL = "*"
#: The sample's material: the post its ledger quotes, as the demo's lead writes it to a file.
MATERIAL: str = PLAN["material"]

_WORK = re.compile(r"(/workspace/projects/[^/\s]+)/plan/")
_CHAPTER = re.compile(r"You write the (beats|shots) of “([^”]+)”")
_STANDING = re.compile(r"You read back the beats of “([^”]+)”")
_FILES = re.compile(r"THE MATERIAL[^\n]*\n((?:- [^\n]+\n)+)")
_JUST_WRITTEN = re.compile(r"at the same time: ([^\n]+?)\. You read the film")
#: What the sample's reader says of each chapter's weakest line: its first that says anything.
_WEAKEST = "“{line}” It tells the viewer what happens before it gives them a reason to care."
_NOTES = re.compile(r"NOTES FROM THE LEAD\n(.*?)\nIf the files you are asked for", re.DOTALL)
_ROW = re.compile(r"“([^”]+)”(?:, at (?:beat |frame )?([\w.]+))?")


def lengths() -> dict[str, float]:
    """Each chapter of the sample, with how long it runs."""
    return {str(row["label"]): float(row["seconds"]) for row in PLAN["chapters"]["rows"]}


def stem(name: str) -> str:
    """A chapter's file stem, as the pipeline names it."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def note_line(name: str, row: str) -> str:
    """One line of the notes a writer is given: the section, and the row when there is one."""
    return f"“{name}”" if row == ALL else f"“{name}”, at {'frame' if '.' in row else 'beat'} {row}"


def rows_in(notes: str, name: str) -> list[str]:
    """The rows of `name` the notes ask to have written again (`ALL` for the whole of it)."""
    return [row or ALL for section, row in _ROW.findall(notes) if section == name]


def _edits(name: str, rows: Sequence[str]) -> dict[str, dict[str, str]]:
    """The prepared rewrites for these rows: for a beat, its own and its shots'."""
    found: dict[str, dict[str, str]] = {}
    for edit in PLAN["revisions"].get(name, []):
        anchor = str(edit["anchor"])
        if ALL in rows or anchor in rows or anchor.split(".")[0] in rows:
            found.setdefault(anchor, {})[str(edit["field"])] = str(edit["text"])
    return found


def _revised(section: dict[str, Any], key: str, name: str, rows: Sequence[str]) -> dict[str, Any]:
    out: dict[str, Any] = copy.deepcopy(section)
    edits = _edits(name, rows)
    for row in out[key]:
        row.update(edits.get(str(row.get("id")), {}))
    return out


def top(name: str, rows: Sequence[str] = ()) -> dict[str, Any]:
    """A section of the brief or of the top layer, with the rows written again so far."""
    return _revised(PLAN[{**BRIEF, **TOP}[name][0]], "rows", name, rows)


def beats(name: str, rows: Sequence[str] = ()) -> dict[str, Any]:
    """A chapter's beats. Each one's passage is what its shots say, in order."""
    section = _revised(PLAN["beats"][name], "beats", name, rows)
    lines = shots(name, rows)["shots"]
    for beat in section["beats"]:
        said = " ".join(str(s["vo"]) for s in lines if s["beat"] == beat["id"] and s.get("vo"))
        _after(beat, "technique", "says", said)
    return section


def _after(row: dict[str, Any], key: str, name: str, value: Any) -> None:
    """Put `name` into a row right after `key`, so the file reads in the order it is taught."""
    items = [(k, v) for k, v in row.items() if k != name]
    at = next((i for i, (k, _) in enumerate(items) if k == key), len(items) - 1) + 1
    row.clear()
    row.update([*items[:at], (name, value), *items[at:]])


def given() -> dict[str, Any]:
    """What the sample's top layer holds every chapter to, as the read-back step reports it."""
    rows = PLAN["chapters"]["rows"]
    brief = {str(row["id"]): row for row in PLAN["brief"]["rows"]}
    return {
        "names": list(brief["source"]["names"]),
        "label": str(brief["label"]["text"]),
        "opens": str(rows[0]["label"]),
        "first": str(rows[0]["first"]),
        "closes": str(rows[-1]["label"]),
        "last": str(rows[-1]["last"]),
    }


def verdict(names: Sequence[str]) -> dict[str, Any]:
    """The first reader's verdict on the chapters just written: with several to read, it sends
    the sample's one weak chapter back; a chapter read alone passes."""
    reader = PLAN["reader"]
    back = len(names) > 1 and reader["chapter"] in names
    return {
        "verdict": "fix" if back else "pass",
        "keep": [reader["keep"]],
        "weakest": {
            name: _WEAKEST.format(line=PLAN["shots"][name]["shots"][0]["vo"])
            for name in names
            if name in PLAN["shots"]
        },
        "chapters": {reader["chapter"]: [reader["note"]]} if back else {},
        "top": [],
    }


def shots(name: str, rows: Sequence[str] = ()) -> dict[str, Any]:
    return _revised(PLAN["shots"][name], "shots", name, rows)


def _dump(section: dict[str, Any]) -> str:
    return json.dumps(section, ensure_ascii=False, indent=1)


# -- the writers ----------------------------------------------------------------------------------


def _brief(messages: Sequence[BaseMessage]) -> str:
    """What the writer was asked: its brief, wherever the harness's own lines sit around it."""
    return "\n".join(str(m.content) for m in messages if isinstance(m, HumanMessage))


def _work(brief: str) -> tuple[list[tuple[str, dict[str, Any]]], str, dict[str, Any]] | None:
    """What this brief's writer writes: each file with its section, the line it reports, and the
    JSON its report ends with. None for a brief the sample has no words for."""
    where = _WORK.search(brief)
    asked = _NOTES.search(brief)
    notes = asked.group(1) if asked else ""
    if where is None:
        return None
    folder = f"{where.group(1)}/plan"
    if "You write the brief of an episode" in brief:
        brief_, claims = (
            top("Brief", rows_in(notes, "Brief")),
            top("Claims", rows_in(notes, "Claims")),
        )
        material = _FILES.search(brief)
        source = next(row for row in brief_["rows"] if row["id"] == "source")
        if material is not None:
            source["files"] = [line[2:].strip() for line in material.group(1).splitlines()]
        idea = next(row for row in brief_["rows"] if row["id"] == "idea")
        return (
            [(f"{folder}/brief.json", brief_), (f"{folder}/claims.json", claims)],
            f"The idea: {idea['text']}",
            {"brief": brief_, "claims": claims},
        )
    if "You pick the spine of an episode" in brief:
        spine = top("Spine", rows_in(notes, "Spine"))
        picked = next(row for row in spine["rows"] if row.get("picked"))
        return (
            [(f"{folder}/spine.json", spine)],
            f"The spine is {picked['label']}: every chapter can point at the same thing.",
            {"brief": top("Brief"), "spine": spine},
        )
    if "You read back six things" in brief:
        return [], "", given()  # read back, not written: no file, no line
    if "You are the first reader" in brief:
        written = _JUST_WRITTEN.search(brief)
        names = re.findall(r"“([^”]+)”", written.group(1)) if written else []
        found = verdict(names)
        sent = ", ".join(found["chapters"]) or "nothing"
        return [(f"{folder}/reader.json", found)], f"Read as a viewer: {sent} goes back.", found
    if "You write the chapter list" in brief:
        listed = top("Chapters", rows_in(notes, "Chapters"))
        sound = top("Sound and look", rows_in(notes, "Sound and look"))
        return (
            [(f"{folder}/chapters.json", listed), (f"{folder}/sound-look.json", sound)],
            f"{len(listed['rows'])} parts: a short open and close, and the chapters between them.",
            {"chapters": listed, "sound": sound},
        )
    standing = _STANDING.search(brief)
    if standing is not None and standing.group(1) in PLAN["beats"]:
        return [], "", beats(standing.group(1))  # read back, not written: no file, no line
    chapter = _CHAPTER.search(brief)
    if chapter is None or chapter.group(2) not in PLAN["beats"]:
        return None
    what, name = chapter.groups()
    rows = rows_in(notes, name)
    if what == "beats":
        section = beats(name, rows)
        line = f"{len(section['beats'])} beats, each one a change on screen."
    else:
        section = shots(name, rows)
        line = f"{len(section['shots'])} shots, each written from its beat."
    return [(f"{folder}/{stem(name)}.{what}.json", section)], line, section


def next_step(messages: Sequence[BaseMessage]) -> AIMessage:
    """A writer's next move: write the files its brief asks for, then report them."""
    work = _work(_brief(messages))
    if work is None:
        return reply("The demo's writers only write the sample plan.")
    files, line, report = work
    if not files:
        return reply(_dump(report))
    if not any(isinstance(m, AIMessage) for m in messages):
        return tool_calls(
            *(("write_file", {"file_path": path, "content": _dump(s)}) for path, s in files),
            content=line,
        )
    return reply(f"{line}\n{_dump(report)}")
