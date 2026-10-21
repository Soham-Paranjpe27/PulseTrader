"""Raw-file discovery and lazy reading. Raw files are opened read-only and never rewritten."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import polars as pl

from pulsetrader.data.schema import resolve_columns

RAW_SUFFIXES = (".csv", ".parquet", ".csv.gz")


def list_raw_files(raw_dir: Path) -> list[Path]:
    files = [p for p in sorted(raw_dir.rglob("*")) if p.is_file() and p.name.lower().endswith(RAW_SUFFIXES)]
    return files


def scan_raw(path: Path) -> tuple[pl.LazyFrame, list[str]]:
    name = path.name.lower()
    if name.endswith(".parquet"):
        lf = pl.scan_parquet(path)
    else:
        lf = pl.scan_csv(path, infer_schema_length=10_000, try_parse_dates=False)
    cols = lf.collect_schema().names()
    return lf, cols


def sha256_file(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def combined_hash(hashes: list[str]) -> str:
    h = hashlib.sha256()
    for x in sorted(hashes):
        h.update(x.encode())
    return h.hexdigest()


def raw_symbol_column(columns: list[str]) -> str | None:
    """Name of the raw symbol column, if the file holds several symbols (e.g. the HF shards)."""
    return resolve_columns(columns).get("symbol")


def symbol_batches(lf: pl.LazyFrame, columns: list[str], batch_size: int) -> list[list[str] | None]:
    """Split a multi-symbol file into symbol batches so memory stays bounded.

    Returns [None] for single-symbol files (no symbol column): process the whole file at once.
    Every row of a symbol lands in exactly one batch, so per-symbol checks (duplicates) stay exact.
    """
    col = raw_symbol_column(columns)
    if col is None:
        return [None]
    syms = lf.select(pl.col(col).unique()).collect()[col].drop_nulls().sort().to_list()
    batches: list[list[str] | None] = [syms[i : i + batch_size] for i in range(0, len(syms), batch_size)]
    return batches or [None]


def filter_batch(lf: pl.LazyFrame, columns: list[str], batch: list[str] | None) -> pl.LazyFrame:
    if batch is None:
        return lf
    col = raw_symbol_column(columns)
    assert col is not None
    return lf.filter(pl.col(col).is_in(batch))


def safe_name(symbol: str) -> str:
    """File-system-safe file stem for a symbol (spaces and slashes become underscores)."""
    return re.sub(r"[^A-Za-z0-9&._-]", "_", symbol)
