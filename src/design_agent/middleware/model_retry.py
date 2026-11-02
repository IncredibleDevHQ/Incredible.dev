"""Bounded recovery at the model boundary, on LangChain's `ModelRetryMiddleware`.

Provider SDK retries are off (`models/factory.py`), so this is the one retry. It retries what
clears on its own: a connection that never completed, a 408/409/429, a 5xx, or the same failure
reported inside a stream. Up to five retries with a doubling, jittered delay spread over about
fifteen seconds. It never replays a tool call; it only sees model calls that failed.

A stall is not retried. Each request is bounded (`model_timeout_seconds`, 600 s by default) so a
hung provider becomes an error rather than silence; a read timeout means the provider held the
request, so replaying it pays for the same work again and multiplies the wait. A connect timeout
never reached the provider and stays transient.

Every class is matched in both HTTP stacks: `anthropic` 1.x and `openai` 3.x run on `httpx2`,
whose classes mirror `httpx`'s without subclassing them. The SDKs wrap what fails before a
response starts (`APIConnectionError`, `APITimeoutError`); what fails while a stream is read
surfaces raw, and an error event inside a stream arrives after the 200, so its `APIStatusError`
carries status 200 and only its `type` names the failure.

What the retry gives up on ends the lead's turn with one line (`ModelFailureBoundary`) rather than
the run: the thread and the sandbox keep the work, so "continue" picks it up. Helpers have no
boundary; their failure reaches the lead as news. A `CancelledError` (the platform stopping the
run) is a `BaseException` and is never caught. A 4xx fails the same way every time, so it is not
retried and still raises: someone has to fix it.

Logs carry exception class names only; provider messages can hold request text.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Awaitable, Callable, Iterator
from typing import Literal

import anthropic
import httpx
import httpx2
import openai
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    ModelRetryMiddleware,
)
from langchain_core.messages import AIMessage
from langgraph.errors import GraphBubbleUp

_LOGGER = logging.getLogger(__name__)
_RETRYABLE_STATUS_CODES = {408, 409, 429}
#: The types Anthropic sends for a 429 or a 5xx (429, 500, 504, 529), which is all a stream's own
#: error event has to go on (platform.claude.com/docs/en/api/errors).
_RETRYABLE_ERROR_TYPES = frozenset(
    {"rate_limit_error", "api_error", "timeout_error", "overloaded_error"}
)


def exception_chain(error: BaseException) -> Iterator[BaseException]:
    """Yield an exception and its explicit cause/context without following cycles."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ if current.__cause__ is not None else current.__context__


#: Transport failures that say the request did not complete on the wire.
_TRANSPORT_ERRORS = (
    openai.APIConnectionError,
    anthropic.APIConnectionError,
    httpx.TimeoutException,
    httpx2.TimeoutException,
    httpx.NetworkError,
    httpx2.NetworkError,
    httpx.RemoteProtocolError,
    httpx2.RemoteProtocolError,
)
#: A timeout after the request reached the gateway. `openai.APITimeoutError` subclasses
#: `APIConnectionError`, so without this a stalled call reads as a transport blip and is
#: replayed.
_STALLS = (
    openai.APITimeoutError,
    anthropic.APITimeoutError,
    httpx.ReadTimeout,
    httpx2.ReadTimeout,
    httpx.WriteTimeout,
    httpx2.WriteTimeout,
    httpx.PoolTimeout,
    httpx2.PoolTimeout,
)
#: The one timeout that never reached a server, even when an SDK wraps it in a stall's class.
_CONNECT_TIMEOUTS = (httpx.ConnectTimeout, httpx2.ConnectTimeout)
_STATUS_ERRORS = (openai.APIStatusError, anthropic.APIStatusError)

FailureKind = Literal["transient", "stall"]


def _classify(error: BaseException) -> tuple[FailureKind, BaseException] | None:
    """A failure's kind and the typed cause that decided it; None when permanent or unknown."""
    causes = list(exception_chain(error))
    connect_timeout = next((c for c in causes if isinstance(c, _CONNECT_TIMEOUTS)), None)
    if connect_timeout is not None:
        return "transient", connect_timeout
    stall = next((c for c in causes if isinstance(c, _STALLS)), None)
    if stall is not None:
        return "stall", stall
    for cause in causes:
        if isinstance(cause, _TRANSPORT_ERRORS):
            return "transient", cause
        if isinstance(cause, _STATUS_ERRORS) and (
            cause.status_code in _RETRYABLE_STATUS_CODES or cause.status_code >= 500
        ):
            return "transient", cause
        if isinstance(cause, anthropic.APIStatusError) and cause.type in _RETRYABLE_ERROR_TYPES:
            return "transient", cause
    return None


def _should_retry(error: Exception) -> bool:
    classified = _classify(error)
    if classified is None:
        return False
    kind, cause = classified
    if kind == "stall":
        return False
    # Exception text can contain request data or credentials.
    _LOGGER.warning("Transient model error: %s", type(cause).__name__)
    return True


class TransientModelRetryMiddleware(ModelRetryMiddleware):
    """Retry OpenAI, Anthropic or HTTP transport failures; never replay a tool call."""

    def __init__(
        self,
        *,
        max_retries: int = 5,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 4.0,
    ) -> None:
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or not 0 <= max_retries <= 5
        ):
            raise ValueError("max_retries must be an integer between 0 and 5")
        if any(
            not math.isfinite(delay) or delay <= 0
            for delay in (
                base_delay_seconds,
                max_delay_seconds,
            )
        ):
            raise ValueError("retry delays must be finite and positive")
        super().__init__(
            max_retries=max_retries,
            retry_on=_should_retry,
            on_failure="error",
            backoff_factor=2.0,
            initial_delay=base_delay_seconds,
            max_delay=max_delay_seconds,
            jitter=True,
        )


#: `response_metadata["partial"]` on the note that ends a turn, as `step_budget` marks its stop.
STALL_STOP_REASON = "stall"
UNAVAILABLE_STOP_REASON = "model_unavailable"
_NOTES: dict[FailureKind, tuple[str, str]] = {
    "stall": (
        STALL_STOP_REASON,
        "_The connection to the model stalled mid-reply, so I stopped this turn here. Everything "
        "so far is saved; reply **continue** and I'll pick up where I left off._",
    ),
    "transient": (
        UNAVAILABLE_STOP_REASON,
        "_The model stayed unavailable through several retries, so I stopped this turn here. "
        "Everything so far is saved; reply **continue** and I'll pick up where I left off._",
    ),
}


class ModelFailureBoundary(AgentMiddleware):
    """A model call the provider could not finish ends the lead's turn with a note, not the run.

    It wraps the retry, so it sees only what the retry gave up on: a stall, or a transient
    failure that outlasted every attempt. The retry's own `on_failure` cannot do this: a stall
    is re-raised before it is consulted, and the retry is shared with the subagents, which must
    raise. The note is fixed text, marked partial in code; the words the model had streamed
    before it failed are gone with the failed call. Anything else still raises: a 4xx, a stale
    history, a bug. The lead's alone -- see the module docstring.
    """

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        try:
            return await handler(request)
        except GraphBubbleUp:
            raise
        except Exception as error:
            classified = _classify(error)
            if classified is None:
                raise
            kind, cause = classified
            reason, note = _NOTES[kind]
            _LOGGER.warning(
                "[model] %s (%s); the turn ends with a note", reason, type(cause).__name__
            )
            return ModelResponse(
                result=[AIMessage(content=note, response_metadata={"partial": reason})]
            )
