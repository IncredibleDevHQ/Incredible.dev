"""The heartbeat ledger: what survives a restart of the process that runs the helpers.

Each helper keeps a record in the deployment store, refreshed every `HEARTBEAT_SECONDS` while this
process holds it. The record also carries how the helper ended (status, report, error) and stays until
the lead has been told, so a restart between a helper finishing and the lead being woken loses
nothing. A record whose heartbeat is older than `STALE_SECONDS` belongs to a process that is gone:
- still `running`: the helper died with the process; `sweep` reports it as interrupted;
- ended but not delivered: the report is in the record; `sweep` delivers it as a normal finish.

Check-ins the lead scheduled (`harness.wakeups`) live here too, so one a restart swallowed fires
late rather than never.

This is the lease, heartbeat and sweeper pattern durable-execution engines use. Deep Agents has
no equivalent for in-process background subagents, which a restart loses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from design_agent.harness.tasks import REGISTRY, TaskRecord

_LOGGER = logging.getLogger(__name__)

#: The store namespace each helper keeps its heartbeat record in.
LEDGER = ("background_tasks",)
#: The store namespace scheduled check-ins live in.
WAKEUP_LEDGER = ("background_wakeups",)
HEARTBEAT_SECONDS = 60.0
#: A record whose heartbeat is older than this belongs to a process that is gone.
STALE_SECONDS = 180.0
#: Reports kept in a record are cut to this many characters.
REPORT_CHARS = 20_000

_HEARTBEAT: asyncio.Task[None] | None = None


def jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str)) if value is not None else None


def record_value(record: TaskRecord) -> dict[str, Any]:
    return {
        "thread_id": record.thread_id,
        "effort": record.effort,
        "label": record.label,
        "wave": record.wave,
        "subagent_type": record.subagent_type,
        "started_at": record.started_at,
        "alive_at": time.time(),
        "status": record.status,
        "finished_at": record.finished_at,
        "report": record.report[:REPORT_CHARS],
        "error": record.error,
        **jsonable(record.meta or {}),
    }


async def beat(record: TaskRecord) -> None:
    """Write or refresh the helper's record."""
    if record.store is None:
        return
    try:
        await record.store.aput(LEDGER, record.id, record_value(record))
    except Exception as error:  # noqa: BLE001 - a missed beat is retried next minute
        _LOGGER.warning("[harness] heartbeat for %s failed: %s", record.id, type(error).__name__)


async def forget(record: TaskRecord) -> None:
    """Drop the record: the lead has been told how the helper ended."""
    record.delivered = True
    if record.store is None:
        return
    try:
        await record.store.adelete(LEDGER, record.id)
    except Exception as error:  # noqa: BLE001 - a leftover is swept and delivered once more, late
        _LOGGER.warning("[harness] forgetting %s failed: %s", record.id, type(error).__name__)


def ensure_heartbeat() -> None:
    """One loop per process refreshes every open record each `HEARTBEAT_SECONDS`."""
    global _HEARTBEAT  # one loop per process, by design
    if _HEARTBEAT is None or _HEARTBEAT.done():
        _HEARTBEAT = asyncio.get_running_loop().create_task(_heartbeat(), name="harness heartbeat")


def _open(record: TaskRecord) -> bool:
    return not record.delivered and record.status != "cancelled"


async def _heartbeat() -> None:
    while any(_open(r) for r in REGISTRY.values()):
        await asyncio.sleep(HEARTBEAT_SECONDS)
        for record in [r for r in REGISTRY.values() if _open(r)]:
            await beat(record)


def stop_heartbeat() -> None:
    if _HEARTBEAT is not None and not _HEARTBEAT.done():
        _HEARTBEAT.cancel()


async def save_wakeup(store: Any, key: str, value: Mapping[str, Any]) -> None:
    if store is None:
        return
    try:
        await store.aput(WAKEUP_LEDGER, key, jsonable(dict(value)))
    except Exception as error:  # noqa: BLE001 - the timer still fires; only a restart would lose it
        _LOGGER.warning("[harness] saving %s failed: %s", key, type(error).__name__)


async def drop_wakeup(store: Any, key: str) -> None:
    if store is None:
        return
    try:
        await store.adelete(WAKEUP_LEDGER, key)
    except Exception as error:  # noqa: BLE001 - a leftover fires once more from the sweep
        _LOGGER.warning("[harness] dropping %s failed: %s", key, type(error).__name__)


OnFound = Callable[[str, dict[str, Any]], Awaitable[None]]


async def sweep(
    store: Any,
    *,
    on_task: OnFound,
    on_wakeup: OnFound,
    held_wakeups: Callable[[str], bool] = lambda _key: False,
    now: float | None = None,
) -> int:
    """Hand every record no live process holds to `on_task` / `on_wakeup`, and delete it.

    A task record is abandoned when this process doesn't hold it and its heartbeat is stale; a
    check-in when no process holds its timer and it is past due. Returns how many were found.
    """
    now = time.time() if now is None else now
    found = 0
    for item in await store.asearch(LEDGER, limit=200):
        value = dict(item.value or {})
        held = item.key in REGISTRY and not REGISTRY[item.key].delivered
        if held or now - float(value.get("alive_at") or 0) < STALE_SECONDS:
            continue
        await store.adelete(LEDGER, item.key)
        await on_task(item.key, value)
        found += 1
    for item in await store.asearch(WAKEUP_LEDGER, limit=200):
        value = dict(item.value or {})
        if held_wakeups(item.key) or float(value.get("due_at") or 0) > now - 60:
            continue
        await store.adelete(WAKEUP_LEDGER, item.key)
        await on_wakeup(item.key, value)
        found += 1
    return found
