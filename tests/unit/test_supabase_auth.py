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
        if request.method == "PUT":
            assert uid and json.loads(request.content) == {
                "password": "new-test-password",
                "data": {"studio_password_set": True},
                **({"current_password": "current-test-password"} if uid == B else {}),
            }
        return httpx.Response(
            200 if uid else 401,
            json={
                "id": uid,
                "email": "member@example.com",
                "app_metadata": {"providers": ["email" if uid == B else "google"]},
                "email_confirmed_at": "2026-01-01T00:00:00Z",
            },
        )
    if request.url.path.endswith("/token"):
        body = json.loads(request.content)
        if body.get("password") == "invalid-password":
            return httpx.Response(400, json={"error_description": "private provider error"})
        return httpx.Response(
            200,
            json={
                "access_token": "token-b"
                if body.get("password") == "current-test-password"
                else "fresh-a",
                "refresh_token": "rotated",
                "expires_in": 3600,
            },
        )
    if request.url.path.endswith("/signup"):
        body = json.loads(request.content)
        assert body.get("code_challenge") and body.get("code_challenge_method") == "s256"
        if body["email"] == "existing@example.com":
            return httpx.Response(200, json={"id": A, "identities": []})
        if body["email"] == "duplicate@example.com":
            return httpx.Response(422, json={"error_code": "user_already_exists"})
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
        research_catalog_dir=tmp_path / "catalogs",
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


async def test_browser_callback_without_verifier_returns_to_sign_in(client):
    c, _ = client
    response = await c.get("/api/auth/callback?code=test-code", headers={"Accept": "text/html"})
    assert response.status_code == 303
    assert response.headers["location"] == "/?auth_error=link"
    assert "set-cookie" not in response.headers
    assert (await c.get("/api/session")).status_code == 401


@pytest.mark.parametrize("email", ["existing@example.com", "duplicate@example.com"])
async def test_duplicate_signup_prompts_sign_in(client, email):
    c, _ = client
    response = await c.post(
        "/api/auth/signup",
        json={"email": email, "password": "valid-password"},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 409
    assert "already" in response.json()["detail"]
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(("token", "has_password"), [("token-a", False), ("token-b", True)])
async def test_password_settings_use_authenticated_account(client, token, has_password):
    c, _ = client
    c.cookies.set("incredible-access", token)
    assert (await c.get("/api/auth/session")).json()["user"]["has_password"] is has_password
    r = await c.post(
        "/api/auth/password",
        headers={"Origin": ORIGIN},
        json={
            "password": "new-test-password",
            "current_password": "current-test-password" if has_password else None,
        },
    )
    assert r.status_code == 200
    assert r.json() == {"has_password": True}


async def test_password_label_persists_for_google_account_after_reload(client, monkeypatch):
    c, _ = client
    original = provider
    saved = {}

    def persistent_provider(request):
        result = original(request)
        if request.url.path.endswith("/user"):
            if request.method == "PUT":
                saved.update(json.loads(request.content)["data"])
            return httpx.Response(
                result.status_code, json={**result.json(), "user_metadata": saved}
            )
        return result

    # The client fixture's transport is already built; swap only its provider handler.
    monkeypatch.setattr(
        c._transport.app.state.auth.client._transport, "handler", persistent_provider
    )
    c.cookies.set("incredible-access", "token-a")
    assert not (await c.get("/api/auth/session")).json()["user"]["has_password"]
    response = await c.post(
        "/api/auth/password", headers={"Origin": ORIGIN}, json={"password": "new-test-password"}
    )
    assert response.status_code == 200
    assert (await c.get("/api/auth/session")).json()["user"]["has_password"]


async def test_password_settings_require_session_origin_and_valid_password(client):
    c, _ = client
    data = {"password": "new-test-password"}
    assert (
        await c.post("/api/auth/password", headers={"Origin": ORIGIN}, json=data)
    ).status_code == 401
    c.cookies.set("incredible-access", "token-a")
    assert (await c.post("/api/auth/password", json=data)).status_code == 403
    r = await c.post("/api/auth/password", headers={"Origin": ORIGIN}, json={"password": "x7test"})
    assert r.status_code == 422 and "x7test" not in r.text


@pytest.mark.parametrize("current", [None, "invalid-password"])
async def test_existing_account_must_confirm_password(client, current):
    c, _ = client
    c.cookies.set("incredible-access", "token-b")
    response = await c.post(
        "/api/auth/password",
        headers={"Origin": ORIGIN},
        json={
            "password": "new-test-password",
            "current_password": current,
        },
    )
    assert response.status_code == 400
    assert "current password" in response.json()["detail"].lower()


def test_profile_and_model_preferences_survive_reopen(tmp_path):
    from design_agent.surfaces.web.store import Store

    db = tmp_path / "house.sqlite"
    store = Store(db)
    store.save_profile("you", "Nova", 220)
    store.save_model_default("openai:gpt-6", "high")
    reopened = Store(db)
    assert reopened.person("you")["name"] == "Nova"
    assert reopened.person("you")["initials"] == "N"
    assert reopened.person("you")["hue"] == 220
    assert reopened.model_default() == {"model": "openai:gpt-6", "effort": "high"}


async def test_verifying_current_password_checks_provider_and_rotates_session(client):
    c, _ = client
    c.cookies.set("incredible-access", "token-b")
    for password, status in [("invalid-password", 400), ("current-test-password", 200)]:
        response = await c.post(
            "/api/auth/password/verify", headers={"Origin": ORIGIN}, json={"password": password}
        )
        assert response.status_code == status
        assert password not in response.text
        if status == 200:
            assert response.json() == {"verified": True}
            assert "HttpOnly" in response.headers["set-cookie"]


async def test_unknown_username_has_generic_login_failure(client):
    c, _ = client
    response = await c.post(
        "/api/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": "unknown_handle", "password": "valid-password"},
    )
    assert response.status_code == 401


async def test_directory_owner_and_invitation_boundary(client):
    c, _ = client
    c.cookies.set("incredible-access", "token-a")
    headers = {"Origin": ORIGIN}
    response = await c.post(
        "/api/team/invite", headers=headers, json={"email": "other@example.com"}
    )
    assert response.status_code == 200
    invite = response.json()["id"]
    c.cookies.set("incredible-access", "token-b")
    assert (await c.post(f"/api/team/{invite}/accept", headers=headers)).status_code == 403
    assert (await c.delete(f"/api/team/{invite}", headers=headers)).status_code == 404
    c.cookies.set("incredible-access", "token-a")
    assert (await c.delete(f"/api/team/{invite}", headers=headers)).status_code == 200


async def test_project_host_requires_membership_and_matching_origin(client):
    c, _ = client
    url = f"http://{A}.localhost:8765"
    c.cookies.set("incredible-access", "token-b")
    assert (await c.get(url + "/api/session")).status_code == 403
    c.cookies.set("incredible-access", "token-a")
    assert (await c.get(url + "/api/session")).status_code == 200
    assert (
        await c.post(url + "/api/resources/test", headers={"Origin": ORIGIN})
    ).status_code == 403
    assert (await c.post(url + "/api/resources/test", headers={"Origin": url})).status_code == 200


async def test_username_is_unique_and_bound_to_verified_user(client):
    c, _ = client
    headers = {"Origin": ORIGIN}
    profile = {"first_name": "Alex", "last_name": "River", "username": "Studio_Alex"}
    c.cookies.set("incredible-access", "token-a")
    assert (await c.put("/api/account/details", headers=headers, json=profile)).status_code == 200
    assert (await c.get("/api/account/details")).json() == profile | {"username": "studio_alex"}
    c.cookies.set("incredible-access", "token-b")
    assert (await c.put("/api/account/details", headers=headers, json=profile)).status_code == 409
    login = {"email": "STUDIO_ALEX", "password": "valid-password"}
    assert (await c.post("/api/auth/login", headers=headers, json=login)).status_code == 200
    # Simulate an old email address now owned by a different verified identity.
    login["password"] = "current-test-password"
    assert (await c.post("/api/auth/login", headers=headers, json=login)).status_code == 401
    assert (
        await c.put(
            "/api/account/details", headers=headers, json=profile | {"username": "invalid@name"}
        )
    ).status_code == 422


async def test_activity_is_scoped_filterable_and_omits_request_content(client):
    c, _ = client
    c.cookies.set("incredible-access", "token-a")
    await c.post(
        "/api/resources/example", headers={"Origin": ORIGIN}, json={"private": "sensitive contents"}
    )
    events = (await c.get("/api/activity", params={"actor_id": A})).json()
    assert events["events"][0]["action"] == "POST /api/resources/{name}"
    assert "sensitive contents" not in str(events)
    assert (await c.get("/api/activity", params={"actor_id": B})).json()["events"] == []
    c.cookies.set("incredible-access", "token-b")
    assert (await c.get("/api/activity")).json()["events"] == []


async def test_invite_log_identifies_event_and_member(client):
    c, _ = client
    c.cookies.set("incredible-access", "token-a")
    result = await c.post(
        "/api/team/invite", headers={"Origin": ORIGIN}, json={"email": "guest@example.com"}
    )
    assert result.status_code == 200
    event = (await c.get("/api/activity")).json()["events"][0]
    assert event["member_email"] == "guest@example.com"
    assert event["duration_ms"] >= 0
    assert len(event["id"]) == 32


async def test_pending_invitation_link_matches_mail_and_remains_copyable_on_failure(
    client, monkeypatch
):
    from design_agent.surfaces.web import team

    c, _ = client
    c.cookies.set("incredible-access", "token-a")
    sent = []

    def capture(settings, email, organization, owner, link):
        sent.append((email, organization, owner, link))
        return email != "offline@example.com"

    monkeypatch.setattr(team, "send_invitation", capture)
    for email, delivered in [("guest@example.com", True), ("offline@example.com", False)]:
        result = await c.post("/api/team/invite", headers={"Origin": ORIGIN}, json={"email": email})
        result.raise_for_status()
        invitation = result.json()
        link = f"http://{A}.localhost:8765/invite/{invitation['id']}"
        assert invitation["invite_url"] == link and invitation["email_sent"] is delivered
        assert sent[-1][0] == email and sent[-1][-1] == link
        pending = (await c.get("/api/team")).json()["members"]
        assert next(row for row in pending if row["email"] == email)["invite_url"] == link
        c.cookies.set("incredible-access", "token-b")
        assert (
            await c.get(f"http://{A}.localhost:8765/api/team/{invitation['id']}")
        ).status_code == 403
        c.cookies.set("incredible-access", "token-a")


@pytest.mark.parametrize("method", ["google", "signup"])
async def test_auth_callback_restores_only_an_invite_path(client, method):
    c, _ = client
    invitation = "a" * 32
    if method == "google":
        await c.get("/api/auth/google", params={"invite": invitation})
    else:
        await c.post(
            "/api/auth/signup",
            params={"invite": invitation},
            headers={"Origin": ORIGIN},
            json={"email": "guest@example.com", "password": "test-password"},
        )
    callback = await c.get("/api/auth/callback?code=valid")
    assert callback.headers["location"] == "/invite/" + invitation
    await c.get("/api/auth/google", params={"invite": "https://example.com"})
    assert (await c.get("/api/auth/callback?code=valid")).headers["location"] == "/"


async def test_private_research_options_are_empty_and_start_is_forbidden(client):
    c, made = client
    c.cookies.set("incredible-access", "token-a")
    options = await c.get("/api/research")
    assert options.status_code == 200
    assert options.json() == {"harnesses": [], "models": {}, "repos": []}
    start = await c.post("/api/channels/brand/research", headers={"Origin": ORIGIN}, json={})
    assert start.status_code == 403
    assert not made


async def test_local_discovery_lists_only_verified_users_catalog(client, tmp_path):
    c, made = client
    catalogs = tmp_path / "catalogs"
    catalogs.mkdir()
    catalog = catalogs / f"{A}.json"
    catalog.write_text(json.dumps(["studio", "team/studio-web"]))
    assert (await c.get("/api/research")).status_code == 401
    c.cookies.set("incredible-access", "token-b")
    assert (await c.get("/api/research", headers={"X-Person": A})).json()["repos"] == []
    c.cookies.set("incredible-access", "token-a")
    options = (await c.get("/api/research")).json()
    assert options["discovery_only"] is True
    assert options["repos"] == [
        {"name": "studio", "path": "studio", "branch": ""},
        {"name": "studio-web", "path": "team/studio-web", "branch": ""},
    ]
    assert (
        await c.post("/api/channels/brand/research", headers={"Origin": ORIGIN})
    ).status_code == 403
    catalog.write_text("broken")
    assert (await c.get("/api/research")).status_code == 503
    assert not made


async def test_only_configured_owner_can_reach_execution_routes(client, monkeypatch):
    c, made = client
    monkeypatch.setattr(Settings, "private_research_enabled", lambda self, uid: uid == A)
    c.cookies.set("incredible-access", "token-b")
    response = await c.post(
        "/api/channels/brand/research", headers={"Origin": ORIGIN, "X-Person": A}
    )
    assert response.status_code == 403 and not made
    c.cookies.set("incredible-access", "token-a")
    # The tenant test app has no research route; reaching its router proves owner dispatch.
    assert (
        await c.post("/api/channels/brand/research", headers={"Origin": ORIGIN})
    ).status_code == 404
    assert made == [A]
