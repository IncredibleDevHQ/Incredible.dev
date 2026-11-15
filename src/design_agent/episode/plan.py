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
                _label_frame(f, b, labels)
                pick = plan["_overrides"].get("frames", {}).get(f["id"], {})
                picked = {k: pick[k] for k in PICKED_KEYS if pick.get(k)}
                if picked:
                    f["picked"] = picked
    inherit_holds(plan)
    return plan


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
    f.update(take(lab, ("picture", "picture_p", "arrangement", "relation", "transition")))
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
