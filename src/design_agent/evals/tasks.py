"""The task set: `tests/eval/tasks.json`, validated."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Kind = Literal["still", "deck", "diagram", "chart", "thumbnail", "storyboard", "film", "behavior"]
Behavior = Literal[
    "uses_look",
    "fewest_words",
    "no_render",
    "storyboard_first",
    "gates_before_render",
    "decides_or_asks",
    "no_invented_logo",
    "no_false_attachment",
    "reports_blocked",
    "paper_unavailable_once",
    "quiet_check_in",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OutputSpec(_Strict):
    glob: str
    size: str | None = Field(default=None, pattern=r"^\d+x\d+(\|\d+x\d+)*$")
    """`WxH`, or acceptable alternatives for an image (`1200x627|1080x1350`)."""
    seconds: float | None = Field(default=None, gt=0)
    count: int = Field(default=1, ge=1)


class Expect(_Strict):
    outputs: tuple[OutputSpec, ...] = ()
    copy_lines: tuple[str, ...] = Field(default=(), alias="copy")
    copy_case: Literal["exact", "any"] = Field(default="exact", alias="copyCase")
    """`any` when the task lists words, not copy: labels may be set in the brand's casing."""
    max_questions: int | None = Field(default=None, ge=0)
    behaviors: tuple[Behavior, ...] = ()


class Budget(_Strict):
    minutes: float = Field(gt=0)
    usd: float = Field(gt=0)


class Task(_Strict):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    kind: Kind
    prompt: str = Field(min_length=1)
    follow_ups: tuple[str, ...] = ()
    attachments: tuple[str, ...] = ()
    brand: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    needs: tuple[str, ...] = ()
    expect: Expect
    budget: Budget


class TaskSet(_Strict):
    version: int
    brand: str
    tasks: tuple[Task, ...]


def load_tasks(path: Path) -> TaskSet:
    tasks = TaskSet.model_validate(json.loads(path.read_text(encoding="utf-8")))
    ids = [t.id for t in tasks.tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("task ids must be unique")
    for task in tasks.tasks:
        for relative in (*task.attachments, *([task.brand] if task.brand else [])):
            if not (path.parent / relative).exists():
                raise ValueError(f"{task.id}: {relative} does not exist next to {path.name}")
    return tasks
