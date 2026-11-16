"""An episode's plan as three hands' work, kept apart.

  the plan     the writer's words and intent. Code never rewrites it.
  the labels   the classifier's readings, each tied to the words it was read from, and a
               person's picks of who has the frame.
  the full plan  what code derives from the two: every time, the cue clock, the marks.

`merged` returns the plan with the labels laid over it. A label whose words have changed since
it was read is dropped, so an edited line is unlabelled until it is classified again.
"""

from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Iterable, Iterator
from typing import Any

Row = dict[str, Any]

CHAPTER_KEYS = ("type", "part", "p", "reads", "one_question", "episode", "by")
BEAT_KEYS = ("subtype", "type", "p", "reads", "by")
FRAME_KEYS = (
    "presence",
    "layout",
    "options",
    "presence_p",
    "override",
    "line_only",
    "by",
    "picture",
    "picture_p",
    "component",
    "component_sig",
    "arrangement",
    "relation",
    "transition",
)
#: What a person may pick for the line that brings a picture in, kept beside the labels and
#: never written over them: the plan's own reading stays, so taking a pick back restores it.
PICKED_KEYS = ("picture", "transition")
MATERIAL_KEYS = ("kind", "p")
OBJECT_KEYS = ("type", "p")
CUE_KEYS = ("move", "p")
BRIEF_KEYS = ("route", "route_p", "hook", "landing")


def digest(*parts: Any) -> str:
    text = "␟".join(re.sub(r"\s+", " ", str(p or "")).strip() for p in parts)
    return hashlib.sha1(text.encode("utf8"), usedforsecurity=False).hexdigest()[:12]


def chapter_hash(ch: Row) -> str:
    return digest(ch.get("question"), *[b.get("says") for b in ch.get("beats", [])])


def beat_hash(b: Row) -> str:
    return digest(b.get("says"))


def frame_hash(f: Row, b: Row | None = None) -> str:
    return digest(f.get("vo"), f.get("shows"), (b or {}).get("subtype"), f.get("wants"))


def design_hash(f: Row) -> str:
    objects = [f"{o.get('id')}={o.get('what')}" for o in f.get("objects", [])]
    cues = [f"{c.get('at')}>{c.get('object')}>{c.get('does')}" for c in f.get("cues", [])]
    return digest(
        f.get("vo"),
        f.get("shows"),
        f.get("presence"),
        "hold" if f.get("hold") else "",
        *objects,
        *cues,
    )


def take(src: Row, keys: Iterable[str]) -> Row:
    return {k: src[k] for k in keys if k in src}


def merged(plan: Row, labels: Row | None = None) -> Row:
    """The writer's plan with the labels laid over it: a copy, so the plan stays the writer's."""
    plan = copy.deepcopy(plan)
    labels = labels or {}
    plan["_overrides"] = copy.deepcopy(labels.get("overrides", {}))
    brief = plan.setdefault("brief", {})
    if plan["_overrides"].get("presenter") == "off":
        brief["presenter"] = "off"
        brief.setdefault("theme_before", brief.get("theme"))
        brief["theme"] = "voice-only"
    brief.update(labels.get("brief", {}))
    for m in plan.get("material", []):
        lab = labels.get("material", {}).get(m.get("id"))
        if lab and lab.get("h") == digest(m.get("text")):
            m.update(take(lab, MATERIAL_KEYS))
    for ch in plan.get("chapters", []):
        lab = labels.get("chapters", {}).get(ch.get("id"))
        if lab and lab.get("h") == chapter_hash(ch):
            ch.update(take(lab, CHAPTER_KEYS))
        for b in ch.get("beats", []):
            lab = labels.get("beats", {}).get(b.get("id"))
            if lab and lab.get("h") == beat_hash(b):
                b.update(take(lab, BEAT_KEYS))
            if not b.get("frames"):
                b["frames"] = [{"id": b["id"] + ".f1"}]
            for i, f in enumerate(b["frames"]):
                f.setdefault("id", f"{b['id']}.f{i + 1}")
                if "vo" not in f and len(b["frames"]) == 1:
                    f["vo"] = b.get("says", "")
                if len(b["frames"]) == 1 and b.get("by_person") and "by_person" not in f:
                    f["by_person"] = b["by_person"]  # the beat's one line is the person's words
                _label_frame(f, b, labels)
                pick = plan["_overrides"].get("frames", {}).get(f["id"], {})
                picked = {k: pick[k] for k in PICKED_KEYS if pick.get(k)}
                if picked:
                    f["picked"] = picked
    inherit_holds(plan)
    return plan


def beat_of(plan: Row, frame_id: str) -> tuple[Row, Row, Row | None] | None:
    """The chapter, the beat and (where the writer wrote one) the frame a frame id names, in
    the writer's own plan."""
    for ch in plan.get("chapters", []):
        for b in ch.get("beats", []):
            frames = b.get("frames") or []
            if not frames and frame_id == f"{b.get('id')}.f1":
                return ch, b, None
            for i, f in enumerate(frames):
                if str(f.get("id") or f"{b.get('id')}.f{i + 1}") == frame_id:
                    return ch, b, f
    return None


def reword(plan: Row, frame_id: str, text: str, *, at: float) -> str:
    """Put a person's words on one line of the plan, in place, and return the words they
    replace. The line keeps what it was drawn from under `by_person` (the writer's words, and
    the word each cue landed on), so a change of words alone never sends its picture back."""
    found = beat_of(plan, frame_id)
    if found is None:
        raise KeyError(frame_id)
    _ch, b, f = found
    frames = b.get("frames") or []
    alone = len(frames) <= 1
    holder = b if alone or f is None else f
    old = str(b.get("says", "")) if alone or f is None else str(f.get("vo", ""))
    mark = dict(holder.get("by_person") or {})
    mark.setdefault("was", old)
    mark.setdefault("cues", [str(c.get("at", "")) for c in (f or {}).get("cues", [])])
    mark["at"] = at
    holder["by_person"] = mark
    if alone or f is None:
        b["says"] = text
        if f is not None and "vo" in f:
            f["vo"] = text
    else:
        f["vo"] = text
        b["says"] = " ".join(str(x.get("vo", "")).strip() for x in frames).strip()
    return old


def _spell_out(b: Row) -> list[Row]:
    """A beat of several lines, its ids written out before a line joins it or leaves it, so
    the lines after that one keep theirs. (Each of its lines already has its own words.)"""
    frames: list[Row] = b["frames"]
    for i, f in enumerate(frames):
        f.setdefault("id", f"{b['id']}.f{i + 1}")
    return frames


def _ids(plan: Row) -> set[str]:
    """Every chapter, beat and line id the plan uses."""
    out: set[str] = set()
    for ch in plan.get("chapters", []):
        out.add(str(ch.get("id")))
        for b in ch.get("beats", []):
            out.add(str(b.get("id")))
            frames = b.get("frames") or [{}]
            out.update(str(f.get("id") or f"{b.get('id')}.f{i + 1}") for i, f in enumerate(frames))
    return out


def _next_id(prefix: str, taken: set[str]) -> str:
    """An id nothing has used, numbered on from the highest after `prefix`."""
    pattern = re.compile(re.escape(prefix) + r"(\d+)")
    numbers = [int(m.group(1)) for t in taken if (m := pattern.fullmatch(t))]
    n = max(numbers, default=0) + 1
    while f"{prefix}{n}" in taken or f"{prefix}{n}.f1" in taken:
        n += 1
    return f"{prefix}{n}"


def add_line(plan: Row, after: str, words: str, *, at: float, hold: bool = False) -> str:
    """Put a person's new line into the plan and return its id. It goes after the line
    `after`, or first in the chapter when `after` names one. After a beat's last line it is a
    beat of its own; inside a beat it joins that beat, so the beat's words stay in the order
    they are said. With `hold` it is said over the picture before it. It is marked
    `by_person`, with no words of the writer's to go back to."""
    mark = {"was": "", "cues": [], "at": at}
    line: Row = {"objects": [], "cues": [], **({"hold": True} if hold else {})}
    taken = _ids(plan)
    chapter = next((ch for ch in plan.get("chapters", []) if ch.get("id") == after), None)
    place = 0
    if chapter is None:
        found = beat_of(plan, after)
        if found is None:
            raise KeyError(after)
        chapter, b, _f = found
        frames = b.get("frames") or []
        if len(frames) > 1 and str(frames[-1].get("id") or f"{b['id']}.f{len(frames)}") != after:
            frames = _spell_out(b)
            fid = _next_id(f"{b['id']}.f", taken)
            i = next(k for k, x in enumerate(frames) if x["id"] == after)
            frames.insert(i + 1, {"id": fid, "vo": words, **line, "by_person": mark})
            b["says"] = " ".join(str(x.get("vo", "")).strip() for x in frames).strip()
            return fid
        place = next(k for k, x in enumerate(chapter["beats"]) if x is b) + 1
    beats = chapter.setdefault("beats", [])
    bid = _next_id(f"{chapter['id']}.b", taken)
    beats.insert(
        place,
        {"id": bid, "says": words, "frames": [{"id": f"{bid}.f1", **line}], "by_person": mark},
    )
    return f"{bid}.f1"


def cut_line(plan: Row, frame_id: str) -> str:
    """Take one line out of the plan and return its words. A beat left with no line goes too."""
    found = beat_of(plan, frame_id)
    if found is None:
        raise KeyError(frame_id)
    chapter, b, _f = found
    if len(b.get("frames") or []) <= 1:
        chapter["beats"] = [x for x in chapter["beats"] if x is not b]
        return str(b.get("says", ""))
    frames = _spell_out(b)
    gone = next(x for x in frames if x["id"] == frame_id)
    b["frames"] = [x for x in frames if x is not gone]
    b["says"] = " ".join(str(x.get("vo", "")).strip() for x in b["frames"]).strip()
    return str(gone.get("vo", ""))


def _designed_as(f: Row) -> Row:
    """What of a frame is designed: whether it holds, what it shows, its objects and what its
    steps do. Not its words."""
    return {
        "hold": bool(f.get("hold")) and not f.get("_auto_hold"),
        "shows": f.get("shows") or "",
        "objects": [(o.get("id"), o.get("what")) for o in f.get("objects", [])],
        "cues": [(c.get("object"), c.get("does")) for c in f.get("cues", [])],
    }


def carried(labels: Row, before: Row, after: Row, *, frames_only: bool = False) -> Row:
    """The labels of `before`, tied again to `after`: the same plan with some words changed.

    A person who rewords a line keeps what the line does, so nothing is read again: who has
    the frame stays, and so does its picture. With `frames_only` (a change the writer made at a
    person's request) the same holds for every line the writer did not redesign: its frame
    stays whose it was, however the new words would read, while what its chapter and beat do
    is read again, and so is a line that was given, or lost, a picture."""
    was = merged(before, labels)
    now = merged(after, labels)
    old_chapters = {ch["id"]: ch for ch in was.get("chapters", [])}
    old_beats = {b["id"]: b for _, b in beats_of(was)}
    old_frames = {f["id"]: f for _, _, f in frames_of(was)}
    for ch in now.get("chapters", []):
        had = old_chapters.get(ch["id"])
        if not frames_only and had is not None and "type" not in ch and "type" in had:
            ch.update(take(had, CHAPTER_KEYS))
        for b in ch.get("beats", []):
            had = old_beats.get(b["id"])
            if not frames_only and had is not None and "subtype" not in b and "subtype" in had:
                b.update(take(had, BEAT_KEYS))
            for f in b.get("frames", []):
                had = old_frames.get(f["id"])
                if had is None:
                    continue
                if frames_only and _designed_as(had) != _designed_as(f):
                    continue  # the writer redesigned it: it is read as a new line is
                if "presence" not in f and "presence" in had:
                    f.update(take(had, FRAME_KEYS))
                if had.get("_designed") and not f.get("_designed"):
                    f["_designed"] = True
                    f.update(
                        take(
                            had,
                            (
                                "picture",
                                "picture_p",
                                "component",
                                "component_sig",
                                "arrangement",
                                "relation",
                                "transition",
                            ),
                        )
                    )
                    by_id = {o.get("id"): o for o in had.get("objects", [])}
                    for o in f.get("objects", []):
                        src = by_id.get(o.get("id"))
                        if src is not None and "type" in src and "type" not in o:
                            o.update(take(src, OBJECT_KEYS))
                    for k, c in enumerate(f.get("cues", [])):
                        src_cues = had.get("cues") or []
                        if k < len(src_cues) and "move" in src_cues[k] and "move" not in c:
                            c.update(take(src_cues[k], CUE_KEYS))
    return labels_of(now)


def picks_kept(then: Row, now: Row, plan_then: Row, plan_now: Row, taken: Row | None = None) -> Row:
    """A person's picks when a change is taken back, or put back: the plan goes to how it
    stood (`plan_then`, picked as `then`) from how it stands (`plan_now`, picked as `now`).

    A change in words never touches a pick, so the picks stand as they are now. A line or a
    chapter that comes back with the plan brings its own, and one that goes takes its own with
    it. `taken` is a pick that is itself what goes back (it needed the writer, who planned a
    picture for it): what it named is as it was then."""
    taken = taken or {}
    cleared = set(taken.get("clear") or [])
    out: Row = {k: copy.deepcopy(v) for k, v in now.items() if k not in ("frames", "chapters")}
    if "all" in taken:
        out.pop("all", None)
        if then.get("all"):
            out["all"] = copy.deepcopy(then["all"])
    for kind, ids, here in (
        (
            "frames",
            [f["id"] for _, _, f in frames_of(plan_then)],
            {f["id"] for _, _, f in frames_of(plan_now)},
        ),
        (
            "chapters",
            [ch["id"] for ch in plan_then.get("chapters", [])],
            {ch["id"] for ch in plan_now.get("chapters", [])},
        ),
    ):
        kept: Row = {}
        for key in ids:
            as_then = key not in here or key in taken.get(kind, {}) or key in cleared
            pick = (then if as_then else now).get(kind, {}).get(key)
            if pick:
                kept[key] = copy.deepcopy(pick)
        if kept:
            out[kind] = kept
    return out


def picture_of(f: Row) -> str:
    """The type of picture a line shows: the person's pick, else the plan's reading."""
    return str((f.get("picked") or {}).get("picture") or f.get("picture") or "")


def transition_of(f: Row) -> str:
    """How a line's picture comes in: the person's pick, else the plan's reading."""
    return str((f.get("picked") or {}).get("transition") or f.get("transition") or "")


def _label_frame(f: Row, b: Row, labels: Row) -> None:
    lab = labels.get("frames", {}).get(f["id"])
    if not lab or lab.get("h") != frame_hash(f, b):
        return
    f.update(
        take(lab, ("presence", "layout", "options", "presence_p", "override", "line_only", "by"))
    )
    if f.get("line_only") and not f.get("shows") and not f.get("hold"):
        f["hold"] = True  # the line needs no picture: the picture before stays
        f["_auto_hold"] = True
    if lab.get("hd") != design_hash(f):
        return
    f["_designed"] = True
    f.update(
        take(
            lab,
            (
                "picture",
                "picture_p",
                "component",
                "component_sig",
                "arrangement",
                "relation",
                "transition",
            ),
        )
    )
    for o in f.get("objects", []):
        ol = labels.get("objects", {}).get(f["id"] + "/" + str(o.get("id", "")))
        if ol and ol.get("h") == digest(o.get("what")):
            o.update(take(ol, OBJECT_KEYS))
    for k, c in enumerate(f.get("cues", [])):
        cl = labels.get("cues", {}).get(f"{f['id']}/{k}")
        if cl and cl.get("h") == digest(c.get("does")):
            c.update(take(cl, CUE_KEYS))


def inherit_holds(plan: Row) -> None:
    """A frame that holds keeps the picture of the frame before it: the same presence and
    layout (unless a person picked otherwise), the same picture and arrangement, no transition.
    `_held` lists the objects of the picture it holds, so its cues may move them."""
    prev: Row | None = None
    for ch in plan.get("chapters", []):
        for b in ch.get("beats", []):
            for f in b.get("frames", []):
                if f.get("hold") and prev is not None:
                    if not f.get("override") and prev.get("presence"):
                        f["presence"], f["layout"] = prev["presence"], prev.get("layout")
                    for key in ("picture", "arrangement"):
                        if prev.get(key):
                            f[key] = prev[key]
                    if prev.get("presence"):
                        f["relation"], f["transition"] = "same-picture", "none"
                    f["_held"] = list(prev.get("_held", [])) + list(prev.get("objects", []))
                    if not f.get("shows") and (prev.get("shows") or prev.get("_shows_held")):
                        f["_shows_held"] = prev.get("shows") or prev.get("_shows_held")
                elif f.get("hold"):
                    f["hold"] = False  # nothing before it to hold
                prev = f


def labels_of(plan: Row) -> Row:
    """The labels a merged plan carries, each with the hash of the words it was read from."""
    out: Row = {
        "brief": take(plan.get("brief", {}), BRIEF_KEYS),
        "material": {},
        "chapters": {},
        "beats": {},
        "frames": {},
        "objects": {},
        "cues": {},
        "overrides": plan.get("_overrides", {}),
    }
    for m in plan.get("material", []):
        if "kind" in m:
            out["material"][m["id"]] = dict(take(m, MATERIAL_KEYS), h=digest(m.get("text")))
    for ch in plan.get("chapters", []):
        if "type" in ch:
            out["chapters"][ch["id"]] = dict(take(ch, CHAPTER_KEYS), h=chapter_hash(ch))
        for b in ch.get("beats", []):
            if "subtype" in b:
                out["beats"][b["id"]] = dict(take(b, BEAT_KEYS), h=beat_hash(b))
            for f in b.get("frames", []):
                if "presence" in f:
                    row = dict(take(f, FRAME_KEYS), h=frame_hash(f, b))
                    if f.get("_designed"):
                        row["hd"] = design_hash(f)
                    out["frames"][f["id"]] = row
                for o in f.get("objects", []):
                    if "type" in o:
                        out["objects"][f["id"] + "/" + o["id"]] = dict(
                            take(o, OBJECT_KEYS), h=digest(o.get("what"))
                        )
                for k, c in enumerate(f.get("cues", [])):
                    if "move" in c:
                        out["cues"][f"{f['id']}/{k}"] = dict(
                            take(c, CUE_KEYS), h=digest(c.get("does"))
                        )
    return out


def beats_of(plan: Row) -> Iterator[tuple[Row, Row]]:
    for ch in plan.get("chapters", []):
        for b in ch.get("beats", []):
            yield ch, b


def frames_of(plan: Row) -> Iterator[tuple[Row, Row, Row]]:
    for ch, b in beats_of(plan):
        for f in b.get("frames", []):
            yield ch, b, f


def toks(text: str | None) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-]*", text or "")
