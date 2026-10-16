"""Phase 1: dataset discovery. Computes actual statistics from the raw files; trusts nothing reported."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from pulsetrader.data.io import list_raw_files, scan_raw, sha256_file
from pulsetrader.data.pipeline import DEFAULT_BATCH_SYMBOLS, iter_flagged
from pulsetrader.data.schema import SchemaError
from pulsetrader.data.validate import SESSION_DAY, SESSION_REGULAR, QualitySummary, summarise

log = logging.getLogger(__name__)


def inspect_file(
    path: Path, hash_file: bool = True, batch_size: int = DEFAULT_BATCH_SYMBOLS
) -> dict[str, Any]:
    lf, cols = scan_raw(path)
    schema = {k: str(v) for k, v in lf.collect_schema().items()}
    entry: dict[str, Any] = {
        "path": str(path),
        "bytes": path.stat().st_size,
        "raw_columns": cols,
        "raw_schema": schema,
        "sha256": sha256_file(path) if hash_file else None,
    }
    summary: QualitySummary | None = None
    symbols: list[str] = []
    regular_dates: set[date] = set()
    off_session: dict[tuple[date, str], list[int]] = {}
    freq = None
    try:
        for batch_freq, flagged in iter_flagged(path, batch_size):
            freq = batch_freq
            s = summarise(flagged.lazy())
            summary = s if summary is None else summary.merge(s)
            symbols += flagged["symbol"].unique().to_list()
            dates = flagged.filter(pl.col("session").is_in([SESSION_REGULAR, SESSION_DAY]))["trade_date"]
            regular_dates |= set(dates.unique().to_list())
            odd = (
                flagged.filter(~pl.col("session").is_in([SESSION_REGULAR, SESSION_DAY]))
                .group_by("trade_date", "session")
                .agg(pl.len().alias("rows"), pl.col("symbol").n_unique().alias("symbols"))
            )
            for d, sess, n, k in odd.iter_rows():
                acc = off_session.setdefault((d, sess), [0, 0])
                acc[0] += n
                acc[1] += k
    except SchemaError as e:
        log.error("schema error in %s: %s", path, e)
        entry["error"] = f"SchemaError: {e}"
        return entry
    assert summary is not None
    entry.update(summary.as_dict())
    entry["frequency"] = freq
    entry["symbol_list"] = sorted(symbols)
    entry["regular_dates"] = sorted(regular_dates)
    entry["off_session"] = [
        {"trade_date": d, "session": sess, "rows": n, "symbols": k}
        for (d, sess), (n, k) in sorted(off_session.items())
    ]
    return entry


def _add(a: dict[str, int], b: dict[str, int]) -> None:
    for k, v in b.items():
        a[k] = a.get(k, 0) + v


def _frequency_block(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-file entries of one bar frequency; computes cross-file symbol overlap."""
    flags: dict[str, int] = {}
    sessions: dict[str, int] = {}
    seen: dict[str, str] = {}
    overlaps: list[str] = []
    dates: set[date] = set()
    off: dict[tuple[date, str], list[int]] = {}
    for e in entries:
        _add(flags, e["flag_counts"])
        _add(sessions, e["session_counts"])
        for sym in e["symbol_list"]:
            if sym in seen:
                overlaps.append(sym)
            seen[sym] = e["path"]
        dates |= set(e["regular_dates"])
        for o in e["off_session"]:
            acc = off.setdefault((o["trade_date"], o["session"]), [0, 0])
            acc[0] += o["rows"]
            acc[1] += o["symbols"]
    holidays: list[date] = []
    if dates:
        d, end = min(dates), max(dates)
        while d <= end:
            if d.weekday() < 5 and d not in dates:
                holidays.append(d)
            d += timedelta(days=1)
    return {
        "file_count": len(entries),
        "row_count": sum(int(e["rows"]) for e in entries),
        "valid_rows": sum(int(e["valid_rows"]) for e in entries),
        "symbol_count": len(seen),
        "symbols_in_several_files": sorted(set(overlaps)),
        "min_timestamp": min(e["min_ts"] for e in entries),
        "max_timestamp": max(e["max_ts"] for e in entries),
        "trading_dates": len(dates),
        "weekdays_without_bars": holidays,
        "flag_counts": flags,
        "session_counts": sessions,
        "off_session_by_date": [
            {"trade_date": d, "session": sess, "rows": n, "symbols": k}
            for (d, sess), (n, k) in sorted(off.items())
        ],
        "symbols": sorted(seen),
    }


def discover(raw_dir: Path, out_dir: Path, hash_files: bool = True) -> dict[str, Any]:
    files = list_raw_files(raw_dir)
    if not files:
        raise FileNotFoundError(f"no raw data files under {raw_dir}")
    entries = []
    for i, p in enumerate(files):
        log.info("inspecting %d/%d %s", i + 1, len(files), p.name)
        entries.append(inspect_file(p, hash_files))
    ok = [e for e in entries if "error" not in e]
    by_freq: dict[str, dict[str, Any]] = {}
    for freq in sorted({str(e["frequency"]) for e in ok}):
        by_freq[freq] = _frequency_block([e for e in ok if e["frequency"] == freq])
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "raw_dir": str(raw_dir),
        "file_count": len(files),
        "files_with_errors": len(entries) - len(ok),
        "total_bytes": sum(int(e["bytes"]) for e in entries),
        "row_count": sum(int(e["rows"]) for e in ok),
        "symbol_count": len({s for b in by_freq.values() for s in b["symbols"]}),
        "min_timestamp": min((e["min_ts"] for e in ok if e["min_ts"]), default=None),
        "max_timestamp": max((e["max_ts"] for e in ok if e["max_ts"]), default=None),
        "by_frequency": by_freq,
        "files": [{k: v for k, v in e.items() if k not in ("symbol_list", "regular_dates")} for e in entries],
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
    for k in ("file_count", "files_with_errors", "total_bytes", "row_count", "symbol_count"):
        lines.append(f"| {k} | {m[k]} |")
    lines.append(f"| timestamps (IST) | {m['min_timestamp']} .. {m['max_timestamp']} |")
    for freq, b in m["by_frequency"].items():
        lines += [
            "",
            f"## {freq} bars",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| files | {b['file_count']} |",
            f"| rows | {b['row_count']} |",
            f"| valid rows | {b['valid_rows']} |",
            f"| symbols | {b['symbol_count']} |",
            f"| symbols in more than one file | {len(b['symbols_in_several_files'])} |",
            f"| timestamps (IST) | {b['min_timestamp']} .. {b['max_timestamp']} |",
            f"| trading dates | {b['trading_dates']} |",
            f"| weekdays without any bar | {len(b['weekdays_without_bars'])} |",
            "",
            "| Flag | Rows |",
            "|---|---|",
            *[f"| {k} | {v} |" for k, v in b["flag_counts"].items()],
            "",
            "| Session | Rows |",
            "|---|---|",
            *[f"| {k} | {v} |" for k, v in sorted(b["session_counts"].items())],
        ]
        if b["weekdays_without_bars"]:
            lines += ["", "Weekdays without bars (holiday candidates): "]
            lines.append(", ".join(str(d) for d in b["weekdays_without_bars"]))
        busy = [o for o in b["off_session_by_date"] if o["symbols"] >= 50]
        if busy:
            lines += [
                "",
                "Off-session dates with bars for 50+ symbols (special-session candidates):",
                "",
                "| Date | Session | Rows | Symbols |",
                "|---|---|---|---|",
                *[f"| {o['trade_date']} | {o['session']} | {o['rows']} | {o['symbols']} |" for o in busy],
            ]
    errs = [e for e in m["files"] if "error" in e]
    if errs:
        lines += ["", "## Files with errors", ""]
        lines += [f"- `{e['path']}`: {e['error']}" for e in errs]
    return "\n".join(lines) + "\n"


def _frame_preview(path: Path, n: int = 5) -> pl.DataFrame:
    lf, _ = scan_raw(path)
    return lf.head(n).collect()
