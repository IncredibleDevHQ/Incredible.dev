"""Opt-in Chromium test with a disposable Postgres DB, built web app and offline identity provider."""

import asyncio
import base64
import hashlib
import json
import os
import socket
import uuid
from pathlib import Path
from urllib.parse import urlencode

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from psycopg import connect, sql
from pydantic import SecretStr

from design_agent.config import Settings
from design_agent.surfaces.web.auth import create_authenticated_app


@pytest.mark.skipif(
    not os.getenv("TEST_PROJECT_BROWSER"),
    reason="set TEST_PROJECT_BROWSER and TEST_DATABASE_URL for browser integration",
)
async def test_browser_project_sign_in(tmp_path):
    database = os.environ["TEST_DATABASE_URL"]
    root = Path(__file__).resolve().parents[2]
    users = [str(uuid.uuid4()) for _ in range(2)]
    challenges = {}
    confirmed = set()

    def provider(request):
        path = request.url.path
        if path.endswith("/settings"):
            return httpx.Response(200, json={"external": {"email": True, "google": True}})
        if path.endswith("/user"):
            uid = request.headers.get("authorization", "").removeprefix("Bearer ")
            return httpx.Response(
                200 if uid in confirmed else 401,
                json={"id": uid, "email": uid + "@example.com", "email_confirmed_at": "today"},
            )
        if path.endswith("/signup"):
            body = json.loads(request.content)
            uid = body["email"].split("@")[0]
            assert uid in users
            challenges[uid] = body["code_challenge"]
            return httpx.Response(200, json={"user": {"id": uid}})
        if path.endswith("/token"):
            body = json.loads(request.content)
            if "auth_code" in body:
                uid = body["auth_code"]
                challenge = (
                    base64.urlsafe_b64encode(
                        hashlib.sha256(body["code_verifier"].encode()).digest()
                    )
                    .decode()
                    .rstrip("=")
                )
                if uid.startswith("google."):
                    _, uid, expected = uid.split(".")
                    assert uid in confirmed and challenge == expected
                else:
                    assert challenges.pop(uid) == challenge
                confirmed.add(uid)
            else:
                uid = body["email"].split("@")[0]
                assert uid in confirmed and body["password"] == "test-password"
            return httpx.Response(
                200, json={"access_token": uid, "refresh_token": "test-refresh-" + uid}
            )
        return httpx.Response(204)

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        settings = Settings(
            _env_file=None,
            app_url=url,
            supabase_url="https://example.invalid",
            supabase_publishable_key="test-key",
            database_url=SecretStr(database),
            workspace_root=tmp_path,
            auth_required=True,
        )
        app = create_authenticated_app(
            root, settings, demo=True, transport=httpx.MockTransport(provider)
        )
        # The browser navigates to a local stand-in for the hosted consent page.
        # Back-channel token validation still goes through the mock Supabase transport.
        front_channel = FastAPI(lifespan=app.router.lifespan_context)
        app.state.auth.url = f"http://localhost:{port}/test-provider"

        @front_channel.get("/test-provider/authorize")
        async def consent(request: Request):
            params = request.query_params
            assert params["provider"] == "google" and params["code_challenge_method"] == "s256"
            assert params["redirect_to"] == url + "/api/auth/callback"
            code = "google." + users[1] + "." + params["code_challenge"]
            return RedirectResponse(
                params["redirect_to"] + "?" + urlencode({"code": code}), status_code=303
            )

        front_channel.mount("/", app)
        server = uvicorn.Server(
            uvicorn.Config(front_channel, log_level="error", timeout_graceful_shutdown=1)
        )
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(30):
                while not server.started:
                    if task.done():
                        await task
                        pytest.fail("Studio stopped during startup")
                    await asyncio.sleep(0.05)
            proc = await asyncio.create_subprocess_exec(
                "node", str(Path(__file__).with_name("project_login_browser.mjs")), url, *users
            )
            try:
                assert await asyncio.wait_for(proc.wait(), 120) == 0
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
        finally:
            server.should_exit = True
            await task
            with connect(database, autocommit=True) as connection:
                for uid in users:
                    mapping = connection.execute(
                        "DELETE FROM studio_directory.workspaces WHERE owner_id=%s RETURNING schema_name",
                        (uid,),
                    ).fetchone()
                    if mapping:
                        connection.execute(
                            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                                sql.Identifier(mapping[0])
                            )
                        )
                    for table, column in [
                        ("project_handoffs", "project"),
                        ("browser_sessions", "actor"),
                        ("project_visits", "actor"),
                        ("project_addresses", "owner"),
                        ("activity", "actor"),
                        ("invitations", "owner"),
                        ("accounts", "id"),
                    ]:
                        connection.execute(
                            sql.SQL("DELETE FROM studio_directory.{} WHERE {}=%s").format(
                                sql.Identifier(table), sql.Identifier(column)
                            ),
                            (uid,),
                        )
