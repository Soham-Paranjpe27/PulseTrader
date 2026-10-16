"""Phase 1: dataset discovery. Computes actual statistics from the raw files; trusts nothing reported."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from pulsetrader.data.io import list_raw_files, scan_raw, sha256_file
from pulsetrader.data.schema import SchemaError, normalise, symbol_from_path
from pulsetrader.data.validate import add_flags, summarise

log = logging.getLogger(__name__)


def inspect_file(path: Path, hash_file: bool = True) -> dict[str, Any]:
    lf, cols = scan_raw(path)
    schema = {k: str(v) for k, v in lf.collect_schema().items()}
    entry: dict[str, Any] = {
        "path": str(path),
        "bytes": path.stat().st_size,
        "raw_columns": cols,
        "raw_schema": schema,
        "sha256": sha256_file(path) if hash_file else None,
    }
    try:
        norm = normalise(lf, cols, symbol_from_path(path))
    except SchemaError as e:
        log.error("schema error in %s: %s", path, e)
        entry["error"] = f"SchemaError: {e}"
        return entry
    s = summarise(add_flags(norm))
    entry.update(s.as_dict())
    return entry


def discover(raw_dir: Path, out_dir: Path, hash_files: bool = True) -> dict[str, Any]:
    files = list_raw_files(raw_dir)
    if not files:
        raise FileNotFoundError(f"no raw data files under {raw_dir}")
    entries = []
    for i, p in enumerate(files):
        log.info("inspecting %d/%d %s", i + 1, len(files), p.name)
        entries.append(inspect_file(p, hash_files))
    ok = [e for e in entries if "error" not in e]
    total_rows = sum(int(e["rows"]) for e in ok)
    flags: dict[str, int] = {}
    sessions: dict[str, int] = {}
    for e in ok:
        for k, v in e["flag_counts"].items():
            flags[k] = flags.get(k, 0) + v
        for k, v in e["session_counts"].items():
            sessions[k] = sessions.get(k, 0) + v
    mins = [e["min_ts"] for e in ok if e["min_ts"]]
    maxs = [e["max_ts"] for e in ok if e["max_ts"]]
    symbols = sorted({symbol_from_path(Path(str(e["path"]))) for e in ok})
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "raw_dir": str(raw_dir),
        "file_count": len(files),
        "files_with_errors": len(entries) - len(ok),
        "total_bytes": sum(int(e["bytes"]) for e in entries),
        "row_count": total_rows,
        "symbol_count_from_filenames": len(symbols),
        "min_timestamp": min(mins) if mins else None,
        "max_timestamp": max(maxs) if maxs else None,
        "flag_counts": flags,
        "session_counts": sessions,
        "files": entries,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    (out_dir / "data_inventory.md").write_text(render_inventory(manifest))
    return manifest


def render_inventory(m: dict[str, Any]) -> str:
    lines = [
        "# Data inventory",
        "",
        f"Generated {m['created_at']} from `{m['raw_dir']}`. All figures computed from the files.",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    for k in (
        "file_count",
        "files_with_errors",
        "total_bytes",
        "row_count",
        "symbol_count_from_filenames",
        "min_timestamp",
        "max_timestamp",
    ):
        lines.append(f"| {k} | {m[k]} |")
    lines += ["", "## Issue counts", "", "| Flag | Rows |", "|---|---|"]
    for k, v in m["flag_counts"].items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Session classification", "", "| Session | Rows |", "|---|---|"]
    for k, v in m["session_counts"].items():
        lines.append(f"| {k} | {v} |")
    errs = [e for e in m["files"] if "error" in e]
    if errs:
        lines += ["", "## Files with errors", ""]
        lines += [f"- `{e['path']}`: {e['error']}" for e in errs]
    return "\n".join(lines) + "\n"


def _frame_preview(path: Path, n: int = 5) -> pl.DataFrame:
    lf, _ = scan_raw(path)
    return lf.head(n).collect()
