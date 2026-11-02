"""Who a run answers in Slack, and the client that may write there: public MDA fields only, the
token only ever in the Authorization header."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from managed_deepagents import ChannelInfo
from pydantic import SecretStr

from design_agent.surfaces.slack.client import SlackClient, SlackError
from design_agent.surfaces.slack.target import (
    BoltSlackResolver,
    MdaSlackResolver,
    SlackSurface,
    target_from_event,
)
from design_agent.testing.fake_slack import CHANNEL, PERSON, TEAM, THREAD_TS, FakeSlack

REPLY_TS = "1712345678.000200"
EVENT = {
    "channel": CHANNEL,
    "ts": REPLY_TS,
    "thread_ts": THREAD_TS,
    "user": PERSON,
    "team": TEAM,
    "text": "hi",
}


def mda_runtime(event: dict[str, Any] | None, kind: str = "message", thread: str = "t-1") -> Any:
    channel = ChannelInfo(name="slack", provider="slack", event={"type": kind}, raw_event=event)  # type: ignore[arg-type]
    return SimpleNamespace(channel=channel, config={"configurable": {"thread_id": thread}})


def test_a_slack_event_names_its_thread_and_nothing_else() -> None:
    target = target_from_event(EVENT)
    assert target is not None
    assert (target.channel, target.thread_ts, target.message_ts) == (CHANNEL, THREAD_TS, REPLY_TS)
    assert (target.team_id, target.user_id) == (TEAM, PERSON)
    top = target_from_event({"channel": CHANNEL, "ts": THREAD_TS})
    assert top is not None and top.thread_ts == THREAD_TS
    assert target_from_event({"channel": "#general", "ts": THREAD_TS}) is None
    assert target_from_event({"channel": CHANNEL, "ts": "soon"}) is None
    assert target_from_event(None) is None


async def test_the_mda_resolver_reads_the_verified_event_and_the_managed_token() -> None:
    fake = FakeSlack()
    asked: list[str] = []

    async def token() -> str:
        asked.append("token")
        return "xoxb-managed"

    resolver = MdaSlackResolver(token=token, transport=fake.transport)
    assert await resolver.target(mda_runtime(EVENT)) == target_from_event(EVENT)
    assert await resolver.target(mda_runtime(None, kind="schedule")) is None
    assert await resolver.target(SimpleNamespace(channel=None)) is None
    client = await resolver.client()
    assert client is not None and await resolver.client() is client and asked == ["token"]
    await client.call("auth.test")
    assert fake.authorizations == {"Bearer xoxb-managed"}


async def test_a_refused_token_is_fetched_again_and_a_missing_one_goes_dark() -> None:
    fake = FakeSlack(refuse={"auth.test": "token_revoked"})
    tokens = iter(["xoxb-old", "xoxb-new"])

    async def token() -> str:
        return next(tokens)

    resolver = MdaSlackResolver(token=token, transport=fake.transport)
    first = await resolver.client()
    assert first is not None
    with pytest.raises(SlackError) as refused:
        await first.call("auth.test")
    assert refused.value.code == "token_revoked" and "xoxb" not in str(refused.value)
    assert await resolver.client() is not first

    async def missing() -> str:
        raise LookupError("no connection")

    assert await MdaSlackResolver(token=missing).client() is None


async def test_the_bolt_resolver_reads_the_event_the_adapter_put_on_the_run() -> None:
    fake = FakeSlack()
    resolver = BoltSlackResolver(SecretStr("xoxb-self-hosted"), transport=fake.transport)
    on_context = SimpleNamespace(context={"slack_event": EVENT})
    on_config = SimpleNamespace(context=None, config={"configurable": {"slack_event": EVENT}})
    assert await resolver.target(on_context) == target_from_event(EVENT)
    assert await resolver.target(on_config) == target_from_event(EVENT)
    assert await resolver.target(SimpleNamespace(context=None, config={})) is None
    client = await resolver.client()
    assert client is not None
    await client.call("auth.test")
    assert fake.authorizations == {"Bearer xoxb-self-hosted"}


async def test_a_run_no_message_started_answers_in_the_threads_last_target() -> None:
    """An MDA wake-up schedule carries no Slack event but posts into the same thread; a helper's
    run has no channel at all and reads what the lead's run resolved."""
    fake = FakeSlack()

    async def token() -> str:
        return "xoxb-managed"

    surface = SlackSurface(MdaSlackResolver(token=token, transport=fake.transport))
    assert await surface.bind(mda_runtime(None, kind="schedule")) is None
    first = await surface.bind(mda_runtime(EVENT))
    woken = await surface.bind(mda_runtime(None, kind="schedule"))
    assert first is not None and woken is not None
    assert woken.target.key == first.target.key and woken.target.message_ts == ""
    assert surface.bound("t-1") is not None and surface.bound("t-other") is None


async def test_the_client_never_puts_the_token_in_a_url_and_reports_codes_only() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": False, "error": "channel_not_found"})

    client = SlackClient("xoxb-secret", transport=httpx.MockTransport(handler))
    with pytest.raises(SlackError) as refused:
        await client.call("chat.postMessage", {"channel": CHANNEL, "blocks": [{"type": "divider"}]})
    assert refused.value.code == "channel_not_found"
    (request,) = seen
    assert "xoxb-secret" not in str(request.url) and "xoxb-secret" not in request.content.decode()
    assert request.headers["authorization"] == "Bearer xoxb-secret"
    assert "xoxb-secret" not in repr(client)
    with pytest.raises(SlackError) as off_slack:
        await client.download("https://example.com/f.png", limit_bytes=10)
    assert off_slack.value.code == "not_a_slack_url" and len(seen) == 1
