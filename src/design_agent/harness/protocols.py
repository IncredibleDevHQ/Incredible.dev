"""The interfaces between harness primitives and whatever hosts them.

Primitives depend on these small protocols, never on MDA, Slack or a sandbox client directly, so the
same primitive runs under Managed Deep Agents, the self-hosted runtime, a plain Deep Agents graph,
or a unit test with a fake.

- `HelperRunner`: start a helper (a subagent) in the background, or run one and await its report.
- `SandboxExec`: run a shell command where the work lives (the thread's sandbox backend).
- `Waker`: start a new lead turn on a thread now, or schedule one for later (SPEC §7.4). The MDA
  adapter uses one-time runtime schedules; the self-hosted adapter enqueues a run in-process.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class HelperResult:
    """How a helper ended: `status` is done, failed, cancelled or interrupted."""

    task_id: str
    status: str
    report: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "done"


@runtime_checkable
class HelperRunner(Protocol):
    async def start(
        self, brief: str, *, effort: str, label: str = "", wave: str | None = None
    ) -> str:
        """Start a helper in the background and return its task id at once."""
        ...

    async def run(
        self, brief: str, *, effort: str, label: str = "", wave: str | None = None
    ) -> HelperResult:
        """Start a helper and wait for it to end (for pipelines and other background code)."""
        ...


@dataclass(frozen=True)
class ExecResult:
    output: str
    exit_code: int | None = 0


@runtime_checkable
class SandboxExec(Protocol):
    async def execute(self, command: str, *, timeout: int | None = None) -> ExecResult:
        """Run `command` in the sandbox and return its combined output."""
        ...


@dataclass(frozen=True)
class WakeTarget:
    """Which lead to wake: its thread, plus opaque adapter data (`channel`) such as where a
    reply is posted. Harness code never reads `channel`; it is persisted with the work so a later
    process can wake the same lead."""

    thread_id: str
    channel: Mapping[str, Any] | str | None = None


@dataclass(frozen=True)
class WakeReceipt:
    """What a wake-up did. `delivered` is true only once the lead's run actually started;
    `run_id` names that run when the adapter knows it; `detail` says why it was not delivered."""

    delivered: bool
    run_id: str | None = None
    detail: str = ""


@runtime_checkable
class Waker(Protocol):
    async def wake(self, target: WakeTarget, message: str, *, dedupe_key: str) -> WakeReceipt:
        """Start a lead turn on `target` with `message`. A repeat with the same `dedupe_key`
        must not start a second run."""
        ...

    async def schedule(self, target: WakeTarget, at: datetime, message: str) -> str:
        """Start a lead turn on `target` at `at`; return an id for `cancel`."""
        ...

    async def cancel(self, schedule_id: str) -> None:
        """Drop a scheduled wake-up. Cancelling one that fired or is unknown is not an error."""
        ...
