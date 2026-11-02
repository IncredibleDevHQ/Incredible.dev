"""Where threads, checkpoints and the store live outside MDA.

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
async def open_persistence(settings: Settings, workspace: Path) -> AsyncIterator[tuple[Any, Any]]:
    """`(checkpointer, store)`, set up and closed with the context."""
    if settings.database_url is not None:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.postgres.aio import AsyncPostgresStore

        url = settings.database_url.get_secret_value()
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
