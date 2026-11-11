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

        url = settings.database_url.get_secret_value()
        if schema:
            from psycopg import AsyncConnection, sql
            from psycopg.rows import dict_row

            from design_agent.surfaces.web.postgres import validate_schema

            validate_schema(schema)
            async with (
                await AsyncConnection.connect(
                    url,
                    autocommit=True,
                    prepare_threshold=None,
                    row_factory=dict_row,
                    connect_timeout=15,
                ) as checkpoints,
                await AsyncConnection.connect(
                    url,
                    autocommit=True,
                    prepare_threshold=None,
                    row_factory=dict_row,
                    connect_timeout=15,
                ) as memory,
            ):
                for connection in (checkpoints, memory):
                    await connection.execute(
                        sql.SQL("SET search_path TO {}").format(sql.Identifier(schema))
                    )
                checkpointer = AsyncPostgresSaver(checkpoints)
                store = AsyncPostgresStore(memory)
                await checkpointer.setup()
                await store.setup()
                # These internal tables must never be reachable through the public Data API.
                tables = await checkpoints.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname = %s", (schema,)
                )
                for row in await tables.fetchall():
                    await checkpoints.execute(
                        sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(
                            sql.Identifier(row["tablename"])
                        )
                    )
                yield checkpointer, store
            return
        async with (
            AsyncPostgresSaver.from_conn_string(url) as checkpointer,
            AsyncPostgresStore.from_conn_string(url) as store,
        ):
            await checkpointer.setup()
            await store.setup()
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
