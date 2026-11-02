"""Integrations: the presets in `config/mcp.example.toml`, and credentials from the host."""

from __future__ import annotations

import re
from pathlib import Path

from design_agent.config import Settings
from design_agent.tools.mcp import McpServer, declared_servers, servers_for_runtime

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


def test_every_preset_is_a_valid_server_that_signs_in_from_the_host(tmp_path: Path) -> None:
    write_config(tmp_path, presets())
    servers = declared_servers(tmp_path)
    assert [s.name for s in servers] == ["github"]
    assert all(s.url.startswith("https://") and s.transport == "http" for s in servers)
    assert all(s.headers_env for s in servers), "credentials come from the host environment"


def test_headers_come_from_the_host_environment_or_not_at_all() -> None:
    server = McpServer(
        "docs", "https://docs.example.com/mcp", headers_env={"Authorization": "DOCS_AUTH"}
    )
    assert server.headers({"DOCS_AUTH": "Bearer t"}) == {"Authorization": "Bearer t"}
    assert server.headers({}) is None


def test_every_runtime_serves_the_declared_servers(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        '[servers.docs]\nurl = "https://docs.example.com/mcp"\n\n'
        '[servers.notes]\ntransport = "stdio"\ncommand = ["notes-app", "mcp"]\n',
    )
    declared = declared_servers(tmp_path)
    assert [s.name for s in declared] == ["docs", "notes"]
    assert servers_for_runtime(tmp_path, settings(), "local") == declared
    assert servers_for_runtime(tmp_path, settings(), "self_hosted") == declared


def test_langsmith_managed_tools_take_the_workspace_key(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        '[servers.parallel]\nurl = "https://api.smith.langchain.com/v1/managed-tools/servers/'
        'parallel/mcp"\n',
    )
    keyed = Settings(_env_file=None, langsmith_api_key="lsv2-test")  # type: ignore[call-arg]
    (local,) = servers_for_runtime(tmp_path, keyed, "local")
    assert local.headers({}) == {"x-api-key": "lsv2-test"}
    assert "lsv2-test" not in repr(local)
