"""Auth is server-verified; cookies and tenant routing cannot be impersonated by headers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from design_agent.config import Settings
from design_agent.surfaces.web.auth import create_authenticated_app

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
ORIGIN = "http://127.0.0.1:8765"
USERS = {"token-a": A, "token-b": B, "fresh-a": A}


def provider(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/settings"):
        return httpx.Response(200, json={"external": {"google": True, "email": True}})
    if request.url.path.endswith("/user"):
        uid = USERS.get(request.headers.get("Authorization", "").removeprefix("Bearer "))
        return httpx.Response(
            200 if uid else 401,
            json={
                "id": uid,
                "email": "member@example.com",
                "email_confirmed_at": "2026-01-01T00:00:00Z",
            },
        )
    if request.url.path.endswith("/token"):
        body = json.loads(request.content)
        if body.get("password") == "invalid-password":
            return httpx.Response(400, json={"error_description": "private provider error"})
        return httpx.Response(
            200, json={"access_token": "fresh-a", "refresh_token": "rotated", "expires_in": 3600}
        )
    if request.url.path.endswith("/signup"):
        body = json.loads(request.content)
        assert body.get("code_challenge") and body.get("code_challenge_method") == "s256"
        return httpx.Response(200, json={"user": {"id": A}})
    return httpx.Response(204)


@pytest.fixture
async def client(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="public-test-key",
        database_url="postgresql://unused",
        app_url=ORIGIN,
    )
    made: list[str] = []

    async def tenant(user: dict[str, Any]) -> FastAPI:
        uid = user["id"]
        made.append(uid)
        app = FastAPI()
        owned: set[str] = set()

        @app.get("/api/session")
        async def session():
            return {"me": uid}

        @app.post("/api/resources/{name}")
        async def put(name: str):
            owned.add(name)
            return {"ok": True}

        @app.get("/api/resources/{name}")
        async def get(name: str):
            if name not in owned:
                raise HTTPException(404)
            return {"owner": uid}

        return app

    app = create_authenticated_app(
        tmp_path, settings, transport=httpx.MockTransport(provider), tenant_factory=tenant
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as c:
            yield c, made


async def test_spoofed_person_headers_and_invalid_tokens_are_rejected(client):
    c, made = client
    assert (await c.get("/api/session", headers={"X-Person": "you"})).status_code == 401
    c.cookies.set("incredible-access", "forged")
    assert (await c.get("/api/session")).status_code == 401
    assert made == []


async def test_each_verified_user_gets_a_private_app_and_cannot_read_another_users_ids(client):
    c, made = client
    c.cookies.set("incredible-access", "token-a")
    assert (await c.get("/api/session", headers={"X-Person": B})).json()["me"] == A
    assert (await c.post("/api/resources/private", headers={"Origin": ORIGIN})).status_code == 200
    c.cookies.set("incredible-access", "token-b")
    assert (await c.get("/api/session")).json()["me"] == B
    assert (await c.get("/api/resources/private")).status_code == 404
    c.cookies.set("incredible-access", "token-a")
    assert (await c.get("/api/resources/private")).status_code == 200
    assert made == [A, B]


async def test_login_uses_httponly_cookies_and_does_not_return_tokens(client):
    c, _ = client
    r = await c.post(
        "/api/auth/login",
        json={"email": "member@example.com", "password": "valid-password"},
        headers={"Origin": ORIGIN},
    )
    assert r.status_code == 200
    assert "fresh-a" not in r.text and "rotated" not in r.text
    assert all("HttpOnly" in v and "SameSite=lax" in v for v in r.headers.get_list("set-cookie"))
    assert (await c.get("/api/auth/session")).json()["user"]["id"] == A


async def test_login_errors_are_generic_and_csrf_is_blocked(client):
    c, _ = client
    body = {"email": "member@example.com", "password": "invalid-password"}
    assert (await c.post("/api/auth/login", json=body)).status_code == 403
    assert (
        await c.post("/api/auth/login", json=body, headers={"Origin": "https://attacker.invalid"})
    ).status_code == 403
    r = await c.post("/api/auth/login", json=body, headers={"Origin": ORIGIN})
    assert r.status_code == 401 and "private provider error" not in r.text
    assert (
        await c.post(
            "/api/auth/login",
            json={"email": "invalid", "password": "x"},
            headers={"Origin": ORIGIN},
        )
    ).status_code == 422


async def test_refresh_rotates_tokens_and_logout_clears_them(client):
    c, _ = client
    c.cookies.set("incredible-access", "expired")
    c.cookies.set("incredible-refresh", "old-refresh")
    r = await c.get("/api/auth/session")
    assert r.status_code == 200
    assert any("rotated" in v for v in r.headers.get_list("set-cookie"))
    r = await c.post("/api/auth/logout", headers={"Origin": ORIGIN})
    assert r.status_code == 200
    assert all("Max-Age=0" in v for v in r.headers.get_list("set-cookie"))


async def test_google_uses_pkce_and_rejects_a_callback_without_its_cookie(client):
    c, _ = client
    r = await c.get("/api/auth/google")
    assert r.status_code == 303
    assert "code_challenge=" in r.headers["location"]
    assert (
        "redirect_to=http%3A%2F%2F127.0.0.1%3A8765%2Fapi%2Fauth%2Fcallback" in r.headers["location"]
    )
    assert "HttpOnly" in r.headers["set-cookie"]
    c.cookies.clear()
    assert (
        await c.get("/api/auth/callback?code=stolen&next=https://attacker.invalid")
    ).status_code == 400


async def test_signup_sends_pkce_and_returns_confirmation_instead_of_a_session(client):
    c, _ = client
    r = await c.post(
        "/api/auth/signup",
        json={"email": "member@example.com", "password": "valid-password"},
        headers={"Origin": ORIGIN},
    )
    assert r.status_code == 200 and "confirm" in r.text.lower()
    assert "incredible-access" not in r.headers.get("set-cookie", "")


def test_required_auth_configuration_fails_closed(tmp_path):
    with pytest.raises(ValueError):
        create_authenticated_app(tmp_path, Settings(_env_file=None))


async def test_oauth_callback_can_only_return_to_the_app(client):
    c, _ = client
    await c.get("/api/auth/google")
    r = await c.get("/api/auth/callback?code=valid&next=https://attacker.invalid")
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert any(
        "incredible-pkce=" in v and "Max-Age=0" in v for v in r.headers.get_list("set-cookie")
    )


async def test_invalid_password_is_never_echoed_in_validation_errors(client):
    c, _ = client
    r = await c.post(
        "/api/auth/login",
        json={"email": "member@example.com", "password": "x1!"},
        headers={"Origin": ORIGIN},
    )
    assert r.status_code == 422 and "x1!" not in r.text


async def test_credential_attempts_are_rate_limited(client):
    c, _ = client
    for _ in range(20):
        r = await c.post(
            "/api/auth/login",
            json={"email": "member@example.com", "password": "invalid-password"},
            headers={"Origin": ORIGIN},
        )
        assert r.status_code == 401
    assert (
        await c.post(
            "/api/auth/login",
            json={"email": "member@example.com", "password": "invalid-password"},
            headers={"Origin": ORIGIN},
        )
    ).status_code == 429


async def test_auth_pages_and_errors_cannot_be_framed_or_cached(client):
    c, _ = client
    response = await c.get("/api/auth/session")
    assert response.status_code == 401
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "no-referrer"
    assert response.headers.get("cache-control") == "no-store"
