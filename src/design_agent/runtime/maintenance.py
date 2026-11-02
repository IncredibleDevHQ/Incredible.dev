"""What a long-running self-hosted process does in the background: stop idle sandbox containers
every minute (their volumes stay) and sweep what a restart killed every 15 minutes, as MDA's
housekeeping schedule does there. Started next to the API or the Slack adapter."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from design_agent.runtime.local import LocalRuntime

_LOGGER = logging.getLogger(__name__)

SWEEP_SECONDS = 15 * 60
REAP_SECONDS = 60


async def start(runtime: LocalRuntime, store: Any) -> None:
    """The first sweep and the check-ins a previous process kept, before serving."""
    await runtime.services.sweep(store)
    await runtime.waker.restore()


async def run(runtime: LocalRuntime, store: Any) -> None:
    elapsed = 0
    while True:
        await asyncio.sleep(REAP_SECONDS)
        elapsed += REAP_SECONDS
        runner = runtime.binding.runner
        if runner is not None:
            try:
                await asyncio.to_thread(runner.reap_idle)
            except Exception as error:  # noqa: BLE001 - the next pass tries again
                _LOGGER.warning("[maintenance] reaping sandboxes failed: %s", type(error).__name__)
        if elapsed >= SWEEP_SECONDS:
            elapsed = 0
            try:
                await runtime.services.sweep(store)
            except Exception as error:  # noqa: BLE001 - the next pass tries again
                _LOGGER.warning("[maintenance] the sweep failed: %s", type(error).__name__)
