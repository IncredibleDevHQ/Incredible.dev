"""Every run names the template it came from, renamed or not, unless the operator turns it off."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage
from langsmith import RunTree

from design_agent.assembly import build_agent_components
from design_agent.config import Settings
from design_agent.middleware import tracing
from design_agent.middleware.tracing import RunTagsMiddleware, template_marker
from design_agent.runtime.local import local_profile
from design_agent.testing.fakes import folder_binding
from design_agent.testing.scripted_model import ScriptedChatModel

ROOT = Path(__file__).resolve().parents[2]


def assembled_run_tags(tmp_path: Path) -> RunTagsMiddleware:
    """The run-tags middleware the shared assembly builds from the operator's settings."""
    settings = Settings(_env_file=None, workspace_root=tmp_path / "ws")  # type: ignore[call-arg]
    profile = local_profile(ROOT, folder_binding(tmp_path / "sb", ROOT), tmp_path / "out")
    components = build_agent_components(
        settings=settings, runtime=profile, model=ScriptedChatModel(steps=[])
    )
    return next(m for m in components.middleware if isinstance(m, RunTagsMiddleware))


async def tags_on_a_run(middleware: RunTagsMiddleware, monkeypatch: pytest.MonkeyPatch) -> RunTree:
    run = RunTree(name="renamed-agent", run_type="chain", session_name="renamed-agent")
    monkeypatch.setattr(tracing, "trace_runs", lambda: (run, run))
    await middleware.abefore_agent({"messages": [HumanMessage("hi")]}, SimpleNamespace())
    return run


def test_the_marker_is_the_template_and_its_version_only() -> None:
    marker = template_marker()
    assert set(marker) == {"ls_template", "ls_template_version"}
    assert marker["ls_template"] == "langchain-ai/design-agent"
    assert marker["ls_template_version"]


async def test_every_run_carries_the_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DESIGN_AGENT_TEMPLATE_TELEMETRY", "1")
    run = await tags_on_a_run(assembled_run_tags(tmp_path), monkeypatch)
    assert "template:langchain-ai/design-agent" in run.tags
    assert run.metadata["ls_template"] == "langchain-ai/design-agent"


async def test_the_operator_can_turn_it_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DESIGN_AGENT_TEMPLATE_TELEMETRY", "0")
    run = await tags_on_a_run(assembled_run_tags(tmp_path), monkeypatch)
    assert not any(tag.startswith("template:") for tag in run.tags)
    assert "ls_template" not in run.metadata
