"""Every model call's usage on the harness bus, and the fan-out stagger, for Design Agent.

`UsageMeterMiddleware(role)` wraps the model call: after the handler returns, it prices the
response's `usage_metadata` (`harness.meter.cost_of`) and publishes a `USAGE` event for the thread
(`langgraph.config.get_config()["configurable"]["thread_id"]`). The source is `lead`, or the
helper's task id when a background helper made the call (`harness.meter.CURRENT_TASK_ID`, which
`middleware/background.py` sets). `METER` is the process's meter, summing those events per thread
and source; `check_tasks` can read `METER.summary(thread_id)`.

`publish_usage` is the same step for a model call made outside the middleware stack (`look`).

`stagger_middleware(gate)` holds a wave's helpers on their first model call until the first one
has a response (`harness.cache.StaggerGate`), so they read the shared prefix instead of each
writing it. Optional; the wiring is in docs/architecture/context-and-cost.md.

Nothing here changes a request or a response, and a failure to meter is logged, never raised.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage
from langgraph.config import get_config

from design_agent.harness import events as ev
from design_agent.harness.cache import StaggerGate
from design_agent.harness.meter import CURRENT_TASK_ID, LEAD, Meter, cost_of

_LOGGER = logging.getLogger(__name__)

#: The process's meter: every `USAGE` event on the bus, summed per thread and source.
METER = Meter()


def _thread_id() -> str:
    try:
        configurable = get_config().get("configurable") or {}
    except RuntimeError:  # outside a run
        return ""
    return str(configurable.get("thread_id") or "")


def _ai_messages(result: object) -> list[AIMessage]:
    """The model's messages in whatever a handler returned (a response, a message, a wrapper)."""
    if isinstance(result, AIMessage):
        return [result]
    inner = getattr(result, "model_response", None)
    messages = getattr(inner if inner is not None else result, "result", None)
    return [m for m in messages or [] if isinstance(m, AIMessage)]


def _cleared(message: AIMessage) -> dict[str, int]:
    """What server-side context editing cleared before this call, when it did."""
    managed = message.response_metadata.get("context_management")
    edits = managed.get("applied_edits") if isinstance(managed, Mapping) else None
    if not edits:
        return {}
    return {
        "cleared_tool_uses": sum(int(e.get("cleared_tool_uses") or 0) for e in edits),
        "cleared_input_tokens": sum(int(e.get("cleared_input_tokens") or 0) for e in edits),
    }


def publish_usage(
    message: AIMessage,
    *,
    role: str,
    model: str | None = None,
    write_ttl: str | None = None,
    bus: ev.EventBus = ev.BUS,
) -> ev.Event | None:
    """Publish one model response's usage as a `USAGE` event; None when there is nothing to bill.

    `model` defaults to the response's own `model_name`. `write_ttl` prices a cache write the
    usage does not split by TTL (the API splits it; this is the fallback).
    """
    usage = message.usage_metadata
    thread_id = _thread_id()
    if not usage or not thread_id:
        return None
    name = str(message.response_metadata.get("model_name") or model or "")
    data: dict[str, Any] = {"model": name, "role": role, "usage": dict(usage)}
    try:
        cost = cost_of(usage, name, write_ttl=write_ttl or "5m")
    except KeyError:  # a model with no listed price: its tokens still count
        data |= {"usd": 0.0, "priced": False, "input_tokens": usage.get("input_tokens", 0)}
        text = f"{role}: {usage.get('input_tokens', 0):,} tokens in (no price for {name})"
    else:
        data |= {
            "usd": cost.usd,
            "cache_read": cost.cache_read,
            "cache_write": cost.cache_write,
            "input_tokens": cost.input_tokens,
            "output_tokens": cost.output_tokens,
        }
        text = (
            f"{role}: ${cost.usd:.3f}, {cost.input_tokens:,} tokens in "
            f"({cost.hit_ratio:.0%} from cache), {cost.output_tokens:,} out"
        )
    data |= _cleared(message)
    event = ev.Event(
        kind=ev.USAGE,
        thread_id=thread_id,
        source=CURRENT_TASK_ID.get() or LEAD,
        label=role,
        text=text,
        data=data,
    )
    bus.publish(event)
    return event


class UsageMeterMiddleware(AgentMiddleware):
    """Publishes a `USAGE` event for every model response this agent gets.

    Place it innermost (last) among the authored middleware: it then sees each real response,
    including each one a retry produced, and no request is changed on its way.
    """

    def __init__(self, role: str, *, bus: ev.EventBus = ev.BUS) -> None:
        super().__init__()
        self.role = role
        self._bus = bus

    def _meter(self, request: ModelRequest, result: object) -> None:
        try:
            ttl_of = getattr(request.model, "effective_cache_ttl", None)
            ttl = ttl_of() if callable(ttl_of) else None
            write_ttl = ttl if isinstance(ttl, str) else None
            for message in _ai_messages(result):
                publish_usage(
                    message,
                    role=self.role,
                    model=getattr(request.model, "model", None),
                    write_ttl=write_ttl,
                    bus=self._bus,
                )
        except Exception as error:  # noqa: BLE001 - metering never costs the call
            _LOGGER.warning("[meter] usage not recorded: %s", type(error).__name__)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        result = handler(request)
        self._meter(request, result)
        return result

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        result = await handler(request)
        self._meter(request, result)
        return result


# -- the fan-out stagger ---------------------------------------------------------------------------

#: Which helper is calling, and its wave: `(task_id, wave)`, or None outside a helper.
Member = Callable[[], tuple[str, str | None] | None]


def current_helper() -> tuple[str, str | None] | None:
    """The running helper's task id (`CURRENT_TASK_ID`) and its wave (`harness.tasks`)."""
    task_id = CURRENT_TASK_ID.get()
    if not task_id:
        return None
    try:
        from design_agent.harness.tasks import REGISTRY
    except ImportError:
        return task_id, None
    record = REGISTRY.get(task_id)
    return task_id, (record.wave if record is not None else None)


class StaggerMiddleware(AgentMiddleware):
    """A helper's first model call waits at its wave's `StaggerGate`; every later call goes."""

    def __init__(self, gate: StaggerGate, *, member: Member = current_helper) -> None:
        super().__init__()
        self._gate = gate
        self._member = member
        self._entered: set[str] = set()

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        found = self._member()
        if found is None:
            return await handler(request)
        task_id, wave = found
        if not wave or task_id in self._entered:
            return await handler(request)
        self._entered.add(task_id)
        await self._gate.enter(wave)
        try:
            return await handler(request)
        finally:
            # A response exists (or the call failed): either way, stop holding the others.
            self._gate.first_response(wave)


def stagger_middleware(gate: StaggerGate, *, member: Member = current_helper) -> StaggerMiddleware:
    """The stagger for one agent's model calls; share one `gate` across the wave's agents."""
    return StaggerMiddleware(gate, member=member)
