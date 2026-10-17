"""Chronological splits with purging and embargo, plus walk-forward windows.

Boundaries are computed from the actual timestamps in the data (by distinct trade dates), never
by shuffling. Purging removes earlier-set rows whose label window ends after the next set begins;
embargo additionally drops the first `embargo` minutes of each later set.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import polars as pl


@dataclass(frozen=True)
class Period:
    name: str
    start: date  # inclusive trade_date
    end: date  # inclusive trade_date

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "start": str(self.start), "end": str(self.end)}


def date_split(dates: list[date], fractions: tuple[float, float, float] = (0.70, 0.15, 0.15)) -> list[Period]:
    d = sorted(set(dates))
    if len(d) < 3:
        raise ValueError("need at least 3 distinct trade dates")
    n = len(d)
    a = max(1, int(round(n * fractions[0])))
    b = max(a + 1, int(round(n * (fractions[0] + fractions[1]))))
    b = min(b, n - 1)
    return [
        Period("train", d[0], d[a - 1]),
        Period("validation", d[a], d[b - 1]),
        Period("test", d[b], d[-1]),
    ]


def assign(
    df: pl.DataFrame,
    periods: list[Period],
    label_end_col: str,
    embargo_minutes: int = 0,
    starts: dict[str, datetime] | None = None,
) -> pl.DataFrame:
    """Add `split` column; rows lost to purge/embargo get split=null and `purged`=True.

    `starts` gives each period's first timestamp in the full dataset. Pass it when `df` is only a
    chunk of the data (e.g. one month), otherwise the chunk's own first row would be mistaken for the
    start of the period.
    """
    expr = pl.lit(None, dtype=pl.Utf8)
    for p in periods:
        expr = pl.when(pl.col("trade_date").is_between(p.start, p.end)).then(pl.lit(p.name)).otherwise(expr)
    out = df.with_columns(expr.alias("split"))
    drop = pl.lit(False)
    for prev, nxt in zip(periods, periods[1:], strict=False):
        nxt_start = (
            starts.get(nxt.name)
            if starts is not None
            else out.filter(pl.col("split") == nxt.name)["ts"].min()
        )
        if nxt_start is None:
            continue
        if not isinstance(nxt_start, datetime):
            raise TypeError("ts column must be a datetime")
        drop = drop | ((pl.col("split") == prev.name) & (pl.col(label_end_col) > nxt_start))
        if embargo_minutes:
            emb_end = nxt_start + timedelta(minutes=embargo_minutes)
            drop = drop | ((pl.col("split") == nxt.name) & (pl.col("ts") < emb_end))
    return out.with_columns(drop.alias("purged")).with_columns(
        pl.when(pl.col("purged")).then(None).otherwise(pl.col("split")).alias("split")
    )


@dataclass(frozen=True)
class Window:
    fold: int
    train: Period
    valid: Period


def walk_forward(
    dates: list[date],
    n_folds: int,
    mode: str = "expanding",
    min_train_frac: float = 0.4,
    train_days: int | None = None,
) -> list[Window]:
    """Expanding or rolling walk-forward over the given (pre-test) dates."""
    d = sorted(set(dates))
    n = len(d)
    start_valid = int(n * min_train_frac)
    step = (n - start_valid) // n_folds
    if step < 1:
        raise ValueError("not enough dates for the requested folds")
    out = []
    for k in range(n_folds):
        v0 = start_valid + k * step
        v1 = n - 1 if k == n_folds - 1 else v0 + step - 1
        if mode == "expanding":
            t0 = 0
        elif mode == "rolling":
            span = train_days if train_days is not None else start_valid
            t0 = max(0, v0 - span)
        else:
            raise ValueError(f"unknown mode {mode}")
        out.append(Window(k, Period("train", d[t0], d[v0 - 1]), Period("validation", d[v0], d[v1])))
    return out
