"""Phase 2: raw -> validated -> canonical, one symbol batch at a time (bounded memory).

Decisions (see docs/data-pipeline.md):
* Multi-symbol source files (the Hugging Face shards hold ~350 symbols and 100M rows each) are
  processed in batches of whole symbols, so per-symbol checks such as duplicates stay exact.
* validated/ keeps every raw row that is flagged, duplicated or outside the regular session (the
  exceptions), so nothing is silently discarded. Clean regular rows are already in canonical/, and
  raw/ stays the full, immutable source; this avoids a second full copy of a ~10 GB dataset.
* canonical/ holds one parquet file per symbol of minute bars: rows with is_valid, exact
  (symbol, ts) duplicates removed keeping the first, REGULAR session only by default.
* Daily bars (detected from the bar spacing) go to canonical_daily/ instead, with session "DAY".
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from pulsetrader.config import PROCESSING_VERSION, SCHEMA_VERSION
from pulsetrader.data.io import (
    combined_hash,
    filter_batch,
    list_raw_files,
    raw_symbol_column,
    safe_name,
    scan_raw,
    sha256_file,
    symbol_batches,
)
from pulsetrader.data.schema import CANONICAL_COLUMNS, normalise, symbol_from_path
from pulsetrader.data.validate import (
    FLAG_COLUMNS,
    FREQ_DAY,
    FREQ_MINUTE,
    SESSION_DAY,
    SESSION_REGULAR,
    QualitySummary,
    add_flags,
    detect_frequency,
    summarise,
)

log = logging.getLogger(__name__)


DEFAULT_BATCH_SYMBOLS = 40


def source_id(path: Path, columns: list[str]) -> str:
    """Stable id for a raw file: the symbol for per-symbol files, '<dir>_<stem>' for shards."""
    if raw_symbol_column(columns) is None:
        return symbol_from_path(path)
    return f"{path.parent.name}_{path.name.split('.')[0]}"


def iter_flagged(path: Path, batch_size: int = DEFAULT_BATCH_SYMBOLS) -> Iterator[tuple[str, pl.DataFrame]]:
    """Yield (frequency, flagged frame) per symbol batch of one raw file."""
    lf, cols = scan_raw(path)
    fallback = None if raw_symbol_column(cols) else symbol_from_path(path)
    freq: str | None = None
    for batch in symbol_batches(lf, cols, batch_size):
        norm = normalise(filter_batch(lf, cols, batch), cols, fallback)
        if freq is None:
            freq = detect_frequency(norm)
        flagged = add_flags(norm)
        if freq == FREQ_DAY:
            flagged = flagged.with_columns(pl.lit(SESSION_DAY).alias("session"))
        yield freq, flagged.sort("symbol", "ts").collect()


def process_file(
    path: Path,
    validated_dir: Path,
    canonical_dir: Path,
    include_non_regular: bool = False,
    daily_dir: Path | None = None,
    batch_size: int = DEFAULT_BATCH_SYMBOLS,
    written: set[str] | None = None,
) -> dict[str, Any]:
    _, cols = scan_raw(path)
    sid = source_id(path, cols)
    daily_dir = daily_dir if daily_dir is not None else canonical_dir.parent / "canonical_daily"
    written = written if written is not None else set()
    summary: QualitySummary | None = None
    counts = {"canonical_rows": 0, "dropped_invalid": 0, "dropped_non_regular": 0, "dropped_duplicates": 0}
    collisions: list[str] = []
    freq = FREQ_MINUTE
    for k, (freq, flagged) in enumerate(iter_flagged(path, batch_size)):
        s = summarise(flagged.lazy())
        summary = s if summary is None else summary.merge(s)
        regular = pl.col("session").is_in([SESSION_REGULAR, SESSION_DAY])
        exceptions = flagged.filter(~pl.col("is_valid") | pl.col("f_duplicate") | ~regular)
        if exceptions.height:
            vdir = validated_dir / sid
            vdir.mkdir(parents=True, exist_ok=True)
            exceptions.write_parquet(vdir / f"part-{k:04d}.parquet")
        keep = pl.col("is_valid")
        if not include_non_regular:
            keep = keep & regular
        kept = flagged.filter(keep)
        canon = kept.unique(subset=["symbol", "ts"], keep="first", maintain_order=True).select(
            *CANONICAL_COLUMNS, "session", "trade_date"
        )
        counts["canonical_rows"] += canon.height
        counts["dropped_invalid"] += int((~flagged["is_valid"]).sum())
        if not include_non_regular:
            counts["dropped_non_regular"] += flagged.filter(pl.col("is_valid") & ~regular).height
        counts["dropped_duplicates"] += kept.height - canon.height
        if freq == FREQ_DAY:
            daily_dir.mkdir(parents=True, exist_ok=True)
            canon.write_parquet(daily_dir / f"{sid}-{k:04d}.parquet")
            continue
        for (sym,), g in canon.partition_by("symbol", as_dict=True, maintain_order=True).items():
            name = safe_name(str(sym))
            if name in written:  # the same symbol in two source files: keep both, report it
                collisions.append(str(sym))
                name = f"{name}__{sid}"
            written.add(name)
            g.write_parquet(canonical_dir / f"{name}.parquet")
    return {
        "source": str(path),
        "source_id": sid,
        "source_sha256": sha256_file(path),
        "frequency": freq,
        "raw": summary.as_dict() if summary else None,
        **counts,
        "symbol_collisions": collisions,
    }


def run(raw_dir: Path, data_root: Path, include_non_regular: bool = False) -> dict[str, Any]:
    files = list_raw_files(raw_dir)
    if not files:
        raise FileNotFoundError(f"no raw files in {raw_dir}")
    vdir, cdir = data_root / "validated", data_root / "canonical"
    vdir.mkdir(parents=True, exist_ok=True)
    cdir.mkdir(parents=True, exist_ok=True)
    ddir = data_root / "canonical_daily"
    results = []
    written: set[str] = set()
    for i, p in enumerate(files):
        log.info("processing %d/%d %s", i + 1, len(files), p.name)
        results.append(process_file(p, vdir, cdir, include_non_regular, ddir, written=written))
    canon = pl.scan_parquet(cdir / "*.parquet")
    stats = (
        canon.select(
            pl.len().alias("rows"),
            pl.col("symbol").n_unique().alias("symbols"),
            pl.col("ts").min().alias("min_ts"),
            pl.col("ts").max().alias("max_ts"),
        )
        .collect()
        .row(0, named=True)
    )
    source_hash = combined_hash([str(r["source_sha256"]) for r in results])
    manifest = {
        "dataset_version": f"{SCHEMA_VERSION}-{source_hash[:12]}",
        "source_hash": source_hash,
        "schema_version": SCHEMA_VERSION,
        "processing_version": PROCESSING_VERSION,
        "row_count": int(stats["rows"]),
        "symbol_count": int(stats["symbols"]),
        "min_timestamp": str(stats["min_ts"]),
        "max_timestamp": str(stats["max_ts"]),
        "include_non_regular": include_non_regular,
        "daily": _daily_stats(ddir),
        "created_at": datetime.now(UTC).isoformat(),
        "files": results,
    }
    (cdir / "_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    return manifest


def _daily_stats(ddir: Path) -> dict[str, Any] | None:
    if not any(ddir.glob("*.parquet")):
        return None
    r = (
        pl.scan_parquet(ddir / "*.parquet")
        .select(
            pl.len().alias("rows"),
            pl.col("symbol").n_unique().alias("symbols"),
            pl.col("trade_date").min().alias("min_date"),
            pl.col("trade_date").max().alias("max_date"),
        )
        .collect()
        .row(0, named=True)
    )
    return {k: (int(v) if k in ("rows", "symbols") else str(v)) for k, v in r.items()}


def render_quality_report(manifest: dict[str, Any]) -> str:
    files = manifest["files"]
    tot = {f: 0 for f in FLAG_COLUMNS}
    raw_rows = 0
    sessions: dict[str, int] = {}
    for r in files:
        if r["raw"] is None:
            continue
        raw_rows += r["raw"]["rows"]
        for f in FLAG_COLUMNS:
            tot[f] += r["raw"]["flag_counts"][f]
        for k, v in r["raw"]["session_counts"].items():
            sessions[k] = sessions.get(k, 0) + v
    lines = [
        "# Data quality report",
        "",
        f"dataset_version `{manifest['dataset_version']}`, processing `{manifest['processing_version']}`.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| raw rows | {raw_rows} |",
        f"| canonical rows | {manifest['row_count']} |",
        f"| symbols | {manifest['symbol_count']} |",
        f"| min timestamp | {manifest['min_timestamp']} |",
        f"| max timestamp | {manifest['max_timestamp']} |",
        "",
        "| Flag | Raw rows |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in tot.items()],
        "",
        "| Session | Raw rows |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(sessions.items())],
    ]
    return "\n".join(lines) + "\n"
