"""The self-hosted API on the real graph: callers, ownership, background updates, downloads."""

from __future__ import annotations

import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from design_agent.config import Settings
from design_agent.harness import inbox as inbox_module
from design_agent.harness.tasks import REGISTRY
from design_agent.runtime.local import build_local_runtime
from design_agent.surfaces.api.app import create_app
from design_agent.testing.fakes import folder_binding
from design_agent.testing.scripted_model import (
    RespondingChatModel,
    ScriptedChatModel,
    reply,
    tool_call,
)
from tests.contract.test_background_contracts import latest_human

ROOT = Path(__file__).resolve().parents[2]
A = {"Authorization": "Bearer token-alice-0123456789"}
B = {"Authorization": "Bearer token-bob-0123456789"}


@pytest.fixture(autouse=True)
def fast(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(inbox_module, "COALESCE_SECONDS", 0.05)
    yield
    REGISTRY.clear()


def lead_turn(messages: Sequence[BaseMessage]) -> AIMessage:
    asked = latest_human(messages)
    last = messages[-1]
    if isinstance(last, ToolMessage):
        if last.name == "start_task":
            return reply("Grabbing frames; about a minute.")
        if last.name == "write_file":
            return tool_call("upload_files", {"paths": ["/workspace/projects/p/card.txt"]})
        return reply("Here is the card.")
    if asked.startswith("Grab"):
        return tool_call(
            "start_task", {"description": "Grab frames.", "effort": "low", "label": "grabs"}
        )
    if asked.startswith("Make"):
        return tool_call(
            "write_file", {"file_path": "/workspace/projects/p/card.txt", "content": "card"}
        )
    if "grabs" in asked:
        return reply("The frame grabs are ready.")
    return reply("ok")


def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,
        workspace_root=tmp_path / "ws",
        api_tokens="token-alice-0123456789:alice,token-bob-0123456789:bob",
    )  # type: ignore[call-arg]

    def build(settings_: Settings, root: Path, **kwargs: Any) -> Any:
        helper = ScriptedChatModel(steps=[lambda _m: reply("Three frames saved.")])
        return build_local_runtime(
            settings_,
            root,
            model=RespondingChatModel(respond=lead_turn),
            role_models={"low": helper},
            binding=folder_binding(tmp_path / "sb", ROOT),
            **kwargs,
        )

    return TestClient(create_app(ROOT, settings, build=build))


def test_callers_own_their_threads_and_get_background_updates(tmp_path: Path) -> None:
    with client(tmp_path) as api:
        assert (
            api.post("/threads/t1/messages", json={"text": "Grab three frames."}).status_code == 401
        )
        first = api.post("/threads/t1/messages", json={"text": "Grab three frames."}, headers=A)
        assert (
            first.status_code == 200 and first.json()["reply"] == "Grabbing frames; about a minute."
        )
        assert api.get("/threads/t1/updates", headers=B).status_code == 404, (
            "another caller's thread"
        )
        assert api.post("/threads/t1/messages", json={"text": "hi"}, headers=B).status_code == 404
        updates: list[str] = []
        for _ in range(200):
            body = api.get("/threads/t1/updates", headers=A).json()
            updates = body["updates"]
            if updates:
                break
            time.sleep(0.02)
        assert updates == ["The frame grabs are ready."]
        assert (
            api.get(f"/threads/t1/updates?after={body['cursor']}", headers=A).json()["updates"]
            == []
        )


def test_delivered_files_download_for_their_owner_only(tmp_path: Path) -> None:
    with client(tmp_path) as api:
        made = api.post("/threads/t2/messages", json={"text": "Make the card."}, headers=A).json()
        assert made["reply"] == "Here is the card." and made["files"] == ["card.txt"]
        assert api.get("/threads/t2/files/card.txt", headers=A).content == b"card"
        assert api.get("/threads/t2/files/card.txt", headers=B).status_code == 404
        assert api.get("/threads/t2/files/..%2F..%2Fsecrets", headers=A).status_code == 404


def test_the_api_refuses_to_start_without_callers(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="DESIGN_AGENT_API_TOKENS"):
        create_app(ROOT, Settings(_env_file=None, workspace_root=tmp_path))  # type: ignore[call-arg]


def test_attachments_land_in_the_threads_sandbox(tmp_path: Path) -> None:
    with client(tmp_path) as api:
        sent = api.post(
            "/threads/t3/attachments",
            files={"files": ("layout.png", b"png-bytes", "image/png")},
            headers=A,
        )
        assert sent.status_code == 200 and sent.json() == {
            "paths": ["/workspace/attachments/layout.png"]
        }
        assert (tmp_path / "sb/workspace/attachments/layout.png").read_bytes() == b"png-bytes"
        assert (
            api.post(
                "/threads/t3/attachments", files={"files": ("x.png", b"x", "image/png")}, headers=B
            ).status_code
            == 404
        )
