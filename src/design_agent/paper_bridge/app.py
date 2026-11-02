"""The Paper bridge: a bearer-authenticated MCP proxy in front of a Paper Desktop the person runs.

It runs on the machine with Paper Desktop (`design-agent paper-bridge`), binds 127.0.0.1 by
default, and is exposed only through a tunnel the person owns (docs/partners/paper.md). Before a
request reaches the MCP endpoint, in order: its Host (and any Origin) must name this bridge, which
stops DNS rebinding; its bearer token must match, compared in constant time; and its path must be
the MCP path. Behind that, every call goes through the same `PaperPolicy` the agent's host applies
(`tools.paper`), and, with a team configured, Paper Desktop must report that team and a call may
only name a file in it.

Only tools are proxied; Paper's resources and prompts are not offered. A failure in Desktop or the
transport comes back as one sentence, never its internals. Desktop writes an export to this
machine's Downloads folder and answers with the paths, which mean nothing to a remote agent, so the
bridge reads the files it just wrote and returns their bytes instead (`tools.paper.take_exports`).
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import json
import logging
import re
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastmcp import Client
from fastmcp.exceptions import PromptError, ResourceError
from fastmcp.server import create_proxy
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import BlobResourceContents, EmbeddedResource, ImageContent, TextContent
from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from design_agent.tools.paper import (
    EXPORT_TOOLS,
    GLOBAL_TOOLS,
    PaperPolicy,
    check_catalog,
    exported_paths,
    log_catalog,
    take_exports,
)

_LOGGER = logging.getLogger(__name__)

MCP_PATH = "/mcp"
DEFAULT_PORT = 29980
#: 32 random bytes, URL-safe base64: what `secrets.token_urlsafe(32)` prints.
MIN_TOKEN_CHARS = 43
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
#: Paper lists at most this many resources per call (partner question: pagination beyond it).
LISTING_LIMIT = 200
TEAM_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

DESKTOP_UNAVAILABLE = (
    "Paper Desktop did not answer; check that it is open with a file, then try again."
)
TEAM_DRIFT = "Paper Desktop is not in the team this bridge serves; switch teams in Paper Desktop, then try again."
TEAM_UNREADABLE = "Paper Desktop did not say which team it is in, so this bridge refuses the call."
FOREIGN_FILE = "That Paper file is not in the team this bridge serves; pass a file from that team."
NOT_OFFERED = "This bridge offers Paper's tools only."


class BridgeConfigError(ValueError):
    """The bridge would start in a state it must not serve."""


def check_token(token: str) -> None:
    if len(token) < MIN_TOKEN_CHARS or not token.isascii() or any(c.isspace() for c in token):
        raise BridgeConfigError(
            "Set PAPER_BRIDGE_TOKEN to at least 32 random bytes, for example the output of "
            '`python -c "import secrets; print(secrets.token_urlsafe(32))"`'
        )


_HOST_HEADER = re.compile(r"(?P<name>[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])(?::\d{1,5})?")


def _host(header: str) -> str:
    """The lowercase hostname a Host header names, or "" for anything that is not one."""
    match = _HOST_HEADER.fullmatch(header.strip())
    return match["name"].strip("[]").lower() if match else ""


def _origin_host(origin: str) -> str:
    """The lowercase hostname of a browser Origin, or "" for one carrying anything else."""
    try:
        parts = urlsplit(origin.strip())
        parts.port  # noqa: B018 - raises on a malformed port
    except ValueError:
        return ""
    if (
        parts.scheme not in ("http", "https")
        or parts.username
        or parts.password
        or parts.path not in ("", "/")
    ):
        return ""
    return (parts.hostname or "").lower()


def allowed_hostnames(extra: Iterable[str] = ()) -> frozenset[str]:
    """Loopback plus each tunnel hostname given; a name with a scheme, path or port is refused."""
    names = set(LOOPBACK_HOSTS)
    for raw in extra:
        name = raw.strip().lower()
        if not re.fullmatch(
            r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+", name
        ):
            raise BridgeConfigError(
                f"--allow-host takes a bare hostname such as paper.example.com, not {raw!r}"
            )
        names.add(name)
    return frozenset(names)


class BridgeGuard:
    """Host and Origin, then the bearer token, then the path; everything else is the proxy's."""

    def __init__(
        self, app: ASGIApp, *, token: str, hostnames: frozenset[str], path: str = MCP_PATH
    ) -> None:
        self.app = app
        self.expected = f"Bearer {token}".encode()
        self.hostnames = hostnames
        self.path = path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if _host(headers.get("host", "")) not in self.hostnames:
            response = PlainTextResponse("Misdirected Request", status_code=421)
        elif origin is not None and _origin_host(origin) not in self.hostnames:
            response = PlainTextResponse("Forbidden", status_code=403)
        elif not hmac.compare_digest(headers.get("authorization", "").encode(), self.expected):
            response = PlainTextResponse(
                "Unauthorized", status_code=401, headers={"WWW-Authenticate": "Bearer"}
            )
        elif scope["path"] != self.path:
            response = PlainTextResponse("Not Found", status_code=404)
        else:
            await self.app(scope, receive, send)
            return
        await response(scope, receive, send)


def _text(sentence: str) -> ToolResult:
    return ToolResult(content=[TextContent(type="text", text=sentence)], is_error=True)


def _json_object(result: Any) -> dict[str, Any] | None:
    if getattr(result, "is_error", False):
        return None
    for block in getattr(result, "content", None) or []:
        if getattr(block, "type", None) == "text":
            try:
                value = json.loads(block.text)
            except ValueError:
                continue
            if isinstance(value, dict):
                return value
    structured = getattr(result, "structured_content", None)
    return structured if isinstance(structured, dict) else None


def _in_team(item: object, kinds: tuple[str, ...] = ("file",)) -> bool:
    """Paper lists open files from other teams first, without timestamps; only items with both
    timestamps belong to the active team."""
    return (
        isinstance(item, dict)
        and item.get("type") in kinds
        and isinstance(item.get("id"), str)
        and type(item.get("createdAt")) in (int, float)
        and type(item.get("updatedAt")) in (int, float)
    )


class TeamScope:
    """Paper Desktop must be in `team_id`, and a call may only name that team's files.

    Unverified against a published contract: the team is read from `list_resources`' `teamId`
    field, and membership from items carrying both timestamps.
    """

    def __init__(self, team_id: str, client_factory: Callable[[], Client[Any]]) -> None:
        if not TEAM_ID.fullmatch(team_id):
            raise BridgeConfigError(
                "PAPER_TEAM_ID must be a Paper team id (letters, digits, - and _)"
            )
        self.team_id = team_id
        self._client = client_factory
        self.lock = asyncio.Lock()

    async def listing(self) -> dict[str, Any] | str:
        """The active team's listing, or the refusal sentence."""
        async with self._client() as client:
            result = await client.call_tool(
                "list_resources", {"limit": LISTING_LIMIT}, raise_on_error=False
            )
        listing = _json_object(result)
        if listing is None or not isinstance(listing.get("teamId"), str):
            return TEAM_UNREADABLE
        return listing if listing["teamId"] == self.team_id else TEAM_DRIFT

    @staticmethod
    def refusal(tool: str, args: dict[str, Any], listing: dict[str, Any]) -> str | None:
        items = listing.get("resources") or []
        files = {item["id"] for item in items if _in_team(item)}
        resources = {item["id"] for item in items if _in_team(item, ("file", "folder"))}
        if args.get("cloneFileId") is not None and args["cloneFileId"] not in files:
            return FOREIGN_FILE
        if tool == "rename_resource" and args.get("resourceId") not in resources:
            return FOREIGN_FILE
        if tool not in GLOBAL_TOOLS and args.get("fileId") not in files:
            return FOREIGN_FILE
        return None

    @staticmethod
    def filtered(listing: dict[str, Any], limit: object) -> ToolResult:
        count = limit if type(limit) is int and 1 <= limit <= LISTING_LIMIT else 50
        items = [
            item for item in listing.get("resources") or [] if _in_team(item, ("file", "folder"))
        ]
        return ToolResult(
            content=[
                TextContent(type="text", text=json.dumps({**listing, "resources": items[:count]}))
            ]
        )


class BridgePolicy(Middleware):
    """The host's `PaperPolicy` and the optional team check, applied to every proxied call."""

    def __init__(
        self,
        policy: PaperPolicy,
        team: TeamScope | None = None,
        *,
        exports_folder: Path | None = None,
    ) -> None:
        self.policy = policy
        self.team = team
        self.exports_folder = exports_folder
        self._checked = False

    async def on_list_tools(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        tools = await call_next(context)
        names = [tool.name for tool in tools]
        if not self._checked:
            self._checked = True
            log_catalog(check_catalog(names, self.policy))
        admitted = self.policy.admitted
        return [tool for tool in tools if tool.name in admitted]

    async def on_call_tool(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        params = context.message
        decision = self.policy.decide(params.name, params.arguments or {})
        if decision.refusal is not None:
            return _text(decision.refusal)
        forwarded = context.copy(message=params.model_copy(update={"arguments": decision.args}))
        started = time.time()
        try:
            if self.team is None or params.name == "get_guide":
                return self._with_exports(params.name, await call_next(forwarded), started)
            async with self.team.lock:
                listing = await self.team.listing()
                if isinstance(listing, str):
                    return _text(listing)
                if params.name == "list_resources":
                    return self.team.filtered(listing, decision.args.get("limit"))
                refusal = self.team.refusal(params.name, decision.args, listing)
                if refusal is not None:
                    return _text(refusal)
                return self._with_exports(params.name, await call_next(forwarded), started)
        except Exception as error:  # noqa: BLE001 - never hand Desktop or transport internals back
            _LOGGER.warning("[paper-bridge] %s failed: %s", params.name, type(error).__name__)
            return _text(DESKTOP_UNAVAILABLE)

    def _with_exports(self, tool: str, result: Any, started: float) -> Any:
        """An export's result with the files Desktop just wrote here in place of their paths."""
        if tool not in EXPORT_TOOLS or getattr(result, "is_error", False):
            return result
        blocks = list(getattr(result, "content", None) or [])
        texts = [block.text for block in blocks if isinstance(block, TextContent)]
        taken = take_exports(texts, since=started, folder=self.exports_folder)
        if not taken:
            return result
        content: list[Any] = [
            block
            for block in blocks
            if not (isinstance(block, TextContent) and exported_paths(block.text))
        ]
        for item in taken:
            data = base64.b64encode(item.data).decode()
            if item.mime_type.startswith("image/"):
                content.append(ImageContent(type="image", data=data, mimeType=item.mime_type))
            else:
                content.append(
                    EmbeddedResource(
                        type="resource",
                        resource=BlobResourceContents(
                            uri="paper://export", mimeType=item.mime_type, blob=data
                        ),
                    )
                )
        return ToolResult(content=content)

    # Paper's resources and prompts are not offered; FastMCP passes `call_next` by keyword.

    async def on_list_resources(self, context: Any, call_next: Any) -> Any:  # noqa: ARG002
        return []

    async def on_list_resource_templates(self, context: Any, call_next: Any) -> Any:  # noqa: ARG002
        return []

    async def on_list_prompts(self, context: Any, call_next: Any) -> Any:  # noqa: ARG002
        return []

    async def on_read_resource(self, context: Any, call_next: Any) -> Any:  # noqa: ARG002
        raise ResourceError(NOT_OFFERED)

    async def on_get_prompt(self, context: Any, call_next: Any) -> Any:  # noqa: ARG002
        raise PromptError(NOT_OFFERED)


def create_app(
    policy: PaperPolicy,
    *,
    token: str,
    upstream: Any,
    hostnames: frozenset[str] = LOOPBACK_HOSTS,
    team_id: str | None = None,
) -> ASGIApp:
    """The bridge as an ASGI app in front of `upstream` (a fastmcp transport or server).

    Raises `BridgeConfigError` instead of starting with a short token or a malformed team id.
    """
    check_token(token)
    team = TeamScope(team_id, lambda: Client(upstream)) if team_id is not None else None
    proxy = create_proxy(upstream, name="design-agent-paper-bridge")
    proxy.add_middleware(BridgePolicy(policy, team))
    app = proxy.http_app(
        path=MCP_PATH, stateless_http=True, json_response=True, host_origin_protection=False
    )
    return BridgeGuard(app, token=token, hostnames=hostnames)


def upstream_for(choice: str, *, cli: Callable[[], str | None] | None = None) -> Any:
    """Paper Desktop's local MCP: `auto` (stdio when the CLI is installed, else HTTP), `stdio`, or
    the legacy `http://127.0.0.1:29979/mcp`."""
    from fastmcp.client.transports import StdioTransport, StreamableHttpTransport

    from design_agent.tools.paper import LOCAL_HTTP, paper_cli

    find = cli or paper_cli
    if choice in ("auto", "stdio"):
        command = find()
        if command is not None:
            return StdioTransport(command, ["mcp"], env=None)
        if choice == "stdio":
            raise BridgeConfigError(
                "Paper Desktop's `paper` CLI was not found in ~/.paper/bin or on PATH"
            )
        return StreamableHttpTransport(LOCAL_HTTP)
    if choice != LOCAL_HTTP:
        raise BridgeConfigError(f"--upstream takes auto, stdio or {LOCAL_HTTP}")
    return StreamableHttpTransport(LOCAL_HTTP)


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    allow_hosts: Sequence[str] = (),
    upstream: str = "auto",
) -> None:
    """Run the bridge with `PAPER_*` settings from the environment or `.env` until interrupted."""
    import uvicorn

    from design_agent.config import Settings

    settings = Settings()
    token = settings.paper_bridge_token.get_secret_value() if settings.paper_bridge_token else ""
    app = create_app(
        PaperPolicy.from_settings(settings),
        token=token,
        upstream=upstream_for(upstream),
        hostnames=allowed_hostnames(allow_hosts),
        team_id=settings.paper_team_id,
    )
    if host not in LOOPBACK_HOSTS:
        _LOGGER.warning(
            "[paper-bridge] listening on %s: expose it only through a tunnel you own", host
        )
    uvicorn.run(app, host=host, port=port, access_log=False, log_level="warning")
