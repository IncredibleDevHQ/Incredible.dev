"""Model-boundary guards (SPEC §7.9-§7.10): retry classification, image clamp, history repair,
tool disclosure, skill list, cache lifetime, date note."""

from __future__ import annotations

import base64
import io
import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from PIL import Image

from design_agent.middleware import model_retry
from design_agent.middleware.image_clamp import _clamp_block
from design_agent.middleware.skill_list import load_summaries, summarized
from design_agent.middleware.today import Zone, note, readable
from design_agent.middleware.tool_disclosure import ToolSearchMiddleware, search_header
from design_agent.middleware.tool_history import repair_history, sanitize_history
from design_agent.models.cache import CachedChatAnthropic
from design_agent.skills_lock import load_lock

ROOT = Path(__file__).resolve().parents[2]
REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def status_error(code: int) -> anthropic.APIStatusError:
    response = httpx.Response(code, request=REQUEST, json={"error": {"type": "x", "message": "m"}})
    return anthropic.APIStatusError("m", response=response, body=None)


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (anthropic.APIConnectionError(request=REQUEST), "transient"),
        (httpx.ConnectTimeout("c"), "transient"),
        (status_error(429), "transient"),
        (status_error(529), "transient"),
        (httpx.ReadTimeout("r"), "stall"),
        (anthropic.APITimeoutError(request=REQUEST), "stall"),
        (status_error(400), None),
        (status_error(401), None),
        (ValueError("bug"), None),
    ],
)
def test_retry_classifies_by_type(error: BaseException, kind: str | None) -> None:
    classified = model_retry._classify(error)
    assert (classified[0] if classified else None) == kind
    assert model_retry._should_retry(error) is (kind == "transient")  # type: ignore[arg-type]


def png(width: int, height: int, fmt: str = "PNG") -> str:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 80, 40)).save(out, format=fmt)
    return base64.b64encode(out.getvalue()).decode()


def test_image_clamp_trusts_bytes_over_labels_and_shrinks_big_images() -> None:
    webp = png(64, 64, "WEBP")
    fixed = _clamp_block(
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "application/octet-stream", "data": webp},
        }
    )
    assert isinstance(fixed, dict) and fixed["source"]["media_type"] == "image/webp"
    big = _clamp_block(
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": png(4000, 1000)},
        }
    )
    assert isinstance(big, dict)
    with Image.open(io.BytesIO(base64.b64decode(big["source"]["data"]))) as image:
        assert max(image.size) == 1500
    assert (
        _clamp_block(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": "bm90IGFuIGltYWdl"},
            }
        )
        is None
    )


def test_history_drops_references_to_missing_tools_and_repair_folds_their_calls() -> None:
    search = AIMessage(
        content=[
            {
                "type": "tool_search_tool_result",
                "tool_use_id": "s1",
                "content": {
                    "type": "tool_search_tool_search_result",
                    "tool_references": [
                        {"type": "tool_reference", "tool_name": "gone_tool"},
                        {"type": "tool_reference", "tool_name": "kept_tool"},
                    ],
                },
            }
        ]
    )
    call = AIMessage(
        content="", tool_calls=[{"name": "gone_tool", "args": {}, "id": "c1", "type": "tool_call"}]
    )
    result = ToolMessage("the old result", tool_call_id="c1", name="gone_tool")
    history = [HumanMessage("hi"), search, call, result, HumanMessage("next")]
    sent, report = sanitize_history(history, frozenset({"kept_tool"}))
    assert report.dropped_references == ["gone_tool"]
    refs = sent[1].content[0]["content"]["tool_references"]  # type: ignore[index]
    assert [r["tool_name"] for r in refs] == ["kept_tool"]
    assert sent[2] is call, "a call to a missing tool is kept until the provider refuses it"

    repaired, report = repair_history(history, frozenset({"kept_tool"}))
    assert report.folded_calls == ["gone_tool"]
    assert not any(isinstance(m, ToolMessage) for m in repaired)
    assert "the old result" in json.dumps([m.content for m in repaired])


@tool
def docs_SearchPages(query: str) -> str:
    """Find pages."""
    return query


@tool
def write_file(path: str) -> str:
    """Host tool."""
    return path


def test_disclosure_defers_declared_servers_only_and_leads_with_plain_words() -> None:
    assert (
        search_header("docs_SearchPages", "docs")
        == "SearchPages: docs search pages (docs_SearchPages)."
    )
    middleware = ToolSearchMiddleware(servers=["docs"])
    assert middleware._defers(docs_SearchPages) and not middleware._defers(write_file)
    deferred = middleware._deferred(docs_SearchPages)
    assert deferred.extras == {"defer_loading": True}  # type: ignore[union-attr]
    assert deferred.description.startswith("SearchPages: docs search pages")  # type: ignore[union-attr]
    assert not ToolSearchMiddleware(servers=["docs"], always_shown=["docs"])._defers(
        docs_SearchPages
    )


def test_every_vendored_skill_has_a_one_line_summary() -> None:
    summaries = load_summaries(ROOT)
    assert set(summaries) == set(load_lock(ROOT)["skills"])
    assert all(len(line) <= 120 for line in summaries.values())
    data = tomllib.loads((ROOT / "config" / "vendored-skills.toml").read_text())
    assert set(data) == {"summaries"}


def test_the_skill_list_swaps_vendored_descriptions_only() -> None:
    skills = [
        {
            "name": "hyperframes",
            "description": "Mandatory entry point: read this first…",
            "path": "/skills/hyperframes/SKILL.md",
        },
        {
            "name": "stills",
            "description": "On-brand still images.",
            "path": "/skills/stills/SKILL.md",
        },
    ]
    out = summarized(skills, {"hyperframes": "Read first for any video."})
    assert out is not None
    assert [s["description"] for s in out] == [
        "Read first for any video.",
        "On-brand still images.",
    ]
    assert out[1] is skills[1] and skills[0]["description"].startswith("Mandatory"), (
        "inputs untouched"
    )
    assert summarized(out, {"hyperframes": "Read first for any video."}) is None, (
        "stable across calls"
    )


def test_cache_breakpoints_take_the_role_ttl() -> None:
    model = CachedChatAnthropic(model="claude-opus-5-5", api_key="test", cache_ttl="1h")  # type: ignore[call-arg]
    system = SystemMessage(
        content=[
            {"type": "text", "text": "rules", "cache_control": {"type": "ephemeral", "ttl": "5m"}}
        ]
    )
    payload = model._get_request_payload(
        [system, HumanMessage("hi")], cache_control={"type": "ephemeral", "ttl": "5m"}
    )
    assert payload["system"][0]["cache_control"]["ttl"] == "1h"
    assert payload.get("cache_control", {}).get("ttl") in (None, "1h")


def test_helper_clearing_is_off_by_default_and_helper_only() -> None:
    from design_agent.config import Settings
    from design_agent.models.factory import CONTEXT_MANAGEMENT_BETA, build_chat_model

    off = build_chat_model(Settings(_env_file=None), "helper", api_key="t")  # type: ignore[call-arg]
    assert getattr(off, "context_management", None) is None
    on = Settings(_env_file=None, enable_tool_clearing=True)  # type: ignore[call-arg]
    helper = build_chat_model(on, "helper", api_key="t")
    lead = build_chat_model(on, "lead", api_key="t")
    assert helper.context_management["edits"][0]["type"] == "clear_tool_uses_20250919"  # type: ignore[attr-defined]
    assert CONTEXT_MANAGEMENT_BETA in helper.betas  # type: ignore[attr-defined]
    assert getattr(lead, "context_management", None) is None
    assert lead.cache_ttl == "1h" and helper.cache_ttl == "5m"  # type: ignore[attr-defined]


def test_the_date_note_names_the_zone_or_says_it_is_unknown() -> None:
    now = datetime(2026, 10, 17, 23, 30, tzinfo=UTC)
    tokyo: Zone = {"name": "Asia/Tokyo", "whose": "the person's timezone"}
    assert note(now, tokyo).startswith("[Today is Sunday 2026-10-18 in Asia/Tokyo")
    assert "the person's timezone is unknown" in note(now, None)
    assert readable({"name": "Not/AZone", "whose": "x"}) is None


async def test_the_date_note_is_written_once_per_input() -> None:
    from design_agent.middleware.today import TodayMiddleware, fixed_zone

    middleware = TodayMiddleware(
        zone_for=fixed_zone("Europe/Paris"), clock=lambda: datetime(2026, 10, 17, 9, tzinfo=UTC)
    )
    state: dict[str, Any] = {"messages": [HumanMessage("make a card", id="m1")]}
    update = await middleware.abefore_model(state, SimpleNamespace())  # type: ignore[arg-type]
    assert update is not None and "Europe/Paris" in update["messages"][0].content
    state["messages"].append(update["messages"][0])
    assert await middleware.abefore_model(state, SimpleNamespace()) is None  # type: ignore[arg-type]


async def test_the_job_budget_is_told_once_when_spend_reaches_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from design_agent.middleware import budget

    monkeypatch.setattr(budget, "_thread_id", lambda: "t1")
    spend = {"t1": 4.0}
    middleware = budget.JobBudgetMiddleware(5.0, spent=lambda thread: spend[thread])
    state: dict[str, Any] = {"messages": []}
    assert await middleware.abefore_model(state, SimpleNamespace()) is None  # type: ignore[arg-type]
    spend["t1"] = 5.4
    update = await middleware.abefore_model(state, SimpleNamespace())  # type: ignore[arg-type]
    assert (
        update is not None
        and "$5.40" in update["messages"][0].content
        and "ask whether to continue" in update["messages"][0].content
    )
    state.update(update)
    assert await middleware.abefore_model(state, SimpleNamespace()) is None  # type: ignore[arg-type]
