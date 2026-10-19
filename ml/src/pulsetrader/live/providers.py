"""Market data providers (spec section 43).

Every provider gives the pipeline two things: `history()` (warm-up minute bars before the session,
so long indicator windows are filled) and `bars()` (closed 1-minute bars as they happen).

- `HistoricalProvider` replays recorded canonical sessions. `is_live` is False, so the feed state is
  REPLAY and nothing it produces is ever labelled LIVE. Test-period sessions are refused unless
  PULSETRADER_ALLOW_TEST_PERIOD=1, so replay cannot quietly evaluate the untouched test period.
- `SnapshotProvider` returns the latest stored bar per symbol (what the dashboard can show when no
  live feed runs).
- `LiveProvider` turns a tick stream into bars with the candle aggregator; `kite.KiteProvider` is the
  Zerodha Kite Connect implementation.
- `MockProvider` produces scripted ticks for tests and refuses to start outside tests.
"""

from __future__ import annotations

import asyncio
import json
import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from pulsetrader.data.io import safe_name
from pulsetrader.live.candles import CandleAggregator
from pulsetrader.live.events import Bar, Tick

WARMUP_SESSIONS = 5


class ProviderError(RuntimeError):
    pass


class ReservedPeriodError(PermissionError):
    pass


def test_period_start(data_root: Path) -> date | None:
    for m in sorted((data_root / "datasets").glob("*/dataset_manifest.json")):
        test = next((p for p in json.loads(m.read_text()).get("periods", []) if p["name"] == "test"), None)
        if test:
            return date.fromisoformat(test["start"])
    return None


def canonical_sessions(data_root: Path, symbols: Iterable[str], first: date, last: date) -> pl.DataFrame:
    """Canonical 1-minute bars of `symbols` with first <= trade_date <= last."""
    frames = []
    for s in symbols:
        f = data_root / "canonical" / f"{safe_name(s)}.parquet"
        if f.exists():
            frames.append(
                pl.scan_parquet(f)
                .filter(pl.col("trade_date").is_between(first, last))
                .select("symbol", "ts", "open", "high", "low", "close", "volume", "trade_date")
                .collect()
            )
    if not frames:
        raise ProviderError(f"no canonical bars for {first}..{last}")
    return pl.concat(frames).sort("symbol", "ts")


def session_dates(data_root: Path) -> list[date]:
    """Recorded trading sessions (from the Phase 3 daily bars)."""
    f = data_root / "reference" / "day_bars.parquet"
    if not f.exists():
        raise ProviderError(f"no daily reference bars at {f}")
    out = pl.scan_parquet(f).select(pl.col("trade_date").unique()).collect()["trade_date"].sort()
    return list(out)


class MarketDataProvider(ABC):
    name: str = "provider"
    is_live: bool = False
    connected: bool = False

    @abstractmethod
    def history(self, symbols: list[str]) -> pl.DataFrame:
        """Warm-up bars before the session being streamed."""

    @abstractmethod
    def bars(self, symbols: list[str]) -> AsyncIterator[Bar]:
        """Closed 1-minute bars in arrival order."""

    async def close(self) -> None:
        self.connected = False


@dataclass
class HistoricalProvider(MarketDataProvider):
    """Replays one recorded session bar by bar (`speed` x real time; 0 = as fast as possible)."""

    data_root: Path
    day: date
    speed: float = 0.0
    warmup_sessions: int = WARMUP_SESSIONS
    allow_test: bool = field(default_factory=lambda: os.environ.get("PULSETRADER_ALLOW_TEST_PERIOD") == "1")
    name: str = "historical-replay"
    is_live: bool = False
    connected: bool = False

    def __post_init__(self) -> None:
        start = test_period_start(self.data_root)
        if start is not None and self.day >= start and not self.allow_test:
            raise ReservedPeriodError(
                f"{self.day} is in the reserved test period (from {start}); replay refused "
                "(set PULSETRADER_ALLOW_TEST_PERIOD=1 only for the final evaluation)"
            )
        dates = session_dates(self.data_root)
        if self.day not in dates:
            raise ProviderError(f"{self.day} is not a recorded session")
        i = dates.index(self.day)
        self._warm = dates[max(0, i - self.warmup_sessions) : i]

    def history(self, symbols: list[str]) -> pl.DataFrame:
        if not self._warm:
            raise ProviderError(f"no sessions before {self.day}")
        return canonical_sessions(self.data_root, symbols, self._warm[0], self._warm[-1])

    async def bars(self, symbols: list[str]) -> AsyncIterator[Bar]:
        day = canonical_sessions(self.data_root, symbols, self.day, self.day).sort("ts", "symbol")
        self.connected = True
        prev: datetime | None = None
        for s, ts, o, h, lo, c, v, _ in day.iter_rows():
            if self.speed > 0 and prev is not None and ts > prev:
                await asyncio.sleep((ts - prev).total_seconds() / self.speed)
            prev = ts
            # a recorded bar is "received" the moment it closes: replay has no network latency
            yield Bar(s, ts, o, h, lo, c, v, received=ts + timedelta(minutes=1))
        self.connected = False


@dataclass
class SnapshotProvider:
    """Latest stored bar per symbol from the canonical store. Not live data."""

    data_root: Path
    name: str = "canonical-snapshot"
    is_live: bool = False

    def latest(self, symbols: list[str]) -> dict[str, Bar]:
        out = {}
        for s in symbols:
            f = self.data_root / "canonical" / f"{safe_name(s)}.parquet"
            if not f.exists():
                continue
            r = pl.scan_parquet(f).sort("ts").tail(1).collect()
            if r.height:
                x = r.row(0, named=True)
                out[s] = Bar(s, x["ts"], x["open"], x["high"], x["low"], x["close"], x["volume"])
        return out


class LiveProvider(MarketDataProvider):
    """Base for real-time providers: subclasses yield ticks, this class turns them into bars."""

    is_live = True
    flush_every = timedelta(seconds=1)

    def __init__(self, cumulative_volume: bool = True) -> None:
        self.agg = CandleAggregator(cumulative_volume=cumulative_volume)

    def now(self) -> datetime:
        return datetime.now(UTC)

    @abstractmethod
    def ticks(self, symbols: list[str]) -> AsyncIterator[Tick]: ...

    async def bars(self, symbols: list[str]) -> AsyncIterator[Bar]:
        queue: asyncio.Queue[Bar | None] = asyncio.Queue()

        async def pump() -> None:
            try:
                async for t in self.ticks(symbols):
                    for b in self.agg.add(t):
                        # available when the aggregator closes it, not when its last tick came in
                        queue.put_nowait(replace(b, received=self.now()))
            finally:
                queue.put_nowait(None)

        async def flusher() -> None:
            while True:
                await asyncio.sleep(self.flush_every.total_seconds())
                now = self.now()
                for b in self.agg.flush(now):
                    queue.put_nowait(replace(b, received=now))

        tasks = [asyncio.create_task(pump()), asyncio.create_task(flusher())]
        try:
            while (b := await queue.get()) is not None:
                yield b
            await asyncio.wait([tasks[0]])
            if (exc := tasks[0].exception()) is not None:
                raise ProviderError(f"{self.name}: tick stream failed: {exc}") from exc
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        # tick stream ended: close the bars still open
        for b in self.agg.flush(datetime.max.replace(tzinfo=UTC)):
            yield replace(b, received=max(self.now(), b.close_ts))


class MockProvider(LiveProvider):
    """Scripted ticks for tests only (spec: MockProvider is test-only)."""

    name = "mock"

    def __init__(self, ticks: list[Tick], history: pl.DataFrame | None = None) -> None:
        if os.environ.get("PULSETRADER_TESTING") != "1" and "PYTEST_CURRENT_TEST" not in os.environ:
            raise ProviderError("MockProvider is test-only and refuses to run outside tests")
        super().__init__(cumulative_volume=True)
        self._ticks = ticks
        self._history = history
        self._clock: datetime | None = None

    def now(self) -> datetime:
        # scripted time: the latest tick seen (ticks are stamped at the exchange)
        return self._clock or datetime.now(UTC)

    def history(self, symbols: list[str]) -> pl.DataFrame:
        if self._history is None:
            raise ProviderError("mock provider has no history")
        return self._history

    async def ticks(self, symbols: list[str]) -> AsyncIterator[Tick]:
        self.connected = True
        for t in self._ticks:
            if t.symbol in symbols:
                self._clock = max(self._clock or t.ts, t.ts)
                yield t
                await asyncio.sleep(0)


def provider_from_env(data_root: Path, day: date | None = None, speed: float = 0.0) -> MarketDataProvider:
    """MARKET_DATA_PROVIDER: `kite` (Zerodha Kite Connect, real time) or `replay` (recorded session)."""
    kind = os.environ.get("MARKET_DATA_PROVIDER", "").strip().lower()
    if kind == "kite":
        from pulsetrader.live.kite import KiteProvider

        return KiteProvider.from_env()
    if kind in ("replay", "historical", ""):
        if day is None:
            raise ProviderError("replay needs a session date (--date)")
        return HistoricalProvider(data_root, day, speed=speed)
    if kind == "mock":
        raise ProviderError("MockProvider is test-only; set MARKET_DATA_PROVIDER=kite or replay")
    raise ProviderError(f"unknown MARKET_DATA_PROVIDER {kind!r}")
