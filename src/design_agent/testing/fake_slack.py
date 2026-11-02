"""Slack's Web API, offline: an `httpx.MockTransport` that records every call and keeps the
messages it was asked to post, stream, update and delete.

Ids are synthetic (`TEST` in each). `thread` is what `conversations.replies` returns besides the
bot's own posts; `refuse` maps a method to the error code Slack answers it with; `files` maps a
download URL to its bytes.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

import httpx

from design_agent.surfaces.slack.client import SlackClient
from design_agent.surfaces.slack.target import SlackBinding, SlackResolver, SlackTarget

TEAM = "T0TESTTEAM1"
BOT = "U0TESTBOT01"
PERSON = "U0TESTUSER1"
CHANNEL = "C0TESTCHAN1"
THREAD_TS = "1712345678.000100"
_JSON_FIELDS = ("chunks", "blocks")


@dataclass
class Posted:
    ts: str
    channel: str
    thread_ts: str
    text: str = ""
    blocks: list[Any] = field(default_factory=list)
    chunks: list[dict[str, Any]] = field(default_factory=list)
    streaming: bool = False
    deleted: bool = False


class FakeSlack:
    """See the module doc."""

    def __init__(
        self,
        *,
        refuse: Mapping[str, str] | None = None,
        thread: list[dict[str, Any]] | None = None,
        files: Mapping[str, bytes] | None = None,
    ) -> None:
        self.refuse = dict(refuse or {})
        self.thread = list(thread or [])
        self.files = dict(files or {})
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.posted: dict[str, Posted] = {}
        self.authorizations: set[str] = set()
        self._ts = itertools.count(1)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def client(self, token: str = "xoxb-test-token") -> SlackClient:  # noqa: S107 - a fake token
        return SlackClient(token, transport=self.transport)

    def _next_ts(self) -> str:
        return f"{time.time():.0f}.{next(self._ts):06d}"

    async def handle(self, request: httpx.Request) -> httpx.Response:
        # Steps overlap in a run; a handler that never yields would hide every race.
        await asyncio.sleep(0)
        self.authorizations.add(request.headers.get("authorization", ""))
        if request.method == "GET":
            data = self.files.get(str(request.url))
            return httpx.Response(200, content=data) if data is not None else httpx.Response(404)
        method = request.url.path.removeprefix("/api/")
        fields: dict[str, Any] = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        for key in _JSON_FIELDS:
            if key in fields:
                fields[key] = json.loads(fields[key])
        self.calls.append((method, fields))
        if method in self.refuse:
            return httpx.Response(200, json={"ok": False, "error": self.refuse[method]})
        return httpx.Response(200, json={"ok": True, **self._answer(method, fields)})

    def _answer(self, method: str, fields: dict[str, Any]) -> dict[str, Any]:
        if method == "auth.test":
            return {"team_id": TEAM, "user_id": BOT}
        if method in ("chat.startStream", "chat.postMessage"):
            ts = self._next_ts()
            self.posted[ts] = Posted(
                ts,
                fields["channel"],
                fields.get("thread_ts", ""),
                text=fields.get("text", ""),
                blocks=fields.get("blocks", []),
                chunks=list(fields.get("chunks", [])),
                streaming=method == "chat.startStream",
            )
            return {"ts": ts, "channel": fields["channel"]}
        if method == "chat.appendStream":
            self.posted[fields["ts"]].chunks += fields["chunks"]
        elif method == "chat.update":
            updated = self.posted[fields["ts"]]
            updated.text, updated.blocks = fields.get("text", ""), fields.get("blocks", [])
        elif method == "chat.delete":
            self.posted[fields["ts"]].deleted = True
        elif method == "conversations.replies":
            mine = [
                {"ts": p.ts, "user": BOT, "text": p.text}
                for p in self.posted.values()
                if p.thread_ts == fields.get("ts") and not p.deleted
            ]
            oldest = float(fields.get("oldest") or 0)
            found = [m for m in [*self.thread, *mine] if float(m["ts"]) >= oldest]
            return {"messages": sorted(found, key=lambda m: float(m["ts"]))}
        return {}

    # -- what was sent -----------------------------------------------------------------------

    def methods(self) -> list[str]:
        return [method for method, _ in self.calls]

    def chunks(self) -> list[dict[str, Any]]:
        return [
            chunk
            for method, fields in self.calls
            if method in ("chat.startStream", "chat.appendStream")
            for chunk in fields["chunks"]
        ]

    def cards(self) -> list[tuple[str, str, str]]:
        return [
            (str(c["id"]), str(c["title"]), str(c["status"]))
            for c in self.chunks()
            if c["type"] == "task_update"
        ]

    def headers(self) -> list[str]:
        return [str(c["title"]) for c in self.chunks() if c["type"] == "plan_update"]

    def said(self) -> list[str]:
        return [str(c["text"]) for c in self.chunks() if c["type"] == "markdown_text"]

    def live(self) -> list[Posted]:
        """Messages still in the thread."""
        return [p for p in self.posted.values() if not p.deleted]


class FakeResolver(SlackResolver):
    """A resolver for tests: every run answers `target`, on `fake`'s client; `None` turns it off."""

    def __init__(self, fake: FakeSlack, target: SlackTarget | None = None) -> None:
        self.target_for_runs = target if target is not None else slack_target()
        self._client = fake.client()

    async def target(self, runtime: Any) -> SlackTarget | None:  # noqa: ARG002 - SlackResolver
        return self.target_for_runs

    async def client(self) -> SlackClient | None:
        return self._client


def slack_target(**changes: Any) -> SlackTarget:
    base = {
        "channel": CHANNEL,
        "thread_ts": THREAD_TS,
        "team_id": TEAM,
        "user_id": PERSON,
        "message_ts": THREAD_TS,
    }
    return SlackTarget(**{**base, **changes})


def binding(fake: FakeSlack, **changes: Any) -> SlackBinding:
    return SlackBinding(slack_target(**changes), fake.client())
