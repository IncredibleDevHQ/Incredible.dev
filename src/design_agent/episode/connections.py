"""Bind relationships in a picture description to scene objects and their narration cues."""

from __future__ import annotations

import re
from collections import defaultdict
from itertools import pairwise
from typing import Any

Row = dict[str, Any]
_LINK = re.compile(
    r"\b(line|lines|arrow|connector|link(?:ed)?|message|reply|travels?|moves?|goes|comes out|runs|cross|connects?|flows?)\b",
    re.I,
)
_FROM = re.compile(r"\b(?:from|out of)\s+", re.I)
_TO = re.compile(r"\b(?:into|to|towards?)\s+", re.I)
_MESSAGE = re.compile(r"\b(?:message|reply)\b", re.I)
_PRINCIPAL = {"node", "lifeline", "container", "interface-mock", "icon-label", "card"}
_GENERIC = {
    "left",
    "right",
    "middle",
    "file",
    "chip",
    "line",
    "arrow",
    "node",
    "step",
    "card",
    "header",
    "tag",
    "label",
    "callout",
    "other",
    "next",
    "first",
    "top",
    "bottom",
    "one",
    "it",
    "them",
}
_WORD = re.compile(r"[\w]+(?:[.\-][\w]+)*")


def _words(text: str) -> str:
    return " ".join(_WORD.findall(text.casefold()))


def _aliases(obj: Row) -> set[str]:
    label = str(obj.get("words") or "")
    parts = [_words(p) for p in re.split(r"[·|]", label)]
    desc = re.sub(r"^(?:an?|the)\s+", "", str(obj.get("what") or "").lower())
    head = _words(
        re.split(r"[,;]|\b(?:with|inside|holding|linked|in|on|under|between|to)\b", desc)[0]
    )
    names = {str(obj["id"]).casefold(), *parts}
    if head:
        names.add(head)
        core = head.removesuffix(" card").removesuffix(" node").removesuffix(" lifeline")
        names.add(core)
        if core and core != head:
            names.add(core.split()[-1])
        names.add(head.split()[0])
    for part in parts:
        if part:
            names.add(part.split()[-1])
    return {n for n in names if n and n not in _GENERIC}


def resolve(frames: list[Row]) -> list[Row]:
    records = [
        (frame, obj) for frame in frames for obj in frame.get("objects", []) if obj.get("id")
    ]
    objects = {obj["id"]: obj for _, obj in records}
    aliases: dict[str, set[str]] = defaultdict(set)
    main = []
    for key, obj in objects.items():
        if (
            obj.get("from")
            or obj.get("to")
            or _MESSAGE.search(str(obj.get("what", "")))
            or obj.get("type") in ("connector", "cross")
        ):
            continue
        for name in _aliases(obj):
            aliases[name].add(key)
        if obj.get("type") in _PRINCIPAL:
            main.append(key)
    unique = {name: next(iter(ids)) for name, ids in aliases.items() if len(ids) == 1}
    # A participant's printed name outranks incidental mentions in other descriptions.
    printed: dict[str, set[str]] = defaultdict(set)
    for name, ids in aliases.items():
        for key in ids:
            parts = [_words(p) for p in str(objects[key].get("words", "")).split("·")]
            if name in parts or any(p.endswith(" " + name) for p in parts):
                printed[name].add(key)
    unique.update({name: next(iter(ids)) for name, ids in printed.items() if len(ids) == 1})
    pattern = (
        re.compile(
            r"(?<![\w.\-])(?:"
            + "|".join(re.escape(s) for s in sorted(unique, key=len, reverse=True))
            + r")(?![\w.\-])"
        )
        if unique
        else None
    )

    def mentions(text: str) -> list[str]:
        return [unique[m[0]] for m in pattern.finditer(_words(text))] if pattern else []

    def endpoint(text: str, subject: str) -> str:
        phrase = re.split(
            r"[,;]|\b(?:and|with|beside|below|above|along|off)\b", text, maxsplit=1, flags=re.I
        )[0]
        named = re.match(r"^(?:the |an? |its )", phrase.strip(), re.I)
        phrase = re.sub(r"^(?:the |an? |its )", "", phrase.strip(), flags=re.I)
        if re.match(r"^(?:it|itself)\b", phrase, re.I):
            return subject
        if matched := mentions(phrase):
            return matched[0]
        # A named participant in the prose can lack its own box in older scene files.
        noun = re.match(
            r"^([A-Za-z][\w.-]*)(?:\s+(?:box|node|lifeline))?(?:\s+(?:on|at|for|of)\b.*)?[.!? ]*$",
            phrase,
            re.I,
        )
        if (
            named
            and noun
            and noun[1].casefold() not in _GENERIC
            and noun[1].casefold() not in aliases
        ):
            return noun[1].capitalize()
        return ""

    result: list[Row] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add(
        src: str,
        dst: str,
        obj: Row,
        frame: Row,
        cue: str,
        *,
        label: str = "",
        blocked: bool = False,
    ) -> None:
        identity = (src, dst, label, obj["id"] if label else "")
        if not src or not dst or src == dst or identity in seen:
            return
        seen.add(identity)
        result.append(
            {
                "from": src,
                "to": dst,
                "object": obj["id"],
                "frame": cue.partition("/")[0] if cue else frame["id"],
                "cue": cue,
                "label": label,
                "blocked": blocked,
            }
        )

    by_object: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for frame in frames:
        for i, cue_row in enumerate(frame.get("cues", [])):
            by_object[cue_row.get("object", "")].append(
                (f"{frame['id']}/{i}", cue_row.get("does", ""))
            )
    for frame, obj in records:
        key = obj["id"]
        cues = by_object[key]
        first = cues[0][0] if cues else ""
        what = str(obj.get("what") or "")
        blocked = obj.get("type") == "cross" or bool(
            re.search(
                r"\b(blocked|crossed|no request|no way in)\b",
                what + " " + str(obj.get("words", "")),
                re.I,
            )
        )
        message = bool(_MESSAGE.search(what)) or obj.get("type") in ("cross", "connector")
        label = str(obj.get("words") or "") if message else ""
        if obj.get("from") and obj.get("to"):

            def explicit(value: str) -> str:
                return value if value in objects else unique.get(_words(value), value)

            add(
                explicit(str(obj["from"])),
                explicit(str(obj["to"])),
                obj,
                frame,
                first,
                label=str(obj.get("words") or ""),
                blocked=blocked,
            )
            continue
        # Prefer the cue wording; the object description often explains the same connection.
        for cue, text in [*cues, (first, what)]:
            if not _LINK.search(text):
                continue
            source = _FROM.search(text)
            target = _TO.search(text, source.end() if source else 0)
            if source:
                src = endpoint(text[source.end() : target.start() if target else None], key)
            else:
                src = ""
            dst = endpoint(text[target.end() :], key) if target else ""
            if not src and target:
                before = mentions(text[: target.start()])
                src = before[-1] if before else ""
            if not src and not message:
                src = key
            if (
                source
                and not dst
                and (group := re.search(r"lands.*?on each ([\w -]+)", text, re.I))
            ):
                noun = _words(group[1]).strip()
                containers = {
                    endpoint(loc.group(1), key)
                    for member in objects.values()
                    if noun
                    and noun in _words(str(member.get("what", "")))
                    and (loc := re.search(r"\binside (.+)", str(member.get("what", "")), re.I))
                } - {""}
                if len(containers) == 1:
                    add(src, containers.pop(), obj, frame, cue, label=str(obj.get("words", "")))
                    continue
            if not dst and source and not message:
                dst = key
            if blocked and len(main) == 2:
                if src in main and not dst:
                    dst = next(k for k in main if k != src)
                if dst in main and not src:
                    src = next(k for k in main if k != dst)
            if not source and re.search(r"\bline from\b", what, re.I) and not message:
                continue
            if src and dst:
                add(src, dst, obj, frame, cue, label=label, blocked=blocked)

    # An explicitly ordered pipeline supplies consecutive endpoints even when an individual
    # cue names only its destination. Never treat ordinary screen placement as a pipeline.
    for frame in frames:
        shows = str(frame.get("shows") or "")
        if not re.search(r"\bpipeline\b", shows, re.I) or not re.search(
            r"left to right|goes into|flows? (?:from|to)|→", shows, re.I
        ):
            continue
        ordered = list(
            dict.fromkeys(
                k for k in mentions(shows) if objects[k].get("type") in _PRINCIPAL | {"chip"}
            )
        )
        for src, dst in pairwise(ordered):
            if any(e["from"] == src and e["to"] == dst for e in result):
                continue
            cue = next(
                (
                    f"{frame['id']}/{i}"
                    for i, c in enumerate(frame.get("cues", []))
                    if c.get("object") == dst
                ),
                "",
            )
            add(src, dst, objects[dst], frame, cue)
    if not result:
        # Older briefs can describe a transfer only in the scene caption.
        for frame in frames:
            for clause in re.split(r"[;!?]|\.(?:\s|$)", str(frame.get("shows") or "")):
                via = re.search(
                    r"\b(?:sends?|returns?|forwards?|flows?|travels?|goes|connects?)\b|→",
                    clause,
                    re.I,
                )
                if not via:
                    continue
                start = _FROM.search(clause, via.end())
                end = _TO.search(clause, start.end() if start else via.end())
                if via[0] != "→" and not end:
                    continue
                left = clause[start.end() : end.start()] if start and end else clause[: via.start()]
                right = clause[end.end() if end else via.end() :]
                srcs, dsts = set(mentions(left)), set(mentions(right))
                if len(srcs) == len(dsts) == 1:
                    src, dst = srcs.pop(), dsts.pop()
                    denied = bool(
                        re.search(
                            r"\b(?:never|cannot|blocked|no request|does not|doesn't)\b",
                            clause,
                            re.I,
                        )
                    )
                    add(src, dst, objects[dst], frame, "", blocked=denied)
    return result
