"""Row-level validation flags and dataset-level quality summary.

Flags are computed lazily so the full dataset never has to sit in memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from pulsetrader.config import SESSION_CLOSE, SESSION_OPEN

SESSION_REGULAR = "REGULAR"
SESSION_PRE = "PRE_MARKET"
SESSION_POST = "POST_MARKET"
SESSION_WEEKEND = "WEEKEND"


def session_expr() -> pl.Expr:
    t = pl.col("ts").dt.time()
    wd = pl.col("ts").dt.weekday()  # Monday=1 .. Sunday=7
    return (
        pl.when(wd >= 6)
        .then(pl.lit(SESSION_WEEKEND))
        .when(t < pl.time(SESSION_OPEN.hour, SESSION_OPEN.minute))
        .then(pl.lit(SESSION_PRE))
        .when(t >= pl.time(SESSION_CLOSE.hour, SESSION_CLOSE.minute))
        .then(pl.lit(SESSION_POST))
        .otherwise(pl.lit(SESSION_REGULAR))
        .alias("session")
    )


def add_flags(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Add boolean issue flags plus `session`, `trade_date`, `is_valid`."""
    prices = ("open", "high", "low", "close")
    any_null = (
        pl.any_horizontal([pl.col(c).is_null() | pl.col(c).is_nan() for c in prices])
        | pl.col("volume").is_null()
        | pl.col("ts").is_null()
        | pl.col("symbol").is_null()
    )
    nonpos = pl.any_horizontal([pl.col(c) <= 0 for c in prices])
    hl = pl.col("high") < pl.col("low")
    ohlc_bad = (pl.col("high") < pl.max_horizontal("open", "close")) | (
        pl.col("low") > pl.min_horizontal("open", "close")
    )
    dup = pl.struct("symbol", "ts").is_duplicated()
    return lf.with_columns(
        session_expr(),
        pl.col("ts").dt.date().alias("trade_date"),
        any_null.fill_null(True).alias("f_null"),
        nonpos.fill_null(False).alias("f_nonpos_price"),
        (pl.col("volume") < 0).fill_null(False).alias("f_neg_volume"),
        hl.fill_null(False).alias("f_high_lt_low"),
        ohlc_bad.fill_null(False).alias("f_ohlc_inconsistent"),
        dup.alias("f_duplicate"),
    ).with_columns(
        (
            ~pl.col("f_null")
            & ~pl.col("f_nonpos_price")
            & ~pl.col("f_neg_volume")
            & ~pl.col("f_high_lt_low")
            & ~pl.col("f_ohlc_inconsistent")
        ).alias("is_valid")
    )


FLAG_COLUMNS = (
    "f_null",
    "f_nonpos_price",
    "f_neg_volume",
    "f_high_lt_low",
    "f_ohlc_inconsistent",
    "f_duplicate",
)


@dataclass
class QualitySummary:
    rows: int
    symbols: int
    min_ts: str | None
    max_ts: str | None
    flag_counts: dict[str, int]
    session_counts: dict[str, int]
    valid_rows: int

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def summarise(flagged: pl.LazyFrame) -> QualitySummary:
    agg = flagged.select(
        pl.len().alias("rows"),
        pl.col("symbol").n_unique().alias("symbols"),
        pl.col("ts").min().alias("min_ts"),
        pl.col("ts").max().alias("max_ts"),
        pl.col("is_valid").sum().alias("valid_rows"),
        *[pl.col(f).sum().alias(f) for f in FLAG_COLUMNS],
    ).collect()
    r = agg.row(0, named=True)
    sess = flagged.group_by("session").agg(pl.len().alias("n")).collect()
    return QualitySummary(
        rows=int(r["rows"]),
        symbols=int(r["symbols"]),
        min_ts=None if r["min_ts"] is None else str(r["min_ts"]),
        max_ts=None if r["max_ts"] is None else str(r["max_ts"]),
        flag_counts={f: int(r[f]) for f in FLAG_COLUMNS},
        session_counts={s: int(n) for s, n in sess.iter_rows()},
        valid_rows=int(r["valid_rows"]),
    )


def missing_candles(canonical: pl.LazyFrame, expected_per_day: int = 375) -> pl.LazyFrame:
    """Per (symbol, trade_date): regular bars present vs the 375 expected for 09:15-15:29."""
    return (
        canonical.filter(pl.col("session") == SESSION_REGULAR)
        .group_by("symbol", "trade_date")
        .agg(pl.len().alias("bars"))
        .with_columns((pl.lit(expected_per_day) - pl.col("bars")).clip(0).alias("missing"))
    )
