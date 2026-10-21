"""Forward-return labels.

future_return(h) = close[t+h] / close[t] - 1, where t+h is the bar stamped exactly h minutes later
on the same trade_date. If that bar is missing (gap, session end) the label is null; we never
silently substitute a different bar. label_end_ts = ts + h + 1 bar is the moment the label becomes
known, and is what purging uses.
"""

from __future__ import annotations

from datetime import timedelta

import polars as pl

from pulsetrader.config import BAR_MINUTES, LABEL_VERSION

UP, NEUTRAL, DOWN = 1, 0, -1


def add_labels(
    df: pl.DataFrame, horizons: tuple[int, ...], thresholds: tuple[float, ...] = ()
) -> pl.DataFrame:
    base = df.select("symbol", "ts", "trade_date", "close")
    out = df
    for h in horizons:
        fut = base.select(
            "symbol",
            "trade_date",
            (pl.col("ts") - timedelta(minutes=h)).alias("ts"),
            pl.col("close").alias(f"_fclose_{h}"),
        )
        out = out.join(fut, on=["symbol", "trade_date", "ts"], how="left", maintain_order="left")
        out = out.with_columns(
            (pl.col(f"_fclose_{h}") / pl.col("close") - 1).alias(f"fret_{h}"),
            pl.col(f"_fclose_{h}").alias(f"fprice_{h}"),
            (pl.col("ts") + timedelta(minutes=h + BAR_MINUTES)).alias(f"label_end_ts_{h}"),
        ).drop(f"_fclose_{h}")
        for thr in thresholds:
            out = out.with_columns(direction_label(pl.col(f"fret_{h}"), thr).alias(label_name(h, thr)))
    return out.with_columns(pl.lit(LABEL_VERSION).alias("label_version"))


def label_name(h: int, thr: float) -> str:
    return f"y_{h}m_{round(thr * 10000)}bp"


def direction_label(fret: pl.Expr, thr: float) -> pl.Expr:
    return (
        pl.when(fret.is_null())
        .then(None)
        .when(fret > thr)
        .then(pl.lit(UP))
        .when(fret < -thr)
        .then(pl.lit(DOWN))
        .otherwise(pl.lit(NEUTRAL))
        .cast(pl.Int8)
    )
