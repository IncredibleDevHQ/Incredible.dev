"""`design-agent slack`: the self-hosted Slack app, on Bolt, in one process with the agent.

What it does, mirroring the managed channel:

- A mention in a channel, or a direct message, starts a turn on the Slack thread's agent thread
  (`slack-<team>-<channel>-<thread ts>`). Turns on one thread queue behind each other; a follow-up
  that arrives while a turn runs is folded into it by the steering middleware.
- Slack delivers some events twice (an `app_mention` and a `message` for the same post, retries);
  each post starts at most one turn.
- Files attached to the message are fetched on the host with the bot token (Slack's own hosts
  only, size-capped) and put in the thread's `/workspace/attachments/`.
- The final reply posts to the thread unless it is `[quiet]`; wake-up replies (finished helpers,
  check-ins) post the same way. `upload_files` uploads finals to the thread and keeps a copy in
  `workspace/out/<thread>/` for the API.
- Live progress, the footer and steering come from the shared middleware, through a
  `BoltSlackResolver` that reads the Slack event this adapter puts on the run.

Only the installed workspace is served: an event from another team is ignored. Transport is
Socket Mode (`SLACK_APP_TOKEN`, no public URL) or signed HTTP (`SLACK_SIGNING_SECRET`).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from design_agent.config import Settings
from design_agent.harness import notices
from design_agent.runtime.local import LocalRuntime, final_text
from design_agent.surfaces.slack.client import SlackClient, SlackError
from design_agent.tools.delivery import DeliveredFile, LocalOutputAdapter

_LOGGER = logging.getLogger(__name__)

THREAD = re.compile(r"^slack-(?P<team>[A-Z0-9]+)-(?P<channel>[A-Z0-9]+)-(?P<ts>\d+\.\d+)$")
_MENTION = re.compile(r"<@[A-Z0-9]+>")
MAX_FILES = 10
MAX_FILE_BYTES = 200 * 1024 * 1024
SEEN_KEPT = 2048


def thread_id_for(team: str, channel: str, thread_ts: str) -> str:
    return f"slack-{team}-{channel}-{thread_ts}"


def target_of(thread_id: str) -> tuple[str, str] | None:
    """The Slack channel and thread ts behind an agent thread id, or None for another surface."""
    match = THREAD.match(thread_id)
    return (match["channel"], match["ts"]) if match else None


class SlackFileDelivery:
    """`upload_files` for Slack threads: upload to the thread, and keep a local copy."""

    def __init__(self, token: str, local: LocalOutputAdapter, *, client: Any = None) -> None:
        if client is None:
            from slack_sdk import WebClient

            client = WebClient(token=token)
        self._client = client
        self._local = local

    def deliver(self, thread_id: str, files: Sequence[DeliveredFile]) -> None:
        self._local.deliver(thread_id, files)
        target = target_of(thread_id)
        if target is None:
            return
        channel, thread_ts = target
        self._client.files_upload_v2(
            channel=channel,
            thread_ts=thread_ts,
            file_uploads=[
                {"content": f.content, "filename": f.name, "title": f.name} for f in files
            ],
        )


@dataclass
class SlackAdapter:
    """Turns Slack events into turns and replies (module doc)."""

    client: SlackClient
    team_id: str
    bot_user_id: str
    trigger_on_all_messages: bool = False
    runtime: LocalRuntime | None = None
    _seen: OrderedDict[str, float] = field(default_factory=OrderedDict)
    _tasks: set[asyncio.Task[None]] = field(default_factory=set)

    def accepts(self, event: Mapping[str, Any], *, mention: bool) -> bool:
        if event.get("bot_id") or event.get("subtype") not in (None, "file_share"):
            return False
        if str(event.get("user") or "") in ("", self.bot_user_id):
            return False
        team = str(event.get("team") or event.get("user_team") or self.team_id)
        if team != self.team_id:
            return False
        if mention:
            return True
        direct = event.get("channel_type") == "im"
        in_thread = bool(event.get("thread_ts"))
        return direct or (self.trigger_on_all_messages and in_thread)

    def first_time(self, event: Mapping[str, Any]) -> bool:
        key = f"{event.get('channel')}:{event.get('ts')}"
        if key in self._seen:
            return False
        self._seen[key] = time.time()
        while len(self._seen) > SEEN_KEPT:
            self._seen.popitem(last=False)
        return True

    def dispatch(self, event: Mapping[str, Any], *, mention: bool) -> None:
        """Start handling an event without holding up Bolt's acknowledgement."""
        if not self.accepts(event, mention=mention) or not self.first_time(event):
            return
        task = asyncio.get_running_loop().create_task(self.handle(event), name="slack turn")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def handle(self, event: Mapping[str, Any]) -> None:
        if self.runtime is None:
            raise RuntimeError("wire the runtime before serving")
        channel = str(event["channel"])
        thread_ts = str(event.get("thread_ts") or event["ts"])
        thread = thread_id_for(self.team_id, channel, thread_ts)
        text = _MENTION.sub("", str(event.get("text") or "")).strip()
        try:
            await self.client.call(
                "reactions.add", {"channel": channel, "timestamp": event["ts"], "name": "eyes"}
            )
        except SlackError:
            pass  # presentation only
        attached = await self._attachments(thread, event)
        if attached:
            text = (text + "\n\nAttached: " + ", ".join(attached)).strip()
        try:
            added = await self.runtime.ask(
                text or "(no text)", thread_id=thread, configurable={"slack_event": dict(event)}
            )
        except Exception as error:  # noqa: BLE001 - the person hears that it failed, never silence
            _LOGGER.warning("[slack] the turn failed: %s", type(error).__name__)
            await self.post(
                thread, "Something went wrong on my side; nothing was lost. Try again in a moment."
            )
            return
        await self.post(thread, final_text(added))

    async def _attachments(self, thread: str, event: Mapping[str, Any]) -> list[str]:
        if self.runtime is None:
            return []
        files: list[tuple[str, bytes]] = []
        for item in list(event.get("files") or [])[:MAX_FILES]:
            url = str(item.get("url_private_download") or item.get("url_private") or "")
            name = Path(str(item.get("name") or "attachment")).name
            try:
                files.append((name, await self.client.download(url, limit_bytes=MAX_FILE_BYTES)))
            except SlackError as error:
                _LOGGER.warning("[slack] an attachment was not fetched: %s", error.code)
        return await self.runtime.attach(thread, files) if files else []

    async def post(self, thread: str, text: str) -> None:
        target = target_of(thread)
        if target is None or not text or not notices.should_post(text):
            return
        channel, thread_ts = target
        try:
            await self.client.call(
                "chat.postMessage", {"channel": channel, "thread_ts": thread_ts, "text": text}
            )
        except SlackError as error:
            _LOGGER.warning("[slack] a reply was not posted: %s", error.code)

    def post_soon(self, thread: str, text: str) -> None:
        """The runtime's `replies` callback for wake-up turns (synchronous by contract)."""
        task = asyncio.get_running_loop().create_task(self.post(thread, text), name="slack reply")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


def register(app: Any, adapter: SlackAdapter) -> None:
    """Bolt handlers: mentions everywhere, direct messages, and thread replies when configured."""

    async def on_mention(event: dict[str, Any]) -> None:
        adapter.dispatch(event, mention=True)

    async def on_message(event: dict[str, Any]) -> None:
        mentioned = f"<@{adapter.bot_user_id}>" in str(event.get("text") or "")
        adapter.dispatch(event, mention=mentioned)

    app.event("app_mention")(on_mention)
    app.event("message")(on_message)


async def serve(project_root: Path, settings: Settings) -> None:
    """Run the Slack app until stopped (module doc)."""
    from slack_bolt.async_app import AsyncApp

    from design_agent.runtime import maintenance
    from design_agent.runtime.local import build_local_runtime
    from design_agent.runtime.persistence import open_persistence, workspace_of
    from design_agent.surfaces.slack import BoltSlackResolver, SlackSurface
    from design_agent.tools.mcp import load_mcp_tools, servers_for_runtime
    from design_agent.tools.paper import PaperPolicy, admit_paper_tools

    if settings.slack_bot_token is None:
        raise SystemExit("SLACK_BOT_TOKEN is not set")
    token = settings.slack_bot_token.get_secret_value()
    client = SlackClient(token)
    identity = await client.identity()
    adapter = SlackAdapter(
        client, identity.team_id, identity.user_id, settings.slack_trigger_on_all_messages
    )
    servers = servers_for_runtime(project_root, settings, "self_hosted")
    loaded = await load_mcp_tools(servers)
    servers = [s for s in servers if s.name not in loaded.failed]
    tools = admit_paper_tools(loaded.tools, PaperPolicy.from_settings(settings))
    workspace = workspace_of(settings, project_root)
    async with open_persistence(settings, workspace) as (checkpointer, store):
        runtime = build_local_runtime(
            settings,
            project_root,
            checkpointer=checkpointer,
            store=store,
            replies=adapter.post_soon,
            mcp_servers=servers,
            mcp_tools=tools,
            slack=SlackSurface(
                BoltSlackResolver(token),
                mention_required=not settings.slack_trigger_on_all_messages,
            ),
            surface="slack",
            delivery=SlackFileDelivery(token, LocalOutputAdapter(workspace / "out")),
        )
        adapter.runtime = runtime
        await maintenance.start(runtime, store)
        keeper = asyncio.get_running_loop().create_task(
            maintenance.run(runtime, store), name="maintenance"
        )
        signing = (
            settings.slack_signing_secret.get_secret_value()
            if settings.slack_signing_secret
            else None
        )
        app = AsyncApp(
            token=token, signing_secret=signing, request_verification_enabled=signing is not None
        )
        register(app, adapter)
        try:
            await _serve_transport(app, settings)
        finally:
            keeper.cancel()
            await runtime.services.aclose()
            if runtime.binding.runner is not None:
                runtime.binding.runner.stop_all()
            await client.aclose()


async def _serve_transport(app: Any, settings: Settings) -> None:
    if settings.slack_transport == "socket_mode":
        from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

        if settings.slack_app_token is None:
            raise SystemExit("Socket Mode needs SLACK_APP_TOKEN (or set SLACK_TRANSPORT=http)")
        socket: Any = AsyncSocketModeHandler(app, settings.slack_app_token.get_secret_value())
        await socket.start_async()
        return
    if settings.slack_signing_secret is None:
        raise SystemExit("HTTP mode needs SLACK_SIGNING_SECRET to verify Slack's requests")
    import uvicorn
    from fastapi import FastAPI, Request
    from slack_bolt.adapter.starlette.async_handler import AsyncSlackRequestHandler

    handler = AsyncSlackRequestHandler(app)
    web = FastAPI(docs_url=None, redoc_url=None)

    @web.post("/slack/events")
    async def events(request: Request) -> Any:
        return await handler.handle(request)

    server = uvicorn.Server(
        uvicorn.Config(web, host=settings.api_host, port=settings.api_port, log_level="info")
    )
    await server.serve()
