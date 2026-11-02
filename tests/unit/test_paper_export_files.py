"""`take_exports`: read back only the files a Paper export just wrote, and leave the rest alone."""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

from fastmcp.tools.base import ToolResult
from mcp.types import ImageContent, TextContent

from design_agent.paper_bridge.app import BridgePolicy
from design_agent.tools.paper import PaperPolicy, take_exports

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _answer(*paths: Path) -> str:
    return json.dumps(
        {"exports": [{"nodeId": f"N-{i}", "filePath": str(p)} for i, p in enumerate(paths)]}
    )


def test_it_takes_the_fresh_export_and_removes_it_from_downloads(tmp_path: Path) -> None:
    fresh = tmp_path / "Frame 1.png"
    fresh.write_bytes(PNG)
    taken = take_exports([_answer(fresh)], since=time.time() - 5, folder=tmp_path)
    assert [(f.data, f.mime_type) for f in taken] == [(PNG, "image/png")]
    assert not fresh.exists()


def test_it_leaves_alone_what_this_call_did_not_write(tmp_path: Path) -> None:
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    old = downloads / "old.png"
    old.write_bytes(PNG)
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    notes = downloads / "notes.txt"
    notes.write_text("mine")
    elsewhere = tmp_path / "elsewhere.png"
    elsewhere.write_bytes(PNG)
    answer = _answer(old, notes, elsewhere, downloads / "missing.png")
    assert take_exports([answer, "not json", "{}"], since=time.time() - 5, folder=downloads) == []
    assert old.exists() and notes.exists() and elsewhere.exists()


def test_the_bridge_returns_the_bytes_instead_of_paths_on_its_machine(tmp_path: Path) -> None:
    fresh = tmp_path / "frame.png"
    fresh.write_bytes(PNG)
    bridge = BridgePolicy(PaperPolicy(drafts_file_id="01TESTDRAFT0000"), exports_folder=tmp_path)
    result = ToolResult(
        content=[
            TextContent(type="text", text='{"file": {"id": "x"}}'),
            TextContent(type="text", text=_answer(fresh)),
        ]
    )
    shown = bridge._with_exports("export", result, time.time() - 5)
    images = [b for b in shown.content if isinstance(b, ImageContent)]
    assert [base64.b64decode(b.data) for b in images] == [PNG] and images[0].mimeType == "image/png"
    assert not any("filePath" in getattr(b, "text", "") for b in shown.content)
    assert not fresh.exists()
    assert bridge._with_exports("get_screenshot", result, 0.0) is result
