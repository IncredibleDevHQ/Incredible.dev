"""Checks a classified plan against the rules of a concept explainer. Code decides; no model.

usage: check.py <plan.json> [--stage script|frames|design|all] [--cues] [--json]

  --cues   also print, for every frame with cues, the word and second each cue lands on,
           the gaps between them, and the still time left at the end

Each rule has an id, a group (structure, words, picture, motion) and a level:
  must   the plan is not done while this fails
  look   reported for the writer to weigh. To keep a look, write the reason in the plan:
         "waived": {"<rule id>": "why"}   (the id is the part after the slash)

The numbers come from reference/types.json ("numbers"), measured on published explainers.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Callable

from design_agent.episode import layouts
from design_agent.episode import questions as Q
from design_agent.episode.plan import Row, beats_of, toks

N = Q.TYPES["numbers"]
SUB = Q.table("beat_subtypes")
CHAP = Q.table("chapter_types")
OBJ = Q.table("object_types")
WPS = N["words_per_second"]

NEEDS = {  # at least one beat of these subtypes in a chapter of that type
    "introduction": ["hook", "promise", "need", "definition", "agenda", "who-is-speaking"],
    "demo-first": ["proof-first", "demonstration", "what-we-built", "worked-example"],
    "problem": ["need", "turn", "first-attempt"],
    "story": ["story"],
    "concept": ["definition"],
    "how-it-works": ["mechanism"],
    "options-compared": ["mechanism", "definition", "contrast"],
    "worked-example": ["worked-example"],
    "demo": ["demonstration"],
    "build": ["step", "code"],
    "feature-tour": ["list", "so-what"],
    "advice": ["advice", "principle"],
    "questions": ["question", "objection", "community-question"],
    "series": [
        "series-recap",
        "map-of-the-series",
        "look-ahead",
        "definition",
        "mechanism",
        "promise",
        "list",
        "contrast",
    ],
    "recap": ["recap", "landing"],
    "outro": ["ask", "sign-off", "landing"],
}
LONG_OK = {"code", "demonstration", "worked-example", "mechanism", "list", "story"}
SHORT_OK = {
    "go-line",
    "sign-off",
    "question",
    "turn",
    "signpost",
    "milestone",
    "bridge",
    "who-is-speaking",
    "tag",
    "ask",
    "landing",
}
CLOSING = {
    "landing",
    "recap",
    "ask",
    "sign-off",
    "look-ahead",
    "question-back",
    "where-to-get-it",
    "tag",
}
NO_ONE_QUESTION = ("introduction", "demo-first", "recap", "outro", "series")
NO_MIX = ("advice", "series", "feature-tour", "outro")
BUILDS = ("list", "chips")  # pictures that are meant to arrive item by item


def norm(text: str) -> str:
    return " ".join(t.lower() for t in toks(text))


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s]


def numbers_said(text: str) -> list[str]:
    """Figures written as digits. A digit inside a name (GPT-3, v2, 3D) is part of the name."""
    return re.findall(r"(?<![A-Za-z\-])\d[\d,.]*(?![A-Za-z\-])", text or "")


class Report:
    def __init__(self, waived: Row | None) -> None:
        self.rows: list[Row] = []
        self.waived: Row = waived or {}

    def add(self, group: str, rule: str, level: str, where: str, text: str) -> None:
        if level == "look" and rule in self.waived:
            return
        self.rows.append(
            {"group": group, "rule": rule, "level": level, "where": where, "text": text}
        )


def check_script(plan: Row, r: Report) -> bool:
    brief = plan.get("brief", {})
    chapters = plan.get("chapters", [])
    beats = [b for _, b in beats_of(plan)]
    for key in ("idea", "gap", "for", "seconds"):
        if not brief.get(key):
            r.add("structure", "brief", "must", "brief", f"the brief has no `{key}`")
    if not chapters or not beats:
        r.add("structure", "empty", "must", "plan", "no chapters or no beats yet")
        return False
    unlabelled = [b["id"] for b in beats if not b.get("subtype")] + [
        c["id"] for c in chapters if not c.get("type")
    ]
    if unlabelled:
        r.add(
            "structure",
            "unclassified",
            "must",
            ", ".join(unlabelled[:8]),
            "these have no label for their current words: run classify.py script",
        )
        return False

    words = {b["id"]: len(toks(b.get("says", ""))) for b in beats}
    total_words = sum(words.values())
    want = float(brief.get("seconds") or 0)
    if want:
        target = (want - layouts.marks_seconds(plan)) * WPS
        tol = N["length_tolerance"]
        if not ((1 - tol) * target <= total_words <= (1 + tol) * target):
            r.add(
                "words",
                "length",
                "must",
                "plan",
                f"{total_words} words; {want:.0f} s less the cards, at {WPS} words a second, is {target:.0f} words ({(1 - tol) * target:.0f} to {(1 + tol) * target:.0f} passes)",
            )
        elif abs(total_words - target) > 0.05 * target:
            r.add(
                "words",
                "length-near",
                "look",
                "plan",
                f"{total_words} words against a budget of {target:.0f}: {abs(total_words - target) / WPS:.0f} s {'over' if total_words > target else 'under'} the brief. Settle the length now; a line cut after its frame is designed takes its cues with it",
            )
    seconds = total_words / WPS
    if not (N["seconds"][0] <= seconds <= N["seconds"][1]):
        r.add(
            "words",
            "range",
            "look",
            "plan",
            f"{seconds:.0f} s is outside the usual {N['seconds'][0]} to {N['seconds'][1]} s",
        )
    if not (N["chapters"][0] <= len(chapters) <= N["chapters"][1]):
        r.add(
            "structure",
            "chapters",
            "look",
            "plan",
            f"{len(chapters)} chapters; the usual is {N['chapters'][0]} to {N['chapters'][1]}",
        )
    per_min = len(beats) / (seconds / 60) if seconds else 0
    if not (N["beats_per_minute"][0] <= per_min <= N["beats_per_minute"][1]):
        r.add(
            "words",
            "pace",
            "look",
            "plan",
            f"{per_min:.1f} beats a minute; explainers run {N['beats_per_minute'][0]} to {N['beats_per_minute'][1]}",
        )

    # open and close
    if chapters[0].get("type") not in ("introduction", "demo-first"):
        r.add(
            "structure",
            "open",
            "must",
            chapters[0]["id"],
            f"the first chapter reads as {chapters[0].get('type')}; a video opens on an introduction or a demo first",
        )
    t, first_substance = 0.0, None
    for i, b in enumerate(beats):
        if b["type"] in ("explain", "prove") and first_substance is None:
            first_substance = (i, t)
        t += words[b["id"]] / WPS
    if (
        first_substance is None
        or first_substance[0] >= N["first_substance_beats"]
        or first_substance[1] > N["first_substance_seconds"]
    ):
        where = (
            "none"
            if first_substance is None
            else f"beat {first_substance[0] + 1} at {first_substance[1]:.0f} s"
        )
        r.add(
            "structure",
            "substance-early",
            "must",
            beats[0]["id"],
            f"the first beat that explains or proves is {where}; it belongs in the first {N['first_substance_beats']} beats and {N['first_substance_seconds']} s",
        )
    tail = [b["subtype"] for b in beats[-3:]]
    if not any(s in ("ask", "sign-off") for s in tail):
        r.add(
            "structure",
            "close",
            "must",
            beats[-1]["id"],
            f"the last three beats read as {', '.join(tail)}; a video ends on the ask and the goodbye. An ask has to request something; a recap has to say it is one",
        )
    lands = [i for i, b in enumerate(beats) if b["subtype"] == "landing"]
    asks = [i for i, b in enumerate(beats) if b["subtype"] == "ask"]
    if not lands:
        r.add(
            "structure",
            "landing",
            "must",
            beats[-1]["id"],
            "no beat reads as the landing: one line that brings the idea home, before the ask",
        )
    elif asks and lands[-1] > asks[-1]:
        r.add(
            "structure",
            "landing-first",
            "look",
            beats[lands[-1]]["id"],
            "the landing comes after the ask; it lands better before it",
        )
    if lands:
        last = sentences(beats[lands[-1]].get("says", ""))
        if last and len(toks(last[-1])) > N["last_words_most"]:
            r.add(
                "words",
                "landing-length",
                "look",
                beats[lands[-1]]["id"],
                f"the landing's last sentence is {len(toks(last[-1]))} words; keep it to {N['last_words_most']}",
            )
    close_words, close_from = 0, beats[-1]["id"]
    for b in reversed(beats):
        if b["subtype"] not in CLOSING:
            break
        close_words += words[b["id"]]
        close_from = b["id"]
    close_most = N["close_words"][1] + (
        25 if (brief.get("series") or "none") != "none" else 0
    )  # a series adds a look ahead
    if not (N["close_words"][0] <= close_words <= close_most):
        r.add(
            "words",
            "close-length",
            "look",
            close_from,
            f"{close_words} words in the closing run that starts here (recap, landing, ask, goodbye); the usual close is {N['close_words'][0]} to {N['close_words'][1]}",
        )

    # chapters
    order = [c.get("part") for c in chapters]
    if order and order[-1] not in ("close", "judge", "series"):
        r.add(
            "structure",
            "parts-order",
            "look",
            chapters[-1]["id"],
            f"the last chapter's part is {order[-1]}; videos end in Close, or on advice that carries the close",
        )
    if "judge" in order and "explain" in order and order.index("judge") < order.index("explain"):
        r.add(
            "structure",
            "parts-order",
            "must",
            chapters[order.index("judge")]["id"],
            "a Judge chapter comes before anything is explained",
        )
    for ch in chapters:
        cb = ch.get("beats", [])
        subs = [b["subtype"] for b in cb]
        cw = sum(words[b["id"]] for b in cb)
        spec = CHAP.get(ch.get("type"), {})
        if ch.get("type") not in NO_ONE_QUESTION and ch.get("one_question", 1) < 0.5:
            r.add(
                "structure",
                "one-question",
                "look",
                ch["id"],
                f"the chapter reads {ch['one_question']} for answering its one question; narrow the question, or move out the beats that answer another",
            )
        need = NEEDS.get(ch.get("type"), [])
        if need and not any(s in need for s in subs):
            r.add(
                "structure",
                "recipe",
                "must",
                ch["id"],
                f"a {spec.get('name', ch.get('type'))} chapter needs a beat that reads as one of: {', '.join(need)}; it has {', '.join(subs) or 'none'}",
            )
        if spec and not (0.6 * spec["words"][0] <= cw <= 1.4 * spec["words"][1]):
            r.add(
                "words",
                "chapter-size",
                "look",
                ch["id"],
                f"{cw} words; a {spec['name']} chapter usually runs {spec['words'][0]} to {spec['words'][1]}",
            )
        if len(cb) >= N["mix_beats"] and ch.get("type") not in NO_MIX:
            top = max(set(subs), key=subs.count)
            if subs.count(top) > len(subs) / 2:
                r.add(
                    "structure",
                    "mix",
                    "look",
                    ch["id"],
                    f"{subs.count(top)} of {len(subs)} beats read as {top}; no one job should carry over half of a chapter",
                )

    # beats
    case_words = 0
    for _ch, b in beats_of(plan):
        w = words[b["id"]]
        most = 95 if b["subtype"] in LONG_OK else N["beat_words"][1]
        if w < N["beat_words"][0] and b["subtype"] not in SHORT_OK:
            r.add(
                "words",
                "beat-size",
                "look",
                b["id"],
                f"{w} words is thin for a {b['subtype']} beat",
            )
        if w > most:
            r.add(
                "words",
                "beat-size",
                "must",
                b["id"],
                f"{w} words in one beat (most: {most}); cut it where the job changes",
            )
        if b["type"] == "turn" and w > N["turn_words_most"]:
            r.add(
                "words",
                "turn-length",
                "look",
                b["id"],
                f"{w} words in a beat that turns; a turn is short (20 words in the middle case). If it explains, it is two beats",
            )
        if b.get("made_up") or b["subtype"] in ("analogy", "worked-example"):
            case_words += w
        if b.get("wants") and b["wants"] != b["subtype"] and b.get("p", 0) >= 0.8:
            r.add(
                "structure",
                "wants-differs",
                "look",
                b["id"],
                f"you meant {b['wants']}; the classifier is sure ({b['p']}) it reads as {b['subtype']}. Rewrite the words, or set wants to {b['subtype']}",
            )
    share = 100 * case_words / total_words if total_words else 0
    if not (N["made_up_share"][0] <= share <= N["made_up_share"][1]):
        r.add(
            "words",
            "case-share",
            "look",
            "plan",
            f"{share:.0f}% of the words are the case, an analogy or made up; explainers spend {N['made_up_share'][0]} to {N['made_up_share'][1]}%",
        )

    # density of turns, guides and examples
    def gaps(pred: Callable[[Row], bool], label: str, most: float, rule: str) -> None:
        t, last, worst, where = 0.0, 0.0, 0.0, beats[0]["id"]
        for b in beats:
            if pred(b):
                if t - last > worst:
                    worst, where = t - last, b["id"]
                last = t
            t += words[b["id"]] / WPS
        if t - last > worst:
            worst, where = t - last, beats[-1]["id"]
        if worst > most:
            r.add(
                "structure",
                rule,
                "look",
                where,
                f"{worst:.0f} s up to here with no {label}; keep it under {most} s",
            )

    gaps(
        lambda b: b["type"] == "turn",
        "beat that turns (a question, a problem, a so-what, a rule)",
        N["turn_every_seconds"],
        "turns",
    )
    gaps(
        lambda b: b["type"] == "guide" or b["subtype"] in ("agenda", "recap"),
        "beat that says where we are",
        N["guide_every_seconds"] + 60,
        "guides",
    )
    if not any(b["subtype"] in ("worked-example", "analogy") for b in beats):
        r.add(
            "structure",
            "example",
            "must",
            "plan",
            "no beat reads as a worked example or an analogy; an explainer needs a concrete case",
        )
    else:
        gaps(
            lambda b: (
                b["subtype"]
                in ("worked-example", "analogy", "demonstration", "story", "proof-first")
            ),
            "worked example, analogy or demo",
            N["example_every_seconds"],
            "example-gap",
        )
    if (brief.get("case") or {}).get("text"):
        chapters_with = sum(
            1
            for ch in chapters
            if any(b["subtype"] == "worked-example" for b in ch.get("beats", []))
        )
        if chapters_with < 2:
            r.add(
                "structure",
                "case-carried",
                "look",
                "plan",
                f"the brief names a case but worked-example beats sit in {chapters_with} chapter; carry it through at least two",
            )

    # share of words by job, and what the notes supply
    by_type: dict[str, int] = {}
    for b in beats:
        by_type[b["type"]] = by_type.get(b["type"], 0) + words[b["id"]]
    for tid, (lo, hi) in N["type_share"].items():
        s = 100 * by_type.get(tid, 0) / total_words
        if not (lo <= s <= hi):
            r.add(
                "words",
                "job-share",
                "look",
                "plan",
                f"{s:.0f}% of the words {tid}; explainers spend {lo} to {hi}%",
            )
    mats = {m["id"] for m in plan.get("material", [])}
    if mats:
        used, from_notes = set(), 0
        for b in beats:
            u = [x for x in b.get("uses", []) if x in mats]
            used.update(u)
            if u and not b.get("made_up"):
                from_notes += words[b["id"]]
        cover = 100 * len(used) / len(mats)
        if cover < 70:
            r.add(
                "structure",
                "coverage",
                "look",
                "plan",
                f"{cover:.0f}% of the notes' items are used by a beat; unused: {', '.join(sorted(mats - used)[:10])}",
            )
        if 100 * from_notes / total_words < N["notes_share_least"]:
            r.add(
                "words",
                "notes-share",
                "look",
                "plan",
                f"{100 * from_notes / total_words:.0f}% of the words are in beats that rest on the notes (`uses`); explainers take about half from the material",
            )

    # the voice
    lens = [(len(toks(s)), b["id"]) for b in beats for s in sentences(b.get("says", ""))]
    if lens:
        mid = statistics.median(n for n, _ in lens)
        want_len = (brief.get("voice") or {}).get("sentence_words")
        if want_len and abs(mid - want_len) > 4:
            r.add(
                "words",
                "voice",
                "look",
                "plan",
                f"the middle sentence is {mid:.0f} words; the brief's voice says {want_len}",
            )
        run = 0
        for n, where in lens:
            run = run + 1 if n >= 12 else 0
            if run >= 7:
                r.add(
                    "words",
                    "breath",
                    "look",
                    where,
                    "seven sentences in a row of twelve words or more end here; give the ear one short one",
                )
                break
    said = [b["id"] for b in beats if numbers_said(b.get("says", ""))]
    if said:
        r.add(
            "words",
            "said",
            "look",
            ", ".join(said[:6]),
            "figures written as digits in the voice; spell them out in `says` and put the digits on screen (a digit inside a name is fine)",
        )
    return True


def check_frames(plan: Row, r: Report) -> None:
    brief = plan.get("brief", {})
    off = brief.get("presenter", "on") == "off"
    away, worst_away, where_away, seen_person = 0.0, 0.0, "plan", False
    counts = {"person": 0, "both": 0, "content": 0}
    for _ch, b in beats_of(plan):
        frames = b.get("frames", [])
        if off and b.get("subtype") in ("who-is-speaking", "authority", "banter"):
            r.add(
                "picture",
                "no-speaker-line",
                "must",
                b["id"],
                f"nobody is on screen, and this line reads as {b['subtype']}: rewrite it or cut it (see feedback.json)",
            )
        if (
            off
            and b.get("subtype") in ("ask", "sign-off")
            and re.search(r"\b(see you|comments|tell me|I'll|I will)\b", b.get("says", ""), re.I)
        ):
            r.add(
                "picture",
                "no-speaker-line",
                "look",
                b["id"],
                f"nobody is on screen: this {b['subtype']} still speaks as a person to camera. Shorten it; the ask and the goodbye belong on the end card",
            )
        if off:
            for f in frames:
                named = [
                    t
                    for t in [f.get("shows", "")]
                    + [o.get("what", "") for o in f.get("objects", [])]
                    + [c.get("does", "") for c in f.get("cues", [])]
                    if re.search(r"\b(presenter|speaker|on camera|to camera)\b", t, re.I)
                ]
                if named:
                    r.add(
                        "picture",
                        "names-presenter",
                        "must",
                        f["id"],
                        "nobody is on screen, but this frame's picture still names the presenter: reword `shows`, the objects and the cues",
                    )
        if norm(" ".join(f.get("vo", "") for f in frames)) != norm(b.get("says", "")):
            r.add(
                "picture",
                "voice-split",
                "must",
                b["id"],
                "the frames' `vo` joined is not the beat's `says`",
            )
        if len(frames) > 3:
            r.add(
                "picture",
                "frames-per-beat",
                "look",
                b["id"],
                f"{len(frames)} frames in one beat; three is the most",
            )
        for f in frames:
            if not f.get("presence"):
                r.add(
                    "picture",
                    "unclassified",
                    "must",
                    f["id"],
                    "who has this frame has not been read for its current words: run classify.py frames",
                )
                continue
            w = len(toks(f.get("vo", "")))
            counts[f["presence"]] += w
            most = N["frame_words"][f["presence"]]
            if w > most:
                level = "look" if f["presence"] == "person" else "must"
                r.add(
                    "picture",
                    "frame-words",
                    level,
                    f["id"],
                    f"{w} words in one {f['presence']} frame (most: {most}); cut the frame at a sentence start, or give it a picture that changes",
                )
            if f["presence"] == "content":
                away += w / WPS
                if away > worst_away:
                    worst_away, where_away = away, f["id"]
            else:
                away, seen_person = 0.0, True
    if not off and worst_away > N["person_away_seconds"]:
        r.add(
            "picture",
            "person-away",
            "look",
            where_away,
            f"the presenter is off screen for {worst_away:.0f} s up to here; the longest absence seen is {N['person_away_seconds']} s",
        )
    if not off and not seen_person and sum(counts.values()) > 0:
        r.add("picture", "never-seen", "look", "plan", "the presenter is on but never on screen")
    total = sum(counts.values())
    if not off and total:
        theme = layouts.theme_of(plan)
        dist = sum(abs(counts[k] / total - theme["shares"][k]) for k in counts) / 2
        if dist > N["frame_share_distance"]:
            have = " / ".join(
                str(round(100 * counts[k] / total)) for k in ("person", "both", "content")
            )
            want = " / ".join(
                str(round(100 * theme["shares"][k])) for k in ("person", "both", "content")
            )
            r.add(
                "picture",
                "frame-share",
                "look",
                "plan",
                f"person / both / content is {have} by words; the theme {theme['id']} runs {want}. Say `wants` on the frames that should be the person's, or drop pictures that are not needed",
            )


def check_design(plan: Row, r: Report) -> None:
    transitions: dict[str, int] = {}
    for _ch, b in beats_of(plan):
        for f in b.get("frames", []):
            vo = f.get("vo", "")
            vt = [t.lower() for t in toks(vo)]
            w = len(vt)
            own = {o["id"]: o for o in f.get("objects", [])}
            objs = {o["id"]: o for o in f.get("_held", [])}
            objs.update(own)
            cues = f.get("cues", [])
            if f.get("transition") and f["transition"] != "none":
                transitions[f["transition"]] = transitions.get(f["transition"], 0) + 1
            if not f.get("presence"):
                continue
            if not f.get("_designed"):
                r.add(
                    "picture",
                    "unclassified",
                    "must",
                    f["id"],
                    "this frame's design has not been read for its current words: run classify.py design",
                )
                continue
            if f.get("presence") == "person":
                if f.get("shows") or any(
                    OBJ.get(o.get("type"), {}).get("family") != "on the person"
                    for o in own.values()
                ):
                    level = "must" if f.get("override") else "look"
                    why = (
                        "a person picked the person alone for this frame"
                        if f.get("override")
                        else "the frame reads as the person alone"
                    )
                    r.add(
                        "picture",
                        "picture-on-person",
                        level,
                        f["id"],
                        f"{why}, but it still carries a picture; keep one overlay at most (a name, a term, a link) and move what must be seen to a neighbouring frame, or set the frame's `wants` to both",
                    )
                continue
            if f.get("hold") and not f.get("shows") and not own and not cues:
                continue  # the picture before simply stays
            if not f.get("shows") and not f.get("hold"):
                why = " (a person moved this line off the presenter)" if f.get("override") else ""
                r.add(
                    "picture",
                    "needs-picture",
                    "must",
                    f["id"],
                    f"the frame shows content but `shows` is empty{why}: write its picture, or set `hold` to keep the picture before",
                )
                continue
            recorded = f.get("picture") in (
                "terminal",
                "product-screen",
                "document",
                "product-output",
            )
            if not recorded and not f.get("hold") and not own:
                r.add(
                    "picture",
                    "needs-objects",
                    "must",
                    f["id"],
                    "a built picture needs its objects listed",
                )
                continue
            if any("type" not in o for o in own.values()) or any("move" not in c for c in cues):
                r.add(
                    "picture",
                    "unclassified",
                    "must",
                    f["id"],
                    "an object or a cue here has no label for its current words: run classify.py design",
                )
                continue
            if own and not recorded and not f.get("hold"):
                if not f.get("focal"):
                    r.add(
                        "motion",
                        "focal",
                        "must",
                        f["id"],
                        "name the one object the eye follows in `focal`",
                    )
                elif f["focal"] not in objs:
                    r.add(
                        "motion",
                        "focal",
                        "must",
                        f["id"],
                        f"`focal` {f['focal']} is not one of the frame's objects",
                    )
            for o in own.values():
                ow = toks(o.get("words", ""))
                if len(ow) > 6:
                    r.add(
                        "motion",
                        "screen-words",
                        "look",
                        f["id"],
                        f"{o['id']} puts {len(ow)} words on screen; six is the rule, and never the spoken sentence",
                    )
            pos = []
            for i, c in enumerate(cues):
                at = [t.lower() for t in toks(c.get("at", ""))]
                p = (
                    next(
                        (k for k in range(len(vt) - len(at) + 1) if vt[k : k + len(at)] == at), None
                    )
                    if at
                    else None
                )
                if p is None:
                    r.add(
                        "motion",
                        "cue-word",
                        "must",
                        f["id"],
                        f"cue {i + 1} lands on “{c.get('at', '')}”, which is not in the frame's words",
                    )
                else:
                    pos.append(p)
                if c.get("object") and c["object"] not in objs:
                    r.add(
                        "motion",
                        "cue-object",
                        "must",
                        f["id"],
                        f"cue {i + 1} moves {c['object']}, which is not an object of this frame or of the picture it holds",
                    )
            if len(pos) != len(cues):
                continue
            where = f"cues land at words {', '.join(str(p + 1) for p in pos)} of {w} ({', '.join(f'{p / WPS:.1f}' for p in pos)} s of {w / WPS:.1f} s)"
            if pos != sorted(pos):
                r.add(
                    "motion",
                    "cue-order",
                    "must",
                    f["id"],
                    f"the cues are not in the order their words are said: {where}",
                )
            if len(cues) > N["cues_per_frame_most"]:
                r.add(
                    "motion",
                    "cue-count",
                    "look",
                    f["id"],
                    f"{len(cues)} cues in one frame; nine is the most a viewer follows",
                )
            want = N["cues_per_beat"].get(b.get("subtype"), 2)
            if w >= 18 and len(cues) < min(2, want) and not recorded and not f.get("hold"):
                r.add(
                    "motion",
                    "slide",
                    "must",
                    f["id"],
                    f"{w} words over a built picture with {len(cues)} cue; a {b.get('subtype')} beat usually gets {want}. A picture that arrives whole and waits is a slide",
                )
            if (
                len(cues) >= 4
                and f.get("picture") not in BUILDS
                and {c.get("move") for c in cues} <= {"reveal"}
            ):
                r.add(
                    "motion",
                    "all-entrances",
                    "look",
                    f["id"],
                    "every cue is a reveal; let something already on screen change state, be pointed at or travel",
                )
            early = sum(1 for p in pos if p < 0.25 * w)
            if len(cues) >= 5 and early > max(2, len(pos) / 3):
                r.add(
                    "motion",
                    "front-loaded",
                    "look",
                    f["id"],
                    f"{early} of {len(pos)} cues land in the first quarter of the words; {where}",
                )
            close = [
                i + 1
                for i, (a, b2) in enumerate(zip(pos, pos[1:], strict=False))
                if (b2 - a) / WPS < N["cue_gap_seconds"][0]
            ]
            if close:
                r.add(
                    "motion",
                    "cue-pace",
                    "look",
                    f["id"],
                    f"cues {', '.join(f'{i} and {i + 1}' for i in close[:4])} are under {N['cue_gap_seconds'][0]} s apart; a presenter advances each cue by hand, so make them one cue that lands as a group. {where}",
                )
            if pos and w:
                gap_words = max(
                    [pos[0]] + [b2 - a for a, b2 in zip(pos, pos[1:], strict=False)] + [w - pos[-1]]
                )
                if gap_words / WPS > N["cue_gap_seconds"][1] + 4 and not recorded:
                    r.add(
                        "motion",
                        "dead-air",
                        "look",
                        f["id"],
                        f"{gap_words / WPS:.0f} s of voice with nothing changing on a built picture; {where}",
                    )
    if len(transitions) > N["transition_types_most"]:
        r.add(
            "motion",
            "transition-types",
            "look",
            "plan",
            f"{len(transitions)} kinds of transition; two or three is the rule: {transitions}",
        )


def cue_table(plan: Row) -> list[str]:
    """Where every cue lands: word, second, the gap to the cue before, the still time left."""
    rows = []
    for _ch, b in beats_of(plan):
        for f in b.get("frames", []):
            cues = f.get("cues", [])
            if not cues:
                continue
            vt = [t.lower() for t in toks(f.get("vo", ""))]
            parts, last = [], None
            for c in cues:
                at = [t.lower() for t in toks(c.get("at", ""))]
                p = (
                    next(
                        (k for k in range(len(vt) - len(at) + 1) if vt[k : k + len(at)] == at), None
                    )
                    if at
                    else None
                )
                if p is None:
                    parts.append(f"“{c.get('at', '')}” not in the words")
                    continue
                gap = "" if last is None else f" +{(p - last) / WPS:.1f}s"
                parts.append(f"{c.get('at', '')} w{p + 1} {p / WPS:.1f}s{gap} {c.get('move', '?')}")
                last = p
            still = f"{(len(vt) - last) / WPS:.1f}s still" if last is not None else ""
            rows.append(
                f" {f['id']} ({len(vt)} words, {len(vt) / WPS:.1f}s{', holds' if f.get('hold') else ''}): "
                + " | ".join(parts)
                + (f" | {still}" if still else "")
            )
    return rows


def check(plan: Row, stage: str = "all") -> list[Row]:
    """Every rule a merged, classified plan breaks at this stage: `must` rows mean the plan is
    not done, `look` rows are the writer's to weigh (and to waive, with a reason)."""
    r = Report(plan.get("waived"))
    ok = check_script(plan, r)
    if ok and stage in ("frames", "design", "all"):
        check_frames(plan, r)
    if ok and stage in ("design", "all"):
        check_design(plan, r)
    return r.rows


def musts(rows: list[Row]) -> list[Row]:
    return [x for x in rows if x["level"] == "must"]


def lines(rows: list[Row], stage: str, plan: Row | None = None) -> list[str]:
    """The check's findings as the writer reads them. With `plan`, also where every cue lands."""
    must = musts(rows)
    look = [x for x in rows if x["level"] == "look"]
    out = [f"check ({stage}): {len(must)} must fix, {len(look)} to look at"]
    for x in must + look:
        level = "MUST" if x["level"] == "must" else "look"
        out.append(f" {level} [{x['group']}/{x['rule']}] {x['where']}: {x['text']}")
    if plan is not None:
        out.append(
            "cues (a cue lands on the first word of its `at`, at its first occurrence in the frame):"
        )
        out.extend(cue_table(plan))
    return out
