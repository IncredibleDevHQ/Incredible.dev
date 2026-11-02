"""Prompt-cache lifetime per role, for Anthropic models.

deepagents installs Anthropic prompt caching on every agent it builds, with a five-minute TTL and
no way to pass another. The lead's thread is read again minutes to hours apart (a wake-up, the
person's next message), so its prefix is worth an hour; a helper's burst of calls is not. This
model sets every cache breakpoint in a request to the role's TTL. All breakpoints get the same
TTL, which also satisfies the provider's rule that longer-lived breakpoints come first.
"""

from __future__ import annotations

from typing import Any, Literal

from langchain_anthropic import ChatAnthropic

CacheTtl = Literal["5m", "1h"]


def _with_ttl(value: Any, ttl: CacheTtl) -> Any:
    if isinstance(value, dict):
        out = {k: _with_ttl(v, ttl) for k, v in value.items()}
        control = out.get("cache_control")
        if isinstance(control, dict) and control.get("type") == "ephemeral":
            out["cache_control"] = {**control, "ttl": ttl}
        return out
    if isinstance(value, list):
        return [_with_ttl(v, ttl) for v in value]
    return value


class CachedChatAnthropic(ChatAnthropic):
    """`ChatAnthropic` whose cache breakpoints live for `cache_ttl` (module doc)."""

    cache_ttl: CacheTtl = "5m"

    def _get_request_payload(
        self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        control = kwargs.get("cache_control")
        if isinstance(control, dict):
            kwargs["cache_control"] = {**control, "ttl": self.cache_ttl}
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        return dict(_with_ttl(payload, self.cache_ttl))
