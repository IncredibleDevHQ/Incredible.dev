"""Private, cross-project directory for authenticated Studio accounts."""

from __future__ import annotations

import sqlite3
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

TABLES = (
    """CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY, email TEXT NOT NULL, username TEXT UNIQUE,
        first_name TEXT NOT NULL DEFAULT '', last_name TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS invitations (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, email TEXT NOT NULL, member TEXT,
        UNIQUE(owner,email), UNIQUE(owner,member))""",
    """CREATE TABLE IF NOT EXISTS activity (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, actor TEXT NOT NULL, actor_email TEXT NOT NULL, action TEXT NOT NULL,
        happened DOUBLE PRECISION NOT NULL, status INTEGER NOT NULL,
        member_email TEXT, duration_ms INTEGER)""",
    "CREATE INDEX IF NOT EXISTS activity_project_time ON activity(owner,happened)",
)


class Directory:
    def __init__(self, url: str | None) -> None:
        async def configure(connection: AsyncConnection[Any]) -> None:
            await connection.execute("SET search_path TO studio_directory")

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
            await self.query(
                "CREATE SCHEMA IF NOT EXISTS studio_directory AUTHORIZATION CURRENT_USER"
            )
            await self.query(
                "REVOKE ALL ON SCHEMA studio_directory FROM PUBLIC, anon, authenticated"
            )
        else:
            self.local = sqlite3.connect(":memory:", isolation_level=None)
            self.local.row_factory = sqlite3.Row
        for statement in TABLES:
            await self.query(statement)
        if self.pool:
            await self.query(
                "ALTER TABLE activity ADD COLUMN IF NOT EXISTS member_email TEXT, "
                "ADD COLUMN IF NOT EXISTS duration_ms INTEGER"
            )
            for table in ("accounts", "invitations", "activity"):
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
