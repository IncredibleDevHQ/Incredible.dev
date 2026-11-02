"""`design-agent ask` keeps threads across invocations and waits for the background work a request
started, printing each update (scripted model, folder sandbox)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from click.testing import CliRunner
from langchain_core.messages import AIMessage, BaseMessage

from design_agent import cli
from design_agent.harness import inbox as inbox_module
from design_agent.runtime import local
from design_agent.testing.fakes import folder_binding
from design_agent.testing.scripted_model import ScriptedChatModel, reply, tool_call

ROOT = Path(__file__).resolve().parents[2]


def test_ask_waits_for_helpers_and_continues_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(inbox_module, "COALESCE_SECONDS", 0.05)
    monkeypatch.setenv("DESIGN_AGENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-used")  # the scripted model needs none
    monkeypatch.setattr(cli, "_root", lambda: ROOT)

    def on_wake(messages: Sequence[BaseMessage]) -> AIMessage:
        return reply("The grabs are ready.")

    lead = ScriptedChatModel(
        steps=[
            lambda _m: tool_call(
                "start_task", {"description": "Grab frames.", "effort": "low", "label": "grabs"}
            ),
            lambda _m: reply("Grabbing frames; a minute or so."),
            on_wake,
            lambda m: reply(
                f"This thread has {sum(isinstance(x, AIMessage) for x in m)} replies so far."
            ),
        ]
    )
    helper = ScriptedChatModel(steps=[lambda _m: reply("Three frames in /workspace/projects/p/.")])
    real = local.build_local_runtime

    def build(settings, root, **kwargs):  # type: ignore[no-untyped-def]
        return real(
            settings,
            root,
            model=lead,
            role_models={"low": helper},
            binding=folder_binding(tmp_path / "sb", ROOT),
            **kwargs,
        )

    monkeypatch.setattr(local, "build_local_runtime", build)
    first = CliRunner().invoke(cli.main, ["ask", "Grab three frames.", "--thread", "t-cli"])
    assert first.exit_code == 0, first.output
    assert "Grabbing frames" in first.output and "The grabs are ready." in first.output
    assert "· start_task" in first.output

    second = CliRunner().invoke(cli.main, ["ask", "How many replies so far?", "--thread", "t-cli"])
    assert second.exit_code == 0, second.output
    assert "This thread has 3 replies so far." in second.output, (
        "the thread survived the first process"
    )


def test_ask_attaches_files_to_the_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DESIGN_AGENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-used")  # the scripted model needs none
    monkeypatch.setattr(cli, "_root", lambda: ROOT)
    seen: list[str] = []

    def lead(messages: Sequence[BaseMessage]) -> AIMessage:
        seen.extend(str(m.content) for m in messages)
        return reply("Got the layout.")

    real = local.build_local_runtime
    monkeypatch.setattr(
        local,
        "build_local_runtime",
        lambda s, r, **kw: real(
            s,
            r,
            model=ScriptedChatModel(steps=[lead]),
            binding=folder_binding(tmp_path / "sb", ROOT),
            **kw,
        ),
    )
    upload = tmp_path / "layout.png"
    upload.write_bytes(b"\\x89PNG fake")
    result = CliRunner().invoke(
        cli.main, ["ask", "Restyle this.", "--file", str(upload), "--thread", "t-file"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "sb/workspace/attachments/layout.png").read_bytes() == b"\\x89PNG fake"
    assert any("/workspace/attachments/layout.png" in s for s in seen)
