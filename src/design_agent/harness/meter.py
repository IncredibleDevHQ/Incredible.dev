"""The cost meter: what each model call cost, summed per job (thread), per source and per role.

A call is priced from all four of its token counts, because the split matters more than the total:
a cache write costs many times a read, so a lead with a healthy hit ratio can still spend most of
its money writing cache. A job's cost is kept per source
(the lead apart from each helper) and per role (lead, builder, critic, ...).

- `load_prices(path)`: list prices per million tokens from `config/prices.toml`, each with the date
  it was checked and its public source. Every figure is an estimate.
- `cost_of(usage, model)`: one call's `Cost`, from LangChain's `usage_metadata` (the Anthropic
  API's own `usage` works too). Cache writes are priced by their TTL when the usage splits them
  (`ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens`), else at `write_ttl`; a prompt past
  a model's long-context threshold pays its long-context prices.
- `Meter`: subscribes to `USAGE` events on the bus and sums them per thread, source and role.
- `CURRENT_TASK_ID`: the helper whose code is running. The adapter that runs helpers sets it, so
  a model call is billed to the helper that made it; unset, a call is the lead's.

Deep Agents has no meter; LangSmith prices traces after the fact. Upstream, this is a callback or
middleware beside the prompt-caching middleware.
"""

from __future__ import annotations

import functools
import logging
import tomllib
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from design_agent.harness import events as ev

_LOGGER = logging.getLogger(__name__)

#: The helper (a `t-...` task id) whose model calls are running; None for the lead's own calls.
CURRENT_TASK_ID: ContextVar[str | None] = ContextVar("harness_current_task_id", default=None)

#: The source of a call made outside any helper.
LEAD = "lead"

#: The repository's price table.
DEFAULT_PRICES_PATH = Path(__file__).resolve().parents[3] / "config" / "prices.toml"

_FIELDS = ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read")


@dataclass(frozen=True)
class Price:
    """USD per million tokens, with where the figures came from.

    `long_context` is the price a request pays once its prompt passes `long_context_above` tokens.
    """

    input: float
    output: float
    write_5m: float
    write_1h: float
    read: float
    provider: str = ""
    date: str = ""
    source: str = ""
    long_context: Price | None = None
    long_context_above: int | None = None

    def write(self, ttl: str) -> float:
        return self.write_1h if ttl == "1h" else self.write_5m

    def for_prompt(self, input_tokens: int) -> Price:
        """The price for a request whose prompt is `input_tokens` long."""
        if self.long_context is not None and self.long_context_above is not None:
            if input_tokens > self.long_context_above:
                return self.long_context
        return self


def _rates(row: Mapping[str, Any], where: str) -> dict[str, float]:
    rates: dict[str, float] = {}
    for name in _FIELDS:
        value = row.get(name)
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise ValueError(f"{where}: {name} must be a price of 0 or more, got {value!r}")
        rates[name] = float(value)
    return rates


def _price(row: Mapping[str, Any], *, provider: str, date: str, source: str, where: str) -> Price:
    rates = _rates(row, where)
    long_context: Price | None = None
    above: int | None = None
    extra = row.get("long_context")
    if extra is not None:
        if not isinstance(extra, Mapping):
            raise ValueError(f"{where}: long_context must be a table")
        above = extra.get("above_input_tokens")
        if isinstance(above, bool) or not isinstance(above, int) or above <= 0:
            raise ValueError(f"{where}: long_context.above_input_tokens must be a token count")
        lc = _rates(extra, f"{where}.long_context")
        long_context = Price(
            lc["input"],
            lc["output"],
            lc["cache_write_5m"],
            lc["cache_write_1h"],
            lc["cache_read"],
            provider=provider,
            date=date,
            source=source,
        )
    return Price(
        rates["input"],
        rates["output"],
        rates["cache_write_5m"],
        rates["cache_write_1h"],
        rates["cache_read"],
        provider=provider,
        date=date,
        source=source,
        long_context=long_context,
        long_context_above=above,
    )


def load_prices(path: Path | str = DEFAULT_PRICES_PATH) -> Mapping[str, Price]:
    """The price table in a TOML file (`config/prices.toml` explains the format), by model id.

    Raises `OSError` when the file can't be read and `ValueError` when a figure, its `date` or its
    `source` is missing or malformed.
    """
    with Path(path).open("rb") as handle:
        data = tomllib.load(handle)
    prices: dict[str, Price] = {}
    for provider, table in data.items():
        if not isinstance(table, Mapping):
            raise ValueError(f"{provider}: expected a table of models")
        models = table.get("models")
        if not isinstance(models, Mapping):
            raise ValueError(f"{provider}: no [{provider}.models] table")
        for model, row in models.items():
            where = f"{provider}.models.{model}"
            if not isinstance(row, Mapping):
                raise ValueError(f"{where}: expected a table")
            date, source = (
                row.get("date", table.get("date")),
                row.get("source", table.get("source")),
            )
            if not date or not isinstance(source, str) or not source.startswith("https://"):
                raise ValueError(f"{where}: needs the date it was checked and an https source")
            prices[str(model)] = _price(
                row, provider=str(provider), date=str(date), source=source, where=where
            )
    return MappingProxyType(prices)


@functools.cache
def default_prices() -> Mapping[str, Price]:
    """The repository's price table, read once; empty (every call unpriced) when it is missing."""
    try:
        return load_prices(DEFAULT_PRICES_PATH)
    except OSError as error:
        _LOGGER.warning("[meter] no price table at %s: %s", DEFAULT_PRICES_PATH, error)
        return MappingProxyType({})


def price_of(model: str, prices: Mapping[str, Price] | None = None) -> Price | None:
    """The price for a model id, or for the longest listed id it extends (a dated snapshot).
    A `provider:model` or gateway `provider:vendor/model` id is looked up by its model part."""
    table = default_prices() if prices is None else prices
    name = model.rpartition(":")[2].rpartition("/")[2]
    if name in table:
        return table[name]
    matches = [listed for listed in table if name.startswith(f"{listed}-")]
    return table[max(matches, key=len)] if matches else None


@dataclass(frozen=True)
class Tokens:
    """One call's token counts. `input` is every prompt token: uncached, written and read."""

    input: int = 0
    uncached: int = 0
    cache_read: int = 0
    write_5m: int = 0
    write_1h: int = 0
    output: int = 0

    @property
    def cache_write(self) -> int:
        return self.write_5m + self.write_1h


def usage_tokens(usage: Mapping[str, Any], *, write_ttl: str = "5m") -> Tokens:
    """Token counts from LangChain's `usage_metadata` or the Anthropic API's `usage`.

    LangChain's `input_tokens` already includes cache reads and writes, with the detail in
    `input_token_details`; the API's `input_tokens` is only the uncached part. A write the usage
    does not split by TTL is counted at `write_ttl`.
    """
    if "cache_read_input_tokens" in usage or "cache_creation_input_tokens" in usage:
        read = _int(usage.get("cache_read_input_tokens"))
        split = usage.get("cache_creation") or {}
        unsplit = _int(usage.get("cache_creation_input_tokens"))
        uncached = _int(usage.get("input_tokens"))
        w5, w1 = _split_writes(split, unsplit, write_ttl)
        total = uncached + read + w5 + w1
    else:
        details = usage.get("input_token_details") or {}
        read = _int(details.get("cache_read"))
        unsplit = _int(details.get("cache_creation"))
        w5, w1 = _split_writes(details, unsplit, write_ttl)
        total = _int(usage.get("input_tokens"))
        uncached = max(0, total - read - w5 - w1)
    return Tokens(
        input=max(total, uncached + read + w5 + w1),
        uncached=uncached,
        cache_read=read,
        write_5m=w5,
        write_1h=w1,
        output=_int(usage.get("output_tokens")),
    )


def _split_writes(details: Mapping[str, Any], unsplit: int, write_ttl: str) -> tuple[int, int]:
    w5 = _int(details.get("ephemeral_5m_input_tokens"))
    w1 = _int(details.get("ephemeral_1h_input_tokens"))
    if w5 or w1:
        return w5, w1
    return (0, unsplit) if write_ttl == "1h" else (unsplit, 0)


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class Cost:
    """One call's cost in USD, by part, with the token counts it came from."""

    usd: float
    input_usd: float
    write_usd: float
    read_usd: float
    output_usd: float
    cache_read: int
    cache_write: int
    input_tokens: int
    output_tokens: int

    @property
    def hit_ratio(self) -> float:
        """The share of prompt tokens read from cache."""
        return self.cache_read / self.input_tokens if self.input_tokens else 0.0


def cost_of(
    usage: Mapping[str, Any],
    model: str,
    *,
    write_ttl: str = "5m",
    prices: Mapping[str, Price] | None = None,
) -> Cost:
    """What one call cost. Raises `KeyError` for a model the price table does not list."""
    price = price_of(model, prices)
    if price is None:
        raise KeyError(f"no price for model {model!r}")
    tokens = usage_tokens(usage, write_ttl=write_ttl)
    price = price.for_prompt(tokens.input)
    per = 1_000_000
    input_usd = tokens.uncached * price.input / per
    write_usd = (tokens.write_5m * price.write_5m + tokens.write_1h * price.write_1h) / per
    read_usd = tokens.cache_read * price.read / per
    output_usd = tokens.output * price.output / per
    return Cost(
        usd=input_usd + write_usd + read_usd + output_usd,
        input_usd=input_usd,
        write_usd=write_usd,
        read_usd=read_usd,
        output_usd=output_usd,
        cache_read=tokens.cache_read,
        cache_write=tokens.cache_write,
        input_tokens=tokens.input,
        output_tokens=tokens.output,
    )


# -- the meter ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class MeterSummary:
    """A job's (a thread's) model spend so far, or one source's or role's share of it.

    `by_source` (the lead, or a helper's task id) and `by_role` (the role a call was made for) are
    empty on a share's own summary.
    """

    usd: float = 0.0
    calls: int = 0
    hit_ratio: float = 0.0
    by_source: Mapping[str, MeterSummary] = field(default_factory=dict)
    by_role: Mapping[str, MeterSummary] = field(default_factory=dict)
    input_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    output_tokens: int = 0


@dataclass
class _Totals:
    usd: float = 0.0
    calls: int = 0
    input_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    output_tokens: int = 0

    def add(self, other: _Totals) -> None:
        self.usd += other.usd
        self.calls += other.calls
        self.input_tokens += other.input_tokens
        self.cache_read += other.cache_read
        self.cache_write += other.cache_write
        self.output_tokens += other.output_tokens

    def summary(
        self,
        by_source: Mapping[str, MeterSummary] | None = None,
        by_role: Mapping[str, MeterSummary] | None = None,
    ) -> MeterSummary:
        return MeterSummary(
            usd=self.usd,
            calls=self.calls,
            hit_ratio=self.cache_read / self.input_tokens if self.input_tokens else 0.0,
            by_source=dict(by_source or {}),
            by_role=dict(by_role or {}),
            input_tokens=self.input_tokens,
            cache_read=self.cache_read,
            cache_write=self.cache_write,
            output_tokens=self.output_tokens,
        )


@dataclass
class _Job:
    sources: dict[str, _Totals] = field(default_factory=dict)
    roles: dict[str, _Totals] = field(default_factory=dict)


#: The role of a call whose event names none.
UNKNOWN_ROLE = "unknown"


class Meter:
    """Sums `USAGE` events per thread, per source (`lead`, or a helper's task id) and per role
    (`data["role"]`, else the event's label).

    It subscribes to `bus` when built (pass `bus=None` and call `record` to feed it by hand) and
    keeps totals in memory; the event log keeps the events themselves.
    """

    def __init__(self, bus: ev.EventBus | None = ev.BUS) -> None:
        self._jobs: dict[str, _Job] = {}
        self._unsubscribe: Callable[[], None] | None = (
            bus.subscribe(self.record) if bus is not None else None
        )

    def record(self, event: ev.Event) -> None:
        if event.kind != ev.USAGE or not event.thread_id:
            return
        data = event.data
        usage = data.get("usage")
        tokens = usage_tokens(usage) if isinstance(usage, Mapping) else Tokens()
        call = _Totals(
            usd=float(data.get("usd") or 0.0),
            calls=1,
            input_tokens=tokens.input or _int(data.get("input_tokens")),
            cache_read=tokens.cache_read or _int(data.get("cache_read")),
            cache_write=tokens.cache_write or _int(data.get("cache_write")),
            output_tokens=tokens.output or _int(data.get("output_tokens")),
        )
        job = self._jobs.setdefault(event.thread_id, _Job())
        job.sources.setdefault(event.source or LEAD, _Totals()).add(call)
        role = str(data.get("role") or event.label or UNKNOWN_ROLE)
        job.roles.setdefault(role, _Totals()).add(call)

    def summary(self, thread_id: str) -> MeterSummary:
        job = self._jobs.get(thread_id, _Job())
        total = _Totals()
        for totals in job.sources.values():
            total.add(totals)
        return total.summary(
            {source: totals.summary() for source, totals in job.sources.items()},
            {role: totals.summary() for role, totals in job.roles.items()},
        )

    def forget(self, thread_id: str) -> None:
        self._jobs.pop(thread_id, None)

    def close(self) -> None:
        """Stop listening to the bus."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
