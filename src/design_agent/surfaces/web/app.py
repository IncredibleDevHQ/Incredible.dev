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
- episodes (`episode_desk.py`): `GET /api/episodes/options` (who can write one, the looks, the
  lengths), `POST /api/channels/{id}/episodes` (one from material or a research frame's notes),
  `GET /api/episodes/{id}` (everything its studio draws), `POST /api/episodes/{id}/approve`,
  `POST /api/episodes/{id}/choices` (the look, who has the frame, a picture's level and who
  builds it),
  `POST /api/episodes/{id}/ask` (a change in words, of the film, a chapter, a line or a
  picture), `POST /api/episodes/{id}/lines/{frame}` (a person's own words for a line),
  `POST /api/episodes/{id}/lines` (a line they add: going on in its block, to camera, or with a
  picture) and `/cut` (lines they cut, or one joined to the line before it),
  `POST /api/episodes/{id}/replan` (pictures planned again for the words their lines say now,
  then drawn again), `POST /api/episodes/{id}/pictures/{unit}/keep` (a picture made for other
  words kept for the new ones, with nothing run),
  `POST /api/episodes/{id}/undo` (the last change, taken back; the one before it is next) and
  `/redo` (put back),
  `POST /api/episodes/{id}/again` (its planning), `/stop` (the plan and the pictures under
  way, or one picture), `POST /api/episodes/{id}/pictures` (make the ones named, a chapter's,
  or the ones that stopped), `POST /api/episodes/{id}/apply` (run what the picks and changes
  wait on: the writer's part, then the pictures out of date),
  `POST /api/episodes/{id}/pictures/{unit}/go` and `/note` (a picture's stills),
  `POST /api/episodes/{id}/takes` (a recording, of any size up to 8 GiB: it goes to disk,
  and as it arrived to the footage bucket when one is set),
  `POST /api/episodes/{id}/takes/{take}/keep`, `DELETE /api/episodes/{id}/takes/{take}`,
  `GET /api/voices` (the voices a narrator can speak in), `POST /api/episodes/{id}/voice` (a
  clone of the person's voice, from their takes or a recording, after they say it is theirs),
  `POST /api/episodes/{id}/film` (render it)
- the production board: `GET /api/production` (every episode's jobs, the agents and how busy
  each is, in one read), `POST /api/production/assign` (pictures of any episodes handed to an
  agent and started)
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
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from starlette.background import BackgroundTask
from starlette.datastructures import UploadFile as FormFile

from design_agent.config import SAMPLE_BRAND, Settings
from design_agent.runtime import maintenance
from design_agent.runtime.local import build_local_runtime
from design_agent.runtime.persistence import open_persistence, workspace_of
from design_agent.surfaces.web.agent import AgentHost
from design_agent.surfaces.web.blobs import StorageUnavailable, byte_range
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
#: A take may be a camera's own recording: ten minutes of 4K at 100 Mbit/s is 7.5 GB. It is
#: written to disk as it arrives and read from there, so its size is never held in memory.
MAX_TAKE_BYTES = 8 * 1024**3
#: A recording brought for a voice clone: a few minutes of speech.
MAX_SAMPLE_BYTES = 25 * 1024 * 1024
PING_SECONDS = 15.0


class OrganizationIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    website: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=500)

    @field_validator("website")
    @classmethod
    def validate_website(cls, value: str) -> str:
        if value:
            HttpUrl(value)
        return value


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
    #: The conversation it branches from, the passage of that one's answer it starts on, and the
    #: answer (a message) the passage was taken from.
    parent: str = Field(default="", max_length=64)
    quote: str = Field(default="", max_length=4_000)
    answer: str = Field(default="", max_length=64)


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=8_000)
    conversation_id: str = Field(default="", max_length=64)
    message_id: str = Field(default="", max_length=64)


class NoteEditIn(BaseModel):
    text: str = Field(min_length=1, max_length=8_000)


class NarratorIn(BaseModel):
    """The ElevenLabs voice an episode is narrated in, by its id, with the name it is shown by."""

    id: str = Field(pattern=r"^[A-Za-z0-9]{10,40}$")
    name: str = Field(default="", max_length=80)


class EpisodeSettingsIn(BaseModel):
    #: How long it may run: the least and the most, in seconds, or "auto" when the material
    #: decides. The desk keeps the two inside its limits and apart.
    seconds: tuple[int, int] | Literal["auto"] | None = None
    presenter: str | None = Field(default=None, pattern=r"^(on|off)$")
    theme: str | None = Field(default=None, max_length=60)
    voice: str | None = Field(default=None, pattern=r"^(live|narrator|local)$")
    background_color: str | None = Field(default=None, pattern=r"^(#[0-9a-fA-F]{6})?$")
    portrait: Literal["mira", "kai", "ellis", "june"] | None = None
    background_texture: Literal["solid", "dots", "grid", "diagonal"] | None = None
    narrator: NarratorIn | None = None
    level: str | None = Field(default=None, pattern=r"^(simple|rich)$")
    writer: str | None = Field(default=None, pattern=r"^(claude|codex|kimi|builtin|demo)$")
    #: The model the film's agent runs on and how hard it thinks; an empty one is the agent's
    #: own default. The desk holds both to what that agent offers.
    writer_model: str | None = Field(default=None, max_length=120)
    writer_effort: str | None = Field(default=None, pattern=r"^[a-z]{0,12}$")


class EpisodeIn(BaseModel):
    title: str = Field(default="", max_length=120)
    #: The notes it starts from (with or without text files), or a word to go with a frame's.
    text: str = Field(default="", max_length=200_000)
    files: list[str] = Field(default_factory=list, max_length=MAX_UPLOADS)
    #: A research frame whose notes it is made from, in that frame.
    from_frame: str = Field(default="", max_length=64)
    settings: EpisodeSettingsIn = Field(default_factory=EpisodeSettingsIn)
    resolve_links: bool = True


class FramePickIn(BaseModel):
    """A person's picks for a line, a chapter or the film. A value of null takes that pick
    back and leaves the others."""

    presence: str | None = Field(default=None, pattern=r"^(person|both|content)$")
    layout: str | None = Field(default=None, max_length=60)
    #: A layout for every line of one presence (a chapter's or the film's picks only).
    layouts: dict[str, str | None] | None = Field(default=None, max_length=3)
    #: The type of the picture a line brings in, and how it comes in (a line's picks only).
    picture: str | None = Field(default=None, max_length=40)
    transition: str | None = Field(default=None, max_length=40)
    window_size: (
        Annotated[int, Field(strict=True, ge=25, le=125)] | Literal["small", "large"] | None
    ) = None
    window_shape: Literal["rectangle", "rounded", "circle"] | None = None


class UnitPickIn(BaseModel):
    """A person's picks for one picture: how it is made, and which agent builds it (an empty
    builder gives it back to the film's writer)."""

    level: str | None = Field(default=None, pattern=r"^(simple|rich)$")
    builder: str | None = Field(default=None, pattern=r"^(claude|codex|kimi|builtin|demo|)$")

    component: str | None = Field(default=None, max_length=40)
    variant: str | None = Field(default=None, max_length=40)
    direction: str | None = Field(default=None, max_length=1600)
    model: str | None = Field(default=None, max_length=100)
    effort: str | None = Field(default=None, max_length=16)


class PicturesIn(BaseModel):
    """Which pictures to make: the ones named, a chapter's, or with neither the ones that
    stopped or failed. With a level, the ones named are made again that way."""

    units: list[str] | None = Field(default=None, max_length=200)
    chapter: str = Field(default="", max_length=80)
    level: Literal["simple", "rich"] | None = None


class RegenerateChapterIn(BaseModel):
    provider: Literal["", "claude", "codex", "kimi", "builtin"] = ""
    model: str = Field(default="", max_length=100)


class LineIn(BaseModel):
    """A line a person adds to a chapter's script: after a line (or first in the chapter
    named), going on in that line's block, said to camera, or with a picture of a type."""

    after: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=2000)
    kind: str = Field(
        default="more",
        pattern=r"^(more|camera|diagram|list|typeset-code|chips|illustration|slide)$",
    )
    #: The words the line `after` keeps, when the new line is the rest of it split off.
    keep: str | None = Field(default=None, max_length=2000)


class CutIn(BaseModel):
    """Lines a person cuts: one, or a block's run. With `join`, the one line's words go on at
    the end of the line before it."""

    frames: list[str] = Field(min_length=1, max_length=40)
    join: bool = False
    #: What the line before says once joined, when the person changed its words too.
    words: str | None = Field(default=None, max_length=2000)


class ReplanIn(BaseModel):
    """Pictures to have planned again for the words their lines say now."""

    units: list[str] = Field(min_length=1, max_length=200)


class StopIn(BaseModel):
    #: One picture to stop; with none, everything under way for the episode.
    unit: str = Field(default="", max_length=80)


class ChoicesIn(BaseModel):
    settings: EpisodeSettingsIn = Field(default_factory=EpisodeSettingsIn)
    #: Who has the frame, and in which layout: for a line, a chapter, or every line.
    frames: dict[str, FramePickIn] = Field(default_factory=dict)
    chapters: dict[str, FramePickIn] = Field(default_factory=dict)
    all: FramePickIn | None = None
    #: Lines (or chapters) whose pick is taken back.
    clear: list[str] = Field(default_factory=list, max_length=400)
    units: dict[str, UnitPickIn] = Field(default_factory=dict)
    #: The agent that builds a chapter's pictures, by chapter; null gives them back to the
    #: film's writer.
    builders: dict[str, str | None] = Field(default_factory=dict, max_length=200)


class AskIn(BaseModel):
    """A change asked for in words, of the film, a chapter, a line or a line's picture."""

    scope: str = Field(pattern=r"^(film|chapter|line|picture)$")
    target: str = Field(default="", max_length=80)
    text: str = Field(min_length=1, max_length=2_000)


class WordsIn(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)


class AgainIn(BaseModel):
    from_start: bool = False
    writer: str = Field(default="", pattern=r"^(claude|codex|kimi|builtin|demo|)$")
    model: str | None = Field(default=None, max_length=120)
    effort: str | None = Field(default=None, pattern=r"^[a-z]{0,12}$")


class PictureNoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=600)


class KeepIn(BaseModel):
    keep: bool = True


class JobIn(BaseModel):
    """A picture as the production board names it: its episode, and its unit there."""

    episode: str = Field(min_length=1, max_length=64)
    unit: str = Field(min_length=1, max_length=80)


class AssignIn(BaseModel):
    """Pictures handed to an agent and started. A model or an effort the agent offers goes with
    every one of them; with neither, a picture already with that agent keeps what it runs on.
    With no agent each keeps the one it is set to."""

    jobs: list[JobIn] = Field(min_length=1, max_length=400)
    agent: str = Field(default="", pattern=r"^(claude|codex|kimi|builtin|demo|)$")
    model: str = Field(default="", max_length=100)
    effort: str = Field(default="", max_length=16)
    start: bool = True


class BrandReadIn(BaseModel):
    url: str = Field(min_length=3, max_length=2_000)
    #: A channel that wears the brand once it is read.
    channel: str = Field(default="", max_length=64)


class ChannelBrandIn(BaseModel):
    brand: str = Field(min_length=1, max_length=60)


def create_app(
    project_root: Path,
    settings: Settings | None = None,
    *,
    demo: bool = False,
    authenticated_user: dict[str, Any] | None = None,
) -> FastAPI:
    settings = settings or Settings()
    if authenticated_user is None and (settings.auth_required or settings.supabase_url):
        from design_agent.surfaces.web.auth import create_authenticated_app

        return create_authenticated_app(project_root, settings, demo=demo)
    schema = None
    if authenticated_user:
        from design_agent.surfaces.web.auth import user_schema

        schema = user_schema(authenticated_user["id"])
    if demo:
        # The demo's scripted lead poses in the sample brand's tokens, whatever pack is installed.
        settings = settings.model_copy(update={"brand_path": SAMPLE_BRAND})
    workspace = workspace_of(settings, project_root)
    data_dir = workspace / "house"
    store = Store(
        data_dir / "house.sqlite",
        database_url=settings.database_url.get_secret_value()
        if authenticated_user and settings.database_url
        else None,
        schema=schema,
        user=authenticated_user,
    )
    hub = Hub()
    host = AgentHost(
        settings=settings,
        store=store,
        hub=hub,
        data_dir=data_dir,
        demo=demo,
        blob_namespace=schema.removeprefix("user_") if schema else "local",
        project_root=project_root,
    )
    shelf = BrandShelf(
        store=store, hub=hub, settings=settings, project_root=project_root, data_dir=data_dir
    )
    host.episodes.brand_for = shelf.brand_for

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001 - FastAPI's signature
        servers = servers_for_runtime(project_root, settings, "self_hosted")
        loaded = await load_mcp_tools(servers)
        servers = [s for s in servers if s.name not in loaded.failed]
        model = None
        if demo:
            from design_agent.surfaces.web.demo import DemoDirector

            model = DemoDirector()
        async with open_persistence(settings, workspace, schema=schema) as (checkpointer, lg_store):
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

    @app.exception_handler(StorageUnavailable)
    async def storage_error(_request: Request, _error: StorageUnavailable) -> Response:
        return Response("File storage is unavailable. Try again shortly.", status_code=503)

    def person(x_person: str = Header(default="you")) -> str:
        if authenticated_user:
            return str(authenticated_user["id"])
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

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/auth/config")
    async def auth_config() -> dict[str, bool]:
        return {"enabled": bool(authenticated_user)}

    @app.get("/api/auth/session")
    async def workspace_auth_session() -> dict[str, bool]:
        # In authenticated mode the outer gateway owns this route and validates the cookie.
        return {"authenticated": bool(authenticated_user)}

    @app.get("/api/session")
    async def session(me: str = Depends(person)) -> dict[str, Any]:
        runtime = host.runtime
        return {
            "me": me,
            "email": authenticated_user["email"] if authenticated_user else None,
            "organizationName": store.organization()["name"],
            "people": store.people(),
            "agent": {"mark": host.mark, "model": "demo" if demo else str(settings.lead_model())},
            "demo": demo,
            "authenticated": bool(authenticated_user),
            "sandbox": runtime.binding.name if runtime else None,
        }

    @app.get("/api/organization")
    def organization(me: str = Depends(person)) -> dict[str, Any]:  # noqa: ARG001
        return store.organization()

    @app.put("/api/organization")
    def save_organization(body: OrganizationIn, me: str = Depends(person)) -> dict[str, str]:  # noqa: ARG001
        store.save_organization(body.name, body.website, body.description)
        return body.model_dump()

    @app.get("/api/usage/report")
    def usage_report(
        period: Literal["today", "week", "month"] = "week", _me: str = Depends(person)
    ) -> dict[str, Any]:
        return store.usage_report(period)

    @app.get("/api/usage")
    def usage(me: str = Depends(person)) -> dict[str, Any]:  # noqa: ARG001
        return store.workspace_usage()

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
            row = await asyncio.to_thread(
                host.save_file,
                "",
                upload.filename or "attachment",
                content,
                origin="upload",
                author=me,
            )
            out.append(host.file_view(row))
        return out

    @app.get("/api/files/{file_id}")
    async def file(
        file_id: str, range_header: str | None = Header(default=None, alias="Range")
    ) -> Response:
        row = store.file(file_id)
        if row is None:
            raise HTTPException(status_code=404, detail="no such file")
        try:
            if row.get("storage", "local") == "local":
                path = host.blobs.local_path(row["rel_path"])
                if not path.is_file():
                    raise FileNotFoundError
                return FileResponse(path, media_type=row["mime"], filename=row["name"])
            try:
                start, end = byte_range(range_header, row["size"])
            except ValueError:
                return Response(
                    status_code=416, headers={"Content-Range": f"bytes */{row['size']}"}
                )
            body = await asyncio.to_thread(
                host.blobs.open, row, start, end if range_header else None
            )
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="no such file") from None

        def chunks() -> Any:
            remaining = end - start + 1
            try:
                while remaining:
                    data = body.read(min(1024 * 1024, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data
            finally:
                body.close()

        headers = {
            "Content-Length": str(end - start + 1),
            "Content-Disposition": f"attachment; filename*=utf-8''{quote(row['name'])}",
            "Accept-Ranges": "bytes",
            "ETag": f'"{row["sha256"]}"',
            "X-Content-Type-Options": "nosniff",
        }
        if range_header:
            headers["Content-Range"] = f"bytes {start}-{end}/{row['size']}"
        return StreamingResponse(
            chunks(),
            status_code=206 if range_header else 200,
            media_type=row["mime"],
            headers=headers,
            background=BackgroundTask(body.close),
        )

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

    # -- episodes: an explainer planned, recorded and rendered in its own studio --------------

    def episode_call(run: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return run()
        except KeyError:
            raise HTTPException(status_code=404, detail="no such episode") from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.get("/api/presenter-portraits/{name}")
    def presenter_portrait(name: str) -> FileResponse:
        from design_agent.episode import film

        if name not in film.PORTRAITS:
            raise HTTPException(status_code=404, detail="Unknown presenter portrait.")
        return FileResponse(film.portrait_path(name), media_type="image/jpeg")

    @app.get("/api/episodes/options")
    async def episode_options(me: str = Depends(person)) -> dict[str, Any]:  # noqa: ARG001
        return await asyncio.to_thread(host.episodes.options)

    @app.get("/api/channels/{channel_id}/voices")
    async def list_channel_voices(channel_id: str, _me: str = Depends(person)) -> dict[str, Any]:
        try:
            return {"voices": host.episodes.channel_voices(channel_id)}
        except KeyError:
            raise HTTPException(status_code=404, detail="no such channel") from None

    async def voice_sample(file: UploadFile) -> tuple[str, bytes]:
        content = await file.read(MAX_SAMPLE_BYTES + 1)
        if len(content) > MAX_SAMPLE_BYTES:
            raise HTTPException(status_code=413, detail="the recording is over 25 MiB")
        if not content:
            raise HTTPException(status_code=422, detail="the recording is empty")
        return file.filename or "sample", content

    @app.post("/api/channels/{channel_id}/voices")
    async def add_channel_voice(
        channel_id: str,
        name: str = Form(..., max_length=80),
        consent: bool = Form(default=False),
        file: UploadFile = File(...),  # noqa: B008 - FastAPI's declaration style
        _me: str = Depends(person),
    ) -> dict[str, Any]:
        try:
            return await host.episodes.clone_channel_voice(
                channel_id, name=name, consent=consent, sample=await voice_sample(file)
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="no such channel") from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.post("/api/channels/{channel_id}/episodes")
    async def new_episode(
        channel_id: str, body: EpisodeIn, me: str = Depends(person)
    ) -> dict[str, Any]:
        if store.channel(channel_id) is None:
            raise HTTPException(status_code=404, detail="no such channel")
        files = [*body.files, *(await linked(body.text, me) if body.resolve_links else [])]
        return episode_call(
            lambda: host.episodes.create(
                channel_id,
                by=me,
                title=body.title,
                text=body.text,
                file_ids=files,
                frame_id=body.from_frame,
                settings=body.settings.model_dump(exclude_none=True),
            )
        )

    @app.get("/api/episodes/{episode_id}")
    async def episode(episode_id: str, me: str = Depends(person)) -> dict[str, Any]:  # noqa: ARG001
        return episode_call(lambda: host.episodes.view(episode_id))

    @app.post("/api/episodes/{episode_id}/approve")
    async def approve_episode(episode_id: str, me: str = Depends(person)) -> dict[str, Any]:
        return episode_call(lambda: host.episodes.approve(episode_id, by=me))

    @app.post("/api/episodes/{episode_id}/choices")
    async def choose_episode(
        episode_id: str, body: ChoicesIn, me: str = Depends(person)
    ) -> dict[str, Any]:
        # what was sent, as it was sent: a null is a pick taken back, not a pick left out
        change = body.model_dump(exclude_unset=True)
        change["settings"] = body.settings.model_dump(exclude_none=True)
        if "narrator" in body.settings.model_fields_set and body.settings.narrator is None:
            change["settings"]["narrator"] = None
        return episode_call(lambda: host.episodes.choose(episode_id, by=me, change=change))

    @app.post("/api/episodes/{episode_id}/ask")
    async def ask_episode(
        episode_id: str, body: AskIn, me: str = Depends(person)
    ) -> dict[str, Any]:
        return episode_call(
            lambda: host.episodes.ask(
                episode_id, by=me, scope=body.scope, target=body.target, text=body.text
            )
        )

    @app.post("/api/episodes/{episode_id}/lines/{frame_id}")
    async def edit_line(
        episode_id: str, frame_id: str, body: WordsIn, me: str = Depends(person)
    ) -> dict[str, Any]:
        return episode_call(
            lambda: host.episodes.edit(episode_id, by=me, frame=frame_id, text=body.text)
        )

    @app.post("/api/episodes/{episode_id}/lines")
    async def add_line(episode_id: str, body: LineIn, me: str = Depends(person)) -> dict[str, Any]:
        return episode_call(
            lambda: host.episodes.add_line(
                episode_id, by=me, after=body.after, text=body.text, kind=body.kind, keep=body.keep
            )
        )

    @app.post("/api/episodes/{episode_id}/pictures/{unit_id}/keep")
    async def keep_picture(
        episode_id: str, unit_id: str, me: str = Depends(person)
    ) -> dict[str, Any]:
        return episode_call(lambda: host.episodes.keep_picture(episode_id, unit_id, by=me))

    @app.post("/api/episodes/{episode_id}/pictures/{unit_id}/versions/{n}/use")
    async def use_picture_version(
        episode_id: str, unit_id: str, n: int, me: str = Depends(person)
    ) -> dict[str, Any]:
        return episode_call(lambda: host.episodes.use_version(episode_id, unit_id, n, by=me))

    @app.post("/api/episodes/{episode_id}/replan")
    async def replan_pictures(
        episode_id: str, body: ReplanIn, me: str = Depends(person)
    ) -> dict[str, Any]:
        return episode_call(lambda: host.episodes.replan(episode_id, by=me, pictures=body.units))

    @app.post("/api/episodes/{episode_id}/cut")
    async def cut_lines(episode_id: str, body: CutIn, me: str = Depends(person)) -> dict[str, Any]:
        return episode_call(
            lambda: host.episodes.cut_lines(
                episode_id, by=me, frames=body.frames, join=body.join, words=body.words
            )
        )

    @app.post("/api/episodes/{episode_id}/undo")
    async def undo_episode(episode_id: str, me: str = Depends(person)) -> dict[str, Any]:
        return episode_call(lambda: host.episodes.undo(episode_id, by=me))

    @app.post("/api/episodes/{episode_id}/redo")
    async def redo_episode(episode_id: str, me: str = Depends(person)) -> dict[str, Any]:
        return episode_call(lambda: host.episodes.redo(episode_id, by=me))

    @app.post("/api/episodes/{episode_id}/again")
    async def plan_again(
        episode_id: str,
        body: AgainIn,
        me: str = Depends(person),  # noqa: ARG001
    ) -> dict[str, Any]:
        return episode_call(
            lambda: host.episodes.again(
                episode_id,
                writer=body.writer,
                model=body.model,
                effort=body.effort,
                from_start=body.from_start,
            )
        )

    @app.post("/api/episodes/{episode_id}/stop")
    async def stop_episode(
        episode_id: str,
        body: StopIn | None = None,
        me: str = Depends(person),  # noqa: ARG001
    ) -> dict[str, bool]:
        if store.episode(episode_id) is None:
            raise HTTPException(status_code=404, detail="no such episode")
        host.episodes.stop(episode_id, body.unit if body else "")
        return {"ok": True}

    @app.get("/api/episodes/{episode_id}/lines/{frame}/history")
    async def line_history(
        episode_id: str, frame: str, _me: str = Depends(person)
    ) -> dict[str, Any]:
        return episode_call(lambda: host.episodes.line_history(episode_id, frame))

    @app.post("/api/episodes/{episode_id}/apply")
    async def apply_episode(episode_id: str, me: str = Depends(person)) -> dict[str, Any]:
        return episode_call(lambda: host.episodes.apply(episode_id, by=me))

    @app.post("/api/episodes/{episode_id}/pictures")
    async def make_pictures(
        episode_id: str, body: PicturesIn | None = None, me: str = Depends(person)
    ) -> dict[str, Any]:
        asked = body or PicturesIn()
        return episode_call(
            lambda: host.episodes.make(
                episode_id, by=me, only=asked.units, chapter=asked.chapter, level=asked.level or ""
            )
        )

    @app.post("/api/episodes/{episode_id}/chapters/{chapter}/regenerate")
    async def regenerate_chapter(
        episode_id: str,
        chapter: str,
        body: RegenerateChapterIn,
        me: str = Depends(person),
    ) -> dict[str, Any]:
        return episode_call(
            lambda: host.episodes.regenerate_chapter(
                episode_id, chapter, by=me, provider=body.provider, model=body.model
            )
        )

    @app.post("/api/episodes/{episode_id}/pictures/{unit_id}/go")
    async def picture_go(
        episode_id: str, unit_id: str, me: str = Depends(person)
    ) -> dict[str, Any]:
        return episode_call(lambda: host.episodes.go(episode_id, unit_id, by=me))

    @app.post("/api/episodes/{episode_id}/pictures/{unit_id}/steer")
    async def steer_picture(
        episode_id: str, unit_id: str, body: PictureNoteIn, me: str = Depends(person)
    ) -> dict[str, Any]:
        return episode_call(lambda: host.episodes.steer(episode_id, unit_id, body.text, by=me))

    @app.delete("/api/episodes/{episode_id}/pictures/{unit_id}/steer/{note_id}")
    async def unsteer_picture(
        episode_id: str, unit_id: str, note_id: str, me: str = Depends(person)
    ) -> dict[str, Any]:
        return episode_call(lambda: host.episodes.unsteer(episode_id, unit_id, note_id, by=me))

    @app.post("/api/episodes/{episode_id}/pictures/{unit_id}/note")
    async def picture_note(
        episode_id: str, unit_id: str, body: PictureNoteIn, me: str = Depends(person)
    ) -> dict[str, Any]:
        return episode_call(
            lambda: host.episodes.send_back(episode_id, unit_id, by=me, note=body.text)
        )

    @app.post("/api/episodes/{episode_id}/takes")
    async def add_take(
        episode_id: str, request: Request, me: str = Depends(person)
    ) -> dict[str, Any]:
        # The form is read here, not declared, so a recording too large is refused by its
        # stated size before any of it is read. What is read goes to a file on disk.
        stated = request.headers.get("content-length", "")
        if not stated.isdigit():
            raise HTTPException(status_code=411, detail="the recording's size must be stated")
        if int(stated) > MAX_TAKE_BYTES:
            raise HTTPException(status_code=413, detail="the recording is over 8 GiB")
        async with request.form(max_files=1, max_fields=8) as form:
            upload, chapter = form.get("file"), form.get("chapter")
            if not isinstance(upload, FormFile) or not isinstance(chapter, str) or not chapter:
                raise HTTPException(status_code=422, detail="a recording and its chapter")
            frame, marks = form.get("frame") or "", form.get("marks") or "[]"
            label = form.get("label") or ""
            if not isinstance(label, str):
                raise HTTPException(status_code=422, detail="version name must be text")
            try:
                given = json.loads(marks) if isinstance(marks, str) else None
                if not isinstance(given, list) or not all(isinstance(m, dict) for m in given):
                    raise ValueError("marks must be a list")
                return await host.episodes.add_take(
                    episode_id,
                    by=me,
                    chapter=chapter,
                    frame=frame if isinstance(frame, str) else "",
                    marks=given,
                    label=label,
                    name=upload.filename or "take.webm",
                    source=upload.file,
                )
            except KeyError:
                raise HTTPException(status_code=404, detail="no such episode or chapter") from None
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from None

    @app.get("/api/voices")
    async def narrator_voices(me: str = Depends(person)) -> dict[str, Any]:  # noqa: ARG001
        try:
            return await host.episodes.voices()
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.post("/api/episodes/{episode_id}/pictures/{unit_id}/preview")
    async def preview_clip(
        episode_id: str, unit_id: str, _me: str = Depends(person)
    ) -> dict[str, Any]:
        try:
            return await host.episodes.preview_clip(episode_id, unit_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown episode.") from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.post("/api/episodes/{episode_id}/chapters/{chapter}/preview-voice")
    async def preview_voice(
        episode_id: str, chapter: str, _me: str = Depends(person)
    ) -> dict[str, Any]:
        try:
            return await host.episodes.preview_voice(episode_id, chapter)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown episode or chapter.") from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.post("/api/episodes/{episode_id}/voice/{voice_id}/preview")
    async def preview_clone(
        episode_id: str, voice_id: str, _me: str = Depends(person)
    ) -> dict[str, Any]:
        try:
            return await host.episodes.preview_channel_voice(episode_id, voice_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such voice in this channel.") from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.get("/api/episodes/{episode_id}/voice/{voice_id}/preview")
    async def clone_audio(
        episode_id: str, voice_id: str, _me: str = Depends(person)
    ) -> FileResponse:
        try:
            path = host.episodes.channel_voice_audio(episode_id, voice_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="No saved sample for this voice.") from None
        return FileResponse(path, media_type="audio/mpeg")

    @app.post("/api/episodes/{episode_id}/voice")
    async def clone_voice(
        episode_id: str,
        name: str = Form(..., max_length=80),
        consent: bool = Form(default=False),
        noisy: bool = Form(default=False),
        file: UploadFile | None = File(default=None),  # noqa: B008 - FastAPI's declaration style
        me: str = Depends(person),
    ) -> dict[str, Any]:
        sample = await voice_sample(file) if file is not None else None
        try:
            return await host.episodes.clone(
                episode_id, by=me, name=name, consent=consent, noisy=noisy, sample=sample
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="no such episode") from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    @app.post("/api/episodes/{episode_id}/takes/{take_id}/keep")
    async def keep_take(
        episode_id: str,
        take_id: str,
        body: KeepIn,
        me: str = Depends(person),  # noqa: ARG001
    ) -> dict[str, Any]:
        return episode_call(lambda: host.episodes.keep_take(episode_id, take_id, keep=body.keep))

    @app.delete("/api/episodes/{episode_id}/takes/{take_id}")
    async def drop_take(episode_id: str, take_id: str, me: str = Depends(person)) -> dict[str, Any]:  # noqa: ARG001
        return episode_call(lambda: host.episodes.keep_take(episode_id, take_id, keep=False))

    @app.post("/api/episodes/{episode_id}/film")
    async def render_episode(episode_id: str, me: str = Depends(person)) -> dict[str, Any]:
        return episode_call(lambda: host.episodes.render(episode_id, by=me))

    # -- the production board: every episode's jobs, and handing them to agents ---------------

    @app.get("/api/production")
    async def production(me: str = Depends(person)) -> dict[str, Any]:  # noqa: ARG001
        # Off the event loop: it reads every episode, and may wait on an agent's list of models.
        return await asyncio.to_thread(host.episodes.production)

    @app.post("/api/production/assign")
    async def assign_jobs(body: AssignIn, me: str = Depends(person)) -> dict[str, Any]:
        return episode_call(
            lambda: host.episodes.assign(
                [(job.episode, job.unit) for job in body.jobs],
                by=me,
                agent=body.agent,
                model=body.model,
                effort=body.effort,
                start=body.start,
            )
        )

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
                answer=body.answer,
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
