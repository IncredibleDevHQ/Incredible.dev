"""Context size: clearing old tool results the way the API accepts, and what images really cost.

Clearing on the server. Claude models that keep earlier thinking blocks ("preserved thinking")
reject a request that edits history before a replayed thinking block (drops a tool result, trims
old turns), for accounts the check is enforced on. Anthropic's own context editing is exempt: the
client keeps sending the whole history and the server clears old tool results before the model
reads it. `clear_old_tool_results` builds that edit for helper models on Anthropic's API; it is
an opt-in request field, so it does nothing for a provider that is not sent it. Each clear rewrites
the cache from the first cleared result, so it clears in batches (`clear_at_least`).

Counting images. LangChain's `count_tokens_approximately`, which Deep Agents' summarization uses,
charges every image a flat 85 tokens, while Claude bills an image by its 28 x 28 pixel patches (a
1080p frame is 2,691 tokens), so an image-heavy thread is undercounted many times over and
summarization barely fires. `image_tokens` is that cost and `count_tokens_with_images` a drop-in
counter; for other providers it is an estimate on the same scale. Image sizes are read from the
file header (PNG, JPEG, GIF, WebP, BMP) with the standard library.

Deep Agents' summarization summarizes on the client; langchain's `ClearToolUsesEdit` clears
client-side too. Upstream, a `context_management` field on a subagent spec would carry this edit.
"""

from __future__ import annotations

import base64
import binascii
import math
import struct
from collections.abc import Iterable, Sequence
from typing import Any

from langchain_core.messages import convert_to_messages
from langchain_core.messages.utils import count_tokens_approximately

#: The Anthropic beta header a request needs for `context_management`.
CONTEXT_MANAGEMENT_BETA = "context-management-2025-06-27"
#: The edit that clears old tool results on the server.
CLEAR_TOOL_USES = "clear_tool_uses_20250919"

#: What never gets cleared by default: the plan, and the lead-helper channel.
DEFAULT_EXCLUDED_TOOLS = ("write_todos", "report_progress", "start_task", "check_tasks")

#: An image is billed in 28 x 28 pixel patches.
PATCH_PX = 28
#: The API scales an image down to this long edge first.
MAX_IMAGE_EDGE_PX = 2576
#: ...and to at most this many patches (about 3.75 megapixels).
MAX_IMAGE_TOKENS = 4784
#: Base64 characters decoded to read an image's size from its header (a multiple of 4).
_HEADER_CHARS = 262_144


def clear_old_tool_results(
    trigger_tokens: int = 150_000,
    keep: int = 6,
    clear_at_least: int = 60_000,
    exclude_tools: Sequence[str] = DEFAULT_EXCLUDED_TOOLS,
    *,
    clear_tool_inputs: bool = False,
) -> dict[str, Any]:
    """The `context_management` value that clears old tool results on the server.

    Once a request's input passes `trigger_tokens`, the API replaces the oldest tool results
    with a placeholder, keeping the `keep` most recent tool uses and every use of
    `exclude_tools`, and only when that frees at least `clear_at_least` tokens. The client keeps
    the full history; the server re-applies the edit on every request. `clear_tool_inputs` also
    clears the calls' arguments (off: the model keeps its record of what it did).

    Send it as an Anthropic request's `context_management`, with the `CONTEXT_MANAGEMENT_BETA`
    beta header.
    """
    edit: dict[str, Any] = {
        "type": CLEAR_TOOL_USES,
        "trigger": {"type": "input_tokens", "value": trigger_tokens},
        "keep": {"type": "tool_uses", "value": keep},
        "clear_at_least": {"type": "input_tokens", "value": clear_at_least},
    }
    if exclude_tools:
        edit["exclude_tools"] = list(exclude_tools)
    if clear_tool_inputs:
        edit["clear_tool_inputs"] = True
    return {"edits": [edit]}


# -- images -------------------------------------------------------------------------------------


def image_tokens(width: int, height: int, *, max_edge: int = MAX_IMAGE_EDGE_PX) -> int:
    """What one image of `width` x `height` pixels costs as input to a current Claude model.

    The image is scaled to fit `max_edge` on its long side (the API's 2576 px, or a smaller
    clamp the app applies first), then billed
    ceil(w/28) * ceil(h/28), never more than 4,784. 1920x1080 is 2,691; 960x540 is 700.
    """
    if width <= 0 or height <= 0:
        return 0
    limit = min(max_edge, MAX_IMAGE_EDGE_PX)
    longest = max(width, height)
    if longest > limit:
        scale = limit / longest
        width, height = max(1, round(width * scale)), max(1, round(height * scale))
    patches = math.ceil(width / PATCH_PX) * math.ceil(height / PATCH_PX)
    return min(patches, MAX_IMAGE_TOKENS)


def image_size(data: bytes | str) -> tuple[int, int] | None:
    """An image's (width, height) from its bytes, base64, or a `data:` URL; None if unreadable.

    Only the header is decoded when that is enough, so sizing a large image stays cheap.
    """
    if isinstance(data, str):
        encoded = data.split(",", 1)[1] if data.startswith("data:") else data
        encoded = "".join(encoded.split())
        head = encoded[:_HEADER_CHARS]
        try:
            size = _size_of(base64.b64decode(head))
            if size is None and len(encoded) > len(head):
                size = _size_of(base64.b64decode(encoded))
        except (binascii.Error, ValueError):
            return None
        return size
    return _size_of(data)


def _size_of(raw: bytes) -> tuple[int, int] | None:
    """(width, height) from an image's header: PNG, JPEG, GIF, WebP or BMP; None otherwise."""
    size: tuple[int, int] | None = None
    if raw.startswith(b"\x89PNG\r\n\x1a\n") and raw[12:16] == b"IHDR" and len(raw) >= 24:
        size = struct.unpack(">II", raw[16:24])
    elif raw.startswith((b"GIF87a", b"GIF89a")) and len(raw) >= 10:
        size = struct.unpack("<HH", raw[6:10])
    elif raw.startswith(b"\xff\xd8"):
        size = _jpeg_size(raw)
    elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        size = _webp_size(raw)
    elif raw.startswith(b"BM") and len(raw) >= 26:
        width, height = struct.unpack("<ii", raw[18:26])
        size = (width, abs(height))
    if size is None or size[0] <= 0 or size[1] <= 0:
        return None
    return size


#: JPEG start-of-frame markers, which carry the size (not DHT, JPG or DAC, which share the range).
_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def _jpeg_size(raw: bytes) -> tuple[int, int] | None:
    at = 2
    while at + 4 <= len(raw):
        if raw[at] != 0xFF:
            return None
        marker = raw[at + 1]
        if marker == 0xFF:  # fill byte
            at += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:  # markers without a length
            at += 2
            continue
        if marker == 0xDA:  # image data starts before any frame header
            return None
        if marker in _SOF:
            if at + 9 > len(raw):
                return None
            height, width = struct.unpack(">HH", raw[at + 5 : at + 9])
            return width, height
        at += 2 + struct.unpack(">H", raw[at + 2 : at + 4])[0]
    return None


def _webp_size(raw: bytes) -> tuple[int, int] | None:
    chunk = raw[12:16]
    if chunk == b"VP8 " and len(raw) >= 30 and raw[23:26] == b"\x9d\x01\x2a":
        width, height = struct.unpack("<HH", raw[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L" and len(raw) >= 25 and raw[20] == 0x2F:
        bits = int.from_bytes(raw[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X" and len(raw) >= 30:
        return 1 + int.from_bytes(raw[24:27], "little"), 1 + int.from_bytes(raw[27:30], "little")
    return None


def image_tokens_of(block: Any, *, max_edge: int = MAX_IMAGE_EDGE_PX) -> int:
    """The image cost of one content block: 0 when it is not an image.

    Reads the Anthropic block (`source.type == "base64"`), LangChain's standard blocks (`base64`,
    or `source_type="base64"` with `data`), OpenAI's `image_url` with a `data:` URL, and an
    Anthropic `tool_result` block's nested images. An image known only by URL or file id is
    charged the most one image can cost; bytes that do not decode as an image cost 0 (the image
    clamp drops them before the request goes out).
    """
    if not isinstance(block, dict):
        return 0
    kind = block.get("type")
    if kind == "tool_result":
        inner = block.get("content")
        if isinstance(inner, list):
            return sum(image_tokens_of(item, max_edge=max_edge) for item in inner)
        return 0
    data: str | None = None
    if kind == "image":
        source = block.get("source")
        if isinstance(source, dict):
            if source.get("type") != "base64":
                return MAX_IMAGE_TOKENS
            data = source.get("data")
        elif isinstance(block.get("base64"), str):
            data = block["base64"]
        elif block.get("source_type") == "base64":
            data = block.get("data")
        else:
            url = block.get("url")
            if not (isinstance(url, str) and url.startswith("data:")):
                return MAX_IMAGE_TOKENS
            data = url
    elif kind == "image_url":
        image_url = block.get("image_url")
        url = image_url.get("url") if isinstance(image_url, dict) else image_url
        if not (isinstance(url, str) and url.startswith("data:")):
            return MAX_IMAGE_TOKENS
        data = url
    else:
        return 0
    if not isinstance(data, str):
        return 0
    size = image_size(data)
    return image_tokens(*size, max_edge=max_edge) if size else 0


def count_tokens_with_images(
    messages: Iterable[Any],
    *,
    tools: list[Any] | None = None,
    max_edge: int = MAX_IMAGE_EDGE_PX,
    chars_per_token: float = 4.0,
) -> int:
    """`count_tokens_approximately`, with each image at its real cost instead of 85 tokens.

    Text stays at about four characters a token, with the same per-message overhead and tool
    schemas as LangChain's counter, so a thread without images counts the same. Accepts `tools`,
    which is how deepagents' summarization decides to pass the tool schemas in.
    """
    converted = convert_to_messages(list(messages))
    text = count_tokens_approximately(
        converted, chars_per_token=chars_per_token, tokens_per_image=0, tools=tools
    )
    images = sum(
        image_tokens_of(block, max_edge=max_edge)
        for message in converted
        if isinstance(message.content, list)
        for block in message.content
        if isinstance(block, dict) and block.get("type") in ("image", "image_url")
    )
    return text + images
