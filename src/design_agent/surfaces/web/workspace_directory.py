"""Map verified project owners to private PostgreSQL schemas, independently of file namespaces."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg import Connection, connect, sql
from psycopg.errors import DuplicateSchema

# Serialize cold registration and backfill across web processes. The lock is released on commit.
LOCK = "SELECT pg_advisory_xact_lock(hashtextextended('studio_directory.workspaces', 0))"

CREATE_DIRECTORY = """
CREATE SCHEMA IF NOT EXISTS studio_directory AUTHORIZATION CURRENT_USER;
REVOKE ALL ON SCHEMA studio_directory FROM PUBLIC, anon, authenticated;
CREATE TABLE IF NOT EXISTS studio_directory.workspaces (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    owner_id uuid NOT NULL UNIQUE,
    legacy boolean NOT NULL DEFAULT false,
    schema_name text GENERATED ALWAYS AS (
        CASE WHEN legacy THEN 'user_' || replace(owner_id::text, '-', '')
             ELSE 'ws_' || id::text END
    ) STORED UNIQUE,
    organization_name text NOT NULL DEFAULT ''
);
ALTER TABLE studio_directory.workspaces ENABLE ROW LEVEL SECURITY;
CREATE OR REPLACE FUNCTION studio_directory.sync_workspace_name() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    UPDATE studio_directory.workspaces SET organization_name = NEW.name
    WHERE schema_name = TG_TABLE_SCHEMA AND organization_name IS DISTINCT FROM NEW.name;
    RETURN NEW;
END;
$$;
"""

BACKFILL = """
INSERT INTO studio_directory.workspaces (owner_id, legacy)
SELECT substring(nspname FROM 6)::uuid, true FROM pg_catalog.pg_namespace n
WHERE nspname ~ '^user_[0-9a-f]{32}$' AND nspowner = current_user::regrole
  AND NOT EXISTS (
      SELECT 1 FROM studio_directory.workspaces w WHERE w.schema_name = n.nspname
  )
ON CONFLICT (owner_id) DO NOTHING RETURNING schema_name
"""


def bind_workspace_name(conn: Connection[Any], schema: str) -> None:
    """Keep the directory label in sync even for writes from a pre-directory web process."""
    if not conn.execute(
        "SELECT 1 WHERE to_regprocedure('studio_directory.sync_workspace_name()') IS NOT NULL "
        "AND NOT EXISTS (SELECT FROM pg_catalog.pg_trigger WHERE tgrelid=to_regclass(%s) "
        "AND tgname='studio_workspace_name')",
        (schema + ".organization",),
    ).fetchone():
        return
    conn.execute(
        sql.SQL(
            "CREATE TRIGGER studio_workspace_name AFTER INSERT OR UPDATE OF name ON {}.organization "
            "FOR EACH ROW EXECUTE FUNCTION studio_directory.sync_workspace_name()"
        ).format(sql.Identifier(schema))
    )


def _copy_name(conn: Connection[Any], schema: str) -> None:
    if conn.execute(
        "SELECT to_regclass(%s) IS NOT NULL", (schema + ".organization",)
    ).fetchone() == (True,):
        bind_workspace_name(conn, schema)
        conn.execute(
            sql.SQL(
                "UPDATE studio_directory.workspaces SET organization_name=o.name "
                "FROM {}.organization o WHERE schema_name=%s AND o.id=1"
            ).format(sql.Identifier(schema)),
            (schema,),
        )


def _backfill(conn: Connection[Any]) -> int:
    conn.execute(CREATE_DIRECTORY)
    names = conn.execute(BACKFILL).fetchall()
    for (schema,) in names:
        _copy_name(conn, schema)
    return len(names)


def backfill_workspace_directory(url: str) -> int:
    """Register existing schemas even if their owners have never set up an account profile."""
    with connect(url, connect_timeout=15) as conn:
        conn.execute(LOCK)
        return _backfill(conn)


def workspace_schema(url: str, owner: UUID) -> str:
    """Resolve the owner once per tenant app. Reserve a new name and schema in one transaction."""
    with connect(url, connect_timeout=15) as conn:
        conn.execute(LOCK)
        if conn.execute("SELECT to_regclass('studio_directory.workspaces')").fetchone() == (None,):
            _backfill(conn)
        mapped = conn.execute(
            "SELECT w.schema_name, n.nspowner=current_user::regrole "
            "FROM studio_directory.workspaces w LEFT JOIN pg_catalog.pg_namespace n "
            "ON n.nspname=w.schema_name WHERE w.owner_id=%s",
            (owner,),
        ).fetchone()
        if mapped:
            if not mapped[1]:
                raise ValueError(
                    "Registered workspace schema is missing or owned by another database role"
                )
            return str(mapped[0])

        # An older server may have initialized this owner since the startup backfill.
        legacy = "user_" + owner.hex
        found = conn.execute(
            "SELECT nspowner = current_user::regrole FROM pg_catalog.pg_namespace WHERE nspname=%s",
            (legacy,),
        ).fetchone()
        if found:
            if not found[0]:
                raise ValueError("Legacy workspace is owned by another database role")
            conn.execute(
                "INSERT INTO studio_directory.workspaces (owner_id, legacy) VALUES (%s, true)",
                (owner,),
            )
            _copy_name(conn, legacy)
            return legacy

        while True:
            try:
                with conn.transaction():
                    result = conn.execute(
                        "INSERT INTO studio_directory.workspaces (owner_id) VALUES (%s) RETURNING schema_name",
                        (owner,),
                    ).fetchone()
                    assert result is not None  # noqa: S101 - INSERT RETURNING yields one row
                    schema = str(result[0])
                    name = sql.Identifier(schema)
                    conn.execute(
                        sql.SQL("CREATE SCHEMA {} AUTHORIZATION CURRENT_USER").format(name)
                    )
                    conn.execute(
                        sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC, anon, authenticated").format(
                            name
                        )
                    )
                    return schema
            except DuplicateSchema:
                # An unrelated schema already uses this number. The identity sequence advances
                # even when this savepoint rolls back, so the next name is fresh.
                continue


if __name__ == "__main__":
    from design_agent.config import Settings

    database = Settings().database_url
    if database is None:
        raise SystemExit("Set DATABASE_URL to the workspace application role's connection URL")
    count = backfill_workspace_directory(database.get_secret_value())
    print(f"Registered {count} existing workspace(s).")
