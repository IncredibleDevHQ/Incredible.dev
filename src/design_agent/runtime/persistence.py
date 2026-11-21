"""Where threads, checkpoints and the store live.

Self-hosted deployments set `DATABASE_URL` (Postgres): LangGraph's Postgres checkpointer and store
hold the conversations and everything the harness keeps in the store (helper ledger, transcripts,
check-ins, watches, pipeline memos, observations, delivery ledgers). Without it, the CLI and a
single-machine server use SQLite files in `workspace/state/`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from design_agent.config import Settings


@asynccontextmanager
async def open_persistence(
    settings: Settings, workspace: Path, *, schema: str | None = None
) -> AsyncIterator[tuple[Any, Any]]:
    """`(checkpointer, store)`, set up and closed with the context."""
    checkpointer: Any
    store: Any
    if settings.database_url is not None:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.postgres.aio import AsyncPostgresStore
        from psycopg import AsyncConnection, sql
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        from design_agent.surfaces.web.postgres import validate_schema

        if schema:
            validate_schema(schema)

        async def configure(connection: AsyncConnection[Any]) -> None:
            if schema:
                await connection.execute(
                    sql.SQL("SET search_path TO {}").format(sql.Identifier(schema))
                )

        async with AsyncConnectionPool[AsyncConnection[Any]](
            settings.database_url.get_secret_value(),
            min_size=0,
            max_size=2,
            open=False,
            configure=configure,
            check=AsyncConnectionPool.check_connection,
            timeout=15,
            kwargs={
                "autocommit": True,
                "prepare_threshold": None,
                "row_factory": dict_row,
                "connect_timeout": 15,
            },
        ) as pool:
            checkpointer = AsyncPostgresSaver(pool)
            store = AsyncPostgresStore(pool)
            await checkpointer.setup()
            await store.setup()
            if schema:
                async with pool.connection() as connection:
                    tables = await connection.execute(
                        "SELECT tablename FROM pg_tables WHERE schemaname = %s", (schema,)
                    )
                    for row in await tables.fetchall():
                        await connection.execute(
                            sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(
                                sql.Identifier(row["tablename"])
                            )
                        )
            yield checkpointer, store
        return
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.store.sqlite.aio import AsyncSqliteStore

    state = workspace / "state"
    state.mkdir(parents=True, exist_ok=True)
    async with (
        AsyncSqliteSaver.from_conn_string(str(state / "threads.sqlite")) as checkpointer,
        AsyncSqliteStore.from_conn_string(str(state / "store.sqlite")) as store,
    ):
        await store.setup()
        yield checkpointer, store


def workspace_of(settings: Settings, project_root: Path) -> Path:
    root = settings.workspace_root
    return root if root.is_absolute() else project_root / root
