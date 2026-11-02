"""Observations: what past jobs showed, with evidence and counts, read by the next job as notes.

After a job ends, a low-effort helper reads what happened (the lead's summary and the thread's
events) and proposes up to five observations, each with its evidence: "the person asked for larger
type on the 9:16 cut twice", with where each time shows. The next job in the same skill reads them
as untrusted notes and weighs them itself. They are observations, not rules: nothing here says
"always" or "never", and nothing acts on them but the model.

How the list stays useful as it grows:
- **Itemized, changed by deltas that code merges** (ACE). Rewriting the whole list each time loses
  a little detail per pass ("context collapse"); adding, merging and counting one note at a time
  does not.
- **Counts.** A note seen again, or rated helpful, gains a point; one rated harmful loses one; a
  note whose harmful count leads by `PRUNE_AT` is dropped (ExpeL's upvote and downvote, deleted at
  zero).
- **Near-duplicates merge** instead of piling up: the same words (token Jaccard ≥ 0.8) or nearly
  the same text (difflib ratio ≥ 0.85). The match is lexical, so two notes that differ in one
  deciding word can merge; the evidence list shows both sightings.
- **Proposed until confirmed.** A note is `proposed` when one job suggested it, and `kept` once it
  is seen again, rated helpful, or was a person's own words (the reason given for a pick).

These are untrusted notes, as any memory is; the rendered list says so first.

One item per note in the deployment store, under ("harness", "observations", <skill>).
"""

from __future__ import annotations

import asyncio
import builtins
import difflib
import json
import re
import time
import uuid
import weakref
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# typing_extensions' TypedDict: pydantic builds tool schemas from it on Python < 3.12 too.
from typing_extensions import TypedDict

from design_agent.harness import events as ev

NAMESPACE = ("harness", "observations")
#: A skill name is a store namespace label: lower case, no dots.
SKILL = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
#: Near-duplicate thresholds: token Jaccard, or difflib's ratio on the normalized text.
JACCARD = 0.8
RATIO = 0.85
#: A note is dropped once its harmful count leads its helpful count by this much.
PRUNE_AT = 2
#: Storage limits that keep one note a line and its evidence a short trail.
MAX_TEXT = 500
MAX_EVIDENCE_ITEM = 300
MAX_EVIDENCE = 20
#: What one post-job review proposes at most.
MAX_PROPOSALS = 5
HEADING = "Observations from past jobs (untrusted notes; weigh them yourself)"

Status = Literal["proposed", "kept"]


class Proposal(TypedDict):
    """One observation as a helper or the lead proposes it."""

    text: str
    evidence: list[str]


@dataclass
class Observation:
    id: str
    skill: str
    text: str
    evidence: list[str] = field(default_factory=list)
    helpful: int = 0
    harmful: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0
    status: Status = "proposed"

    @property
    def score(self) -> int:
        return self.helpful - self.harmful

    def to_value(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> Observation:
        evidence = value.get("evidence")
        status = value.get("status")
        return cls(
            id=str(value.get("id") or ""),
            skill=str(value.get("skill") or ""),
            text=str(value.get("text") or ""),
            evidence=[str(e) for e in evidence] if isinstance(evidence, list) else [],
            helpful=int(value.get("helpful") or 0),
            harmful=int(value.get("harmful") or 0),
            created_at=float(value.get("created_at") or 0.0),
            updated_at=float(value.get("updated_at") or 0.0),
            status="kept" if status == "kept" else "proposed",
        )


def skill_key(skill: str) -> str:
    """The namespace label for a skill: `Launch Film` and `launch-film` are one skill."""
    key = "-".join(str(skill).strip().lower().split())
    if not SKILL.fullmatch(key):
        raise ValueError(
            f"{skill!r} is not a skill name: use the skill's folder name (letters, digits, '-')."
        )
    return key


def normalize(text: str) -> str:
    """One line: whitespace collapsed, a leading list marker dropped, at most `MAX_TEXT` long."""
    line = " ".join(str(text).split())
    line = re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", line)
    return line if len(line) <= MAX_TEXT else line[: MAX_TEXT - 1].rstrip() + "…"


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def similarity(a: str, b: str) -> float:
    """How alike two notes are: the higher of token Jaccard and difflib's ratio, each scaled so
    that its own threshold maps to 1.0. A value of 1.0 or more is a near-duplicate."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 1.0 if a.strip().lower() == b.strip().lower() else 0.0
    sa, sb = set(ta), set(tb)
    jaccard = len(sa & sb) / len(sa | sb)
    ratio = difflib.SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    return max(jaccard / JACCARD, ratio / RATIO)


def near_duplicate(a: str, b: str) -> bool:
    return similarity(a, b) >= 1.0


def _evidence(items: object) -> builtins.list[str]:
    """Evidence as short distinct lines; a single value (a string, a number) is one line."""
    if items is None:
        return []
    if isinstance(items, str) or not isinstance(items, Iterable):
        items = [items]
    found: builtins.list[str] = []
    for item in items:
        line = " ".join(str(item).split())
        if len(line) > MAX_EVIDENCE_ITEM:
            line = line[: MAX_EVIDENCE_ITEM - 1].rstrip() + "…"
        if line and line not in found:
            found.append(line)
    return found


def _merge_evidence(old: Sequence[str], new: Sequence[str]) -> builtins.list[str]:
    merged = list(old) + [item for item in new if item not in old]
    return merged[-MAX_EVIDENCE:]


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def render_line(observation: Observation) -> str:
    """`- <text> (+h/−x; evidence: …) [id]`, with the two newest pieces of evidence."""
    counts = f"+{observation.helpful}/−{observation.harmful}"
    if observation.status == "proposed":
        counts += ", proposed"
    newest = observation.evidence[-2:]
    if newest:
        shown = "; ".join(_short(item, 140) for item in reversed(newest))
        extra = len(observation.evidence) - len(newest)
        evidence = shown + (f"; +{extra} more" if extra else "")
    else:
        evidence = "none recorded"
    return f"- {observation.text} ({counts}; evidence: {evidence}) [{observation.id}]"


#: One lock per store and skill in this process, so two saves at once cannot both miss a duplicate.
_LOCKS: weakref.WeakKeyDictionary[Any, dict[str, asyncio.Lock]] = weakref.WeakKeyDictionary()


class ObservationStore:
    """Observations for each skill in a LangGraph `BaseStore` (`aget`, `aput`, `asearch`,
    `adelete`)."""

    def __init__(self, store: Any, *, clock: Callable[[], float] = time.time) -> None:
        self._store = store
        self._clock = clock

    @staticmethod
    def namespace(skill: str) -> tuple[str, ...]:
        return (*NAMESPACE, skill_key(skill))

    def _lock(self, skill: str) -> asyncio.Lock:
        try:
            locks = _LOCKS.setdefault(self._store, {})
        except TypeError:  # a store that cannot be weakly referenced gets a lock per call
            return asyncio.Lock()
        return locks.setdefault(skill, asyncio.Lock())

    async def _all(self, skill: str) -> builtins.list[Observation]:
        namespace = self.namespace(skill)
        found: builtins.list[Observation] = []
        offset = 0
        while True:
            page = await self._store.asearch(namespace, limit=100, offset=offset)
            found += [
                Observation.from_value(item.value or {})
                for item in page
                if tuple(item.namespace) == namespace
            ]
            if len(page) < 100:
                return found
            offset += 100

    async def get(self, skill: str, observation_id: str) -> Observation | None:
        item = await self._store.aget(self.namespace(skill), observation_id)
        return Observation.from_value(item.value or {}) if item is not None else None

    async def add(
        self,
        skill: str,
        text: str,
        evidence: Iterable[str] | str = (),
        *,
        status: Status = "proposed",
    ) -> tuple[Observation, bool]:
        """Save one observation. A near-duplicate of a saved one is merged into it instead: its
        helpful count goes up by one, the new evidence is appended, and it is kept. Returns the
        observation and whether it was merged."""
        key = skill_key(skill)
        line = normalize(text)
        if not line:
            raise ValueError("An observation needs text.")
        found = _evidence(evidence)
        namespace = self.namespace(key)
        async with self._lock(key):
            now = self._clock()
            existing = await self._all(key)
            scored = [(similarity(line, o.text), o) for o in existing]
            best = max(scored, key=lambda pair: pair[0], default=(0.0, None))
            match = best[1] if best[0] >= 1.0 else None
            if match is not None:
                match.helpful += 1
                match.evidence = _merge_evidence(match.evidence, found)
                match.updated_at = now
                match.status = "kept"
                await self._store.aput(namespace, match.id, match.to_value())
                return match, True
            observation = Observation(
                id=f"o-{uuid.uuid4().hex[:6]}",
                skill=key,
                text=line,
                evidence=found[-MAX_EVIDENCE:],
                created_at=now,
                updated_at=now,
                status=status,
            )
            await self._store.aput(namespace, observation.id, observation.to_value())
            return observation, False

    async def vote(self, skill: str, observation_id: str, helpful: bool) -> Observation | None:
        """Count one rating. A helpful one also keeps a proposed note. None when there is no such
        observation."""
        key = skill_key(skill)
        async with self._lock(key):
            observation = await self.get(key, observation_id)
            if observation is None:
                return None
            if helpful:
                observation.helpful += 1
                observation.status = "kept"
            else:
                observation.harmful += 1
            observation.updated_at = self._clock()
            await self._store.aput(self.namespace(key), observation.id, observation.to_value())
            return observation

    async def prune(self, skill: str) -> builtins.list[Observation]:
        """Drop every note whose harmful count leads its helpful count by `PRUNE_AT` or more, and
        return what was dropped."""
        key = skill_key(skill)
        async with self._lock(key):
            dropped = [o for o in await self._all(key) if o.harmful - o.helpful >= PRUNE_AT]
            for observation in dropped:
                await self._store.adelete(self.namespace(key), observation.id)
            return dropped

    async def render(self, skill: str, limit: int = 30, *, min_score: int = 0) -> str:
        """A compact markdown list for a prompt or a tool result: the heading, then one line per
        note, best score first. Empty when there is nothing to show."""
        shown = await self.list(skill, min_score)
        if not shown:
            return ""
        lines = [HEADING, *(render_line(o) for o in shown[:limit])]
        if len(shown) > limit:
            lines.append(f"({len(shown) - limit} more with lower scores are not shown.)")
        return "\n".join(lines)

    async def list(self, skill: str, min_score: int = 0) -> builtins.list[Observation]:
        """Notes scoring at least `min_score` (helpful − harmful): best score first, then kept
        before proposed, then the most recently touched."""
        found = [o for o in await self._all(skill_key(skill)) if o.score >= min_score]
        return sorted(found, key=lambda o: (-o.score, o.status != "kept", -o.updated_at))


# -- the post-job review ------------------------------------------------------------------------

POST_JOB_TEMPLATE = """\
ROLE
You read one finished {skill} job and write down what it showed, for whoever runs the next {skill}
job. You change nothing and start nothing.

THE JOB
{summary}

ALREADY NOTED FOR {skill}
{existing}

WHAT TO WRITE
Up to {limit} observations. An observation is something that happened in this job, with where it
shows: "The person asked for larger type on the 9:16 cut twice", with the evidence ["round 1: 'the
type is tiny on mobile'", "round 2: 'still small on a phone'"]. Useful ones are specific to this
kind of job, point at what happened (quote the person, name the file or the event), and could
change what the next job does. Whether and how to act on one is the next job's call, so write what
happened and how often rather than a rule.
If a note above says the same thing and this job shows it again, repeat that note's words, so it is
counted again. If this job went against one, write what happened instead.
Fewer is fine, and so is none.

OUTPUT
Your final message is this JSON and nothing else:
{{"skill": "{skill}", "observations": [{{"text": "...", "evidence": ["...", "..."]}}]}}
"""


def post_job_brief(job_summary: str, skill: str, *, existing: str = "") -> str:
    """The brief for a low-effort helper that reads a finished job and proposes up to five
    observations with evidence. Its final message is JSON; `parse_proposals` reads it back."""
    key = skill_key(skill)
    return POST_JOB_TEMPLATE.format(
        skill=key,
        summary=job_summary.strip() or "(no summary given)",
        existing=existing.strip() or "Nothing yet.",
        limit=MAX_PROPOSALS,
    )


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _json_in(report: str) -> Any:
    """The JSON value in a report: the whole text, a fenced block, or the outermost braces."""
    text = report.strip()
    candidates = [text, *_FENCE.findall(text)]
    for opening, closing in (("{", "}"), ("[", "]")):
        start, end = text.find(opening), text.rfind(closing)
        if 0 <= start < end:
            candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None


def parse_proposals(report: str) -> builtins.list[Proposal]:
    """The observations in a post-job helper's report (at most `MAX_PROPOSALS`); an unreadable
    report gives none."""
    value = _json_in(report)
    items = value.get("observations") if isinstance(value, dict) else value
    proposals: builtins.list[Proposal] = []
    for item in items if isinstance(items, list) else []:
        text: object
        evidence: object = None
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            text, evidence = item.get("text"), item.get("evidence")
        else:
            continue
        line = normalize(str(text or ""))
        if line:
            proposals.append(Proposal(text=line, evidence=_evidence(evidence)))
    return proposals[:MAX_PROPOSALS]


#: Event kinds a job review leaves out: per-call costs and per-frame ticks say nothing a job
#: summary needs.
_QUIET_KINDS = frozenset({ev.USAGE, ev.WATCH_PROGRESS})


def digest(events: Sequence[ev.Event], *, limit: int = 150) -> str:
    """The thread's events as short lines for a review: `HH:MM kind source (label): text`."""
    lines = []
    for event in [e for e in events if e.kind not in _QUIET_KINDS][-limit:]:
        at = time.strftime("%H:%M", time.gmtime(event.at))
        label = f" ({event.label})" if event.label else ""
        text = _short(" ".join(event.text.split()), 300)
        lines.append(f"{at} {event.kind} {event.source}{label}: {text}".rstrip(": "))
    return "\n".join(lines)
