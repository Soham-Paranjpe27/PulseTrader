"""Canonical OHLCV schema and raw-column normalisation.

Raw files are never modified; normalisation happens on read into a LazyFrame.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from pulsetrader.config import IST

CANONICAL_COLUMNS = ("symbol", "ts", "open", "high", "low", "close", "volume")

CANONICAL_SCHEMA = {
    "symbol": pl.Utf8,
    "ts": pl.Datetime("us", IST),
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
}

# Accepted aliases seen in public Indian minute-data dumps. Matched case-insensitively.
_ALIASES = {
    "ts": ("ts", "timestamp", "date", "datetime", "time", "date_time"),
    "symbol": ("symbol", "ticker", "tradingsymbol", "stock", "name"),
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "c", "ltp"),
    "volume": ("volume", "vol", "v", "qty"),
}


class SchemaError(ValueError):
    """Raw input cannot be mapped onto the canonical schema."""


def resolve_columns(columns: list[str]) -> dict[str, str]:
    """Map canonical name -> raw column name. Raises SchemaError if a required column is missing."""
    lower = {c.lower().strip(): c for c in columns}
    mapping: dict[str, str] = {}
    for canon, aliases in _ALIASES.items():
        for a in aliases:
            if a in lower:
                mapping[canon] = lower[a]
                break
    missing = [c for c in ("ts", "open", "high", "low", "close", "volume") if c not in mapping]
    if missing:
        raise SchemaError(f"missing required columns {missing}; got {columns}")
    return mapping


def symbol_from_path(path: Path) -> str:
    """Derive a symbol from a per-symbol file name, e.g. 'RELIANCE_minute.csv' -> 'RELIANCE'."""
    stem = path.name.split(".")[0]
    stem = re.sub(r"(?i)[_-](minute|min|1min|1m|data|intraday)$", "", stem)
    return stem.upper()


def normalise(lf: pl.LazyFrame, raw_columns: list[str], symbol: str | None) -> pl.LazyFrame:
    """Rename/cast a raw LazyFrame to canonical columns.

    Naive timestamps are interpreted as IST wall-clock (NSE convention); tz-aware ones are converted.
    """
    m = resolve_columns(raw_columns)
    if "symbol" in m:
        sym = pl.col(m["symbol"]).cast(pl.Utf8).str.strip_chars().str.to_uppercase()
    elif symbol is not None:
        sym = pl.lit(symbol)
    else:
        raise SchemaError("no symbol column and no symbol supplied")

    ts_raw = _to_ist(pl.col(m["ts"]), lf.collect_schema()[m["ts"]])
    out = lf.select(
        sym.alias("symbol"),
        ts_raw.alias("_ts_raw"),
        *[
            pl.col(m[c]).cast(pl.Float64, strict=False).alias(c)
            for c in ("open", "high", "low", "close", "volume")
        ],
    )
    return out.rename({"_ts_raw": "ts"}).select(CANONICAL_COLUMNS)


def _to_ist(e: pl.Expr, dtype: pl.DataType) -> pl.Expr:
    """Convert a raw timestamp column to Datetime(us, IST).

    tz-aware datetimes (e.g. the Hugging Face dataset's UTC column) are converted to IST.
    Naive datetimes and strings are treated as IST wall-clock (NSE convention).
    """
    if isinstance(dtype, pl.Datetime):
        e = e.dt.cast_time_unit("us")
        if dtype.time_zone is not None:
            return e.dt.convert_time_zone(IST)
        return e.dt.replace_time_zone(IST, ambiguous="earliest", non_existent="null")
    return (
        e.cast(pl.Utf8)
        .str.replace(r"\+05:30$", "")
        .str.to_datetime(time_unit="us", strict=False)
        .dt.replace_time_zone(IST, ambiguous="earliest", non_existent="null")
    )
