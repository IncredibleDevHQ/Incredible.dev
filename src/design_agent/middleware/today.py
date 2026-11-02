"""Each turn starts with a note of today's date and the time, in the person's timezone.

The model has no clock, and "tomorrow", "this week" or "Thursday at 10" in a brief resolve against
whatever it guesses. So the date is written into the history once per new input: a human message
after the newest input (the person's message, a wake-up, a restored helper's closing note), before
the model first sees it.

Not in the system prompt: a prompt that changes every turn breaks the cached prefix of the whole
thread behind it. Not appended to every model call either, since a note riding the tail changes
every request. Written before the model call, it lands after every `before_agent` hook, so a hook
that replaces the history (a resumed helper's restored transcript) cannot drop it. It is a human
message because langchain-anthropic folds system messages into the one system prompt.

Whose timezone: the lead decides once per turn through `zone_for` (the Slack adapter reads the
person's profile; otherwise the deployment's `DESIGN_AGENT_TIMEZONE`) and keeps it in
`today_zone`. A subagent reads its lead's and never hands it back: deepagents copies a finished
subagent's state to its lead, and two parallel `task` calls would write it twice in one step,
which LangGraph refuses. A zone that cannot be read is UTC, and the note says so.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, NotRequired, TypedDict
from zoneinfo import ZoneInfo

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.agents.middleware.types import OmitFromSchema
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

_LOGGER = logging.getLogger(__name__)

#: A date note's id starts with this, so code looking for what a person asked can pass it over.
DATE_NOTE = "today:"


class Zone(TypedDict):
    """The zone a turn's clock is read in: its IANA name, and whose zone it is."""

    name: str
    whose: str


#: Decides the lead's zone for a turn from its runtime and state; None when unknown.
ZoneFor = Callable[[Any, Mapping[str, Any]], Awaitable[Zone | None]]


class TodayState(AgentState[Any]):
    today_zone: NotRequired[Annotated[Zone | None, OmitFromSchema(input=False, output=True)]]


def note(now: datetime, zone: Zone | None) -> str:
    """Today's date in `zone`, or in UTC when there is none, and the time the turn started."""
    if zone is None:
        where, local = "UTC (the person's timezone is unknown)", now.astimezone(UTC)
    else:
        where, local = f"{zone['name']}, {zone['whose']}", now.astimezone(ZoneInfo(zone["name"]))
    return (
        f"[Today is {local:%A %Y-%m-%d} in {where}. "
        f"This turn started at {local.isoformat(timespec='minutes')}.]"
    )


def fixed_zone(name: str) -> ZoneFor:
    """Every turn in one configured zone (`DESIGN_AGENT_TIMEZONE`)."""

    async def zone_for(_runtime: Any, _state: Mapping[str, Any]) -> Zone | None:
        return readable({"name": name, "whose": "this deployment's timezone"})

    return zone_for


def readable(zone: object) -> Zone | None:
    """`zone` when Python can read its name; otherwise None, which the note reads as UTC."""
    if not isinstance(zone, Mapping) or not isinstance(zone.get("whose"), str):
        return None
    try:
        ZoneInfo(str(zone.get("name")))
    except Exception:  # noqa: BLE001 - not a name the zone database has
        return None
    return Zone(name=str(zone["name"]), whose=zone["whose"])


def _unnoted(messages: Sequence[object]) -> HumanMessage | None:
    """The newest input, when no date note follows it yet."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return None if str(message.id or "").startswith(DATE_NOTE) else message
    return None


class TodayMiddleware(AgentMiddleware[TodayState, Any, Any]):
    """Note the date after each new input, before the model sees it (module doc).

    The lead (`zone_for` given) decides the turn's zone; a subagent reads the one its lead decided.
    """

    state_schema = TodayState

    def __init__(
        self,
        *,
        zone_for: ZoneFor | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__()
        self._zone_for = zone_for
        self._clock = clock

    async def abefore_model(
        self, state: TodayState, runtime: Runtime[Any]
    ) -> dict[str, Any] | None:
        noting = _unnoted(state.get("messages") or [])
        if noting is None:
            return None
        update: dict[str, Any] = {}
        if self._zone_for is not None:
            try:
                update["today_zone"] = await self._zone_for(runtime, state)
            except Exception as error:  # noqa: BLE001 - the date is worth a turn; whose zone is not
                _LOGGER.warning("[today] the timezone was not read: %s", type(error).__name__)
                update["today_zone"] = None
        zone = readable(update.get("today_zone", state.get("today_zone")))
        written = HumanMessage(
            note(self._clock(), zone), id=f"{DATE_NOTE}{noting.id or uuid.uuid4().hex}"
        )
        return {**update, "messages": [written]}
