"""Allowed picture-generation settings. The client can select only an advertised model."""

from __future__ import annotations

from typing import Any

from design_agent.config import Settings
from design_agent.models.factory import resolve_model
from design_agent.models.registry import CAPABILITY_REGISTRY

Row = dict[str, Any]
PROVIDERS = {"codex": "OpenAI", "claude": "Anthropic", "kimi": "Kimi Code", "demo": "Scripted"}
ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


def options(settings: Settings, writer: str) -> list[Row]:
    if writer in {"demo", "kimi"}:
        return [{"id": "", "name": "demo" if writer == "demo" else "CLI default", "efforts": []}]
    prefix = {"codex": "openai", "claude": "anthropic"}.get(writer)
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
    choices = [default]
    for spec, caps in CAPABILITY_REGISTRY.items():
        provider, name = spec.split(":", 1)
        if provider == prefix:
            choices.append(
                {"id": name, "name": name, "efforts": [e for e in ORDER if e in caps.efforts]}
            )
    return choices


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
        "model": choice["name"],
        "effort": effort or ("Not applicable" if writer == "demo" else "CLI default"),
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
