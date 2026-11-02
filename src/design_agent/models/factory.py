"""Build chat models for each role from settings and the capability registry.

Direct providers by default; `langsmith:provider/model` opts into the LangSmith Gateway. Anthropic
and OpenAI models go through the gateway's native routes, so they keep their own API (prompt
caching, context editing, tool search, effort); other providers use its shared OpenAI-style route.
The SDK's own retries are off: `TransientModelRetryMiddleware` owns recovery, bounded and logged in
one place. Every call has a stall ceiling.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from dotenv import dotenv_values
from langchain_core.language_models import BaseChatModel

from design_agent.config import ModelSpec, Settings
from design_agent.models.registry import (
    ModelCapabilities,
    ModelConfigurationError,
    capabilities_for,
    require_vision,
    resolve_effort,
)

Role = Literal["lead", "helper", "look", "tool_selector", "learning"]
VISION_ROLES: frozenset[Role] = frozenset({"lead", "helper", "look"})
SDK_MAX_RETRIES = 0
#: The gateway origin is pinned, never read from settings, so no setting can send its key elsewhere.
GATEWAY_ORIGIN = "https://gateway.smith.langchain.com"
#: Providers the gateway serves on their own API, which keeps their native features.
GATEWAY_NATIVE_ROUTES = {"anthropic": "/anthropic", "openai": "/openai/v1"}


@dataclass(frozen=True)
class ResolvedModel:
    """One role's validated model choice. Building it performs no network call."""

    role: Role
    spec: ModelSpec
    caps: ModelCapabilities
    effort: str | None
    max_output_tokens: int | None
    base_url: str | None


def resolve_model(
    settings: Settings, role: Role = "lead", *, effort: str | None = None
) -> ResolvedModel:
    """Validate a role's model, effort and output budget against the registry."""
    spec = settings.lead_model() if role == "lead" else settings.role_model(role)
    base_url = settings.model_base_url if spec == settings.lead_model() else None
    caps = capabilities_for(spec, base_url=base_url)
    if role in VISION_ROLES and spec.provider != "scripted":
        require_vision(spec, caps, role=role)
    requested = effort
    if requested is None and role == "lead":
        requested = settings.model_effort
    if requested is None and role == "look":
        requested = "low"
    resolved_effort = resolve_effort(spec, caps, requested, role=role)
    max_output = caps.max_output_tokens
    floor = caps.min_output_tokens(resolved_effort)
    if floor is not None and (max_output is None or max_output < floor):
        max_output = floor
    return ResolvedModel(
        role=role,
        spec=spec,
        caps=caps,
        effort=resolved_effort,
        max_output_tokens=max_output,
        base_url=base_url,
    )


def build_chat_model(
    settings: Settings,
    role: Role = "lead",
    *,
    effort: str | None = None,
    project_root: Path | None = None,
    **overrides: Any,
) -> BaseChatModel:
    """The chat model for `role`. Keyword overrides go to the provider class (tests pass api_key)."""
    resolved = resolve_model(settings, role, effort=effort)
    spec = resolved.spec
    kwargs: dict[str, Any] = {
        "timeout": settings.model_timeout_seconds,
        "max_retries": SDK_MAX_RETRIES,
    }
    if resolved.base_url is not None:
        kwargs["base_url"] = resolved.base_url
        key = _named_key(settings.model_api_key_env, project_root)
        if key is None:
            raise ModelConfigurationError(
                "DESIGN_AGENT_MODEL_BASE_URL needs DESIGN_AGENT_MODEL_API_KEY_ENV naming the "
                "variable that holds that endpoint's key"
            )
        kwargs["api_key"] = key
    kwargs.update(overrides)

    if spec.via_gateway:
        upstream = spec.upstream
        # Never "" -> provider key: a missing gateway key must fail at the gateway, not leak.
        kwargs.setdefault("api_key", gateway_key(settings))
        if upstream.provider in GATEWAY_NATIVE_ROUTES:
            kwargs.setdefault("base_url", GATEWAY_ORIGIN + GATEWAY_NATIVE_ROUTES[upstream.provider])
            native = replace(resolved, spec=upstream)
            build = _anthropic if upstream.provider == "anthropic" else _openai
            return build(settings, native, kwargs)
        from langchain.chat_models import init_chat_model

        gateway: BaseChatModel = init_chat_model(str(spec), **kwargs)
        return gateway
    if spec.provider == "anthropic":
        return _anthropic(settings, resolved, kwargs)
    if spec.provider == "openai":
        return _openai(settings, resolved, kwargs)

    from langchain.chat_models import init_chat_model

    if resolved.max_output_tokens is not None and "max_tokens" not in kwargs:
        kwargs["max_tokens"] = resolved.max_output_tokens
    if spec.provider == "google_genai" and settings.google_api_key is not None:
        kwargs.setdefault("api_key", settings.google_api_key.get_secret_value())
    model: BaseChatModel = init_chat_model(str(spec), **kwargs)
    return model


#: Server-side tool-result clearing for helpers (platform.claude.com, "Context editing"). A clear
#: invalidates the cached prefix, so it waits for a large prompt and clears at least 20k tokens.
CONTEXT_MANAGEMENT_BETA = "context-management-2025-06-27"
HELPER_TOOL_CLEARING: dict[str, Any] = {
    "type": "clear_tool_uses_20250919",
    "trigger": {"type": "input_tokens", "value": 120_000},
    "keep": {"type": "tool_uses", "value": 6},
    "clear_at_least": {"type": "input_tokens", "value": 20_000},
}


def _anthropic(
    settings: Settings, resolved: ResolvedModel, kwargs: dict[str, Any]
) -> BaseChatModel:
    from design_agent.models.cache import CachedChatAnthropic

    kwargs.setdefault(
        "cache_ttl", settings.cache_ttl if resolved.role == "lead" else settings.helper_cache_ttl
    )
    if settings.enable_tool_clearing and resolved.role == "helper":
        kwargs.setdefault("betas", [CONTEXT_MANAGEMENT_BETA])
        kwargs.setdefault("context_management", {"edits": [HELPER_TOOL_CLEARING]})
    if settings.anthropic_api_key is not None:
        kwargs.setdefault("api_key", settings.anthropic_api_key.get_secret_value())
    if resolved.effort is not None:
        kwargs.setdefault("effort", resolved.effort)
    if resolved.caps.adaptive_thinking:
        kwargs.setdefault("thinking", {"type": "adaptive"})
    if resolved.max_output_tokens is not None:
        kwargs.setdefault("max_tokens", resolved.max_output_tokens)
    return CachedChatAnthropic(model=resolved.spec.model, **kwargs)


def _openai(settings: Settings, resolved: ResolvedModel, kwargs: dict[str, Any]) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    if settings.openai_api_key is not None:
        kwargs.setdefault("api_key", settings.openai_api_key.get_secret_value())
    kwargs.setdefault("use_responses_api", resolved.caps.responses_api)
    if resolved.effort is not None:
        kwargs.setdefault("reasoning", {"effort": resolved.effort})
    if resolved.max_output_tokens is not None:
        kwargs.setdefault("max_completion_tokens", resolved.max_output_tokens)
    return ChatOpenAI(model=resolved.spec.model, **kwargs)


def gateway_key(settings: Settings) -> str:
    """The gateway credential: its own key, else the LangSmith key; "" when there is neither."""
    for key in (settings.langsmith_gateway_api_key, settings.langsmith_api_key):
        if key is not None and key.get_secret_value():
            return key.get_secret_value()
    return ""


def _named_key(env_name: str | None, project_root: Path | None) -> str | None:
    """The value of the variable `env_name` from the process or the project `.env`."""
    if not env_name:
        return None
    if value := os.environ.get(env_name, "").strip():
        return value
    env_file = (project_root or Path.cwd()) / ".env"
    if env_file.is_file():
        value = (dotenv_values(env_file).get(env_name) or "").strip()
        return value or None
    return None
