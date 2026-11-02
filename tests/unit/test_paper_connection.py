"""Paper's connection per mode and runtime, and the stdio transport it needs in `tools/mcp.py`."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from design_agent.config import Settings
from design_agent.tools import mcp
from design_agent.tools.mcp import (
    McpConfigError,
    McpServer,
    declared_servers,
    mda_declaration,
    servers_for_runtime,
)
from design_agent.tools.paper import (
    BRIDGE_CONNECTION,
    LOCAL_HTTP,
    PaperConfigError,
    paper_cli,
    paper_server,
)

TOKEN = "t" * 43


def settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def found() -> str:
    return "/opt/paper/bin/paper"


def missing() -> None:
    return None


def test_off_declares_nothing() -> None:
    assert paper_server(settings(), runtime="local") is None


def test_local_prefers_desktops_stdio_cli() -> None:
    server = paper_server(settings(paper_mode="local"), runtime="local", cli=found)
    assert server is not None
    assert (server.name, server.transport, server.command, server.url) == (
        "paper",
        "stdio",
        ("/opt/paper/bin/paper", "mcp"),
        "",
    )


def test_local_finds_the_cli_paper_desktop_installs(tmp_path: Path) -> None:
    cli = tmp_path / ".paper" / "bin" / "paper"
    cli.parent.mkdir(parents=True)
    cli.write_text("#!/bin/sh\n")
    cli.chmod(0o755)
    assert paper_cli(home=tmp_path, which=lambda _name: None) == str(cli)
    assert (
        paper_cli(home=tmp_path / "nobody", which=lambda _name: "/usr/local/bin/paper")
        == "/usr/local/bin/paper"
    )


def test_local_without_the_cli_says_what_to_do() -> None:
    with pytest.raises(PaperConfigError, match="open Paper Desktop once"):
        paper_server(settings(paper_mode="local"), runtime="self_hosted", cli=missing)


def test_local_takes_desktops_legacy_http_endpoint_and_nothing_else() -> None:
    server = paper_server(
        settings(paper_mode="local", paper_mcp_url=LOCAL_HTTP), runtime="local", cli=missing
    )
    assert server is not None and (server.transport, server.url) == ("http", LOCAL_HTTP)
    for url in (
        "https://paper.example.com/mcp",
        "http://127.0.0.1:8080/mcp",
        "http://localhost:29979/mcp",
    ):
        with pytest.raises(PaperConfigError, match="PAPER_MODE=bridged"):
            paper_server(settings(paper_mode="local", paper_mcp_url=url), runtime="local")


def test_local_is_not_served_on_mda() -> None:
    with pytest.raises(PaperConfigError, match="on Managed Deep Agents use PAPER_MODE=bridged"):
        paper_server(settings(paper_mode="local"), runtime="mda", cli=found)


def test_bridged_locally_carries_the_bearer_from_settings_and_never_prints_it() -> None:
    configured = settings(
        paper_mode="bridged",
        paper_mcp_url="https://paper.example.com/mcp",
        paper_bridge_token=TOKEN,
    )
    server = paper_server(configured, runtime="self_hosted")
    assert server is not None and server.connection is None
    assert server.headers({}) == {"Authorization": f"Bearer {TOKEN}"}
    assert TOKEN not in repr(server)


def test_bridged_on_mda_names_the_workspace_connection_and_holds_no_secret() -> None:
    configured = settings(
        paper_mode="bridged",
        paper_mcp_url="https://paper.example.com/mcp",
        paper_bridge_token=TOKEN,
    )
    server = paper_server(configured, runtime="mda")
    assert server is not None
    assert (server.connection, server.bearer) == (BRIDGE_CONNECTION, None)


@pytest.mark.parametrize(
    ("values", "runtime", "message"),
    [
        ({"paper_mcp_url": None}, "local", "PAPER_MCP_URL"),
        ({"paper_mcp_url": "http://paper.example.com/mcp"}, "local", "https"),
        ({"paper_mcp_url": "http://127.0.0.1:29980/mcp"}, "mda", "https"),
        ({"paper_mcp_url": "https://paper.example.com/mcp"}, "local", "PAPER_BRIDGE_TOKEN"),
    ],
)
def test_bridged_without_what_it_needs_says_which(
    values: dict[str, Any], runtime: Any, message: str
) -> None:
    with pytest.raises(PaperConfigError, match=message):
        paper_server(settings(paper_mode="bridged", **values), runtime=runtime)


def test_bridged_may_reach_a_bridge_on_this_machine_for_testing() -> None:
    configured = settings(
        paper_mode="bridged", paper_mcp_url="http://127.0.0.1:29980/mcp", paper_bridge_token=TOKEN
    )
    server = paper_server(configured, runtime="local")
    assert server is not None and server.url == "http://127.0.0.1:29980/mcp"


def test_colliding_paper_files_fail_before_a_run() -> None:
    with pytest.raises(PaperConfigError, match="different file"):
        paper_server(
            settings(paper_mode="local", paper_brand_file_id="SAME1", paper_drafts_file_id="SAME1"),
            runtime="local",
            cli=found,
        )


def write_config(root: Path, text: str) -> None:
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "mcp.toml").write_text(text)


def test_servers_for_runtime_adds_paper_after_the_declared_servers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(tmp_path, '[servers.docs]\nurl = "https://docs.example.com/mcp"\n')
    monkeypatch.setattr("design_agent.tools.paper.paper_cli", found)
    names = [s.name for s in servers_for_runtime(tmp_path, settings(paper_mode="local"), "local")]
    assert names == ["docs", "paper"]


def test_a_paper_that_cannot_be_served_leaves_only_paper_out(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    write_config(tmp_path, '[servers.docs]\nurl = "https://docs.example.com/mcp"\n')
    with caplog.at_level(logging.WARNING, logger=mcp.__name__):
        servers = servers_for_runtime(tmp_path, settings(paper_mode="local"), "mda")
    assert [s.name for s in servers] == ["docs"]
    assert "paper left out" in caplog.text


def test_a_declared_server_named_paper_is_a_config_error(tmp_path: Path) -> None:
    write_config(tmp_path, '[servers.paper]\nurl = "https://paper.example.com/mcp"\n')
    with pytest.raises(McpConfigError, match="PAPER_MODE"):
        servers_for_runtime(tmp_path, settings(), "local")


def test_config_declares_a_stdio_server_with_a_command_and_no_url(tmp_path: Path) -> None:
    write_config(tmp_path, '[servers.notes]\ntransport = "stdio"\ncommand = ["notes-app", "mcp"]\n')
    assert declared_servers(tmp_path)[0].command == ("notes-app", "mcp")
    write_config(
        tmp_path,
        '[servers.notes]\ntransport = "stdio"\ncommand = ["notes-app"]\nurl = "https://x.example/mcp"\n',
    )
    with pytest.raises(McpConfigError, match="takes a command and no url"):
        declared_servers(tmp_path)


def test_a_stdio_child_gets_only_the_sdks_safe_environment() -> None:
    transport = mcp._transport(
        McpServer("paper", "", transport="stdio", command=("paper", "mcp")),
        {"ANTHROPIC_API_KEY": "k"},
    )
    assert (transport.command, transport.args, transport.env) == ("paper", ["mcp"], None)


def test_mda_leaves_stdio_and_bearer_only_servers_out(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    declared: dict[str, Any] = {}
    monkeypatch.setattr(
        "managed_deepagents.define_mcp", lambda **config: declared.update(config) or "declared"
    )
    servers = [
        McpServer("paper", "", transport="stdio", command=("paper", "mcp")),
        McpServer("bridge", "https://b.example/mcp", bearer=SecretStr(TOKEN)),
        McpServer("docs", "https://docs.example.com/mcp"),
    ]
    with caplog.at_level(logging.WARNING, logger=mcp.__name__):
        assert mda_declaration(servers) == "declared"
    assert list(declared["servers"]) == ["docs"]
    assert "paper left out on MDA: it runs over stdio" in caplog.text
    assert mda_declaration(servers[:1]) is None
