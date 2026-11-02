"""Live updates for the web app: every change is one small JSON event, fanned out to open streams.

Anything may publish, from the event loop or from a worker thread (a host tool's delivery runs
in one); a stream that falls behind drops its oldest events rather than holding the app up, and
the app re-reads what it shows when it reconnects.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import threading
from collections.abc import AsyncIterator
from typing import Any

Event = dict[str, Any]

#: Events one slow stream may hold before its oldest are dropped.
BACKLOG = 2_000


class Hub:
    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[Event]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._seq = itertools.count(1)
        self._lock = threading.Lock()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, kind: str, **data: Any) -> None:
        with self._lock:
            event: Event = {"type": kind, "seq": next(self._seq), **data}
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._fan_out(event)
        else:
            loop.call_soon_threadsafe(self._fan_out, event)

    def _fan_out(self, event: Event) -> None:
        for queue in list(self._queues):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(event)

    def open(self) -> asyncio.Queue[Event]:
        """A queue that receives every event from now on; `close` it when the stream ends. A
        reader may time out on `get` (to send a keep-alive) without losing the queue."""
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=BACKLOG)
        self._queues.add(queue)
        return queue

    def close(self, queue: asyncio.Queue[Event]) -> None:
        self._queues.discard(queue)

    async def stream(self) -> AsyncIterator[Event]:
        queue = self.open()
        try:
            while True:
                yield await queue.get()
        finally:
            self.close(queue)
