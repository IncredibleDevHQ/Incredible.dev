"""Supabase Auth at the server boundary; one private app/runtime per verified user.

Provider tokens stay in HttpOnly cookies. Neither X-Person nor a client-supplied workspace
selects an identity. Tenant schemas, files, event hubs and agent stores are separate.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import secrets
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, SecretStr, field_validator
from starlette.types import ASGIApp, Receive, Scope, Send

from design_agent.config import Settings
from design_agent.runtime.persistence import workspace_of
from design_agent.surfaces.web.directory import Directory
from design_agent.surfaces.web.project_login import (
    BROWSER_SESSION,
    FLOW_ID,
    PROJECT_SESSION,
    digest,
    project_login_routes,
)
from design_agent.surfaces.web.research_catalog import catalog_repos
from design_agent.surfaces.web.team import team_routes

ACCESS = "incredible-access"
REFRESH = "incredible-refresh"
VERIFIER = "incredible-pkce"
INVITE_ID = re.compile(r"[0-9a-f]{32}")
TenantFactory = Callable[[dict[str, Any]], Awaitable[FastAPI]]


class SecurityHeaders:
    def __init__(self, app: ASGIApp, directory: Directory) -> None:
        self.app = app
        self.directory = directory

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        started = time.monotonic()

        async def secured(message: Any) -> None:
            if message["type"] == "http.response.start":
                state = scope.get("state", {})
                actor = state.get("actor")
                route = getattr(scope.get("route"), "path", "")
                if (
                    actor
                    and route.startswith("/api/")
                    and (
                        scope["method"] not in {"GET", "HEAD", "OPTIONS"}
                        or route == "/api/auth/callback"
                    )
                ):
                    await self.directory.query(
                        "INSERT INTO activity(id,owner,actor,actor_email,action,happened,status,member_email,duration_ms) VALUES(?,?,?,?,?,?,?,?,?)",
                        uuid.uuid4().hex,
                        state.get("project", actor["id"]),
                        actor["id"],
                        actor["email"],
                        state.get("client_action") or scope["method"] + " " + route,
                        time.time(),
                        message["status"],
                        state.get("member_email"),
                        round((time.monotonic() - started) * 1000),
                    )
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-frame-options", b"DENY"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (
                            b"content-security-policy",
                            b"frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
                        ),
                    ]
                )
                if str(scope.get("path", "")).startswith("/api/"):
                    headers = [(k, v) for k, v in headers if k.lower() != b"cache-control"] + [
                        (b"cache-control", b"no-store")
                    ]
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, secured)


def user_schema(user_id: str) -> str:
    """The legacy UUID-derived name, used for pre-directory data."""
    return "user_" + uuid.UUID(user_id).hex


class PasswordInput(BaseModel):
    password: SecretStr = Field(min_length=8, max_length=256)


class CurrentPasswordInput(BaseModel):
    password: SecretStr = Field(min_length=1, max_length=256)


class PasswordChange(PasswordInput):
    current_password: SecretStr | None = Field(default=None, max_length=256)


class LoginInput(PasswordInput):
    email: str = Field(min_length=1, max_length=254)


class Credentials(LoginInput):
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def email_address(cls, value: str) -> str:
        from email_validator import EmailNotValidError, validate_email

        try:
            return str(validate_email(value, check_deliverability=False).normalized)
        except EmailNotValidError:
            raise ValueError("Enter a valid email address") from None


class Auth:
    def __init__(
        self,
        settings: Settings,
        directory: Directory,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if (
            not settings.supabase_url
            or not settings.supabase_publishable_key
            or not settings.database_url
        ):
            raise ValueError(
                "Supabase Auth requires SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY and DATABASE_URL"
            )
        url = urlparse(settings.supabase_url)
        origin = urlparse(settings.app_url)
        if (
            url.scheme != "https"
            or not url.netloc
            or origin.scheme not in {"http", "https"}
            or not origin.netloc
            or origin.path not in {"", "/"}
            or origin.query
            or origin.fragment
        ):
            raise ValueError("Configure an HTTPS Supabase URL and an application origin")
        if origin.scheme == "http" and origin.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("Non-local authentication requires HTTPS")
        self.directory = directory
        self.origin = settings.app_url.rstrip("/")
        self.secure = origin.scheme == "https"
        self.url = settings.supabase_url.rstrip("/") + "/auth/v1"
        self.client = httpx.AsyncClient(
            base_url=self.url + "/",
            headers={"apikey": settings.supabase_publishable_key.get_secret_value()},
            timeout=15,
            transport=transport,
        )
        self.attempts: dict[str, deque[float]] = defaultdict(deque)
        self.refresh_lock = asyncio.Lock()
        self.refreshed: dict[str, tuple[float, dict[str, Any]]] = {}

    def host_url(self, label: str) -> str:
        base = urlparse(self.origin)
        domain = "localhost" if base.hostname == "127.0.0.1" else base.hostname
        port = f":{base.port}" if base.port else ""
        return f"{base.scheme}://{label}.{domain}{port}"

    def host_label(self, request: Request) -> str | None:
        host = request.headers.get("host", "").lower()
        if host == urlparse(self.origin).netloc:
            return None
        label = host.split(".", 1)[0]
        if (
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            and host == urlparse(self.host_url(label)).netloc
        ):
            return label
        raise HTTPException(400, "Unrecognized Studio host.")

    async def project_host(self, request: Request) -> str | None:
        label = self.host_label(request)
        if not label:
            return None
        if not hasattr(request.state, "host_project"):
            project = await self.directory.project_for_label(label)
            if not project:
                raise HTTPException(404, "Project address not found.")
            request.state.host_project = project
        return str(request.state.host_project)

    async def request_origin(self, request: Request) -> str:
        if await self.project_host(request):
            return self.host_url(str(self.host_label(request)))
        return self.origin

    async def origin_check(self, request: Request) -> None:
        if request.headers.get("origin") != await self.request_origin(request):
            raise HTTPException(403, "Request must come from this application")

    def throttle(self, request: Request, *, scope: str = "auth", limit: int = 20) -> None:
        peer = request.client.host if request.client else "local"
        now = time.monotonic()
        attempts = self.attempts[scope + ":" + peer]
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if len(attempts) >= limit:
            raise HTTPException(429, "Too many attempts. Try again shortly.")
        attempts.append(now)
        # Bound bookkeeping without dropping active limits.
        if len(self.attempts) > 2048:
            self.attempts = defaultdict(
                deque, {k: v for k, v in self.attempts.items() if v and v[-1] >= now - 60}
            )

    async def call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.RequestError:
            raise HTTPException(503, "Sign-in service is unavailable. Try again shortly.") from None
        if response.status_code >= 500:
            raise HTTPException(503, "Sign-in service is unavailable. Try again shortly.")
        if response.status_code == 429:
            raise HTTPException(429, "Too many attempts. Try again shortly.")
        return response

    async def user(self, access: str) -> dict[str, Any] | None:
        response = await self.call("GET", "user", headers={"Authorization": "Bearer " + access})
        if not response.is_success:
            return None
        data = response.json()
        try:
            uuid.UUID(data["id"])
        except (KeyError, ValueError, TypeError, AttributeError):
            return None
        if not data.get("email_confirmed_at") or not data.get("email") or data.get("is_anonymous"):
            return None
        # Supabase links an email identity on first password setup. Keep the
        # existing Studio marker for accounts created before identity linking.
        providers = (data.get("app_metadata") or {}).get("providers") or []
        identities = {
            entry.get("provider")
            for entry in data.get("identities") or []
            if isinstance(entry, dict)
        }
        marked = (data.get("user_metadata") or {}).get("studio_password_set") is True
        return {
            "id": data["id"],
            "email": data["email"],
            "has_password": marked
            or "email" in identities
            or "email" in providers
            or "google" not in providers,
        }

    def browser_cookie(self, response: Response, session: str) -> None:
        response.set_cookie(
            BROWSER_SESSION,
            session,
            httponly=True,
            secure=self.secure,
            samesite="lax",
            max_age=30 * 86400,
            path="/",
        )

    async def new_browser(self, response: Response, actor: str, previous: str | None = None) -> str:
        if previous:
            await self.directory.query("DELETE FROM browser_sessions WHERE id=?", digest(previous))
        session = secrets.token_urlsafe(32)
        await self.directory.query("DELETE FROM browser_sessions WHERE expires<=?", time.time())
        await self.directory.query(
            "INSERT INTO browser_sessions(id,actor,expires) VALUES(?,?,?)",
            digest(session),
            actor,
            time.time() + 30 * 86400,
        )
        self.browser_cookie(response, session)
        return session

    async def project_cookie(
        self, response: Response, project: str, session: str, access: str
    ) -> None:
        # The host-specific cookie is the encryption key. The private table holds only
        # its hash and ciphertext, and revoking the root session removes every alias.
        key = Fernet.generate_key()
        now = time.time()
        # Keep the session reference after access expires so Log out can still revoke
        # the root session. Deleting an expired browser session cascades to its projects.
        await self.directory.query("DELETE FROM browser_sessions WHERE expires<=?", now)
        rows = await self.directory.query(
            "INSERT INTO project_sessions(id,project,session,access,expires) "
            "SELECT ?,?,id,?,? FROM browser_sessions WHERE id=? AND expires>? RETURNING id",
            digest(key.decode()),
            project,
            Fernet(key).encrypt(access.encode()).decode(),
            now + 3600,
            session,
            now,
        )
        if not rows:
            raise HTTPException(401, "Sign in to continue")
        response.set_cookie(
            PROJECT_SESSION,
            key.decode(),
            httponly=True,
            secure=self.secure,
            samesite="lax",
            max_age=30 * 86400,
            path="/",
        )

    async def identity(self, request: Request) -> tuple[dict[str, Any], dict[str, Any] | None]:
        key = request.cookies.get(PROJECT_SESSION)
        if key:
            project = await self.project_host(request)
            rows = await self.directory.query(
                "SELECT b.actor,p.session,p.access FROM project_sessions p "
                "JOIN browser_sessions b ON b.id=p.session WHERE p.id=? AND p.project=? "
                "AND p.expires>? AND b.expires>?",
                digest(key),
                project,
                time.time(),
                time.time(),
            )
            if not rows:
                raise HTTPException(401, "Sign in to continue")
            access = Fernet(key.encode()).decrypt(rows[0]["access"].encode()).decode()
            user = await self.user(access)
            if not user or user["id"] != rows[0]["actor"]:
                raise HTTPException(401, "Sign in to continue")
            request.state.access = access
            request.state.browser_session = rows[0]["session"]
            request.state.actor = user
            return user, None
        browser = request.cookies.get(BROWSER_SESSION)
        if browser:
            rows = await self.directory.query(
                "SELECT actor FROM browser_sessions WHERE id=? AND expires>?",
                digest(browser),
                time.time(),
            )
            if not rows:
                raise HTTPException(401, "Sign in to continue")
        user, tokens = await self.provider_identity(request)
        if browser and rows[0]["actor"] != user["id"]:
            raise HTTPException(401, "Sign in to continue")
        request.state.access = tokens["access_token"] if tokens else request.cookies[ACCESS]
        request.state.actor = user
        return user, tokens

    async def provider_identity(
        self, request: Request
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        access = request.cookies.get(ACCESS)
        user = await self.user(access) if access else None
        if user:
            return user, None
        refresh = request.cookies.get(REFRESH)
        if refresh:
            async with self.refresh_lock:
                now = time.monotonic()
                self.refreshed = {k: v for k, v in self.refreshed.items() if v[0] > now}
                key = hashlib.sha256(refresh.encode()).hexdigest()
                cached = self.refreshed.get(key)
                if cached:
                    tokens = cached[1]
                else:
                    response = await self.call(
                        "POST", "token?grant_type=refresh_token", json={"refresh_token": refresh}
                    )
                    tokens = response.json() if response.is_success else {}
                    if tokens.get("access_token") and tokens.get("refresh_token"):
                        self.refreshed[key] = (now + 10, tokens)
                user = (
                    await self.user(str(tokens.get("access_token", "")))
                    if tokens.get("access_token")
                    else None
                )
                if user:
                    return user, tokens
        raise HTTPException(401, "Sign in to continue")

    def cookies(self, response: Response, tokens: dict[str, Any]) -> None:
        response.set_cookie(
            ACCESS,
            tokens["access_token"],
            httponly=True,
            secure=self.secure,
            samesite="lax",
            max_age=min(int(tokens.get("expires_in", 3600)), 3600),
            path="/",
        )
        response.set_cookie(
            REFRESH,
            tokens["refresh_token"],
            httponly=True,
            secure=self.secure,
            samesite="lax",
            max_age=30 * 86400,
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"

    def pkce(
        self,
        response: Response,
        invite: str | None = None,
        *,
        flow: str | None = None,
        max_age: int = 600,
    ) -> str:
        verifier = secrets.token_urlsafe(48)
        response.set_cookie(
            VERIFIER,
            verifier
            + (
                ".flow-" + flow
                if flow and FLOW_ID.fullmatch(flow)
                else "." + invite
                if invite and INVITE_ID.fullmatch(invite)
                else ""
            ),
            httponly=True,
            secure=self.secure,
            samesite="lax",
            max_age=max_age,
            path="/api/auth",
        )
        return (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )


class Tenants:
    def __init__(
        self,
        root: Path,
        settings: Settings,
        stack: AsyncExitStack,
        demo: bool,
        factory: TenantFactory | None,
    ) -> None:
        self.root, self.settings, self.stack, self.demo, self.factory = (
            root,
            settings,
            stack,
            demo,
            factory,
        )
        self.apps: dict[str, FastAPI] = {}
        self.lock = asyncio.Lock()

    async def project_url(self, auth: Auth, owner: dict[str, Any], name: str | None = None) -> str:
        if name is None:
            app = await self.get(owner)
            host = getattr(app.state, "host", None)
            profile = await asyncio.to_thread(host.store.organization) if host else {}
            name = profile.get("name") or ""
        return auth.host_url(await auth.directory.organization_slug(owner["id"], name or ""))

    def close_streams(self) -> None:
        for app in tuple(self.apps.values()):
            app.state.host.hub.close_streams()

    async def get(self, user: dict[str, Any]) -> FastAPI:
        async with self.lock:
            if user["id"] not in self.apps:
                if self.factory:
                    app = await self.factory(user)
                else:
                    from design_agent.surfaces.web.app import create_app

                    folder = (
                        workspace_of(self.settings, self.root)
                        / "accounts"
                        / uuid.UUID(user["id"]).hex
                    )
                    settings = self.settings.model_copy(
                        update={
                            "workspace_root": folder,
                            "brand_path": folder / "brand",
                            "private_fonts_dir": folder / "private-fonts",
                            "research_roots": "",
                            "enable_traces": False,
                        }
                    )
                    app = await asyncio.to_thread(
                        create_app, self.root, settings, demo=self.demo, authenticated_user=user
                    )
                await self.stack.enter_async_context(app.router.lifespan_context(app))
                self.apps[user["id"]] = app
            return self.apps[user["id"]]


class Gateway:
    def __init__(self, auth: Auth, tenants: Tenants, root: Path, directory: Directory) -> None:
        self.directory = directory
        self.auth, self.tenants, self.built = auth, tenants, root / "web/dist"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        request = Request(scope, receive)
        response: Response
        try:
            if request.url.path.startswith("/api/"):
                if request.method not in {"GET", "HEAD", "OPTIONS"}:
                    await self.auth.origin_check(request)
                user, tokens = await self.auth.identity(request)
                # A server's local code and coding-agent account are not a user's resources.
                if (
                    "/research" in request.url.path
                    and not self.tenants.settings.private_research_enabled(user["id"])
                ):
                    if request.method == "GET" and request.url.path == "/api/research":
                        options: dict[str, Any] = {"harnesses": [], "models": {}, "repos": []}
                        directory = self.tenants.settings.research_catalog_dir
                        if directory is not None:
                            try:
                                repos = await asyncio.to_thread(
                                    catalog_repos, directory, user["id"]
                                )
                            except (OSError, ValueError):
                                raise HTTPException(
                                    503, "Local repository list is unavailable"
                                ) from None
                            if repos is not None:
                                options.update(repos=repos, discovery_only=True)
                        response = JSONResponse(options)
                    else:
                        response = JSONResponse(
                            {"detail": "Repository research is unavailable in private workspaces"},
                            status_code=403,
                        )
                    if tokens:
                        self.auth.cookies(response, tokens)
                    await response(scope, receive, send)
                    return
                selected = await self.auth.project_host(request)
                project = await self.directory.project(user, selected)
                if selected and request.url.path == "/api/session" and request.method == "GET":
                    await self.directory.remember(user["id"], selected)
                if request.url.path == "/api/session":
                    request.state.project_url = await self.tenants.project_url(self.auth, project)
                request.state.project = project["id"]
                if (
                    user["id"] != project["id"]
                    and request.url.path == "/api/organization"
                    and request.method != "GET"
                ):
                    raise HTTPException(403, "Only the owner can edit the organization.")
                app = await self.tenants.get(project)
                if user["id"] != project["id"] and hasattr(app.state, "host"):
                    await asyncio.to_thread(
                        app.state.host.store.ensure_member, user["id"], user["email"]
                    )
                cookie_response = Response()
                if tokens:
                    self.auth.cookies(cookie_response, tokens)
                started = False

                async def private_send(message: Any) -> None:
                    nonlocal started
                    if message["type"] == "http.response.start":
                        started = True
                        message["headers"] = [
                            (k, v)
                            for k, v in message.get("headers", [])
                            if k.lower() != b"cache-control"
                        ] + [(b"cache-control", b"no-store")]
                        message["headers"].extend(
                            (k, v)
                            for k, v in cookie_response.raw_headers
                            if k.lower() == b"set-cookie"
                        )
                    await send(message)

                if request.url.path == "/api/stream":
                    try:
                        await asyncio.wait_for(app(scope, receive, private_send), timeout=300)
                    except TimeoutError:
                        if started:
                            await send(
                                {"type": "http.response.body", "body": b"", "more_body": False}
                            )
                else:
                    await app(scope, receive, private_send)
                return
            path = (self.built / request.url.path.lstrip("/")).resolve()
            if self.built.resolve() not in path.parents or not path.is_file():
                path = self.built / "index.html"
            response = (
                FileResponse(path, headers={"Cache-Control": "no-cache"})
                if path.is_file()
                else JSONResponse({"detail": "Build the frontend first"}, status_code=503)
            )
        except HTTPException as error:
            response = JSONResponse(
                {"detail": error.detail},
                status_code=error.status_code,
                headers={"Cache-Control": "no-store"},
            )
        await response(scope, receive, send)


def create_authenticated_app(
    root: Path,
    settings: Settings,
    *,
    demo: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
    tenant_factory: TenantFactory | None = None,
) -> FastAPI:
    directory = Directory(
        settings.database_url.get_secret_value()
        if settings.database_url and tenant_factory is None
        else None
    )
    auth = Auth(settings, directory, transport)
    stack = AsyncExitStack()
    tenants = Tenants(root, settings, stack, demo, tenant_factory)
    from design_agent.surfaces.web.blobs import BlobFiles, StorageUnavailable

    blobs = BlobFiles(settings, root / "workspace/house/files", "local")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with stack:
            try:
                await directory.open()
                await asyncio.to_thread(blobs.check)
                if tenant_factory is None:
                    from psycopg import AsyncConnection

                    assert settings.database_url is not None  # noqa: S101 - Auth validates this
                    async with await AsyncConnection.connect(
                        settings.database_url.get_secret_value(), connect_timeout=15
                    ) as connection:
                        await connection.execute("SELECT 1")
                yield
            finally:
                await directory.close()
                await auth.client.aclose()
                blobs.close()

    app = FastAPI(
        title="Incredible.dev", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.add_middleware(SecurityHeaders, directory=directory)
    app.include_router(project_login_routes(auth, directory, tenants))
    app.include_router(team_routes(auth, directory, tenants))
    app.state.auth = auth
    app.state.tenants = tenants

    @app.exception_handler(StorageUnavailable)
    async def storage_error(_request: Request, _error: StorageUnavailable) -> Response:
        return JSONResponse(
            {"detail": "File storage is unavailable. Try again shortly."}, status_code=503
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, error: RequestValidationError) -> Response:
        # Pydantic's default errors echo invalid inputs, including a submitted password.
        return JSONResponse(
            {
                "detail": [
                    {"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in error.errors()
                ]
            },
            status_code=422,
        )

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok", "authentication": "supabase"}

    @app.get("/api/auth/config")
    async def config(request: Request) -> Response:
        if await auth.project_host(request):
            return JSONResponse(
                {"enabled": True, "project_signin": True}, headers={"Cache-Control": "no-store"}
            )
        response = await auth.call("GET", "settings")
        external = response.json().get("external", {}) if response.is_success else {}
        return JSONResponse(
            {
                "enabled": True,
                "google": bool(external.get("google")),
                "email": bool(external.get("email", True)),
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/auth/session")
    async def session(request: Request) -> Response:
        user, tokens = await auth.identity(request)
        selected = await auth.project_host(request)
        data: dict[str, Any] = {"user": user, "root_entry": selected is None}
        if selected:
            try:
                owner = await directory.project(user, selected)
            except HTTPException as exc:
                if exc.status_code != 403:
                    raise
            else:
                canonical = await tenants.project_url(auth, owner)
                if canonical != await auth.request_origin(request):
                    data["canonical_url"] = canonical
        response = JSONResponse(
            data,
            headers={"Cache-Control": "no-store"},
        )
        if tokens:
            auth.cookies(response, tokens)
        return response

    async def password(request: Request, body: LoginInput, signup: bool) -> Response:
        await auth.origin_check(request)
        auth.throttle(request)
        payload = {"email": body.email, "password": body.password.get_secret_value()}
        expected_id = None
        if not signup and "@" not in body.email:
            rows = await directory.query(
                "SELECT id,email FROM accounts WHERE username=?", body.email.strip().lower()
            )
            if not rows:
                raise HTTPException(
                    401, "Email or password is incorrect, or the email has not been confirmed."
                )
            payload["email"] = rows[0]["email"]
            expected_id = rows[0]["id"]
        response = JSONResponse({"ok": True})
        if signup:
            payload.update(
                {
                    "code_challenge": auth.pkce(
                        response,
                        request.query_params.get("invite"),
                        flow=request.query_params.get("flow"),
                        max_age=86400,
                    ),
                    "code_challenge_method": "s256",
                }
            )
        upstream = await auth.call(
            "POST",
            "signup" if signup else "token?grant_type=password",
            params={"redirect_to": await auth.request_origin(request) + "/api/auth/callback"}
            if signup
            else None,
            json=payload,
        )
        if signup and upstream.headers.get("content-type", "").startswith("application/json"):
            payload_data = upstream.json()
            if isinstance(payload_data, dict):
                identity = payload_data.get("user", payload_data)
                duplicate = payload_data.get("error_code") in {
                    "email_exists",
                    "user_already_exists",
                }
                if duplicate or (
                    upstream.is_success
                    and isinstance(identity, dict)
                    and identity.get("identities") == []
                    and not payload_data.get("access_token")
                ):
                    raise HTTPException(
                        409, "An account with this email already exists. Sign in to continue."
                    )
        if not upstream.is_success:
            raise HTTPException(
                400 if signup else 401,
                "Could not create the account. Check your email and password, then try again."
                if signup
                else "Email or password is incorrect, or the email has not been confirmed.",
            )
        data = upstream.json()
        if data.get("access_token") and data.get("refresh_token"):
            user = await auth.user(data["access_token"])
            if not user:
                raise HTTPException(401, "Confirm your email before signing in")
            if expected_id and user["id"] != expected_id:
                raise HTTPException(
                    401, "Email or password is incorrect, or the email has not been confirmed."
                )
            request.state.actor = user
            if signup:
                return JSONResponse(
                    {"message": "Account created. Sign in to continue."},
                    headers={"Cache-Control": "no-store"},
                )
            auth.cookies(response, data)
            await auth.new_browser(response, user["id"], request.cookies.get(BROWSER_SESSION))
        elif signup:
            response.body = b'{"message":"Check your email to confirm your account, then sign in."}'
            response.headers["content-length"] = str(len(response.body))
        else:
            raise HTTPException(401, "Sign in could not be completed")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/auth/login")
    async def login(request: Request, body: LoginInput) -> Response:
        return await password(request, body, False)

    @app.post("/api/auth/signup")
    async def signup(request: Request, body: Credentials) -> Response:
        return await password(request, body, True)

    @app.get("/api/auth/google")
    async def google(request: Request) -> Response:
        auth.throttle(request)
        available = await auth.call("GET", "settings")
        if not available.is_success or not available.json().get("external", {}).get("google"):
            invite = request.query_params.get("invite", "")
            path = "/invite/" + invite if INVITE_ID.fullmatch(invite) else "/"
            flow = request.query_params.get("flow", "")
            if FLOW_ID.fullmatch(flow):
                return RedirectResponse(
                    "/?flow=" + flow + "&auth_error=google_unavailable", status_code=303
                )
            return RedirectResponse(path + "?auth_error=google_unavailable", status_code=303)
        response = RedirectResponse("/", status_code=303)
        challenge = auth.pkce(
            response, request.query_params.get("invite"), flow=request.query_params.get("flow")
        )
        response.headers["location"] = (
            auth.url
            + "/authorize?"
            + urlencode(
                {
                    "provider": "google",
                    "redirect_to": await auth.request_origin(request) + "/api/auth/callback",
                    "code_challenge": challenge,
                    "code_challenge_method": "s256",
                }
            )
        )
        return response

    @app.get("/api/auth/callback")
    async def callback(request: Request) -> Response:
        code = request.query_params.get("code")
        verifier, _, invite = request.cookies.get(VERIFIER, "").partition(".")
        destination = "/invite/" + invite if INVITE_ID.fullmatch(invite) else "/"
        if invite.startswith("flow-") and FLOW_ID.fullmatch(invite[5:]):
            destination = "/?flow=" + invite[5:]
        failed_destination = destination + ("&" if "?" in destination else "?") + "auth_error=link"
        if not code or not verifier:
            if "text/html" in request.headers.get("accept", ""):
                return RedirectResponse(failed_destination, status_code=303)
            raise HTTPException(
                400, "Sign-in link is invalid or expired. Start again in this browser."
            )
        result = await auth.call(
            "POST", "token?grant_type=pkce", json={"auth_code": code, "code_verifier": verifier}
        )
        if not result.is_success:
            if "text/html" in request.headers.get("accept", ""):
                return RedirectResponse(failed_destination, status_code=303)
            raise HTTPException(400, "Sign-in link is invalid or expired. Start again.")
        data = result.json()
        if (
            not data.get("access_token")
            or not data.get("refresh_token")
            or not (actor := await auth.user(data["access_token"]))
        ):
            raise HTTPException(401, "Sign in could not be verified")
        request.state.actor = actor
        response = RedirectResponse(destination, status_code=303)
        auth.cookies(response, data)
        await auth.new_browser(response, actor["id"], request.cookies.get(BROWSER_SESSION))
        response.delete_cookie(
            VERIFIER, path="/api/auth", secure=auth.secure, httponly=True, samesite="lax"
        )
        return response

    async def verify_current(user: dict[str, Any], current: str) -> dict[str, Any]:
        verified = await auth.call(
            "POST",
            "token?grant_type=password",
            json={"email": user["email"], "password": current},
        )
        fresh = verified.json() if verified.is_success else {}
        identity = await auth.user(fresh["access_token"]) if fresh.get("access_token") else None
        if not identity or identity["id"] != user["id"]:
            raise HTTPException(400, "Your current password is incorrect.")
        return dict(fresh)

    async def password_cookies(
        request: Request, response: Response, tokens: dict[str, Any]
    ) -> None:
        parent = getattr(request.state, "browser_session", None)
        project = await auth.project_host(request)
        if parent and project:
            await auth.project_cookie(response, project, parent, tokens["access_token"])
        else:
            auth.cookies(response, tokens)

    @app.post("/api/auth/password/verify")
    async def verify_password(request: Request, body: CurrentPasswordInput) -> Response:
        await auth.origin_check(request)
        auth.throttle(request)
        user, _ = await auth.identity(request)
        tokens = await verify_current(user, body.password.get_secret_value())
        response = JSONResponse({"verified": True})
        await password_cookies(request, response, tokens)
        return response

    @app.post("/api/auth/password")
    async def save_password(request: Request, body: PasswordChange) -> Response:
        await auth.origin_check(request)
        auth.throttle(request)
        user, tokens = await auth.identity(request)
        current = body.current_password.get_secret_value() if body.current_password else ""
        if user["has_password"] or current:
            if not current:
                raise HTTPException(400, "Enter your current password.")
            tokens = await verify_current(user, current)
        access = tokens["access_token"] if tokens else request.state.access
        updated = await auth.call(
            "PUT",
            "user",
            headers={"Authorization": f"Bearer {access}"},
            json={
                "password": body.password.get_secret_value(),
                "data": {"studio_password_set": True},
                **({"current_password": current} if current else {}),
            },
        )
        if not updated.is_success:
            code = (
                updated.json().get("error_code")
                if "application/json" in updated.headers.get("content-type", "")
                else None
            )
            messages = {
                "same_password": "Choose a password different from your current one.",
                "weak_password": "Choose a stronger password and try again.",
                "reauthentication_needed": "Sign in again, then retry the password change.",
            }
            raise HTTPException(
                400,
                messages.get(str(code), "Password could not be saved. Sign in again and retry."),
            )
        response = JSONResponse({"has_password": True}, headers={"Cache-Control": "no-store"})
        if tokens:
            await password_cookies(request, response, tokens)
        return response

    @app.post("/api/auth/logout")
    async def logout(request: Request) -> Response:
        await auth.origin_check(request)
        browser = request.cookies.get(BROWSER_SESSION)
        project_key = request.cookies.get(PROJECT_SESSION)
        access = request.cookies.get(ACCESS)
        if project_key:
            rows = await directory.query(
                "SELECT session,access FROM project_sessions WHERE id=? AND project=?",
                digest(project_key),
                await auth.project_host(request),
            )
            if rows:
                access = Fernet(project_key.encode()).decrypt(rows[0]["access"].encode()).decode()
                await directory.query("DELETE FROM browser_sessions WHERE id=?", rows[0]["session"])
        if browser:
            await directory.query("DELETE FROM browser_sessions WHERE id=?", digest(browser))
        if access:
            try:
                request.state.actor = await auth.user(access)
                await auth.call("POST", "logout", headers={"Authorization": "Bearer " + access})
            except HTTPException:
                pass
        auth.refreshed.clear()
        response = JSONResponse(
            {"ok": True, "url": auth.origin + "/"}, headers={"Cache-Control": "no-store"}
        )
        for name, path in [
            (ACCESS, "/"),
            (REFRESH, "/"),
            (BROWSER_SESSION, "/"),
            (PROJECT_SESSION, "/"),
            (VERIFIER, "/api/auth"),
        ]:
            response.delete_cookie(
                name, path=path, secure=auth.secure, httponly=True, samesite="lax"
            )
        return response

    app.mount("/", Gateway(auth, tenants, root, directory))
    return app
