"""Follow-ups: messages in a run's Slack thread, newer than the one it started from, that would
start a run of their own.

That is the Slack channel's rule: in a channel a message starts a run when it mentions the bot
(unless the channel triggers on every message), and in a DM every message does. A follow-up is
never the bot's own message nor another bot's. Its `text` is Slack markup with the bot's mention
taken out; it is a person's words and is treated as untrusted input like any message.

Reads are shared for `TTL_SECONDS` per thread, so the progress heartbeat and steering together
cost one `conversations.replies` a step at most (Slack allows about 50 a minute per app).
A file a follow-up brings is fetched host-side (`attachment_path` is MDA's own `<id>__<name>`
naming under `/workspace/attachments/`, so a file that arrives both ways is one file).
"""

from __future__ import annotations

import posixpath
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from design_agent.surfaces.slack.client import SlackClient
    from design_agent.surfaces.slack.target import SlackTarget

#: How long one read of a thread serves every caller.
TTL_SECONDS = 15.0
ATTACHMENTS_DIR = "/workspace/attachments"
MAX_FILE_BYTES = 200 * 1024 * 1024
_STOP = re.compile(r"^\s*(stop|cancel|abort|never\s?mind)\b", re.IGNORECASE)
_FILE_ID = re.compile(r"F[A-Z0-9]{6,}")
#: Message subtypes a person's own message carries; joins, edits and bot posts are not follow-ups.
_PEOPLE = frozenset({None, "file_share", "thread_broadcast"})


@dataclass(frozen=True, slots=True)
class FollowUp:
    ts: str
    user: str
    text: str
    files: tuple[Mapping[str, object], ...] = ()


def is_stop(text: str) -> bool:
    """Whether a follow-up asks to drop the work in progress rather than change it."""
    return bool(_STOP.match(text))


def attachment_path(ref: Mapping[str, object]) -> tuple[str, str] | None:
    """Where a Slack file lands in the sandbox and the private URL its bytes come from, or None
    for a file that cannot be staged (external, deleted, too large, malformed)."""
    file_id = ref.get("id")
    url = ref.get("url_private_download") or ref.get("url_private")
    size = ref.get("size", 0)
    if (
        not isinstance(file_id, str)
        or not _FILE_ID.fullmatch(file_id)
        or ref.get("is_external")
        or ref.get("deleted")
        or not isinstance(url, str)
        or not isinstance(size, int)
        or not 0 <= size <= MAX_FILE_BYTES
    ):
        return None
    name = ref.get("name") or ref.get("title") or "file"
    name = posixpath.basename(str(name).replace("\\", "/"))
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:160].strip(".") or "file"
    return f"{ATTACHMENTS_DIR}/{file_id}__{name}", url


class FollowUpReader:
    """Reads a thread's follow-ups, sharing each read for a moment (module doc)."""

    def __init__(self, *, mention_required: bool = True, ttl: float | None = None) -> None:
        self._mention_required = mention_required
        self._ttl = ttl
        self._reads: dict[tuple[str, str, str], tuple[float, list[FollowUp]]] = {}

    async def read(self, client: SlackClient, target: SlackTarget, since: str) -> list[FollowUp]:
        """Follow-ups in `target`'s thread after `since`, oldest first. Raises `SlackError`."""
        key = (target.channel, target.thread_ts, since)
        now, ttl = time.monotonic(), TTL_SECONDS if self._ttl is None else self._ttl
        for stale in [k for k, (at, _) in self._reads.items() if now - at > ttl * 4]:
            del self._reads[stale]
        cached = self._reads.get(key)
        if cached is not None and now - cached[0] < ttl:
            return cached[1]
        me = (await client.identity()).user_id
        found = await client.call(
            "conversations.replies",
            {"channel": target.channel, "ts": target.thread_ts, "oldest": since, "limit": 100},
        )
        mention = f"<@{me}>" if me else ""
        needs_mention = self._mention_required and not target.in_dm
        follow_ups: list[FollowUp] = []
        for message in found.get("messages") or []:
            if not isinstance(message, Mapping):
                continue
            ts, user = message.get("ts"), message.get("user")
            text = str(message.get("text") or "")
            if not isinstance(ts, str) or not isinstance(user, str) or not user or user == me:
                continue
            if message.get("bot_id") or message.get("subtype") not in _PEOPLE:
                continue
            if not _after(ts, since) or (needs_mention and (not mention or mention not in text)):
                continue
            files = tuple(ref for ref in message.get("files") or [] if isinstance(ref, Mapping))
            words = text.replace(mention, "") if mention else text
            follow_ups.append(FollowUp(ts, user, words.strip(), files))
        follow_ups.sort(key=lambda follow_up: float(follow_up.ts))
        self._reads[key] = (now, follow_ups)
        return follow_ups


def _after(ts: str, since: str) -> bool:
    try:
        return float(ts) > float(since or 0)
    except ValueError:
        return False
