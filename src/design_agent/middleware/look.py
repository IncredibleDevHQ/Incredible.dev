"""`look`: the lead asks about images and keeps only the answer.

Why. An image in the lead's context is re-read from cache on every later turn. A 1080p frame is
2,691 tokens, so one kept for 50 turns is about 134K cached tokens, where a 300-token answer is
15K. The lead reviews renders, stills and contact sheets all job long, and its context fills with
images it has already judged.

`look(paths, question)` reads up to 8 images from the thread's sandbox, fits each within 1280 px,
and makes one call to the look model (the lead's model at low effort unless configured). Only
the answer, about 300 tokens or less, enters the lead's context; the images never do. The call's
usage is published like any other (`middleware/meter.py`).

The lead can still read an image itself when it needs to see it; `look` is one more tool.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.tools import ToolRuntime
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, tool
from PIL import Image

from design_agent.middleware.meter import publish_usage
from design_agent.tools.files import (
    BackendFor,
    WorkspaceError,
    read_bytes,
    require_backend,
    workspace_path,
)

_LOGGER = logging.getLogger(__name__)

MAX_IMAGES = 8
#: Long edge sent to the model: 1280 x 720 costs 1,196 tokens against 2,691 for 1080p.
MAX_EDGE = 1280
READ_CAP_MB = 20

_MEDIA_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif", "WEBP": "image/webp"}

LOOK_PROMPT = """You look at images for the lead of a design job and answer its question about them. The lead does not see the images; your answer is all it keeps.

Answer what was asked, concretely: refer to images by number, say what is where, quote the text you can read, name colours and sizes when they matter, and say plainly what is wrong or different. If the images cannot answer the question, say so. Plain text, about 200 words (300 tokens) or fewer, no preamble."""

ModelSource = BaseChatModel | Callable[[], BaseChatModel]


@dataclass(frozen=True)
class _Picture:
    path: str
    media_type: str
    data: str
    size: tuple[int, int]
    sent: tuple[int, int]


def _fit(path: str, raw: bytes) -> _Picture:
    """The image as the model gets it: its own bytes when they fit, else shrunk to MAX_EDGE."""
    with Image.open(io.BytesIO(raw)) as image:
        size = image.size
        media_type = _MEDIA_TYPES.get(image.format or "")
        if media_type is not None and max(size) <= MAX_EDGE:
            return _Picture(path, media_type, base64.b64encode(raw).decode(), size, size)
        frame = image.copy()
    frame.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
    alpha = frame.mode in ("RGBA", "LA") or (frame.mode == "P" and "transparency" in frame.info)
    out = io.BytesIO()
    if alpha:
        frame.convert("RGBA").save(out, format="PNG")
        media_type = "image/png"
    else:
        frame.convert("RGB").save(out, format="JPEG", quality=85)
        media_type = "image/jpeg"
    return _Picture(path, media_type, base64.b64encode(out.getvalue()).decode(), size, frame.size)


async def _load(backend_for: BackendFor, runtime: ToolRuntime, path: str) -> _Picture | str:
    """One image ready to send, or why it could not be."""
    try:
        path = workspace_path(path)
        raw = await read_bytes(require_backend(backend_for, runtime), path, cap_mb=READ_CAP_MB)
    except WorkspaceError as error:
        return str(error)
    try:
        return await asyncio.to_thread(_fit, path, raw)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return f"{path} is not an image this can read (for a video, grab frames or a contact sheet first)."


def _content(question: str, pictures: list[_Picture]) -> list[str | dict[Any, Any]]:
    blocks: list[str | dict[Any, Any]] = [{"type": "text", "text": f"Question: {question.strip()}"}]
    for number, picture in enumerate(pictures, 1):
        (width, height), sent = picture.size, picture.sent
        shown = f", shown at {sent[0]}x{sent[1]}" if sent != picture.size else ""
        blocks.append(
            {"type": "text", "text": f"Image {number}: {picture.path} ({width}x{height}{shown})"}
        )
        blocks.append({"type": "image", "base64": picture.data, "mime_type": picture.media_type})
    return blocks


def _answer(reply: object) -> str:
    if isinstance(reply, AIMessage):
        return reply.text.strip()
    return str(getattr(reply, "content", reply) or "").strip()


def make_look_tool(*, model: ModelSource, model_name: str, backend_for: BackendFor) -> BaseTool:
    """The `look` tool. `model` is the look model (or a factory for it, built on first use)."""
    held: list[BaseChatModel] = []

    def chat_model() -> BaseChatModel:
        if not held:
            held.append(model if isinstance(model, BaseChatModel) else model())
        return held[0]

    @tool
    async def look(paths: list[str], question: str, runtime: ToolRuntime) -> str:
        """Look at images in the sandbox and get a short answer; the images stay out of your context.

        A fast model looks at up to 8 images (renders, stills, frame grabs, contact
        sheets; each fitted within 1280 px) and answers `question` in about 300 tokens. Only
        that answer stays with you. An image you read yourself is re-read on every later turn:
        a 1080p frame is about 2,700 tokens each time, so one kept for 50 turns is about 134K
        tokens, against 15K for an answer. Ask for what you need to decide: what is on screen,
        text you need read, positions, colours, what is wrong, how two versions differ. For a
        video, grab frames or a contact sheet first. `paths` are files under /workspace.
        """
        wanted = [path.strip() for path in paths if path and path.strip()]
        if not wanted:
            return "Pass one or more image paths under /workspace."
        if not question.strip():
            return "Say what you want to know about the images."
        chosen = wanted[:MAX_IMAGES]
        loaded = await asyncio.gather(*(_load(backend_for, runtime, path) for path in chosen))
        pictures = [item for item in loaded if isinstance(item, _Picture)]
        notes = [item for item in loaded if isinstance(item, str)]
        if len(wanted) > MAX_IMAGES:
            notes.append(
                f"Looked at the first {MAX_IMAGES} of {len(wanted)} images; ask again for the rest."
            )
        if not pictures:
            return "Nothing to look at: " + " ".join(notes)
        try:
            reply = await chat_model().ainvoke(
                [
                    SystemMessage(content=LOOK_PROMPT),
                    HumanMessage(content=_content(question, pictures)),
                ]
            )
        except Exception as error:  # noqa: BLE001 - a failed look is a tool result, not a crash
            _LOGGER.warning("[look] the model call failed: %s", type(error).__name__)
            return (
                f"The look failed ({type(error).__name__}); try again, or read the image yourself."
            )
        if isinstance(reply, AIMessage):
            publish_usage(reply, role="look", model=model_name, write_ttl="5m")
        answer = _answer(reply) or "(The look came back without an answer.)"
        return answer + ("\n\n" + "\n".join(notes) if notes else "")

    return look


class LookMiddleware(AgentMiddleware[Any, Any, Any]):
    """Gives the lead `look`."""

    def __init__(self, *, model: ModelSource, model_name: str, backend_for: BackendFor) -> None:
        super().__init__()
        self.tools = [make_look_tool(model=model, model_name=model_name, backend_for=backend_for)]

    @property
    def name(self) -> str:
        return "DesignAgentLook"
