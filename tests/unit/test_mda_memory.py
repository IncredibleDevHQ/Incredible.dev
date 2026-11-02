"""MDA memory (`memory.py`): a team layer for every caller, a personal layer anywhere in Slack."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from managed_deepagents import ManagedChannelContext

ROOT = Path(__file__).resolve().parents[2]


def declaration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mda_memory", ROOT / "memory.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def channel(provider: str) -> ManagedChannelContext:
    return ManagedChannelContext.model_construct(channel={"provider": provider})  # type: ignore[typeddict-item]


def test_both_layers_are_mounted_and_the_team_layer_is_open_to_every_caller() -> None:
    layers = declaration().memory.config["scope"]
    assert [layer["type"] for layer in layers] == ["agent", "user"]
    assert "allow" not in layers[0]


def test_personal_memory_follows_the_person_anywhere_in_slack_and_nowhere_else() -> None:
    allow = declaration().memory.config["scope"][1]["allow"]
    assert allow(channel("slack")) is True
    assert allow(channel("teams")) is False
    assert allow({"channel": {"provider": "slack"}}) is False
    assert allow(None) is False
