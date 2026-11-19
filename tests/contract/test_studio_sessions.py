"""Studio API journeys on disposable workspaces, including a cold reopen of the database."""

import sqlite3
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from design_agent.config import Settings
from design_agent.runtime import sandbox
from design_agent.surfaces.web import demo
from design_agent.surfaces.web.app import create_app
from design_agent.testing.fakes import folder_binding
from design_agent.testing.scripted_model import reply, tool_call
from tests.unit.test_web_episode import ROOT, lines_of


def start_episode(client: TestClient, body: dict) -> tuple[str, dict]:
    channel = client.get("/api/channels").json()[0]["id"]
    response = client.post(
        f"/api/channels/{channel}/episodes", json={**body, "settings": {"writer": "demo"}}
    )
    response.raise_for_status()
    url = f"/api/episodes/{response.json()['id']}"
    return url, wait_for(client, url, lambda view: view["status"] == "plan")


def wait_for(client: TestClient, url: str, ready: Callable[[dict], Any], timeout: int = 45) -> dict:
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        response = client.get(url)
        response.raise_for_status()
        view = response.json()
        if ready(view):
            return view
        time.sleep(0.1)
    pytest.fail(f"Timed out waiting for {url} (last status: {view.get('status')})")


def test_markdown_transcript_edit_and_thread_survive_reopening_studio(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, workspace_root=tmp_path, sandbox="host")
    source = "# Session test\n\n- Keep the **original** notes.\n"
    request = "Say the opening line in fewer words."
    with TestClient(create_app(ROOT, settings, demo=True)) as client:
        uploaded = client.post(
            "/api/uploads", files={"files": ("brief.md", source, "text/markdown")}
        )
        uploaded.raise_for_status()
        file = uploaded.json()[0]
        url, before = start_episode(client, {"files": [file["id"]]})
        line = next(
            f for f in lines_of(before).values() if not f.get("cues") and len(f["vo"].split()) > 12
        )
        change = {"scope": "line", "target": line["id"], "text": request}
        client.post(f"{url}/ask", json=change).raise_for_status()
        after = wait_for(client, url, lambda v: (v.get("last_change") or {}).get("why") == request)
        revised = lines_of(after)[line["id"]]["vo"]
        assert 0 < len(revised.split()) < len(line["vo"].split())
        thread = before["thread_id"]
        thread_url = f"/api/threads/{thread}"
        client.post(
            f"{thread_url}/messages", json={"text": "Keep this revision.", "to_agent": False}
        ).raise_for_status()
        messages = client.get(thread_url).json()["messages"]
        assert any(m["text"] == "Keep this revision." for m in messages)

    with sqlite3.connect(f"file:{tmp_path}/house/house.sqlite?mode=ro", uri=True) as db:
        assert (
            source.strip()
            in db.execute("SELECT material FROM episodes WHERE id=?", (before["id"],)).fetchone()[0]
        )
        run = db.execute(
            "SELECT answer, state FROM runs WHERE thread_id=? AND instr(prompt, ?) > 0 ORDER BY started_at DESC LIMIT 1",
            (thread, request),
        ).fetchone()
        assert run and run[0] and run[1] == "done"
        assert db.execute(
            "SELECT why FROM history WHERE episode_id=? ORDER BY n DESC LIMIT 1", (before["id"],)
        ).fetchone() == (request,)

    with TestClient(create_app(ROOT, settings, demo=True)) as reopened:
        saved = reopened.get(url).json()
        assert lines_of(saved)[line["id"]]["vo"] == revised
        assert saved["last_change"]["was"][line["id"]] == line["vo"]
        assert reopened.get(thread_url).json()["messages"] == messages
        assert reopened.get(file["url"]).text == source
        assert lines_of(reopened.post(f"{url}/undo").json())[line["id"]]["vo"] == line["vo"]
        assert lines_of(reopened.post(f"{url}/redo").json())[line["id"]]["vo"] == revised


@pytest.mark.render
def test_studio_generates_and_approves_a_playable_motion_graphic(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, workspace_root=tmp_path, sandbox="docker")
    with TestClient(create_app(ROOT, settings, demo=True)) as client:
        url, view = start_episode(client, {"text": "Use the scripted HTTP caching sample."})
        unit = view["units"][0]
        unit_id = unit["id"]
        response = client.post(f"{url}/pictures", json={"units": [unit_id], "level": "rich"})
        response.raise_for_status()

        def picture(v):
            return next(u["picture"] for u in v["units"] if u["id"] == unit_id)

        result = wait_for(
            client,
            url,
            lambda v: picture(v)["status"] == "failed" or picture(v)["clip"],
            timeout=300,
        )
        built = picture(result)
        assert built["status"] == "go", built["failure"]
        assert [s["frame"] for s in built["motion"]["shots"]] == unit["frames"]
        assert set(built["stills"]) == set(unit["frames"])
        for still in built["stills"].values():
            assert client.get(still["url"]).content.startswith(b"\x89PNG")
        clip = client.get(built["clip"]["url"])
        clip.raise_for_status()
        assert clip.headers["content-type"] == "video/mp4" and clip.content[4:8] == b"ftyp"
        approved = client.post(f"{url}/pictures/{unit_id}/go")
        approved.raise_for_status()
        assert picture(approved.json())["status"] == "made"


def test_markdown_file_edit_and_chat_checkpoint_survive_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(_env_file=None, workspace_root=tmp_path, sandbox="host")
    source = "# Draft\n\n- Read the **old** brief.\n- Keep this line.\n"
    path = "/workspace/attachments/brief.md"
    done = "Revised the wording in brief.md."
    recalled = "The previous edit revised brief.md."
    followup = "Which file did we just revise?"

    def model(messages: Sequence[BaseMessage]) -> AIMessage:
        last = messages[-1]
        if isinstance(last, ToolMessage):
            if last.name == "read_file":
                return tool_call(
                    "edit_file",
                    {"file_path": path, "old_string": "**old**", "new_string": "**new**"},
                )
            if last.name == "edit_file":
                return tool_call("upload_files", {"paths": [path]})
            return reply(done)
        if any(followup in str(m.content) for m in messages):
            return reply(
                recalled
                if any(isinstance(m, AIMessage) and m.content == done for m in messages)
                else "No previous edit found."
            )
        return tool_call("read_file", {"file_path": path})

    monkeypatch.setattr(demo, "next_step", model)
    monkeypatch.setattr(
        sandbox, "host_binding", lambda root: folder_binding(tmp_path / "computer", root)
    )
    with TestClient(create_app(ROOT, settings, demo=True)) as client:
        uploaded = client.post(
            "/api/uploads", files={"files": ("brief.md", source, "text/markdown")}
        )
        uploaded.raise_for_status()
        file = uploaded.json()[0]
        channel = client.get("/api/channels").json()[0]["id"]
        request = client.post(
            f"/api/channels/{channel}/messages",
            json={"text": "Replace **old** with **new** in brief.md.", "files": [file["id"]]},
        )
        request.raise_for_status()
        thread = request.json()["thread_id"]
        url = f"/api/threads/{thread}"
        first = wait_for(client, url, lambda v: any(m["text"] == done for m in v["messages"]))
        (delivered,) = first["files"]
        assert client.get(delivered["url"]).text == source.replace("**old**", "**new**")
    with sqlite3.connect(f"file:{tmp_path}/state/threads.sqlite?mode=ro", uri=True) as db:
        assert (
            db.execute("SELECT COUNT(*) FROM checkpoints WHERE thread_id=?", (thread,)).fetchone()[
                0
            ]
            > 0
        )

    with TestClient(create_app(ROOT, settings, demo=True)) as reopened:
        assert reopened.get(url).json()["messages"] == first["messages"]
        assert reopened.get(delivered["url"]).text == source.replace("**old**", "**new**")
        reopened.post(f"{url}/messages", json={"text": followup}).raise_for_status()
        continued = wait_for(
            reopened, url, lambda v: any(m["text"] == recalled for m in v["messages"])
        )
        assert continued["messages"][: len(first["messages"])] == first["messages"]
