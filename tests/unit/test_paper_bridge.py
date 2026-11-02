"""The Paper bridge authenticates before reaching Paper and holds every call to the host's policy.

A fake Paper Desktop (an in-process FastMCP server with Paper's tool names) sits behind the real
bridge app; requests go through Starlette's test client as raw MCP JSON-RPC.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastmcp import FastMCP
from starlette.testclient import TestClient

from design_agent.middleware.paper_scope import PaperScopeMiddleware
from design_agent.paper_bridge import app as bridge
from design_agent.paper_bridge.app import (
    DESKTOP_UNAVAILABLE,
    FOREIGN_FILE,
    TEAM_DRIFT,
    BridgeConfigError,
    BridgePolicy,
    allowed_hostnames,
    create_app,
)
from design_agent.tools.paper import BRAND_READ_ONLY, IMPORTS_REFUSED, PaperPolicy

TOKEN = "x" * 43
BRAND = "BRAND123"
DRAFT = "DRAFT123"
HOSTS = frozenset({"testserver", "127.0.0.1", "localhost", "paper.example.com"})
AUTHORIZED = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}
POLICY = PaperPolicy(brand_file_id=BRAND, drafts_file_id=DRAFT)


class FakeDesktop:
    """Paper Desktop's MCP with a handful of its tools; records every call that reaches it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.team = "team_TEST"
        self.fail = False
        self.server = FastMCP("paper")
        resources = [
            {"id": DRAFT, "type": "file", "createdAt": 1, "updatedAt": 2},
            {"id": "FOLDER1", "type": "folder", "createdAt": 1, "updatedAt": 2},
            {"id": "TEAMFILE", "type": "file", "createdAt": 1, "updatedAt": 2},
            {"id": "FOREIGN", "type": "file", "open": True},
        ]
        record = self.calls.append

        @self.server.tool
        def get_guide(topic: str) -> str:
            record(("get_guide", {"topic": topic}))
            return "guide"

        @self.server.tool
        def write_html(html: str, fileId: str) -> str:
            if self.fail:
                raise RuntimeError("socket at /Users/someone/.paper/desktop.sock refused")
            record(("write_html", {"html": html, "fileId": fileId}))
            return "wrote"

        @self.server.tool
        def get_tokens(fileId: str) -> str:
            record(("get_tokens", {"fileId": fileId}))
            return "{}"

        @self.server.tool
        def delete_nodes(nodeIds: list[str], fileId: str) -> str:
            record(("delete_nodes", {"fileId": fileId}))
            return "deleted"

        @self.server.tool
        def set_comment_thread_status(commentThreadId: str, status: str, fileId: str) -> str:
            record(("set_comment_thread_status", {}))
            return "ok"

        @self.server.tool
        def list_resources(limit: int = 50) -> str:
            record(("list_resources", {"limit": limit}))
            return json.dumps({"teamId": self.team, "resources": resources})


@pytest.fixture
def desktop() -> FakeDesktop:
    return FakeDesktop()


def client_for(
    desktop: FakeDesktop, *, team: str | None = None, policy: PaperPolicy = POLICY
) -> TestClient:
    return TestClient(
        create_app(policy, token=TOKEN, upstream=desktop.server, hostnames=HOSTS, team_id=team)
    )


@pytest.fixture
def client(desktop: FakeDesktop) -> Iterator[TestClient]:
    with client_for(desktop) as test_client:
        yield test_client


def rpc(
    client: TestClient, method: str, params: dict[str, Any], headers: dict[str, str] | None = None
) -> Any:
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers=AUTHORIZED if headers is None else headers,
    )


def call(client: TestClient, name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
    result = rpc(client, "tools/call", {"name": name, "arguments": arguments}).json()["result"]
    return result["isError"], result["content"][0]["text"]


def test_a_short_or_spaced_token_never_starts_a_bridge(desktop: FakeDesktop) -> None:
    for token in ("x" * 42, " " + "x" * 43, "é" * 43):
        with pytest.raises(BridgeConfigError, match="32 random bytes"):
            create_app(POLICY, token=token, upstream=desktop.server)


def test_a_malformed_team_id_never_starts_a_bridge(desktop: FakeDesktop) -> None:
    with pytest.raises(BridgeConfigError, match="PAPER_TEAM_ID"):
        create_app(POLICY, token=TOKEN, upstream=desktop.server, team_id="team/../x")


def test_authentication_precedes_any_access_to_paper(
    client: TestClient, desktop: FakeDesktop
) -> None:
    accept = {"Accept": AUTHORIZED["Accept"]}
    assert rpc(client, "tools/list", {}, accept).status_code == 401
    assert (
        rpc(client, "tools/list", {}, {**accept, "Authorization": "Bearer wrong"}).status_code
        == 401
    )
    assert rpc(client, "tools/list", {}, {**accept, "Authorization": TOKEN}).status_code == 401
    assert desktop.calls == []
    response = rpc(client, "tools/list", {})
    assert response.status_code == 200 and response.headers["content-type"].startswith(
        "application/json"
    )


def test_a_rebinding_host_or_foreign_origin_is_refused_before_the_token(
    client: TestClient, desktop: FakeDesktop
) -> None:
    assert (
        rpc(client, "tools/list", {}, {**AUTHORIZED, "Host": "attacker.example"}).status_code == 421
    )
    assert (
        rpc(
            client, "tools/list", {}, {**AUTHORIZED, "Host": "127.0.0.1.attacker.example"}
        ).status_code
        == 421
    )
    assert (
        rpc(
            client, "tools/list", {}, {**AUTHORIZED, "Origin": "https://attacker.example"}
        ).status_code
        == 403
    )
    assert (
        rpc(client, "tools/list", {}, {**AUTHORIZED, "Host": "paper.example.com"}).status_code
        == 200
    )
    assert (
        rpc(client, "tools/list", {}, {**AUTHORIZED, "Host": "localhost:29980"}).status_code == 200
    )
    assert desktop.calls == []


def test_only_the_mcp_path_is_served(client: TestClient) -> None:
    assert client.post("/other", json={}, headers=AUTHORIZED).status_code == 404
    assert client.post("/mcp/../admin", json={}, headers=AUTHORIZED).status_code == 404
    assert client.post("/other", json={}).status_code == 401, (
        "an unauthenticated caller learns nothing"
    )


def test_tunnel_hostnames_are_bare_names() -> None:
    assert "paper.example.com" in allowed_hostnames(["Paper.Example.com"])
    for bad in (
        "https://paper.example.com",
        "paper.example.com:443",
        "paper.example.com/mcp",
        "*.example.com",
    ):
        with pytest.raises(BridgeConfigError):
            allowed_hostnames([bad])


def test_the_bridge_offers_only_the_tools_the_policy_admits(client: TestClient) -> None:
    tools = {tool["name"] for tool in rpc(client, "tools/list", {}).json()["result"]["tools"]}
    assert tools == {"get_guide", "write_html", "get_tokens", "list_resources"}
    deletes = PaperPolicy(drafts_file_id=DRAFT, allow_deletes=True)
    with client_for(FakeDesktop(), policy=deletes) as opted_in:
        assert "delete_nodes" in {
            t["name"] for t in rpc(opted_in, "tools/list", {}).json()["result"]["tools"]
        }


def test_paper_resources_and_prompts_are_not_offered(client: TestClient) -> None:
    assert rpc(client, "resources/list", {}).json()["result"]["resources"] == []
    assert rpc(client, "prompts/list", {}).json()["result"]["prompts"] == []


def test_calls_are_held_to_the_same_policy_as_the_host(
    client: TestClient, desktop: FakeDesktop
) -> None:
    assert call(client, "write_html", {"html": "x", "fileId": BRAND}) == (True, BRAND_READ_ONLY)
    assert call(
        client, "write_html", {"html": "<img src='paper-asset&#58;/x.png'>", "fileId": DRAFT}
    ) == (True, IMPORTS_REFUSED)
    assert call(client, "delete_nodes", {"nodeIds": [], "fileId": DRAFT})[0] is True
    assert (
        call(
            client,
            "set_comment_thread_status",
            {"commentThreadId": "c", "status": "resolved", "fileId": DRAFT},
        )[0]
        is True
    )
    assert desktop.calls == []
    assert call(
        client, "write_html", {"html": "x", "fileId": f"https://app.paper.design/file/{DRAFT}/1-0"}
    ) == (False, "wrote")
    assert call(client, "write_html", {"html": "y"}) == (False, "wrote")
    assert desktop.calls == [
        ("write_html", {"html": "x", "fileId": DRAFT}),
        ("write_html", {"html": "y", "fileId": DRAFT}),
    ]


def test_bridge_and_host_decide_with_one_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both enforcement points call `PaperPolicy.decide`; neither keeps its own copy of the rules."""
    seen: list[str] = []
    original = PaperPolicy.decide

    def spy(self: PaperPolicy, tool: str, args: Any) -> Any:
        seen.append(tool)
        return original(self, tool, args)

    monkeypatch.setattr(PaperPolicy, "decide", spy)
    assert BridgePolicy(POLICY).policy is POLICY
    assert PaperScopeMiddleware(POLICY, backend_for=lambda _r: None)._policy is POLICY
    with client_for(FakeDesktop()) as test_client:
        call(test_client, "get_guide", {"topic": "paper-mcp-instructions"})
    assert seen == ["get_guide"]


def test_paper_tool_errors_reach_the_model_and_transport_failures_read_as_one_sentence(
    client: TestClient, desktop: FakeDesktop
) -> None:
    """Paper's own error result is what the model corrects itself from, so it passes through; a
    Desktop that cannot be reached at all is one sentence, never the transport's internals."""
    desktop.fail = True
    error, text = call(client, "write_html", {"html": "x", "fileId": DRAFT})
    assert error is True and "refused" in text
    from fastmcp.client.transports import StreamableHttpTransport

    unreachable = StreamableHttpTransport("http://127.0.0.1:9/mcp")
    with TestClient(
        create_app(POLICY, token=TOKEN, upstream=unreachable, hostnames=HOSTS)
    ) as offline:
        assert call(offline, "write_html", {"html": "x", "fileId": DRAFT}) == (
            True,
            DESKTOP_UNAVAILABLE,
        )


def test_a_transport_failure_reads_as_desktop_unavailable(
    monkeypatch: pytest.MonkeyPatch, desktop: FakeDesktop
) -> None:
    async def broken(self: Any, context: Any) -> Any:
        raise OSError("connection refused on 127.0.0.1:29979")

    with client_for(desktop, team="team_TEST") as test_client:
        monkeypatch.setattr(bridge.TeamScope, "listing", broken)
        assert call(test_client, "write_html", {"html": "x", "fileId": DRAFT}) == (
            True,
            DESKTOP_UNAVAILABLE,
        )


def test_with_a_team_desktop_must_be_in_it_and_calls_stay_in_it(desktop: FakeDesktop) -> None:
    with client_for(desktop, team="team_TEST") as test_client:
        assert call(test_client, "write_html", {"html": "x", "fileId": "TEAMFILE"}) == (
            False,
            "wrote",
        )
        assert call(test_client, "write_html", {"html": "x", "fileId": "FOREIGN"}) == (
            True,
            FOREIGN_FILE,
        )
        assert call(test_client, "write_html", {"html": "x", "fileId": "FOLDER1"}) == (
            True,
            FOREIGN_FILE,
        )
        listing = json.loads(call(test_client, "list_resources", {"limit": 10})[1])
        assert [item["id"] for item in listing["resources"]] == [DRAFT, "FOLDER1", "TEAMFILE"]
        assert call(test_client, "get_guide", {"topic": "paper-mcp-instructions"}) == (
            False,
            "guide",
        )
        desktop.team = "team_OTHER"
        assert call(test_client, "write_html", {"html": "x", "fileId": "TEAMFILE"}) == (
            True,
            TEAM_DRIFT,
        )
    writes = [args["fileId"] for name, args in desktop.calls if name == "write_html"]
    assert writes == ["TEAMFILE"]
