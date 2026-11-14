"""Who reads an episode's words and says what they are: a typed classifier, never the writer.

Every categorical field in a plan (a chapter's type, a beat's job, who has the frame, the kind
of picture, the kind of move) is the answer to a typed question over a closed list. Two readers
can answer:

- Jev (TypeSafe's System One), when the deployment holds its key: it answers typed questions
  with probabilities and writes no text.
- A model, through whichever agent the episode runs on: it is given the same questions and must
  answer with the ids on the lists, which code then checks. Its confidence is its own estimate,
  so near-ties move more than Jev's do.

Both answer in one shape: a choice is `{"choice", "confidence", "probabilities"}`, a yes or no
is `{"noul": p}`.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

import httpx

Row = dict[str, Any]
#: A reader: the state it is shown, the questions about it, the answers by question id.
Ask = Callable[[Any, Row], Row]
#: Text in, text out: how a model reader reaches its model.
Complete = Callable[[str], str]
#: Many items read at once: `[(key, state, questions)]` to `{key: answers}`, a failed item as
#: `{"error": why}`. A reader that has this attribute (`many`) is asked in batches.
Job = tuple[str, Any, Row]
#: Items a model reader is shown in one prompt.
BATCH = 10

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
RETRY_STATUS = (429, 500, 502, 503, 529)


class ClassifierError(RuntimeError):
    """A question that got no usable answer."""


def jev(key: str, *, timeout: float = 60.0, tries: int = 6, transport: Any = None) -> Ask:
    """A reader backed by Jev. The key stays on the host: it is sent to Jev and nowhere else,
    and no error names it."""

    def ask(state: Any, questions: Row) -> Row:
        body = {"model": JEV_MODEL, "state": state, "questions": questions}
        delay = 1.5
        for attempt in range(tries):
            try:
                with httpx.Client(timeout=timeout, transport=transport) as client:
                    response = client.post(
                        JEV_URL, json=body, headers={"Authorization": f"Bearer {key}"}
                    )
            except httpx.HTTPError as error:
                if attempt < tries - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise ClassifierError(
                    f"the classifier could not be reached: {type(error).__name__}"
                ) from None
            if response.status_code in RETRY_STATUS and attempt < tries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            if response.status_code >= 400:
                raise ClassifierError(f"the classifier answered {response.status_code}")
            data = response.json()
            answers = data.get("answers", data)
            if not isinstance(answers, dict):
                raise ClassifierError("the classifier's answer was not a set of answers")
            return answers
        raise ClassifierError("the classifier gave no answer")

    return ask


MODEL_ASK = """You are a classifier. You are given a STATE and typed QUESTIONS about it.
Answer every question from the STATE alone. Write no prose.

- A question of type "choice" lists its options under "criteria", by id. Answer with the ids of
  the three options that fit best and how likely each is (numbers from 0 to 1 that sum to at
  most 1), most likely first.
- A question of type "noul" is a yes or no. Answer with how likely "true" is, from 0 to 1.

Reply with one JSON object and nothing else, shaped exactly like this:
{"<question id>": {"top": [["<option id>", 0.7], ["<option id>", 0.2]]}, "<question id>": {"yes": 0.9}}

STATE:
%s

QUESTIONS:
%s
"""


MODEL_MANY = """You are a classifier. You are given ITEMS. Each has a STATE and names a set
of typed QUESTIONS (under QUESTION SETS) to answer about that state. Answer every question of
every item from its own state alone. Write no prose.

- A question of type "choice" lists its options under "criteria", by id. Answer with the ids of
  the three options that fit best and how likely each is (numbers from 0 to 1 that sum to at
  most 1), most likely first.
- A question of type "noul" is a yes or no. Answer with how likely "true" is, from 0 to 1.

Reply with one JSON object and nothing else, keyed by item, shaped exactly like this:
{"<item>": {"<question id>": {"top": [["<option id>", 0.7], ["<option id>", 0.2]]}, "<question id>": {"yes": 0.9}}}

QUESTION SETS:
%s

ITEMS:
%s
"""


def _checked(raw: Any, questions: Row) -> Row:
    """A model's answers to one item's questions, held to the lists: an id that is not an
    option is dropped, and a question left without one fails."""
    if not isinstance(raw, dict):
        raise ClassifierError("no answers")
    out: Row = {}
    for qid, question in questions.items():
        given = raw.get(qid)
        if not isinstance(given, dict):
            raise ClassifierError(f"no answer for {qid}")
        if question.get("type") == "noul":
            out[qid] = {"noul": _unit(given.get("yes"))}
            continue
        allowed = question.get("criteria") or {}
        probs: dict[str, float] = {}
        for pair in given.get("top") or []:
            if isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[0] in allowed:
                probs.setdefault(str(pair[0]), _unit(pair[1]))
        if not probs:
            raise ClassifierError(f"{qid} was answered with none of its options")
        total = sum(probs.values())
        if total > 1:
            probs = {k: v / total for k, v in probs.items()}
        best = max(probs, key=lambda k: probs[k])
        out[qid] = {"choice": best, "confidence": probs[best], "probabilities": probs}
    return out


def model(complete: Complete, *, batch: int = BATCH) -> Ask:
    """A reader backed by a model. Asked one item at a time it answers one; through its `many`
    it is shown `batch` items a prompt, each question set written once."""

    def ask(state: Any, questions: Row) -> Row:
        prompt = MODEL_ASK % (
            json.dumps(state, ensure_ascii=False, indent=1),
            json.dumps(questions, ensure_ascii=False, indent=1),
        )
        return _checked(_json_in(complete(prompt)), questions)

    def many(jobs: list[Job]) -> dict[str, Row]:
        out: dict[str, Row] = {}
        for start in range(0, len(jobs), batch):
            chunk = jobs[start : start + batch]
            sets: dict[str, str] = {}
            items = []
            for key, state, questions in chunk:
                body = json.dumps(questions, ensure_ascii=False, sort_keys=True)
                name = sets.setdefault(body, f"Q{len(sets) + 1}")
                items.append({"item": key, "questions": name, "state": state})
            prompt = MODEL_MANY % (
                "\n".join(f"{name}: {body}" for body, name in sets.items()),
                json.dumps(items, ensure_ascii=False, indent=1),
            )
            try:
                raw = _json_in(complete(prompt))
            except ClassifierError as error:
                out.update({key: {"error": str(error)} for key, _, _ in chunk})
                continue
            for key, _state, questions in chunk:
                try:
                    out[key] = _checked(raw.get(key), questions)
                except ClassifierError as error:
                    out[key] = {"error": str(error)}
        return out

    ask.many = many  # type: ignore[attr-defined]
    return ask


def _unit(value: Any) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _json_in(text: str) -> Row:
    """The JSON object a reply holds: the whole reply, a fenced block, or its outermost braces."""
    for candidate in (
        text.strip(),
        *re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S),
        text[text.find("{") : text.rfind("}") + 1],
    ):
        try:
            found = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(found, dict):
            return found
    raise ClassifierError("the reply held no JSON object")
