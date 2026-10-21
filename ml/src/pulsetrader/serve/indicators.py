"""Technical indicators and market regime for one symbol and session, for the stock detail page.

Indicators come from the shared feature engine (`features.engine.compute_symbol_features`), run on the
canonical minute bars of the requested session plus up to `WARMUP_SESSIONS` earlier sessions, so the
dashboard shows the same formulas the models were trained on. Long-memory features (EMA 50, SMA 200)
can differ slightly from a full-history computation; `parity` in the reply says how they were built.

The regime is the Phase 11 definition: previous-day NIFTY close vs its 50-day average (trend) and the
previous-day 20-day realised volatility tercile (cut-offs from the training period). Known at the open.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from pulsetrader.data.io import safe_name
from pulsetrader.experiments.robustness import MARKET_INDEX, daily_regimes
from pulsetrader.features.engine import compute_symbol_features

WARMUP_SESSIONS = 5
# features shown on the page: (column, label)
PANEL = (
    ("rsi_14", "RSI 14"),
    ("macd", "MACD"),
    ("macd_signal", "MACD signal"),
    ("macd_hist", "MACD histogram"),
    ("adx_14", "ADX 14"),
    ("di_plus_14", "DI+ 14"),
    ("di_minus_14", "DI- 14"),
    ("atr_pct_14", "ATR % 14"),
    ("bb_width_20", "Bollinger width 20"),
    ("stoch_k_14", "Stochastic %K 14"),
    ("williams_r_14", "Williams %R 14"),
    ("rel_volume_20", "Relative volume 20"),
    ("vwap_dist", "Distance from VWAP"),
    ("sma_20_ratio", "Close / SMA 20 - 1"),
    ("sma_50_ratio", "Close / SMA 50 - 1"),
    ("ema_20_ratio", "Close / EMA 20 - 1"),
    ("realized_vol_30", "Realised volatility 30"),
    ("ret_since_open", "Return since open"),
)
SERIES = ("rsi_14", "macd_hist", "vwap_dist")


class IndicatorsUnavailable(Exception):
    """No canonical bars for the symbol/session."""


def _clean(v: Any) -> Any:
    if isinstance(v, float) and v != v:  # NaN
        return None
    return v


def indicators(data_root: Path, symbol: str, day: date) -> dict[str, Any]:
    f = data_root / "canonical" / f"{safe_name(symbol)}.parquet"
    if not f.exists():
        raise IndicatorsUnavailable(f"no canonical bars for {symbol}")
    lf = pl.scan_parquet(f)
    dates = (
        lf.filter(pl.col("trade_date") <= day)
        .select(pl.col("trade_date").unique())
        .collect()["trade_date"]
        .sort()
    )
    if dates.len() == 0 or dates[-1] != day:
        raise IndicatorsUnavailable(f"no bars for {symbol} on {day.isoformat()}")
    sessions = dates[-(WARMUP_SESSIONS + 1) :].to_list()
    feats, _ = compute_symbol_features(lf.filter(pl.col("trade_date").is_in(sessions)))
    today = feats.filter(pl.col("trade_date") == day).sort("ts")
    last = today.row(-1, named=True)
    return {
        "symbol": symbol,
        "date": day.isoformat(),
        "bar_ts": last["ts"].isoformat(),
        "availability_ts": last["availability_ts"].isoformat(),
        "feature_version": last["feature_version"],
        "latest": [{"name": c, "label": lbl, "value": _clean(last[c])} for c, lbl in PANEL],
        "series": {
            c: [{"ts": t.isoformat(), "value": _clean(v)} for t, v in today.select("ts", c).iter_rows()]
            for c in SERIES
        },
        "parity": {
            "engine": "pulsetrader.features.engine.compute_symbol_features",
            "warmup_sessions": len(sessions) - 1,
        },
        "regime": regime(data_root, day),
    }


def _train_end(data_root: Path) -> date | None:
    for m in sorted((data_root / "datasets").glob("*/dataset_manifest.json")):
        periods = json.loads(m.read_text()).get("periods", [])
        train = next((p for p in periods if p.get("name") == "train"), None)
        if train:
            return date.fromisoformat(train["end"])
    return None


def regime(data_root: Path, day: date) -> dict[str, Any]:
    f = data_root / "reference" / "day_bars.parquet"
    end = _train_end(data_root)
    if not f.exists() or end is None:
        return {"status": "DATA_UNAVAILABLE", "reason": "daily index bars or training period not found"}
    bars = pl.read_parquet(f).filter(pl.col("symbol") == MARKET_INDEX)  # shift(1) inside: no lookahead
    reg = daily_regimes(bars, end).filter(pl.col("trade_date") == day)
    if reg.height == 0 or reg["nifty_trend"][0] is None:
        return {"status": "DATA_UNAVAILABLE", "reason": f"no {MARKET_INDEX} regime for {day.isoformat()}"}
    r = reg.row(0, named=True)
    return {
        "status": "OK",
        "index": MARKET_INDEX,
        "trend": r["nifty_trend"],
        "volatility": r["nifty_vol"],
        "definition": "previous-day NIFTY close vs 50-day average; previous-day 20-day realised vol "
        "tercile (training-period cut-offs)",
        "cuts": json.loads(r["_cuts"]),
    }
