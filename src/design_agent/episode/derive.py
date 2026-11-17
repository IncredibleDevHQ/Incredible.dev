"""Derives everything a plan states as a number or a schedule. Code writes these, never the
writer: times, the cue clock, the marks, and the recording plan.

usage: derive.py <plan.json>

Writes plan.full.json beside the plan: the writer's words, the classifier's labels and what
code derives (`seconds` and `start` on chapters, beats and frames, `t` on cues, `marks`,
`totals`). Writes recording.json. plan.json itself is never rewritten.
"""

from __future__ import annotations

import re
from typing import Any

from design_agent.episode import questions as Q
from design_agent.episode.plan import Row

N = Q.TYPES["numbers"]
WPS = N["words_per_second"]
LEAD = 0.2  # a cue starts this long before its word, so it has landed when the word is said
THEMES = Q.table("themes")
MARKS = Q.table("marks")


def toks(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-]*", text or "")


def derive(plan: Row) -> Row:
    brief = plan.get("brief", {})
    off = brief.get("presenter", "on") == "off"
    theme = THEMES.get("voice-only" if off else brief.get("theme"), THEMES["corner-window"])
    marks = []
    t = 0.0
    if "title-sting" in theme["marks"]:
        marks.append({"mark": "title-sting", "start": 0.0, "seconds": 3.0})
        t = 3.0
    presence_words = {"person": 0, "both": 0, "content": 0}
    cues_total = 0
    for ch in plan.get("chapters", []):
        ch["start"] = round(t, 1)
        if (
            "chapter-card" in theme["marks"]
            and ch is not plan["chapters"][0]
            and ch.get("part") not in ("close",)
        ):
            marks.append(
                {
                    "mark": "chapter-card",
                    "start": round(t, 1),
                    "seconds": 2.0,
                    "chapter": ch["id"],
                    "over": "the first words of the chapter",
                }
            )
        for b in ch.get("beats", []):
            b["start"] = round(t, 1)
            frames = b.get("frames") or [{"vo": b.get("says", "")}]
            for f in frames:
                w = len(toks(f.get("vo", "")))
                f["start"], f["seconds"], f["words"] = round(t, 1), round(w / WPS, 1), w
                vt = [x.lower() for x in toks(f.get("vo", ""))]
                for c in f.get("cues", []):
                    at = [x.lower() for x in toks(c.get("at", ""))]
                    p = (
                        next(
                            (k for k in range(len(vt) - len(at) + 1) if vt[k : k + len(at)] == at),
                            None,
                        )
                        if at
                        else None
                    )
                    if p is not None:
                        c["t"] = round(max(t, t + p / WPS - LEAD), 1)
                    else:
                        # Keep the original reveal's share of the line when its spoken anchor
                        # was edited away. Every pass recomputes it on this frame's new clock.
                        original = [
                            x.lower() for x in toks((f.get("by_person") or {}).get("was", ""))
                        ]
                        position = (
                            next(
                                (
                                    i
                                    for i in range(len(original) - len(at) + 1)
                                    if original[i : i + len(at)] == at
                                ),
                                None,
                            )
                            if at
                            else None
                        )
                        share = (
                            max(0, position / WPS - LEAD) / (len(original) / WPS)
                            if position is not None
                            else 0
                        )
                        c["t"] = round(t + share * w / WPS, 3)
                    cues_total += 1
                if f.get("presence") in presence_words:
                    presence_words[f["presence"]] += w
                t += w / WPS
            b["seconds"] = round(t - b["start"], 1)
            b["words"] = len(toks(b.get("says", "")))
        ch["seconds"] = round(t - ch["start"], 1)
        ch["words"] = sum(b["words"] for b in ch.get("beats", []))
    marks.append({"mark": "end-card", "start": round(t, 1), "seconds": 5.0})
    plan["marks"] = marks
    words = sum(ch["words"] for ch in plan.get("chapters", []))
    total = sum(presence_words.values()) or 1
    plan["totals"] = {
        "seconds": round(t + 5.0, 1),
        "voice_seconds": round(t - (3.0 if "title-sting" in theme["marks"] else 0), 1),
        "words": words,
        "chapters": len(plan.get("chapters", [])),
        "beats": sum(len(ch.get("beats", [])) for ch in plan.get("chapters", [])),
        "frames": sum(
            len(b.get("frames", [])) for ch in plan.get("chapters", []) for b in ch.get("beats", [])
        ),
        "cues": cues_total,
        "presence_share": {k: round(100 * v / total) for k, v in presence_words.items()},
    }
    return plan


def recording(plan: Row) -> Row:
    """One take per chapter, recorded inside the layout, with the script as notes beside the
    frame and the cues as steps the presenter advances. With the presenter off, voice only."""
    brief = plan.get("brief", {})
    off = brief.get("presenter", "on") == "off"
    takes = []
    for ch in plan.get("chapters", []):
        frames = [f for b in ch.get("beats", []) for f in b.get("frames", [])]
        track, last = [], None
        for f in frames:
            if f.get("presence") != last:
                track.append(
                    {"from": f.get("id"), "presence": f.get("presence"), "layout": f.get("layout")}
                )
                last = f.get("presence")
        on_camera = sum(
            f.get("seconds", 0) for f in frames if f.get("presence") in ("person", "both")
        )
        takes.append(
            {
                "take": ch["id"],
                "chapter": ch.get("question", ""),
                "seconds": ch.get("seconds", 0),
                "camera": (not off) and on_camera > 0,
                "on_camera_seconds": 0 if off else round(on_camera, 1),
                "notes": [
                    {"beat": b["id"], "says": b.get("says", "")} for b in ch.get("beats", [])
                ],
                "presence_track": [] if off else track,
                "switches": 0 if off else max(0, len(track) - 1),
                "steps": [
                    {"frame": f["id"], "at": c.get("at", ""), "does": c.get("does", "")}
                    for f in frames
                    for c in f.get("cues", [])
                ],
            }
        )
    return {
        "mode": "voice only" if off else "record inside the layout",
        "notes_dock": "right",
        "takes": takes,
        "totals": {
            "takes": len(takes),
            "camera_takes": sum(1 for t in takes if t["camera"]),
            "on_camera_seconds": round(sum(t["on_camera_seconds"] for t in takes), 1),
            "steps": sum(len(t["steps"]) for t in takes),
            "switches": sum(t["switches"] for t in takes),
        },
    }


def full(plan: Row) -> Row:
    """What code derives from a merged plan, ready to be read by anything else: every time,
    the cue clock, the marks and the totals, with the working keys taken out."""
    out = derive(plan)
    out["overrides"] = out.pop("_overrides", {})

    def clean(x: Any) -> Any:
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items() if not k.startswith("_")}
        if isinstance(x, list):
            return [clean(v) for v in x]
        return x

    cleaned: Row = clean(out)
    return cleaned
