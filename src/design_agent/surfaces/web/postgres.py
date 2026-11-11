"""Private PostgreSQL schemas for the web store, preserving its parameterized queries."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from psycopg import Connection, connect, sql
from psycopg.rows import dict_row


def validate_schema(value: str) -> str:
    if not re.fullmatch(r"user_[0-9a-f]{32}", value):
        raise ValueError("A private workspace requires a verified user UUID")
    return value


def pg_schema() -> str:
    from design_agent.surfaces.web.store import ADDED_COLUMNS, SCHEMA

    result = SCHEMA.replace(" REAL", " DOUBLE PRECISION")
    for table, column, kind in ADDED_COLUMNS:
        result += f"\nALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {kind};"
    return result


class IndexedRow(dict[str, Any]):
    def __getitem__(self, key: Any) -> Any:
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def fetchone(self) -> Any:
        row = self.cursor.fetchone()
        self.cursor.close()
        return IndexedRow(row) if row is not None else None

    def fetchall(self) -> list[IndexedRow]:
        rows = self.cursor.fetchall()
        self.cursor.close()
        return [IndexedRow(row) for row in rows]


class PostgresConnection:
    def __init__(self, url: str, schema: str) -> None:
        schema = validate_schema(schema)
        self.connection: Connection[Any] = connect(
            url, autocommit=True, row_factory=dict_row, prepare_threshold=None, connect_timeout=15
        )
        try:
            # No schema is exposed to PostgREST's public/anon/authenticated roles.
            self.connection.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION CURRENT_USER").format(
                    sql.Identifier(schema)
                )
            )
            self.connection.execute(
                sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC, anon, authenticated").format(
                    sql.Identifier(schema)
                )
            )
            self.connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            with self.connection.transaction():
                self.connection.execute(pg_schema(), prepare=False)
                tables = self.connection.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname = %s", (schema,)
                ).fetchall()
                for row in tables:
                    self.connection.execute(
                        sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(
                            sql.Identifier(row["tablename"])
                        )
                    )
        except BaseException:
            self.connection.close()
            raise

    def execute(self, query: str, args: Sequence[Any] = ()) -> Cursor:
        # Callers pass static SQL; values are always bound separately. All Store queries use
        # question marks for placeholders and contain no question-mark string literals.
        return Cursor(self.connection.execute(query.replace("?", "%s"), tuple(args)))

    def close(self) -> None:
        self.connection.close()
