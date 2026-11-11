"""Private PostgreSQL schemas for the web store, preserving its parameterized queries."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


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
    def __init__(self, rows: list[IndexedRow]) -> None:
        self.rows = rows

    def fetchone(self) -> IndexedRow | None:
        return next(iter(self.rows), None)

    def fetchall(self) -> list[IndexedRow]:
        return self.rows


class PostgresConnection:
    def __init__(self, url: str, schema: str) -> None:
        schema = validate_schema(schema)

        def configure(connection: Connection[Any]) -> None:
            connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))

        self.pool: ConnectionPool[Connection[Any]] = ConnectionPool(
            url,
            min_size=0,
            max_size=1,
            timeout=15,
            configure=configure,
            check=ConnectionPool.check_connection,
            kwargs={
                "autocommit": True,
                "row_factory": dict_row,
                "prepare_threshold": None,
                "connect_timeout": 15,
            },
        )
        try:
            with self.pool.connection() as connection:
                # No schema is exposed to PostgREST's public/anon/authenticated roles.
                connection.execute(
                    sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION CURRENT_USER").format(
                        sql.Identifier(schema)
                    )
                )
                connection.execute(
                    sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC, anon, authenticated").format(
                        sql.Identifier(schema)
                    )
                )
                with connection.transaction():
                    connection.execute(pg_schema(), prepare=False)
                    tables = connection.execute(
                        "SELECT tablename FROM pg_tables WHERE schemaname = %s", (schema,)
                    ).fetchall()
                    for row in tables:
                        connection.execute(
                            sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(
                                sql.Identifier(row["tablename"])
                            )
                        )
        except BaseException:
            self.pool.close()
            raise

    def execute(self, query: str, args: Sequence[Any] = ()) -> Cursor:
        # Callers pass static SQL; values are always bound separately. All Store queries use
        # question marks for placeholders and contain no question-mark string literals.
        with (
            self.pool.connection() as connection,
            connection.execute(query.replace("?", "%s"), tuple(args)) as cursor,
        ):
            return Cursor([IndexedRow(row) for row in cursor] if cursor.description else [])

    def close(self) -> None:
        self.pool.close()
