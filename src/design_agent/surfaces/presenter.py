"""Where a thread's people are: a channel UI shows each turn's work and carries their follow-ups in.
The assembly asks the runtime's presenter for the middleware that does this; with none, runs are headless."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from langchain.agents.middleware import AgentMiddleware

    from design_agent.config import Settings
    from design_agent.middleware.background import BackgroundServices


class Presenter(Protocol):
    def lead_middleware(
        self, *, settings: Settings, services: BackgroundServices | None
    ) -> Sequence[AgentMiddleware[Any, Any, Any]]: ...

    def helper_middleware(
        self, *, settings: Settings
    ) -> Sequence[AgentMiddleware[Any, Any, Any]]: ...
