"""Supabase Auth at the server boundary; one private app/runtime per verified user.

Provider tokens stay in HttpOnly cookies. Neither X-Person nor a client-supplied workspace
selects an identity. Tenant schemas, files, event hubs and agent stores are separate.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
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
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, SecretStr, field_validator
from starlette.types import ASGIApp, Receive, Scope, Send

from design_agent.config import Settings
from design_agent.runtime.persistence import workspace_of

ACCESS = "incredible-access"
REFRESH = "incredible-refresh"
VERIFIER = "incredible-pkce"
TenantFactory = Callable[[dict[str, Any]], Awaitable[FastAPI]]


class SecurityHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def secured(message: Any) -> None:
            if message["type"] == "http.response.start":
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
    return "user_" + uuid.UUID(user_id).hex


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=8, max_length=256)

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
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
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

    def origin_check(self, request: Request) -> None:
        if request.headers.get("origin") != self.origin:
            raise HTTPException(403, "Request must come from this application")

    def throttle(self, request: Request) -> None:
        peer = request.client.host if request.client else "local"
        now = time.monotonic()
        attempts = self.attempts[peer]
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if len(attempts) >= 20:
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
            user_schema(data["id"])
        except (KeyError, ValueError, TypeError, AttributeError):
            return None
        if not data.get("email_confirmed_at") or not data.get("email") or data.get("is_anonymous"):
            return None
        return {"id": data["id"], "email": data["email"]}

    async def identity(self, request: Request) -> tuple[dict[str, Any], dict[str, Any] | None]:
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

    def pkce(self, response: Response, *, max_age: int = 600) -> str:
        verifier = secrets.token_urlsafe(48)
        response.set_cookie(
            VERIFIER,
            verifier,
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
    def __init__(self, auth: Auth, tenants: Tenants, root: Path) -> None:
        self.auth, self.tenants, self.built = auth, tenants, root / "web/dist"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        request = Request(scope, receive)
        response: Response
        try:
            if request.url.path.startswith("/api/"):
                if request.method not in {"GET", "HEAD", "OPTIONS"}:
                    self.auth.origin_check(request)
                user, tokens = await self.auth.identity(request)
                # A server's local code and coding-agent account are not a user's resources.
                if "/research" in request.url.path:
                    response = (
                        JSONResponse({"harnesses": [], "repos": []})
                        if request.method == "GET" and request.url.path == "/api/research"
                        else JSONResponse(
                            {"detail": "Repository research is unavailable in private workspaces"},
                            status_code=403,
                        )
                    )
                    await response(scope, receive, send)
                    return
                app = await self.tenants.get(user)
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
    auth = Auth(settings, transport)
    stack = AsyncExitStack()
    tenants = Tenants(root, settings, stack, demo, tenant_factory)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with stack:
            try:
                if tenant_factory is None:
                    from psycopg import AsyncConnection

                    assert settings.database_url is not None  # noqa: S101 - Auth validates this
                    async with await AsyncConnection.connect(
                        settings.database_url.get_secret_value(), connect_timeout=15
                    ) as connection:
                        await connection.execute("SELECT 1")
                yield
            finally:
                await auth.client.aclose()

    app = FastAPI(
        title="Incredible.dev", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.add_middleware(SecurityHeaders)
    app.state.auth = auth
    app.state.tenants = tenants

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
    async def config() -> Response:
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
        response = JSONResponse({"user": user}, headers={"Cache-Control": "no-store"})
        if tokens:
            auth.cookies(response, tokens)
        return response

    async def password(request: Request, body: Credentials, signup: bool) -> Response:
        auth.origin_check(request)
        auth.throttle(request)
        payload = {"email": body.email, "password": body.password.get_secret_value()}
        response = JSONResponse({"ok": True})
        if signup:
            payload.update(
                {
                    "code_challenge": auth.pkce(response, max_age=86400),
                    "code_challenge_method": "s256",
                }
            )
        upstream = await auth.call(
            "POST",
            "signup" if signup else "token?grant_type=password",
            params={"redirect_to": auth.origin + "/api/auth/callback"} if signup else None,
            json=payload,
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
            auth.cookies(response, data)
        elif signup:
            response.body = b'{"message":"Check your email to confirm your account, then sign in."}'
            response.headers["content-length"] = str(len(response.body))
        else:
            raise HTTPException(401, "Sign in could not be completed")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/auth/login")
    async def login(request: Request, body: Credentials) -> Response:
        return await password(request, body, False)

    @app.post("/api/auth/signup")
    async def signup(request: Request, body: Credentials) -> Response:
        return await password(request, body, True)

    @app.get("/api/auth/google")
    async def google(request: Request) -> Response:
        auth.throttle(request)
        available = await auth.call("GET", "settings")
        if not available.is_success or not available.json().get("external", {}).get("google"):
            return RedirectResponse("/?auth_error=google_unavailable", status_code=303)
        response = RedirectResponse("/", status_code=303)
        challenge = auth.pkce(response)
        response.headers["location"] = (
            auth.url
            + "/authorize?"
            + urlencode(
                {
                    "provider": "google",
                    "redirect_to": auth.origin + "/api/auth/callback",
                    "code_challenge": challenge,
                    "code_challenge_method": "s256",
                }
            )
        )
        return response

    @app.get("/api/auth/callback")
    async def callback(request: Request) -> Response:
        code = request.query_params.get("code")
        verifier = request.cookies.get(VERIFIER)
        if not code or not verifier:
            raise HTTPException(
                400, "Sign-in link is invalid or expired. Start again in this browser."
            )
        result = await auth.call(
            "POST", "token?grant_type=pkce", json={"auth_code": code, "code_verifier": verifier}
        )
        if not result.is_success:
            raise HTTPException(400, "Sign-in link is invalid or expired. Start again.")
        data = result.json()
        if (
            not data.get("access_token")
            or not data.get("refresh_token")
            or not await auth.user(data["access_token"])
        ):
            raise HTTPException(401, "Sign in could not be verified")
        response = RedirectResponse("/", status_code=303)
        auth.cookies(response, data)
        response.delete_cookie(
            VERIFIER, path="/api/auth", secure=auth.secure, httponly=True, samesite="lax"
        )
        return response

    @app.post("/api/auth/logout")
    async def logout(request: Request) -> Response:
        auth.origin_check(request)
        access = request.cookies.get(ACCESS)
        if access:
            try:
                await auth.call("POST", "logout", headers={"Authorization": "Bearer " + access})
            except HTTPException:
                pass  # Local logout must work even while the provider is unavailable.
        auth.refreshed.clear()
        response = JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})
        for name, path in [(ACCESS, "/"), (REFRESH, "/"), (VERIFIER, "/api/auth")]:
            response.delete_cookie(
                name, path=path, secure=auth.secure, httponly=True, samesite="lax"
            )
        return response

    app.mount("/", Gateway(auth, tenants, root))
    return app
