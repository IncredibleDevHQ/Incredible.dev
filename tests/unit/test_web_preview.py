"""A film's final look on the canvas: the Studio preview the agent hands over goes on the film's
card with its proof frames, the team signs the render off from there, and the house reaches the
preview on the thread's computer through a local port."""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest
from deepagents.backends.protocol import ExecuteResponse

from design_agent.surfaces.web.agent import AgentHost
from design_agent.surfaces.web.preview import PreviewError, Previews, StudioLink, studio_links
from design_agent.surfaces.web.store import AGENT_ID, Store
from design_agent.tools.delivery import DeliveredFile
from tests.unit.test_web_assets import MP4, _board, _by_title, _channel, host
from tests.unit.test_web_surface import PNG, FakeRuntime

__all__ = ["host"]  # the fixture, shared with the asset tests

READY = "The teaser is ready in the [editable preview](http://localhost:3002/#project/video)."
SHEETS = [f"/workspace/projects/t/video/review/final-proof/contact-sheet-{n}.jpg" for n in (1, 2)]


def test_studio_links_are_read_from_the_agents_words() -> None:
    assert studio_links(READY) == [StudioLink(3002, "video")]
    assert studio_links(
        "Open http://127.0.0.1:3017/#project/my%20film or http://localhost:3017/#project/my%20film"
    ) == [StudioLink(3017, "my film")]
    assert (
        studio_links("Player: http://localhost:3003 and https://example.com:3002/#project/x") == []
    )
    assert studio_links("http://localhost:80/#project/x") == []


async def test_a_preview_puts_the_film_up_for_review_with_its_proofs(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    # The live Launch kit: the storyboard signed off, the teaser built, its proof sheets attached.
    agent, _ = host
    message = agent.place_template(_channel(agent), "launch-kit", by="you", text="Our note.")
    await asyncio.sleep(0.05)
    thread = message["thread_id"]
    board_id = await _board(agent, thread)
    agent.send_board(board_id, by="you", approve=True)
    await asyncio.sleep(0.05)
    teaser = _by_title(agent, thread)["Teaser"]
    agent.mark_asset(thread, teaser["id"], status="making", note="")
    agent._delivered[thread] = []
    agent.uploading(thread, SHEETS)
    agent.deliver(thread, [DeliveredFile(Path(p).name, PNG + p.encode()) for p in SHEETS])
    sheets = list(agent._delivered[thread])

    agent._reply(thread, READY)
    agent._settle_status(thread)

    assets = _by_title(agent, thread)
    film = assets["Teaser"]
    assert film["status"] == "review"
    assert film["preview"] == {"port": 3002, "project": "video", "proofs": sheets}
    assert not {f["id"] for f in assets["Storyboard"]["files"]} & set(sheets)
    view = agent.asset_view(film)["preview"]
    assert view["url"] == f"/api/threads/{thread}/preview/3002?project=video"
    assert [f["id"] for f in view["proofs"]] == sheets
    [task] = agent.canvas_view(_channel(agent))
    assert task["files"] == []
    assert agent.store.thread(thread)["status"] == "needs_you"  # type: ignore[index]


def _older_thread(agent: AgentHost, *, rendered: bool = False) -> tuple[str, str, list[str]]:
    """A thread from before the canvas showed previews: a signed-off storyboard, a "yes", then
    the preview with its proof sheets (and, if `rendered`, the film after it)."""
    channel = _channel(agent)
    thread = agent.store.add_thread(
        thread_id="th_old", channel_id=channel, task=True, title="Old", kind="", by="you"
    )["id"]
    agent.store.add_board(
        {
            "thread_id": thread,
            "project": "t",
            "title": "Storyboard",
            "kind": "storyboard",
            "version": 1,
            "status": "approved",
        }
    )
    board_sheet = agent.save_file(thread, "board.png", PNG, origin="delivered")
    proofs = [
        agent.save_file(thread, Path(p).name, PNG + p.encode(), origin="delivered") for p in SHEETS
    ]

    def say(author: str, text: str, files: list[dict[str, object]]) -> None:
        agent.store.add_message(
            channel_id=channel,
            thread_id=thread,
            author_id=author,
            kind="agent" if author == AGENT_ID else "person",
            text=text,
            data={"files": files},
        )

    say(AGENT_ID, "The storyboard is up.", [agent.file_view(board_sheet)])
    say("you", "yes", [])
    say(AGENT_ID, READY, [agent.file_view(p) for p in proofs])
    if rendered:
        film = agent.save_file(thread, "teaser.mp4", MP4, origin="delivered")
        say(AGENT_ID, "Here it is.", [agent.file_view(film)])
    return thread, board_sheet["id"], [p["id"] for p in proofs]


async def test_an_older_preview_gets_its_film_once_and_its_sign_off_renders_it(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, runtime = host
    thread, board_sheet, proofs = _older_thread(agent)
    agent.restore()
    agent.restore()

    board, film = agent.store.assets(thread)
    assert [f["id"] for f in board["files"]] == [board_sheet]
    assert (film["kind"], film["title"], film["status"]) == ("video", "Video", "review")
    assert film["sources"] == [board["id"]] and film["preview"]["proofs"] == proofs
    assert agent.store.thread(thread)["status"] == "needs_you"  # type: ignore[index]

    said = agent.approve_film(film["id"], by="you")
    await asyncio.sleep(0.05)
    assert said["text"] == "Approved the preview of “Video”. Render it."
    assert agent.store.asset(film["id"])["status"] == "making"  # type: ignore[index]
    assert runtime.asked[-1][0] == thread
    with pytest.raises(KeyError):
        agent.approve_film(board["id"], by="you")


def test_a_film_rendered_after_its_preview_keeps_its_card(
    host: tuple[AgentHost, FakeRuntime],
) -> None:
    agent, _ = host
    thread, _, _ = _older_thread(agent, rendered=True)
    agent.restore()
    assert not any(a["preview"] for a in agent.store.assets(thread))


def test_an_older_store_gains_the_preview_column(tmp_path: Path) -> None:
    path = tmp_path / "house.sqlite"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE assets (id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, kind TEXT NOT NULL,"
            " title TEXT NOT NULL, brief TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,"
            " sources TEXT NOT NULL DEFAULT '[]', gate INTEGER NOT NULL DEFAULT 0,"
            " board_id TEXT NOT NULL DEFAULT '', files TEXT NOT NULL DEFAULT '[]',"
            " note TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL,"
            " template TEXT NOT NULL DEFAULT '', added_by TEXT NOT NULL, created_at REAL NOT NULL,"
            " updated_at REAL NOT NULL)"
        )
        db.execute(
            "INSERT INTO assets (id, thread_id, kind, title, status, position, added_by, "
            "created_at, updated_at) VALUES ('as_1', 'th', 'video', 'Teaser', 'making', 0, 'you', "
            "0, 0)"
        )
    store = Store(path)
    assert store.asset("as_1")["preview"] == {}  # type: ignore[index]


# -- reaching the preview on the thread's computer ------------------------------------------------

#: Stands in for the container's bridge: stdin/stdout piped to a port, as `node -e BRIDGE` does.
PIPE = """
import socket, sys, threading
s = socket.create_connection(("127.0.0.1", int(sys.argv[1])))
def up():
    while data := sys.stdin.buffer.read1(65536):
        s.sendall(data)
    s.shutdown(socket.SHUT_WR)
threading.Thread(target=up, daemon=True).start()
while data := s.recv(65536):
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()
"""


class FakeRunner:
    def __init__(self, *answers: ExecuteResponse) -> None:
        self.answers = list(answers)
        self.commands: list[str] = []

    def container_for(self, thread_id: str) -> str:
        return f"box-{thread_id}"

    def exec(
        self, thread_id: str, command: str, *, timeout: int | None = None, root: bool = False
    ) -> ExecuteResponse:
        self.commands.append(command)
        return self.answers.pop(0)


def _answer(output: str, code: int = 0) -> ExecuteResponse:
    return ExecuteResponse(output=output, exit_code=code, truncated=False)


async def test_a_preview_port_pipes_each_connection_to_the_studio() -> None:
    async def studio(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await reader.readuntil(b"\r\n\r\n")
        body = request.split(b" ")[1]
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(studio, "127.0.0.1", 0)
    studio_port = server.sockets[0].getsockname()[1]
    runner = FakeRunner(*[_answer("200"), _answer("")] * 2)
    previews = Previews(
        runner, bridge=lambda _box, _port: [sys.executable, "-c", PIPE, str(studio_port)]
    )
    try:
        url = await previews.open("th_1", 3002, project="video")
        assert url.endswith("/#project/video") and url.startswith("http://127.0.0.1:")
        port = int(url.split(":")[2].split("/")[0])
        # The same port answers inside the container, for the Studio's own captures.
        assert f"{3002} {port}" in runner.commands[1] and "setsid node" in runner.commands[1]
        for path in (b"/", b"/assets/index.js"):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET %s HTTP/1.1\r\nHost: x\r\n\r\n" % path)
            await writer.drain()
            reply = await asyncio.wait_for(reader.read(), 10)
            writer.close()
            assert reply.startswith(b"HTTP/1.1 200 OK") and reply.endswith(path)
        assert await previews.open("th_1", 3002, project="video") == url  # one port per preview
    finally:
        await previews.close()
        server.close()


async def test_a_stopped_studio_starts_again_and_a_lost_one_says_so() -> None:
    runner = FakeRunner(_answer("000"), _answer(""), _answer(""))
    started = Previews(runner)
    lost = Previews(FakeRunner(_answer("000"), _answer("", 3)))
    silent = Previews(FakeRunner(_answer("000")))
    try:
        await started.open("th_1", 3002, project="video")
        assert "-path '*/video/hyperframes.json'" in runner.commands[1]
        assert 'hyperframes preview "$dir" --background --port 3002' in runner.commands[1]
        with pytest.raises(PreviewError, match="no longer on the thread's computer"):
            await lost.open("th_1", 3002, project="video")
        with pytest.raises(PreviewError, match="Nothing answers"):
            await silent.open("th_1", 3003)
        with pytest.raises(PreviewError, match="isn't a project"):
            await started.open("th_1", 3002, project="a b;rm")
    finally:
        for previews in (started, lost, silent):
            await previews.close()
