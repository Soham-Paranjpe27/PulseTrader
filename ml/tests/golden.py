"""Golden dataset: tiny, deterministic, offline. TEST ONLY - never used as market data.

Prices follow closed-form formulas so tests can verify exact feature, label and split values.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import polars as pl

from pulsetrader.config import IST

DAYS = (date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5))
BARS_PER_DAY = 375


def _bars(sym_idx: int) -> list[dict[str, object]]:
    rows = []
    k = 0
    for d in DAYS:
        start = datetime(d.year, d.month, d.day, 9, 15)
        for i in range(BARS_PER_DAY):
            base = 100.0 * (sym_idx + 1) + 0.01 * k + 2.0 * math.sin(k / (7.0 + sym_idx))
            o = base
            c = base + 0.05 * math.cos(k / 3.0)
            h = max(o, c) + 0.03
            lo = min(o, c) - 0.03
            v = 1000 + 100 * ((k * (sym_idx + 3)) % 17)
            rows.append(
                {
                    "date": start + timedelta(minutes=i),
                    "open": o,
                    "high": h,
                    "low": lo,
                    "close": c,
                    "volume": v,
                }
            )
            k += 1
    return rows


SYMBOLS = ("AAA", "BBB", "CCC", "NIFTY 50")


def golden_frames() -> dict[str, pl.DataFrame]:
    return {s: pl.DataFrame(_bars(i)) for i, s in enumerate(SYMBOLS)}


def write_raw(raw_dir) -> None:
    """Write golden raw CSVs, plus a dirty file with known defects for validation tests."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    for s, df in golden_frames().items():
        df.with_columns(pl.col("date").dt.strftime("%Y-%m-%d %H:%M:%S")).write_csv(
            raw_dir / f"{s}_minute.csv"
        )
    dirty = pl.DataFrame(
        {
            "date": [
                "2024-01-01 09:15:00",  # ok
                "2024-01-01 09:15:00",  # duplicate
                "2024-01-01 09:16:00",  # high < low
                "2024-01-01 09:17:00",  # negative volume
                "2024-01-01 09:18:00",  # zero price
                "2024-01-01 09:00:00",  # pre-market
                "2024-01-01 15:45:00",  # post-market
                "2024-01-06 10:00:00",  # Saturday
                "2024-01-01 09:19:00",  # close above high
            ],
            "open": [10.0, 10.0, 10.0, 10.0, 0.0, 10.0, 10.0, 10.0, 10.0],
            "high": [11.0, 11.0, 9.0, 11.0, 11.0, 11.0, 11.0, 11.0, 10.5],
            "low": [9.0, 9.0, 10.0, 9.0, 9.0, 9.0, 9.0, 9.0, 9.0],
            "close": [10.5, 10.5, 9.5, 10.5, 10.5, 10.5, 10.5, 10.5, 10.8],
            "volume": [5, 5, 5, -5, 5, 5, 5, 5, 5],
        }
    )
    dirty.write_csv(raw_dir / "DIRTY_minute.csv")


def to_canonical(df: pl.DataFrame, symbol: str) -> pl.DataFrame:
    return df.select(
        pl.lit(symbol).alias("symbol"),
        pl.col("date").dt.replace_time_zone(IST).cast(pl.Datetime("us", IST)).alias("ts"),
        "open",
        "high",
        "low",
        "close",
        pl.col("volume").cast(pl.Float64),
    ).with_columns(pl.col("ts").dt.date().alias("trade_date"))


def golden_canonical(symbols=("AAA", "BBB", "CCC")) -> pl.DataFrame:
    fr = golden_frames()
    return pl.concat([to_canonical(fr[s], s) for s in symbols])
