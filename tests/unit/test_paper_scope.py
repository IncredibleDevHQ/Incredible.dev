"""Paper scope on the host, driven through a real agent loop with no Paper behind it.

Each case is one model turn that emits one Paper call, so what a stand-in tool records is what
Paper would have been asked, and what the model reads back is the sentence the host wrote.
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool, tool
from langgraph.checkpoint.memory import InMemorySaver

from design_agent.middleware.paper_scope import NEEDS_PROJECT, PaperScopeMiddleware
from design_agent.testing.fakes import FolderSandbox
from design_agent.testing.scripted_model import ScriptedChatModel, reply, tool_call
from design_agent.tools import paper
from design_agent.tools.paper import (
    BRAND_NO_CLONE,
    BRAND_READ_ONLY,
    GENERATION_OFF,
    IMPORTS_REFUSED,
    PaperConfigError,
    PaperPolicy,
    admit_paper_tools,
    check_catalog,
)

BRAND = "01TESTBRAND0000"
DRAFT = "01TESTDRAFT0000"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
Calls = list[tuple[str, dict[str, Any]]]


@pytest.fixture(autouse=True)
def fresh_catalog_log() -> Iterator[None]:
    """Each test sees its own catalog warnings; the process-wide dedupe would hide repeats."""
    paper._LOGGED.clear()
    yield
    paper._LOGGED.clear()


@pytest.fixture
def calls() -> Calls:
    return []


@pytest.fixture
def sandbox(tmp_path: Path) -> FolderSandbox:
    box = FolderSandbox(tmp_path / "sb")
    (tmp_path / "sb" / "workspace" / "projects" / "teaser").mkdir(parents=True)
    return box


def stand_ins(calls: Calls, export_blocks: list[Any] | None = None) -> list[BaseTool]:
    """Stand-ins for the loaded Paper tools, in Paper's own argument spelling.

    Every file-taking stand-in accepts `fileId` even where Paper's own schema would not, so a
    default the host injected where it should not have would leave a trace to assert on.
    """

    def edit(name: str) -> BaseTool:
        @tool(name)
        async def edited(html: str = "", fileId: str | None = None) -> str:
            """Edit a Paper canvas."""
            calls.append((name, {"html": html, "fileId": fileId}))
            return "ok"

        return edited

    def read(name: str) -> BaseTool:
        @tool(name)
        async def observed(fileId: str | None = None) -> str:
            """Read a Paper file."""
            calls.append((name, {"fileId": fileId}))
            return "ok"

        return observed

    def global_tool(name: str) -> BaseTool:
        @tool(name)
        async def unscoped(query: str = "", fileId: str | None = None) -> str:
            """Read the account, not a file."""
            calls.append((name, {"query": query, "fileId": fileId}))
            return "ok"

        return unscoped

    @tool("paper_create_file")
    async def create_file(name: str = "", cloneFileId: str | None = None) -> str:
        """Create a Paper file."""
        calls.append(("paper_create_file", {"name": name, "cloneFileId": cloneFileId}))
        return "ok"

    async def export(**kwargs: Any) -> tuple[list[Any], None]:
        calls.append(("paper_export", kwargs))
        return (export_blocks if export_blocks is not None else [], None)

    exporter = StructuredTool(
        name="paper_export",
        description="Export nodes.",
        args_schema={
            "type": "object",
            "properties": {
                "fileId": {"type": "string"},
                "nodes": {"type": "object"},
                "pageId": {"type": "string"},
            },
            "required": ["nodes", "fileId"],
        },
        coroutine=export,
        response_format="content_and_artifact",
    )

    @tool("attach_file")
    async def attach(path: str) -> str:
        """Send a file to the thread."""
        calls.append(("attach_file", {"path": path}))
        return "ok"

    return [
        edit("paper_write_html"),
        edit("paper_update_styles"),
        edit("paper_delete_nodes"),
        read("paper_get_tree_summary"),
        read("paper_get_tokens"),
        read("paper_get_font_family_info"),
        read("paper_open_file"),
        global_tool("paper_list_resources"),
        global_tool("paper_get_guide"),
        global_tool("paper_teleport"),
        create_file,
        exporter,
        attach,
    ]


async def turn(
    tools: list[BaseTool],
    name: str,
    args: dict[str, Any],
    *,
    policy: PaperPolicy | None = None,
    backend: Any = None,
    model: ScriptedChatModel | None = None,
    **scope_options: Any,
) -> dict[str, Any]:
    """Run one turn whose only tool call is this one, and hand back the final state."""
    scope = PaperScopeMiddleware(
        policy or PaperPolicy(brand_file_id=BRAND, drafts_file_id=DRAFT),
        backend_for=lambda _runtime: backend,
        clock=lambda: 1_790_000_000.0,
        **scope_options,
    )
    lead = model or ScriptedChatModel(
        steps=[lambda _m: tool_call(name, args), lambda _m: reply("Done.")]
    )
    graph = create_agent(lead, tools=tools, middleware=[scope], checkpointer=InMemorySaver())
    result: dict[str, Any] = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "Lay out the card."}]},
        {"configurable": {"thread_id": name}},
    )
    return result


def replied(result: dict[str, Any]) -> ToolMessage:
    messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(messages) == 1
    return messages[0]


def refusal(result: dict[str, Any]) -> str:
    message = replied(result)
    assert message.status == "error"
    return message.text


@pytest.mark.parametrize(
    ("value", "sentence"),
    [
        ("<div>paper-gen:seed-42</div>", GENERATION_OFF),
        # The same reference written to get past a plain substring check.
        ("<img src='paper-asset&#58;01ABC'>", IMPORTS_REFUSED),
        ("<img src='file:///home/me/board.png'>", IMPORTS_REFUSED),
        # A tab inside the scheme, which a browser drops before it resolves the URL: the raw
        # character, the entities that become it, and the same trick on the generation scheme.
        ("<img src='fi\tle:///home/me/board.png'>", IMPORTS_REFUSED),
        ("<img src='fi&#9;le:///home/me/board.png'>", IMPORTS_REFUSED),
        ("<img src='file&#10;:///home/me/board.png'>", IMPORTS_REFUSED),
        ("<div>paper-ge&#9;n:seed-42</div>", GENERATION_OFF),
        # `&COLON;` survives one lowering, so the payload is unescaped on both sides of it.
        ("<img src='paper-asset&COLON;01ABC'>", IMPORTS_REFUSED),
    ],
)
async def test_a_resource_scheme_never_reaches_paper(
    calls: Calls, value: str, sentence: str
) -> None:
    result = await turn(stand_ins(calls), "paper_write_html", {"html": value})
    assert refusal(result) == sentence
    assert calls == []


async def test_generation_opted_in_reaches_paper_but_file_imports_never_do(calls: Calls) -> None:
    allowed = PaperPolicy(drafts_file_id=DRAFT, allow_generation=True)
    await turn(
        stand_ins(calls), "paper_write_html", {"html": "<div>paper-gen:seed</div>"}, policy=allowed
    )
    assert calls == [("paper_write_html", {"html": "<div>paper-gen:seed</div>", "fileId": DRAFT})]
    calls.clear()
    result = await turn(
        stand_ins(calls), "paper_write_html", {"html": "<img src='file:///x.png'>"}, policy=allowed
    )
    assert refusal(result) == IMPORTS_REFUSED and calls == []


async def test_the_brand_file_is_not_cloned_into_a_writable_copy(calls: Calls) -> None:
    """A clone is the other way to a brand file the fences do not cover: the copy has a new id."""
    result = await turn(
        stand_ins(calls), "paper_create_file", {"name": "tokens", "cloneFileId": BRAND}
    )
    assert refusal(result) == BRAND_NO_CLONE
    assert calls == []


async def test_a_design_file_may_be_cloned(calls: Calls) -> None:
    await turn(stand_ins(calls), "paper_create_file", {"name": "spike", "cloneFileId": DRAFT})
    assert calls == [("paper_create_file", {"name": "spike", "cloneFileId": DRAFT})]


@pytest.mark.parametrize(
    "target",
    [BRAND, f"https://app.paper.design/file/{BRAND}/1-0", f"https://APP.paper.design/file/{BRAND}"],
)
async def test_the_brand_file_takes_no_writes_in_any_spelling(calls: Calls, target: str) -> None:
    result = await turn(stand_ins(calls), "paper_update_styles", {"fileId": target, "html": ""})
    assert refusal(result) == BRAND_READ_ONLY
    assert calls == []


async def test_the_brand_file_takes_no_deletes_even_when_deletes_are_on(calls: Calls) -> None:
    allowed = PaperPolicy(brand_file_id=BRAND, drafts_file_id=DRAFT, allow_deletes=True)
    result = await turn(stand_ins(calls), "paper_delete_nodes", {"fileId": BRAND}, policy=allowed)
    assert refusal(result) == BRAND_READ_ONLY and calls == []
    await turn(stand_ins(calls), "paper_delete_nodes", {}, policy=allowed)
    assert calls == [("paper_delete_nodes", {"html": "", "fileId": DRAFT})]


async def test_deletes_are_off_by_default(calls: Calls) -> None:
    result = await turn(stand_ins(calls), "paper_delete_nodes", {"fileId": DRAFT})
    assert "Deleting on the Paper canvas is off" in refusal(result)
    assert calls == []


async def test_the_brand_file_still_answers_reads_and_a_link_reaches_paper_as_its_id(
    calls: Calls,
) -> None:
    result = await turn(
        stand_ins(calls),
        "paper_get_tree_summary",
        {"fileId": f"https://app.paper.design/file/{BRAND}"},
    )
    assert replied(result).status != "error"
    assert calls == [("paper_get_tree_summary", {"fileId": BRAND})]


async def test_a_call_that_names_no_file_lands_in_the_drafts_file(calls: Calls) -> None:
    result = await turn(stand_ins(calls), "paper_write_html", {"html": "<div>Hi</div>"})
    assert replied(result).status != "error"
    assert calls == [("paper_write_html", {"html": "<div>Hi</div>", "fileId": DRAFT})]


async def test_a_file_scoped_font_check_lands_in_the_drafts_file(calls: Calls) -> None:
    await turn(stand_ins(calls), "paper_get_font_family_info", {})
    assert calls == [("paper_get_font_family_info", {"fileId": DRAFT})]


async def test_a_call_that_names_a_file_keeps_it(calls: Calls) -> None:
    await turn(stand_ins(calls), "paper_write_html", {"html": "<div/>", "fileId": "TEAMFILE1"})
    assert calls == [("paper_write_html", {"html": "<div/>", "fileId": "TEAMFILE1"})]


@pytest.mark.parametrize("name", ["paper_open_file", "paper_get_tokens"])
async def test_a_call_the_drafts_default_would_answer_wrongly_must_name_its_file(
    calls: Calls, name: str
) -> None:
    """`open_file` switches the file Desktop shows, and a defaulted token read would answer a brand
    question with the drafts file's tokens, which look right."""
    result = await turn(stand_ins(calls), name, {})
    sentence = refusal(result)
    assert DRAFT in sentence and BRAND in sentence and "read-only" in sentence
    assert calls == []


async def test_a_named_file_is_still_opened(calls: Calls) -> None:
    await turn(stand_ins(calls), "paper_open_file", {"fileId": "TEAMFILE1"})
    assert calls == [("paper_open_file", {"fileId": "TEAMFILE1"})]


@pytest.mark.parametrize("name", ["paper_list_resources", "paper_get_guide"])
async def test_a_tool_that_takes_no_file_is_given_none(calls: Calls, name: str) -> None:
    await turn(stand_ins(calls), name, {"query": "brand"})
    assert calls == [(name, {"query": "brand", "fileId": None})]


async def test_without_a_drafts_file_a_file_scoped_call_is_told_what_to_pass(calls: Calls) -> None:
    result = await turn(
        stand_ins(calls), "paper_write_html", {"html": "<div/>"}, policy=PaperPolicy()
    )
    assert refusal(result) == (
        "Pass fileId on write_html: list_resources lists the files, or use the id of the file you are working in."
    )
    assert calls == []


async def test_a_value_that_is_no_paper_file_is_refused(calls: Calls) -> None:
    result = await turn(
        stand_ins(calls), "paper_write_html", {"html": "<div/>", "fileId": "../../etc"}
    )
    assert "not a Paper file id" in refusal(result)
    assert calls == []


async def test_a_tool_the_policy_does_not_name_is_refused(calls: Calls) -> None:
    result = await turn(stand_ins(calls), "paper_teleport", {"query": "anywhere"})
    assert (
        refusal(result)
        == "That Paper tool is not available here; use the paper_ tools in your tool list."
    )
    assert calls == []


async def test_another_servers_tool_is_left_alone(calls: Calls) -> None:
    """The prefix is the whole test: host tools carry no Paper policy."""
    result = await turn(stand_ins(calls), "attach_file", {"path": "paper-gen:seed-42.png"})
    assert replied(result).status != "error"
    assert calls == [("attach_file", {"path": "paper-gen:seed-42.png"})]


async def test_a_canvas_edit_runs_without_approval(calls: Calls) -> None:
    result = await turn(stand_ins(calls), "paper_write_html", {"html": "<div/>"})
    assert "__interrupt__" not in result
    assert result["messages"][-1].text == "Done."


async def test_the_model_sees_only_admitted_tools_the_export_project_and_the_files(
    calls: Calls,
) -> None:
    seen: list[Any] = []

    def capture(messages: Any) -> AIMessage:
        seen.extend(messages)
        return reply("Looked.")

    model = ScriptedChatModel(steps=[capture])
    await turn(stand_ins(calls), "look", {}, model=model)
    names = {t["function"]["name"] for t in model.bound_tool_batches[-1]}
    assert "paper_teleport" not in names and "paper_delete_nodes" not in names
    assert {"paper_write_html", "paper_export", "attach_file"} <= names
    export = next(
        t for t in model.bound_tool_batches[-1] if t["function"]["name"] == "paper_export"
    )
    assert "project" in export["function"]["parameters"]["required"]
    system = [m for m in seen if isinstance(m, SystemMessage)]
    assert (
        system
        and f"Paper drafts file: {DRAFT}" in system[0].text
        and f"Paper brand file: {BRAND} (read-only)" in system[0].text
    )


def test_a_tool_paper_stopped_advertising_is_missing_alone(
    caplog: pytest.LogCaptureFixture, calls: Calls
) -> None:
    """A rename on Paper's side degrades that one tool; the catalog is never pinned."""
    loaded = [t for t in stand_ins(calls) if t.name != "paper_get_tree_summary"]
    policy = PaperPolicy(drafts_file_id=DRAFT)
    with caplog.at_level(logging.INFO, logger=paper.__name__):
        kept = admit_paper_tools(loaded, policy)
    names = {t.name for t in kept}
    assert "paper_write_html" in names and "attach_file" in names
    assert "paper_teleport" not in names and "paper_delete_nodes" not in names
    assert "get_tree_summary" in caplog.text and "teleport" in caplog.text
    catalog = check_catalog(["get_guide", "list_files"], policy)
    assert "list_files" in catalog.unknown and "list_resources" in catalog.missing


async def test_an_export_lands_in_the_project_with_a_receipt(
    calls: Calls, sandbox: FolderSandbox, tmp_path: Path
) -> None:
    run = tmp_path / "sb" / "workspace" / "projects" / "teaser" / "run.json"
    run.write_text(json.dumps({"status": "storyboard"}))
    blocks = [
        {"type": "text", "text": "Exported 1 node."},
        {"type": "image", "base64": base64.b64encode(PNG).decode(), "mime_type": "image/png"},
    ]
    result = await turn(
        stand_ins(calls, blocks),
        "paper_export",
        {"nodes": {"A-1": []}, "pageId": "2-0", "project": "teaser"},
        backend=sandbox,
    )
    message = replied(result)
    assert message.status != "error"
    saved = "/workspace/projects/teaser/renders/paper-20260921-141320-1.png"
    assert saved in message.text and "base64" not in json.dumps(message.content)
    assert (tmp_path / "sb" / saved.removeprefix("/")).read_bytes() == PNG
    assert calls == [("paper_export", {"nodes": {"A-1": []}, "pageId": "2-0", "fileId": DRAFT})]
    data = json.loads(run.read_text())
    assert data["status"] == "storyboard"
    assert data["paper"] == [
        {
            "file_id": DRAFT,
            "page_id": "2-0",
            "link": f"https://app.paper.design/file/{DRAFT}/2-0",
            "exports": [saved],
            "at": "2026-09-21T14:13:20Z",
        }
    ]


async def test_an_export_without_bytes_still_records_the_link(
    calls: Calls, sandbox: FolderSandbox, tmp_path: Path
) -> None:
    result = await turn(
        stand_ins(calls, [{"type": "text", "text": "Saved to Downloads."}]),
        "paper_export",
        {"nodes": {}, "project": "teaser"},
        backend=sandbox,
    )
    assert "returned no file bytes" in replied(result).text
    data = json.loads(
        (tmp_path / "sb" / "workspace" / "projects" / "teaser" / "run.json").read_text()
    )
    assert data["paper"][0]["exports"] == [] and data["paper"][0]["page_id"] is None


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"nodes": {}}, NEEDS_PROJECT),
        ({"nodes": {}, "project": "../escape"}, NEEDS_PROJECT),
        ({"nodes": {}, "project": "absent"}, "There is no project folder named absent"),
    ],
)
async def test_an_export_needs_a_real_project(
    calls: Calls, sandbox: FolderSandbox, args: dict[str, Any], expected: str
) -> None:
    result = await turn(stand_ins(calls), "paper_export", args, backend=sandbox)
    assert refusal(result).startswith(expected)
    assert calls == []


async def test_a_run_json_that_is_not_json_is_not_overwritten(
    calls: Calls, sandbox: FolderSandbox, tmp_path: Path
) -> None:
    run = tmp_path / "sb" / "workspace" / "projects" / "teaser" / "run.json"
    run.write_text("{half")
    await turn(
        stand_ins(calls, []), "paper_export", {"nodes": {}, "project": "teaser"}, backend=sandbox
    )
    assert run.read_text() == "{half"


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda: PaperPolicy(brand_file_id=DRAFT, drafts_file_id=DRAFT), "different file"),
        (
            lambda: PaperPolicy(drafts_file_id=f"https://app.paper.design/file/{DRAFT}"),
            "plain Paper file id",
        ),
    ],
)
def test_a_policy_that_would_guard_nothing_does_not_build(
    build: Callable[[], PaperPolicy], message: str
) -> None:
    with pytest.raises(PaperConfigError, match=message):
        build()


def test_page_and_file_reorganization_is_an_opt_in_setting() -> None:
    from design_agent.config import Settings
    from design_agent.tools.paper import REORG_TOOLS, PaperPolicy

    assert not REORG_TOOLS & PaperPolicy.from_settings(Settings(_env_file=None)).admitted  # type: ignore[call-arg]
    allowed = PaperPolicy.from_settings(Settings(_env_file=None, paper_allow_reorg=True))  # type: ignore[call-arg]
    assert REORG_TOOLS <= allowed.admitted


async def test_a_local_export_moves_the_files_desktop_wrote_into_the_project(
    calls: Calls, sandbox: FolderSandbox, tmp_path: Path
) -> None:
    """Paper Desktop writes an export to Downloads and answers with the path; in Local mode the host
    moves that file into the project's renders and records it."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    written = downloads / "Frame 1 · Ready.png"
    written.write_bytes(PNG)
    answer = {"exports": [{"nodeId": "A-1", "filePath": str(written)}]}
    result = await turn(
        stand_ins(calls, [{"type": "text", "text": json.dumps(answer)}]),
        "paper_export",
        {"nodes": {"A-1": []}, "pageId": "2-0", "project": "teaser"},
        backend=sandbox,
        local_exports=True,
        exports_folder=downloads,
    )
    message = replied(result)
    saved = "/workspace/projects/teaser/renders/paper-20260921-141320-1.png"
    assert saved in message.text and "Downloads" not in message.text
    assert (tmp_path / "sb" / saved.removeprefix("/")).read_bytes() == PNG
    assert not written.exists()
    data = json.loads(
        (tmp_path / "sb" / "workspace" / "projects" / "teaser" / "run.json").read_text()
    )
    assert data["paper"][0]["exports"] == [saved]


async def test_a_bridged_export_never_reads_this_machines_files(
    calls: Calls, sandbox: FolderSandbox, tmp_path: Path
) -> None:
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    written = downloads / "frame.png"
    written.write_bytes(PNG)
    answer = {"exports": [{"nodeId": "A-1", "filePath": str(written)}]}
    result = await turn(
        stand_ins(calls, [{"type": "text", "text": json.dumps(answer)}]),
        "paper_export",
        {"nodes": {"A-1": []}, "project": "teaser"},
        backend=sandbox,
        exports_folder=downloads,
    )
    assert "returned no file bytes" in replied(result).text and written.exists()
