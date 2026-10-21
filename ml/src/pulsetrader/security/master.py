"""Phase 3: security master, symbol history and corporate-action audit.

One pass over canonical/ (one file per symbol, so memory is bounded by the largest symbol) builds:
* `day_bars`: per symbol-day OHLCV aggregated from regular-session minute bars,
* `security_master`: per-symbol stats + instrument classification + experiment eligibility,
* `symbol_history`: first/last trading dates, status, and rename candidates,
* `corporate_action_events`: suspicious overnight gaps and intraday jumps.

Everything is computed from the data; no external reference data is available offline.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from pulsetrader.security.lists import ETF_SYMBOLS, INDEX_SYMBOLS, OTHER_SYMBOLS, UNCERTAIN

log = logging.getLogger(__name__)

SECURITY_MASTER_VERSION = "secmaster-v1"

EQUITY, ETF, INDEX, OTHER = "EQUITY", "ETF", "INDEX", "OTHER"

# NSE price bands cap most equities at 20% a day; a larger overnight move needs an explanation.
GAP_THRESHOLD = 0.20
JUMP_THRESHOLD = 0.20  # consecutive-minute move inside one session
# Ratios produced by common splits/bonuses (old:new shares), used to label suspicious gaps.
# 1.25x/1.33x ratios (bonus 1:4, 1:3) are not labelled: they coincide with 20% circuit moves.
SPLIT_RATIOS = (2.0, 3.0, 4.0, 5.0, 10.0, 1.5)
RATIO_TOL = 0.03


@dataclass(frozen=True)
class Eligibility:
    """Rules for the automatic stock-prediction universe (EQUITY only)."""

    min_days: int = 250
    max_zero_volume_frac: float = 0.2
    min_median_daily_turnover: float = 1e7  # INR 1 crore


def classify(symbol: str, zero_volume_frac: float) -> tuple[str, str]:
    """Return (instrument_type, basis)."""
    if symbol in INDEX_SYMBOLS:
        return INDEX, "listed index ticker"
    if " " in symbol:
        return INDEX, "index-style name with spaces"
    if symbol in ETF_SYMBOLS:
        return ETF, "curated ETF list"
    if symbol in OTHER_SYMBOLS:
        return OTHER, "curated debt/commodity list"
    if symbol.startswith("NIFTY") and zero_volume_frac >= 0.99:
        return INDEX, "NIFTY-prefixed series with no traded volume"
    return EQUITY, "default (not index/ETF/other)"


def day_bars(minute: pl.DataFrame) -> pl.DataFrame:
    """Per symbol-day OHLCV from one symbol's canonical minute bars (sorted by ts)."""
    return (
        minute.group_by("symbol", "trade_date", maintain_order=True)
        .agg(
            pl.col("open").first(),
            pl.col("high").max(),
            pl.col("low").min(),
            pl.col("close").last(),
            pl.col("volume").sum(),
            (pl.col("close") * pl.col("volume")).sum().alias("turnover"),
            pl.len().alias("bars"),
            pl.col("close").pct_change().abs().max().alias("max_minute_move"),
        )
        .sort("trade_date")
    )


def _ratio_label(gap: float) -> str | None:
    """Name the split/bonus-like ratio a gap matches, if any (e.g. 'split 1:2')."""
    if gap <= -1:
        return None
    # A split/bonus drops the price (gap < 0, ratio = old/new); a consolidation raises it.
    r = 1 / (1 + gap) if gap < 0 else 1 + gap
    for k in SPLIT_RATIOS:
        if abs(r - k) / k < RATIO_TOL:
            return f"{'split/bonus' if gap < 0 else 'consolidation'} {k:.3g}:1"
    return None


def gap_events(days: pl.DataFrame) -> pl.DataFrame:
    """Overnight gaps (open vs previous session close) and intraday jumps above thresholds."""
    d = days.with_columns(
        pl.col("close").shift(1).alias("prev_close"), pl.col("trade_date").shift(1).alias("prev_date")
    ).with_columns((pl.col("open") / pl.col("prev_close") - 1).alias("gap"))
    gaps = d.filter(pl.col("gap").abs() > GAP_THRESHOLD).select(
        "symbol",
        "trade_date",
        "prev_date",
        pl.lit("OVERNIGHT_GAP").alias("kind"),
        pl.col("gap").alias("move"),
        "prev_close",
        "open",
        pl.col("volume").alias("day_volume"),
        (pl.col("volume") / pl.col("volume").shift(1).rolling_median(20)).alias("volume_vs_median"),
        (pl.col("trade_date") - pl.col("prev_date")).dt.total_days().alias("calendar_days_since_prev"),
    )
    jumps = d.filter(pl.col("max_minute_move") > JUMP_THRESHOLD).select(
        "symbol",
        "trade_date",
        "prev_date",
        pl.lit("INTRADAY_JUMP").alias("kind"),
        pl.col("max_minute_move").alias("move"),
        "prev_close",
        "open",
        pl.col("volume").alias("day_volume"),
        pl.lit(None, dtype=pl.Float64).alias("volume_vs_median"),
        pl.lit(None, dtype=pl.Int64).alias("calendar_days_since_prev"),
    )
    ev = pl.concat([gaps, jumps])
    return ev.with_columns(
        pl.col("move").map_elements(_ratio_label, return_dtype=pl.Utf8).alias("ratio_match")
    )


def symbol_stats(days: pl.DataFrame) -> dict[str, Any]:
    zero, med_close, med_turnover = days.select(
        (pl.col("volume") == 0).mean(), pl.col("close").median(), pl.col("turnover").median()
    ).row(0)
    return {
        "first_date": days["trade_date"].min(),
        "last_date": days["trade_date"].max(),
        "days": days.height,
        "bars": int(days["bars"].sum()),
        "zero_volume_frac": float(zero or 0.0),
        "median_close": float(med_close or 0.0),
        "median_daily_turnover": float(med_turnover or 0.0),
    }


def rename_candidates(hist: pl.DataFrame, max_days: int = 7, max_price_diff: float = 0.02) -> pl.DataFrame:
    """Pairs (old, new) where one symbol stops and another starts days later at a continuous price.

    Only a candidate list for review: no symbol-change reference data is available offline.
    """
    ended = hist.filter(pl.col("status") == "ENDED").select(
        pl.col("symbol").alias("old_symbol"), pl.col("last_date").alias("old_last"), "last_close"
    )
    started = hist.filter(pl.col("status") == "LISTED_LATER").select(
        pl.col("symbol").alias("new_symbol"), pl.col("first_date").alias("new_first"), "first_open"
    )
    if ended.is_empty() or started.is_empty():
        return pl.DataFrame(
            schema={"old_symbol": pl.Utf8, "new_symbol": pl.Utf8, "old_last": pl.Date, "new_first": pl.Date}
        )
    return (
        ended.join(started, how="cross")
        .filter(
            (pl.col("new_first") > pl.col("old_last"))
            & (pl.col("new_first") - pl.col("old_last") <= timedelta(days=max_days))
            & ((pl.col("first_open") / pl.col("last_close") - 1).abs() <= max_price_diff)
        )
        .select("old_symbol", "new_symbol", "old_last", "new_first")
    )


def build(
    canonical_dir: Path, out_dir: Path, reports_dir: Path, eligibility: Eligibility | None = None
) -> dict[str, Any]:
    elig = eligibility or Eligibility()
    files = sorted(p for p in canonical_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no canonical files in {canonical_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    all_days, all_events, rows = [], [], []
    for i, f in enumerate(files):
        if i % 250 == 0:
            log.info("security master %d/%d", i, len(files))
        m = pl.read_parquet(
            f, columns=["symbol", "ts", "open", "high", "low", "close", "volume", "trade_date"]
        )
        if m.is_empty():
            continue
        d = day_bars(m)
        all_days.append(d)
        all_events.append(gap_events(d))
        sym = str(m["symbol"][0])
        st = symbol_stats(d)
        st["last_close"] = float(d["close"][-1])
        st["first_open"] = float(d["open"][0])
        kind, basis = classify(sym, st["zero_volume_frac"])
        rows.append(
            {"symbol": sym, "instrument_type": kind, "basis": basis, "uncertain": sym in UNCERTAIN, **st}
        )
    days = pl.concat(all_days)
    events = pl.concat(all_events)
    master = pl.DataFrame(rows)
    start, end = days["trade_date"].min(), days["trade_date"].max()
    trading_dates = days["trade_date"].unique().sort()
    margin_start = trading_dates[min(5, len(trading_dates) - 1)]
    margin_end = trading_dates[max(len(trading_dates) - 6, 0)]
    master = master.with_columns(
        pl.when(pl.col("last_date") < margin_end)
        .then(pl.lit("ENDED"))
        .when(pl.col("first_date") > margin_start)
        .then(pl.lit("LISTED_LATER"))
        .otherwise(pl.lit("ACTIVE"))
        .alias("status"),
    )
    n_events = events.group_by("symbol").agg(pl.len().alias("ca_events"))
    master = (
        master.join(n_events, on="symbol", how="left")
        .with_columns(pl.col("ca_events").fill_null(0))
        .with_columns(
            (
                (pl.col("instrument_type") == EQUITY)
                & (pl.col("days") >= elig.min_days)
                & (pl.col("zero_volume_frac") <= elig.max_zero_volume_frac)
                & (pl.col("median_daily_turnover") >= elig.min_median_daily_turnover)
            ).alias("experiment_eligible"),
            pl.lit(SECURITY_MASTER_VERSION).alias("version"),
        )
        .sort("symbol")
    )
    renames = rename_candidates(master)
    history = master.select("symbol", "first_date", "last_date", "status", "last_close", "first_open").join(
        renames.select(
            pl.col("new_symbol").alias("symbol"), pl.col("old_symbol").alias("rename_candidate_of")
        ),
        on="symbol",
        how="left",
    )

    days.write_parquet(out_dir / "day_bars.parquet")
    master.write_parquet(out_dir / "security_master.parquet")
    master.select("symbol", "instrument_type", "basis", "uncertain").write_parquet(
        out_dir / "instrument_classification.parquet"
    )
    history.write_parquet(out_dir / "symbol_history.parquet")
    events.sort("symbol", "trade_date").write_parquet(out_dir / "corporate_action_events.parquet")

    summary = {
        "version": SECURITY_MASTER_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "date_range": [str(start), str(end)],
        "symbols": master.height,
        "by_type": dict(master.group_by("instrument_type").len().sort("instrument_type").iter_rows()),
        "by_status": dict(master.group_by("status").len().sort("status").iter_rows()),
        "experiment_eligible": int(master["experiment_eligible"].sum()),
        "eligibility_rules": elig.__dict__,
        "events": dict(events.group_by("kind").len().sort("kind").iter_rows()),
        "rename_candidates": renames.height,
    }
    (out_dir / "security_master_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (reports_dir / "security_master.md").write_text(render_master(summary, master, renames))
    (reports_dir / "corporate_action_audit.md").write_text(render_audit(events, master))
    return summary


def _table(df: pl.DataFrame, cols: list[str]) -> list[str]:
    def fmt(v: Any) -> str:
        if isinstance(v, float):
            return "" if math.isnan(v) else f"{v:.4g}"
        return "" if v is None else str(v)

    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += [
        "| " + " | ".join(fmt(r[c]) for c in cols) + " |" for r in df.select(cols).iter_rows(named=True)
    ]
    return lines


def render_master(summary: dict[str, Any], master: pl.DataFrame, renames: pl.DataFrame) -> str:
    unc = master.filter(pl.col("uncertain"))
    idx_vol = master.filter((pl.col("instrument_type") == INDEX) & (pl.col("zero_volume_frac") < 0.99))
    eq_zero = master.filter((pl.col("instrument_type") == EQUITY) & (pl.col("zero_volume_frac") > 0.9))
    lines = [
        "# Security master",
        "",
        f"`{summary['version']}`, built {summary['created_at']} from canonical minute data "
        f"{summary['date_range'][0]} .. {summary['date_range'][1]}. All figures computed from the data.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| symbols | {summary['symbols']} |",
        *[f"| type {k} | {v} |" for k, v in summary["by_type"].items()],
        *[f"| status {k} | {v} |" for k, v in summary["by_status"].items()],
        f"| experiment-eligible equities | {summary['experiment_eligible']} |",
        f"| rename candidates | {summary['rename_candidates']} |",
        "",
        "Eligibility (EQUITY only): "
        + ", ".join(f"{k}={v}" for k, v in summary["eligibility_rules"].items())
        + ". Turnover is close x volume summed over regular-session minute bars, in INR.",
        "",
        "## Limitations",
        "",
        "- No official NSE security master is reachable offline; ETF and other types come from a curated "
        "list (`ml/src/pulsetrader/security/lists.py`), indices from names and zero volume.",
        "- Symbol history covers only symbols present in this dataset (2022-01 onward). Renames are "
        "inferred candidates, not confirmed. Securities delisted before 2022 are absent, so survivorship "
        "bias before the data start cannot be measured; symbols that ENDED inside the window are kept.",
        "",
        *(
            [
                "- **Survivorship bias:** no symbol stops trading before the dataset end, so the dataset "
                "holds only securities still listed when it was downloaded. Stocks delisted or merged away "
                "during 2022-2026 are missing. Results are therefore biased toward survivors; this cannot be "
                "corrected offline and must be stated with every result.",
                "",
            ]
            if "ENDED" not in summary["by_status"]
            else []
        ),
        "## Indices with traded volume (check)",
        "",
        *(_table(idx_vol, ["symbol", "zero_volume_frac"]) if idx_vol.height else ["None."]),
        "",
        "## Equities with almost no traded volume (excluded by eligibility)",
        "",
        *(_table(eq_zero, ["symbol", "days", "zero_volume_frac"]) if eq_zero.height else ["None."]),
        "",
        "## Uncertain classifications",
        "",
        *(_table(unc, ["symbol", "instrument_type", "basis", "median_close"]) if unc.height else ["None."]),
        "",
        "## Rename candidates",
        "",
        *(
            _table(renames, ["old_symbol", "new_symbol", "old_last", "new_first"])
            if renames.height
            else ["None."]
        ),
    ]
    return "\n".join(lines) + "\n"


def render_audit(events: pl.DataFrame, master: pl.DataFrame) -> str:
    ev = events.join(master.select("symbol", "instrument_type"), on="symbol", how="left")
    eq = ev.filter(pl.col("instrument_type") == EQUITY)
    gaps = eq.filter(pl.col("kind") == "OVERNIGHT_GAP")
    ratio = gaps.filter(pl.col("ratio_match").is_not_null())
    top = gaps.sort(pl.col("move").abs(), descending=True).head(40)
    lines = [
        "# Corporate-action audit",
        "",
        "Generated from canonical minute data (regular session). Suspicious events are overnight gaps "
        f"above {GAP_THRESHOLD:.0%} (NSE price bands cap most stocks at 20%/day) and single-minute "
        f"moves above {JUMP_THRESHOLD:.0%} inside a session. Gaps close to a split/bonus ratio are labelled.",
        "",
        "## Finding: prices are already adjusted",
        "",
        "Known corporate actions show no price discontinuity in this dataset, e.g. RELIANCE 1:1 bonus "
        "(ex-date 2024-10-28): close 1328.15 on 2024-10-25, open 1337.00 on 2024-10-28. The vendor "
        "(Upstox, per the dataset card) back-adjusts history. Consequences:",
        "",
        "- Absolute price levels before an action are not what traded at the time; only scale-free "
        "features (returns, ratios, normalised indicators) are point-in-time safe. Raw price levels must "
        "not be used as model inputs.",
        "- Adjustment uses information from after the action date (future corporate actions). Returns "
        "and ratios are unaffected by a multiplicative adjustment, so they carry no leakage from it.",
        "- Residual unadjusted actions show up as the events below and are handled by the policy.",
        "",
        "## Event counts",
        "",
        "| Scope | Events | Symbols |",
        "|---|---|---|",
        f"| all instruments | {events.height} | {events['symbol'].n_unique()} |",
        f"| equities: overnight gaps | {gaps.height} | {gaps['symbol'].n_unique()} |",
        f"| equities: gaps at split/bonus ratios | {ratio.height} | {ratio['symbol'].n_unique()} |",
        f"| equities: intraday jumps | {eq.filter(pl.col('kind') == 'INTRADAY_JUMP').height} | "
        f"{eq.filter(pl.col('kind') == 'INTRADAY_JUMP')['symbol'].n_unique()} |",
        "",
        "## Largest equity overnight gaps",
        "",
        *_table(
            top,
            ["symbol", "trade_date", "calendar_days_since_prev", "move", "prev_close", "open", "ratio_match"],
        ),
        "",
        "## Gaps matching split/bonus ratios",
        "",
        *(
            _table(
                ratio.sort("trade_date"),
                ["symbol", "trade_date", "move", "prev_close", "open", "ratio_match", "volume_vs_median"],
            )
            if ratio.height
            else ["None."]
        ),
        "",
        "## Policy",
        "",
        "- Events are stored in `data/reference/corporate_action_events.parquet`.",
        "- Labels never cross a session boundary, so an overnight gap never enters a label.",
        "- Features whose rolling window spans a flagged OVERNIGHT_GAP for that symbol are distorted; "
        "the event session and the next session of that symbol are excluded from training/evaluation "
        "datasets (`flagged_days`, applied when datasets are built). Extreme returns are never treated as "
        "opportunities by default.",
        "- Large gaps that match no ratio are mostly unadjusted demergers (e.g. RAYMOND 2025-05-14, "
        "ABFRL 2025-05-22, SKFINDIA 2025-10-15) or resumption after a suspension "
        "(calendar_days_since_prev large); both are excluded by the same rule.",
    ]
    return "\n".join(lines) + "\n"


def flagged_days(events: pl.DataFrame, days: pl.DataFrame, sessions_after: int = 1) -> pl.DataFrame:
    """(symbol, trade_date) pairs to exclude from datasets: each OVERNIGHT_GAP date plus the next
    `sessions_after` sessions of that symbol, so no rolling feature window spans the discontinuity
    (the longest minute-bar window, SMA 200, is shorter than one 375-bar session)."""
    g = events.filter(pl.col("kind") == "OVERNIGHT_GAP").select("symbol", "trade_date").unique()
    if g.is_empty():
        return g
    seq = (
        days.select("symbol", "trade_date")
        .sort("symbol", "trade_date")
        .with_columns(pl.int_range(pl.len()).over("symbol").alias("n"))
    )
    hit = g.join(seq, on=["symbol", "trade_date"]).select("symbol", pl.col("n").alias("n0"))
    return (
        seq.join(hit, on="symbol")
        .filter((pl.col("n") >= pl.col("n0")) & (pl.col("n") <= pl.col("n0") + sessions_after))
        .select("symbol", "trade_date")
        .unique()
        .sort("symbol", "trade_date")
    )
