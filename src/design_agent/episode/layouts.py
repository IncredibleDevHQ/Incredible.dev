"""Who has the frame, and in which layout. Code, not a model.

The classifier reads each line and says how likely it is to need the person, the person with
content, or content alone. The theme says how often a film on that theme uses each. This
module multiplies the two, ranks the theme's kit for every frame, and applies a person's
overrides on top. The first option is the pick; the rest are what a layout picker shows.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from design_agent.episode import questions as Q
from design_agent.episode.plan import Row, frames_of

LAY = Q.table("layouts")
THEMES = Q.table("themes")
PRESENCES = ("person", "both", "content")


def theme_of(plan: Row) -> Row:
    brief = plan.get("brief", {})
    if brief.get("presenter", "on") == "off":
        return THEMES["voice-only"]
    return THEMES.get(str(brief.get("theme") or ""), THEMES["corner-window"])


def marks_seconds(plan: Row) -> float:
    """Seconds of the video that are not voice: the end card, and the title sting when the
    theme opens on one."""
    numbers = Q.TYPES["numbers"]
    sting = numbers["title_sting_seconds"] if "title-sting" in theme_of(plan)["marks"] else 0
    return float(numbers["end_card_seconds"] + sting)


def word_budget(plan: Row) -> tuple[int, int] | None:
    """The fewest and the most words the script may hold, for the length a person asked for:
    the brief's `seconds` is the least and the most the film may run. None when the brief has
    none: they left the length to the material, and no length is checked."""
    asked = plan.get("brief", {}).get("seconds")
    if not isinstance(asked, (list, tuple)) or len(asked) != 2:
        return None
    rate, cards = Q.TYPES["numbers"]["words_per_second"], marks_seconds(plan)
    # rounded first: 295 s at 2.6 words is 767 words, not the 767.0000000000001 a float makes
    least, most = (round((float(s) - cards) * rate, 6) for s in asked)
    return math.ceil(least), math.floor(most)


def wanted(plan: Row, ch: Row, f: Row) -> Row:
    """A person's pick for this frame: the whole video, then its chapter, then the frame."""
    over = plan.get("_overrides", {})
    want = dict(over.get("all", {}))
    want.update(over.get("chapters", {}).get(ch["id"], {}))
    want.update(over.get("frames", {}).get(f["id"], {}))
    return want


def scoped(plan: Row, ch: Row, theme: Row, presence: str) -> tuple[str, str] | None:
    """A layout a person set for every line of one presence, in the chapter or in the whole
    film, and which of the two it came from. It never changes who has the frame, and it holds
    only while the film's look has that layout."""
    over = plan.get("_overrides", {})
    for scope, picks in (
        ("chapter", over.get("chapters", {}).get(ch["id"], {})),
        ("film", over.get("all", {})),
    ):
        lay = (picks.get("layouts") or {}).get(presence)
        if lay in LAY and LAY[lay]["presence"] == presence and lay in theme["kit"]:
            return str(lay), scope
    return None


def layout_for(theme: Row, presence: str, asked: str | None = None) -> str:
    if asked is not None and asked in LAY and LAY[asked]["presence"] == presence:
        return asked
    default = theme["default"].get(presence)
    if default and LAY[default]["presence"] == presence:
        return str(default)
    for lay in Q.TYPES["layouts"]:
        if lay["presence"] == presence and lay["id"] in theme["kit"]:
            return str(lay["id"])
    return str(next(lay["id"] for lay in Q.TYPES["layouts"] if lay["presence"] == presence))


def split(theme: Row) -> float:
    """Of the frames that show something, the share the theme keeps beside the person."""
    shares = theme["shares"]
    shown = shares.get("both", 0.0) + shares.get("content", 0.0)
    return float(shares.get("both", 0.0) / shown) if shown else 0.0


def rank(
    theme: Row, probs: Mapping[str, float], first: str | None = None, preferred: str | None = None
) -> list[Row]:
    """The theme's kit ranked for one frame. The classifier answers what it can read from a
    line: does it need the person alone, or something shown? The theme answers what it owns:
    whether shown content sits beside the person or alone. `first` is the presence picked."""
    pj = probs.get("person", 0.0)
    both_w = split(theme)
    score = {"person": pj, "both": (1 - pj) * both_w, "content": (1 - pj) * (1 - both_w)}
    defaults = dict(theme["default"])
    if preferred is not None:
        defaults[LAY[preferred]["presence"]] = preferred
    ranked: list[Row] = []
    for lay_id in theme["kit"]:
        presence = LAY[lay_id]["presence"]
        p = score[presence]
        if lay_id != defaults.get(presence):
            p *= 0.35  # a second layout of the same presence is a variation, not the default
        ranked.append({"layout": lay_id, "presence": presence, "p": round(p, 2)})
    ranked.sort(key=lambda r: (r["presence"] != first, -r["p"]))
    return ranked


def settle_frames(plan: Row) -> None:
    """Sets presence, layout and options on every frame that has been read (or needs no
    reading because nobody is on camera), then applies a person's overrides.

    A line goes to the person when its reading clears the theme's bar (`person_from`), or when
    the writer meant it to and the reading does not rule it out. Otherwise something is shown,
    beside the person or alone as the theme has it. A line that reads as the person's but does
    not clear the bar needs no picture of its own: it holds the picture before."""
    theme = theme_of(plan)
    off = plan.get("brief", {}).get("presenter", "on") == "off"
    numbers = Q.TYPES["numbers"]
    prev: Row | None = None
    for ch, _b, f in frames_of(plan):
        probs: Row | None = {"content": 1.0} if off else f.get("presence_p")
        if not probs:
            prev = f
            continue
        pj = probs.get("person", 0.0)
        wants = f.get("wants")
        f.pop("override", None)
        f.pop("line_only", None)
        f.pop("by", None)
        if f.pop("_auto_hold", None):
            f["hold"] = False  # a hold this module set earlier is worked out again, never kept
        presence: str
        layout: str | None
        if off:
            presence = "content"
        elif wants in PRESENCES and probs.get(wants, 0.0) >= numbers["intent_presence"]:
            presence = str(wants)
            f["by"] = "intent"
        elif pj >= theme.get("person_from", 0.5):
            presence = "person"
        else:
            presence = "both" if split(theme) >= 0.5 else "content"
        if not off and wants in PRESENCES and presence != wants:
            f["by"] = "overruled"  # the reading gave the writer's intent under the least it needs
        intent = f.get("layout_intent")
        layout = layout_for(theme, presence, intent if intent in theme["kit"] else None)
        ranked = rank(theme, probs, presence, layout)
        f["options"] = [r for r in ranked if r["p"] > 0][:4] or ranked[:1]
        want = wanted(plan, ch, f)
        if off and (
            want.get("layout") not in theme["kit"] or want.get("presence") not in (None, "content")
        ):
            want = {}
        if want.get("presence") in PRESENCES or want.get("layout") in LAY:
            new_presence = str(
                want.get("presence")
                if want.get("presence") in PRESENCES
                else LAY[want["layout"]]["presence"]
            )
            new_layout = layout_for(theme, new_presence, want.get("layout"))
            if (new_presence, new_layout) != (presence, layout):
                f["override"] = {
                    "presence": new_presence,
                    "layout": new_layout,
                    "reason": want.get("reason", "picked by a person"),
                    "was": {"presence": presence, "layout": layout},
                }
                presence, layout = new_presence, new_layout
        elif (
            not off
            and presence != "person"
            and not f.get("shows")
            and prev is not None
            and pj >= numbers["line_only_person"]
        ):
            f["line_only"] = True
            f["hold"] = True
            f["_auto_hold"] = True
        own = plan.get("_overrides", {}).get("frames", {}).get(f["id"], {})
        own_layout = own.get("layout")
        own_applies = own_layout in (theme["kit"] if off else LAY) and (not off or bool(want))
        if not f.get("hold") and not own_applies:
            # the line has no layout of its own picked: its chapter's, then the film's
            found = scoped(plan, ch, theme, presence)
            if found is not None and found[0] != layout:
                was = (f.get("override") or {}).get("was") or {
                    "presence": presence,
                    "layout": layout,
                }
                f["override"] = {
                    "presence": presence,
                    "layout": found[0],
                    "reason": "picked by a person",
                    "was": was,
                    "scope": found[1],
                }
                layout = found[0]
        if f.get("hold") and prev is not None and not f.get("override") and prev.get("presence"):
            presence, layout = prev["presence"], prev.get("layout")
        f["presence"], f["layout"] = presence, layout
        prev = f
