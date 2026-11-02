"""Server-side clearing of old tool results, and what images really cost in tokens."""

from __future__ import annotations

import base64
import io

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from PIL import Image

from design_agent.harness.context import (
    CONTEXT_MANAGEMENT_BETA,
    MAX_IMAGE_TOKENS,
    clear_old_tool_results,
    count_tokens_with_images,
    image_size,
    image_tokens,
    image_tokens_of,
)


def _png(width: int, height: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 40, 40)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _jpeg_with_deep_header(width: int, height: int) -> str:
    """A JPEG whose size marker sits past the first chunk the sizer decodes (~250 KB of APP15)."""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height)).save(buffer, format="JPEG")
    raw = buffer.getvalue()
    padding = b"".join(b"\xff\xef" + (60_002).to_bytes(2, "big") + b"\0" * 60_000 for _ in range(4))
    return base64.b64encode(raw[:2] + padding + raw[2:]).decode()


def test_clear_old_tool_results_is_the_api_shape() -> None:
    assert clear_old_tool_results() == {
        "edits": [
            {
                "type": "clear_tool_uses_20250919",
                "trigger": {"type": "input_tokens", "value": 150_000},
                "keep": {"type": "tool_uses", "value": 6},
                "clear_at_least": {"type": "input_tokens", "value": 60_000},
                "exclude_tools": ["write_todos", "report_progress", "start_task", "check_tasks"],
            }
        ]
    }
    assert CONTEXT_MANAGEMENT_BETA == "context-management-2025-06-27"


def test_clear_old_tool_results_takes_its_knobs() -> None:
    [edit] = clear_old_tool_results(
        200_000, keep=3, clear_at_least=80_000, exclude_tools=(), clear_tool_inputs=True
    )["edits"]

    assert edit["trigger"]["value"] == 200_000
    assert edit["keep"]["value"] == 3
    assert edit["clear_at_least"]["value"] == 80_000
    assert "exclude_tools" not in edit
    assert edit["clear_tool_inputs"] is True


@pytest.mark.parametrize(
    ("size", "tokens"),
    [
        ((1920, 1080), 2691),
        ((960, 540), 700),
        ((640, 360), 299),
        ((3840, 2160), 4784),  # scaled to 2576 x 1449 first
        ((4000, 4000), MAX_IMAGE_TOKENS),  # over 3.75 MP after scaling: capped
        ((28, 28), 1),
        ((29, 1), 2),
        ((0, 100), 0),
    ],
)
def test_image_tokens(size: tuple[int, int], tokens: int) -> None:
    assert image_tokens(*size) == tokens


def test_image_tokens_after_the_apps_own_clamp() -> None:
    # ImageClampMiddleware sends a 1080p frame at 1500 x 844.
    assert image_tokens(1920, 1080, max_edge=1500) == 54 * 31


def test_image_size_reads_base64_data_urls_and_bytes() -> None:
    png = _png(300, 200)

    assert image_size(png) == (300, 200)
    assert image_size(f"data:image/png;base64,{png}") == (300, 200)
    assert image_size(base64.b64decode(png)) == (300, 200)
    assert image_size("not base64 at all!") is None
    assert image_size(base64.b64encode(b"plain text").decode()) is None


@pytest.mark.parametrize(
    ("fmt", "mode"),
    [
        ("PNG", "RGBA"),
        ("JPEG", "RGB"),
        ("GIF", "RGB"),
        ("WEBP", "RGB"),
        ("WEBP", "RGBA"),
        ("BMP", "RGB"),
    ],
)
def test_image_size_reads_each_format_from_its_header(fmt: str, mode: str) -> None:
    buffer = io.BytesIO()
    Image.new(mode, (321, 123)).save(buffer, format=fmt)
    assert image_size(buffer.getvalue()) == (321, 123)


def test_image_size_reads_progressive_jpegs_and_rejects_truncated_ones() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (640, 360)).save(buffer, format="JPEG", progressive=True)
    raw = buffer.getvalue()
    assert image_size(raw) == (640, 360)
    assert image_size(raw[:20]) is None
    assert image_size(b"\x89PNG\r\n\x1a\n") is None


def test_image_size_falls_back_to_the_whole_image_when_the_header_is_deep() -> None:
    deep = _jpeg_with_deep_header(1280, 720)

    assert len(deep) > 262_144
    assert image_size(deep) == (1280, 720)


def test_image_tokens_of_every_block_shape() -> None:
    png = _png(960, 540)
    shapes = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": png}},
        {"type": "image", "base64": png, "mime_type": "image/png"},
        {"type": "image", "source_type": "base64", "data": png, "mime_type": "image/png"},
        {"type": "image", "url": f"data:image/png;base64,{png}"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png}"}},
        {"type": "image_url", "image_url": f"data:image/png;base64,{png}"},
        {
            "type": "tool_result",
            "tool_use_id": "x",
            "content": [{"type": "text", "text": "ok"}, {"type": "image", "base64": png}],
        },
    ]

    assert [image_tokens_of(block) for block in shapes] == [700] * len(shapes)


def test_images_without_bytes_cost_the_most_and_broken_ones_nothing() -> None:
    assert (
        image_tokens_of({"type": "image", "url": "https://example.com/a.png"}) == MAX_IMAGE_TOKENS
    )
    assert (
        image_tokens_of({"type": "image", "source": {"type": "file", "file_id": "f"}})
        == MAX_IMAGE_TOKENS
    )
    assert (
        image_tokens_of({"type": "image_url", "image_url": {"url": "https://x/y.png"}})
        == MAX_IMAGE_TOKENS
    )
    assert image_tokens_of({"type": "image", "base64": "AAAA"}) == 0
    assert image_tokens_of({"type": "text", "text": "hello"}) == 0
    assert image_tokens_of("a string block") == 0


def test_count_tokens_with_images_charges_the_real_image_cost() -> None:
    frame = _png(1920, 1080)
    messages = [
        HumanMessage("Review the render."),
        AIMessage("", tool_calls=[{"name": "read_file", "args": {"path": "f.png"}, "id": "c1"}]),
        ToolMessage(
            content=[{"type": "image", "base64": frame, "mime_type": "image/png"}],
            tool_call_id="c1",
        ),
    ]

    langchain = count_tokens_approximately(messages)
    ours = count_tokens_with_images(messages)

    assert ours - (langchain - 85) == 2691
    assert count_tokens_with_images(messages, max_edge=1500) == ours - 2691 + 54 * 31


def test_count_tokens_with_images_matches_langchain_without_images() -> None:
    messages = [HumanMessage("hello there"), AIMessage("hi, how can I help?")]
    tools = [{"name": "t", "description": "d", "input_schema": {"type": "object"}}]

    assert count_tokens_with_images(messages, tools=tools) == count_tokens_approximately(
        messages, tools=tools
    )
