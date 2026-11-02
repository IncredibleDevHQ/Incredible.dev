"""The self-hosted HTTP API: one process runs the agent, its helpers, wake-ups and housekeeping.

Not the LangGraph Agent Server protocol; a small surface for your own tools and the Slack adapter:

- `POST /threads/{thread_id}/messages` `{"text": "..."}` runs one turn and returns the reply, the
  files delivered on the thread so far, and whether background work is still running.
- `GET /threads/{thread_id}/updates?after=N` returns what background work posted since (wake-up
  replies), in order, with a cursor.
- `POST /threads/{thread_id}/attachments` (multipart `files`) puts files in the thread's
  `/workspace/attachments/`; mention them in the next message.
- `GET /threads/{thread_id}/files/{name}` downloads a delivered file.
- `GET /health`.

Every route but `/health` needs `Authorization: Bearer <token>`; `DESIGN_AGENT_API_TOKENS` maps
tokens to callers (`token:caller,...`). A thread belongs to the caller who started it; another
caller gets 404 for it, never its contents. With no tokens configured the server refuses to start.

Durability comes from `runtime/persistence.py` (Postgres with `DATABASE_URL`). At startup the
server sweeps what a restart killed and re-arms check-ins; every 15 minutes it sweeps again.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from design_agent.config import Settings
from design_agent.runtime import maintenance
from design_agent.runtime.local import LocalRuntime, build_local_runtime, final_text
from design_agent.runtime.persistence import open_persistence, workspace_of
from design_agent.tools.mcp import load_mcp_tools, servers_for_runtime
from design_agent.tools.paper import PaperPolicy, admit_paper_tools

_LOGGER = logging.getLogger(__name__)

THREADS = ("design_agent", "api_threads")
UPDATES = ("design_agent", "api_updates")
THREAD_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
MAX_ATTACHMENTS = 10
MAX_ATTACHMENT_BYTES = 200 * 1024 * 1024


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class MessageOut(BaseModel):
    reply: str
    files: list[str]
    working: bool


class Updates(BaseModel):
    updates: list[str]
    cursor: int


@dataclass
class ApiState:
    runtime: LocalRuntime
    store: Any
    tokens: dict[str, str]
    _counters: dict[str, int] = field(default_factory=dict)

    async def record_update(self, thread_id: str, text: str) -> None:
        count = self._counters.get(thread_id)
        if count is None:
            count = len(await self.store.asearch((*UPDATES, thread_id), limit=10_000))
        self._counters[thread_id] = count + 1
        await self.store.aput((*UPDATES, thread_id), f"{count:08d}", {"text": text})


def _caller(request: Request) -> str:
    state: ApiState = request.app.state.api
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token:
        for known, caller in state.tokens.items():
            if hmac.compare_digest(known.encode(), token.encode()):
                return caller
    raise HTTPException(
        status_code=401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"}
    )


async def _owned(request: Request, thread_id: str, caller: str, *, create: bool) -> None:
    if not THREAD_ID.fullmatch(thread_id):
        raise HTTPException(status_code=404, detail="no such thread")
    state: ApiState = request.app.state.api
    item = await state.store.aget(THREADS, thread_id)
    if item is None and create:
        await state.store.aput(THREADS, thread_id, {"owner": caller})
        return
    if item is None or not hmac.compare_digest(str(item.value.get("owner")), caller):
        raise HTTPException(status_code=404, detail="no such thread")


def _files(runtime: LocalRuntime, thread_id: str) -> list[str]:
    folder = runtime.out_dir / thread_id
    return sorted(p.name for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []


def create_app(
    project_root: Path,
    settings: Settings | None = None,
    *,
    build: Callable[..., LocalRuntime] = build_local_runtime,
) -> FastAPI:
    settings = settings or Settings()
    tokens = settings.api_token_map()
    if not tokens:
        raise RuntimeError(
            "DESIGN_AGENT_API_TOKENS is empty: the API refuses to serve without callers"
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        servers = servers_for_runtime(project_root, settings, "self_hosted")
        loaded = await load_mcp_tools(servers)
        servers = [s for s in servers if s.name not in loaded.failed]
        loaded.tools = admit_paper_tools(loaded.tools, PaperPolicy.from_settings(settings))
        async with open_persistence(settings, workspace_of(settings, project_root)) as (
            checkpointer,
            store,
        ):
            holder: list[ApiState] = []

            def posted(thread_id: str, text: str) -> None:
                asyncio.get_running_loop().create_task(holder[0].record_update(thread_id, text))

            runtime = build(
                settings,
                project_root,
                checkpointer=checkpointer,
                store=store,
                replies=posted,
                mcp_servers=servers,
                mcp_tools=loaded.tools,
            )
            holder.append(ApiState(runtime=runtime, store=store, tokens=tokens))
            app.state.api = holder[0]
            await maintenance.start(runtime, store)
            keeper = asyncio.get_running_loop().create_task(
                maintenance.run(runtime, store), name="maintenance"
            )
            try:
                yield
            finally:
                keeper.cancel()
                await runtime.services.aclose()
                if runtime.binding.runner is not None:
                    runtime.binding.runner.stop_all()

    app = FastAPI(title="Design Agent", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        state: ApiState | None = getattr(request.app.state, "api", None)
        return {"ok": state is not None, "sandbox": state.runtime.binding.name if state else None}

    @app.post("/threads/{thread_id}/messages", response_model=MessageOut)
    async def post_message(
        thread_id: str, body: MessageIn, request: Request, caller: str = Depends(_caller)
    ) -> MessageOut:
        await _owned(request, thread_id, caller, create=True)
        state: ApiState = request.app.state.api
        added = await state.runtime.ask(body.text, thread_id=thread_id)
        return MessageOut(
            reply=final_text(added),
            files=_files(state.runtime, thread_id),
            working=state.runtime.busy(),
        )

    @app.post("/threads/{thread_id}/attachments")
    async def attach(
        thread_id: str,
        request: Request,
        files: list[UploadFile] = File(...),  # noqa: B008 - FastAPI's declaration style
        caller: str = Depends(_caller),
    ) -> dict[str, list[str]]:
        await _owned(request, thread_id, caller, create=True)
        if len(files) > MAX_ATTACHMENTS:
            raise HTTPException(status_code=413, detail=f"at most {MAX_ATTACHMENTS} files")
        loaded: list[tuple[str, bytes]] = []
        for upload in files:
            content = await upload.read(MAX_ATTACHMENT_BYTES + 1)
            if len(content) > MAX_ATTACHMENT_BYTES:
                raise HTTPException(status_code=413, detail="a file is over 200 MiB")
            name = Path(upload.filename or "attachment").name
            if not THREAD_ID.fullmatch(name):
                raise HTTPException(
                    status_code=400, detail="file names are letters, digits, dot, dash, underscore"
                )
            loaded.append((name, content))
        state: ApiState = request.app.state.api
        return {"paths": await state.runtime.attach(thread_id, loaded)}

    @app.get("/threads/{thread_id}/updates", response_model=Updates)
    async def updates(
        thread_id: str, request: Request, after: int = 0, caller: str = Depends(_caller)
    ) -> Updates:
        await _owned(request, thread_id, caller, create=False)
        state: ApiState = request.app.state.api
        items = sorted(
            await state.store.asearch((*UPDATES, thread_id), limit=10_000), key=lambda i: i.key
        )
        fresh = [str(i.value.get("text", "")) for i in items[after:]]
        return Updates(updates=fresh, cursor=len(items))

    @app.get("/threads/{thread_id}/files/{name}")
    async def download(
        thread_id: str, name: str, request: Request, caller: str = Depends(_caller)
    ) -> FileResponse:
        await _owned(request, thread_id, caller, create=False)
        state: ApiState = request.app.state.api
        folder = (state.runtime.out_dir / thread_id).resolve()
        path = (folder / name).resolve()
        if path.parent != folder or not path.is_file():
            raise HTTPException(status_code=404, detail="no such file")
        return FileResponse(path, filename=path.name)

    return app
