"""Private, cross-project directory for authenticated Studio accounts."""

from __future__ import annotations

import asyncio
import re
import sqlite3
import unicodedata
import uuid
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from design_agent.surfaces.web.workspace_directory import backfill_workspace_directory

TABLES = (
    """CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY, email TEXT NOT NULL, username TEXT UNIQUE,
        first_name TEXT NOT NULL DEFAULT '', last_name TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS invitations (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, email TEXT NOT NULL, member TEXT,
        UNIQUE(owner,email), UNIQUE(owner,member))""",
    """CREATE TABLE IF NOT EXISTS project_addresses (
        owner TEXT NOT NULL, base TEXT NOT NULL, slug TEXT NOT NULL UNIQUE, PRIMARY KEY(owner,base))""",
    """CREATE TABLE IF NOT EXISTS project_visits (
        actor TEXT PRIMARY KEY, project TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS browser_sessions (
        id TEXT PRIMARY KEY, actor TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS project_sessions (
        id TEXT PRIMARY KEY, project TEXT NOT NULL, session TEXT NOT NULL
        REFERENCES browser_sessions(id) ON DELETE CASCADE, access TEXT NOT NULL,
        expires DOUBLE PRECISION NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS project_session_expiry ON project_sessions(expires)",
    """CREATE TABLE IF NOT EXISTS project_handoffs (
        flow TEXT PRIMARY KEY, proof TEXT NOT NULL, project TEXT NOT NULL, path TEXT NOT NULL,
        expires DOUBLE PRECISION NOT NULL, code TEXT UNIQUE, payload TEXT, session TEXT)""",
    "CREATE INDEX IF NOT EXISTS handoff_expiry ON project_handoffs(expires)",
    """CREATE TABLE IF NOT EXISTS activity (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, actor TEXT NOT NULL, actor_email TEXT NOT NULL, action TEXT NOT NULL,
        happened DOUBLE PRECISION NOT NULL, status INTEGER NOT NULL,
        member_email TEXT, duration_ms INTEGER)""",
    "CREATE INDEX IF NOT EXISTS activity_project_time ON activity(owner,happened)",
)


def hostname_label(words: str, suffix: str) -> str:
    # Encode the suffix along with the name so duplicate international names remain valid IDNs.
    words = words[: 63 - len(suffix)].rstrip("-")
    while words:
        try:
            label = (words + suffix).encode("idna").decode("ascii")
            if re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label):
                return label
        except UnicodeError:
            pass
        words = words[:-1].rstrip("-")
    return "workspace" + suffix


class Directory:
    def __init__(self, url: str | None) -> None:
        async def configure(connection: AsyncConnection[Any]) -> None:
            await connection.execute("SET search_path TO studio_directory")

        self.url = url
        self.pool: AsyncConnectionPool[AsyncConnection[Any]] | None = (
            AsyncConnectionPool(
                url,
                open=False,
                min_size=0,
                max_size=4,
                configure=configure,
                kwargs={
                    "autocommit": True,
                    "row_factory": dict_row,
                    "prepare_threshold": None,
                },
            )
            if url
            else None
        )
        self.local: sqlite3.Connection | None = None

    async def open(self) -> None:
        if self.pool:
            await self.pool.open()
            assert self.url is not None  # noqa: S101 - the pool and URL are configured together
            await asyncio.to_thread(backfill_workspace_directory, self.url)
        else:
            self.local = sqlite3.connect(":memory:", isolation_level=None)
            self.local.row_factory = sqlite3.Row
            self.local.execute("PRAGMA foreign_keys=ON")
        for statement in TABLES:
            await self.query(statement)
        if self.pool:
            await self.query(
                "ALTER TABLE activity ADD COLUMN IF NOT EXISTS member_email TEXT, "
                "ADD COLUMN IF NOT EXISTS duration_ms INTEGER"
            )
            for table in (
                "accounts",
                "invitations",
                "activity",
                "project_visits",
                "project_addresses",
                "browser_sessions",
                "project_handoffs",
                "project_sessions",
            ):
                await self.query(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()
        elif self.local:
            self.local.close()

    async def query(self, statement: str, *values: Any) -> list[dict[str, Any]]:
        if self.pool:
            async with self.pool.connection() as conn:
                cursor = await conn.execute(statement.replace("?", "%s"), values)
                return list(await cursor.fetchall()) if cursor.description else []
        if self.local is None:
            raise RuntimeError("Account directory has not started")
        return [dict(row) for row in self.local.execute(statement, values).fetchall()]

    async def organization_slug(self, owner: str, name: str) -> str:
        normalized = unicodedata.normalize("NFKD", name.casefold())
        normalized = "".join(c for c in normalized if not unicodedata.combining(c))
        words = re.sub(r"[\W_]+", "-", normalized.replace("’", "").replace("'", "")).strip("-")
        if words in {"www", "api", "auth", "app", "admin", "mail", "localhost", "studio"}:
            words += "-team"
        if re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", words):
            words = "workspace"
        base = hostname_label(words, "")
        suffix = ""
        index = 1
        while True:
            rows = await self.query(
                "SELECT slug FROM project_addresses WHERE owner=? AND base=?", owner, base
            )
            if rows:
                return str(rows[0]["slug"])
            slug = hostname_label(words, suffix)
            rows = await self.query(
                "INSERT INTO project_addresses(owner,base,slug) VALUES(?,?,?) "
                "ON CONFLICT DO NOTHING RETURNING slug",
                owner,
                base,
                slug,
            )
            if rows:
                return slug
            index += 1
            suffix = f"-{index}"

    async def project_for_label(self, label: str) -> str | None:
        try:
            if str(uuid.UUID(label)) == label:
                return label
        except ValueError:
            pass
        rows = await self.query("SELECT owner FROM project_addresses WHERE slug=?", label)
        return str(rows[0]["owner"]) if rows else None

    async def project(self, user: dict[str, Any], selected: str | None) -> dict[str, Any]:
        from fastapi import HTTPException

        if not selected or selected == user["id"]:
            return user
        rows = await self.query(
            "SELECT a.id,a.email FROM invitations i JOIN accounts a ON a.id=i.owner "
            "WHERE i.owner=? AND i.member=?",
            selected,
            user["id"],
        )
        if not rows:
            raise HTTPException(
                403, "Access to this project has ended. Open Members to return to your project."
            )
        return rows[0]

    async def remember(self, actor: str, project: str) -> None:
        await self.query(
            "INSERT INTO project_visits(actor,project) VALUES(?,?) ON CONFLICT(actor) "
            "DO UPDATE SET project=excluded.project WHERE project_visits.project<>excluded.project",
            actor,
            project,
        )
