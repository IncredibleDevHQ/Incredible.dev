"""A small Slack Web API client over httpx, for host-side presentation and thread reads.

- The token travels only in the `Authorization` header. It is never put in a URL, a form field,
  a log line or an exception, and `repr` does not show it.
- Fields go form-encoded, which every Web API method accepts; structured values (`blocks`,
  `chunks`) are JSON-encoded inside them.
- A refusal raises `SlackError` carrying Slack's own code (`ratelimited`, `missing_scope`, ...) and
  the method, never the request: callers log the code and carry on.
- Redirects are never followed, and a file download only goes to an HTTPS Slack host, so a
  link in an event cannot send the token anywhere else.
- `transport` is injectable (`httpx.MockTransport` in tests); one connection pool serves every
  call, since a TLS handshake per call is most of a second.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

SLACK_API = "https://slack.com/api/"
#: How long one presentation call may hold up the run behind it.
TIMEOUT_SECONDS = 10.0
#: Codes that mean the token itself is no good: the resolver fetches it again next run.
AUTH_ERRORS = frozenset(
    {"invalid_auth", "not_authed", "token_revoked", "token_expired", "account_inactive"}
)
#: Methods that create a message; the client remembers the newest ones it created.
_POSTS = frozenset({"chat.postMessage", "chat.startStream"})
POSTED_KEPT = 1000


class SlackError(Exception):
    """Slack refused a call, or was not reached. `code` is Slack's error code (or the transport
    failure's class name); the message never carries the request or the token."""

    def __init__(self, method: str, code: str) -> None:
        super().__init__(f"Slack {method} failed: {code}")
        self.method = method
        self.code = code


@dataclass(frozen=True)
class SlackIdentity:
    """The token's own workspace and bot user, from `auth.test`."""

    team_id: str
    user_id: str


def _encode(fields: Mapping[str, object]) -> dict[str, str]:
    encoded: dict[str, str] = {}
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, bool):
            encoded[key] = "true" if value else "false"
        elif isinstance(value, str | int | float):
            encoded[key] = str(value)
        else:
            encoded[key] = json.dumps(value, separators=(",", ":"))
    return encoded


def is_slack_file_url(url: str) -> bool:
    """Whether `url` is an HTTPS Slack host on the default port, with no credentials in it."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        return (
            parts.scheme == "https"
            and (host == "slack.com" or host.endswith(".slack.com"))
            and parts.port in (None, 443)
            and parts.username is None
            and parts.password is None
        )
    except ValueError:
        return False


class SlackClient:
    """Web API calls on one bot token (module doc)."""

    def __init__(
        self,
        token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = SLACK_API,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self._token = token
        self._transport = transport
        self._base_url = base_url if base_url.endswith("/") else f"{base_url}/"
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None
        self._identity: SlackIdentity | None = None
        self._posted: deque[str] = deque(maxlen=POSTED_KEPT)
        #: Set when Slack said the token is no good; the resolver replaces this client.
        self.auth_failed = False

    def __repr__(self) -> str:
        return f"SlackClient(base_url={self._base_url!r})"

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                transport=self._transport, timeout=self._timeout, follow_redirects=False
            )
        return self._http

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def call(self, method: str, fields: Mapping[str, object] | None = None) -> dict[str, Any]:
        """One Web API method; Slack's answer when it says `ok`, else `SlackError`."""
        try:
            response = await self._client().post(
                f"{self._base_url}{method}", headers=self._auth(), data=_encode(fields or {})
            )
        except httpx.HTTPError as error:
            raise SlackError(method, type(error).__name__) from None
        if response.status_code == 429:
            raise SlackError(method, "ratelimited")
        if response.status_code != 200:
            raise SlackError(method, f"http_{response.status_code}")
        try:
            result = response.json()
        except ValueError:
            raise SlackError(method, "invalid_response") from None
        if not isinstance(result, dict) or result.get("ok") is not True:
            code = result.get("error") if isinstance(result, dict) else None
            code = code if isinstance(code, str) and code else "unknown"
            self.auth_failed = self.auth_failed or code in AUTH_ERRORS
            raise SlackError(method, code)
        if method in _POSTS and isinstance(result.get("ts"), str):
            self._posted.append(result["ts"])
        return result

    def posted(self, ts: object) -> bool:
        """Whether this client created the message at `ts` (a progress message, a footer)."""
        return isinstance(ts, str) and ts in self._posted

    async def identity(self) -> SlackIdentity:
        """The token's team and bot user, read once per client."""
        if self._identity is None:
            found = await self.call("auth.test")
            self._identity = SlackIdentity(
                str(found.get("team_id") or ""), str(found.get("user_id") or "")
            )
        return self._identity

    async def download(self, url: str, *, limit_bytes: int) -> bytes:
        """A private Slack file's bytes, refused past `limit_bytes` and off Slack's own hosts."""
        if not is_slack_file_url(url):
            raise SlackError("files.download", "not_a_slack_url")
        try:
            async with self._client().stream("GET", url, headers=self._auth()) as response:
                if response.status_code != 200:
                    raise SlackError("files.download", f"http_{response.status_code}")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > limit_bytes:
                        raise SlackError("files.download", "too_large")
                return bytes(data)
        except httpx.HTTPError as error:
            raise SlackError("files.download", type(error).__name__) from None

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None
