"""One live progress message in a Slack thread: a card per step, under a header that says where
the work is.

Slack's agent streaming API is the first choice: `chat.startStream` opens one message,
`chat.appendStream` adds a chunk (a `task_update` card, a `plan_update` header, `markdown_text`),
and `chat.stopStream` closes it. Cards sit in one collapsible group (`task_display_mode=plan`),
titled by a `plan_update` from the first chunk on, so a collapsed group still says what the run
is doing ("Working: Rolling the render"); an untitled group would read "Thinking completed". A
card is keyed by its step: the same id rewrites it in place.

Where streaming is refused (an older workspace, a token type or scope it does not allow), the
same cards go into one `chat.postMessage` that `chat.update` redraws, at most once every
`MIN_UPDATE_SECONDS`, since a redraw per step would run into Slack's rate limits.

Rules every caller relies on:

- Slack failures are swallowed. A failure latches the stream off and leaves what the person has
  seen: the answer posts on its own, so the degraded state is "progress stopped", never "the run
  died". Logs carry Slack's error code or the exception's class name, never text.
- Calls are serialized: a model calls tools in parallel, and two steps arriving before the
  message exists must not each open one.
- A quiet stream is touched every `HEARTBEAT_SECONDS` (a long render is minutes of silence, and
  Slack ends an idle stream): the running card is sent again with how long it has run. The
  heartbeat stops `HEARTBEAT_LIFETIME` after the last real step, so a run that died past every
  handler does not keep a "Working" card alive.
- Titles are plain text. Narration has broadcast mentions defused.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
import weakref
from collections.abc import Awaitable, Callable
from typing import Protocol

from design_agent.surfaces.slack.client import AUTH_ERRORS, SlackClient, SlackError
from design_agent.surfaces.slack.target import SlackTarget

_LOGGER = logging.getLogger(__name__)

Card = dict[str, object]

#: Slack's ceilings: a card's title, one markdown chunk, and one section block's text.
TITLE_LIMIT = 256
TEXT_LIMIT = 12_000
SECTION_LIMIT = 2_900
HEARTBEAT_SECONDS = 30.0
HEARTBEAT_LIFETIME = 3 * 3600.0
MIN_UPDATE_SECONDS = 1.5
#: Refusals no fallback can fix: the stream goes dark instead.
_FINAL = AUTH_ERRORS | {"ratelimited", "channel_not_found", "not_in_channel", "is_archived"}
#: Refusals about one message's fields (`missing_recipient_team_id`), not the workspace: that
#: message falls back, and the next one streams again.
_PER_MESSAGE = ("missing_", "invalid_")
#: Slack closed this message's stream (it ends idle or long streams); the message itself remains,
#: so it carries on as an ordinary message redrawn with `chat.update`.
_STREAM_ENDED = "message_not_in_streaming_state"
#: Steps a fallback message shows while it works; the native stream folds the rest away.
FALLBACK_STEPS = 4
_GLYPHS = {
    "complete": ":heavy_check_mark:",
    "in_progress": ":hourglass_flowing_sand:",
    "error": ":x:",
    "pending": ":white_circle:",
}
_BROADCAST = re.compile(r"<!(channel|here|everyone)[^>]*>")
#: Clients whose workspace refused streaming once: they go straight to the fallback.
_UNSTREAMABLE: weakref.WeakSet[SlackClient] = weakref.WeakSet()


def card(card_id: str, title: str, status: str) -> Card:
    """One step's card. Its id is the step: a new id adds a card, the same id rewrites it."""
    return {"type": "task_update", "id": card_id, "title": title[:TITLE_LIMIT], "status": status}


def elapsed(title: str, seconds: float) -> str:
    """A long step's title with how long it has run, so a quiet card still reads as moving."""
    minutes = int(seconds // 60)
    return f"{title} · {minutes} min" if minutes >= 1 else title


def defuse(text: str) -> str:
    """Narration with `@channel`-style broadcasts turned into plain words."""
    return _BROADCAST.sub(r"@\1", text)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Progress(Protocol):
    """Where a run shows its work, and where it stops."""

    async def step(self, card: Card, header: str = "") -> None: ...

    async def steps(self, cards: list[Card], header: str = "") -> None: ...

    async def text(self, chunk: str) -> None: ...

    async def note(self, line: str) -> None: ...

    async def close(self, header: str = "") -> None: ...

    async def discard(self) -> None: ...


class Silent:
    """A run with no Slack thread behind it says nothing and costs nothing."""

    async def step(self, card: Card, header: str = "") -> None:  # noqa: ARG002 - Progress
        return None

    async def steps(self, cards: list[Card], header: str = "") -> None:  # noqa: ARG002 - Progress
        return None

    async def text(self, chunk: str) -> None:  # noqa: ARG002 - Progress
        return None

    async def note(self, line: str) -> None:  # noqa: ARG002 - Progress
        return None

    async def close(self, header: str = "") -> None:  # noqa: ARG002 - Progress
        return None

    async def discard(self) -> None:
        return None


Beat = Callable[["SlackProgress"], Awaitable[None]]


class SlackProgress:
    """`Progress` in one Slack message (module doc). `on_beat` runs on each heartbeat, before
    the running card is touched (the lead uses it to acknowledge follow-ups)."""

    def __init__(
        self,
        client: SlackClient,
        target: SlackTarget,
        *,
        on_beat: Beat | None = None,
        heartbeat: float | None = None,
        min_update: float | None = None,
    ) -> None:
        self._client = client
        self._target = target
        self._channel = target.channel
        self._on_beat = on_beat
        self._heartbeat = HEARTBEAT_SECONDS if heartbeat is None else heartbeat
        self._min_update = MIN_UPDATE_SECONDS if min_update is None else min_update
        self._ts = ""
        self._streaming = False
        self._dead = False
        self._closed = False
        self._header = ""
        self._lock = asyncio.Lock()
        self._last = time.monotonic()
        self._current: Card | None = None
        self._began: dict[str, float] = {}
        self._beat: asyncio.Task[None] | None = None
        # The fallback message's content, in arrival order.
        self._items: list[tuple[str, str]] = []
        self._cards: dict[str, tuple[str, str]] = {}
        self._drawn = ""
        self._drawn_at = 0.0
        self._redraw: asyncio.Task[None] | None = None

    @property
    def shown(self) -> bool:
        """Whether a message exists in the thread."""
        return bool(self._ts)

    async def step(self, card: Card, header: str = "") -> None:
        await self._emit([card], header)

    async def steps(self, cards: list[Card], header: str = "") -> None:
        await self._emit(list(cards), header)

    async def text(self, chunk: str) -> None:
        if chunk.strip():
            await self._emit([{"type": "markdown_text", "text": defuse(chunk)[:TEXT_LIMIT]}])

    async def note(self, line: str) -> None:
        """A line that is not a step: the heartbeat does not track it."""
        await self._emit(
            [{"type": "markdown_text", "text": defuse(line)[:TEXT_LIMIT]}], track=False
        )

    async def close(self, header: str = "") -> None:
        """Close the message, retitled with `header`. A run that showed nothing posts nothing."""
        await self._finish(header, delete=False)

    async def discard(self) -> None:
        """Close the message and delete it: the run had nothing to tell anyone."""
        await self._finish("", delete=True)

    # -- sending -----------------------------------------------------------------------------

    async def _emit(self, chunks: list[Card], header: str = "", *, track: bool = True) -> None:
        async with self._lock:
            if header and header != self._header:
                self._header = header
                chunks = [{"type": "plan_update", "title": header[:TITLE_LIMIT]}, *chunks]
            if self._dead or not chunks:
                return
            self._apply(chunks)
            try:
                if not self._ts:
                    await self._open(chunks)
                elif self._streaming:
                    await self._append(chunks)
                else:
                    await self._draw()
            except SlackError as error:
                self._stop(error)
                return
            self._last = time.monotonic()
            if track:
                self._track(chunks)
            if self._beat is None and not self._dead:
                self._beat = asyncio.get_running_loop().create_task(self._beating())

    async def _open(self, chunks: list[Card]) -> None:
        if self._client not in _UNSTREAMABLE:
            fields: dict[str, object] = {
                "channel": self._channel,
                "thread_ts": self._target.thread_ts,
                "task_display_mode": "plan",
                "chunks": chunks,
            }
            fields |= await self._recipient()
            try:
                opened = await self._client.call("chat.startStream", fields)
            except SlackError as error:
                if error.code in _FINAL:
                    raise
                if not error.code.startswith(_PER_MESSAGE):
                    _UNSTREAMABLE.add(self._client)
                _LOGGER.info(
                    "[progress] streaming refused (%s); one updated message instead", error.code
                )
            else:
                self._ts, self._streaming = str(opened.get("ts") or ""), True
                self._dead = not self._ts
                return
        text, blocks = self._render()
        posted = await self._client.call(
            "chat.postMessage",
            {
                "channel": self._channel,
                "thread_ts": self._target.thread_ts,
                "text": text,
                "blocks": blocks,
            },
        )
        self._ts = str(posted.get("ts") or "")
        self._channel = str(posted.get("channel") or self._channel)
        self._drawn, self._drawn_at = text + str(blocks), time.monotonic()
        self._dead = not self._ts

    async def _recipient(self) -> dict[str, str]:
        """Who the stream is shown to. Slack refuses a stream in a channel without both halves,
        and some events carry no team (a file upload): those take the token's own workspace."""
        user, team = self._target.user_id, self._target.team_id
        if user and not team:
            with contextlib.suppress(SlackError):
                team = (await self._client.identity()).team_id
        return {"recipient_user_id": user, "recipient_team_id": team} if user and team else {}

    async def _append(self, chunks: list[Card]) -> None:
        try:
            await self._client.call(
                "chat.appendStream", {"channel": self._channel, "ts": self._ts, "chunks": chunks}
            )
        except SlackError as error:
            if error.code != _STREAM_ENDED:
                raise
            self._ended_stream()
            await self._draw(now=True)

    def _ended_stream(self) -> None:
        self._streaming = False
        _LOGGER.info("[progress] Slack ended the stream; updating the message instead")

    def _stop(self, error: SlackError) -> None:
        self._dead = True
        _LOGGER.warning("[progress] Slack progress stopped: %s", error.code)

    # -- the fallback message ----------------------------------------------------------------

    def _apply(self, chunks: list[Card]) -> None:
        for chunk in chunks:
            kind = chunk.get("type")
            if kind == "task_update":
                card_id = str(chunk.get("id"))
                if card_id not in self._cards:
                    self._items.append(("card", card_id))
                self._cards[card_id] = (
                    str(chunk.get("title") or ""),
                    str(chunk.get("status") or ""),
                )
            elif kind == "markdown_text":
                self._items.append(("text", str(chunk.get("text") or "")))

    def _render(self) -> tuple[str, list[dict[str, object]]]:
        """The fallback message: the header, narration, and the latest few steps while working.

        Repeats of a step merge into one line ("Read an image ×3"). A closed message keeps only
        the header and narration, as the native stream folds its steps away.
        """
        # (kind, text or title, status, repeats)
        entries: list[tuple[str, str, str, int]] = []
        for kind, value in self._items:
            if kind == "text":
                entries.append(("text", value.strip(), "", 0))
                continue
            title, status = self._cards[value]
            if entries and entries[-1][:3] == ("card", title, status):
                entries[-1] = ("card", title, status, entries[-1][3] + 1)
            else:
                entries.append(("card", title, status, 1))
        steps = [i for i, entry in enumerate(entries) if entry[0] == "card"]
        hidden = set(steps if self._closed else steps[:-FALLBACK_STEPS])
        earlier = f"… {len(hidden)} earlier step{'s' if len(hidden) > 1 else ''}"
        lines = [earlier] if hidden and not self._closed else []
        for i, (kind, text, status, repeats) in enumerate(entries):
            if kind == "text":
                lines.append(text)
            elif i not in hidden:
                glyph = _GLYPHS.get(status, _GLYPHS["pending"])
                lines.append(f"{glyph} {_escape(text)}{f' ×{repeats}' if repeats > 1 else ''}")
        body, dropped = "\n".join(line for line in lines if line), 0
        while len(body) > SECTION_LIMIT and len(lines) > 1:
            lines.pop(0)
            dropped += 1
            body = "\n".join(["…", *lines])
        header = _escape(self._header or "Working")
        blocks: list[dict[str, object]] = [
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"*{header}*"}]}
        ]
        if body:
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": body[:SECTION_LIMIT]}}
            )
        return self._header or "Working", blocks

    async def _draw(self, *, now: bool = False) -> None:
        """Redraw the fallback message; within `min_update` of the last redraw, once later."""
        wait = self._min_update - (time.monotonic() - self._drawn_at)
        if wait > 0 and not now:
            if self._redraw is None or self._redraw.done():
                self._redraw = asyncio.get_running_loop().create_task(self._draw_later(wait))
            return
        text, blocks = self._render()
        if text + str(blocks) == self._drawn:
            return
        await self._client.call(
            "chat.update",
            {"channel": self._channel, "ts": self._ts, "text": text, "blocks": blocks},
        )
        self._drawn, self._drawn_at = text + str(blocks), time.monotonic()

    async def _draw_later(self, wait: float) -> None:
        await asyncio.sleep(wait)
        async with self._lock:
            if self._dead:
                return
            try:
                await self._draw(now=True)
            except SlackError as error:
                self._stop(error)

    # -- the heartbeat -----------------------------------------------------------------------

    def _track(self, chunks: list[Card]) -> None:
        """Remember which step is running, and since when, for the heartbeat to re-send."""
        for chunk in chunks:
            if chunk.get("type") != "task_update":
                continue
            card_id = str(chunk.get("id"))
            if chunk.get("status") == "in_progress":
                self._current = chunk
                self._began.setdefault(card_id, time.monotonic())
            elif self._current is not None and card_id == str(self._current.get("id")):
                self._current = None

    async def _beating(self) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            while not self._dead:
                await asyncio.sleep(self._heartbeat)
                if time.monotonic() - self._last > HEARTBEAT_LIFETIME:
                    return
                if self._on_beat is not None:
                    try:
                        await self._on_beat(self)
                    except Exception as error:  # noqa: BLE001 - a courtesy, never the keep-alive
                        _LOGGER.debug("[progress] beat hook skipped: %s", type(error).__name__)
                await self._beat_once()

    async def _beat_once(self) -> None:
        """Re-send the running card in place, decided under the lock: a beat that read the card
        before the step finished must not flip a done card back to "Working"."""
        async with self._lock:
            running = self._current
            if running is None or self._dead or not self._ts:
                return
            if time.monotonic() - self._last < self._heartbeat:
                return
            card_id = str(running.get("id"))
            began = self._began.get(card_id, time.monotonic())
            title = elapsed(str(running.get("title") or ""), time.monotonic() - began)
            touched = {**running, "title": title[:TITLE_LIMIT]}
            try:
                if self._streaming:
                    await self._append([touched])
                else:
                    self._cards[card_id] = (title, "in_progress")
                    await self._draw(now=True)
            except SlackError as error:
                self._stop(error)
                return
            self._last = time.monotonic()

    # -- the end -----------------------------------------------------------------------------

    async def _finish(self, header: str, *, delete: bool) -> None:
        for task in (self._beat, self._redraw):
            if task is not None and task is not asyncio.current_task() and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._beat = self._redraw = None
        async with self._lock:
            where = {"channel": self._channel, "ts": self._ts}
            if not self._dead and self._ts and not delete:
                with contextlib.suppress(SlackError):
                    if self._streaming and header and header != self._header:
                        retitle: Card = {"type": "plan_update", "title": header[:TITLE_LIMIT]}
                        await self._append([retitle])
                    if self._streaming:
                        try:
                            await self._client.call("chat.stopStream", where)
                        except SlackError as error:
                            if error.code != _STREAM_ENDED:
                                raise
                            self._ended_stream()
                    if not self._streaming:
                        self._header = header or self._header
                        self._closed = True
                        await self._draw(now=True)
            if delete and self._ts:
                with contextlib.suppress(SlackError):
                    if self._streaming and not self._dead:
                        await self._client.call("chat.stopStream", where)
                    await self._client.call("chat.delete", where)
            self._dead = True
