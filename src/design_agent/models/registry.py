"""Exact-id model capability registry.

Each entry records what the harness relies on for one `provider:model` id. Lookups are exact: no
substring matching on provider or model names, so a new model takes the portable path until
someone verifies it and adds an entry. `tests/unit/test_model_registry.py` cross-checks every
entry against the limits the installed provider package publishes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from design_agent.config import ModelSpec


class ToolDisclosure(StrEnum):
    """How deferred tools reach the model."""

    PROVIDER_NATIVE = "provider_native"
    """Provider-side deferred tool search (Anthropic tool search, OpenAI Responses tool_search)."""
    PORTABLE_SELECTOR = "portable_selector"
    """`LLMToolSelectorMiddleware` picks a bounded subset per turn."""
    ALL = "all"
    """Every tool bound on every call (scripted model only)."""


ANTHROPIC_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
OPENAI_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})
#: Anthropic's recommended output headroom for the two highest effort levels.
HIGH_EFFORT_MIN_OUTPUT_TOKENS = 64_000


@dataclass(frozen=True)
class ModelCapabilities:
    """What one exact model id supports. Only `verified` entries claim provider features."""

    provider: str
    vision: bool
    tool_calling: bool = True
    disclosure: ToolDisclosure = ToolDisclosure.PORTABLE_SELECTOR
    efforts: frozenset[str] = frozenset()
    default_effort: str | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None
    adaptive_thinking: bool = False
    """Claude 5: thinking is adaptive and replayed thinking must match unedited history."""
    cache_ttls: frozenset[str] = frozenset()
    server_context_editing: bool = False
    streaming_tool_calls: bool = True
    responses_api: bool = False
    integration_package: str = ""
    image_tokens_per_megapixel: int | None = None
    """Approximate input tokens for a 1-megapixel image; drives the look tool's budget."""
    verified: bool = False
    notes: str = ""
    extra: dict[str, object] = field(default_factory=dict)

    def min_output_tokens(self, effort: str | None) -> int | None:
        """The output budget the harness needs for `effort`, or None when any budget works."""
        if self.provider == "anthropic" and effort in {"xhigh", "max"}:
            return HIGH_EFFORT_MIN_OUTPUT_TOKENS
        return None


def _claude(
    default_effort: str | None, *, efforts: frozenset[str] = ANTHROPIC_EFFORTS
) -> ModelCapabilities:
    return ModelCapabilities(
        provider="anthropic",
        vision=True,
        disclosure=ToolDisclosure.PROVIDER_NATIVE,
        efforts=efforts,
        default_effort=default_effort,
        context_window=1_000_000,
        max_output_tokens=128_000,
        adaptive_thinking=bool(efforts),
        cache_ttls=frozenset({"5m", "1h"}),
        server_context_editing=True,
        integration_package="langchain-anthropic",
        # platform.claude.com vision docs: tokens ~= width * height / 750.
        image_tokens_per_megapixel=1_334,
        verified=True,
        notes="Anthropic tool search, prompt caching (5m/1h) and context editing per current docs.",
    )


def _openai(default_effort: str) -> ModelCapabilities:
    return ModelCapabilities(
        provider="openai",
        vision=True,
        disclosure=ToolDisclosure.PROVIDER_NATIVE,
        efforts=OPENAI_EFFORTS,
        default_effort=default_effort,
        context_window=1_050_000,
        max_output_tokens=128_000,
        responses_api=True,
        integration_package="langchain-openai",
        verified=True,
        notes="OpenAI Responses tool_search; automatic prompt caching.",
    )


CAPABILITY_REGISTRY: dict[str, ModelCapabilities] = {
    "anthropic:claude-opus-5-5": _claude("high"),
    "anthropic:claude-fable-5-1": _claude("high"),
    "anthropic:claude-sonnet-5-5": _claude("high"),
    # No effort parameter: a fast, cheap model for `look` and the tool selector.
    "anthropic:claude-haiku-5-5": _claude(None, efforts=frozenset()),
    "openai:gpt-6.1-sol": _openai("medium"),
    "openai:gpt-6-sol": _openai("medium"),
    "openai:gpt-5.6-sol": _openai("medium"),
    "google_genai:gemini-3.6-flash": ModelCapabilities(
        provider="google_genai",
        vision=True,
        disclosure=ToolDisclosure.PORTABLE_SELECTOR,
        efforts=frozenset({"minimal", "low", "medium", "high"}),
        default_effort="medium",
        context_window=1_048_576,
        max_output_tokens=65_536,
        streaming_tool_calls=False,
        integration_package="langchain-google-genai",
        verified=True,
        notes="No provider-side deferred tool search: portable selector path.",
    ),
    "scripted:demo": ModelCapabilities(
        provider="scripted",
        vision=True,
        disclosure=ToolDisclosure.ALL,
        streaming_tool_calls=False,
        integration_package="design-agent",
        verified=True,
        notes="Deterministic scripted model for the offline demo and tests.",
    ),
}

#: Providers the LangSmith Gateway serves on their own API (`models.factory.GATEWAY_NATIVE_ROUTES`).
GATEWAY_NATIVE_PROVIDERS = frozenset({"anthropic", "openai"})

UNKNOWN_MODEL = ModelCapabilities(
    provider="",
    vision=False,
    notes="Not in the registry: portable selector path and no provider-feature claims.",
)


def capabilities_for(spec: ModelSpec, *, base_url: str | None = None) -> ModelCapabilities:
    """Exact lookup. A custom endpoint, or a gateway route that is not the provider's own API,
    never inherits provider-native features."""
    if spec.via_gateway:
        upstream = CAPABILITY_REGISTRY.get(str(spec.upstream), UNKNOWN_MODEL)
        if spec.upstream.provider in GATEWAY_NATIVE_PROVIDERS:
            return upstream
        return _portable(upstream, "LangSmith Gateway shared route: portable selector.")
    found = CAPABILITY_REGISTRY.get(str(spec), UNKNOWN_MODEL)
    if base_url is not None and found.disclosure is ToolDisclosure.PROVIDER_NATIVE:
        return _portable(found, "custom base URL: provider-native search is not assumed.")
    return found


def _portable(caps: ModelCapabilities, note: str) -> ModelCapabilities:
    return ModelCapabilities(
        provider=caps.provider,
        vision=caps.vision,
        tool_calling=caps.tool_calling,
        disclosure=ToolDisclosure.PORTABLE_SELECTOR,
        efforts=caps.efforts,
        default_effort=caps.default_effort,
        context_window=caps.context_window,
        max_output_tokens=caps.max_output_tokens,
        adaptive_thinking=caps.adaptive_thinking,
        streaming_tool_calls=caps.streaming_tool_calls,
        integration_package=caps.integration_package,
        image_tokens_per_megapixel=caps.image_tokens_per_megapixel,
        verified=caps.verified,
        notes=note,
    )


class ModelConfigurationError(ValueError):
    """A model setting the harness cannot run with. The message is safe to print."""


def require_vision(spec: ModelSpec, caps: ModelCapabilities, *, role: str) -> None:
    """Lead, helper and look roles look at renders: refuse a model without image input."""
    if not caps.vision:
        raise ModelConfigurationError(
            f"{role} model {spec} is not registered with image input; the {role} looks at its "
            "own renders. Choose a vision model from the capability registry."
        )


def resolve_effort(
    spec: ModelSpec, caps: ModelCapabilities, requested: str | None, *, role: str
) -> str | None:
    """The effort to send: the request if the model supports it, else the model's default."""
    effort = (requested or "").strip().lower() or caps.default_effort
    if effort is None:
        return None
    if not caps.efforts:
        # Unknown or effort-less models: drop the request rather than send an unknown parameter.
        return None
    if effort not in caps.efforts:
        allowed = ", ".join(sorted(caps.efforts))
        raise ModelConfigurationError(
            f"{role} effort {effort!r} is not supported by {spec}; choose one of: {allowed}"
        )
    return effort
