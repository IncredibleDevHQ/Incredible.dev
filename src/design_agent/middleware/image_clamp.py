"""Resize inline model images without changing stored messages or sandbox files.

The MIME type is read from the bytes, never trusted from the label: the sandbox's `read_file`
can hand back a valid WebP labeled `application/octet-stream`, and the provider rejects the label
before it looks at the image. A format the model API does not take, or bytes that do not decode,
drop just that block; the text beside it still reaches the model. Existing history is corrected
on the way out too, so a thread holding a mislabeled or oversized image heals on its next call
without its checkpoint being rewritten.
"""

from __future__ import annotations

import base64
import io
from collections.abc import Awaitable, Callable
from typing import cast

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AnyMessage
from PIL import Image

#: Long-edge cap, safely under the model API's 2000px limit for a request with many images.
_MAX_EDGE = 1500
#: The image formats the model API accepts, keyed by what Pillow reads from the bytes.
_MEDIA_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif", "WEBP": "image/webp"}
_Block = str | dict[str, object]


def _shrink(data: object, media_type: object) -> tuple[str, str] | None:
    """Return (base64, MIME) for a supported image, shrunk when oversized; None to drop it.

    Small images keep their exact bytes (and so their transparency); only the label is corrected.
    """
    del media_type  # A label can be wrong; the bytes say what the image is.
    if not isinstance(data, str):
        return None
    try:
        with Image.open(io.BytesIO(base64.b64decode(data, validate=True))) as image:
            mime = _MEDIA_TYPES.get(image.format or "")
            if mime is None:
                return None
            width, height = image.size
            if max(width, height) <= _MAX_EDGE:
                return data, mime
            scale = _MAX_EDGE / max(width, height)
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
            resized = image.convert("RGB").resize(size)
            output = io.BytesIO()
            resized.save(output, format="JPEG", quality=82)
            return base64.b64encode(output.getvalue()).decode("ascii"), "image/jpeg"
    except (ValueError, OSError, SyntaxError, Image.DecompressionBombError):
        # Invalid image bytes are removed, and text in the message is kept.
        return None


def _clamp_block(block: _Block) -> _Block | None:
    if isinstance(block, str):
        return block
    if block.get("type") == "image":
        source = block.get("source")
        if isinstance(source, dict) and source.get("type") == "base64":
            result = _shrink(source.get("data"), source.get("media_type"))
            if result is None:
                return None
            data, mime = result
            return (
                block
                if data == source.get("data") and mime == source.get("media_type")
                else {
                    **block,
                    "source": {**source, "data": data, "media_type": mime},
                }
            )
        field = "data" if block.get("source_type") == "base64" else "base64"
        if field in block:
            result = _shrink(block[field], block.get("mime_type"))
            if result is None:
                return None
            data, mime = result
            if data == block[field] and mime == block.get("mime_type"):
                return block
            return {**block, field: data, "mime_type": mime}
    if block.get("type") == "image_url":
        image_url = block.get("image_url")
        url = image_url.get("url") if isinstance(image_url, dict) else image_url
        if isinstance(url, str) and url.startswith("data:") and ";base64," in url:
            header, original = url.split(",", 1)
            result = _shrink(original, header[5:].split(";")[0])
            if result is None:
                return None
            data, mime = result
            if data == original and mime == header[5:].split(";")[0]:
                return block
            resized_url = f"data:{mime};base64,{data}"
            return {
                **block,
                "image_url": (
                    {**image_url, "url": resized_url}
                    if isinstance(image_url, dict)
                    else resized_url
                ),
            }
    return block


def _clamp_request(request: ModelRequest) -> ModelRequest:
    messages: list[AnyMessage] = []
    changed = False
    for message in request.messages:
        if isinstance(message.content, str):
            messages.append(message)
            continue
        # Message content is the dynamic boundary; all other data stays typed.
        original = cast(list[_Block], message.content)
        content = [result for block in original if (result := _clamp_block(block)) is not None]
        if content == original:
            messages.append(message)
        else:
            changed = True
            messages.append(message.model_copy(update={"content": content}))
    return request.override(messages=messages) if changed else request


class ImageClampMiddleware(AgentMiddleware):
    """Limit inline images to a 1500-pixel long edge before each model call."""

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(_clamp_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(_clamp_request(request))
