"""Raw-file discovery and lazy reading. Raw files are opened read-only and never rewritten."""

from __future__ import annotations

import hashlib
from pathlib import Path

import polars as pl

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
