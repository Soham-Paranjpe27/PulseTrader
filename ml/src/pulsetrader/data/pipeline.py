"""Phase 2: raw -> validated -> canonical, one source file at a time (bounded memory).

Decisions (see docs/data-pipeline.md):
* validated/ keeps every raw row with flag columns, so nothing is silently discarded.
* canonical/ keeps rows with is_valid, removes exact (symbol, ts) duplicates keeping the first
  occurrence, and keeps only REGULAR session bars by default. Non-regular bars are counted and
  reported, and can be kept with include_non_regular=True.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from pulsetrader.config import PROCESSING_VERSION, SCHEMA_VERSION
from pulsetrader.data.io import combined_hash, list_raw_files, scan_raw, sha256_file
from pulsetrader.data.schema import CANONICAL_COLUMNS, normalise, symbol_from_path
from pulsetrader.data.validate import FLAG_COLUMNS, SESSION_REGULAR, add_flags, summarise

log = logging.getLogger(__name__)


def process_file(
    path: Path, validated_dir: Path, canonical_dir: Path, include_non_regular: bool = False
) -> dict[str, Any]:
    lf, cols = scan_raw(path)
    symbol = symbol_from_path(path)
    flagged = add_flags(normalise(lf, cols, symbol)).sort("symbol", "ts").collect()
    summary = summarise(flagged.lazy())

    vpath = validated_dir / f"{symbol}.parquet"
    flagged.write_parquet(vpath)

    keep = pl.col("is_valid")
    if not include_non_regular:
        keep = keep & (pl.col("session") == SESSION_REGULAR)
    canon = (
        flagged.filter(keep)
        .unique(subset=["symbol", "ts"], keep="first", maintain_order=True)
        .select(*CANONICAL_COLUMNS, "session", "trade_date")
    )
    cpath = canonical_dir / f"{symbol}.parquet"
    canon.write_parquet(cpath)
    return {
        "source": str(path),
        "source_sha256": sha256_file(path),
        "symbol": symbol,
        "raw": summary.as_dict(),
        "canonical_rows": canon.height,
        "dropped_invalid": int((~flagged["is_valid"]).sum()),
        "dropped_non_regular": int(
            flagged.filter(pl.col("is_valid") & (pl.col("session") != SESSION_REGULAR)).height
        )
        if not include_non_regular
        else 0,
        "dropped_duplicates": int(flagged.filter(keep).height - canon.height),
    }


def run(raw_dir: Path, data_root: Path, include_non_regular: bool = False) -> dict[str, Any]:
    files = list_raw_files(raw_dir)
    if not files:
        raise FileNotFoundError(f"no raw files in {raw_dir}")
    vdir, cdir = data_root / "validated", data_root / "canonical"
    vdir.mkdir(parents=True, exist_ok=True)
    cdir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, p in enumerate(files):
        log.info("processing %d/%d %s", i + 1, len(files), p.name)
        results.append(process_file(p, vdir, cdir, include_non_regular))
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
        "created_at": datetime.now(UTC).isoformat(),
        "files": results,
    }
    (cdir / "_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    return manifest


def render_quality_report(manifest: dict[str, Any]) -> str:
    files = manifest["files"]
    tot = {f: 0 for f in FLAG_COLUMNS}
    raw_rows = 0
    sessions: dict[str, int] = {}
    for r in files:
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
