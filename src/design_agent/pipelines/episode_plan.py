"""An episode's plan as a pipeline: each level is written from the level above it.

`skills/episode-plan/` plans a 4 to 10 minute explainer in words before any picture. Written in
one go, a plan's shots get invented beside its beats instead of from them, and its chapter list
drifts from its spine. Here the order is code, and each step's brief carries what the step before
it returned:

- `stage="brief"`: the brief and its ledger of claims, from the material (max). The team signs
  it off before anything is planned from it.
- `stage="top"`: the spine, from the brief as it stands (max), then the chapter list, the sound
  and the look, written from the picked spine (xhigh).
- `stage="chapters"`: for each chapter named, its beats from its row of the chapter list (xhigh),
  then its shots from those beats (xhigh). A chapter's shots are not started until its beats have
  come back and passed their checks; chapters run side by side, with no barrier between the two
  stages. Then a first reader goes through what was written as a viewer would (xhigh), with how
  each chapter's beats explain counted for it, and each chapter it sends back is written once
  more with its notes. Its verdict is a file in the plan folder, and a note to the lead the
  moment it reports, so a run stopped during the rewrites does not take it along.
- `stage="shots"`: for each chapter named, its shots alone, from its beats as they stand on disk
  (a beat someone edited, or a chapter whose shots never landed). The beats are read back first
  (low) and never rewritten, so the shots step is handed them the same way.
- `stage="review"`: the first reader alone, over the chapters named as they stand on disk, and
  the rewrite of each chapter it sends back. For a plan that was edited by hand, or written
  without its reader.

The words the voice says are a beat's (`says`), written by the one writer who has the material
open; a chapter's shots cut them into lines and change none. Every result is checked with
`design_agent.episode` (the rules the canvas shows): a section that does not pass goes back to
its writer once, with what is wrong. What still fails after that is in the result (`open`), for
the lead to say.

What only reading the words shows (`episode.STYLE`: a line that credits, a figure left for the
voice to read, one technique on most of a chapter's beats) goes back to the writer once like any
other fault, but it does not hold a chapter's shots back: it is said in `open`, and to the reader.

The helpers write the plan's files in `/workspace/projects/<project>/plan/`. The result lists them
in the order the lead publishes them (`publish`): a chapter's beats, then its shots (the shots
alone, from the shots stage). Helpers never publish. A step whose helper fails is re-issued once;
a chapter that still fails is named in the result (`failed`) and the others go on. A helper that
has not reported within its step's time (`WITHIN`) is stopped and counts as failed: a model call
can hang far longer than a step takes, and a chapter must not wait on it.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from design_agent import episode
from design_agent.harness.workflow import Step, StepFailed, WorkflowContext

SKILL = "/skills/episode-plan/SKILL.md"
BRIEFS = "/skills/episode-plan/briefs"
SECTIONS = "/skills/episode-plan/references/sections.md"
#: The stages: the brief; the plan's top layer; the chapters named, each in full; only their
#: shots; or only their first reader.
BRIEF, TOP, CHAPTERS, SHOTS, REVIEW = "brief", "top", "chapters", "shots", "review"
#: The brief's sections and the top layer's, as their boards name them, and the file each is
#: written to.
BRIEF_FILES: tuple[tuple[str, str, str], ...] = (
    ("brief", "Brief", "brief.json"),
    ("claims", "Claims", "claims.json"),
)
TOP_FILES: tuple[tuple[str, str, str], ...] = (
    ("spine", "Spine", "spine.json"),
    ("chapters", "Chapters", "chapters.json"),
    ("sound", "Sound and look", "sound-look.json"),
)
#: The chapters a first reader may send back in one run. More than this is a fault above the
#: chapters, which no rewrite of them mends.
SENT_BACK_MOST = 3
#: The most seconds one helper may take, by effort: about twice the longest such step has run
#: (a chapter's shots at 271 s, the brief at 419 s). Past it the helper is stopped and the step
#: is re-issued once.
WITHIN: dict[str, float] = {"low": 180.0, "xhigh": 600.0, "max": 1200.0}
#: The reader's verdict, kept in the plan folder beside what it read.
READER_FILE = "reader.json"

_SECTION: dict[str, Any] = {"type": "object", "required": ["section"]}
_LINES: dict[str, Any] = {"type": "array", "items": {"type": "string"}}
BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["brief", "claims"],
    "properties": {"brief": _SECTION, "claims": _SECTION},
}
#: What every chapter is held to from the levels above it, read back as it stands.
GIVEN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["names", "label", "opens", "first", "closes", "last"],
    "properties": {
        "names": _LINES,
        **{key: {"type": "string"} for key in ("label", "opens", "first", "closes", "last")},
    },
}
#: A first reader's verdict: what to keep, each chapter's weakest line, what each chapter must
#: fix, and what only the top layer could.
READER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["verdict", "keep", "weakest", "chapters", "top"],
    "properties": {
        "verdict": {"enum": ["pass", "fix"]},
        "keep": _LINES,
        "weakest": {"type": "object"},
        "chapters": {"type": "object"},
        "top": _LINES,
    },
}
SPINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["brief", "spine"],
    "properties": {"brief": _SECTION, "spine": _SECTION},
}
CHAPTERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["chapters", "sound"],
    "properties": {"chapters": _SECTION, "sound": _SECTION},
}
BEATS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["section", "beats"],
    "properties": {
        "section": {"enum": [episode.CHAPTER]},
        "beats": {"type": "array", "minItems": 1, "items": {"type": "object"}},
    },
}
SHOTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["section", "shots"],
    "properties": {
        "section": {"enum": [episode.SHOTS]},
        "shots": {"type": "array", "minItems": 1, "items": {"type": "object"}},
    },
}

_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


async def episode_plan(
    ctx: WorkflowContext,
    *,
    project: str,
    stage: str = BRIEF,
    material: Sequence[str] = (),
    chapters: Mapping[str, float] | None = None,
    notes: str = "",
    review: bool = True,
) -> dict[str, Any]:
    """An episode's plan in words, each level written from the one above it. `stage` "brief":
    the brief and its ledger of claims, from `material` (the paths of the post, docs or notes
    under /workspace). `stage` "top", once the brief is signed off: the spine, then the chapter
    list, the sound and the look. `stage` "chapters": every chapter in `chapters` (its name in
    the chapter list, and its length in seconds), its beats first, then its shots, written from
    those beats; then a first reader sends back what a viewer would trip on, once (`review`
    false leaves the reader out, for a part a person asked to have rewritten). `stage` "shots":
    the same chapters' shots alone, from their beats as they stand. `stage` "review": the
    first reader alone, over the same chapters as they stand. `project` is its folder
    under /workspace/projects/; `notes` is anything the writers should know beyond the brief,
    or, for a part being written again, what the team asked for and the row it is on."""
    if not _PROJECT.fullmatch(project):
        raise ValueError(f"project is a folder name under /workspace/projects/, not {project!r}")
    work = f"/workspace/projects/{project}"
    if stage == BRIEF:
        return await _brief(ctx, project, work, _material(material), notes)
    if stage == TOP:
        return await _top(ctx, project, work, notes)
    if stage in (CHAPTERS, SHOTS, REVIEW):
        return await _chapters(
            ctx, project, work, _named(chapters), notes, stage=stage, review=bool(review)
        )
    raise ValueError(
        f'stage is "{BRIEF}", "{TOP}", "{CHAPTERS}", "{SHOTS}" or "{REVIEW}", not {stage!r}'
    )


def _material(material: Sequence[str]) -> list[str]:
    """The files a brief is written from, as paths on the thread's computer."""
    paths = [material] if isinstance(material, str) else list(material or ())
    if not paths or not all(isinstance(p, str) and p.startswith("/workspace/") for p in paths):
        raise ValueError(
            "material is the paths of what the episode is made from, under /workspace: "
            '["/workspace/attachments/post.md"]'
        )
    return paths


def _named(chapters: Mapping[str, float] | None) -> dict[str, float]:
    """The chapters to write, by name, with each one's length; every name has its own file."""
    if not isinstance(chapters, Mapping) or not chapters:
        raise ValueError(
            'chapters is an object of each chapter to write and its seconds: {"Chapter 1": 55}'
        )
    lengths: dict[str, float] = {}
    for name, length in chapters.items():
        if isinstance(length, bool) or not isinstance(length, int | float) or length <= 0:
            raise ValueError(f"{name!r} needs its length in seconds, as the chapter list has it")
        lengths[str(name)] = float(length)
    stems = [_stem(name) for name in lengths]
    if "" in stems or len(set(stems)) != len(stems):
        raise ValueError("each chapter needs its own name, with a letter or a digit in it")
    return lengths


def _stem(name: str) -> str:
    return episode.stem(name)


# -- the brief -------------------------------------------------------------------------------------


async def _brief(
    ctx: WorkflowContext, project: str, work: str, material: Sequence[str], notes: str
) -> dict[str, Any]:
    ctx.phase("brief")
    value, still = await _checked(
        ctx,
        _brief_brief(work, material, notes),
        effort="max",
        label="brief",
        schema=BRIEF_SCHEMA,
        problems=_brief_faults,
    )
    idea = next(
        (
            str(row.get("text") or "")
            for row in value["brief"].get("rows") or []
            if isinstance(row, dict) and row.get("id") == "idea"
        ),
        "",
    )
    return {
        "project": project,
        "stage": BRIEF,
        "publish": [{"name": name, "path": f"{work}/plan/{file}"} for _, name, file in BRIEF_FILES],
        "idea": idea,
        "open": still,
        "next": (
            "Publish these two sections as the brief's board (canvas_publish_board, kind "
            '"brief"), say the idea in a line, and wait for the brief\'s sign-off: nothing is '
            "planned before it."
        ),
    }


def _brief_faults(value: Mapping[str, Any]) -> list[str]:
    names = {key: name for key, name, _ in BRIEF_FILES}
    found = [
        f"{names[key]}: {fault}" for key in names for fault in episode.faults(value.get(key) or {})
    ]
    return found or [
        f"Brief: {fault}" for fault in episode.brief_faults(value["brief"], value["claims"])
    ]


# -- the top layer ---------------------------------------------------------------------------------


async def _top(ctx: WorkflowContext, project: str, work: str, notes: str) -> dict[str, Any]:
    ctx.phase("spine")
    first, open_first = await _checked(
        ctx,
        _spine_brief(work, notes),
        effort="max",
        label="spine",
        schema=SPINE_SCHEMA,
        problems=_spine_faults,
    )
    ctx.phase("chapter list")
    second, open_second = await _checked(
        ctx,
        _chapters_brief(work, first, notes),
        effort="xhigh",
        label="chapter list",
        schema=CHAPTERS_SCHEMA,
        problems=lambda value: _list_faults(first, value),
    )
    rows = second["chapters"].get("rows") or []
    return {
        "project": project,
        "stage": TOP,
        "publish": [{"name": name, "path": f"{work}/plan/{file}"} for _, name, file in TOP_FILES],
        "chapters": {
            str(row.get("label")): episode.seconds_of(row) for row in rows if isinstance(row, dict)
        },
        "open": [*open_first, *open_second],
        "next": (
            "Publish these three sections as the plan's board (canvas_publish_board, kind "
            '"plan"), say what the spine is and the film\'s first and last line, and wait for '
            "the top layer's sign-off: no chapter is written before it."
        ),
    }


def _spine_faults(value: Mapping[str, Any]) -> list[str]:
    if episode.faults(value.get("brief") or {}):
        return [
            "Brief: report brief.json whole, as it stands. The plan is written from the brief "
            "the team signed off; if there is none in the plan folder, say so and stop"
        ]
    return _top_faults(value, ("spine",))


def _top_faults(value: Mapping[str, Any], keys: Sequence[str]) -> list[str]:
    names = {key: name for key, name, _ in TOP_FILES}
    return [
        f"{names[key]}: {fault}" for key in keys for fault in episode.faults(value.get(key) or {})
    ]


def _list_faults(first: Mapping[str, Any], second: Mapping[str, Any]) -> list[str]:
    """What is wrong with the chapter list and the sound, and with the list's clock against the
    brief's length."""
    found = _top_faults(second, ("chapters", "sound"))
    if found:
        return found
    sections = {
        "Brief": first["brief"],
        "Spine": first["spine"],
        "Chapters": second["chapters"],
        "Sound and look": second["sound"],
    }
    clock = next(row for row in episode.checks(sections) if row["id"] == "clock")
    found = [f"Chapters: {clock['text']}"] if clock["state"] == "fail" else []
    return found + [
        f"Chapters: {flag}" for flags in episode.top_flags(sections).values() for flag in flags
    ]


# -- the chapters ----------------------------------------------------------------------------------


async def _chapters(
    ctx: WorkflowContext,
    project: str,
    work: str,
    lengths: Mapping[str, float],
    notes: str,
    *,
    stage: str,
    review: bool,
) -> dict[str, Any]:
    ctx.phase(stage)
    # What the levels above hold every chapter to, as they stand on disk: the checks that read
    # a line (who it credits, what it calls made up, the film's first and last words) need them.
    standing = await _step(
        ctx, _given_brief(work), effort="low", label="the top as it stands", schema=GIVEN_SCHEMA
    )
    held = episode.Given(
        names=tuple(str(name) for name in standing.value["names"]),
        **{key: str(standing.value[key]) for key in ("label", "opens", "first", "closes", "last")},
    )

    def beat_faults(name: str) -> Callable[[Any], list[str]]:
        return lambda found: _beat_faults(found, lengths[name], held, name)

    def beats_item(name: str, value: Any, still: list[str], **more: Any) -> dict[str, Any]:
        # What only reading the words shows is said (`open`) and does not hold the shots back;
        # beats that do not add up do, because shots written from them are written twice.
        blocked = bool(_beat_faults(value, lengths[name], held, name, style=False))
        return {"name": name, "beats": value, "open": still, "blocked": blocked, **more}

    async def stood(name: str) -> Any:
        step = await _step(
            ctx,
            _standing_brief(work, name),
            effort="low",
            label=f"{name}: beats as they stand",
            schema=BEATS_SCHEMA,
        )
        return step.value

    async def beats(name: str) -> dict[str, Any]:
        if stage == SHOTS:
            # The beats stand: they are read back, never rewritten, and what does not pass in
            # them is said.
            value = await stood(name)
            return beats_item(name, value, beat_faults(name)(value))
        value, still = await _checked(
            ctx,
            _beats_brief(work, name, lengths[name], notes),
            effort="xhigh",
            label=f"{name}: beats",
            schema=BEATS_SCHEMA,
            problems=beat_faults(name),
        )
        return beats_item(name, value, still)

    async def shots(item: dict[str, Any], *, said: str = notes, again: str = "") -> dict[str, Any]:
        name = item["name"]
        if item["blocked"]:
            return {**item, "shots": None}
        # What its beats' words still show is their writer's to mend, and already said: the
        # shots are held to what the shots add.
        known = list(item["open"])
        try:
            value, still = await _checked(
                ctx,
                _shots_brief(work, name, lengths[name], item["beats"], said),
                effort="xhigh",
                label=f"{name}: shots{again}",
                schema=SHOTS_SCHEMA,
                problems=lambda found: [
                    line
                    for line in _shot_faults(item["beats"], found, lengths[name], held, name)
                    if line not in known
                ],
            )
        except StepFailed:
            return {**item, "shots": None}
        return {**item, "shots": value, "open": [*known, *still]}

    # The reader alone reads what stands: nothing is written before it, and only what it sends
    # back is written after.
    done = [] if stage == REVIEW else await ctx.pipeline(list(lengths), beats, shots)
    written = {item["name"]: item for item in done if item is not None}
    failed = [name for name, item in zip(lengths, done, strict=False) if item is None]

    reader: dict[str, Any] | None = None
    whole = [name for name, item in written.items() if item["shots"] is not None]
    if stage == REVIEW:
        whole = list(lengths)
    if whole and (stage == REVIEW or (review and stage == CHAPTERS)):
        ctx.phase("reader")
        if stage == REVIEW:
            # Nothing was written in this run, so the beats are read back as they stand: the
            # reader is handed how they explain, counted, and what the checks find in them.
            found = await ctx.parallel([(lambda name=name: stood(name)) for name in whole])
            read = {name: value for name, value in zip(whole, found, strict=True) if value}
            flagged = {name: beat_faults(name)(value) for name, value in read.items()}
        else:
            read = {name: written[name]["beats"] for name in whole}
            flagged = {name: written[name]["open"] for name in whole}
        verdict = await _read(ctx, work, whole, notes, _counted(read, flagged))
        asked = {
            name: found for name, found in verdict["chapters"].items() if name in whole and found
        }
        back = dict(list(asked.items())[:SENT_BACK_MOST])
        if verdict["reported"]:
            # Said the moment it is known: a run stopped during the rewrites still told the
            # lead what its reader found.
            ctx.note(_reader_note(work, verdict, back))

        async def beats_again(name: str) -> dict[str, Any]:
            said = _reader_notes(notes, back[name], verdict["keep"])
            value, still = await _checked(
                ctx,
                _beats_brief(work, name, lengths[name], said),
                effort="xhigh",
                label=f"{name}: beats, again",
                schema=BEATS_SCHEMA,
                problems=beat_faults(name),
            )
            return beats_item(name, value, still, said=said)

        async def shots_again(item: dict[str, Any]) -> dict[str, Any]:
            return await shots(item, said=item["said"], again=", again")

        if back:
            ctx.phase("chapters, again")
            for name, item in zip(
                back, await ctx.pipeline(list(back), beats_again, shots_again), strict=True
            ):
                if item is None:
                    failed.append(name)
                    del written[name]
                else:
                    written[name] = item
        reader = {
            "verdict": verdict["verdict"],
            "sent_back": dict(back),
            "left": {
                name: found
                for name, found in verdict["chapters"].items()
                if name not in back and found
            },
            "keep": verdict["keep"],
            "weakest": verdict["weakest"],
            "top": verdict["top"],
        }
        if verdict["reported"]:
            reader["file"] = f"{work}/plan/{READER_FILE}"

    publish: list[dict[str, str]] = []
    for item in written.values():
        stem = _stem(item["name"])
        if stage != SHOTS:
            publish.append({"name": item["name"], "path": f"{work}/plan/{stem}.beats.json"})
        if item["shots"] is not None:
            publish.append({"name": item["name"], "path": f"{work}/plan/{stem}.shots.json"})
    then = (
        "Publish these on the plan's board in this order, in one call (canvas_publish_board "
        "with `replaces`): a chapter's beats, then its shots, which go under them. Say what "
        "is still open, in a line. A chapter in `failed` is run again with this stage; one in "
        f'`bare` (beats, and no shots) with stage "{SHOTS}", unless `open` says its beats do '
        "not pass."
    )
    result: dict[str, Any] = {
        "project": project,
        "stage": stage,
        "publish": publish,
        "open": {name: item["open"] for name, item in written.items() if item["open"]},
        "bare": [name for name, item in written.items() if item["shots"] is None],
        "failed": failed,
        "next": then,
    }
    if reader is not None:
        result["reader"] = reader
        result["next"] = (
            f"{then} `reader` is what a first reader made of it: say in a line which chapters "
            "it sent back (`sent_back`, already written again) and what it left for the team "
            "(`left`, `top`). With nothing in `publish`, it sent nothing back: say so, and "
            "publish nothing. A chapter in `failed` that the reader sent back is run again "
            'with its lines in `sent_back` as `notes`, and "review": false.'
        )
    return result


async def _read(
    ctx: WorkflowContext, work: str, names: Sequence[str], notes: str, counted: str
) -> dict[str, Any]:
    """A first reader's verdict on the chapters just written. One that fails to report is no
    verdict (`reported` false): the chapters stand as written, and the team is their first
    reader. `counted` is what code counted for it."""
    try:
        step = await _step(
            ctx,
            _reader_brief(work, names, notes, counted),
            effort="xhigh",
            label="reader",
            schema=READER_SCHEMA,
        )
    except StepFailed:
        return {
            "verdict": "pass",
            "keep": [],
            "weakest": {},
            "chapters": {},
            "top": ["The reader did not report."],
            "reported": False,
        }
    # A reader may name a chapter with its title after it ("Chapter 2 · Follow the leads"): it is
    # the chapter whose name that starts with.
    called = {_stem(name): name for name in names}

    def named(key: str) -> str:
        stem = _stem(key)
        return next(
            (name for at, name in called.items() if stem == at or stem.startswith(f"{at}-")), key
        )

    return {
        **step.value,
        "weakest": {named(str(key)): str(line) for key, line in step.value["weakest"].items()},
        "chapters": {
            named(str(key)): [str(line) for line in found if str(line).strip()]
            for key, found in step.value["chapters"].items()
            if isinstance(found, list)
        },
        "reported": True,
    }


def _counted(read: Mapping[str, Mapping[str, Any]], flagged: Mapping[str, Sequence[str]]) -> str:
    """What code counted for the reader: how each chapter's beats explain, and what the checks
    still find in the chapters it reads. Empty when there is nothing to count."""
    film: Counter[str] = Counter()
    lines: list[str] = []
    for name, beats in read.items():
        found = episode.ways(beats)
        film.update(found)
        if found:
            lines.append(f"- {name}: {', '.join(f'{way} {n}' for way, n in found.items())}")
    if not lines:
        return ""
    total = ", ".join(f"{way} {n}" for way, n in film.most_common())
    none = (
        ""
        if any(film[way] for way in episode.CONCRETE)
        else f" None by {' or '.join(episode.CONCRETE)}."
    )
    said = "\n".join([*lines, f"- The film: {total}.{none}"])
    still = "\n".join(f"- {name}: {flag}" for name, flags in flagged.items() for flag in flags)
    return f"""
HOW THE BEATS EXPLAIN (counted from each beat's `technique`)
{said}
""" + (
        f"""
WHAT THE CHECKS STILL FLAG (the team is told; weigh it, and spend no note repeating it)
{still}
"""
        if still
        else ""
    )


def _reader_note(work: str, verdict: Mapping[str, Any], back: Mapping[str, Any]) -> str:
    """What the lead is told the moment the reader reports, whatever becomes of the run."""
    left = [name for name, found in verdict["chapters"].items() if name not in back and found]
    sent = f"sent back {', '.join(back)}, now being written again" if back else "sent nothing back"
    more = f" It left notes on {', '.join(left)} for the team." if left else ""
    return (
        f"The first reader {sent}.{more} Its verdict, with each chapter's weakest line, is in "
        f"{work}/plan/{READER_FILE}."
    )


def _reader_notes(notes: str, found: Sequence[str], keep: Sequence[str]) -> str:
    """What a chapter's writers are told when a first reader sends it back."""
    asked = "\n".join(f"- {line}" for line in found)
    kept = "\n".join(f"- {line}" for line in keep)
    said = f"A first reader went through the film as a viewer would and sent this chapter back. Fix these, and only these:\n{asked}"
    if kept:
        said += f"\nKeep what works; the reader named it:\n{kept}"
    return f"{notes.strip()}\n\n{said}" if notes.strip() else said


def _beat_faults(
    section: Mapping[str, Any],
    length: float,
    held: episode.Given,
    name: str,
    *,
    style: bool = True,
) -> list[str]:
    found = episode.faults(section)
    return found or episode.chapter_faults(
        section, length, shots=False, held=held, part=name, style=style
    )


def _shot_faults(
    beats: Mapping[str, Any],
    shots: Mapping[str, Any],
    length: float,
    held: episode.Given,
    name: str,
) -> list[str]:
    found = episode.faults(shots)
    if found:
        return found
    try:
        chapter = episode.with_shots(beats, shots)
    except ValueError as error:
        return [str(error)]
    return episode.chapter_faults(chapter, length, held=held, part=name)


# -- steps -----------------------------------------------------------------------------------------


async def _checked(
    ctx: WorkflowContext,
    brief: str,
    *,
    effort: str,
    label: str,
    schema: Mapping[str, Any],
    problems: Callable[[Any], list[str]],
) -> tuple[Any, list[str]]:
    """One step whose result is checked: sent back once with what is wrong. Returns the result
    that stands and what is still wrong with it."""
    step = await _step(ctx, brief, effort=effort, label=label, schema=schema)
    found = problems(step.value)
    if not found:
        return step.value, []
    again = await _step(
        ctx, _fix(brief, found, step.value), effort=effort, label=f"{label}, fix", schema=schema
    )
    return again.value, problems(again.value)


async def _step(
    ctx: WorkflowContext, brief: str, *, effort: str, label: str, schema: Mapping[str, Any]
) -> Step:
    """One step; a helper that fails, goes quiet past its time (`WITHIN`), or whose report is
    not the JSON asked for, is re-issued once. The second helper is told to look at what the
    first left before it writes: the harness's own retry assumes the work is on disk, and a first
    helper that misread its brief, or hung before it wrote, leaves nothing there."""
    within = WITHIN.get(effort)
    try:
        return await ctx.agent(
            brief, effort=effort, label=label, schema=schema, attempts=1, within=within
        )
    except StepFailed as failure:
        return await ctx.agent(
            _resumed(brief, failure.reason),
            effort=effort,
            label=f"{label}, resumed",
            schema=schema,
            attempts=1,
            within=within,
        )


def _resumed(brief: str, reason: str) -> str:
    return f"""A helper before you was given this task and did not finish it ({reason}). Look in the plan folder first: keep what it wrote that is sound, and write whatever the brief asks for that is not there. It may have written nothing. Everything in the original brief below still applies.

--- original brief ---
{brief}"""


def _fix(brief: str, found: Sequence[str], value: Any) -> str:
    wrong = "\n".join(f"- {line}" for line in found)
    return f"""{brief}

--- From the pipeline, about what you wrote ---
It does not pass yet:
{wrong}
Change only what these lines name, in the files you wrote, and keep every other word as it is. Then report again in the same form.

What you reported:
{_json(value)}"""


def _json(value: Any) -> str:
    return json.dumps(value, indent=1, ensure_ascii=False)


def _notes(notes: str) -> str:
    if not notes.strip():
        return ""
    return f"""
NOTES FROM THE LEAD
{notes.strip()}
If the files you are asked for are already in the plan folder, this is a second pass over them: change only what these notes ask for and what has to follow from it, and keep every other word as it is, because the team has read them. If they are not there, this is the first pass: write them fresh, and take the notes as guidance.
"""


# -- the briefs: roles, pointers to the skill's briefs, and the values to fill in ------------------


def _brief_brief(work: str, material: Sequence[str], notes: str) -> str:
    files = "\n".join(f"- {path}" for path in material)
    return f"""ROLE
You write the brief of an episode in {work}/: its one idea, who it is for, how long it runs, and the ledger of what it may state. An episode is a 4 to 10 minute technical explainer led by a voiceover ({SKILL}). Nothing of its plan exists yet. The team signs your brief off before anything is planned, and every later writer takes its facts from your ledger.

BRIEF
Your brief is {BRIEFS}/brief.md. Read it and follow it. The sections' form is in {SECTIONS}.

THE MATERIAL (read every file whole before you write a word)
{files}
{_notes(notes)}
DELIVERABLES (in {work}/plan/)
- brief.json and claims.json.

REPORT
The idea in a line, ending with one JSON object:
{{"brief": <brief.json, whole>, "claims": <claims.json, whole>}}"""


def _spine_brief(work: str, notes: str) -> str:
    return f"""ROLE
You pick the spine of an episode in {work}/. An episode is a 4 to 10 minute technical explainer led by a voiceover ({SKILL}). Its brief is signed off: the idea, who it is for, its length and the ledger of what it may state. Everything after you (the chapter list, each chapter's beats, each beat's shots) is written from what you pick.

BRIEF
Your brief is {BRIEFS}/spine.md. Read it and follow it. The sections' form is in {SECTIONS}.

READ FIRST
- {work}/plan/brief.json and {work}/plan/claims.json: they stand as the team signed them off. Change neither.
- The material the brief's `source` row names.
{_notes(notes)}
DELIVERABLES (in {work}/plan/)
- spine.json.

REPORT
The spine you picked and why, in a line or two, ending with one JSON object:
{{"brief": <brief.json as it stands, whole, word for word>, "spine": <spine.json, whole>}}"""


def _chapters_brief(work: str, top: Mapping[str, Any], notes: str) -> str:
    return f"""ROLE
You write the chapter list of an episode in {work}/, and its sound and look. The brief is signed off and the spine is picked; each chapter you list is one stop on that spine. Each chapter's beats are written from its row of your list and the material, by a different person per chapter, all at the same time: a row says what its chapter must do and where its share of the material ends. You also decide what no one of them can: the film's first spoken line and its last, and the turn, the one chapter the film pivots on.

BRIEF
Your brief is {BRIEFS}/chapters.md. Read it and follow it. The sections' form is in {SECTIONS}.

THE BRIEF AND THE SPINE (written before you; build on them as they are)
{_json(top)}

READ AS WELL
- {work}/plan/claims.json, and the material the brief's `source` row names.
{_notes(notes)}
DELIVERABLES (in {work}/plan/)
- chapters.json and sound-look.json.

REPORT
The chapters in a line, ending with one JSON object:
{{"chapters": <chapters.json, whole>, "sound": <sound-look.json, whole>}}"""


def _given_brief(work: str) -> str:
    return f"""ROLE
You read back six things from the plan in {work}/plan/, exactly as they stand, so each chapter can be checked against them. You change nothing and write nothing.

DO
Read {work}/plan/brief.json and {work}/plan/chapters.json.

REPORT
One JSON object, every value word for word:
{{"names": <the `names` of the brief's `source` row, as a list>, "label": <the `text` of the brief's `label` row, or "" when it has none>, "opens": <the `label` of the first row of chapters.json>, "first": <that row's `first`>, "closes": <the `label` of its last row>, "last": <that row's `last`>}}"""


def _beats_brief(work: str, name: str, length: float, notes: str) -> str:
    return f"""ROLE
You write the beats of “{name}” ({_seconds(length)} s) of the episode planned in {work}/plan/. The brief and the top layer are signed off: the idea, the ledger of claims, the spine, the chapter list, the sound and the look. Other chapters are written side by side with yours, from the same list. You are the one writer of this chapter with the material open, so the words the voice says are yours: each beat carries the passage it says. Its shots are written from your beats next and cut that passage into lines without changing a word, so a beat that leaves something open leaves it open on screen.

BRIEF
Your brief is {BRIEFS}/beats.md. Read it and follow it. The sections' form is in {SECTIONS}.

READ FIRST
- In {work}/plan/: brief.json, claims.json, spine.json, chapters.json (the row called “{name}” is yours; read the rows before and after it) and sound-look.json.
- The material the brief's `source` row names: your facts come from the ledger and from there, inside what your row covers.
{_notes(notes)}
DELIVERABLES (in {work}/plan/)
- {_stem(name)}.beats.json: the beats of “{name}”, adding up to {_seconds(length)} s, with no shots in it.

REPORT
The chapter in a line, ending with one JSON object: {_stem(name)}.beats.json, whole."""


def _standing_brief(work: str, name: str) -> str:
    return f"""ROLE
You read back the beats of “{name}” of the episode planned in {work}/plan/, exactly as they stand, so its shots can be written from them. You change nothing and write nothing.

DO
Read {work}/plan/{_stem(name)}.beats.json.

REPORT
One JSON object: that file, whole, word for word."""


def _shots_brief(work: str, name: str, length: float, beats: Mapping[str, Any], notes: str) -> str:
    return f"""ROLE
You write the shots of “{name}” ({_seconds(length)} s) of the episode planned in {work}/plan/. Its beats are written and checked, and they are below. Write every shot from its beat: what it shows performs the beat's change, its lines are the beat's passage (`says`) cut where the picture changes, word for word, and its last shot ends on the beat's result. You write no line of your own. A shot that needs something its beat does not say means the beat is wrong: say so in your report, and write the shot the beat asks for.

BRIEF
Your brief is {BRIEFS}/shots.md. Read it and follow it. The sections' form is in {SECTIONS}.

THE BEATS OF “{name}” (written before you; do not change them)
{_json(beats)}

READ AS WELL (in {work}/plan/)
- brief.json, spine.json, chapters.json (the row called “{name}”) and sound-look.json.
{_notes(notes)}
DELIVERABLES (in {work}/plan/)
- {_stem(name)}.shots.json: every shot of “{name}”, each under its beat, the shots of a beat adding up to that beat's seconds.

REPORT
The chapter's shots in a line, ending with one JSON object: {_stem(name)}.shots.json, whole."""


def _reader_brief(work: str, names: Sequence[str], notes: str, counted: str = "") -> str:
    listed = ", ".join(f"“{name}”" for name in names)
    asked = (
        f"""
WHAT THE TEAM ASKED FOR (a note of theirs is settled: send nothing back that undoes it)
{notes.strip()}
"""
        if notes.strip()
        else ""
    )
    return f"""ROLE
You are the first reader of the episode planned in {work}/plan/, before the team reads it. You judge; you do not fix, and the one file you write is your verdict. These chapters were written, each by a different person at the same time: {listed}. You read the film as its viewer hears it, start to end, and say which of them must be written again.

BRIEF
Your brief is {BRIEFS}/reader.md. Read it and follow it.

READ
- In {work}/plan/: brief.json, claims.json, spine.json, chapters.json and sound-look.json, then every chapter's beats and shots that are there (<chapter>.beats.json, <chapter>.shots.json), in the order of the chapter list.
{asked}{counted}
DELIVERABLE (in {work}/plan/)
- {READER_FILE}: your verdict, the same JSON object you report. Write no other file.

REPORT
Your verdict in a line or two, ending with one JSON object:
{{"verdict": "pass" or "fix", "keep": [<what the next pass must protect, three lines at most>], "weakest": {{"<each chapter's name, of those listed above>": "<its weakest line, quoted, and what the viewer loses there>"}}, "chapters": {{"<the name of a chapter to write again>": [<what it must fix, each a line its writer can act on, three at most>]}}, "top": [<what only the brief or the chapter list could mend, for the team>]}}"""


def _seconds(length: float) -> str:
    return str(int(length)) if float(length).is_integer() else f"{length:.1f}"
