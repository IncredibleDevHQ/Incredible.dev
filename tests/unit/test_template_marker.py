"""Every run names the template it came from, renamed or not, unless the operator turns it off."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage
from langsmith import RunTree

from design_agent.middleware import tracing
from design_agent.middleware.tracing import RunTagsMiddleware, template_marker

ROOT = Path(__file__).resolve().parents[2]


def mda_definition() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mda_agent", ROOT / "agent.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


async def test_the_mda_root_run_and_every_run_carry_the_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DESIGN_AGENT_TEMPLATE_TELEMETRY", "1")
    module = mda_definition()
    assert module.agent.config["metadata"] == template_marker()
    tags = next(m for m in module._components.middleware if isinstance(m, RunTagsMiddleware))
    run = await tags_on_a_run(tags, monkeypatch)
    assert "template:langchain-ai/design-agent" in run.tags
    assert run.metadata["ls_template"] == "langchain-ai/design-agent"


async def test_the_operator_can_turn_it_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DESIGN_AGENT_TEMPLATE_TELEMETRY", "0")
    module = mda_definition()
    assert module.agent.config.get("metadata") is None
    tags = next(m for m in module._components.middleware if isinstance(m, RunTagsMiddleware))
    run = await tags_on_a_run(tags, monkeypatch)
    assert not any(tag.startswith("template:") for tag in run.tags)
    assert "ls_template" not in run.metadata
