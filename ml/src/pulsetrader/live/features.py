"""Live feature rows from the real-time cache, through the one shared feature engine (spec section 46).

At a sampled bar `ts` the builder runs `compute_symbol_features` on each symbol's cached bars (warm-up
sessions + today's validated bars up to `ts`, nothing later), keeps the bar at `ts`, and adds market
context, the VIX level and relative strength with `add_cross_sectional`, exactly as the dataset builder
does. Feature names and order are checked against the model artifact before inference; missing values
stay missing (the model's training-fit imputer handles them).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import polars as pl

from pulsetrader.features.engine import MARKET_COLS, FeatureSet, add_cross_sectional, compute_symbol_features
from pulsetrader.live.cache import BarCache


class FeatureMismatch(ValueError):
    pass


@dataclass(frozen=True)
class LiveUniverse:
    stocks: list[str]
    market: dict[str, str]  # index symbol -> feature prefix
    vix: str | None
    sample_every: int

    @classmethod
    def from_manifest(cls, dataset_dir: Path) -> LiveUniverse:
        m = json.loads((dataset_dir / "dataset_manifest.json").read_text())
        cfg = m["config"]
        return cls(list(m["universe"]), dict(cfg["market_indices"]), cfg.get("vix_symbol"),
                   int(cfg["sample_every"]))  # fmt: skip

    @property
    def symbols(self) -> list[str]:
        return [*self.stocks, *self.market, *([self.vix] if self.vix else [])]

    def is_sample_bar(self, minute_of_session: int) -> bool:
        return minute_of_session % self.sample_every == 0


def feature_rows(cache: BarCache, uni: LiveUniverse, ts: datetime) -> tuple[pl.DataFrame, list[str]]:
    """One row per universe stock that has a bar at `ts`, with every model feature. Returns the rows and
    the engine's feature names (in the order the dataset builder produces them)."""
    frame = cache.frame(uni.symbols, ts)
    stocks = frame.filter(pl.col("symbol").is_in(uni.stocks))
    feats, fs0 = compute_symbol_features(stocks)
    xs = feats.filter(pl.col("ts") == ts)
    market = []
    for sym, prefix in uni.market.items():
        idx = frame.filter(pl.col("symbol") == sym)
        if idx.height:
            f_idx = compute_symbol_features(idx)[0].filter(pl.col("ts") == ts)
        else:  # index bar missing: its features are missing, never invented
            schema: dict[str, pl.DataType] = {
                "ts": frame.schema["ts"],
                **dict.fromkeys(MARKET_COLS, pl.Float64()),
            }
            f_idx = pl.DataFrame({"ts": [ts], **{c: [None] for c in MARKET_COLS}}, schema=schema)
        market.append((prefix, f_idx))
    vix = frame.filter(pl.col("symbol") == uni.vix) if uni.vix else None
    fs = FeatureSet(list(fs0.specs))
    xs = add_cross_sectional(xs, market, vix, fs)
    return xs.sort("symbol"), fs.names


def check_features(engine_names: list[str], model_features: list[str], engine_version: str,
                   model_version: str) -> None:  # fmt: skip
    """The model must get the features it was trained on, from the same feature version. Inference
    reads them by name into the artifact's own order (`LoadedModel.matrix`), so order cannot drift."""
    if engine_version != model_version:
        raise FeatureMismatch(f"feature version {engine_version} != model's {model_version}")
    missing = [f for f in model_features if f not in set(engine_names)]
    if missing:
        raise FeatureMismatch(f"live engine lacks model features: {missing[:10]}")
