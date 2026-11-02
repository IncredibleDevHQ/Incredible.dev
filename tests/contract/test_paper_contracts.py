"""Real graph, scripted model, a fake Paper: the storyboard twin, its export and its receipt.

The fake is an in-process FastMCP server exposing a few of Paper Desktop's tools under their real
names, loaded through `load_mcp_tools` the way a runtime loads Paper, so tools reach the graph as
`paper_<tool>` and calls cross the real MCP adapter. The assembly puts `PaperScopeMiddleware` ahead
of the model guards, so tool disclosure only ever sees admitted Paper tools.

The live test at the bottom talks to the developer's own Paper Desktop (SPEC §20.6).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.utilities.types import Image
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import BaseTool

from design_agent.config import Settings
from design_agent.harness.tasks import REGISTRY
from design_agent.middleware.image_clamp import ImageClampMiddleware
from design_agent.middleware.paper_scope import PaperScopeMiddleware
from design_agent.runtime.local import LocalRuntime, build_local_runtime
from design_agent.testing.fakes import folder_binding
from design_agent.testing.scripted_model import ScriptedChatModel, reply, tool_call
from design_agent.tools import paper
from design_agent.tools.mcp import McpServer, _transport, load_mcp_tools
from design_agent.tools.paper import (
    BRAND_READ_ONLY,
    PaperConfigError,
    PaperPolicy,
    admit_paper_tools,
    paper_server,
)

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.filterwarnings("ignore::langchain_core._api.LangChainBetaWarning")
BRAND = "01BRANDFILE000"
DRAFTS = "01DRAFTSFILE00"
PROJECT = "launch-teaser"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


@pytest.fixture(autouse=True)
def fresh_catalog_log() -> Iterator[None]:
    """Each test sees its own catalog warnings; the process-wide dedupe would hide repeats."""
    paper._LOGGED.clear()
    yield
    paper._LOGGED.clear()


@pytest.fixture(autouse=True)
def clean() -> Iterator[None]:
    yield
    REGISTRY.clear()


def fake_paper(calls: list[tuple[str, dict[str, Any]]]) -> FastMCP:
    """A Paper Desktop with no `get_screenshot`, as if Paper had renamed it."""
    server = FastMCP("paper")

    @server.tool
    def get_guide(topic: str) -> str:
        calls.append(("get_guide", {"topic": topic}))
        return "Write one visual group per call; call finish_working_on_nodes when done."

    @server.tool
    def create_page(fileId: str, name: str = "") -> str:
        calls.append(("create_page", {"fileId": fileId, "name": name}))
        return json.dumps({"pageId": "2-0"})

    @server.tool
    def create_artboard(
        fileId: str, name: str, styles: dict[str, Any], pageId: str | None = None
    ) -> str:
        calls.append(("create_artboard", {"fileId": fileId, "name": name, "pageId": pageId}))
        return json.dumps({"nodeId": "A-1"})

    @server.tool
    def write_html(fileId: str, html: str, targetNodeId: str, mode: str) -> str:
        calls.append(("write_html", {"fileId": fileId, "targetNodeId": targetNodeId}))
        return "Wrote 3 nodes."

    @server.tool
    def export(fileId: str, nodes: dict[str, Any], pageId: str | None = None) -> Image:
        calls.append(("export", {"fileId": fileId, "nodes": nodes, "pageId": pageId}))
        return Image(data=PNG, format="png")

    @server.tool
    def finish_working_on_nodes(fileId: str) -> str:
        calls.append(("finish_working_on_nodes", {"fileId": fileId}))
        return "Released."

    @server.tool
    def delete_nodes(fileId: str, nodeIds: list[str]) -> str:
        calls.append(("delete_nodes", {"fileId": fileId}))
        return "Deleted."

    return server


async def load_fake(server: FastMCP) -> tuple[McpServer, list[BaseTool]]:
    declared = McpServer("paper", "", transport="stdio", command=("paper", "mcp"))

    async def loader(entry: McpServer, _env: object) -> list[BaseTool]:
        from langchain.mcp import MCPAdapter  # the runtime's own adapter (tools/mcp.py)

        async with MCPAdapter(server) as adapter:
            tools = await adapter.list_tools()
        return [t.model_copy(update={"name": f"{entry.name}_{t.name}"}) for t in tools]

    loaded = await load_mcp_tools([declared], loader=loader)
    assert loaded.failed == {}
    return declared, loaded.tools


def with_paper_scope(runtime: LocalRuntime, policy: PaperPolicy) -> LocalRuntime:
    """The assembly puts the scope just ahead of the lead's model guards when Paper is declared."""
    middleware = list(runtime.components.middleware)
    scope = next(i for i, m in enumerate(middleware) if isinstance(m, PaperScopeMiddleware))
    assert isinstance(middleware[scope + 1], ImageClampMiddleware)
    assert middleware[scope]._policy == policy
    helpers = [s for s in runtime.components.subagents if s.get("middleware")]
    assert all(any(isinstance(m, PaperScopeMiddleware) for m in s["middleware"]) for s in helpers)
    return runtime


def storyboard_turn() -> ScriptedChatModel:
    """Guide once, a page and a frame in the drafts file, a check that finds its tool gone, a
    write aimed at the brand file, the export, release, and the board attached."""

    def attach(messages: Sequence[BaseMessage]) -> AIMessage:
        exported = [
            m.text for m in messages if isinstance(m, ToolMessage) and m.name == "paper_export"
        ]
        saved = re.search(r"/workspace/projects/\S+?\.png", exported[-1])
        assert saved, exported
        return tool_call("upload_files", {"paths": [saved.group(0)]})

    return ScriptedChatModel(
        steps=[
            lambda _m: tool_call("paper_get_guide", {"topic": "paper-mcp-instructions"}),
            lambda _m: tool_call("paper_create_page", {"name": "Teaser storyboard"}),
            lambda _m: tool_call(
                "paper_create_artboard",
                {
                    "fileId": DRAFTS,
                    "name": "Beat 1",
                    "pageId": "2-0",
                    "styles": {"width": "1920px", "height": "1080px"},
                },
            ),
            lambda _m: tool_call(
                "paper_write_html",
                {
                    "fileId": DRAFTS,
                    "html": "<div>Beat 1</div>",
                    "targetNodeId": "A-1",
                    "mode": "insert-children",
                },
            ),
            lambda _m: tool_call("paper_get_screenshot", {"fileId": DRAFTS, "nodeId": "A-1"}),
            lambda _m: tool_call(
                "paper_write_html",
                {
                    "fileId": BRAND,
                    "html": "<div/>",
                    "targetNodeId": "root",
                    "mode": "insert-children",
                },
            ),
            lambda _m: tool_call(
                "paper_export",
                {"fileId": DRAFTS, "nodes": {"A-1": []}, "pageId": "2-0", "project": PROJECT},
            ),
            lambda _m: tool_call("paper_finish_working_on_nodes", {"fileId": DRAFTS}),
            attach,
            lambda _m: reply("The board is attached and editable in Paper."),
        ]
    )


async def test_a_storyboard_lands_in_the_drafts_file_exports_attaches_and_leaves_a_receipt(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    declared, tools = await load_fake(fake_paper(calls))
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        workspace_root=tmp_path / "ws",
        paper_mode="local",
        paper_brand_file_id=BRAND,
        paper_drafts_file_id=DRAFTS,
    )
    policy = PaperPolicy.from_settings(settings)
    project = tmp_path / "sb" / "workspace" / "projects" / PROJECT
    project.mkdir(parents=True)
    (project / "run.json").write_text(json.dumps({"status": "storyboard", "phase": "board"}))
    with caplog.at_level(logging.INFO, logger=paper.__name__):
        admitted = admit_paper_tools(tools, policy)
    runtime = with_paper_scope(
        build_local_runtime(
            settings,
            ROOT,
            model=storyboard_turn(),
            binding=folder_binding(tmp_path / "sb", ROOT),
            out_dir=tmp_path / "out",
            replies=lambda *_: None,
            mcp_servers=[declared],
            mcp_tools=admitted,
        ),
        policy,
    )

    added = await runtime.ask(
        "Storyboard the teaser in Paper and send me the board.", thread_id="p1"
    )

    # The frame went to a page in the drafts file, and nothing reached the brand file.
    assert ("create_page", {"fileId": DRAFTS, "name": "Teaser storyboard"}) in calls
    assert ("write_html", {"fileId": DRAFTS, "targetNodeId": "A-1"}) in calls
    assert all(args.get("fileId") != BRAND for _name, args in calls)
    results = {m.tool_call_id: m for m in added if isinstance(m, ToolMessage)}
    refusals = [m for m in results.values() if m.name == "paper_write_html" and m.status == "error"]
    assert [m.text for m in refusals] == [BRAND_READ_ONLY]
    # Paper stopped advertising one tool: that tool alone is gone, and the turn carried on.
    assert "get_screenshot" in caplog.text
    missing = [m for m in results.values() if m.name == "paper_get_screenshot"]
    assert missing and missing[0].status == "error"
    assert ("finish_working_on_nodes", {"fileId": DRAFTS}) in calls
    # The export reached Paper without the host's argument, landed in the project and was attached.
    exported = [args for name, args in calls if name == "export"]
    assert exported == [{"fileId": DRAFTS, "nodes": {"A-1": []}, "pageId": "2-0"}]
    renders = sorted((project / "renders").glob("paper-*.png"))
    assert len(renders) == 1 and renders[0].read_bytes() == PNG
    delivered = tmp_path / "out" / "p1" / renders[0].name
    assert delivered.read_bytes() == PNG
    # The receipt: Paper file, page and link beside the run's own fields, and nothing secret.
    run = json.loads((project / "run.json").read_text())
    assert (run["status"], run["phase"]) == ("storyboard", "board")
    receipt = run["paper"][0]
    assert (receipt["file_id"], receipt["page_id"], receipt["link"]) == (
        DRAFTS,
        "2-0",
        f"https://app.paper.design/file/{DRAFTS}/2-0",
    )
    assert receipt["exports"] == [f"/workspace/projects/{PROJECT}/renders/{renders[0].name}"]
    assert set(receipt) == {"file_id", "page_id", "link", "exports", "at"}
    assert added[-1].content == "The board is attached and editable in Paper."


async def test_paper_tools_the_policy_does_not_admit_never_reach_the_graph(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    _declared, tools = await load_fake(fake_paper(calls))
    admitted = {t.name for t in admit_paper_tools(tools, PaperPolicy(drafts_file_id=DRAFTS))}
    assert "paper_delete_nodes" not in admitted and "paper_write_html" in admitted


@pytest.mark.live
async def test_live_paper_desktop_reads_writes_screenshots_exports_and_cleans_up() -> None:
    """Paper Local mode against the developer's own Paper Desktop (SPEC §20.6).

    Point PAPER_DRAFTS_FILE_ID at a scratch file first: the test adds one artboard there and
    deletes it again. Skipped unless DESIGN_AGENT_LIVE_TESTS=1 and Paper Desktop answers.
    """
    settings = Settings(paper_mode="local")  # type: ignore[call-arg]
    scratch = settings.paper_drafts_file_id
    if not scratch:
        pytest.skip("set PAPER_DRAFTS_FILE_ID to a scratch Paper file")
    try:
        server = paper_server(settings, runtime="local")
    except PaperConfigError as error:
        pytest.skip(f"Paper Desktop is not reachable: {error}")
    assert server is not None
    policy = PaperPolicy(
        brand_file_id=settings.paper_brand_file_id, drafts_file_id=scratch, allow_deletes=True
    )

    async def paper_call(client: Client[Any], tool: str, args: dict[str, Any]) -> Any:
        decision = policy.decide(tool, args)
        assert decision.refusal is None, decision.refusal
        result = await client.call_tool(tool, decision.args, raise_on_error=False)
        assert not result.is_error, result.content
        return result

    try:
        client: Client[Any] = Client(_transport(server, os.environ))
        async with client:
            await paper_call(client, "get_guide", {"topic": "paper-mcp-instructions"})
            await paper_call(client, "get_basic_info", {})
            created = await paper_call(
                client,
                "create_artboard",
                {"name": "design-agent live test", "styles": {"width": "320px", "height": "200px"}},
            )
            node = re.search(r"[0-9A-Za-z]+-[0-9A-Za-z]+", created.content[0].text)
            assert node, created.content
            try:
                await paper_call(client, "get_screenshot", {"nodeId": node.group(0)})
                exported = await paper_call(
                    client, "export", {"nodes": {node.group(0): [{"format": "png", "scale": "1x"}]}}
                )
                assert exported.content
            finally:
                await paper_call(client, "delete_nodes", {"nodeIds": [node.group(0)]})
                await paper_call(client, "finish_working_on_nodes", {})
    except OSError as error:
        pytest.skip(f"Paper Desktop is not reachable: {type(error).__name__}")
