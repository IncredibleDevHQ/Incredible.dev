"""Opt-in real Postgres tests: TEST_DATABASE_URL must name a disposable test database.

Only randomly named, test-owned user schemas are created and removed. No Auth users or emails
are created. Mocked provider validation keeps sign-in tests offline while exercising the real
HTTP application, PostgreSQL store and LangGraph persistence.
"""

from __future__ import annotations

import asyncio
import os
import re
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
                if conn.execute("SELECT to_regclass('studio_directory.workspaces')").fetchone() != (
                    None,
                ):
                    mapping = conn.execute(
                        "DELETE FROM studio_directory.workspaces WHERE owner_id=%s RETURNING schema_name",
                        (user["id"],),
                    ).fetchone()
                    if mapping:
                        conn.execute(
                            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                                sql.Identifier(mapping[0])
                            )
                        )
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


def test_episode_history_and_voice_clone_backfill_survive_reopening(database, tmp_path: Path):
    credential, users = database
    user = users[0]

    def open_store() -> Store:
        return Store(
            tmp_path / "workspace",
            database_url=credential.get_secret_value(),
            schema=user_schema(user["id"]),
            user=user,
        )

    store = open_store()
    try:
        channel = store.add_channel("episodes")
        thread = store.add_thread(
            thread_id="example",
            channel_id=channel["id"],
            task=True,
            title="Example",
            kind="",
            by=user["id"],
        )
        episode = store.add_episode(
            {
                "thread_id": thread["id"],
                "title": "Example",
                "status": "planned",
                "started_by": user["id"],
                "settings": {"cloned_voice": {"id": "voice-1", "name": "Speaker", "verify": True}},
            }
        )
        plan = {"chapters": [{"id": "first"}]}
        store.put_snapshot(episode["id"], why="Changed plan", data={"plan": plan})
        store.put_snapshot(episode["id"], why="Earlier draft", data={})
    finally:
        store.close()

    store = open_store()
    try:
        history = store.previous_plans(episode["id"])
        assert [item["plan"] for item in history] == [{}, plan]
        assert history[0]["n"] > history[1]["n"]
        voices = store.channel_voice_clones(channel["id"])
        assert [(voice["id"], voice["name"], voice["verify"]) for voice in voices] == [
            ("voice-1", "Speaker", True)
        ]
    finally:
        store.close()


async def test_real_private_apps_reject_other_users_channel_file_and_thread_ids(
    database, tmp_path: Path
):
    credential, users = database
    root = Path(__file__).resolve().parents[2]
    tokens = {"alpha": users[0], "beta": users[1]}
    # The shared project predates the directory. The other account starts on the new naming scheme.
    original = user_schema(users[0]["id"])
    store = Store(
        tmp_path, database_url=credential.get_secret_value(), schema=original, user=users[0]
    )
    try:
        existing = store.add_channel("before-upgrade")
    finally:
        store.close()
    async with open_persistence(
        Settings(_env_file=None, database_url=credential), tmp_path, schema=original
    ) as (_, memory):
        await memory.aput(("before-upgrade",), "state", {"saved": True})

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
            (
                await client.post(
                    f"/api/threads/{message['thread_id']}/messages",
                    json={"text": "Private reply", "to_agent": False},
                )
            ).raise_for_status()
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
            assert a.store.channel(existing["id"])["name"] == "before-upgrade"
            assert (await a.runtime.graph.store.aget(("before-upgrade",), "state")).value == {
                "saved": True
            }
            assert a.blobs.prefix == f"accounts/{uuid.UUID(users[0]['id']).hex}/blobs/"
            assert (
                app.state.tenants.apps[users[1]["id"]].state.host.blobs.prefix
                == f"accounts/{uuid.UUID(users[1]['id']).hex}/blobs/"
            )
            with connect(credential.get_secret_value()) as connection:
                assert connection.execute(
                    "SELECT schema_name FROM studio_directory.workspaces WHERE owner_id=%s",
                    (users[0]["id"],),
                ).fetchone() == (original,)
            b = app.state.tenants.apps[users[1]["id"]].state.host
            profile = {"name": "Private studio", "website": "", "description": "Beta only"}
            assert (
                await client.put("/api/organization", json=profile)
            ).raise_for_status().json() == profile
            assert (await client.get("/api/session")).json()["organizationName"] == profile["name"]
            with connect(credential.get_secret_value()) as connection:
                mapped = connection.execute(
                    "SELECT schema_name, organization_name FROM studio_directory.workspaces WHERE owner_id=%s",
                    (users[1]["id"],),
                ).fetchone()
                assert mapped and re.fullmatch(r"ws_[1-9][0-9]*", mapped[0])
                assert mapped[1] == profile["name"]
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

            invitation = (
                (await client.post("/api/team/invite", json={"email": users[1]["email"]}))
                .raise_for_status()
                .json()
            )
            client.cookies.set("incredible-access", "beta")
            project_url, invite_id = invitation["invite_url"].split("/invite/")
            assert invite_id == invitation["id"]
            preview_url = f"{project_url}/api/team/{invite_id}"
            preview = (await client.get(preview_url)).raise_for_status().json()
            assert not preview["accepted"]
            assert (await client.get(project_url + "/api/session")).status_code == 403
            project = (
                (await client.post(preview_url + "/accept", headers={"Origin": project_url}))
                .raise_for_status()
                .json()["url"]
            )
            assert project == project_url
            assert (await client.get(preview_url)).json()["accepted"]
            shared = (await client.get(project + "/api/session")).raise_for_status().json()
            assert shared["me"] == users[1]["id"] and shared["projectId"] == users[0]["id"]
            assert (await client.get(project + "/api/files/" + file_id)).content == b"private data"
            assert (
                await client.put(
                    project + "/api/organization", json=profile, headers={"Origin": project}
                )
            ).status_code == 403
            client.cookies.set("incredible-access", "alpha")
            (await client.delete("/api/team/" + invitation["id"])).raise_for_status()
            client.cookies.set("incredible-access", "beta")
            assert (await client.get(project + "/api/files/" + file_id)).status_code == 403
            assert (await client.get(preview_url)).status_code == 403

    reopened = create_authenticated_app(
        root,
        settings.model_copy(update={"workspace_root": tmp_path / "replacement"}),
        demo=True,
        transport=httpx.MockTransport(provider),
    )
    async with reopened.router.lifespan_context(reopened):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=reopened),
            base_url="http://127.0.0.1:8765",
            cookies={"incredible-access": "alpha"},
        ) as client:
            thread = (
                (await client.get(f"/api/threads/{message['thread_id']}")).raise_for_status().json()
            )
            assert [item["text"] for item in thread["messages"]] == [
                "Private note",
                "Private reply",
            ]
            if settings.blob_backend == "s3":
                assert (await client.get(f"/api/files/{file_id}")).content == b"private data"


@pytest.mark.render
@pytest.mark.skipif(not os.getenv("TEST_S3_CONFIG"), reason="set TEST_S3_CONFIG for MinIO")
async def test_chapter_recording_reopens_without_the_original_workspace(database, tmp_path: Path):
    """Use the real multipart, FFmpeg, PostgreSQL and MinIO paths with synthetic footage."""
    import subprocess

    from design_agent.surfaces.web.app import create_app
    from design_agent.surfaces.web.computer import PROJECTS
    from design_agent.surfaces.web.demo_episode import SCRIPT
    from design_agent.surfaces.web.episode_workers import DEMO, DemoWorker
    from tests.conftest import SANDBOX_IMAGE

    credential, users = database
    user = users[0]
    root = Path(__file__).resolve().parents[2]
    settings = Settings(
        _env_file=os.environ["TEST_S3_CONFIG"],
        database_url=credential,
        sandbox="docker",
        sandbox_image=SANDBOX_IMAGE,
        workspace_root=tmp_path / "first",
    )
    raw = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network=none",
            "--entrypoint=ffmpeg",
            SANDBOX_IMAGE,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:r=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-f",
            "matroska",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout

    app = create_app(root, settings, demo=True, authenticated_user=user)
    host = app.state.host
    host.episodes.workers[DEMO] = DemoWorker(
        data_dir=tmp_path / "demo", script=SCRIPT, pause=0, store=host.store
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            channel = (
                (await client.post("/api/channels", json={"name": "recordings"}))
                .raise_for_status()
                .json()
            )
            source = (
                (
                    await client.post(
                        "/api/uploads",
                        files={
                            "files": ("source.md", b"Notes about HTTP caching.", "text/markdown")
                        },
                    )
                )
                .raise_for_status()
                .json()[0]
            )
            episode = (
                (
                    await client.post(
                        f"/api/channels/{channel['id']}/episodes",
                        json={
                            "title": "Caching",
                            "files": [source["id"]],
                            "settings": {"writer": DEMO},
                        },
                    )
                )
                .raise_for_status()
                .json()
            )
            episode_id = episode["id"]
            async with asyncio.timeout(15):
                while host.episodes.planning(episode_id):
                    await asyncio.sleep(0.02)
            episode = host.episodes.view(episode_id)
            chapter = episode["plan"]["chapters"][0]["id"]
            response = await client.post(
                f"/api/episodes/{episode_id}/takes",
                data={"chapter": chapter, "label": "First take"},
                files={"file": ("camera.mkv", raw, "video/x-matroska")},
            )
            saved = response.raise_for_status().json()
            assert [job["chapter"] for job in saved["imports"]] == [chapter]
            async with asyncio.timeout(90):
                while saved["imports"]:
                    (job,) = saved["imports"]
                    assert job["state"] != "failed", job["failure"]
                    await asyncio.sleep(0.1)
                    current = await client.get(f"/api/episodes/{episode_id}")
                    saved = current.raise_for_status().json()
            (take,) = saved["takes"]
            assert take["chapter"] == chapter
            row = host.store.take(take["id"])
            bucket, key = row["raw"].removeprefix("s3://").split("/", 1)
            assert bucket == settings.s3_bucket
            with host.blobs.open({"storage": "s3", "rel_path": key}) as original:
                assert original.read() == raw
            for media in (take["video"], take["audio"]):
                assert host.store.file(media["id"])["storage"] == "s3"
            assert not any(path.is_file() for path in host.files_dir.rglob("*"))
            computer = host.episodes._computer(host.store.episode(episode_id))
            assert computer.run(f"test ! -e {PROJECTS}/{episode_id}/takes").ok
            scratch = computer.run("find /tmp -maxdepth 1 -name 'design-agent-take_*'")
            assert scratch.ok and not scratch.output.strip()

    reopened = create_app(
        root,
        settings.model_copy(update={"workspace_root": tmp_path / "replacement"}),
        demo=True,
        authenticated_user=user,
    )
    async with reopened.router.lifespan_context(reopened):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=reopened), base_url="http://test"
        ) as client:
            saved = (await client.get(f"/api/episodes/{episode_id}")).raise_for_status().json()
            assert [kept["id"] for kept in saved["takes"]] == [take["id"]]
            video = await client.get(
                saved["takes"][0]["video"]["url"], headers={"Range": "bytes=0-11"}
            )
            assert video.status_code == 206
            assert video.content[4:8] == b"ftyp"


def test_legacy_backfill_and_concurrent_new_workspace_registration(database, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from design_agent.surfaces.web.workspace_directory import (
        backfill_workspace_directory,
        workspace_schema,
    )

    credential, (old, new) = database
    dsn = credential.get_secret_value()
    legacy = user_schema(old["id"])
    store = Store(tmp_path, database_url=dsn, schema=legacy, user=old)
    try:
        channel = store.add_channel("existing-channel")
        store.save_organization("Existing studio", "", "")
    finally:
        store.close()

    backfill_workspace_directory(dsn)
    with connect(dsn) as conn:
        assert conn.execute(
            "SELECT schema_name, organization_name FROM studio_directory.workspaces WHERE owner_id=%s",
            (old["id"],),
        ).fetchone() == (legacy, "Existing studio")
    with ThreadPoolExecutor(max_workers=6) as workers:
        names = list(workers.map(lambda _: workspace_schema(dsn, uuid.UUID(new["id"])), range(12)))
    assert len(set(names)) == 1
    assert re.fullmatch(r"ws_[1-9][0-9]*", names[0])
    assert workspace_schema(dsn, uuid.UUID(old["id"])) == legacy
    backfill_workspace_directory(dsn)
    assert workspace_schema(dsn, uuid.UUID(new["id"])) == names[0]
    with connect(dsn) as conn:
        assert conn.execute(
            "SELECT schema_name FROM studio_directory.workspaces WHERE owner_id=%s AND schema_name='ws_' || id::text",
            (new["id"],),
        ).fetchone() == (names[0],)
        assert conn.execute(
            sql.SQL("SELECT name FROM {}.channels WHERE id=%s").format(sql.Identifier(legacy)),
            (channel["id"],),
        ).fetchone() == ("existing-channel",)
        assert not conn.execute(
            "SELECT has_schema_privilege('authenticated', %s, 'USAGE')", (names[0],)
        ).fetchone()[0]
    with connect(dsn) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {}").format(sql.Identifier(names[0])))
    with pytest.raises(ValueError, match="Registered workspace schema is missing"):
        workspace_schema(dsn, uuid.UUID(new["id"]))


@pytest.mark.skipif(not os.getenv("TEST_S3_CONFIG"), reason="needs a private test MinIO bucket")
def test_brand_reopens_from_postgres_and_minio_after_migration(database, tmp_path):
    import shutil

    from design_agent.config import project_root
    from design_agent.surfaces.web.blobs import BlobFiles, StorageUnavailable
    from design_agent.surfaces.web.brand_versions import BrandVersions

    url, users = database
    settings = Settings(_env_file=os.environ["TEST_S3_CONFIG"])

    def open_store(user):
        return Store(
            tmp_path / "unused",
            database_url=url.get_secret_value(),
            schema=user_schema(user["id"]),
            user=user,
        )

    a, b = map(open_store, users)
    owner, other = [BlobFiles(settings, tmp_path / "unused", uuid.UUID(u["id"]).hex) for u in users]
    try:
        folder = tmp_path / "brands" / "specimen"
        shutil.copytree(project_root() / "examples/brands/example-studio", folder)
        packs = BrandVersions(a, owner, project_root())
        assert packs.migrate(folder.parent, tmp_path / "default") == 1
        assert packs.migrate(folder.parent, tmp_path / "default") == 0
        version = packs.heads()["specimen"]
        a.close()
        a = open_store(users[0])
        shutil.rmtree(folder)
        packs = BrandVersions(a, owner, project_root())
        with packs.snapshot("specimen", version).open() as temp:
            assert (temp / "brand.toml").is_file()
        assert not temp.exists() and not folder.exists()
        assert a.brand_heads() == {"specimen": version} and not b.brand_heads()
        with (
            pytest.raises(StorageUnavailable),
            BrandVersions(b, other, project_root()).snapshot("specimen", version).open(),
        ):
            pytest.fail("another workspace could read the snapshot")
    finally:
        a.close()
        b.close()
        owner.close()
        other.close()
