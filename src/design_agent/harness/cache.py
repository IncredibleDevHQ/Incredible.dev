"""Prompt-cache policy: one TTL per request, a breakpoint on the tools, and a watch on the prefix.

A lead that sleeps while helpers work and wakes minutes later rewrites its whole cached prefix on
every wake-up unless the prefix is stable and outlives the wait. What rewrites a prefix: a clock or
other per-call text in the system prompt, edits that land between the system prompt and the
conversation (memory blocks), no breakpoint on the tools array (so every system change also
rewrites every tool definition), and a TTL shorter than the gap between calls.

This module works on the request payload, after every middleware has run, the only place that sees
the whole prefix. It acts only on what the payload shows: it rewrites the `cache_control`
breakpoints a payload already carries, and adds one to the tools only when they are in Anthropic's
shape, so a payload for another provider passes through unchanged.
- `apply_cache_policy` rewrites every breakpoint to one TTL, since a 1h entry may not follow a 5m
  one, and adds the missing tools breakpoint within the API's four.
- `CachePolicy` holds the TTL per role and picks one from the expected gap between calls.
- `StaggerGate` holds a wave's siblings until the first one's response has started, so they read
  the shared prefix instead of each writing it.
- `prefix_fingerprint` and `PrefixWatch` say which part of a prefix changed between two calls.

Deep Agents' Anthropic prompt-caching middleware uses a fixed 5m TTL and tags the tools only when
the last one is a `BaseTool`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)

TTLS = ("5m", "1h")
#: The API's limit per request. The top-level (automatic) `cache_control` takes one slot.
MAX_BREAKPOINTS = 4
#: The gaps `choose_ttl` separates: a 5m entry dies after 300 s idle, a 1h entry after 3600 s.
FIVE_MINUTES = 300.0
ONE_HOUR = 3600.0


def cache_control(ttl: str) -> dict[str, str]:
    """The one breakpoint shape this module writes."""
    if ttl not in TTLS:
        raise ValueError(f"cache TTL must be one of {', '.join(TTLS)}, not {ttl!r}")
    return {"type": "ephemeral", "ttl": ttl}


# -- the payload -------------------------------------------------------------------------------


def apply_cache_policy(payload: Mapping[str, Any], ttl: str) -> dict[str, Any]:
    """A new Anthropic request payload with every breakpoint at `ttl` and one on the tools.

    - Every `cache_control` the payload already carries (top level, system blocks, tools, message
      content blocks and the blocks nested in a `tool_result`) becomes `{"type": "ephemeral",
      "ttl": ttl}`. One TTL per request always satisfies the rule that 1h entries come first.
    - When no tool carries a breakpoint and the tools are Anthropic's shape (`input_schema`, or a
      server tool's dated `type`), the last tool that is not `defer_loading` gets one, so a
      system-prompt change no longer rewrites the tool definitions. Server tool dicts count: the
      tool-search dict is usually the last entry. Function tools in another provider's shape are
      left as they are.
    - The request never ends up with more than `MAX_BREAKPOINTS`, counting the top-level one: when
      the tools breakpoint would be one too many it is left off, and that is logged.

    Pure: `payload` is not changed, and only the containers on a changed path are copied.
    """
    control = cache_control(ttl)
    result = dict(payload)
    found = 0
    if result.get("cache_control"):
        result["cache_control"] = dict(control)
        found += 1
    system = result.get("system")
    if isinstance(system, list):
        result["system"], count = _retag_blocks(system, control)
        found += count
    messages = result.get("messages")
    if isinstance(messages, list):
        result["messages"], count = _retag_messages(messages, control)
        found += count
    tools = result.get("tools")
    if isinstance(tools, list) and tools:
        tagged, count = _retag_blocks(tools, control)
        found += count
        index = _last_eager_tool(tagged) if count == 0 and _anthropic_tools(tagged) else None
        if index is not None:
            if found >= MAX_BREAKPOINTS:
                _warn_once(
                    f"full-{found}",
                    "[cache] no tools breakpoint: the request already carries %d of %d",
                    found,
                    MAX_BREAKPOINTS,
                )
            else:
                tagged = list(tagged)
                tagged[index] = {**tagged[index], "cache_control": dict(control)}
        result["tools"] = tagged
    return result


def count_breakpoints(payload: Mapping[str, Any]) -> int:
    """How many cache breakpoints a payload carries, the top-level one included."""
    count = 1 if payload.get("cache_control") else 0
    for key in ("system", "tools"):
        value = payload.get(key)
        if isinstance(value, list):
            count += _retag_blocks(value, None)[1]
    messages = payload.get("messages")
    if isinstance(messages, list):
        count += _retag_messages(messages, None)[1]
    return count


def _retag_blocks(
    blocks: Sequence[Any], control: Mapping[str, str] | None
) -> tuple[list[Any], int]:
    """Blocks (or tool dicts) with their own `cache_control` replaced; the count of those found.

    Only the block's own key is touched, never anything inside it (a tool's `input_schema` may
    name a property `cache_control`). `tool_result` blocks are opened, since their content
    blocks may carry one. With `control=None` nothing changes and only the count is returned.
    """
    out: list[Any] | None = None
    found = 0
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        new = block
        if block.get("cache_control"):
            found += 1
            if control is not None:
                new = {**block, "cache_control": dict(control)}
        inner = block.get("content")
        if block.get("type") == "tool_result" and isinstance(inner, list):
            retagged, count = _retag_blocks(inner, control)
            found += count
            if count and control is not None:
                new = {**new, "content": retagged}
        if new is not block:
            if out is None:
                out = list(blocks)
            out[index] = new
    return (out if out is not None else list(blocks)), found


def _retag_messages(
    messages: Sequence[Any], control: Mapping[str, str] | None
) -> tuple[list[Any], int]:
    out: list[Any] | None = None
    found = 0
    for index, message in enumerate(messages):
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        retagged, count = _retag_blocks(content, control)
        found += count
        if count and control is not None:
            if out is None:
                out = list(messages)
            out[index] = {**message, "content": retagged}
    return (out if out is not None else list(messages)), found


def _anthropic_tools(tools: Sequence[Any]) -> bool:
    """Whether every tool is in Anthropic's shape: a client tool with `input_schema`, or a server
    tool named by a dated `type` (`tool_search_tool_bm25_20251119`). OpenAI-style function tools
    (`"type": "function"`, `function` or `parameters`) take no `cache_control`."""
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") == "function":
            return False
        if "function" in tool or ("parameters" in tool and "input_schema" not in tool):
            return False
        if "input_schema" not in tool and not str(tool.get("type") or ""):
            return False
    return True


def _last_eager_tool(tools: Sequence[Any]) -> int | None:
    """The index of the last tool whose schema is sent up front (not deferred behind search)."""
    for index in range(len(tools) - 1, -1, -1):
        tool = tools[index]
        if isinstance(tool, dict) and tool.get("defer_loading") is not True:
            return index
    return None


_WARNED: set[str] = set()


def _warn_once(key: str, message: str, *args: object) -> None:
    if key in _WARNED:
        _LOGGER.debug(message, *args)
        return
    _WARNED.add(key)
    _LOGGER.warning(message, *args)


# -- the TTL per role ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CachePolicy:
    """Which TTL each role's requests write.

    The lead sleeps while helpers work and wakes minutes later, so its prefix must outlive the
    wait: 1h. A helper calls the model every few seconds, and a 5m entry that every read
    refreshes costs 1.25x base to write against 2x for 1h: 5m.
    """

    lead: str = "1h"
    default: str = "5m"
    roles: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for ttl in (self.lead, self.default, *self.roles.values()):
            cache_control(ttl)

    def ttl_for(self, role: str | None) -> str:
        """The TTL for `role`; `None` and `"lead"` are the lead."""
        if role is None or role == "lead":
            return self.lead
        return self.roles.get(role, self.default)

    @staticmethod
    def choose_ttl(expected_gap_seconds: float) -> str:
        """The cheaper TTL for requests that share a prefix and start this far apart.

        Under 5 minutes every read refreshes a 5m entry, so the 2x write buys nothing. From 5
        minutes to an hour only a 1h entry is still there. Past an hour neither is, and the 5m
        write is the cheaper miss.
        """
        if FIVE_MINUTES <= expected_gap_seconds <= ONE_HOUR:
            return "1h"
        return "5m"


# -- fan-out ------------------------------------------------------------------------------------


@dataclass
class _Wave:
    started: float = field(default_factory=time.monotonic)
    ready: asyncio.Event = field(default_factory=asyncio.Event)


class StaggerGate:
    """Holds a wave's siblings until the first sibling's response has started.

    A cache entry can be read only once the response that writes it starts streaming, so N
    helpers launched together over the same tools and system prompt each write that prefix. The
    first caller of `enter(wave)` goes at once; the others wait until `first_response(wave)` or
    until `max_wait` seconds after the first one entered, whichever comes first. Later entrants
    to a released wave go at once. Waves older than `forget_after` seconds are dropped.
    """

    def __init__(self, max_wait: float = 5.0, *, forget_after: float = ONE_HOUR) -> None:
        self.max_wait = max_wait
        self.forget_after = forget_after
        self._waves: dict[str, _Wave] = {}

    async def enter(self, wave: str) -> None:
        self._prune()
        state = self._waves.get(wave)
        if state is None:
            self._waves[wave] = _Wave()
            return
        if state.ready.is_set():
            return
        remaining = state.started + self.max_wait - time.monotonic()
        if remaining <= 0:
            return
        try:
            await asyncio.wait_for(state.ready.wait(), timeout=remaining)
        except TimeoutError:
            pass

    def first_response(self, wave: str) -> None:
        """A response in `wave` has started: its prefix is readable, so release the rest."""
        state = self._waves.get(wave)
        if state is None:
            state = self._waves[wave] = _Wave()
        state.ready.set()

    def forget(self, wave: str) -> None:
        self._waves.pop(wave, None)

    def _prune(self) -> None:
        cutoff = time.monotonic() - self.forget_after
        for wave in [w for w, state in self._waves.items() if state.started < cutoff]:
            del self._waves[wave]


# -- diagnosing a break ---------------------------------------------------------------------------


def prefix_fingerprint(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Hashes of a request's tools, system prompt and each message, breakpoints left out.

    Each is the first 16 hex digits of a SHA-256 over the part's JSON, with every
    `cache_control` removed: a breakpoint that moves between calls never breaks a cache. Two
    requests that should share a prefix differ only where the prefix actually changed.
    """
    return {
        "tools": _digest(payload.get("tools") or []),
        "system": _digest(payload.get("system") or ""),
        "messages": [_digest(message) for message in payload.get("messages") or []],
    }


def _digest(value: Any) -> str:
    text = json.dumps(_without_breakpoints(value), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _without_breakpoints(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _without_breakpoints(v) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list | tuple):
        return [_without_breakpoints(v) for v in value]
    return value


class PrefixWatch:
    """Logs a warning when a key's tools, system prompt or history change between calls.

    A key is one conversation: a thread's lead, one helper, one nested subagent. The tools and the
    system prompt should never change within it, and every message but the last one of the
    previous request should come back unchanged (the last may grow: a follow-up merged into it
    keeps its cached blocks). Anything else rewrote the cache from that point, and under
    preserved thinking an edited history is also rejected for accounts the check enforces.
    """

    def __init__(self, *, max_keys: int = 256, logger: logging.Logger | None = None) -> None:
        self.max_keys = max_keys
        self._logger = logger or _LOGGER
        self._last: OrderedDict[str, Mapping[str, Any]] = OrderedDict()

    def observe(self, key: str, payload: Mapping[str, Any]) -> list[str]:
        """Record this call's prefix (a payload or its fingerprint); return what changed."""
        current = payload if _is_fingerprint(payload) else prefix_fingerprint(payload)
        previous = self._last.pop(key, None)
        self._last[key] = current
        while len(self._last) > self.max_keys:
            self._last.popitem(last=False)
        if previous is None:
            return []
        changed = [part for part in ("tools", "system") if current[part] != previous[part]]
        if not changed:
            kept = list(previous["messages"][:-1])
            now = list(current["messages"][: len(kept)])
            if now != kept:
                index = next(
                    (i for i, (a, b) in enumerate(zip(kept, now, strict=False)) if a != b),
                    len(now),
                )
                changed.append(f"messages[{index}]")
        if changed:
            detail = ", ".join(
                f"{part} {previous[part]} -> {current[part]}"
                if part in ("tools", "system")
                else part
                for part in changed
            )
            self._logger.warning("[cache] prefix changed for %s: %s", key, detail)
        return changed

    def forget(self, key: str) -> None:
        self._last.pop(key, None)


def _is_fingerprint(value: Mapping[str, Any]) -> bool:
    return (
        isinstance(value.get("tools"), str)
        and isinstance(value.get("system"), str)
        and isinstance(value.get("messages"), list)
    )
