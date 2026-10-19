"""Real-time bar cache: per-symbol history (warm-up sessions from the canonical store) plus today's
validated live bars, kept as a Polars frame per symbol for the shared feature engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import polars as pl

from pulsetrader.live.events import IST, Bar

COLUMNS = ("symbol", "ts", "open", "high", "low", "close", "volume")


def bars_frame(bars: list[Bar]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": [b.symbol for b in bars],
            "ts": [b.ts.astimezone(IST) for b in bars],
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
        },
        schema={
            "symbol": pl.Utf8,
            "ts": pl.Datetime("us", "Asia/Kolkata"),
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
        },
    )


@dataclass
class BarCache:
    history: pl.DataFrame  # warm-up bars, COLUMNS (+ session/trade_date allowed)
    live: dict[str, list[Bar]] = field(default_factory=dict)
    latest: dict[str, Bar] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.history = self.history.select(*COLUMNS).with_columns(
            pl.col("ts").dt.convert_time_zone("Asia/Kolkata"), pl.col(pl.Float32).cast(pl.Float64)
        )

    def add(self, b: Bar) -> None:
        self.live.setdefault(b.symbol, []).append(b)
        self.latest[b.symbol] = b

    def frame(self, symbols: list[str], upto: datetime) -> pl.DataFrame:
        """History + live bars for `symbols` with bar start <= upto (nothing later can leak in)."""
        live = [b for s in symbols for b in self.live.get(s, []) if b.ts <= upto]
        hist = self.history.filter(pl.col("symbol").is_in(symbols))
        return pl.concat([hist, bars_frame(live)]).unique(["symbol", "ts"], keep="last").sort("symbol", "ts")
