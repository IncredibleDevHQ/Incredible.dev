"""When everything happens in the film: code, never a model.

The plan's own clock counts words. Once a chapter is recorded the take's clock replaces it:
each line runs for as long as it was said, and the picture's cues move with it, so nothing a
person records has to match a guess. A narrated line runs for as long as the narration, and
its cues land on the words the narrator's timings give.
"""

from __future__ import annotations

from typing import Any

from design_agent.episode.plan import toks

Row = dict[str, Any]

#: A cue starts this long before its word, so it has landed when the word is said.
LEAD = 0.2
#: The breath between two narrated lines.
NARRATION_GAP = 0.25
#: The shortest a recorded line may run in the film, however early the next line was started.
LINE_LEAST = 0.4


def schedule(full: Row, takes: list[Row] | None = None, voice: Row | None = None) -> Row:
    """The film's clock from a derived plan, the takes that are kept, and narration by frame.

    A take is `{"id", "chapter", "frame" (a line's own take), "seconds", "marks": [{"frame",
    "t"}]}`; a line's own take wins over its chapter's. Narration is `{frame id: {"seconds",
    "words": [{"word", "start", "end"}]}}`.
    """
    by_chapter: dict[str, Row] = {}
    by_line: dict[str, Row] = {}
    for take in takes or []:
        if take.get("frame"):
            by_line[str(take["frame"])] = take
        else:
            by_chapter[str(take["chapter"])] = take
    voice = voice or {}
    marks: list[Row] = []
    lines: list[Row] = []
    chapters: list[Row] = []
    cues: dict[str, float] = {}
    t = 0.0
    for mark in full.get("marks", []):
        if mark.get("mark") == "title-sting":
            marks.append({"mark": "title-sting", "start": 0.0, "seconds": float(mark["seconds"])})
            t = float(mark["seconds"])
    cards = {m.get("chapter"): m for m in full.get("marks", []) if m.get("mark") == "chapter-card"}
    for ch in full.get("chapters", []):
        frames = [f for b in ch.get("beats", []) for f in b.get("frames", [])]
        kept = by_chapter.get(ch["id"])
        starts = {str(m["frame"]): float(m["t"]) for m in (kept or {}).get("marks", [])}
        chapter_start = t
        if ch["id"] in cards:
            marks.append(
                {
                    "mark": "chapter-card",
                    "start": round(t, 2),
                    "seconds": float(cards[ch["id"]].get("seconds", 2.0)),
                    "chapter": ch["id"],
                }
            )
        for i, f in enumerate(frames):
            fid = str(f["id"])
            planned = max(float(f.get("seconds", 0.0)), LINE_LEAST)
            source: Row = {"kind": "plan"}
            seconds = planned
            words: list[Row] = []
            if fid in by_line:
                own = by_line[fid]
                seconds = max(float(own.get("seconds", planned)), LINE_LEAST)
                source = {"kind": "take", "take": own["id"], "offset": 0.0}
            elif kept is not None and fid in starts:
                later = [starts[str(g["id"])] for g in frames[i + 1 :] if str(g["id"]) in starts]
                until = min(later) if later else float(kept.get("seconds", starts[fid] + planned))
                seconds = max(until - starts[fid], LINE_LEAST)
                source = {"kind": "take", "take": kept["id"], "offset": round(starts[fid], 3)}
            elif fid in voice:
                seconds = float(voice[fid].get("seconds", planned)) + NARRATION_GAP
                words = list(voice[fid].get("words") or [])
                source = {"kind": "voice"}
            lines.append(
                {
                    "frame": fid,
                    "chapter": ch["id"],
                    "start": round(t, 3),
                    "seconds": round(seconds, 3),
                    "source": source,
                }
            )
            for k, cue in enumerate(f.get("cues", [])):
                cues[f"{fid}/{k}"] = round(_cue_at(cue, f, t, seconds, planned, words), 3)
            t += seconds
        chapters.append(
            {
                "id": ch["id"],
                "start": round(chapter_start, 3),
                "seconds": round(t - chapter_start, 3),
            }
        )
    card = next((m for m in full.get("marks", []) if m.get("mark") == "end-card"), None)
    end_seconds = float(card["seconds"]) if card else 5.0
    marks.append({"mark": "end-card", "start": round(t, 3), "seconds": end_seconds})
    return {
        "total": round(t + end_seconds, 3),
        "marks": marks,
        "chapters": chapters,
        "lines": lines,
        "cues": cues,
    }


def _cue_at(
    cue: Row, f: Row, start: float, seconds: float, planned: float, words: list[Row]
) -> float:
    """Where a cue lands in the film: on its word when the narration's timings have it, else at
    the same share of the line as the plan gave it."""
    said = _word_start(cue, words)
    if said is not None:
        return max(start, start + said - LEAD)
    planned_t = cue.get("t")
    if planned_t is None:
        return start
    share = (float(planned_t) - float(f.get("start", 0.0))) / planned if planned else 0.0
    return start + min(max(share, 0.0), 1.0) * seconds


def _word_start(cue: Row, words: list[Row]) -> float | None:
    at = [w.lower() for w in toks(str(cue.get("at", "")))]
    if not at or not words:
        return None
    spoken = [(toks(str(w.get("word", ""))), float(w.get("start", 0.0))) for w in words]
    flat = [(parts[0].lower(), start) for parts, start in spoken if parts]
    for i in range(len(flat) - len(at) + 1):
        if [w for w, _ in flat[i : i + len(at)]] == at:
            return flat[i][1]
    return None


def line_of(clock: Row, frame: str) -> Row | None:
    return next((line for line in clock["lines"] if line["frame"] == frame), None)
