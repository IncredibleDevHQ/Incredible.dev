"""Allowed generation settings: each agent's models and the efforts each one takes. The client
can select only an advertised model and effort."""

from __future__ import annotations

import re
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from design_agent.config import Settings
from design_agent.models.factory import resolve_model
from design_agent.models.registry import CAPABILITY_REGISTRY

Row = dict[str, Any]
PROVIDERS = {"codex": "OpenAI", "claude": "Anthropic", "kimi": "Kimi Code", "demo": "Scripted"}
ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")

#: Claude Code's models by the names its `--model` takes, as a person knows them, with the
#: levels its `--effort` takes. Its small model takes none.
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CLAUDE_CODE: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("claude-fable-5-2", "Fable 5.2", CLAUDE_EFFORTS),
    ("claude-opus-5-5", "Opus 5.5", CLAUDE_EFFORTS),
    ("claude-sonnet-5-5", "Sonnet 5.5", CLAUDE_EFFORTS),
    ("claude-haiku-5-5", "Haiku 5.5", ()),
)
#: Where Kimi Code keeps its settings: the models its account offers, the one it starts on and
#: how hard it thinks unless told otherwise.
KIMI_HOME = Path("~/.kimi-code")
#: The Codex CLI is launched with the Studio host's HOME.
CODEX_HOME = Path("~/.codex")


def options(settings: Settings, writer: str) -> list[Row]:
    """What an agent can be asked to run on. The first row is the agent's own default; where
    the agent says what that is, the row says so (`resolves`, `default_effort`)."""
    if writer == "demo":
        return [{"id": "", "name": "demo", "efforts": []}]
    if writer == "kimi":
        return _kimi(KIMI_HOME.expanduser())
    if writer == "claude":
        return [
            {"id": "", "name": "CLI default", "efforts": list(CLAUDE_EFFORTS)},
            *({"id": i, "name": name, "efforts": list(e)} for i, name, e in CLAUDE_CODE),
        ]
    prefix = {"codex": "openai"}.get(writer)
    if writer == "builtin":
        resolved = resolve_model(settings)
        prefix = resolved.spec.upstream.provider
        # A custom endpoint only promises the model configured by its operator.
        default = {
            "id": "",
            "name": resolved.spec.upstream.model,
            "efforts": [e for e in ORDER if e in resolved.caps.efforts],
        }
        if settings.model_base_url:
            return [default]
    else:
        default = {"id": "", "name": "CLI default", "efforts": []}
        if writer == "codex" and (model := _codex_default(CODEX_HOME.expanduser())):
            default["resolves"] = model
            caps = CAPABILITY_REGISTRY.get(f"openai:{model}")
            if caps is not None:
                default["efforts"] = [e for e in ORDER if e in caps.efforts]
    choices = [default]
    for spec, caps in CAPABILITY_REGISTRY.items():
        provider, name = spec.split(":", 1)
        if provider == prefix:
            choices.append(
                {"id": name, "name": name, "efforts": [e for e in ORDER if e in caps.efforts]}
            )
    return choices


def _codex_default(home: Path) -> str:
    path = home / "config.toml"
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return ""
    return _codex_model(path, stamp)


@lru_cache(maxsize=4)
def _codex_model(path: Path, stamp: int) -> str:  # noqa: ARG001 - changes invalidate the cached read
    try:
        with path.open("rb") as handle:
            model = tomllib.load(handle).get("model")
    except (OSError, ValueError):
        return ""
    return model if isinstance(model, str) and re.fullmatch(r"[\w./:-]{1,120}", model) else ""


def _kimi(home: Path) -> list[Row]:
    """Kimi Code's models, from its own settings: each alias its `--model` takes under the name
    Kimi gives it, newest first, with the efforts that model takes."""
    path = home / "config.toml"
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return [{"id": "", "name": "CLI default", "efforts": []}]
    return [dict(row) for row in _kimi_read(str(path), stamp)]


@lru_cache(maxsize=4)
def _kimi_read(path: str, stamp: int) -> tuple[Row, ...]:  # noqa: ARG001 - a change is a new read
    fallback: tuple[Row, ...] = ({"id": "", "name": "CLI default", "efforts": []},)
    try:
        with open(path, "rb") as handle:
            read = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return fallback
    # only what is shown is kept: the file also holds the account's keys
    listed = read.get("models")
    thinking = read.get("thinking")
    usual = thinking.get("effort") if isinstance(thinking, dict) else None
    rows: list[Row] = []
    for alias, model in (listed if isinstance(listed, dict) else {}).items():
        if not isinstance(model, dict):
            continue
        offered = model.get("support_efforts")
        efforts = [e for e in ORDER if e in (offered if isinstance(offered, list) else [])]
        row: Row = {
            "id": str(alias),
            "name": str(model.get("display_name") or str(alias).rsplit("/", 1)[-1]),
            "efforts": efforts,
        }
        # how hard it thinks when nothing is asked: Kimi's own setting where this model takes
        # it, else the model's
        default = usual if usual in efforts else model.get("default_effort")
        if default in efforts:
            row["default_effort"] = default
        rows.append(row)
    if not rows:
        return fallback
    rows.sort(key=_newest_first)
    first: Row = {"id": "", "name": "CLI default", "efforts": []}
    starts = next((r for r in rows if r["id"] == read.get("default_model")), None)
    if starts is not None:
        first = {**starts, "id": "", "name": "CLI default", "resolves": starts["name"]}
    return (first, *rows)


def _newest_first(row: Row) -> tuple[float, int]:
    """A model's version, read from its name, so 3.1 comes before 3 and 2.7; of one version the
    plainest name leads (a model before its high-speed or long-context kind)."""
    found = re.search(r"\d+(?:\.\d+)?", str(row["name"]))
    return (-float(found.group()) if found else 0.0, len(str(row["name"])))


def named(writer: str, reported: str) -> str:
    """The model a run says it ran on, under the name it is offered by."""
    if writer == "claude":
        for model_id, name, _ in CLAUDE_CODE:
            if reported.startswith(model_id):
                return name
    return reported


def generation(settings: Settings, writer: str, pick: Row) -> Row:
    model, effort = pick.get("model", ""), pick.get("effort", "")
    choice = next((o for o in options(settings, writer) if o["id"] == model), None)
    if choice is None or effort and effort not in choice["efforts"]:
        raise ValueError("Choose a supported model and effort for this provider.")
    if writer == "builtin":
        scoped = settings_for(settings, model, effort)
        resolved = resolve_model(scoped)
        return {
            "provider": resolved.spec.upstream.provider,
            "model": resolved.spec.upstream.model,
            "effort": resolved.effort or "Not applicable",
        }
    return {
        "provider": PROVIDERS.get(writer, writer),
        # the agent's own default is named where the agent says what it is
        "model": choice.get("resolves") or choice["name"],
        "effort": effort
        or choice.get("default_effort")
        or ("Not applicable" if writer == "demo" else "CLI default"),
    }


def settings_for(settings: Settings, model: str, effort: str) -> Settings:
    spec = settings.lead_model()
    route = str(spec)
    if model:
        route = (
            f"langsmith:{spec.upstream.provider}/{model}"
            if spec.via_gateway
            else f"{spec.provider}:{model}"
        )
    return settings.model_copy(
        update={
            "model": route,
            "model_effort": effort or (settings.model_effort if route == str(spec) else None),
        }
    )
