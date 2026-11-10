"""The web app's server: our channels and canvas in front of the design agent's engine.

One process runs the agent, its helpers, watches, wake-ups and housekeeping (the self-hosted
runtime), the store of channels, messages and boards, and this API:

- `GET /api/session`, `GET /api/channels`, `POST /api/channels`
- `GET /api/channels/{id}/messages` (each thread's first message, with its thread),
  `POST /api/channels/{id}/messages` (a new thread; a task when it is for the agent)
- `GET /api/threads/{id}`, `POST /api/threads/{id}/messages`, `POST /api/threads/{id}/stop`,
  `POST /api/threads/{id}/work/{work_id}/cancel`
- `POST /api/uploads`, `GET /api/files/{id}`
- the canvas: `GET /api/channels/{id}/canvas`, `GET /api/boards/{id}`,
  `POST /api/frames/{id}/comments`, `POST /api/comments/{id}/resolve`,
  `POST /api/frames/{id}/verdict`, `POST /api/boards/{id}/send`
- what the canvas can ask for: `GET /api/catalog` (the kinds of work and the templates),
  `POST /api/threads/{id}/assets` (one more asset in a task),
  `POST /api/channels/{id}/templates` (a template, as a new task or onto a finished asset)
- links in what someone sends the agent (a new task, a template's material, a reply) are read
  first and go with it as files (`pages.py`): a page as its article's words, a PDF as itself
- a film's final look: `GET /api/threads/{id}/preview/{port}` (its Studio on the thread's
  computer, through a local port: `preview.py`), `POST /api/assets/{id}/render` (signed off);
  a draft's sign-off: `POST /api/assets/{id}/approve`
- research on this computer (`research_desk.py`): `GET /api/research` (the agents and the
  repositories), `POST /api/channels/{id}/research` (a research frame and its first question),
  `POST /api/research/{id}/conversations` (another, or a branch from a passage),
  `POST /api/research/{id}/notes`, `PATCH /api/notes/{id}`, `DELETE /api/notes/{id}`; a
  conversation's follow-ups and stops go through its thread's routes
- what the agent works with: `GET /api/brand` (a channel's with `?channel=`), `GET /api/skills`,
  `GET /api/computer`
- brands (`brands.py`): `GET /api/brands`, `POST /api/brands` (read one from a website),
  `GET /api/brands/{slug}`, `GET /api/brands/{slug}/files/{name}`, `PATCH /api/channels/{id}`
  (the brand a channel wears)
- `GET /api/stream`: every change, live (server-sent events)

It binds to 127.0.0.1. Who is asking comes from the `X-Person` header: this is a local, single-
workspace build; put real sign-in in front of it before anyone else reaches it.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import json
import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from design_agent.config import SAMPLE_BRAND, Settings
from design_agent.runtime import maintenance
from design_agent.runtime.local import build_local_runtime
from design_agent.runtime.persistence import open_persistence, workspace_of
from design_agent.surfaces.web.agent import AgentHost
from design_agent.surfaces.web.brands import BrandShelf, brand_view
from design_agent.surfaces.web.catalog import catalog_view
from design_agent.surfaces.web.hub import Hub
from design_agent.surfaces.web.presenter import WebDelivery, WebPresenter
from design_agent.surfaces.web.preview import PreviewError
from design_agent.surfaces.web.site_brand import SiteBrandError
from design_agent.surfaces.web.store import CONVERSATION, Store
from design_agent.tools.mcp import load_mcp_tools, servers_for_runtime

MAX_UPLOADS = 10
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
PING_SECONDS = 15.0


class ChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9][a-z0-9-]*$")
    topic: str = Field(default="", max_length=200)


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    to_agent: bool = True
    files: list[str] = Field(default_factory=list, max_length=MAX_UPLOADS)
    kind: str = Field(default="", max_length=40)
    #: The question (an agent message) this message answers from its buttons, if any.
    answers: str = Field(default="", max_length=64)


class CommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=4_000)
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    parent_id: str = ""


class ResolveIn(BaseModel):
    resolved: bool = True


class VerdictIn(BaseModel):
    verdict: str = Field(pattern=r"^(approved|changes|)$")


class SendIn(BaseModel):
    approve: bool


class PickIn(BaseModel):
    frame_id: str
    reason: str = Field(default="", max_length=2_000)


class AssetIn(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    #: The assets in the task it is made from; none means what the task started from.
    sources: list[str] = Field(default_factory=list, max_length=8)
    note: str = Field(default="", max_length=4_000)


class TemplateIn(BaseModel):
    template: str = Field(min_length=1, max_length=60)
    #: A link or notes to start from (with or without files), or a note when it starts from an
    #: asset already on the canvas.
    text: str = Field(default="", max_length=20_000)
    files: list[str] = Field(default_factory=list, max_length=MAX_UPLOADS)
    from_asset: str = Field(default="", max_length=64)
    #: A research frame whose notes it is made from, in that frame.
    from_frame: str = Field(default="", max_length=64)


AGENTS = r"^(claude|codex|kimi)$"


class ResearchIn(BaseModel):
    repo: str = Field(min_length=1, max_length=1_024)
    harness: str = Field(pattern=AGENTS)
    question: str = Field(min_length=1, max_length=8_000)


class QuestionIn(BaseModel):
    question: str = Field(min_length=1, max_length=8_000)
    harness: str = Field(default="", pattern=r"^(claude|codex|kimi|)$")
    #: The conversation it branches from, and the passage of that one's answer it starts on.
    parent: str = Field(default="", max_length=64)
    quote: str = Field(default="", max_length=4_000)


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=8_000)
    conversation_id: str = Field(default="", max_length=64)
    message_id: str = Field(default="", max_length=64)


class NoteEditIn(BaseModel):
    text: str = Field(min_length=1, max_length=8_000)


class BrandReadIn(BaseModel):
    url: str = Field(min_length=3, max_length=2_000)
    #: A channel that wears the brand once it is read.
    channel: str = Field(default="", max_length=64)


class ChannelBrandIn(BaseModel):
    brand: str = Field(min_length=1, max_length=60)


def create_app(
    project_root: Path, settings: Settings | None = None, *, demo: bool = False
) -> FastAPI:
    settings = settings or Settings()
    if demo:
        # The demo's scripted lead poses in the sample brand's tokens, whatever pack is installed.
        settings = settings.model_copy(update={"brand_path": SAMPLE_BRAND})
    workspace = workspace_of(settings, project_root)
    data_dir = workspace / "house"
    store = Store(data_dir / "house.sqlite")
    hub = Hub()
    host = AgentHost(settings=settings, store=store, hub=hub, data_dir=data_dir, demo=demo)
    shelf = BrandShelf(
        store=store, hub=hub, settings=settings, project_root=project_root, data_dir=data_dir
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001 - FastAPI's signature
        servers = servers_for_runtime(project_root, settings, "self_hosted")
        loaded = await load_mcp_tools(servers)
        servers = [s for s in servers if s.name not in loaded.failed]
        model = None
        if demo:
            from design_agent.surfaces.web.demo import DemoDirector

            model = DemoDirector()
        async with open_persistence(settings, workspace) as (checkpointer, lg_store):
            runtime = build_local_runtime(
                settings,
                project_root,
                model=model,
                out_dir=data_dir / "out",
                replies=host.wake_reply,
                checkpointer=checkpointer,
                store=lg_store,
                mcp_servers=servers,
                mcp_tools=loaded.tools,
                presenter=WebPresenter(host),
                surface="web",
                delivery=WebDelivery(host),
                brand_for=shelf.brand_for,
            )
            host.attach_runtime(runtime)
            await maintenance.start(runtime, lg_store)
            keeper = asyncio.get_running_loop().create_task(
                maintenance.run(runtime, lg_store), name="maintenance"
            )
            try:
                yield
            finally:
                keeper.cancel()
                await shelf.close()
                await host.close()
                await runtime.services.aclose()
                if runtime.binding.runner is not None:
                    runtime.binding.runner.stop_all()
                store.close()

    app = FastAPI(title="Creative House", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.host = host

    def person(x_person: str = Header(default="you")) -> str:
        if store.person(x_person) is None or x_person == "agent":
            raise HTTPException(status_code=403, detail="unknown person")
        return x_person

    def thread_or_404(thread_id: str) -> dict[str, Any]:
        thread = store.thread(thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail="no such thread")
        return thread

    async def linked(text: str, me: str) -> list[str]:
        """The pages and PDFs linked in what someone sends the agent, read and kept as files."""
        try:
            return await host.read_links(text, by=me)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    # -- the workspace -----------------------------------------------------------------------

    @app.get("/api/session")
    async def session(me: str = Depends(person)) -> dict[str, Any]:
        runtime = host.runtime
        return {
            "me": me,
            "people": store.people(),
            "agent": {"mark": host.mark, "model": "demo" if demo else str(settings.lead_model())},
            "demo": demo,
            "sandbox": runtime.binding.name if runtime else None,
        }

    @app.get("/api/channels")
    async def channels(me: str = Depends(person)) -> list[dict[str, Any]]:  # noqa: ARG001
        out = []
        for channel in store.channels():
            threads = store.threads(channel["id"])
            out.append(
                {
                    **channel,
                    "working": sum(1 for t in threads if t["status"] == "working"),
                    "needs_you": sum(1 for t in threads if t["status"] == "needs_you"),
                }
            )
        return out

    @app.post("/api/channels")
    async def add_channel(body: ChannelIn, me: str = Depends(person)) -> dict[str, Any]:  # noqa: ARG001
        if any(c["name"] == body.name for c in store.channels()):
            raise HTTPException(status_code=409, detail=f"There is already a #{body.name}.")
        channel = store.add_channel(body.name, body.topic)
        hub.publish("channel.created", channel=channel)
        return channel

    @app.get("/api/channels/{channel_id}/messages")
    async def channel_messages(channel_id: str, me: str = Depends(person)) -> dict[str, Any]:  # noqa: ARG001
        if store.channel(channel_id) is None:
            raise HTTPException(status_code=404, detail="no such channel")
        threads = {t["id"]: host.thread_view(t) for t in store.threads(channel_id)}
        counts = store.reply_counts(channel_id)
        return {
            "roots": store.roots(channel_id),
            "threads": threads,
            "replies": counts,
        }

    @app.post("/api/channels/{channel_id}/messages")
    async def new_thread(
        channel_id: str, body: MessageIn, me: str = Depends(person)
    ) -> dict[str, Any]:
        if store.channel(channel_id) is None:
            raise HTTPException(status_code=404, detail="no such channel")
        read = await linked(body.text, me) if body.to_agent else []
        return host.post(
            channel_id=channel_id,
            author_id=me,
            text=body.text,
            to_agent=body.to_agent,
            file_ids=[*body.files, *read],
            kind=body.kind,
        )

    # -- threads -----------------------------------------------------------------------------

    @app.get("/api/threads/{thread_id}")
    async def thread(thread_id: str, me: str = Depends(person)) -> dict[str, Any]:  # noqa: ARG001
        found = thread_or_404(thread_id)
        return {
            "thread": host.thread_view(found),
            "messages": store.messages(thread_id),
            "work": store.work(thread_id),
            "boards": [host.board_view(b["id"]) for b in store.boards(thread_id)],
            "files": [host.file_view(f) for f in store.files(thread_id, "delivered")],
            "assets": [host.asset_view(a) for a in store.assets(thread_id)],
            "conversation": store.conversation(thread_id),
        }

    @app.post("/api/threads/{thread_id}/messages")
    async def reply(thread_id: str, body: MessageIn, me: str = Depends(person)) -> dict[str, Any]:
        found = thread_or_404(thread_id)
        if body.answers:
            host.answered(body.answers, by=me, text=body.text)
        asks = body.to_agent and found["task"] and found["kind"] != CONVERSATION
        read = await linked(body.text, me) if asks else []
        try:
            return host.post(
                channel_id=found["channel_id"],
                author_id=me,
                text=body.text,
                to_agent=body.to_agent,
                file_ids=[*body.files, *read],
                thread_id=thread_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.post("/api/threads/{thread_id}/stop")
    async def stop(thread_id: str, me: str = Depends(person)) -> dict[str, bool]:  # noqa: ARG001
        thread_or_404(thread_id)
        host.stop(thread_id)
        return {"ok": True}

    @app.post("/api/threads/{thread_id}/work/{work_id}/cancel")
    async def cancel(thread_id: str, work_id: str, me: str = Depends(person)) -> dict[str, str]:  # noqa: ARG001
        thread_or_404(thread_id)
        return {"said": host.cancel_work(thread_id, work_id)}

    @app.get("/api/threads/{thread_id}/folder")
    async def folder(thread_id: str, me: str = Depends(person)) -> list[dict[str, Any]]:  # noqa: ARG001
        found = thread_or_404(thread_id)
        if not found["task"]:
            return []
        return await asyncio.to_thread(host.folder, thread_id)

    @app.get("/api/threads/{thread_id}/folder/file")
    async def folder_file(thread_id: str, path: str) -> Response:
        thread_or_404(thread_id)
        content = await asyncio.to_thread(host.folder_file, thread_id, path)
        if content is None:
            raise HTTPException(status_code=404, detail="no such file")
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if mime == "text/html":
            # Shown as source, never run in the app's origin.
            mime = "text/plain"
        return Response(content, media_type=mime, headers={"X-Content-Type-Options": "nosniff"})

    # -- files -------------------------------------------------------------------------------

    @app.post("/api/uploads")
    async def uploads(
        files: list[UploadFile] = File(...),  # noqa: B008 - FastAPI's declaration style
        me: str = Depends(person),
    ) -> list[dict[str, Any]]:
        if len(files) > MAX_UPLOADS:
            raise HTTPException(status_code=413, detail=f"at most {MAX_UPLOADS} files")
        out = []
        for upload in files:
            content = await upload.read(MAX_UPLOAD_BYTES + 1)
            if len(content) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="a file is over 200 MiB")
            row = host.save_file(
                "", upload.filename or "attachment", content, origin="upload", author=me
            )
            out.append(host.file_view(row))
        return out

    @app.get("/api/files/{file_id}")
    async def file(file_id: str) -> FileResponse:
        row = store.file(file_id)
        if row is None:
            raise HTTPException(status_code=404, detail="no such file")
        path = (host.files_dir / row["rel_path"]).resolve()
        if host.files_dir.resolve() not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="no such file")
        return FileResponse(path, media_type=row["mime"], filename=row["name"])

    # -- the canvas --------------------------------------------------------------------------

    @app.get("/api/channels/{channel_id}/canvas")
    async def canvas(channel_id: str, me: str = Depends(person)) -> list[dict[str, Any]]:  # noqa: ARG001
        if store.channel(channel_id) is None:
            raise HTTPException(status_code=404, detail="no such channel")
        return host.canvas_view(channel_id)

    @app.get("/api/boards/{board_id}")
    async def board(board_id: str, me: str = Depends(person)) -> dict[str, Any]:  # noqa: ARG001
        view = host.board_view(board_id)
        if not view:
            raise HTTPException(status_code=404, detail="no such board")
        return view

    @app.post("/api/frames/{frame_id}/comments")
    async def comment(frame_id: str, body: CommentIn, me: str = Depends(person)) -> dict[str, Any]:
        try:
            return host.add_comment(
                frame_id, author_id=me, text=body.text, x=body.x, y=body.y, parent_id=body.parent_id
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="no such frame") from None

    @app.post("/api/comments/{comment_id}/resolve")
    async def resolve(
        comment_id: str, body: ResolveIn, me: str = Depends(person)
    ) -> dict[str, bool]:
        try:
            host.resolve_comment(comment_id, by=me, resolved=body.resolved)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such note") from None
        return {"ok": True}

    @app.post("/api/frames/{frame_id}/verdict")
    async def verdict(frame_id: str, body: VerdictIn, me: str = Depends(person)) -> dict[str, bool]:
        try:
            host.set_verdict(frame_id, by=me, verdict=body.verdict)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such frame") from None
        return {"ok": True}

    @app.post("/api/boards/{board_id}/send")
    async def send(board_id: str, body: SendIn, me: str = Depends(person)) -> dict[str, Any]:
        try:
            return host.send_board(board_id, by=me, approve=body.approve)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such board") from None

    @app.post("/api/boards/{board_id}/pick")
    async def pick(board_id: str, body: PickIn, me: str = Depends(person)) -> dict[str, Any]:
        try:
            return host.pick_look(board_id, body.frame_id, by=me, reason=body.reason)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such look") from None

    # -- what the canvas can ask for ---------------------------------------------------------

    @app.get("/api/catalog")
    async def catalog(me: str = Depends(person)) -> dict[str, Any]:  # noqa: ARG001
        return catalog_view()

    @app.post("/api/threads/{thread_id}/assets")
    async def add_asset(thread_id: str, body: AssetIn, me: str = Depends(person)) -> dict[str, Any]:
        thread_or_404(thread_id)
        try:
            asset = host.request_asset(
                thread_id, kind=body.kind, by=me, sources=body.sources, note=body.note
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="no such task or asset") from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        return host.asset_view(asset)

    @app.post("/api/channels/{channel_id}/templates")
    async def place_template(
        channel_id: str, body: TemplateIn, me: str = Depends(person)
    ) -> dict[str, Any]:
        if store.channel(channel_id) is None:
            raise HTTPException(status_code=404, detail="no such channel")
        # Started from what someone brings, the links in it are read first.
        material = not body.from_asset and not body.from_frame
        read = await linked(body.text, me) if material else []
        try:
            message = host.place_template(
                channel_id,
                body.template,
                by=me,
                text=body.text,
                file_ids=[*body.files, *read],
                from_asset=body.from_asset or None,
                from_frame=body.from_frame or None,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="no such template or asset") from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        return message

    # -- a film's final look -----------------------------------------------------------------

    # -- research: questions about the person's repositories, asked on this computer --------

    @app.get("/api/research")
    async def research_options(me: str = Depends(person)) -> dict[str, Any]:  # noqa: ARG001
        return await asyncio.to_thread(host.research.options)

    @app.post("/api/channels/{channel_id}/research")
    async def open_research(
        channel_id: str, body: ResearchIn, me: str = Depends(person)
    ) -> dict[str, Any]:
        if store.channel(channel_id) is None:
            raise HTTPException(status_code=404, detail="no such channel")
        try:
            frame, conversation = host.research.open(
                channel_id, by=me, repo=body.repo, harness=body.harness, question=body.question
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        return {"thread": host.thread_view(frame), "conversation": conversation}

    @app.post("/api/research/{frame_id}/conversations")
    async def ask_research(
        frame_id: str, body: QuestionIn, me: str = Depends(person)
    ) -> dict[str, Any]:
        try:
            return host.research.ask(
                frame_id,
                by=me,
                question=body.question,
                harness=body.harness,
                parent=body.parent,
                quote=body.quote,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="no such research") from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.post("/api/research/{frame_id}/notes")
    async def keep_note(frame_id: str, body: NoteIn, me: str = Depends(person)) -> dict[str, Any]:
        try:
            return host.research.keep(
                frame_id,
                by=me,
                text=body.text,
                conversation_id=body.conversation_id,
                message_id=body.message_id,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="no such research") from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.patch("/api/notes/{note_id}")
    async def edit_note(
        note_id: str,
        body: NoteEditIn,
        me: str = Depends(person),  # noqa: ARG001
    ) -> dict[str, Any]:
        try:
            return host.research.edit_note(note_id, text=body.text)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such note") from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.delete("/api/notes/{note_id}")
    async def drop_note(note_id: str, me: str = Depends(person)) -> dict[str, bool]:  # noqa: ARG001
        try:
            host.research.drop_note(note_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such note") from None
        return {"ok": True}

    @app.get("/api/threads/{thread_id}/preview/{port}")
    async def preview(
        thread_id: str,
        port: int,
        project: str = "",
        me: str = Depends(person),  # noqa: ARG001
    ) -> Response:
        """The preview the agent opened on the thread's computer: the browser goes on to the
        local port that reaches it. On the host sandbox the agent's ports are this machine's."""
        thread_or_404(thread_id)
        if not 1024 <= port <= 65535:
            raise HTTPException(status_code=404, detail="no such preview")
        if host.previews is None:
            target = f"http://127.0.0.1:{port}/" + (f"#project/{quote(project)}" if project else "")
        else:
            try:
                target = await host.previews.open(thread_id, port, project=project)
            except PreviewError as error:
                return HTMLResponse(_preview_missing(str(error)), status_code=503)
        return RedirectResponse(target, status_code=307)

    @app.post("/api/assets/{asset_id}/approve")
    async def approve_draft(asset_id: str, me: str = Depends(person)) -> dict[str, Any]:
        try:
            return host.approve_draft(asset_id, by=me)
        except KeyError:
            raise HTTPException(status_code=404, detail="no draft to sign off") from None

    @app.post("/api/assets/{asset_id}/render")
    async def render_film(asset_id: str, me: str = Depends(person)) -> dict[str, Any]:
        try:
            return host.approve_film(asset_id, by=me)
        except KeyError:
            raise HTTPException(status_code=404, detail="no film preview to sign off") from None

    # -- what the agent works with -----------------------------------------------------------

    @app.get("/api/brand")
    async def brand(me: str = Depends(person), channel: str = "") -> dict[str, Any]:  # noqa: ARG001
        if channel:
            return shelf.view(shelf.channel_brand(channel))
        return brand_view(settings.resolved_brand_path(project_root))

    # -- brands: the configured pack and those read from websites ----------------------------

    @app.get("/api/brands")
    async def brands(me: str = Depends(person)) -> dict[str, Any]:  # noqa: ARG001
        return {"brands": shelf.brands(), "reading": list(shelf.reading.values())}

    @app.post("/api/brands")
    async def read_brand(body: BrandReadIn, me: str = Depends(person)) -> dict[str, Any]:
        if body.channel and store.channel(body.channel) is None:
            raise HTTPException(status_code=404, detail="no such channel")
        try:
            return shelf.read(body.url, by=me, channel_id=body.channel)
        except SiteBrandError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.get("/api/brands/{slug}")
    async def brand_pack(slug: str, me: str = Depends(person)) -> dict[str, Any]:  # noqa: ARG001
        try:
            return shelf.view(slug)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such brand") from None

    @app.get("/api/brands/{slug}/files/{name:path}")
    async def brand_file(slug: str, name: str) -> FileResponse:
        path = shelf.file(slug, name)
        if path is None:
            raise HTTPException(status_code=404, detail="no such file")
        return FileResponse(path, headers={"X-Content-Type-Options": "nosniff"})

    @app.patch("/api/channels/{channel_id}")
    async def wear_brand(
        channel_id: str,
        body: ChannelBrandIn,
        me: str = Depends(person),  # noqa: ARG001
    ) -> dict[str, Any]:
        try:
            return shelf.wear(channel_id, body.brand)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such channel") from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.get("/api/brand/logos/{name}")
    async def brand_logo(name: str) -> FileResponse:
        folder = (settings.resolved_brand_path(project_root) / "logos").resolve()
        path = (folder / name).resolve()
        if path.parent != folder or not path.is_file():
            raise HTTPException(status_code=404, detail="no such logo")
        return FileResponse(path)

    @app.get("/api/skills")
    async def skills(me: str = Depends(person)) -> list[dict[str, Any]]:  # noqa: ARG001
        return skills_view(project_root)

    @app.get("/api/computer")
    async def computer(me: str = Depends(person)) -> dict[str, Any]:  # noqa: ARG001
        return computer_view(project_root, settings, host)

    # -- live --------------------------------------------------------------------------------

    @app.get("/api/stream")
    async def stream() -> StreamingResponse:
        async def events() -> AsyncIterator[str]:
            yield "retry: 2000\n\n"
            # A queue, not the hub's generator: timing out a `get` for a keep-alive is harmless,
            # where cancelling a generator's `anext` would close it.
            queue = hub.open()
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=PING_SECONDS)
                    except TimeoutError:
                        yield ": ping\n\n"
                        continue
                    yield f"data: {json.dumps(event, default=str)}\n\n"
            finally:
                hub.close(queue)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # -- the app itself ----------------------------------------------------------------------

    built = project_root / "web" / "dist"
    if (built / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=built / "assets"), name="assets")

        @app.get("/{path:path}")
        async def spa(path: str) -> FileResponse:
            target = (built / path).resolve()
            if path and built.resolve() in target.parents and target.is_file():
                return FileResponse(target)
            # Revalidate the page every time: it names this build's hashed assets.
            return FileResponse(built / "index.html", headers={"Cache-Control": "no-cache"})

    return app


# -- read-only views of the brand pack, the skills and the computer ----------------------------


def _frontmatter(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    if not lines or lines[0].strip() != "---":
        return out
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, _, value = line.partition(":")
        if key.strip() in ("name", "description"):
            out[key.strip()] = value.strip().strip('"')
    return out


def skills_view(root: Path) -> list[dict[str, Any]]:
    vendored: set[str] = set()
    with contextlib.suppress(OSError, ValueError):
        lock = json.loads((root / "skills-lock.json").read_text(encoding="utf-8"))
        for entry in (
            lock.get("skills", {}).values() if isinstance(lock.get("skills"), dict) else []
        ):
            if isinstance(entry, dict) and entry.get("name"):
                vendored.add(str(entry["name"]))
        if isinstance(lock.get("skills"), dict):
            vendored |= set(lock["skills"])
    out = []
    for skill in sorted((root / "skills").glob("*/SKILL.md")):
        meta = _frontmatter(skill)
        name = meta.get("name") or skill.parent.name
        out.append(
            {
                "name": name,
                "description": meta.get("description", ""),
                "vendored": skill.parent.name in vendored,
            }
        )
    return out


def computer_view(root: Path, settings: Settings, host: AgentHost) -> dict[str, Any]:
    pinned: dict[str, str] = {}
    with contextlib.suppress(OSError, ValueError):
        package = json.loads((root / "sandbox" / "render" / "package.json").read_text())
        pinned = {str(k): str(v) for k, v in (package.get("dependencies") or {}).items()}
    runtime = host.runtime
    return {
        "sandbox": runtime.binding.name if runtime else None,
        "image": settings.sandbox_image,
        "vcpus": settings.sandbox_vcpus,
        "mem_gib": settings.sandbox_mem_gib,
        "network": settings.egress_allowlist() or [],
        "pinned": pinned,
        "keys_inside": False,
    }


def _preview_missing(reason: str) -> str:
    """What the preview's frame shows when the Studio can't be reached: why, and what to do."""
    return (
        "<!doctype html><meta charset=utf-8><title>Preview unavailable</title>"
        "<style>:root{color-scheme:light dark}body{margin:0;display:grid;place-items:center;"
        "min-height:100vh;font:15px/1.5 system-ui,sans-serif;background:Canvas;color:CanvasText}"
        "main{max-width:420px;padding:24px;text-align:center}p{margin:6px 0;opacity:.75}</style>"
        f"<main><b>The preview isn't open</b><p>{html.escape(reason)}</p>"
        "<p>Ask in the thread and the agent will open it again.</p></main>"
    )
