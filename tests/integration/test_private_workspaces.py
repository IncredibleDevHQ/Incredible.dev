"""Opt-in real Postgres tests: TEST_DATABASE_URL must name a disposable test database.

Only randomly named, test-owned user schemas are created and removed. No Auth users or emails
are created. Mocked provider validation keeps sign-in tests offline while exercising the real
HTTP application, PostgreSQL store and LangGraph persistence.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import httpx
import pytest
from psycopg import connect, sql
from pydantic import SecretStr

from design_agent.config import Settings
from design_agent.runtime.persistence import open_persistence
from design_agent.surfaces.web.auth import create_authenticated_app, user_schema
from design_agent.surfaces.web.store import Store

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="set TEST_DATABASE_URL for real Postgres integration"
)


@pytest.fixture
def database():
    credential = SecretStr(os.environ["TEST_DATABASE_URL"])
    users = [{"id": str(uuid.uuid4()), "email": f"member-{i}@example.com"} for i in range(2)]
    try:
        yield credential, users
    finally:
        if os.getenv("TEST_S3_CONFIG"):
            from tests.integration.test_minio import remove_test_objects

            remove_test_objects([uuid.UUID(u["id"]).hex for u in users])
        with connect(credential.get_secret_value(), autocommit=True) as conn:
            for user in users:
                conn.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(user_schema(user["id"]))
                    )
                )


async def test_ui_data_and_graph_memory_are_private_and_survive_reopening(database, tmp_path: Path):
    credential, users = database
    stores = [
        Store(
            tmp_path / str(i),
            database_url=credential.get_secret_value(),
            schema=user_schema(u["id"]),
            user=u,
        )
        for i, u in enumerate(users)
    ]
    try:
        a, b = stores
        assert [p["id"] for p in a.people() if not p["agent"]] == [users[0]["id"]]
        assert not list(tmp_path.rglob("*.sqlite"))
        # Simulate a lost workspace connection without restarting the application.
        with a._db.pool.connection() as idle:
            idle.close()
        channel = a.add_channel("private")
        assert b.channel(channel["id"]) is None
        assert b._one("SELECT id FROM channels WHERE name = ?", ("private",)) is None
        # Parameter binding must preserve quotes, question marks and SQL-shaped text as data.
        marker = "hello? '); DROP TABLE channels; --"
        a.update_channel(channel["id"], topic=marker)
        assert a.channel(channel["id"])["topic"] == marker
        stamp = a.channel(channel["id"])["created_at"]
        a.close()
        stores[0] = Store(
            tmp_path / "reopened",
            database_url=credential.get_secret_value(),
            schema=user_schema(users[0]["id"]),
            user=users[0],
        )
        assert stores[0].channel(channel["id"])["created_at"] == stamp
        settings = Settings(_env_file=None, database_url=credential)
        async with open_persistence(settings, tmp_path, schema=user_schema(users[0]["id"])) as (
            _,
            memory,
        ):
            async with memory.conn.connection() as idle:
                await idle.close()
            await memory.aput(("same-namespace",), "same-key", {"private": "alpha"})
        async with open_persistence(settings, tmp_path, schema=user_schema(users[1]["id"])) as (
            _,
            memory,
        ):
            assert await memory.aget(("same-namespace",), "same-key") is None
        async with open_persistence(settings, tmp_path, schema=user_schema(users[0]["id"])) as (
            _,
            memory,
        ):
            assert (await memory.aget(("same-namespace",), "same-key")).value == {
                "private": "alpha"
            }
    finally:
        for store in stores:
            store.close()


async def test_real_private_apps_reject_other_users_channel_file_and_thread_ids(
    database, tmp_path: Path
):
    credential, users = database
    root = Path(__file__).resolve().parents[2]
    tokens = {"alpha": users[0], "beta": users[1]}

    def provider(request):
        user = tokens.get(request.headers.get("Authorization", "").removeprefix("Bearer "))
        return httpx.Response(
            200 if user else 401,
            json={**(user or {}), "email_confirmed_at": "2026-01-01T00:00:00Z"},
        )

    settings = Settings(
        _env_file=None,
        database_url=credential,
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="public-test-key",
        workspace_root=tmp_path,
    )
    if os.getenv("TEST_S3_CONFIG"):
        storage = Settings(_env_file=os.environ["TEST_S3_CONFIG"])
        settings = settings.model_copy(
            update={
                key: getattr(storage, key)
                for key in (
                    "blob_backend",
                    "s3_endpoint",
                    "s3_bucket",
                    "s3_region",
                    "s3_access_key",
                    "s3_secret_key",
                )
            }
        )
    app = create_authenticated_app(
        root, settings, demo=True, transport=httpx.MockTransport(provider)
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8765",
            headers={"Origin": "http://127.0.0.1:8765"},
        ) as client:
            client.cookies.set("incredible-access", "alpha")
            channel = (
                (await client.post("/api/channels", json={"name": "private"}))
                .raise_for_status()
                .json()
            )
            message = (
                (
                    await client.post(
                        "/api/channels/" + channel["id"] + "/messages",
                        json={"text": "Private note", "to_agent": False, "files": []},
                    )
                )
                .raise_for_status()
                .json()
            )
            upload = (
                (
                    await client.post(
                        "/api/uploads", files={"files": ("note.txt", b"private data", "text/plain")}
                    )
                )
                .raise_for_status()
                .json()
            )
            file_id = upload[0]["id"]
            client.cookies.set("incredible-access", "beta")
            assert (
                await client.get("/api/channels/" + channel["id"] + "/messages")
            ).status_code == 404
            assert (await client.get("/api/threads/" + message["thread_id"])).status_code == 404
            assert (await client.get("/api/files/" + file_id)).status_code == 404
            assert (
                await client.post("/api/threads/" + message["thread_id"] + "/stop")
            ).status_code == 404
            session = (
                await client.get("/api/session", headers={"X-Person": users[0]["id"]})
            ).json()
            assert session["me"] == users[1]["id"]
            assert all(p["id"] in {users[1]["id"], "agent"} for p in session["people"])
            a = app.state.tenants.apps[users[0]["id"]].state.host
            b = app.state.tenants.apps[users[1]["id"]].state.host
            profile = {"name": "Private studio", "website": "", "description": "Beta only"}
            assert (
                await client.put("/api/organization", json=profile)
            ).raise_for_status().json() == profile
            assert (await client.get("/api/session")).json()["organizationName"] == profile["name"]
            assert (await client.get("/api/session")).json()["email"] == users[1]["email"]
            a.store.add_activity(
                {
                    "kind": "usage",
                    "thread_id": message["thread_id"],
                    "at": 1,
                    "data": {"input_tokens": 31, "priced": False},
                }
            )
            assert (await client.get("/api/usage")).raise_for_status().json()["input_tokens"] == 0
            if settings.blob_backend == "s3":
                assert a.store.file(file_id)["storage"] == "s3"
                assert not list(tmp_path.rglob("note.txt"))
                delivered = await asyncio.to_thread(
                    a.save_file,
                    message["thread_id"],
                    "generated.txt",
                    b"generated bytes",
                    origin="delivered",
                )
                assert (await client.get("/api/files/" + delivered["id"])).status_code == 404
            a.hub.bind(asyncio.get_running_loop())
            b.hub.bind(asyncio.get_running_loop())
            own_queue = a.hub.open()
            queue = b.hub.open()
            a.hub.publish("private-event", secret="alpha")
            await asyncio.sleep(0)
            assert own_queue.get_nowait()["secret"] == "alpha"
            assert queue.empty()
            a.hub.close(own_queue)
            b.hub.close(queue)
            client.cookies.set("incredible-access", "alpha")
            assert (await client.get("/api/organization")).raise_for_status().json()["name"] == ""
            assert (await client.get("/api/usage")).raise_for_status().json()["input_tokens"] == 31
            assert (await client.get("/api/files/" + file_id)).content == b"private data"
            if settings.blob_backend == "s3":
                assert (
                    await client.get("/api/files/" + delivered["id"])
                ).content == b"generated bytes"
