"""Integrations: the presets in `config/mcp.example.toml` and per-person connections (`owner`)."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pytest

from design_agent.config import Settings
from design_agent.tools import mcp
from design_agent.tools.mcp import (
    McpConfigError,
    McpServer,
    declared_servers,
    mda_declaration,
    servers_for_runtime,
)

ROOT = Path(__file__).resolve().parents[2]
SETTING = re.compile(r"# (\[servers\.[a-z0-9]+\]|[a-z_]+ = .*)$")


def presets() -> str:
    """The hosted-integration entries of the example file, uncommented."""
    text = (ROOT / "config" / "mcp.example.toml").read_text(encoding="utf-8")
    section = text.split("--- Hosted integrations", 1)[1].split("--- Your own servers", 1)[0]
    return "\n".join(m.group(1) for line in section.splitlines() if (m := SETTING.match(line)))


def write_config(root: Path, text: str) -> None:
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "mcp.toml").write_text(text, encoding="utf-8")


def settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_every_preset_is_a_valid_per_person_server(tmp_path: Path) -> None:
    write_config(tmp_path, presets())
    servers = declared_servers(tmp_path)
    assert [s.name for s in servers] == [
        "notion",
        "linear",
        "github",
        "figma",
        "atlassian",
        "asana",
        "canva",
        "webflow",
        "box",
    ]
    assert all(s.owner == "user" and s.connection == s.name for s in servers)
    assert all(s.url.startswith("https://") and s.transport == "http" for s in servers)


def test_owner_is_agent_or_user_and_a_person_needs_a_connection(tmp_path: Path) -> None:
    write_config(tmp_path, '[servers.docs]\nurl = "https://docs.example.com/mcp"\n')
    assert declared_servers(tmp_path)[0].owner == "agent"
    write_config(tmp_path, '[servers.docs]\nurl = "https://d.example/mcp"\nowner = "team"\n')
    with pytest.raises(McpConfigError, match="owner must be agent or user"):
        declared_servers(tmp_path)
    write_config(tmp_path, '[servers.docs]\nurl = "https://d.example/mcp"\nowner = "user"\n')
    with pytest.raises(McpConfigError, match="needs a connection"):
        declared_servers(tmp_path)


def test_mda_resolves_each_connection_for_its_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    declared: dict[str, Any] = {}
    monkeypatch.setattr(
        "managed_deepagents.define_mcp", lambda **config: declared.update(config) or "declared"
    )
    servers = [
        McpServer("notion", "https://mcp.notion.com/mcp", connection="notion", owner="user"),
        McpServer("docs", "https://docs.example.com/mcp", connection="docs"),
    ]
    assert mda_declaration(servers) == "declared"
    owners = {name: entry["connection"].owner for name, entry in declared["servers"].items()}
    assert owners == {"notion": {"type": "user"}, "docs": {"type": "agent"}}


def test_per_person_servers_run_only_on_mda(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    write_config(
        tmp_path,
        '[servers.notion]\nurl = "https://mcp.notion.com/mcp"\nconnection = "notion"\n'
        'owner = "user"\n\n[servers.docs]\nurl = "https://docs.example.com/mcp"\n',
    )
    assert [s.name for s in servers_for_runtime(tmp_path, settings(), "mda")] == ["notion", "docs"]
    with caplog.at_level(logging.WARNING, logger=mcp.__name__):
        local = servers_for_runtime(tmp_path, settings(), "local")
    assert [s.name for s in local] == ["docs"]
    assert "notion left out: per-person connections need Managed Deep Agents" in caplog.text


def test_langsmith_managed_tools_take_the_workspace_key_off_mda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(
        tmp_path,
        '[servers.parallel]\nurl = "https://api.smith.langchain.com/v1/managed-tools/servers/'
        'parallel/mcp"\n',
    )
    keyed = Settings(_env_file=None, langsmith_api_key="lsv2-test")  # type: ignore[call-arg]
    (local,) = servers_for_runtime(tmp_path, keyed, "local")
    assert local.headers({}) == {"x-api-key": "lsv2-test"}
    assert "lsv2-test" not in repr(local)

    (deployed,) = servers_for_runtime(tmp_path, keyed, "mda")
    assert deployed.api_key is None
    declared: dict[str, Any] = {}
    monkeypatch.setattr(
        "managed_deepagents.define_mcp", lambda **config: declared.update(config) or "declared"
    )
    assert mda_declaration([deployed]) == "declared" and "parallel" in declared["servers"]
