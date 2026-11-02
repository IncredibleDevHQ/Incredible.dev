"""Keep the resident skill list to one "when to use" line per skill.

Skills load on demand; only their name and description stay in the system prompt, on every model
call. Upstream HyperFrames skills carry long descriptions written for routing among themselves, and
they are vendored unmodified. deepagents renders the list from `request.state["skills_metadata"]`
inside this middleware, so on each model call this hands it a copy of that state in which each
vendored skill's description is our one-line summary from `config/vendored-skills.toml`. Nothing
is written to the thread's state, the SKILL.md files are untouched, and the swap is deterministic,
so the cached prompt prefix stays byte-identical across calls.
"""

from __future__ import annotations

import tomllib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse


def load_summaries(project_root: Path) -> dict[str, str]:
    path = project_root / "config" / "vendored-skills.toml"
    if not path.is_file():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {str(k): " ".join(str(v).split()) for k, v in dict(data.get("summaries") or {}).items()}


def summarized(
    skills: Sequence[Mapping[str, Any]], summaries: Mapping[str, str]
) -> list[Mapping[str, Any]] | None:
    """The skills with vendored descriptions replaced; None when nothing changes."""
    out: list[Mapping[str, Any]] = []
    changed = False
    for skill in skills:
        summary = summaries.get(str(skill.get("name")))
        if summary is not None and skill.get("description") != summary:
            out.append({**skill, "description": summary})
            changed = True
        else:
            out.append(skill)
    return out if changed else None


class SkillListMiddleware(AgentMiddleware[Any, Any, Any]):
    """Swap vendored skills' descriptions in what the skill list is rendered from (module doc)."""

    def __init__(self, summaries: Mapping[str, str]) -> None:
        super().__init__()
        self._summaries = dict(summaries)

    def _summarized(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        state: Mapping[str, Any] = cast("Mapping[str, Any]", request.state)
        skills = state.get("skills_metadata") if isinstance(state, Mapping) else None
        if not skills or not self._summaries:
            return request
        swapped = summarized(skills, self._summaries)
        if swapped is None:
            return request
        return request.override(state=cast("Any", {**state, "skills_metadata": swapped}))

    def wrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], ModelResponse[Any]]
    ) -> ModelResponse[Any]:
        return handler(self._summarized(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(self._summarized(request))
