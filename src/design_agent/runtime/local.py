"""The local runtime: the CLI, the offline demo and the test suite compile the shared assembly
with `create_deep_agent`, an in-memory checkpointer and a local sandbox binding."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from design_agent.assembly import AgentComponents, build_agent_components
from design_agent.config import Settings
from design_agent.harness import notices
from design_agent.harness.tasks import REGISTRY
from design_agent.middleware.background import BackgroundServices
from design_agent.middleware.watch_tools import WATCHES
from design_agent.runtime.profiles import RuntimeProfile
from design_agent.runtime.sandbox import SandboxBinding, select_binding
from design_agent.runtime.waker.local import InProcessWaker
from design_agent.tools.delivery import DeliveryAdapter, LocalOutputAdapter
from design_agent.tools.mcp import McpServer

Replies = Callable[[str, str], None]

GRAPH_NAME = "design-agent"
#: deepagents' own ceiling, as on MDA; `StepBudgetMiddleware` wraps a turn up just before it.
DEFAULT_RECURSION_LIMIT = 9_999


def local_profile(
    project_root: Path,
    binding: SandboxBinding,
    out_dir: Path,
    services: BackgroundServices | None = None,
    *,
    slack: Any = None,
    surface: str = "cli",
    delivery: DeliveryAdapter | None = None,
) -> RuntimeProfile:
    return RuntimeProfile(
        name="local",
        slack=slack,
        surface=surface,
        project_root=project_root,
        backend_for=binding.backend_for,
        staging_for=binding.staging_for,
        delivery=delivery or LocalOutputAdapter(out_dir),
        services=services,
    )


def compile_graph(
    components: AgentComponents,
    binding: SandboxBinding,
    *,
    checkpointer: Any | None = None,
    store: Any | None = None,
) -> Any:
    return create_deep_agent(
        model=components.model,
        tools=list(components.tools),
        system_prompt=components.system_prompt,
        middleware=list(components.middleware),
        subagents=list(components.subagents) or None,
        skills=list(components.skills),
        backend=binding.graph_backend,
        interrupt_on=dict(components.interrupt_on) or None,
        checkpointer=checkpointer if checkpointer is not None else InMemorySaver(),
        store=store if store is not None else InMemoryStore(),
        name=GRAPH_NAME,
    )


@dataclass
class LocalRuntime:
    settings: Settings
    project_root: Path
    binding: SandboxBinding
    components: AgentComponents
    graph: Any
    out_dir: Path
    waker: InProcessWaker
    services: BackgroundServices
    replies: Replies
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def _config(self, thread_id: str, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return {
            "configurable": {**(extra or {}), "thread_id": thread_id},
            "recursion_limit": DEFAULT_RECURSION_LIMIT,
        }

    def _lock(self, thread_id: str) -> asyncio.Lock:
        return self._locks.setdefault(thread_id, asyncio.Lock())

    async def ask(
        self, message: str, *, thread_id: str, configurable: Mapping[str, Any] | None = None
    ) -> list[BaseMessage]:
        """Run one turn and return the messages it added. `configurable` carries what a surface
        knows about the request (the Slack adapter's event)."""
        async with self._lock(thread_id):
            return await self._turn(thread_id, message, configurable)

    async def _turn(
        self, thread_id: str, message: str, configurable: Mapping[str, Any] | None = None
    ) -> list[BaseMessage]:
        config = self._config(thread_id, configurable)
        before = await self._message_count(config)
        result = await self.graph.ainvoke(
            {"messages": [HumanMessage(content=message)]}, config=config
        )
        messages: list[BaseMessage] = list(result.get("messages", []))
        return messages[before:]

    async def wake_turn(self, thread_id: str, message: str, started: asyncio.Event) -> None:
        """A turn the waker started: after the person's own turn on the thread, never during it."""
        async with self._lock(thread_id):
            started.set()
            added = await self._turn(thread_id, message)
        text = final_text(added)
        if text and notices.should_post(text):
            self.replies(thread_id, text)

    async def attach(self, thread_id: str, files: Sequence[tuple[str, bytes]]) -> list[str]:
        """Put files in the thread's `/workspace/attachments/`, where a channel puts what people
        drop in a thread. Returns their sandbox paths."""
        from langchain_core.runnables.config import var_child_runnable_config

        placed = [(f"/workspace/attachments/{Path(name).name}", content) for name, content in files]
        token = var_child_runnable_config.set({"configurable": {"thread_id": thread_id}})
        try:
            await asyncio.to_thread(self.binding.sandbox.upload_files, placed)
        finally:
            var_child_runnable_config.reset(token)
        return [path for path, _ in placed]

    def busy(self) -> bool:
        """Whether a helper, watch, check-in or woken turn is outstanding on this runtime's threads."""
        threads = list(self._locks)
        return (
            any(r.status == "running" and r.thread_id in threads for r in REGISTRY.values())
            or any(w.status == "watching" for thread in threads for w in WATCHES.list(thread))
            or self.waker.pending() > 0
            or any(
                b.delivery is not None and not b.delivery.done()
                for b in self.services.inbox.boxes.values()
            )
        )

    async def settle(self, *, timeout_seconds: float = 6 * 3600, poll_seconds: float = 2.0) -> bool:
        """Wait until nothing is outstanding (`busy`), so the CLI stays open while a job runs.
        Returns False on timeout."""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not self.busy():
                return True
            await asyncio.sleep(poll_seconds)
        return False

    async def stream(self, message: str, *, thread_id: str) -> AsyncIterator[dict[str, Any]]:
        async with self._lock(thread_id):
            async for chunk in self.graph.astream(
                {"messages": [HumanMessage(content=message)]},
                config=self._config(thread_id),
                stream_mode="updates",
            ):
                yield chunk

    async def _message_count(self, config: Mapping[str, Any]) -> int:
        state = await self.graph.aget_state(config)
        return len((state.values or {}).get("messages", [])) if state else 0


def final_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.content and not message.tool_calls:
            return message.text if hasattr(message, "text") else str(message.content)
    return ""


def build_local_runtime(
    settings: Settings,
    project_root: Path,
    *,
    model: BaseChatModel | None = None,
    role_models: Mapping[str, BaseChatModel] | None = None,
    binding: SandboxBinding | None = None,
    out_dir: Path | None = None,
    replies: Replies | None = None,
    checkpointer: Any | None = None,
    store: Any | None = None,
    mcp_servers: Sequence[McpServer] = (),
    mcp_tools: Sequence[BaseTool] = (),
    slack: Any = None,
    surface: str = "cli",
    delivery: DeliveryAdapter | None = None,
) -> LocalRuntime:
    """Select the sandbox, assemble the components, compile the graph and wire the waker.

    MCP tools are loaded by the caller (`tools.mcp.load_mcp_tools`, async) and passed in."""
    chosen = binding if binding is not None else select_binding(settings, project_root)
    workspace_root = (
        settings.workspace_root
        if settings.workspace_root.is_absolute()
        else project_root / settings.workspace_root
    )
    out = out_dir if out_dir is not None else workspace_root / "out"
    holder: list[LocalRuntime] = []

    async def run_turn(thread_id: str, message: str, started: asyncio.Event) -> None:
        await holder[0].wake_turn(thread_id, message, started)

    store = store if store is not None else InMemoryStore()
    waker = InProcessWaker(run_turn, store=store)
    services = BackgroundServices(waker=waker, capture_target=waker.capture)
    profile = local_profile(
        project_root, chosen, out, services, slack=slack, surface=surface, delivery=delivery
    )
    components = build_agent_components(
        settings=settings,
        runtime=profile,
        model=model,
        role_models=role_models,
        mcp_servers=mcp_servers,
        mcp_tools=mcp_tools,
    )
    runtime = LocalRuntime(
        settings=settings,
        project_root=project_root,
        binding=chosen,
        components=components,
        graph=compile_graph(components, chosen, checkpointer=checkpointer, store=store),
        out_dir=out,
        waker=waker,
        services=services,
        replies=replies or (lambda _thread, text: print(text)),
    )
    holder.append(runtime)
    return runtime
