"""Delivery: the local upload tool and the exactly-once ledger."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from deepagents.backends.protocol import ExecuteResponse, FileDownloadResponse, FileUploadResponse
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from design_agent.tools.delivery import (
    UPLOADED,
    DeliveryLedgerMiddleware,
    LocalOutputAdapter,
    build_upload_tool,
    ledger_path,
)


class FakeBackend:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return [
            FileDownloadResponse(
                path=p,
                content=self.files.get(p),
                error=None if p in self.files else "file_not_found",
            )
            for p in paths
        ]

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        self.files.update(files)
        return [FileUploadResponse(path=p) for p, _ in files]

    def execute(self, command: str, timeout: int | None = None) -> ExecuteResponse:
        lines = []
        for path, content in self.files.items():
            if path in command:
                lines.append(f"{hashlib.sha256(content).hexdigest()}  {path}")
        return ExecuteResponse(output="\n".join(lines), exit_code=0)


class Runtime:
    config: dict[str, Any] = {"configurable": {"thread_id": "t-1"}}


def test_ledger_path_groups_by_project() -> None:
    assert (
        ledger_path("/workspace/projects/card/renders/a.png")
        == "/workspace/projects/card/DELIVERY.json"
    )
    assert ledger_path("/workspace/attachments/a.png") == "/workspace/projects/DELIVERY.json"


def test_upload_tool_copies_files_and_refuses_paths_outside_workspace(tmp_path: Path) -> None:
    backend = FakeBackend({"/workspace/projects/card/a.png": b"png-bytes"})
    tool = build_upload_tool(
        adapter=LocalOutputAdapter(tmp_path),
        backend_for=lambda _rt: backend,  # type: ignore[arg-type,return-value]
        thread_id_for=lambda _rt: "t-1",
    )
    func = tool.func  # type: ignore[attr-defined]
    assert func(paths=["/workspace/projects/card/a.png"], runtime=Runtime()) == UPLOADED
    assert (tmp_path / "t-1/a.png").read_bytes() == b"png-bytes"
    assert "under /workspace" in func(paths=["/etc/passwd"], runtime=Runtime())
    assert "could not be read" in func(paths=["/workspace/missing.png"], runtime=Runtime())


def _request(paths: list[str]) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={
            "name": "upload_files",
            "args": {"paths": paths},
            "id": "call-1",
            "type": "tool_call",
        },
        tool=None,
        state={"messages": []},
        runtime=Runtime(),  # type: ignore[arg-type]
    )


def test_ledger_sends_once_and_records_only_confirmed_uploads() -> None:
    backend = FakeBackend(
        {"/workspace/projects/card/a.png": b"A", "/workspace/projects/card/b.png": b"B"}
    )
    ledger = DeliveryLedgerMiddleware(
        lambda _rt: backend, thread_id_for=lambda _rt: "t-1", clock=lambda: 1.0
    )  # type: ignore[arg-type,return-value]
    sent: list[list[str]] = []

    def handler(request: ToolCallRequest) -> ToolMessage:
        sent.append(request.tool_call["args"]["paths"])
        return ToolMessage(content=UPLOADED, tool_call_id="call-1")

    ledger.wrap_tool_call(_request(["/workspace/projects/card/a.png"]), handler)
    again = ledger.wrap_tool_call(_request(["/workspace/projects/card/a.png"]), handler)
    assert "Already delivered" in str(again.content)  # type: ignore[union-attr]
    ledger.wrap_tool_call(
        _request(["/workspace/projects/card/a.png", "/workspace/projects/card/b.png"]), handler
    )
    assert sent == [["/workspace/projects/card/a.png"], ["/workspace/projects/card/b.png"]]
    record = json.loads(backend.files["/workspace/projects/card/DELIVERY.json"])
    assert [d["path"] for d in record["deliveries"]] == [
        "/workspace/projects/card/a.png",
        "/workspace/projects/card/b.png",
    ]


def test_ledger_records_nothing_when_the_upload_failed() -> None:
    backend = FakeBackend({"/workspace/projects/card/a.png": b"A"})
    ledger = DeliveryLedgerMiddleware(lambda _rt: backend, thread_id_for=lambda _rt: "t-1")  # type: ignore[arg-type,return-value]
    ledger.wrap_tool_call(
        _request(["/workspace/projects/card/a.png"]),
        lambda _r: ToolMessage(content="File upload failed.", tool_call_id="call-1"),
    )
    assert "/workspace/projects/card/DELIVERY.json" not in backend.files


def test_a_changed_file_with_the_same_path_is_sent_again() -> None:
    backend = FakeBackend({"/workspace/projects/card/a.png": b"A"})
    ledger = DeliveryLedgerMiddleware(lambda _rt: backend, thread_id_for=lambda _rt: "t-1")  # type: ignore[arg-type,return-value]
    sent: list[list[str]] = []

    def handler(request: ToolCallRequest) -> ToolMessage:
        sent.append(request.tool_call["args"]["paths"])
        return ToolMessage(content=UPLOADED, tool_call_id="call-1")

    ledger.wrap_tool_call(_request(["/workspace/projects/card/a.png"]), handler)
    backend.files["/workspace/projects/card/a.png"] = b"A2"
    ledger.wrap_tool_call(_request(["/workspace/projects/card/a.png"]), handler)
    assert len(sent) == 2
