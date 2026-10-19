"""Phases 4-5 on real data: leakage-safe research dataset = features + labels + split tags.

Full-resolution features for 1,300 symbols would be ~100 GB, so features are computed per symbol on
the fly (the one shared engine, over the symbol's full history so rolling windows warm up), then
rows are filtered and sampled every `sample_every` minutes on a common clock, so every sampled
timestamp holds the whole cross-section for the leave-one-out relative-strength features.

Universe (point-in-time): experiment-eligible equities ranked by median daily turnover over the
first `universe_days` trading days only, so the choice never uses later data. The dataset still
inherits the source's survivorship bias (no delisted stocks), which is reported in the manifest.

Row exclusions: the first `warmup_bars` bars of each symbol (long windows not warm), sessions with
fewer than `min_session_bars` bars, and corporate-action event sessions (`flagged_days`).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from pulsetrader.config import FEATURE_VERSION, HORIZONS, LABEL_VERSION, THRESHOLDS
from pulsetrader.data.io import safe_name
from pulsetrader.features.engine import (
    FeatureSet,
    add_cross_sectional,
    compute_symbol_features,
)
from pulsetrader.labels.labels import add_labels, label_name
from pulsetrader.security.master import flagged_days
from pulsetrader.splits.splits import Period, assign, date_split

log = logging.getLogger(__name__)

DATASET_BUILDER_VERSION = "dataset-v1"


@dataclass
class DatasetConfig:
    universe_size: int = 100
    universe_days: int = 250  # trading days used to rank liquidity (all inside the training period)
    sample_every: int = 5  # minutes; sampled bars are those with minute-of-session % sample_every == 0
    warmup_bars: int = 250
    min_session_bars: int = 370
    horizons: tuple[int, ...] = HORIZONS
    thresholds: tuple[float, ...] = THRESHOLDS
    fractions: tuple[float, float, float] = (0.70, 0.15, 0.15)
    embargo_minutes: int = 60
    market_indices: dict[str, str] = field(
        default_factory=lambda: {"NIFTY": "nifty", "BANKNIFTY": "banknifty"}
    )
    vix_symbol: str | None = "INDIA VIX"


def select_universe(reference: Path, cfg: DatasetConfig) -> tuple[list[str], dict[str, Any]]:
    master = pl.read_parquet(reference / "security_master.parquet")
    days = pl.read_parquet(reference / "day_bars.parquet")
    dates = days["trade_date"].unique().sort()
    cutoff = dates[min(cfg.universe_days, len(dates)) - 1]
    eligible = master.filter(pl.col("experiment_eligible"))["symbol"].implode()
    ranked = (
        days.filter(pl.col("symbol").is_in(eligible) & (pl.col("trade_date") <= cutoff))
        .group_by("symbol")
        .agg(pl.col("turnover").median().alias("median_turnover"), pl.len().alias("days"))
        .filter(pl.col("days") >= int(0.95 * cfg.universe_days))
        .sort("median_turnover", "symbol", descending=[True, False])
    )
    universe = ranked.head(cfg.universe_size)["symbol"].to_list()
    info = {
        "rule": f"top {cfg.universe_size} experiment-eligible equities by median daily turnover over "
        f"trade dates {dates[0]}..{cutoff}, present on >=95% of those days",
        "ranking_window": [str(dates[0]), str(cutoff)],
        "survivorship_bias": "source contains no delisted symbols; universe drawn from survivors",
    }
    return universe, info


def _index_features(canonical: Path, symbol: str) -> pl.DataFrame:
    feats, _ = compute_symbol_features(pl.read_parquet(canonical / f"{safe_name(symbol)}.parquet"))
    return feats


def symbol_rows(
    canonical: Path,
    symbol: str,
    cfg: DatasetConfig,
    exclude: pl.DataFrame,
    session_bars: pl.DataFrame,
) -> tuple[pl.DataFrame, FeatureSet]:
    raw = pl.read_parquet(canonical / f"{safe_name(symbol)}.parquet")
    feats, fs = compute_symbol_features(raw)
    out = add_labels(feats, cfg.horizons, cfg.thresholds)
    out = (
        out.with_row_index("_n")
        .filter(pl.col("_n") >= cfg.warmup_bars)
        .drop("_n")
        .join(session_bars, on=["symbol", "trade_date"], how="left")
        .filter(pl.col("bars") >= cfg.min_session_bars)
        .drop("bars")
        .join(exclude, on=["symbol", "trade_date"], how="anti")
        .filter(pl.col("min_since_open") % cfg.sample_every == 0)
    )
    return out, fs


def _f32(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(pl.col(pl.Float64).cast(pl.Float32))


def build(data_root: Path, out_dir: Path, cfg: DatasetConfig | None = None) -> dict[str, Any]:
    cfg = cfg or DatasetConfig()
    canonical, reference = data_root / "canonical", data_root / "reference"
    universe, uinfo = select_universe(reference, cfg)
    if not universe:
        raise ValueError("empty universe")
    days = pl.read_parquet(reference / "day_bars.parquet")
    events = pl.read_parquet(reference / "corporate_action_events.parquet")
    exclude = flagged_days(events, days)
    session_bars = days.select("symbol", "trade_date", "bars")

    market: list[tuple[str, pl.DataFrame]] = [
        (prefix, _index_features(canonical, sym)) for sym, prefix in cfg.market_indices.items()
    ]
    vix = pl.read_parquet(canonical / f"{safe_name(cfg.vix_symbol)}.parquet") if cfg.vix_symbol else None

    parts = out_dir / "_parts"
    parts.mkdir(parents=True, exist_ok=True)
    fs: FeatureSet | None = None
    for i, sym in enumerate(universe):
        log.info("dataset %d/%d %s", i + 1, len(universe), sym)
        rows, fs_sym = symbol_rows(canonical, sym, cfg, exclude, session_bars)
        fs = fs or fs_sym
        _f32(rows).write_parquet(parts / f"{safe_name(sym)}.parquet")
    assert fs is not None

    # cross-sectional + market features, one month at a time to bound memory
    full = pl.scan_parquet(parts / "*.parquet")
    months = (
        full.select(pl.col("trade_date").dt.truncate("1mo").alias("m"))
        .unique()
        .sort("m")
        .collect()["m"]
        .to_list()
    )
    longest = max(cfg.horizons)
    all_dates = sorted(full.select("trade_date").unique().collect()["trade_date"].to_list())
    periods = date_split(all_dates, cfg.fractions)
    split_of = pl.lit(None, dtype=pl.Utf8)
    for per in periods:
        split_of = (
            pl.when(pl.col("trade_date").is_between(per.start, per.end))
            .then(pl.lit(per.name))
            .otherwise(split_of)
        )
    starts = {
        str(k): v for k, v in full.group_by(split_of.alias("s")).agg(pl.col("ts").min()).collect().iter_rows()
    }
    feature_names: list[str] = []
    fsm = FeatureSet(list(fs.specs))
    out_dir.mkdir(parents=True, exist_ok=True)
    for m in months:
        chunk = full.filter(pl.col("trade_date").dt.truncate("1mo") == m).collect()
        fsm = FeatureSet(list(fs.specs))
        chunk = add_cross_sectional(chunk, market, vix, fsm)
        chunk = assign(chunk, periods, f"label_end_ts_{longest}", cfg.embargo_minutes, starts)
        feature_names = fsm.names
        _f32(chunk.sort("ts", "symbol")).write_parquet(out_dir / f"part-{m:%Y-%m}.parquet")
    for p in parts.glob("*.parquet"):
        p.unlink()
    parts.rmdir()

    manifest = _manifest(out_dir, cfg, universe, uinfo, periods, feature_names, fsm)
    (out_dir / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    (out_dir / "features.json").write_text(
        json.dumps({"feature_version": FEATURE_VERSION, "features": feature_names}, indent=1)
    )
    return manifest


def _manifest(
    out_dir: Path,
    cfg: DatasetConfig,
    universe: list[str],
    uinfo: dict[str, Any],
    periods: list[Period],
    feature_names: list[str],
    fs: FeatureSet,
) -> dict[str, Any]:
    ds = pl.scan_parquet(out_dir / "part-*.parquet")
    counts = ds.group_by("split").agg(pl.len().alias("rows")).collect()
    dist: dict[str, Any] = {}
    for h in cfg.horizons:
        for thr in cfg.thresholds:
            col = label_name(h, thr)
            d = (
                ds.filter(pl.col("split").is_not_null() & pl.col(col).is_not_null())
                .group_by("split", col)
                .agg(pl.len().alias("n"))
                .collect()
            )
            dist[col] = {
                s: {str(int(k)): int(n) for _, k, n in d.filter(pl.col("split") == s).iter_rows()}
                for s in ("train", "validation", "test")
            }
    stats = ds.select(
        pl.len().alias("rows"), pl.col("ts").min().alias("min_ts"), pl.col("ts").max().alias("max_ts")
    ).collect()
    r = stats.row(0, named=True)
    return {
        "builder_version": DATASET_BUILDER_VERSION,
        "dataset_id": f"{DATASET_BUILDER_VERSION}-{FEATURE_VERSION}-{LABEL_VERSION}"
        f"-u{len(universe)}-s{cfg.sample_every}",
        "feature_version": FEATURE_VERSION,
        "label_version": LABEL_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "config": {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(cfg).items()},
        "universe": universe,
        "universe_selection": uinfo,
        "periods": [p.as_dict() for p in periods],
        "rows": int(r["rows"]),
        "min_ts": str(r["min_ts"]),
        "max_ts": str(r["max_ts"]),
        "rows_by_split": {str(s): int(n) for s, n in counts.iter_rows()},
        "feature_count": len(feature_names),
        "feature_groups": {
            g: len([s for s in fs.specs if s.group == g]) for g in sorted({s.group for s in fs.specs})
        },
        "label_distribution": dist,
        "test_note": "test split is reserved; it must not influence any modelling decision",
    }
