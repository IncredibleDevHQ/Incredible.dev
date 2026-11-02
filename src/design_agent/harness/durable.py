"""Durable helpers: a background helper saves its transcript as it works and resumes from it.

A helper is an asyncio task in the server process, so a deploy or a restart kills it. Without a
saved transcript the lead can only re-issue the brief, and a long builder starts over from the
files and progress notes on disk.

- `TranscriptCheckpointMiddleware`, on each worker, saves the helper's history to the deployment
  store as it goes: the tool results before each model call, the model's reply after it
  (`TranscriptStore`: one item per chunk, under the task `CURRENT_TASK` names).
- After a restart the lead calls `resume_task(id)`, which starts the same worker with
  `resume_brief(id)`. The middleware's before-agent hook swaps that one-line brief for the saved
  transcript and a closing note, and the helper carries on from its last step.

What is saved is always valid to send back, and small:
- images the helper viewed become a text stub naming the file (`[image you viewed: <path>]`), so it
  re-opens the ones it still needs; other media it opened likewise;
- thinking blocks are dropped: a provider may reject replayed thinking once the history before it
  was edited, and accepts the same history with the thinking stripped;
- a tool call the restart cut off gets a result saying so, and that its effect is unknown;
- past `max_bytes`, the oldest steps after the brief are dropped, with a marker where they were.

Deep Agents' `AsyncSubAgentMiddleware` gets this by running subagents as checkpointed server runs,
but those run on threads of their own, without the lead's sandbox. When the runtime can run a
background subagent on the lead's sandbox, this becomes LangGraph's own checkpoint; the stub rules
stay if replay still needs them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    ToolMessage,
    messages_from_dict,
    messages_to_dict,
)
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime
from langgraph.store.base import PutOp
from langgraph.types import Command

_LOGGER = logging.getLogger(__name__)

#: The background task whose helper is running, by id (None in the lead). The host sets it around
#: each helper's run; the helper's transcript is saved under it.
CURRENT_TASK: ContextVar[str | None] = ContextVar("harness_durable_task", default=None)

#: A brief that starts with this resumes the task it names: `[resume t-abc123]`.
RESUME_MARKER_PREFIX = "[resume "
_MARKER = re.compile(r"\[resume ([^\]\s]+)\]")

#: Each task's chunks live under `(*NAMESPACE, <task_id>)`.
NAMESPACE = ("harness", "transcripts")
MAX_BYTES = 8_000_000
#: Where the store supports TTL, a transcript expires a week after it was last written or read.
TTL_MINUTES = 7 * 24 * 60
#: How long `save_on_cancel` may hold up a shutdown.
CANCEL_FLUSH_SECONDS = 10.0
_PAGE = 500

#: Content blocks holding thinking (`reasoning` is LangChain's standard name for the same thing).
_THINKING = frozenset({"thinking", "redacted_thinking", "reasoning"})
#: Content blocks holding media, and what their stub calls them.
_MEDIA = {
    "image": "image",
    "image_url": "image",
    "audio": "audio",
    "video": "video",
    "file": "file",
}


# -- the store --------------------------------------------------------------------------------


@dataclass
class _Writer:
    """One task's saved chunks as `append` tracks them: sequence numbers and sizes, oldest first."""

    kept: list[tuple[int, int]] = field(default_factory=list)
    total: int = 0
    next_seq: int = 0
    #: Tool call id -> the file it opened, for the stub of an image in its result.
    paths: dict[str, str] = field(default_factory=dict)

    @classmethod
    def of(cls, chunks: Sequence[tuple[int, Mapping[str, Any]]]) -> _Writer:
        kept = [(seq, int(value.get("bytes") or 0)) for seq, value in chunks]
        return cls(kept, sum(size for _, size in kept), kept[-1][0] + 1 if kept else 0)


class TranscriptStore:
    """A helper's message history in the deployment store, saved in chunks as it grows.

    Namespace `("harness", "transcripts", <task_id>)`: one item per `append`, keyed by a zero-padded
    sequence number, holding the messages as `messages_to_dict` writes them. Messages are cleaned on
    the way in (module doc), and `load` answers every tool call, so a loaded history is always one a
    model accepts. Past `max_bytes` the oldest chunks after the first (the brief) are deleted, and
    `load` puts a marker where they were. `store` is LangGraph's `BaseStore`.
    """

    def __init__(self, store: Any, *, max_bytes: int = MAX_BYTES) -> None:
        self.store = store
        self.max_bytes = max_bytes
        self._writers: dict[str, _Writer] = {}

    @staticmethod
    def namespace(task_id: str) -> tuple[str, ...]:
        return (*NAMESPACE, task_id)

    async def append(self, task_id: str, messages: Sequence[BaseMessage]) -> None:
        """Save `messages` as the next chunk of `task_id`'s transcript."""
        writer = self._writers.get(task_id)
        if writer is None:
            writer = self._writers.setdefault(task_id, _Writer.of(await self._chunks(task_id)))
        cleaned = [
            kept for message in messages if (kept := _clean(message, writer.paths)) is not None
        ]
        if not cleaned:
            return
        text = json.dumps({"messages": messages_to_dict(cleaned), "at": time.time()}, default=str)
        seq, size = writer.next_seq, len(text)
        await self._put(task_id, seq, {**json.loads(text), "bytes": size})
        # Counted only once written: a failed put leaves no gap, which `load` would read as a drop.
        writer.next_seq = seq + 1
        writer.kept.append((seq, size))
        writer.total += size
        while writer.total > self.max_bytes and len(writer.kept) > 2:
            dropped, dropped_size = writer.kept.pop(1)
            await self.store.adelete(self.namespace(task_id), _key(dropped))
            writer.total -= dropped_size

    async def load(self, task_id: str) -> list[BaseMessage]:
        """The saved history, ready to send: cleaned, in order, every tool call answered."""
        return (await self._read(task_id))[0]

    async def delete(self, task_id: str) -> None:
        self._writers.pop(task_id, None)
        chunks = await self._chunks(task_id)
        if chunks:
            namespace = self.namespace(task_id)
            await self.store.abatch([PutOp(namespace, _key(seq), None) for seq, _ in chunks])

    async def exists(self, task_id: str) -> bool:
        # The first chunk (the brief) is written first and never dropped.
        return await self.store.aget(self.namespace(task_id), _key(0)) is not None

    async def _read(self, task_id: str) -> tuple[list[BaseMessage], float | None]:
        """The saved history, and when its last chunk was written."""
        chunks = await self._chunks(task_id)
        self._writers.setdefault(task_id, _Writer.of(chunks))
        messages: list[BaseMessage] = []
        previous: int | None = None
        for seq, value in chunks:
            if previous is not None and seq > previous + 1:
                messages.append(_dropped(seq - previous - 1))
            messages.extend(messages_from_dict(list(value.get("messages") or [])))
            previous = seq
        saved_at = float(chunks[-1][1].get("at") or 0.0) if chunks else None
        return _sendable(messages), saved_at

    async def _copy(self, source: str, target: str) -> None:
        """Start `target`'s transcript as a copy of `source`'s: a resume under a new id."""
        chunks = await self._chunks(source)
        for seq, value in chunks:
            await self._put(target, seq, dict(value))
        self._writers[target] = _Writer.of(chunks)

    async def _chunks(self, task_id: str) -> list[tuple[int, Mapping[str, Any]]]:
        """Every saved chunk of `task_id`, oldest first."""
        namespace = self.namespace(task_id)
        found: dict[int, Mapping[str, Any]] = {}
        offset = 0
        while True:
            page = await self.store.asearch(namespace, limit=_PAGE, offset=offset)
            for item in page:
                # A store may match the namespace as a text prefix: keep this task's own items.
                if tuple(item.namespace) == namespace and item.key.isdigit():
                    found[int(item.key)] = item.value or {}
            if len(page) < _PAGE:
                return sorted(found.items())
            offset += len(page)

    async def _put(self, task_id: str, seq: int, value: dict[str, Any]) -> None:
        # `index=False`: a store with a semantic index would otherwise embed every chunk.
        ttl = {"ttl": TTL_MINUTES} if getattr(self.store, "supports_ttl", False) else {}
        await self.store.aput(self.namespace(task_id), _key(seq), value, index=False, **ttl)


def _key(seq: int) -> str:
    return f"{seq:08d}"


def _clean(message: BaseMessage, paths: dict[str, str]) -> BaseMessage | None:
    """`message` as it is saved: thinking dropped, media as a stub naming its file, no tool
    artifact (the model never saw it). None for a model reply left with nothing to send."""
    if isinstance(message, AIMessage):
        for call in message.tool_calls:
            if call.get("id") and (path := _path_of(call.get("args"))):
                paths[str(call["id"])] = path
    update: dict[str, Any] = {}
    if isinstance(message, ToolMessage) and message.artifact is not None:
        update["artifact"] = None
    content: Any = message.content
    if isinstance(content, list):
        opened = message.additional_kwargs.get("read_file_path")  # deepagents' read_file sets it
        if isinstance(message, ToolMessage):
            opened = paths.get(message.tool_call_id) or opened
        blocks: list[Any] = []
        changed = False
        for block in content:
            kind = block.get("type") if isinstance(block, dict) else None
            if kind in _THINKING or kind in _MEDIA:
                changed = True
                if kind in _MEDIA:
                    blocks.append(_stub(_MEDIA[kind], opened))
            else:
                blocks.append(block)
        if changed:
            update["content"] = content = blocks
    parts = content if isinstance(content, list) else [content]
    if isinstance(message, AIMessage) and not message.tool_calls and not any(map(_says, parts)):
        return None
    return message.model_copy(update=update) if update else message


def _path_of(args: object) -> str | None:
    if isinstance(args, Mapping):
        for name in ("file_path", "path"):
            value = args.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _stub(kind: str, path: object) -> dict[str, str]:
    verb = "viewed" if kind == "image" else "opened"
    text = f"[{kind} you {verb}: {path}]" if isinstance(path, str) and path else None
    return {"type": "text", "text": text or f"[{kind} you {verb} earlier]"}


def _says(block: object) -> bool:
    """Whether a content block carries anything a model would be sent."""
    if isinstance(block, str):
        return bool(block.strip())
    if isinstance(block, Mapping) and block.get("type") == "text":
        return bool(str(block.get("text") or "").strip())
    return block is not None


def _sendable(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """The saved history as a model accepts it: each message once, every tool result answering a
    call before it (a result whose call was dropped with earlier work goes too), and every call
    with exactly one result."""
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    ids: set[str] = set()
    called: set[str] = set()
    seen: set[str] = set()
    owed: list[ToolMessage] = []
    sendable: list[BaseMessage] = []
    for message in messages:
        if message.id is not None:
            if message.id in ids:  # saved twice: a shutdown cut a save short and it was retried
                continue
            ids.add(message.id)
        if isinstance(message, ToolMessage):
            if message.tool_call_id in called and message.tool_call_id not in seen:
                seen.add(message.tool_call_id)
                sendable.append(message)
            continue
        sendable += owed
        owed = []
        sendable.append(message)
        if isinstance(message, AIMessage):
            for call in (*message.tool_calls, *message.invalid_tool_calls):
                if call_id := call.get("id"):
                    called.add(call_id)
                    if call_id not in answered:
                        owed.append(_interrupted(call))
    sendable += owed
    for message in sendable:
        if message.id is None:
            message.id = str(uuid.uuid4())
    return sendable


def _interrupted(call: Mapping[str, Any]) -> ToolMessage:
    name = str(call.get("name") or "tool")
    if call.get("type") == "invalid_tool_call":
        text = f"{name} did not run: its arguments were malformed or cut off."
    else:
        text = (
            f"{name} was interrupted by the restart before it returned, so whether it took effect "
            "is unknown. Check its output before running it again."
        )
    return ToolMessage(content=text, tool_call_id=str(call["id"]), name=name, status="error")


def _dropped(chunks: int) -> HumanMessage:
    return HumanMessage(
        content=(
            f"[Earlier work was dropped here to keep this transcript small: {chunks} saved steps. "
            "What they made is in the project's files.]"
        )
    )


# -- the helper's side --------------------------------------------------------------------------


@dataclass
class _Progress:
    """How much of one running task's history is saved, in this process."""

    transcripts: TranscriptStore
    #: The history as last seen (the state's messages, then the model's reply) and how much of it
    #: is saved; `last_id` is the id of the last saved message, to notice a rewritten history.
    history: list[BaseMessage] = field(default_factory=list)
    saved: int = 0
    last_id: str | None = None
    #: Tool results that came back since the last save, not yet in the state: what
    #: `save_on_cancel` adds when a restart hits while a sibling call still runs.
    returned: list[ToolMessage] = field(default_factory=list)

    async def save(self, task_id: str, history: list[BaseMessage]) -> None:
        """Append what `history` adds to what is saved. A history that no longer starts with what
        was saved (a middleware rewrote it) is saved again from the start."""
        self.history = history
        rewritten = self.saved > len(history) or (
            self.saved > 0 and history[self.saved - 1].id != self.last_id
        )
        try:
            if rewritten:
                await self.transcripts.delete(task_id)
                self.saved = 0
            delta = history[self.saved :]
            if delta:
                await self.transcripts.append(task_id, delta)
        except Exception as error:  # noqa: BLE001 - the next save retries what this one missed
            _LOGGER.warning("[harness] saving %s's transcript failed: %s", task_id, error)
            return
        self.saved, self.last_id = len(history), history[-1].id if history else None
        answered = {m.tool_call_id for m in delta if isinstance(m, ToolMessage)}
        self.returned = [m for m in self.returned if m.tool_call_id not in answered]


#: Per running task, in this process: what the middleware saved, and what `save_on_cancel` flushes.
_PROGRESS: dict[str, _Progress] = {}

#: Returns the deployment store for the running helper, or None.
StoreGetter = Callable[[], Any]


class TranscriptCheckpointMiddleware(AgentMiddleware):
    """Saves a helper's transcript as it works, and resumes it from a `resume_brief` (module doc).

    Put it on each background worker. It saves only while `CURRENT_TASK` names a task, so the same
    worker run in the lead's turn saves nothing. Around each model call it saves the tool results
    that came back since the last call, then the model's reply: every step is in the store before
    the next one starts, at no extra graph step. `store_getter` returns the deployment store; a
    detached helper's own runtime has none (the host strips LangGraph's per-run config), so the host
    hands it over. The hook's `runtime.store` is the fallback.
    """

    def __init__(
        self, store_getter: StoreGetter | None = None, *, max_bytes: int = MAX_BYTES
    ) -> None:
        super().__init__()
        self._store_getter = store_getter
        self._max_bytes = max_bytes

    def _open(self, runtime: object) -> TranscriptStore | None:
        store = self._store_getter() if self._store_getter is not None else None
        if store is None:
            store = getattr(runtime, "store", None)
        return None if store is None else TranscriptStore(store, max_bytes=self._max_bytes)

    async def abefore_agent(
        self, state: AgentState, runtime: Runtime[Any]
    ) -> dict[str, Any] | None:
        """A fresh brief starts a fresh transcript; a resume brief is swapped for the saved one.

        The swap starts with `RemoveMessage(REMOVE_ALL_MESSAGES)`: LangGraph's `add_messages` and
        deepagents' messages reducer both drop everything before it (the one-line brief), so the
        state becomes the restored history plus the closing note instead of growing by them.
        """
        task_id = CURRENT_TASK.get()
        if task_id:
            _PROGRESS.pop(task_id, None)
        resumed = _resumed_task(state.get("messages") or [])
        if resumed is None:
            if task_id and (transcripts := self._open(runtime)) is not None:
                _PROGRESS[task_id] = _Progress(transcripts)
                try:
                    await transcripts.delete(task_id)
                except Exception as error:  # noqa: BLE001 - a leftover only lengthens a resume
                    _LOGGER.warning("[harness] clearing %s's transcript failed: %s", task_id, error)
            return None
        transcripts = self._open(runtime)
        if transcripts is None:
            return None
        try:
            restored, saved_at = await transcripts._read(resumed)
            if restored and task_id and task_id != resumed:
                await transcripts._copy(resumed, task_id)
        except Exception as error:  # noqa: BLE001 - the brief itself says nothing was restored
            _LOGGER.warning("[harness] restoring %s's transcript failed: %s", resumed, error)
            return None
        if not restored:
            return None
        if task_id:
            _PROGRESS[task_id] = _Progress(
                transcripts, history=restored, saved=len(restored), last_id=restored[-1].id
            )
        closing = HumanMessage(content=_closing(saved_at), id=str(uuid.uuid4()))
        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *restored, closing]}

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        task_id = CURRENT_TASK.get()
        progress = _PROGRESS.get(task_id) if task_id else None
        if progress is None and task_id:
            transcripts = self._open(request.runtime)
            if transcripts is not None:
                progress = _PROGRESS[task_id] = _Progress(transcripts)
        messages = _messages(request.state)
        if progress is None or task_id is None or not messages:
            return await handler(request)
        await progress.save(task_id, messages)
        response = await handler(request)
        replies = list(response.result)
        for message in replies:
            if message.id is None:  # so the next save finds the reply in the state by its id
                message.id = str(uuid.uuid4())
        await progress.save(task_id, [*progress.history, *replies])
        return response

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        result = await handler(request)
        task_id = CURRENT_TASK.get()
        progress = _PROGRESS.get(task_id) if task_id else None
        if progress is not None:
            progress.returned.extend(_tool_messages(result))
        return result

    async def aafter_agent(self, state: AgentState, runtime: Runtime[Any]) -> None:  # noqa: ARG002
        task_id = CURRENT_TASK.get()
        progress = _PROGRESS.pop(task_id, None) if task_id else None
        messages = _messages(state)
        if progress is not None and task_id is not None and messages:
            await progress.save(task_id, messages)


def _messages(state: object) -> list[BaseMessage]:
    """The state's messages; empty for a state without them (then nothing is saved, and nothing
    already saved is taken for rewritten)."""
    messages = state.get("messages") if isinstance(state, Mapping) else None
    return list(messages) if isinstance(messages, list) else []


def _resumed_task(messages: Sequence[Any]) -> str | None:
    """The task a resume brief names, from the first human message; None for any other brief."""
    first = next((m for m in messages if isinstance(m, HumanMessage)), None)
    if first is None:
        return None
    text = _text(first.content).lstrip()
    match = _MARKER.match(text) if text.startswith(RESUME_MARKER_PREFIX) else None
    return match.group(1) if match else None


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else str(block.get("text") or "")
            for block in content
            if isinstance(block, str)
            or (isinstance(block, Mapping) and block.get("type") == "text")
        )
    return ""


def _tool_messages(result: object) -> list[ToolMessage]:
    if isinstance(result, ToolMessage):
        return [result]
    update = getattr(result, "update", None)  # a Command
    messages = update.get("messages") if isinstance(update, Mapping) else None
    return [m for m in messages or () if isinstance(m, ToolMessage)]


def _closing(saved_at: float | None) -> str:
    at = datetime.fromtimestamp(saved_at or time.time(), UTC).strftime("%H:%M UTC")
    return (
        f"You were interrupted at {at} (a restart or a stop). Everything above is your own work so "
        "far; images you viewed are replaced by their file paths, so re-open any you need. Continue "
        "from where you stopped; don't redo finished steps. Your brief is the first message."
    )


# -- the host's side ----------------------------------------------------------------------------


def resume_brief(task_id: str) -> str:
    """The brief that resumes `task_id`: the worker's `TranscriptCheckpointMiddleware` swaps it for
    the saved transcript before the first model call. The rest of the text reaches the model only
    if nothing could be restored."""
    return (
        f"{RESUME_MARKER_PREFIX}{task_id}] This brief resumes task {task_id} from its saved "
        "transcript, and you are reading it because the transcript could not be restored. Reply in "
        "one line that there was nothing to resume from, so the lead re-issues the task."
    )


async def can_resume(store: Any, task_id: str) -> bool:
    """Whether `task_id` saved a transcript to resume from."""
    if store is None or not task_id:
        return False
    try:
        return await TranscriptStore(store).exists(task_id)
    except Exception as error:  # noqa: BLE001 - unknown means no: the lead re-issues the brief
        _LOGGER.warning("[harness] checking %s's transcript failed: %s", task_id, error)
        return False


async def save_on_cancel(
    task_id: str | None = None, *, timeout: float = CANCEL_FLUSH_SECONDS
) -> int:
    """A best-effort flush for a helper whose coroutine is being cancelled (a shutdown's drain).

    Every step is saved as it happens; what can be left is what came back since the last save (the
    results of calls that finished while a sibling still ran) and a save that failed. Call it in
    the helper's `except asyncio.CancelledError` before re-raising. It never raises and gives up
    after `timeout` seconds, so it cannot hold up a shutdown. Returns how many messages it saved.
    """
    task_id = task_id or CURRENT_TASK.get()
    progress = _PROGRESS.pop(task_id, None) if task_id else None
    if progress is None or task_id is None:
        return 0
    unsaved = list(progress.history[progress.saved :])
    answered = {m.tool_call_id for m in unsaved if isinstance(m, ToolMessage)}
    unsaved += [m for m in progress.returned if m.tool_call_id not in answered]
    if not unsaved:
        return 0
    flush = asyncio.shield(progress.transcripts.append(task_id, unsaved))
    try:
        await asyncio.wait_for(flush, timeout)
    except (Exception, asyncio.CancelledError) as error:  # noqa: BLE001 - best effort at shutdown
        _LOGGER.warning("[harness] flushing %s's transcript failed: %r", task_id, error)
        return 0
    return len(unsaved)
