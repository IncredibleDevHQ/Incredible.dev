"""The preview a film's final look opens on the thread's computer, reached from the house.

At a film's final look the engine opens HyperFrames Studio on the thread's computer and hands over
`http://localhost:<port>/#project/<name>`: the film to play, in an editor whose edits save to the
project. The sandbox has no network, so that address works only inside it. Here each preview gets
a port of its own on 127.0.0.1, and every connection to it is piped through `docker exec` to the
Studio's port in the container: the whole editor works, websockets too, and the container stays
unreachable from anywhere else. The same port number answers inside the container as well, since
the Studio opens its own captures at the address the browser used. A Studio that stopped with its
idle computer starts again on the next visit. Like the app, these ports are for this machine only:
whoever reaches one can edit the project.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import re
import shlex
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote, unquote

from deepagents.backends.protocol import ExecuteResponse

#: A link to the thread's own computer, with its port and the rest of the address.
LOCAL_LINK = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(\d{2,5})(/[^\s)\]>\"'`]*)?"
)
#: The project a Studio link opens (`#project/<name>`), URL-encoded when its name needs it.
STUDIO_PROJECT = re.compile(r"#project/([^\s?&#/)\]>\"'`]+)")
#: What a project name may hold before it goes into a search on the thread's computer.
PROJECT_NAME = re.compile(r"[A-Za-z0-9._-]{1,80}")
#: The agent's user on the thread's computer.
AGENT_USER = "1000:1000"
#: Pipes one connection between the process's stdin/stdout and a port on the container's loopback.
BRIDGE = (
    "const s=require('net').connect(+process.argv[1],'127.0.0.1');"
    "s.on('connect',()=>{process.stdin.pipe(s);s.pipe(process.stdout)});"
    "s.on('error',()=>process.exit(1));s.on('close',()=>process.exit(0));"
)
#: Listens on the container's loopback at the house's port and passes through to the Studio's.
MIRROR = (
    "const n=require('net'),[to,at]=process.argv.slice(1).map(Number);"
    "n.createServer(c=>{const s=n.connect(to,'127.0.0.1');c.pipe(s);s.pipe(c);"
    "c.on('error',()=>s.destroy());s.on('error',()=>c.destroy())}).listen(at,'127.0.0.1')"
)
CHUNK = 64 * 1024
#: How long a looked-up container name is trusted before the runner is asked again.
SEEN_SECONDS = 60.0
#: How often an open connection keeps its computer from being stopped as idle.
AWAKE_SECONDS = 120.0
#: How long the Studio's side gets to close after the browser hangs up.
CLOSE_SECONDS = 10.0


class PreviewError(RuntimeError):
    """The preview could not be reached; the message says why, in the team's words."""


class Runner(Protocol):
    """What previews need of the Docker sandbox runner."""

    def container_for(self, thread_id: str) -> str: ...

    def exec(
        self, thread_id: str, command: str, *, timeout: int | None = None, root: bool = False
    ) -> ExecuteResponse: ...


@dataclass(frozen=True)
class StudioLink:
    port: int
    project: str


def studio_links(text: str) -> list[StudioLink]:
    """The Studio previews an agent's words hand over: `http://localhost:3002/#project/video`."""
    found: list[StudioLink] = []
    for match in LOCAL_LINK.finditer(text):
        named = STUDIO_PROJECT.search(match.group(2) or "")
        port = int(match.group(1))
        if named and 1024 <= port <= 65535:
            link = StudioLink(port, unquote(named.group(1)))
            if link not in found:
                found.append(link)
    return found


def address(thread_id: str, port: int, project: str = "") -> str:
    """Where the app opens a preview: this server's route, which sends the browser on to it."""
    query = f"?project={quote(project)}" if project else ""
    return f"/api/threads/{thread_id}/preview/{port}{query}"


def docker_bridge(container: str, port: int) -> list[str]:
    return [
        "docker",
        "exec",
        "-i",
        "--user",
        AGENT_USER,
        container,
        "node",
        "-e",
        BRIDGE,
        str(port),
    ]


class Previews:
    """Ports on 127.0.0.1 that reach the previews on the threads' computers."""

    def __init__(
        self, runner: Runner, *, bridge: Callable[[str, int], Sequence[str]] = docker_bridge
    ) -> None:
        self.runner = runner
        self._bridge = bridge
        self._servers: dict[tuple[str, int], asyncio.Server] = {}
        self._seen: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    async def open(self, thread_id: str, port: int, *, project: str = "") -> str:
        """The address of the thread's preview on `port`; a Studio that stopped with its computer
        is started again first."""
        if project and not PROJECT_NAME.fullmatch(project):
            raise PreviewError("That isn't a project on the thread's computer.")
        async with self._lock:
            server = self._servers.get((thread_id, port))
            if server is None:
                server = await asyncio.start_server(
                    functools.partial(self._pipe, thread_id, port), "127.0.0.1", 0
                )
                self._servers[(thread_id, port)] = server
        local = int(server.sockets[0].getsockname()[1])
        try:
            if not await self._answers(thread_id, port):
                if not project:
                    raise PreviewError("Nothing answers there on the thread's computer.")
                await self._restart(thread_id, port, project)
            await self._mirror(thread_id, port, local)
        except (RuntimeError, subprocess.SubprocessError) as error:
            if isinstance(error, PreviewError):
                raise
            raise PreviewError("The thread's computer isn't answering.") from error
        return f"http://127.0.0.1:{local}/" + (f"#project/{quote(project)}" if project else "")

    async def close(self) -> None:
        for server in self._servers.values():
            server.close()
        self._servers.clear()

    async def _answers(self, thread_id: str, port: int) -> bool:
        result = await asyncio.to_thread(
            self.runner.exec,
            thread_id,
            f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 3 http://127.0.0.1:{port}/",
            timeout=20,
        )
        return result.output.strip()[-3:].startswith(("2", "3"))

    async def _restart(self, thread_id: str, port: int, project: str) -> None:
        """Start the project's Studio again on its port, as the agent started it."""
        pattern = shlex.quote(f"*/{project}/hyperframes.json")
        script = (
            f"dir=$(find /workspace/projects -maxdepth 5 -name hyperframes.json -path {pattern} "
            "-printf '%T@ %h\\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-); "
            '[ -n "$dir" ] || exit 3; '
            f'hyperframes preview "$dir" --background --port {port} >/tmp/preview-{port}.log 2>&1; '
            f"for _ in $(seq 60); do curl -s -o /dev/null --max-time 2 http://127.0.0.1:{port}/ "
            "&& exit 0; sleep 0.5; done; exit 4"
        )
        result = await asyncio.to_thread(self.runner.exec, thread_id, script, timeout=120)
        if result.exit_code == 3:
            raise PreviewError(f"The project “{project}” is no longer on the thread's computer.")
        if result.exit_code != 0:
            raise PreviewError("The preview didn't start again. Ask the agent to open it.")

    async def _mirror(self, thread_id: str, port: int, local: int) -> None:
        """The house's port on the container's loopback too, passing through to the Studio's. The
        Studio builds the addresses of its own captures (thumbnails, exports) from the browser's
        and opens them from inside, where only this makes them answer."""
        if local == port:
            return
        script = (
            f"curl -s -o /dev/null --max-time 2 http://127.0.0.1:{local}/ || "
            f"(setsid node -e {shlex.quote(MIRROR)} {port} {local} >/dev/null 2>&1 &)"
        )
        await asyncio.to_thread(self.runner.exec, thread_id, script, timeout=20)

    async def _container(self, thread_id: str) -> str:
        """The thread's container (started if it stopped), asked for at most once a minute."""
        seen = self._seen.get(thread_id)
        if seen is not None and time.monotonic() - seen[1] < SEEN_SECONDS:
            return seen[0]
        name = await asyncio.to_thread(self.runner.container_for, thread_id)
        self._seen[thread_id] = (name, time.monotonic())
        return name

    async def _keep_awake(self, thread_id: str) -> None:
        """A connection held open (the editor's live updates) keeps its computer from being
        stopped as idle."""
        while True:
            await asyncio.sleep(AWAKE_SECONDS)
            with contextlib.suppress(RuntimeError, subprocess.SubprocessError):
                await asyncio.to_thread(self.runner.container_for, thread_id)

    async def _pipe(
        self,
        thread_id: str,
        port: int,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """One browser connection, piped to the Studio's port on the thread's computer."""
        try:
            container = await self._container(thread_id)
            process = await asyncio.create_subprocess_exec(
                *self._bridge(container, port),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except (OSError, RuntimeError, subprocess.SubprocessError):
            writer.close()
            return
        if process.stdin is None or process.stdout is None:  # pragma: no cover - PIPE always set
            writer.close()
            return
        up = asyncio.create_task(_copy(reader, process.stdin))
        down = asyncio.create_task(_copy(process.stdout, writer))
        awake = asyncio.create_task(self._keep_awake(thread_id))
        try:
            done, _ = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
            if down not in done:
                # The browser hung up; the Studio's side closes on its own moments later.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(down), CLOSE_SECONDS)
        finally:
            for task in (up, down, awake):
                task.cancel()
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
            await process.wait()
            writer.close()


async def _copy(source: asyncio.StreamReader, sink: asyncio.StreamWriter) -> None:
    try:
        while data := await source.read(CHUNK):
            sink.write(data)
            await sink.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        with contextlib.suppress(ConnectionError, OSError, RuntimeError):
            sink.close()
