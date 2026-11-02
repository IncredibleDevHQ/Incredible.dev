"""Pricing one call from its usage with the price table in config/prices.toml, and summing a
thread's calls per source and per role from the bus."""

from __future__ import annotations

from pathlib import Path

import pytest

from design_agent.harness import events as ev
from design_agent.harness.meter import (
    CURRENT_TASK_ID,
    DEFAULT_PRICES_PATH,
    Meter,
    cost_of,
    default_prices,
    load_prices,
    price_of,
    usage_tokens,
)

PRICES = default_prices()


def _langchain_usage(*, uncached: int, read: int, w5: int = 0, w1: int = 0, out: int = 0) -> dict:
    """`usage_metadata` exactly as langchain-anthropic 1.7.2 builds it (`_create_usage_metadata`)."""
    # With a TTL split, langchain-anthropic zeroes the generic `cache_creation`.
    details: dict = {"cache_read": read, "cache_creation": 0}
    if w5 or w1:
        details |= {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1}
    total = uncached + read + w5 + w1
    return {
        "input_tokens": total,
        "output_tokens": out,
        "total_tokens": total + out,
        "input_token_details": details,
    }


def test_prices_are_the_list_prices_per_mtok() -> None:
    opus55, opus5 = PRICES["claude-opus-5-5"], PRICES["claude-opus-5"]

    assert (opus55.input, opus55.output, opus55.write_5m, opus55.write_1h, opus55.read) == (
        4.0,
        20.0,
        5.0,
        8.0,
        0.20,
    )
    assert (opus5.input, opus5.output, opus5.write_5m, opus5.write_1h, opus5.read) == (
        5.0,
        25.0,
        6.25,
        10.0,
        0.50,
    )
    assert price_of("claude-opus-5-5-20261001") is opus55
    assert price_of("claude-opus-5-20260401") is opus5
    assert price_of("anthropic:claude-opus-5-5") is opus55  # a provider:model spec
    assert price_of("langsmith:anthropic/claude-opus-5-5") is opus55  # a gateway spec
    assert price_of("mistral:mistral-large-3") is None


def test_a_lead_wake_up_that_rewrites_150k_at_1h() -> None:
    cost = cost_of(
        _langchain_usage(uncached=2_000, read=0, w1=150_000, out=1_000), "claude-opus-5-5"
    )

    assert cost.write_usd == pytest.approx(1.20)
    assert cost.input_usd == pytest.approx(0.008)
    assert cost.output_usd == pytest.approx(0.02)
    assert cost.read_usd == 0
    assert cost.usd == pytest.approx(1.228)
    assert (cost.cache_write, cost.input_tokens, cost.output_tokens) == (150_000, 152_000, 1_000)


def test_a_warm_call_is_mostly_reads() -> None:
    cost = cost_of(
        _langchain_usage(uncached=500, read=150_000, w5=3_000, out=800), "claude-opus-5-5"
    )

    assert cost.read_usd == pytest.approx(0.03)
    assert cost.write_usd == pytest.approx(0.015)
    assert cost.hit_ratio == pytest.approx(150_000 / 153_500)


def test_an_unsplit_write_is_priced_at_the_ttl_given() -> None:
    usage = {
        "input_tokens": 110_000,
        "output_tokens": 0,
        "input_token_details": {"cache_read": 0, "cache_creation": 100_000},
    }

    assert cost_of(usage, "claude-opus-5-5").write_usd == pytest.approx(0.50)
    assert cost_of(usage, "claude-opus-5-5", write_ttl="1h").write_usd == pytest.approx(0.80)
    assert cost_of(usage, "claude-opus-5-5").input_usd == pytest.approx(0.04)


def test_the_anthropic_api_usage_works_too() -> None:
    raw = {
        "input_tokens": 1_000,  # the API's: uncached only
        "cache_read_input_tokens": 100_000,
        "cache_creation_input_tokens": 20_000,
        "cache_creation": {"ephemeral_5m_input_tokens": 5_000, "ephemeral_1h_input_tokens": 15_000},
        "output_tokens": 500,
    }

    tokens = usage_tokens(raw)
    cost = cost_of(raw, "claude-opus-5")

    assert (tokens.input, tokens.uncached, tokens.write_5m, tokens.write_1h) == (
        121_000,
        1_000,
        5_000,
        15_000,
    )
    assert cost.write_usd == pytest.approx(5_000 * 6.25e-6 + 15_000 * 10e-6)
    assert cost.read_usd == pytest.approx(0.05)


def test_an_unpriced_model_raises() -> None:
    with pytest.raises(KeyError, match="mistral"):
        cost_of(_langchain_usage(uncached=1, read=0), "mistral-large-3")


def test_missing_or_odd_fields_count_as_zero() -> None:
    assert cost_of({}, "claude-opus-5-5").usd == 0
    tokens = usage_tokens({"input_tokens": None, "input_token_details": {"cache_read": "x"}})
    assert tokens.input == 0 and tokens.cache_read == 0


# -- the meter ------------------------------------------------------------------------------------


def _event(thread: str, source: str, usage: dict, usd: float) -> ev.Event:
    return ev.Event(
        kind=ev.USAGE,
        thread_id=thread,
        source=source,
        label="lead",
        data={"model": "claude-opus-5-5", "usage": usage, "usd": usd},
    )


def test_the_meter_sums_a_thread_per_source_from_the_bus() -> None:
    bus = ev.EventBus()
    meter = Meter(bus)
    lead_call = _langchain_usage(uncached=1_000, read=90_000, w1=9_000, out=500)
    helper_call = _langchain_usage(uncached=100, read=98_000, w5=1_900, out=2_000)

    bus.publish(_event("t1", "lead", lead_call, 0.10))
    bus.publish(_event("t1", "lead", lead_call, 0.10))
    bus.publish(_event("t1", "t-abc123", helper_call, 0.07))
    bus.publish(_event("t2", "lead", lead_call, 5.00))
    bus.publish(ev.Event(kind=ev.TASK_DONE, thread_id="t1", source="t-abc123"))

    summary = meter.summary("t1")

    assert summary.usd == pytest.approx(0.27)
    assert summary.calls == 3
    assert summary.hit_ratio == pytest.approx((90_000 * 2 + 98_000) / (100_000 * 3))
    assert set(summary.by_source) == {"lead", "t-abc123"}
    assert summary.by_source["lead"].calls == 2
    assert summary.by_source["lead"].hit_ratio == pytest.approx(0.90)
    assert summary.by_source["t-abc123"].hit_ratio == pytest.approx(0.98)
    assert summary.by_source["t-abc123"].cache_write == 1_900
    assert summary.by_source["lead"].by_source == {}


def test_a_thread_with_nothing_yet_and_forgetting() -> None:
    meter = Meter(bus=None)
    assert meter.summary("nobody").calls == 0

    meter.record(_event("t1", "lead", _langchain_usage(uncached=10, read=0), 0.01))
    meter.forget("t1")
    assert meter.summary("t1").usd == 0


def test_close_stops_listening() -> None:
    bus = ev.EventBus()
    meter = Meter(bus)
    meter.close()

    bus.publish(_event("t1", "lead", _langchain_usage(uncached=10, read=0), 0.01))

    assert meter.summary("t1").calls == 0


def test_current_task_id_is_unset_for_the_lead() -> None:
    assert CURRENT_TASK_ID.get() is None
    token = CURRENT_TASK_ID.set("t-1")
    try:
        assert CURRENT_TASK_ID.get() == "t-1"
    finally:
        CURRENT_TASK_ID.reset(token)


def test_the_meter_sums_a_thread_per_role_too() -> None:
    meter = Meter(bus=None)
    call = _langchain_usage(uncached=1_000, read=9_000, out=100)
    for source, role, usd in (
        ("lead", "lead", 0.05),
        ("t-aaa111", "builder", 0.20),
        ("t-bbb222", "builder", 0.30),
        ("t-ccc333", "critic", 0.10),
    ):
        meter.record(
            ev.Event(
                ev.USAGE, "t1", source, label=role, data={"role": role, "usage": call, "usd": usd}
            )
        )
    meter.record(ev.Event(ev.USAGE, "t1", "t-ddd444", data={"usage": call, "usd": 0.01}))

    summary = meter.summary("t1")
    assert summary.usd == pytest.approx(0.66) and summary.calls == 5
    assert {role: round(s.usd, 2) for role, s in summary.by_role.items()} == {
        "lead": 0.05,
        "builder": 0.50,
        "critic": 0.10,
        "unknown": 0.01,
    }
    assert summary.by_role["builder"].calls == 2 and summary.by_role["builder"].by_role == {}
    assert len(summary.by_source) == 5


# -- the price table --------------------------------------------------------------------------------


def test_every_listed_price_names_its_date_and_public_source() -> None:
    assert DEFAULT_PRICES_PATH == Path(__file__).resolve().parents[3] / "config" / "prices.toml"
    assert {"claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "gpt-6.1-sol"} <= set(
        PRICES
    )
    for model, price in PRICES.items():
        assert price.provider in ("anthropic", "openai"), model
        assert price.source.startswith("https://") and price.date, model
        assert price.write_1h >= price.write_5m >= price.input > price.read, model


def test_a_prompt_past_the_long_context_threshold_pays_its_prices() -> None:
    short = _langchain_usage(uncached=100_000, read=0, out=1_000)
    long = _langchain_usage(uncached=100_001, read=0, out=1_000)

    assert cost_of(short, "claude-haiku-5-5").usd == pytest.approx(
        100_000 * 0.10e-6 + 1_000 * 0.50e-6
    )
    assert cost_of(long, "claude-haiku-5-5").usd == pytest.approx(
        100_001 * 0.50e-6 + 1_000 * 2.50e-6
    )
    # Cache reads count toward the prompt's length.
    warm = _langchain_usage(uncached=1_000, read=200_000, out=0)
    assert cost_of(warm, "claude-haiku-5-5").read_usd == pytest.approx(200_000 * 0.05e-6)
    # A model without a long-context table pays the same at any length.
    assert cost_of(long, "claude-opus-5-5").input_usd == pytest.approx(100_001 * 4e-6)


def test_an_openai_call_prices_its_cached_input() -> None:
    usage = {
        "input_tokens": 50_000,
        "output_tokens": 2_000,
        "input_token_details": {"cache_read": 40_000},
    }
    cost = cost_of(usage, "openai:gpt-6.1-sol")
    assert cost.input_usd == pytest.approx(10_000 * 2e-6)
    assert cost.read_usd == pytest.approx(40_000 * 0.10e-6)
    assert cost.output_usd == pytest.approx(2_000 * 10e-6)


def test_a_price_file_is_read_with_its_dates_and_sources(tmp_path) -> None:
    path = tmp_path / "prices.toml"
    path.write_text(
        """
[acme]
source = "https://acme.example/pricing"
date = 2026-10-01

[acme.models.acme-1]
input = 1.0
output = 2.0
cache_write_5m = 1.25
cache_write_1h = 2.0
cache_read = 0.1

[acme.models.acme-2]
source = "https://acme.example/pricing/acme-2"
date = 2026-10-09
input = 3
output = 6
cache_write_5m = 3.75
cache_write_1h = 6
cache_read = 0.3
"""
    )
    prices = load_prices(path)
    assert prices["acme-1"].date == "2026-10-01" and prices["acme-1"].provider == "acme"
    assert prices["acme-2"].source == "https://acme.example/pricing/acme-2"
    assert prices["acme-2"].date == "2026-10-09" and prices["acme-2"].input == 3.0
    assert price_of("acme-1-preview", prices) is prices["acme-1"]
    cost = cost_of(_langchain_usage(uncached=1_000_000, read=0), "acme-2", prices=prices)
    assert cost.usd == pytest.approx(3.0)


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        ('[a]\ndate = 2026-10-01\nsource = "https://a.example"\n', "no \\[a.models\\] table"),
        (
            '[a]\ndate = 2026-10-01\nsource = "https://a.example"\n[a.models.m]\ninput = 1\n',
            "output must be a price",
        ),
        (
            "[a.models.m]\ninput = 1\noutput = 1\ncache_write_5m = 1\ncache_write_1h = 1\n"
            "cache_read = 1\n",
            "needs the date it was checked and an https source",
        ),
        (
            '[a]\ndate = 2026-10-01\nsource = "https://a.example"\n[a.models.m]\ninput = -1\n'
            "output = 1\ncache_write_5m = 1\ncache_write_1h = 1\ncache_read = 1\n",
            "input must be a price of 0 or more",
        ),
    ],
)
def test_a_malformed_price_file_says_what_is_wrong(tmp_path, body: str, problem: str) -> None:
    path = tmp_path / "prices.toml"
    path.write_text(body)
    with pytest.raises(ValueError, match=problem):
        load_prices(path)
