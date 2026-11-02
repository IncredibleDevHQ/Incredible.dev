"""The cache policy on request payloads, the TTL choice, the fan-out gate and the prefix watch."""

from __future__ import annotations

import asyncio
import copy
import logging
import time

import pytest

from design_agent.harness import cache
from design_agent.harness.cache import (
    CachePolicy,
    PrefixWatch,
    StaggerGate,
    apply_cache_policy,
    count_breakpoints,
    prefix_fingerprint,
)

SEARCH = {"type": "tool_search_tool_bm25_20251119", "name": "tool_search_tool_bm25"}
H1 = {"type": "ephemeral", "ttl": "1h"}
M5 = {"type": "ephemeral", "ttl": "5m"}


def _tool(name: str, **extra: object) -> dict[str, object]:
    return {"name": name, "description": name, "input_schema": {"type": "object"}, **extra}


def _payload() -> dict[str, object]:
    """The lead's request as langchain-anthropic builds it: three breakpoints, none on tools."""
    return {
        "model": "claude-opus-5-5",
        "cache_control": M5,
        "tools": [_tool("render"), _tool("notion__search", defer_loading=True), SEARCH],
        "system": [
            {"type": "text", "text": "You are the lead.", "cache_control": M5},
            {"type": "text", "text": "<agent_memory/>", "cache_control": {"type": "ephemeral"}},
        ],
        "messages": [
            {"role": "user", "content": "make a film"},
            {"role": "assistant", "content": [{"type": "text", "text": "On it."}]},
            {"role": "user", "content": [{"type": "text", "text": "thanks"}]},
        ],
    }


def test_every_breakpoint_gets_the_ttl_and_the_tools_get_one() -> None:
    result = apply_cache_policy(_payload(), "1h")

    assert result["cache_control"] == H1
    assert [b["cache_control"] for b in result["system"]] == [H1, H1]
    assert result["tools"][-1] == {**SEARCH, "cache_control": H1}
    assert "cache_control" not in result["tools"][0]
    assert count_breakpoints(result) == 4


def test_the_input_payload_is_never_changed() -> None:
    payload = _payload()
    before = copy.deepcopy(payload)

    apply_cache_policy(payload, "1h")

    assert payload == before


def test_a_deferred_last_tool_is_skipped_for_the_last_one_sent_up_front() -> None:
    payload = {"tools": [_tool("render"), _tool("remote__a", defer_loading=True)]}

    result = apply_cache_policy(payload, "5m")

    assert result["tools"][0]["cache_control"] == M5
    assert "cache_control" not in result["tools"][1]


def test_a_tool_that_already_carries_one_is_retagged_not_duplicated() -> None:
    payload = {"tools": [_tool("a", cache_control=M5), _tool("b")]}

    result = apply_cache_policy(payload, "1h")

    assert [t.get("cache_control") for t in result["tools"]] == [H1, None]


def test_message_blocks_and_nested_tool_result_blocks_are_retagged() -> None:
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "x",
                        "content": [{"type": "text", "text": "ok", "cache_control": M5}],
                    },
                    {"type": "text", "text": "next", "cache_control": M5},
                ],
            }
        ]
    }

    result = apply_cache_policy(payload, "1h")

    blocks = result["messages"][0]["content"]
    assert blocks[0]["content"][0]["cache_control"] == H1
    assert blocks[1]["cache_control"] == H1


def test_a_schema_property_named_cache_control_is_left_alone() -> None:
    schema = {"type": "object", "properties": {"cache_control": {"type": "string"}}}
    payload = {"tools": [{"name": "t", "input_schema": schema}]}

    result = apply_cache_policy(payload, "1h")

    assert result["tools"][0]["input_schema"] == schema
    assert result["tools"][0]["cache_control"] == H1


def test_the_tools_breakpoint_is_dropped_when_it_would_be_a_fifth(caplog, monkeypatch) -> None:
    monkeypatch.setattr(cache, "_WARNED", set())  # the warning is logged once per process
    payload = _payload()
    payload["messages"][2]["content"][0]["cache_control"] = M5  # a fourth, on the history

    with caplog.at_level(logging.WARNING, logger="harness.cache"):
        result = apply_cache_policy(payload, "1h")

    assert not any("cache_control" in t for t in result["tools"])
    assert count_breakpoints(result) == 4
    assert "no tools breakpoint" in caplog.text


def test_a_payload_for_another_provider_passes_through_unchanged() -> None:
    """OpenAI-style function tools take no `cache_control`; nothing in the payload says to cache."""
    payload = {
        "model": "gpt-6.1-sol",
        "tools": [
            {"type": "function", "function": {"name": "render", "parameters": {"type": "object"}}},
            {"type": "function", "name": "look", "parameters": {"type": "object"}},
        ],
        "messages": [{"role": "user", "content": "make a film"}],
    }
    before = copy.deepcopy(payload)

    assert apply_cache_policy(payload, "1h") == before
    assert count_breakpoints(payload) == 0


def test_no_tools_and_no_breakpoints_is_a_no_op() -> None:
    payload = {"model": "m", "system": "plain", "messages": [{"role": "user", "content": "hi"}]}

    assert apply_cache_policy(payload, "5m") == payload


def test_an_unknown_ttl_is_refused() -> None:
    with pytest.raises(ValueError, match="cache TTL"):
        apply_cache_policy(_payload(), "10m")


# -- the policy ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gap", "ttl"),
    [(0, "5m"), (299, "5m"), (300, "1h"), (1200, "1h"), (3600, "1h"), (3601, "5m")],
)
def test_choose_ttl_by_the_gap_between_calls(gap: float, ttl: str) -> None:
    assert CachePolicy.choose_ttl(gap) == ttl


def test_the_lead_and_roles_have_their_own_ttl() -> None:
    policy = CachePolicy(lead="1h", default="5m", roles={"critic": "1h"})

    assert policy.ttl_for(None) == "1h"
    assert policy.ttl_for("lead") == "1h"
    assert policy.ttl_for("xhigh") == "5m"
    assert policy.ttl_for("critic") == "1h"
    with pytest.raises(ValueError):
        CachePolicy(lead="2h")


# -- fan-out ---------------------------------------------------------------------------------------


async def test_the_first_sibling_goes_and_the_rest_wait_for_its_response() -> None:
    gate = StaggerGate(max_wait=5.0)
    order: list[str] = []

    async def sibling(name: str) -> None:
        await gate.enter("act-wave")
        order.append(name)

    await gate.enter("act-wave")  # the leader
    waiting = [asyncio.create_task(sibling(f"s{i}")) for i in range(2)]
    await asyncio.sleep(0.05)
    assert order == []

    gate.first_response("act-wave")
    await asyncio.wait_for(asyncio.gather(*waiting), timeout=1.0)

    assert sorted(order) == ["s0", "s1"]
    started = time.monotonic()
    await gate.enter("act-wave")  # a released wave lets latecomers straight in
    assert time.monotonic() - started < 0.05


async def test_siblings_go_after_max_wait_even_without_a_response() -> None:
    gate = StaggerGate(max_wait=0.1)
    await gate.enter("w")

    started = time.monotonic()
    await gate.enter("w")

    assert 0.05 <= time.monotonic() - started < 1.0


async def test_waves_are_independent() -> None:
    gate = StaggerGate(max_wait=5.0)
    await gate.enter("a")

    await asyncio.wait_for(gate.enter("b"), timeout=0.1)  # b's first caller leads b


# -- the prefix watch ------------------------------------------------------------------------------


def test_the_fingerprint_ignores_moving_breakpoints() -> None:
    one = _payload()
    two = apply_cache_policy(_payload(), "1h")

    assert prefix_fingerprint(one) == prefix_fingerprint(two)
    assert len(prefix_fingerprint(one)["messages"]) == 3


def test_the_watch_is_quiet_while_history_only_grows(caplog) -> None:
    watch = PrefixWatch()
    first = _payload()
    second = _payload()
    second["messages"].append({"role": "assistant", "content": [{"type": "text", "text": "ok"}]})

    with caplog.at_level(logging.WARNING, logger="harness.cache"):
        assert watch.observe("t1/lead", first) == []
        assert watch.observe("t1/lead", second) == []

    assert caplog.text == ""


def test_the_watch_names_what_changed(caplog) -> None:
    watch = PrefixWatch()
    watch.observe("t1/lead", _payload())
    ticked = _payload()
    ticked["system"][0]["text"] = "You are the lead. (act 3, 4 min)"

    with caplog.at_level(logging.WARNING, logger="harness.cache"):
        assert watch.observe("t1/lead", ticked) == ["system"]

    assert "prefix changed for t1/lead: system" in caplog.text
    tools_changed = _payload()
    tools_changed["tools"] = tools_changed["tools"][:-1]
    assert watch.observe("t1/lead", tools_changed) == ["tools", "system"]


def test_the_watch_catches_an_edited_history_but_not_a_grown_last_message() -> None:
    watch = PrefixWatch()
    watch.observe("k", _payload())

    grown = _payload()
    grown["messages"][2]["content"].append({"type": "text", "text": "and one more thing"})
    assert watch.observe("k", grown) == []

    trimmed = _payload()
    trimmed["messages"][1]["content"] = [{"type": "text", "text": "[cleared]"}]
    assert watch.observe("k", trimmed) == ["messages[1]"]


def test_keys_are_separate_and_bounded() -> None:
    watch = PrefixWatch(max_keys=2)
    watch.observe("a", _payload())
    other = _payload()
    other["system"] = "a helper's prompt"

    assert watch.observe("b", other) == []
    watch.observe("c", other)
    assert watch.observe("a", other) == []  # "a" was evicted: a first sighting again
