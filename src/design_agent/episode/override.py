"""Applies a person's choices about who has the frame, and tells the planner what follows.

A layout is never one right answer: the plan keeps the ranked options for every frame, and a
person may pick another one, for one frame, for a chapter or for the whole video. A choice
changes more than the frame. This script records the choice, works out what it breaks, and
writes that down as feedback for the next planning pass.

usage: override.py <plan.json> <overrides.json>

overrides.json, any of:
  {"presenter": "off"}                                  no speaker anywhere
  {"frames":   {"c2.b3.f1": {"presence": "content"}}}   or {"layout": "split"}; optional "reason"
  {"chapters": {"c4": {"presence": "content"}}}         every frame of a chapter
  {"all":      {"layout": "panel-and-portrait"}}        the old studio's "apply to all"
  {"chapters": {"c4": {"layouts": {"both": "split"}}}}  a layout for one presence, in a chapter
  {"all":      {"layouts": {"both": "split"}}}          or in the whole film
  {"frames":   {"c2.b3.f1": {"picture": "list"}}}       the type of the picture a line brings in
  {"frames":   {"c2.b3.f1": {"transition": "push"}}}    and how it comes in
  {"clear":    ["c2.b3.f1"]}                            take a line's or a chapter's picks back

A value of null takes one pick back and leaves the others of that line.

The picks are kept in labels.json and applied every time the plan is read, so they survive
re-planning. plan.json is never rewritten. feedback.json says what changed, why it matters,
and what the planner must redo.
"""

from __future__ import annotations

from design_agent.episode import geometry, layouts
from design_agent.episode import plan as planio
from design_agent.episode import questions as Q
from design_agent.episode.plan import Row, beats_of, frames_of

OBJ = Q.table("object_types")
NEEDS_A_FACE = {
    "who-is-speaking": "a greeting by name needs a face: open on the subject instead, or put the name on a card",
    "authority": "a claim to authority needs the person: move it onto an overlay or cut it",
    "banter": "banter has no one to say it: cut it",
    "sign-off": "the goodbye becomes the end card's line",
    "ask": "the ask moves onto the end card as a link, and the line shortens",
}


#: The picture types a person may pick: the ones a builder draws from a line's own words.
PICTURES = ("diagram", "list", "typeset-code", "chips", "illustration", "slide")
#: How a picture may come in. A line that holds the picture before has nothing to pick.
TRANSITIONS = ("cut", "push", "crossfade", "zoom-through")


def _laid(old: Row, new: Row) -> Row:
    """One line's, chapter's or the film's picks with `new` laid over them. A value of None
    takes that pick back; `layouts` (a layout for each presence) is merged the same way."""
    out = dict(old)
    for key, value in new.items():
        if key == "layouts" and isinstance(value, dict):
            layouts_now = _laid(dict(out.get("layouts") or {}), value)
            if layouts_now:
                out["layouts"] = layouts_now
            else:
                out.pop("layouts", None)
        elif value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def merge(old: Row, new: Row) -> Row:
    out = dict(old)
    for key in ("frames", "chapters"):
        if key in new:
            out[key] = dict(out.get(key, {}))
            for item, picks in new[key].items():
                laid = _laid(out[key].get(item, {}), picks)
                if laid:
                    out[key][item] = laid
                else:
                    out[key].pop(item, None)
    if "all" in new:
        laid = _laid(out.get("all", {}), new["all"])
        if laid:
            out["all"] = laid
        else:
            out.pop("all", None)
    if "presenter" in new:
        out["presenter"] = new["presenter"]
    for fid in new.get("clear", []):
        out.get("frames", {}).pop(fid, None)
        out.get("chapters", {}).pop(fid, None)
    return out


def refuse(new: Row) -> None:
    """Raises ValueError for a pick that names something outside the closed lists."""
    every = [*new.get("frames", {}).values(), *new.get("chapters", {}).values()]
    if new.get("all"):
        every.append(new["all"])
    for picks in every:
        size = picks.get("window_size")
        if size is not None and not (
            (type(size) is int and 25 <= size <= 125)
            or (isinstance(size, str) and size in geometry.WINDOW_SIZES)
        ):
            raise ValueError("Presenter size must be between 25 and 125 percent.")
        if (
            picks.get("window_shape") is not None
            and picks["window_shape"] not in geometry.WINDOW_SHAPES
        ):
            raise ValueError("Invalid presenter window_shape.")
        if picks.get("picture") is not None and picks["picture"] not in PICTURES:
            raise ValueError(f"There is no picture type called {picks['picture']}.")
        if picks.get("transition") is not None and picks["transition"] not in TRANSITIONS:
            raise ValueError(f"There is no transition called {picks['transition']}.")
        if picks.get("layout") is not None and picks["layout"] not in layouts.LAY:
            raise ValueError(f"There is no layout called {picks['layout']}.")
        for presence, lay in (picks.get("layouts") or {}).items():
            if presence not in layouts.PRESENCES:
                raise ValueError(f"Nobody has the frame as {presence}.")
            if lay is not None and (
                lay not in layouts.LAY or layouts.LAY[lay]["presence"] != presence
            ):
                raise ValueError(f"{lay} is not a layout for {presence}.")


def has_picture(f: Row) -> bool:
    return any(
        OBJ.get(o.get("type"), {}).get("family") not in ("on the person", None)
        for o in f.get("objects", [])
    ) or bool(f.get("shows"))


def apply(plan: Row, new: Row) -> list[Row]:
    """Record a person's picks on a merged plan (in place) and say what each one changes: what
    was, what is now, why, and what the writer has to redo, if anything."""
    before = {f["id"]: (f.get("presence"), f.get("layout")) for _, _, f in frames_of(plan)}
    was_off = plan.get("brief", {}).get("presenter", "on") == "off"
    plan["_overrides"] = merge(plan.get("_overrides", {}), new)
    brief = plan.setdefault("brief", {})
    feedback: list[Row] = []
    if plan["_overrides"].get("presenter") == "off" and not was_off:
        brief["theme_before"], brief["presenter"], brief["theme"] = (
            brief.get("theme"),
            "off",
            "voice-only",
        )
        feedback.append(
            {
                "where": "brief",
                "was": "presenter on",
                "now": "presenter off",
                "why": "no speaker",
                "do": "the theme is now voice-only: every frame shows content and nothing is recorded on camera",
            }
        )
    off = brief.get("presenter", "on") == "off"
    layouts.settle_frames(plan)
    planio.inherit_holds(plan)
    for _ch, b in beats_of(plan):
        if off and not was_off and b.get("subtype") in NEEDS_A_FACE:
            feedback.append(
                {
                    "where": b["id"],
                    "was": b.get("subtype"),
                    "now": "no one on screen",
                    "why": "no speaker",
                    "do": "rewrite the line: " + NEEDS_A_FACE[b["subtype"]],
                }
            )
    for _ch, _b, f in frames_of(plan):
        was_p, was_l = before.get(f["id"], (None, None))
        now_p, now_l = f.get("presence"), f.get("layout")
        if was_p is None or (was_p, was_l) == (now_p, now_l):
            continue
        why = "no speaker" if off else (f.get("override") or {}).get("reason", "picked by a person")
        item: Row = {
            "where": f["id"],
            "was": f"{was_p} / {was_l}",
            "now": f"{now_p} / {now_l}",
            "why": why,
        }
        if was_p == "person" and now_p != "person":
            item["do"] = (
                "nothing to redo: a picture was already written"
                if f.get("shows")
                else "nothing to redo: it holds the picture before"
                if f.get("hold")
                else "the line was said to camera and now needs a picture: write `shows`, objects and cues for it, or mark it `hold` on the picture before"
            )
        elif was_p != "person" and now_p == "person":
            item["do"] = (
                "the picture is gone: keep at most one term as an overlay and move what must be seen to the frame before or after"
                if has_picture(f)
                else "nothing to redo"
            )
        elif was_p == "both" and now_p == "content":
            item["do"] = (
                "nothing to redo: the picture stays as written, unless its `shows` or an object names the presenter"
                if off
                else "nothing to redo: the person leaves the frame. Look at the person-away check and at the take's switches"
            )
        elif was_p == "content" and now_p == "both":
            item["do"] = (
                "nothing to redo: the person returns beside the picture. Keep the picture clear of the person's side"
            )
        else:
            item["do"] = "nothing to redo: the layout changed within the same presence"
        feedback.append(item)
    return feedback


def redo(feedback: list[Row]) -> list[Row]:
    """The picks that leave the writer something to do."""
    return [x for x in feedback if not str(x["do"]).startswith("nothing to redo")]
