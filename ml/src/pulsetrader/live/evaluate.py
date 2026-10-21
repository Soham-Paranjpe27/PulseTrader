"""Phase 18: live paper evaluation of live (or replayed) predictions and their outcomes.

Per model and mode, over predictions whose outcome is known (label not null):
- full coverage: the model's argmax class vs the realised class -> accuracy, balanced accuracy, MCC,
  Brier and top-class ECE (raw and calibrated probabilities), via `eval.multiclass.multiclass_report`;
- selective (what the user sees): coverage = UP/DOWN calls / all predictions, label accuracy, sign
  accuracy, balanced accuracy and MCC of the calls, rolling accuracy over the last 20/50/100/500 calls,
  daily / weekly / monthly accuracy;
- paper trading per call: return of following the call over its horizon (d * fret), gross and after
  the Phase 12 round-trip costs. Calls are scored independently (no capital or overlap limits), so this
  is an upper bound on what a portfolio could keep, not a backtest.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl
from sklearn import metrics as skm

from pulsetrader.backtest.engine import CostConfig
from pulsetrader.eval.multiclass import multiclass_report

IDX = {"DOWN": 0, "NEUTRAL": 1, "UP": 2}
ROLLING = (20, 50, 100, 500)


def round_trip_cost_bp(costs: CostConfig | None = None, notional: float = 100_000.0) -> float:
    c = costs or CostConfig()
    charges = c.order_cost(notional, "buy") + c.order_cost(notional, "sell")
    return charges / notional * 1e4 + 2 * c.slippage_bp


def outcomes_frame(outs: list[dict[str, Any]]) -> pl.DataFrame:
    rows = [
        {
            "model": f"{o['model_id']}@v{o['model_version']}",
            "mode": o.get("mode") or "UNKNOWN",
            "symbol": o["symbol"],
            "ts": o["market_data_timestamp"],
            "direction": o["direction"],
            "model_class": o["model_class"],
            "actual_class": o["actual_class"],
            "actual_return": o["actual_return"],
            "direction_correct": o["direction_correct"],
            "sign_correct": o["sign_correct"],
            "horizon": o["horizon_minutes"],
            **{f"raw_{k}": o["raw_probability"][k] for k in ("down", "neutral", "up")},
            **{f"cal_{k}": o["calibrated_probability"][k] for k in ("down", "neutral", "up")},
        }
        for o in outs
    ]
    return pl.DataFrame(rows, infer_schema_length=None).with_columns(
        pl.col("ts").str.to_datetime(time_zone="Asia/Kolkata")
    )


def _acc(x: pl.Series) -> float | None:
    return float(x.mean()) if x.len() else None  # type: ignore[arg-type]


def _period(calls: pl.DataFrame, known: pl.DataFrame, fmt: str) -> list[dict[str, Any]]:
    """Calls, accuracy and coverage per calendar period (strftime format)."""
    if not calls.height:
        return []
    per = (
        calls.with_columns(pl.col("ts").dt.strftime(fmt).alias("p"))
        .group_by("p")
        .agg(
            pl.len().alias("calls"),
            pl.col("direction_correct").cast(pl.Float64).mean().alias("accuracy"),
        )
    )
    tot = known.with_columns(pl.col("ts").dt.strftime(fmt).alias("p")).group_by("p").len("n")
    per = (
        per.join(tot, on="p", how="right")
        .sort("p")
        .with_columns(
            pl.col("calls").fill_null(0),
            (pl.col("calls").fill_null(0) / pl.col("n")).alias("coverage"),
        )
    )
    return per.to_dicts()


def evaluate(outs: list[dict[str, Any]], costs: CostConfig | None = None) -> list[dict[str, Any]]:
    if not outs:
        return []
    df = outcomes_frame(outs)
    cost_bp = round_trip_cost_bp(costs)
    res = []
    for (model, mode), g in df.group_by("model", "mode", maintain_order=True):
        g = g.sort("ts", "symbol")
        known = g.filter(pl.col("actual_class").is_not_null())
        y = known["actual_class"].replace_strict(IDX).to_numpy()
        raw = known.select("raw_down", "raw_neutral", "raw_up").to_numpy()
        cal = known.select("cal_down", "cal_neutral", "cal_up").to_numpy()
        full = multiclass_report(y, raw) if known.height else None
        full_cal = multiclass_report(y, cal, pred=raw.argmax(axis=1)) if known.height else None
        calls = known.filter(pl.col("direction").is_in(["UP", "DOWN"]))
        d = np.where(calls["direction"].to_numpy() == "UP", 1.0, -1.0)
        gross = d * calls["actual_return"].to_numpy() * 1e4
        yt = calls["actual_class"].replace_strict(IDX).to_numpy()
        pt = calls["direction"].replace_strict(IDX).to_numpy()
        corr = calls["direction_correct"].cast(pl.Float64)

        res.append({
            "model": model,
            "mode": mode,
            "horizon_minutes": int(g["horizon"][0]),
            "predictions": g.height,
            "evaluated": known.height,
            "label_unavailable": g.height - known.height,
            "first": str(g["ts"].min()),
            "last": str(g["ts"].max()),
            "full_coverage": {k: full[k] for k in ("n", "accuracy", "balanced_accuracy", "mcc", "brier",
                                                   "ece_top", "class_distribution", "pred_distribution")}
            if full else None,
            "calibrated": {k: full_cal[k] for k in ("brier", "ece_top", "log_loss")} if full_cal else None,
            "selective": {
                "calls": calls.height,
                "coverage": calls.height / known.height if known.height else None,
                "accuracy": _acc(corr),
                "sign_accuracy": _acc(calls["sign_correct"].cast(pl.Float64)),
                "balanced_accuracy": float(skm.balanced_accuracy_score(yt, pt)) if calls.height else None,
                "mcc": float(skm.matthews_corrcoef(yt, pt)) if calls.height > 1 else None,
                "share_up": float(np.mean(pt == 2)) if calls.height else None,
            },
            "rolling": {f"last_{w}": {"n": min(w, calls.height), "accuracy": _acc(corr.tail(w))}
                        for w in ROLLING},
            "daily": _period(calls, known, "%Y-%m-%d"),
            "weekly": _period(calls, known, "%G-W%V"),
            "monthly": _period(calls, known, "%Y-%m"),
            "paper": {
                "calls": calls.height,
                "round_trip_cost_bp": cost_bp,
                "mean_gross_bp": float(gross.mean()) if calls.height else None,
                "mean_net_bp": float(gross.mean() - cost_bp) if calls.height else None,
                "hit_rate_gross": float(np.mean(gross > 0)) if calls.height else None,
                "hit_rate_net": float(np.mean(gross > cost_bp)) if calls.height else None,
                "sum_net_bp": float((gross - cost_bp).sum()) if calls.height else None,
            },
        })  # fmt: skip
    return res
