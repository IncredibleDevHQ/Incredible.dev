"""Which Slack thread a run answers, and the client that may write there.

A resolver turns a run's runtime into a `SlackTarget` (channel, thread, workspace, the person the
stream is shown to, and the message that started the run) and hands out a `SlackClient` on the
bot token. Two are provided:

- `MdaSlackResolver`, on public Managed Deep Agents APIs only: the target comes from
  `runtime.channel` (a `RuntimeChannel`) when its provider is Slack and its event is a message,
  read from the Slack event MDA verified and passed as `raw_event`; the token comes from the
  reserved agent connection `mda/slack-bot-token`, awaited inside a run.
- `BoltSlackResolver`, for the self-hosted Slack adapter: a bot token it is given, and the Bolt
  event the adapter put on the run (`slack_event` in the run's context or configurable).

`SlackSurface` is what middleware holds. It resolves per call and remembers each LangGraph
thread's latest target, because a run that answers no message (an MDA wake-up schedule, the turn
after an approval) carries no Slack event but still posts into the same thread, and because a
background helper's run has no channel at all: it works after the lead's turn ended, so it reads
the target and client the lead's run resolved. The token stays in this process's memory; it is
never written to the store, the ledger or a wake-up target.
"""

from __future__ import annotations

import logging
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol

import httpx
from langgraph.config import get_config
from pydantic import SecretStr

from design_agent.surfaces.slack.client import SlackClient
from design_agent.surfaces.slack.followups import FollowUpReader

_LOGGER = logging.getLogger(__name__)

#: MDA's reserved agent connection holding the Slack app's bot token.
MDA_BOT_TOKEN = "mda/slack-bot-token"  # noqa: S105 - a connection name, not a secret
#: Threads whose latest target this process remembers.
THREADS_KEPT = 512

_CONVERSATION = re.compile(r"[CDG][A-Z0-9]{6,}")
_TS = re.compile(r"\d{9,11}\.\d{1,7}")
_PERSON = re.compile(r"[UW][A-Z0-9]{6,}")
_TEAM = re.compile(r"[TE][A-Z0-9]{6,}")


@dataclass(frozen=True)
class SlackTarget:
    """A Slack thread a run answers in.

    `user_id` is who a stream is shown to (Slack wants a recipient in a channel); it is never put
    on a card, a tag or a log line. `message_ts` is the message that started the run, empty for a
    run no message started.
    """

    channel: str
    thread_ts: str
    team_id: str = ""
    user_id: str = ""
    message_ts: str = ""

    @property
    def in_dm(self) -> bool:
        return self.channel.startswith("D")

    @property
    def key(self) -> tuple[str, str]:
        return (self.channel, self.thread_ts)


@dataclass(frozen=True)
class SlackBinding:
    target: SlackTarget
    client: SlackClient


def _text(value: object, pattern: re.Pattern[str]) -> str:
    return value if isinstance(value, str) and pattern.fullmatch(value) else ""


def target_from_event(event: object) -> SlackTarget | None:
    """The thread a Slack message event belongs to, or None when it is not one.

    A reply carries its thread's `thread_ts`; a top-level message is its own thread. Only ids of
    Slack's own shapes are kept, so an event cannot smuggle text into a later API call.
    """
    if not isinstance(event, Mapping):
        return None
    channel = _text(event.get("channel"), _CONVERSATION)
    ts = _text(event.get("ts"), _TS)
    thread_ts = _text(event.get("thread_ts"), _TS) or ts
    if not channel or not thread_ts:
        return None
    team = _text(event.get("team"), _TEAM) or _text(event.get("user_team"), _TEAM)
    return SlackTarget(
        channel=channel,
        thread_ts=thread_ts,
        team_id=team,
        user_id=_text(event.get("user"), _PERSON),
        message_ts=ts,
    )


class SlackResolver(Protocol):
    """Who a run answers in Slack, and a client on the bot token."""

    async def target(self, runtime: Any) -> SlackTarget | None: ...

    async def client(self) -> SlackClient | None: ...


TokenSource = Callable[[], Awaitable[str]]


async def _mda_token() -> str:
    from managed_deepagents import connections

    return str(await connections.get(MDA_BOT_TOKEN, {"type": "agent"}))


class _TokenClients:
    """One client per token, replaced once Slack says the token is no good."""

    def __init__(self, token: TokenSource, transport: httpx.AsyncBaseTransport | None) -> None:
        self._token = token
        self._transport = transport
        self._client: SlackClient | None = None
        self._logged = False

    async def client(self) -> SlackClient | None:
        if self._client is not None and not self._client.auth_failed:
            return self._client
        try:
            token = await self._token()
        except Exception as error:  # noqa: BLE001 - presentation goes dark, the run goes on
            if not self._logged:
                self._logged = True
                _LOGGER.warning("[slack] no bot token: %s", type(error).__name__)
            return None
        if not token:
            return None
        if self._client is not None:
            await self._client.aclose()
        self._client = SlackClient(token, transport=self._transport)
        return self._client


class MdaSlackResolver:
    """Managed Deep Agents: `runtime.channel.raw_event` and the managed bot token (module doc)."""

    def __init__(
        self,
        *,
        token: TokenSource = _mda_token,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._clients = _TokenClients(token, transport)

    async def target(self, runtime: Any) -> SlackTarget | None:
        channel = getattr(runtime, "channel", None)
        if channel is None or getattr(channel, "provider", None) != "slack":
            return None
        event = getattr(channel, "event", None)
        if not isinstance(event, Mapping) or event.get("type") != "message":
            return None
        return target_from_event(getattr(channel, "raw_event", None))

    async def client(self) -> SlackClient | None:
        return await self._clients.client()


def event_on_run(runtime: Any) -> Mapping[str, Any] | None:
    """The Bolt event the self-hosted adapter put on a run: `slack_event` in the run's context,
    else in its configurable."""
    context = getattr(runtime, "context", None)
    found = context.get("slack_event") if isinstance(context, Mapping) else None
    if isinstance(found, Mapping):
        return found
    config = getattr(runtime, "config", None)
    if not isinstance(config, Mapping):
        try:
            config = get_config()
        except RuntimeError:
            return None
    found = (config.get("configurable") or {}).get("slack_event")
    return found if isinstance(found, Mapping) else None


class BoltSlackResolver:
    """Self-hosted Slack: a bot token from settings and the Bolt event on the run (module doc)."""

    def __init__(
        self,
        token: str | SecretStr,
        *,
        event_for: Callable[[Any], Mapping[str, Any] | None] = event_on_run,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        secret = token.get_secret_value() if isinstance(token, SecretStr) else token

        async def given() -> str:
            return secret

        self._clients = _TokenClients(given, transport)
        self._event_for = event_for

    async def target(self, runtime: Any) -> SlackTarget | None:
        return target_from_event(self._event_for(runtime))

    async def client(self) -> SlackClient | None:
        return await self._clients.client()


def thread_of(runtime: Any = None) -> str:
    """The run's LangGraph thread id, from the ambient run config or the runtime's own."""
    try:
        config: Mapping[str, Any] = get_config()
    except RuntimeError:
        config = getattr(runtime, "config", None) or {}
    return str((config.get("configurable") or {}).get("thread_id") or "")


class SlackSurface:
    """What the Slack middleware hold: a resolver, each thread's latest target (module doc), and
    one follow-up reader, so progress and steering share each read of a thread.

    `mention_required` is the channel's rule for starting a run in a channel thread: off when
    the Slack channel triggers on every message.
    """

    def __init__(self, resolver: SlackResolver, *, mention_required: bool = True) -> None:
        self.resolver = resolver
        self.follow_ups = FollowUpReader(mention_required=mention_required)
        self._threads: OrderedDict[str, SlackBinding] = OrderedDict()

    async def bind(self, runtime: Any) -> SlackBinding | None:
        """The thread and client for a lead's hook, or None for a run that answers no Slack
        thread. Never raises."""
        try:
            target = await self.resolver.target(runtime)
            thread = thread_of(runtime)
            if target is None:
                known = self._threads.get(thread) if thread else None
                if known is None:
                    return None
                # Same thread, but no message started this run.
                target = replace(known.target, message_ts="")
            client = await self.resolver.client()
        except Exception as error:  # noqa: BLE001 - presentation never costs a run
            _LOGGER.warning("[slack] target not resolved: %s", type(error).__name__)
            return None
        if client is None:
            return None
        binding = SlackBinding(target, client)
        if thread:
            self._threads[thread] = binding
            self._threads.move_to_end(thread)
            while len(self._threads) > THREADS_KEPT:
                self._threads.popitem(last=False)
        return binding

    def bound(self, thread_id: str) -> SlackBinding | None:
        """The binding a lead's run on this thread last resolved (helpers read it)."""
        binding = self._threads.get(thread_id)
        if binding is None or binding.client.auth_failed:
            return None
        return binding
