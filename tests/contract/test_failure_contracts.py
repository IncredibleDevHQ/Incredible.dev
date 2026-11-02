"""Real graph, scripted models: errors never end a run silently (SPEC §7.10).

A stalled model call ends the lead's turn with a line; a transient one is retried; a turn near the
graph's step limit wraps up with a partial answer; a failed delegated task comes back as a tool
error; an MCP server that fails to load, or a call that raises, leaves the rest working.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import BaseTool, tool

from design_agent.config import Settings
from design_agent.harness.tasks import REGISTRY
from design_agent.middleware import model_retry
from design_agent.runtime import local
from design_agent.runtime.local import build_local_runtime
from design_agent.testing.fakes import folder_binding
from design_agent.testing.scripted_model import (
    RespondingChatModel,
    ScriptedChatModel,
    reply,
    tool_call,
)
from design_agent.tools.mcp import McpServer, load_mcp_tools
from tests.contract.test_background_contracts import latest_human

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def clean() -> Iterator[None]:
    yield
    REGISTRY.clear()


def runtime(tmp_path: Path, lead: ScriptedChatModel, **kwargs: object) -> local.LocalRuntime:
    settings = Settings(_env_file=None, workspace_root=tmp_path / "ws")  # type: ignore[call-arg]
    return build_local_runtime(
        settings,
        ROOT,
        model=lead,
        binding=folder_binding(tmp_path / "sb", ROOT),
        replies=lambda *_: None,
        **kwargs,  # type: ignore[arg-type]
    )


def raises(error: BaseException):  # type: ignore[no-untyped-def]
    def step(_m: Sequence[BaseMessage]) -> AIMessage:
        raise error

    return step


async def test_a_stalled_model_call_ends_the_turn_with_a_line(tmp_path: Path) -> None:
    lead = ScriptedChatModel(steps=[raises(httpx.ReadTimeout("stalled"))])
    added = await runtime(tmp_path, lead).ask("Make a card.", thread_id="f1")
    assert lead.call_count == 1, "a stall is not replayed"
    assert "stalled mid-reply" in str(added[-1].content)
    assert added[-1].response_metadata.get("partial") == model_retry.STALL_STOP_REASON


async def test_a_transient_failure_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        model_retry.TransientModelRetryMiddleware.__init__,
        "__kwdefaults__",
        {"max_retries": 5, "base_delay_seconds": 0.01, "max_delay_seconds": 0.02},
    )
    lead = ScriptedChatModel(
        steps=[raises(httpx.ConnectError("blip")), lambda _m: reply("Here it is.")]
    )
    added = await runtime(tmp_path, lead).ask("Make a card.", thread_id="f2")
    assert added[-1].content == "Here it is."


async def test_a_turn_at_the_step_limit_wraps_up_with_a_partial_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local, "DEFAULT_RECURSION_LIMIT", 40)

    def step(messages: Sequence[BaseMessage]) -> AIMessage:
        if "step limit" in str(messages[-1].content):
            return reply(
                "Finished the brief and two frames in /workspace/projects/p; the third is next."
            )
        return tool_call("ls", {"path": "/workspace"})

    lead = ScriptedChatModel(steps=[step] * 40)
    added = await runtime(tmp_path, lead).ask("Build all frames.", thread_id="f3")
    final = added[-1]
    assert isinstance(final, AIMessage) and final.response_metadata.get("partial") == "step_budget"
    assert "the third is next" in final.text and "continue" in final.text


async def test_a_failed_delegated_task_comes_back_as_a_tool_error(tmp_path: Path) -> None:
    def step(messages: Sequence[BaseMessage]) -> AIMessage:
        if (
            latest_human(messages) == "Look something up."
        ):  # general-purpose runs on the lead's model
            raise RuntimeError("helper bug")
        if isinstance(messages[-1], ToolMessage):
            return reply("did it myself" if messages[-1].status == "error" else "?")
        return tool_call(
            "task", {"description": "Look something up.", "subagent_type": "general-purpose"}
        )

    rt = runtime(tmp_path, RespondingChatModel(respond=step))
    added = await rt.ask("Find the brand's launch date.", thread_id="f4")
    errors = [m for m in added if isinstance(m, ToolMessage) and m.name == "task"]
    assert errors and "stopped before finishing (RuntimeError)" in str(errors[0].content)
    assert "helper bug" not in str(errors[0].content), "only the class reaches the model"
    assert added[-1].content == "did it myself"


@tool
def docs_search(query: str) -> str:
    """Search the docs."""
    raise ConnectionError("server went away")


async def test_mcp_servers_fail_alone_at_load_and_at_call(tmp_path: Path) -> None:
    good, bad = (
        McpServer("docs", "https://docs.example/mcp"),
        McpServer("broken", "https://broken.example/mcp"),
    )

    async def loader(server: McpServer, _env: object) -> list[BaseTool]:
        if server.name == "broken":
            raise OSError("connection refused")
        return [docs_search]

    loaded = await load_mcp_tools([good, bad], loader=loader)
    assert [t.name for t in loaded.tools] == ["docs_search"] and loaded.failed == {
        "broken": "OSError"
    }

    lead = ScriptedChatModel(
        steps=[
            lambda _m: tool_call("docs_search", {"query": "fonts"}),
            lambda m: reply(str(m[-1].content)),
        ]
    )
    added = await runtime(tmp_path, lead, mcp_servers=[good], mcp_tools=loaded.tools).ask(
        "Search the docs.", thread_id="f5"
    )
    assert "The docs service failed on this call (ConnectionError)" in str(added[-1].content)
    assert "server went away" not in str(added[-1].content)


async def test_two_parallel_delegations_hand_back_without_a_state_conflict(tmp_path: Path) -> None:
    from design_agent.testing.scripted_model import tool_calls

    def step(messages: Sequence[BaseMessage]) -> AIMessage:
        asked = latest_human(messages)
        if asked in ("Count the frames.", "Name the fonts."):  # each delegated run
            return reply(f"done: {asked}")
        if isinstance(messages[-1], ToolMessage):
            results = [m for m in messages if isinstance(m, ToolMessage) and m.name == "task"]
            return reply(f"{len(results)} answers")
        return tool_calls(
            ("task", {"description": "Count the frames.", "subagent_type": "general-purpose"}),
            ("task", {"description": "Name the fonts.", "subagent_type": "general-purpose"}),
        )

    added = await runtime(tmp_path, RespondingChatModel(respond=step)).ask(
        "Two lookups.", thread_id="f6"
    )
    assert added[-1].content == "2 answers"


async def test_the_housekeeping_run_never_calls_the_model_or_stages_the_sandbox(
    tmp_path: Path,
) -> None:
    model = ScriptedChatModel(steps=[])
    added = await runtime(tmp_path, model).ask("<housekeeping>", thread_id="hk")
    assert model.call_count == 0
    assert str(added[-1].content).startswith("Housekeeping:")
    assert not (tmp_path / "sb" / "workspace" / ".design-agent-ready").exists()
