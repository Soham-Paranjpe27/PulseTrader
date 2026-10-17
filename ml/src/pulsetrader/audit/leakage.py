"""Phase 6 leakage gate on real data.

The golden tests (tests/test_leakage.py) prove the code is causal on synthetic data. This module
re-runs the same ideas on the real canonical data and on a built research dataset:

1. Perturbation: change every real bar after a cut-off; features at or before it must not move
   (single-symbol features, market context, cross-sectional features).
2. Timestamps: availability_ts = bar close, every label ends after availability.
3. Labels: recomputed from canonical closes for a random sample; no label crosses a session.
4. Splits: chronological, non-overlapping, purge and embargo hold at both boundaries.
5. Universe: the liquidity ranking window ends before validation starts.
6. Scaler isolation: the Preprocessor refuses non-training rows and fits on train-only statistics.

Every check returns a CheckResult; the gate passes only when all of them pass.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from pulsetrader.config import BAR_MINUTES
from pulsetrader.data.io import safe_name
from pulsetrader.features.engine import (
    FeatureSet,
    add_market_context,
    add_relative_strength,
    compute_symbol_features,
)
from pulsetrader.features.preprocess import PreprocessError, Preprocessor

AUDIT_VERSION = "leakage-audit-v1"


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


def perturb_after(df: pl.DataFrame, cut_ts: datetime, seed: int = 0) -> pl.DataFrame:
    """Scale OHLC by random factors and distort volume for every bar strictly after `cut_ts`."""
    m = pl.col("ts") > cut_ts
    rng = np.random.default_rng(seed)
    f = pl.Series(rng.uniform(0.5, 2.0, df.height))
    return df.with_columns(
        *[pl.when(m).then(pl.col(c) * f).otherwise(pl.col(c)).alias(c) for c in ("open", "close")],
        pl.when(m).then(pl.col("volume") * 7 + 13).otherwise(pl.col("volume")).alias("volume"),
    ).with_columns(
        pl.max_horizontal("open", "close", "high").alias("high"),
        pl.min_horizontal("open", "close", "low").alias("low"),
    )


def _diff_cols(a: pl.DataFrame, b: pl.DataFrame, cols: list[str]) -> dict[str, float]:
    """Max abs difference per column for columns that differ (NaN/null positions must match)."""
    bad: dict[str, float] = {}
    for c in cols:
        x = a[c].cast(pl.Float64).to_numpy()
        y = b[c].cast(pl.Float64).to_numpy()
        if x.shape != y.shape or not np.array_equal(np.isnan(x), np.isnan(y)):
            bad[c] = float("inf")
            continue
        ok = ~np.isnan(x)
        if not np.allclose(x[ok], y[ok], rtol=1e-9, atol=1e-12):
            bad[c] = float(np.max(np.abs(x[ok] - y[ok])))
    return bad


def _cut_points(df: pl.DataFrame, rng: np.random.Generator, n: int) -> list[datetime]:
    """Session-open, mid-session and last-bar cut-offs on randomly chosen dates (not the first year)."""
    dates = df["trade_date"].unique().sort().to_list()
    pool = np.arange(len(dates) // 4, len(dates) - 1)
    pick = rng.choice(pool, size=min(n, len(pool)), replace=False)
    cuts: list[datetime] = []
    for k, i in enumerate(sorted(pick)):
        day = df.filter(pl.col("trade_date") == dates[int(i)])["ts"].sort()
        pos = (0, day.len() // 2, day.len() - 1)[k % 3]
        cuts.append(day[pos])
    return cuts


def check_symbol_perturbation(
    canonical: Path, symbols: list[str], cuts_per_symbol: int, seed: int
) -> CheckResult:
    rng = np.random.default_rng(seed)
    tested, leaks = 0, {}
    rows = 0
    for sym in symbols:
        base = pl.read_parquet(canonical / f"{safe_name(sym)}.parquet").sort("ts")
        if "trade_date" not in base.columns:
            base = base.with_columns(pl.col("ts").dt.date().alias("trade_date"))
        f0, fs = compute_symbol_features(base)
        for cut in _cut_points(base, rng, cuts_per_symbol):
            f1, _ = compute_symbol_features(perturb_after(base, cut, seed))
            m = pl.col("ts") <= cut
            a, b = f0.filter(m), f1.filter(m)
            bad = _diff_cols(a, b, fs.names)
            if bad:
                leaks[f"{sym}@{cut}"] = bad
            tested += 1
            rows += a.height
    return CheckResult(
        "single-symbol feature perturbation",
        not leaks,
        f"{tested} cut-offs on {len(symbols)} real symbols, {rows:,} past rows compared, {len(leaks)} leaks",
        {"symbols": symbols, "leaks": leaks},
    )


def check_market_perturbation(canonical: Path, index_symbol: str, stock: str, seed: int) -> CheckResult:
    rng = np.random.default_rng(seed)
    idx = pl.read_parquet(canonical / f"{safe_name(index_symbol)}.parquet").sort("ts")
    stk, _ = compute_symbol_features(pl.read_parquet(canonical / f"{safe_name(stock)}.parquet"))
    if "trade_date" not in idx.columns:
        idx = idx.with_columns(pl.col("ts").dt.date().alias("trade_date"))
    n0, _ = compute_symbol_features(idx)
    leaks: dict[str, Any] = {}
    cuts = _cut_points(idx, rng, 3)
    names: list[str] = []
    for cut in cuts:
        n1, _ = compute_symbol_features(perturb_after(idx, cut, seed))
        fs0, fs1 = FeatureSet(), FeatureSet()
        a = add_market_context(stk, n0, "mkt", fs0).filter(pl.col("ts") <= cut)
        b = add_market_context(stk, n1, "mkt", fs1).filter(pl.col("ts") <= cut)
        names = fs0.names
        bad = _diff_cols(a, b, names)
        if bad:
            leaks[str(cut)] = bad
    return CheckResult(
        "market-context perturbation",
        not leaks,
        f"{index_symbol} perturbed after {len(cuts)} cut-offs, joined to {stock}; {len(names)} "
        f"market features compared, {len(leaks)} leaks",
        {"leaks": leaks},
    )


REL_INPUTS = ("ret_5", "ret_15", "ret_60", "rel_volume_20", "vol_20")


def check_cross_sectional_perturbation(chunk: pl.DataFrame, seed: int) -> CheckResult:
    """Distort other stocks' rows after a cut-off; relative features at or before it must not move."""
    rng = np.random.default_rng(seed)
    chunk = chunk.with_columns(pl.col(c).cast(pl.Float64) for c in REL_INPUTS)  # same dtype both runs
    probe = chunk["symbol"].unique().sort()[0]
    fs = FeatureSet()
    base = add_relative_strength(chunk, fs)
    names = fs.names
    ts = chunk["ts"].unique().sort()
    leaks: dict[str, Any] = {}
    cuts = [ts[int(i)] for i in rng.integers(1, ts.len() - 1, size=3)]
    for cut in cuts:
        m = (pl.col("ts") > cut) & (pl.col("symbol") != probe)
        noise = pl.Series(rng.normal(0, 0.05, chunk.height))
        pert = chunk.with_columns(
            [pl.when(m).then(pl.col(c) + noise).otherwise(pl.col(c)).alias(c) for c in REL_INPUTS]
        )
        out = add_relative_strength(pert, FeatureSet())
        keep = (pl.col("ts") <= cut) & (pl.col("symbol") == probe)
        bad = _diff_cols(base.filter(keep), out.filter(keep), names)
        if bad:
            leaks[str(cut)] = bad
    return CheckResult(
        "cross-sectional perturbation",
        not leaks,
        f"other stocks' inputs distorted after {len(cuts)} cut-offs; {probe}'s {len(names)} relative "
        f"features compared, {len(leaks)} leaks",
        {"probe": probe, "leaks": leaks},
    )


def check_timestamps(ds: pl.LazyFrame, horizons: list[int]) -> CheckResult:
    exprs = [
        (pl.col("availability_ts") != pl.col("ts") + timedelta(minutes=BAR_MINUTES)).sum().alias("avail"),
        (pl.col("feature_ts") != pl.col("ts")).sum().alias("feature_ts"),
    ]
    for h in horizons:
        exprs.append((pl.col(f"label_end_ts_{h}") <= pl.col("availability_ts")).sum().alias(f"end_{h}"))
        # a label may only exist if its future bar is on the same trade date
        exprs.append(
            (
                pl.col(f"fret_{h}").is_not_null()
                & ((pl.col("ts") + timedelta(minutes=h)).dt.date() != pl.col("trade_date"))
            )
            .sum()
            .alias(f"cross_{h}")
        )
    r = ds.select(*exprs, pl.len().alias("rows")).collect().row(0, named=True)
    bad = {k: int(v) for k, v in r.items() if k != "rows" and v}
    return CheckResult(
        "timestamps and session boundaries",
        not bad,
        f"{r['rows']:,} rows: availability_ts = bar close, label_end_ts > availability_ts and no label "
        f"crosses a session for horizons {horizons}; violations {bad or 0}",
        {"violations": bad},
    )


def check_label_recompute(
    ds: pl.LazyFrame, canonical: Path, horizons: list[int], n_symbols: int, seed: int
) -> CheckResult:
    rng = np.random.default_rng(seed)
    syms = ds.select("symbol").unique().collect()["symbol"].sort().to_list()
    pick = [syms[int(i)] for i in rng.choice(len(syms), size=min(n_symbols, len(syms)), replace=False)]
    checked, mismatches = 0, {}
    for sym in pick:
        rows = (
            ds.filter(pl.col("symbol") == sym)
            .select("ts", "trade_date", "close", *[f"fret_{h}" for h in horizons])
            .collect()
        )
        can = pl.read_parquet(canonical / f"{safe_name(sym)}.parquet").select("ts", "close")
        for h in horizons:
            fut = can.select((pl.col("ts") - timedelta(minutes=h)).alias("ts"), pl.col("close").alias("fc"))
            j = rows.join(fut, on="ts", how="left").with_columns(
                pl.when((pl.col("ts") + timedelta(minutes=h)).dt.date() == pl.col("trade_date"))
                .then(pl.col("fc") / pl.col("close").cast(pl.Float64) - 1)
                .otherwise(None)
                .alias("exp")
            )
            x = j[f"fret_{h}"].cast(pl.Float64).to_numpy()
            y = j["exp"].cast(pl.Float64).to_numpy()
            # stored as float32: compare at float32 precision
            ok = np.array_equal(np.isnan(x), np.isnan(y)) and np.allclose(
                x[~np.isnan(x)], y[~np.isnan(y)], rtol=1e-4, atol=1e-6
            )
            if not ok:
                mismatches[f"{sym}:{h}"] = int(
                    np.sum(~np.isclose(x, y, rtol=1e-4, atol=1e-6, equal_nan=True))
                )
            checked += j.height
    return CheckResult(
        "label recomputation from canonical",
        not mismatches,
        f"{checked:,} (row, horizon) labels recomputed for {len(pick)} symbols; "
        f"{len(mismatches)} mismatching series",
        {"symbols": pick, "mismatches": mismatches},
    )


def check_splits(ds: pl.LazyFrame, manifest: dict[str, Any]) -> CheckResult:
    periods = manifest["periods"]
    embargo = int(manifest["config"]["embargo_minutes"])
    longest = max(manifest["config"]["horizons"])
    end_col = f"label_end_ts_{longest}"
    problems: list[str] = []
    bounds = (
        ds.filter(pl.col("split").is_not_null())
        .group_by("split")
        .agg(
            pl.col("ts").min().alias("min_ts"),
            pl.col("ts").max().alias("max_ts"),
            pl.col(end_col).max().alias("max_end"),
            pl.col("trade_date").min().alias("d0"),
            pl.col("trade_date").max().alias("d1"),
            pl.len().alias("rows"),
        )
        .collect()
    )
    b = {r["split"]: r for r in bounds.iter_rows(named=True)}
    # period starts in the full data (purged rows included) for embargo checks
    raw_start = {
        p["name"]: ds.filter(pl.col("trade_date") >= date.fromisoformat(p["start"]))
        .select(pl.col("ts").min())
        .collect()
        .item()
        for p in periods
    }
    names = [p["name"] for p in periods]
    for p in periods:
        r = b.get(p["name"])
        if r is None:
            problems.append(f"{p['name']} empty")
            continue
        if not (str(r["d0"]) >= p["start"] and str(r["d1"]) <= p["end"]):
            problems.append(f"{p['name']} rows outside its period")
    for prev, nxt in zip(names, names[1:], strict=False):
        if prev not in b or nxt not in b:
            continue
        if b[prev]["max_ts"] >= b[nxt]["min_ts"]:
            problems.append(f"{prev} overlaps {nxt}")
        if b[prev]["max_end"] > raw_start[nxt]:
            problems.append(f"purge failed: {prev} label ends {b[prev]['max_end']} after {nxt} starts")
        if b[nxt]["min_ts"] < raw_start[nxt] + timedelta(minutes=embargo):
            problems.append(f"embargo failed at {nxt}")
    purged = ds.select(pl.col("purged").sum()).collect().item()
    span = ", ".join(f"{p['name']} {p['start']}..{p['end']}" for p in periods)
    return CheckResult(
        "chronological split, purge and embargo",
        not problems,
        f"periods {span}; {purged:,} rows purged/embargoed; problems: {problems or 'none'}",
        {
            "bounds": {k: {kk: str(vv) for kk, vv in v.items()} for k, v in b.items()},
            "problems": problems,
        },
    )


def check_universe(manifest: dict[str, Any]) -> CheckResult:
    window_end = manifest["universe_selection"]["ranking_window"][1]
    train_end = next(p["end"] for p in manifest["periods"] if p["name"] == "train")
    ok = window_end <= train_end
    return CheckResult(
        "point-in-time universe",
        ok,
        f"liquidity ranking window ends {window_end}; training ends {train_end}",
        {"ranking_window": manifest["universe_selection"]["ranking_window"]},
    )


def check_scaler(ds: pl.LazyFrame, features: list[str]) -> CheckResult:
    sample = (
        ds.filter(pl.col("split").is_not_null())
        .filter(pl.col("ts").dt.minute() % 30 == 0)
        .select("ts", "split", *features)
        .collect()
    )
    refused = False
    try:
        Preprocessor.fit(sample, features, "audit")
    except PreprocessError:
        refused = True
    train = sample.filter(pl.col("split") == "train")
    pp = Preprocessor.fit(train, features, "audit")
    x = train.select(features).to_numpy().astype(np.float64)
    med = np.nan_to_num(np.nanmedian(x, axis=0))
    means = np.where(np.isnan(x), med, x).mean(axis=0)
    stats_ok = bool(np.allclose(pp.means, means))
    period_ok = pp.fit_period[1] == str(train["ts"].max())
    return CheckResult(
        "scaler isolation",
        refused and stats_ok and period_ok,
        f"fit on mixed splits refused={refused}; train-only means match={stats_ok}; fit period ends "
        f"{pp.fit_period[1]} (train max)",
        {"train_rows": train.height},
    )


def run(
    data_root: Path,
    dataset_dir: Path,
    perturb_symbols: int = 3,
    cuts_per_symbol: int = 6,
    label_symbols: int = 10,
    seed: int = 7,
) -> dict[str, Any]:
    canonical = data_root / "canonical"
    manifest = json.loads((dataset_dir / "dataset_manifest.json").read_text())
    features = json.loads((dataset_dir / "features.json").read_text())["features"]
    horizons = list(manifest["config"]["horizons"])
    ds = pl.scan_parquet(dataset_dir / "part-*.parquet")
    universe = manifest["universe"]
    index_symbol = next(iter(manifest["config"]["market_indices"]))
    rng = np.random.default_rng(seed)
    syms = [universe[int(i)] for i in rng.choice(len(universe), size=perturb_symbols, replace=False)]

    parts = sorted(dataset_dir.glob("part-*.parquet"))
    day = pl.read_parquet(parts[len(parts) // 2])
    first_day = day["trade_date"].min()
    chunk = day.filter(pl.col("trade_date") == first_day)

    checks = [
        check_symbol_perturbation(canonical, syms, cuts_per_symbol, seed),
        check_market_perturbation(canonical, index_symbol, universe[0], seed),
        check_cross_sectional_perturbation(chunk, seed),
        check_timestamps(ds, horizons),
        check_label_recompute(ds, canonical, horizons, label_symbols, seed),
        check_splits(ds, manifest),
        check_universe(manifest),
        check_scaler(ds, features),
    ]
    return {
        "audit_version": AUDIT_VERSION,
        "dataset_id": manifest["dataset_id"],
        "passed": all(c.passed for c in checks),
        "checks": [asdict(c) for c in checks],
    }


def render(report: dict[str, Any]) -> str:
    lines = [
        "# Leakage audit on real data",
        "",
        f"Audit `{report['audit_version']}` on dataset `{report['dataset_id']}`. "
        f"Gate: **{'PASSED' if report['passed'] else 'FAILED'}**.",
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
    ]
    for c in report["checks"]:
        lines.append(f"| {c['name']} | {'PASS' if c['passed'] else 'FAIL'} | {c['detail']} |")
    lines.append("")
    return "\n".join(lines)
