"""The self-hosted Slack adapter on a fake Slack: one turn per post, attachments fetched on the
host, finals uploaded to the thread, replies posted there, other teams and bots ignored."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from design_agent.config import Settings
from design_agent.runtime.local import build_local_runtime
from design_agent.surfaces.slack import BoltSlackResolver, SlackSurface
from design_agent.surfaces.slack.bolt_app import (
    SlackAdapter,
    SlackFileDelivery,
    target_of,
    thread_id_for,
)
from design_agent.testing.fake_slack import BOT, CHANNEL, PERSON, TEAM, FakeSlack
from design_agent.testing.fakes import folder_binding
from design_agent.testing.scripted_model import RespondingChatModel, reply, tool_call
from design_agent.tools.delivery import LocalOutputAdapter

ROOT = Path(__file__).resolve().parents[2]
FILE_URL = "https://files.slack.com/files-pri/T0TESTTEAM1-F0TEST/layout.png"


class Uploads:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def files_upload_v2(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def lead(messages: Sequence[BaseMessage]) -> AIMessage:
    last = messages[-1]
    if isinstance(last, ToolMessage) and last.name == "write_file":
        return tool_call("upload_files", {"paths": ["/workspace/projects/card/card.txt"]})
    if isinstance(last, ToolMessage):
        return reply("Here's the card.")
    return tool_call(
        "write_file", {"file_path": "/workspace/projects/card/card.txt", "content": "card"}
    )


async def test_a_mention_runs_one_turn_and_answers_in_the_thread(tmp_path: Path) -> None:
    fake = FakeSlack(files={FILE_URL: b"png-bytes"})
    uploads = Uploads()
    adapter = SlackAdapter(fake.client(), TEAM, BOT)
    model = RespondingChatModel(respond=lead)
    runtime = build_local_runtime(
        Settings(_env_file=None, workspace_root=tmp_path / "ws"),  # type: ignore[call-arg]
        ROOT,
        model=model,
        binding=folder_binding(tmp_path / "sb", ROOT),
        replies=adapter.post_soon,
        slack=SlackSurface(BoltSlackResolver("xoxb-test-token", transport=fake.transport)),
        surface="slack",
        delivery=SlackFileDelivery(
            "xoxb-test-token", LocalOutputAdapter(tmp_path / "out"), client=uploads
        ),
    )
    adapter.runtime = runtime
    ts = "1712345678.000100"
    event = {
        "type": "app_mention",
        "user": PERSON,
        "team": TEAM,
        "channel": CHANNEL,
        "ts": ts,
        "text": f"<@{BOT}> Make a card from this.",
        "files": [{"name": "layout.png", "url_private_download": FILE_URL}],
    }
    adapter.dispatch(event, mention=True)
    adapter.dispatch({**event, "type": "message"}, mention=True)  # Slack's second delivery
    adapter.dispatch({**event, "ts": "1712345679.000100", "team": "T0OTHERTEAM"}, mention=True)
    adapter.dispatch({**event, "ts": "1712345680.000100", "bot_id": "B0TEST"}, mention=True)
    for _ in range(300):
        if any(
            m == "chat.postMessage" and f.get("text") == "Here's the card." for m, f in fake.calls
        ):
            break
        await asyncio.sleep(0.02)

    thread = thread_id_for(TEAM, CHANNEL, ts)
    assert target_of(thread) == (CHANNEL, ts)
    assert (tmp_path / "sb/workspace/attachments/layout.png").read_bytes() == b"png-bytes"
    assert ("reactions.add", {"channel": CHANNEL, "timestamp": ts, "name": "eyes"}) in fake.calls
    assert [c["channel"] for c in uploads.calls] == [CHANNEL] and uploads.calls[0][
        "thread_ts"
    ] == ts
    assert (tmp_path / "out" / thread / "card.txt").read_text() == "card", (
        "a local copy for the API"
    )
    replies = [
        f for m, f in fake.calls if m == "chat.postMessage" and f.get("text") == "Here's the card."
    ]
    assert len(replies) == 1 and replies[0]["thread_ts"] == ts
    assert model.call_count == 3, "one turn: write, upload, reply"


async def test_quiet_replies_are_not_posted(tmp_path: Path) -> None:
    fake = FakeSlack()
    adapter = SlackAdapter(fake.client(), TEAM, BOT)
    await adapter.post(thread_id_for(TEAM, CHANNEL, "1.000001"), "[quiet]")
    await adapter.post("cli-thread", "hello")
    assert not [m for m, _ in fake.calls if m == "chat.postMessage"]
