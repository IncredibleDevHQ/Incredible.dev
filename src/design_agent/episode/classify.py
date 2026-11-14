"""Labels a plan. Every categorical field is decided here by the classifier (Jev), from the
words the writer wrote. The writer never types a label.

usage: classify.py <plan.json> <stage> [--fresh]

stages
  material   what kind of material each item of the notes is, and the route they suggest
  script     chapter types, beat types and subtypes, hook, landing
  frames     who has the frame for each beat, and the layouts ranked
  design     picture, arrangement, object types, moves, how each frame follows the last
  all        the four above, in order

plan.json is never rewritten. Labels go to labels.json beside it, each tied to the words it
was read from: change a line and its label is dropped until you run this again. Only what
changed is asked again; --fresh asks everything (readings near a tie can then move a little).
The script prints what the writer has to look at.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from design_agent.episode import layouts
from design_agent.episode import plan as planio
from design_agent.episode import questions as Q
from design_agent.episode.classifier import Ask, ClassifierError
from design_agent.episode.plan import Row, beats_of, frames_of, toks

SURE = 0.8  # at or above this confidence a label stands without a second look
NEAR = 0.05  # a reading this close to the line can flip when it is asked again
TOP = 3  # an intent among the classifier's top three stands when the classifier is unsure
INTENT_LEAST = 0.05  # ...provided the classifier gave it at least this much

N = Q.TYPES["numbers"]
SUB = Q.table("beat_subtypes")
CHAP = Q.table("chapter_types")
REL = Q.table("relations")
OBJ = Q.table("object_types")
PERSON_OBJECTS = [o["id"] for o in Q.TYPES["object_types"] if o["family"] == "on the person"]
NO_ONE_QUESTION = ("introduction", "demo-first", "recap", "outro", "series")


def ask_many(jobs: Sequence[tuple[str, Any, Row]], ask: Ask) -> dict[str, Row]:
    """jobs: [(key, state, questions)] -> {key: answers}. A failed call is reported, not hidden.
    A reader that takes many items at once is given them together; one that answers a single
    item is asked six at a time."""
    if not jobs:
        return {}
    many = getattr(ask, "many", None)
    if many is not None:
        answered: dict[str, Row] = many(list(jobs))
        return answered

    def run(job: tuple[str, Any, Row]) -> tuple[str, Row]:
        key, state, qs = job
        try:
            return key, ask(state, qs)
        except ClassifierError as err:
            return key, {"error": str(err)}

    with ThreadPoolExecutor(6) as pool:
        return dict(pool.map(run, jobs))


def top(answer: Row, n: int = TOP) -> list[Row]:
    probs = sorted(answer["probabilities"].items(), key=lambda kv: -kv[1])
    return [{"id": k, "p": round(v, 2)} for k, v in probs[:n] if v > 0.004]


def settle(row: Row, allowed: Collection[str] | None = None) -> tuple[str | None, str]:
    """The classifier's first reading, unless it is unsure and the writer's intent is among its
    top three. Worked out again on every run, so changing `wants` needs no new reading."""
    reads = row.get("reads") or []
    if not reads:
        return None, "read"
    first, wants = reads[0]["id"], row.get("wants")
    if wants and wants != first and row.get("p", 1) < SURE:
        hit = next((r for r in reads if r["id"] == wants), None)
        if hit and hit["p"] >= INTENT_LEAST and (allowed is None or wants in allowed):
            return wants, "intent"
    return first, "read"


def first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", (text or "").strip())[0] if text else ""


def last_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", (text or "").strip())[-1] if text else ""


def budget(plan: Row) -> str:
    brief = plan.get("brief", {})
    seconds = float(brief.get("seconds") or 0)
    if not seconds:
        return "the brief has no `seconds` yet"
    marks = layouts.marks_seconds(plan)
    voice = seconds - marks
    target = round(voice * N["words_per_second"])
    have = sum(len(toks(b.get("says", ""))) for _, b in beats_of(plan))
    lo, hi = (
        round(target * (1 - N["length_tolerance"])),
        round(target * (1 + N["length_tolerance"])),
    )
    return (
        f"word budget: {seconds:.0f} s less {marks:.0f} s of cards, at {N['words_per_second']} words a second, "
        f"is {target} words ({lo} to {hi} passes); the script has {have}"
    )


# ---------------------------------------------------------------- material


def stage_material(plan: Row, out: list[str], fresh: bool, ask: Ask) -> None:
    brief = plan.setdefault("brief", {})
    items = plan.get("material", [])
    q = Q.choice(
        "This is one item from a set of raw notes for a technical explainer. What kind of material is it?",
        Q.options("material_kinds"),
    )
    todo = [m for m in items if fresh or "kind" not in m]
    jobs = [(m["id"], {"note": m.get("text", "")}, {"kind": q}) for m in todo]
    answers = ask_many(jobs, ask)
    for m in todo:
        a = answers[m["id"]]
        if "error" in a:
            out.append(f"{m['id']}: classifier error: {a['error']}")
            continue
        m["kind"], m["p"] = a["kind"]["choice"], round(a["kind"]["confidence"], 2)
    by_kind: dict[str, list[str]] = {}
    for m in items:
        by_kind.setdefault(m.get("kind", "?"), []).append(m["id"])
    for kind, ids in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        out.append(f"{kind} ({len(ids)}): {' '.join(ids)}")
    missing = [
        k["name"].lower()
        for k in Q.TYPES["material_kinds"]
        if k["id"] in ("definition", "mechanism") and k["id"] not in by_kind
    ]
    if missing:
        out.append(
            "the notes hold no "
            + " and no ".join(missing)
            + ": say so in your report, and do not invent one"
        )
    if brief.get("idea"):
        series = (brief.get("series") or "none") != "none"
        if fresh or "route" not in brief:
            notes = [f"{m.get('kind', '?')}: {m.get('text', '')[:140]}" for m in items][:60]
            a = ask_many(
                [
                    (
                        "route",
                        {"idea": brief.get("idea"), "gap": brief.get("gap", ""), "notes": notes},
                        {
                            "route": Q.choice(
                                "In what order should these notes be told as an explainer? Pick the route the material itself suggests.",
                                Q.options(
                                    "routes",
                                    [
                                        r["id"]
                                        for r in Q.TYPES["routes"]
                                        if series or r["id"] != "series"
                                    ],
                                ),
                            )
                        },
                    )
                ],
                ask,
            )["route"]
            if "error" not in a:
                brief["route"], brief["route_p"] = (
                    a["route"]["choice"],
                    round(a["route"]["confidence"], 2),
                )
        out.append(f"route: {brief.get('route')} ({brief.get('route_p')})")
        out.append(budget(plan))
    else:
        out.append("no route yet: write the brief's `idea`, then run this stage again")


# ---------------------------------------------------------------- script


def stage_script(plan: Row, out: list[str], fresh: bool, ask: Ask) -> None:
    brief = plan.setdefault("brief", {})
    idea = brief.get("idea", "")
    series = (brief.get("series") or "none") != "none"
    allowed_ch = [c["id"] for c in Q.TYPES["chapter_types"] if c["part"] != "series"]
    chapters = plan.get("chapters", [])
    beats = [b for _, b in beats_of(plan)]
    jobs = []
    for i, ch in enumerate(chapters):
        if fresh or "reads" not in ch:
            text = " ".join(b.get("says", "") for b in ch.get("beats", []))
            state = {
                "video_idea": idea,
                "all_chapter_questions_in_order": [c.get("question", "") for c in chapters],
                "chapter_number": i + 1,
                "chapter_question": ch.get("question", ""),
                "chapter_words": text,
            }
            jobs.append((ch["id"], state, Q.chapter_questions(allowed_ch, series)))
    sub_q = {"subtype": Q.beat_questions()["subtype"]}
    for i, (ch, b) in enumerate(beats_of(plan)):
        if not fresh and "reads" in b:
            continue
        place = (
            "the first passage of the video"
            if i == 0
            else "among the last passages of the video"
            if i >= len(beats) - 3
            else "the middle of the video"
        )
        before = last_sentence(beats[i - 1].get("says", "")) if i else ""
        after = first_sentence(beats[i + 1].get("says", "")) if i + 1 < len(beats) else ""
        jobs.append(
            (
                b["id"],
                Q.beat_state(idea, ch.get("question", ""), before, b.get("says", ""), after, place),
                sub_q,
            )
        )
    answers = ask_many(jobs, ask)

    for ch in chapters:
        a = answers.get(ch["id"])
        if a is not None and "error" in a:
            out.append(f"{ch['id']}: classifier error: {a['error']}")
            continue
        if a is not None:
            ch["p"], ch["reads"] = round(a["type"]["confidence"], 2), top(a["type"])
            ch["one_question"] = round(a["one_question"]["noul"], 2)
            ch["episode"] = round(a["episode"]["noul"], 2) if "episode" in a else 0.0
        if not ch.get("reads"):
            continue
        frames_the_video = (
            ch["reads"][0]["id"] in ("introduction", "demo-first", "recap", "outro")
            and ch.get("wants") != "series"
        )
        if (
            series
            and not frames_the_video
            and (
                ch.get("episode", 0) >= 0.5
                or (ch.get("wants") == "series" and ch.get("episode", 0) >= 0.25)
            )
        ):
            ch["type"], ch["by"] = "series", "read" if ch.get("episode", 0) >= 0.5 else "intent"
        else:
            ch["type"], ch["by"] = settle(ch, allowed_ch)
        ch["part"] = CHAP[ch["type"]]["part"]
        reads = ", ".join(f"{r['id']} {r['p']}" for r in ch["reads"])
        note = ""
        if ch.get("wants") and ch["wants"] != ch["type"]:
            note = f"  <- you wanted {ch['wants']}: change the question or the beats, or set wants to {ch['type']}"
        elif ch["by"] == "intent":
            note = "  <- kept by your intent; the classifier was unsure"
        elif abs(ch["p"] - SURE) < NEAR and ch.get("wants") and ch["reads"][0]["id"] != ch["wants"]:
            note = "  <- near the line: asked again, this could flip"
        one = "" if ch["type"] in NO_ONE_QUESTION else f" · one question {ch['one_question']}"
        out.append(f"{ch['id']} {ch['type']} ({reads}){one}{note}")

    flagged = 0
    for _ch, b in beats_of(plan):
        a = answers.get(b["id"])
        if a is not None and "error" in a:
            out.append(f"{b['id']}: classifier error: {a['error']}")
            continue
        if a is not None:
            b["p"], b["reads"] = round(a["subtype"]["confidence"], 2), top(a["subtype"])
        if not b.get("reads"):
            continue
        b["subtype"], b["by"] = settle(b)
        b["type"] = SUB[b["subtype"]]["type"]
        if b.get("wants") and b["wants"] != b["subtype"]:
            rest = ", ".join(f"{r['id']} {r['p']}" for r in b["reads"])
            out.append(
                f"{b['id']}: you wanted {b['wants']}; it reads {rest}. Rewrite the words so the job is plain, or set wants to {b['subtype']}."
            )
            flagged += 1
        elif b["by"] == "intent":
            out.append(
                f"{b['id']}: unsure ({', '.join(str(r['id']) + ' ' + str(r['p']) for r in b['reads'])}); kept your {b['subtype']}."
            )
    if not flagged:
        out.append(
            "every beat reads as the job you meant, or was kept by your intent where the classifier was unsure"
        )

    if beats:
        first = beats[0].get("says", "")
        land = [b for b in beats if b.get("subtype") == "landing"]
        jobs = [
            (
                "hook",
                {"first_lines": first},
                {
                    "hook": Q.choice(
                        "How does this explainer earn its first ten seconds?", Q.options("hooks")
                    )
                },
            )
        ]
        if land:
            jobs.append(
                (
                    "landing",
                    {
                        "opening_lines": first,
                        "carried_example": (brief.get("case") or {}).get("text", ""),
                        "landing_line": land[-1].get("says", ""),
                    },
                    {
                        "landing": Q.choice(
                            "How does the landing line bring the idea home?",
                            Q.options(
                                "landings",
                                [x["id"] for x in Q.TYPES["landings"] if x["id"] != "none"],
                            ),
                        )
                    },
                )
            )
        ans = ask_many(jobs, ask)
        if "error" not in ans["hook"]:
            brief["hook"] = ans["hook"]["hook"]["choice"]
        brief["landing"] = (
            ans["landing"]["landing"]["choice"]
            if land and "error" not in ans.get("landing", {"error": 1})
            else "none"
        )
    out.append(f"hook {brief.get('hook')} · landing {brief.get('landing')}")
    out.append(budget(plan))


# ---------------------------------------------------------------- frames


def stage_frames(plan: Row, out: list[str], fresh: bool, ask: Ask) -> None:
    off = plan.get("brief", {}).get("presenter", "on") == "off"
    jobs = []
    if not off:
        for _ch, b, f in frames_of(plan):
            if not fresh and f.get("presence_p"):
                continue
            sub = SUB.get(str(b.get("subtype")))
            state = {
                "video": {
                    "kind": "a technical concept explainer",
                    "presenter": "one person on camera",
                },
                "job_of_the_passage": f"{sub['name']}: {sub['reads_as']}" if sub else "",
                "PASSAGE": f.get("vo", ""),
                "what_the_writer_wants_shown": f.get("shows", ""),
            }
            jobs.append((f["id"], state, Q.presence_questions()))
    answers = ask_many(jobs, ask)
    for _ch, _b, f in frames_of(plan):
        a = answers.get(f["id"])
        if a is None:
            continue
        if "error" in a:
            out.append(f"{f['id']}: classifier error: {a['error']}")
            continue
        f["presence_p"] = {k: round(v, 2) for k, v in a["presence"]["probabilities"].items()}
    layouts.settle_frames(plan)
    planio.inherit_holds(plan)
    theme = layouts.theme_of(plan)
    counts = {"person": 0, "both": 0, "content": 0}
    for ch in plan.get("chapters", []):
        row = []
        for b in ch.get("beats", []):
            for f in b.get("frames", []):
                w = len(toks(f.get("vo", "")))
                if f.get("presence") in counts:
                    counts[f["presence"]] += w
                pj = (f.get("presence_p") or {}).get("person", 0)
                mark = (
                    "person"
                    if f.get("presence") == "person"
                    else "holds"
                    if f.get("hold")
                    else f.get("presence", "?") + ("" if f.get("shows") else " NEEDS A PICTURE")
                )
                if f.get("override"):
                    mark += " (a person's pick)"
                elif f.get("by") == "intent":
                    mark += " (your intent)"
                elif f.get("by") == "overruled":
                    got = (f.get("presence_p") or {}).get(f.get("wants"), 0)
                    mark += f" (you wanted {f.get('wants')}; the line reads {got} for it, under the {N['intent_presence']} an intent needs: reword the line, or write `shows`)"
                row.append(
                    f"{f['id'].replace(ch['id'] + '.', '')} {b.get('subtype', '?')} {w}w p{pj}: {mark}"
                )
        out.append(f"{ch['id']}: " + " | ".join(row))
    total = sum(counts.values()) or 1
    share = {k: round(100 * v / total) for k, v in counts.items()}
    ts = theme["shares"]
    out.append(
        f"who has the frame, by words: person {share['person']}%, both {share['both']}%, content {share['content']}% "
        f"(the theme {theme['id']} runs {round(100 * ts['person'])} / {round(100 * ts['both'])} / {round(100 * ts['content'])})"
    )
    out.append(
        f"a line goes to the person when it reads p{theme.get('person_from', 0.5)} or more for the person, or when the frame's `wants` says so; "
        f"a line that reads p{N['line_only_person']} or more and shows nothing holds the picture before"
    )


# ---------------------------------------------------------------- design


def stage_design(plan: Row, out: list[str], fresh: bool, ask: Ask) -> None:
    jobs: list[tuple[str, Any, Row]] = []
    order: list[tuple[Row, Row | None]] = []
    prev: Row | None = None
    for _ch, _b, f in frames_of(plan):
        order.append((f, prev))
        if fresh or not f.get("_designed"):
            qs = {}
            state = {
                "PASSAGE": f.get("vo", ""),
                "on_screen": f.get("shows", "") or f.get("_shows_held", ""),
            }
            shows_own = f.get("presence") != "person" and f.get("shows")
            if shows_own and not f.get("hold"):
                qs["picture"] = Q.choice(
                    "What kind of picture fills this frame? Judge from on_screen.",
                    Q.options(
                        "picture_types",
                        [p["id"] for p in Q.TYPES["picture_types"] if p["group"] != "person"],
                    ),
                )
                qs["arrangement"] = Q.choice(
                    "How are the things in this picture arranged? Judge from on_screen.",
                    Q.options("arrangements"),
                )
            if (
                prev is not None
                and not f.get("hold")
                and not (prev.get("presence") == "person" and f.get("presence") == "person")
            ):
                state["frame_before"] = {
                    "said": prev.get("vo", "")[-220:],
                    "on_screen": prev.get("shows", "")
                    or prev.get("_shows_held", "")
                    or "the presenter, to camera",
                }
                state["this_frame"] = {
                    "on_screen": f.get("shows", "") or "the presenter, to camera"
                }
                qs["relation"] = Q.choice(
                    "How does this frame follow the frame before it?",
                    Q.options(
                        "relations",
                        [r["id"] for r in Q.TYPES["relations"] if r["id"] != "same-picture"],
                    ),
                )
            allowed = (
                PERSON_OBJECTS
                if f.get("presence") == "person"
                else [o["id"] for o in Q.TYPES["object_types"] if o["id"] not in PERSON_OBJECTS]
            )
            for o in f.get("objects", []):
                state.setdefault("objects", {})[o["id"]] = {
                    "description": o.get("what", ""),
                    "text_on_it": o.get("words", ""),
                }
                qs["obj_" + o["id"]] = Q.choice(
                    f"What kind of on-screen object is `{o['id']}`? Judge from its description.",
                    {t: f"{OBJ[t]['name']} ({OBJ[t]['family']})" for t in allowed},
                )
            for i, c in enumerate(f.get("cues", [])):
                state.setdefault("cues", {})[str(i)] = {
                    "at_the_word": c.get("at", ""),
                    "object": c.get("object", ""),
                    "what_happens": c.get("does", ""),
                }
                qs[f"cue_{i}"] = Q.choice(
                    f"What kind of move is cue {i}? Judge from what_happens.", Q.options("moves")
                )
            jobs.append((f["id"], state, qs))
        prev = f
    answers = ask_many([j for j in jobs if j[2]], ask)
    moves: dict[str, int] = {}
    unsure: list[str] = []
    for f, prev in order:
        a = answers.get(f["id"])
        if a is not None and "error" in a:
            out.append(f"{f['id']}: classifier error: {a['error']}")
            continue
        asked = any(j[0] == f["id"] for j in jobs)
        if asked:
            a = a or {}
            if "picture" in a:
                f["picture"], f["picture_p"] = (
                    a["picture"]["choice"],
                    round(a["picture"]["confidence"], 2),
                )
                f["arrangement"] = a["arrangement"]["choice"]
            if prev is None:
                f["relation"], f["transition"] = "new-topic", "none"
            elif f.get("hold") or (
                prev.get("presence") == "person" and f.get("presence") == "person"
            ):
                f["relation"], f["transition"] = (
                    "same-picture",
                    "none",
                )  # the picture, or the person, stays
            elif "relation" in a:
                rel = a["relation"]["choice"]
                if prev.get("presence") != f.get("presence") and "person" in (
                    prev.get("presence"),
                    f.get("presence"),
                ):
                    rel = "swap"  # the person and the content change places: a cut, never a move into a talking head
                f["relation"], f["transition"] = rel, REL[rel]["transition"]
            for o in f.get("objects", []):
                ans = a.get("obj_" + o["id"])
                if ans:
                    o["type"], o["p"] = ans["choice"], round(ans["confidence"], 2)
                    if o["p"] < 0.5:
                        unsure.append(f"{f['id']} {o['id']} {o['type']} {o['p']}")
            for i, c in enumerate(f.get("cues", [])):
                ans = a.get(f"cue_{i}")
                if ans:
                    c["move"], c["p"] = ans["choice"], round(ans["confidence"], 2)
        if f.get("presence"):
            f["_designed"] = True
        if f.get("presence") == "person" and "picture" not in f:
            f["picture"] = "camera-and-type" if f.get("objects") else "camera"
        for c in f.get("cues", []):
            if c.get("move"):
                moves[c["move"]] = moves.get(c["move"], 0) + 1
    planio.inherit_holds(plan)
    out.append(
        "moves: "
        + (", ".join(f"{k} {v}" for k, v in sorted(moves.items(), key=lambda kv: -kv[1])) or "none")
    )
    trans: dict[str, int] = {}
    for f, _ in order:
        if f.get("transition"):
            trans[f["transition"]] = trans.get(f["transition"], 0) + 1
    out.append(
        "transitions: "
        + ", ".join(f"{k} {v}" for k, v in sorted(trans.items(), key=lambda kv: -kv[1]))
    )
    if unsure:
        out.append(
            "objects the classifier was unsure of (describe them more plainly if the type is wrong): "
            + "; ".join(unsure[:14])
        )


STAGES: dict[str, Callable[[Row, list[str], bool, Ask], None]] = {
    "material": stage_material,
    "script": stage_script,
    "frames": stage_frames,
    "design": stage_design,
}


def classify(plan: Row, stage: str, ask: Ask, *, fresh: bool = False) -> list[str]:
    """Label one stage of a merged plan (`plan.merged`) in place and return what the writer has
    to look at. `all` runs the four stages in order. The caller keeps `plan.labels_of(plan)`."""
    out: list[str] = []
    for name in STAGES if stage == "all" else [stage]:
        STAGES[name](plan, out, fresh, ask)
    return out
