"""Data and model drift (spec section 49): feature, prediction, accuracy, calibration and market regime
drift of a monitoring window against a reference. When degradation is detected the report says
MODEL_DRIFT_DETECTED; nothing here ever replaces or retrains a model (a human decides).

References come only from data the model did not see at fit time or that precedes the window:
- features: the training split of the research dataset (decile bins per feature, plus a null bin);
- predictions, accuracy and calibration: the model's walk-forward predictions on the folds before the
  validation period (out-of-sample, one fitted model per fold);
- market regime: the daily NIFTY trend x volatility regime mix over the training period.

Thresholds are calibrated on history, per window length. Market data is persistent: within one day,
week or month, slow series (VIX, index trend, volatility, the regime) sit in a narrow band, so even a
perfectly ordinary month has a large PSI against the multi-year reference. Fixed rules of thumb
(PSI > 0.25) would flag every window. So each statistic is computed for every day, week and month of
the reference period, and a window is
- WARN when it is more extreme than 95% of reference windows of the same length,
- DRIFT when it is more extreme than 99% of them (for MCC / accuracy: lower than the 5% / 1% quantile;
  for ECE: higher than the 95% / 99% quantile),
with floors of PSI 0.1 / 0.25 so that tiny, stable PSIs never alarm. PSI = sum((a - e) * ln(a / e)) over
bins, eps 1e-4. Window length is chosen by the number of trading days: 1 = day, 2-7 = week, else month.

Overall: MODEL_DRIFT_DETECTED when accuracy or calibration drifted, or when features and predictions both
drifted; WARN when any component is WARN/DRIFT; INSUFFICIENT_DATA when nothing could be measured; else OK.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from sklearn import metrics as skm

from pulsetrader.eval.multiclass import top_class_ece

EPS = 1e-4
PSI_WARN = 0.1
PSI_DRIFT = 0.25
REFERENCE_VERSION = "monitor-ref-v2"
REGIMES = [f"{t}/{v}" for t in ("up", "down") for v in ("low", "mid", "high")]
REGIME_FEATURES = ("vix_level", "nifty_vol_20", "nifty_sma_50_ratio", "nifty_adx_14")
PROBS = ("down", "neutral", "up")
KINDS = {"day": "%Y-%m-%d", "week": "%G-W%V", "month": "%Y-%m"}
MIN_WINDOW_ROWS = 300  # reference windows smaller than this are not used for thresholds


# --- binning and PSI ------------------------------------------------------------------------------
def decile_edges(x: np.ndarray) -> list[float]:
    """Unique interior deciles of the non-missing values (empty when none)."""
    v = x[np.isfinite(x)]
    if not len(v):
        return []
    return [float(e) for e in np.unique(np.quantile(v, np.linspace(0.1, 0.9, 9)))]


def bin_index(x: np.ndarray, edges: Sequence[float]) -> np.ndarray:
    """Bin per value: 0..len(edges) for values, len(edges) + 1 for missing ones."""
    x = np.asarray(x, dtype=np.float64)
    out = np.full(len(x), len(edges) + 1, dtype=np.int64)
    ok = np.isfinite(x)
    out[ok] = np.searchsorted(np.asarray(edges), x[ok], side="right")
    return out


def bin_fractions(x: np.ndarray, edges: Sequence[float]) -> list[float]:
    counts = np.bincount(bin_index(x, edges), minlength=len(edges) + 2).astype(np.float64)
    return [float(f) for f in counts / max(len(x), 1)]


def psi(expected: Sequence[float], actual: Sequence[float]) -> float:
    e = np.clip(np.asarray(expected, dtype=np.float64), EPS, None)
    a = np.clip(np.asarray(actual, dtype=np.float64), EPS, None)
    return float(np.sum((a - e) * np.log(a / e)))


def _group_psi(bins: np.ndarray, groups: np.ndarray, n_groups: int, ref: Sequence[float]) -> np.ndarray:
    """PSI of every group's bin distribution against `ref` (vectorised)."""
    b = len(ref)
    counts = np.bincount(groups * b + bins, minlength=n_groups * b).reshape(n_groups, b).astype(np.float64)
    frac = np.clip(counts / np.maximum(counts.sum(axis=1, keepdims=True), 1), EPS, None)
    e = np.clip(np.asarray(ref, dtype=np.float64), EPS, None)
    return np.sum((frac - e) * np.log(frac / e), axis=1)


def _groups(ts: pl.Series, fmt: str) -> tuple[np.ndarray, int, np.ndarray]:
    """Group id per row for a window format, the number of groups and the row count per group."""
    key = ts.dt.strftime(fmt) if ts.dtype != pl.Date else ts.cast(pl.Datetime).dt.strftime(fmt)
    codes: np.ndarray = (key.rank("dense") - 1).to_numpy().astype(np.int64)
    n = int(np.max(codes)) + 1 if len(codes) else 0
    return codes, n, np.bincount(codes, minlength=n)


def _q(v: np.ndarray, qs: Sequence[float]) -> list[float] | None:
    v = v[np.isfinite(v)]
    return [float(np.quantile(v, q)) for q in qs] if len(v) else None


def _mean(v: np.ndarray) -> float | None:
    v = v[np.isfinite(v)]
    return float(v.mean()) if len(v) else None


def window_kind(days: int) -> str:
    return "day" if days <= 1 else "week" if days <= 7 else "month"


# --- reference ------------------------------------------------------------------------------------
@dataclass
class Reference:
    """Everything a window is compared with; JSON-serialisable (`to_json` / `load`)."""

    model: str
    features: dict[str, dict[str, Any]]  # name -> {edges, fractions}
    importance: dict[str, float]  # normalised gain, sums to 1
    predictions: dict[str, dict[str, Any]]  # down/neutral/up -> {edges, fractions}
    pred_share: dict[str, float]  # argmax class shares
    folds: list[dict[str, Any]]  # per reference fold: n, accuracy, mcc, balanced_accuracy, ece_top
    regime_mix: dict[str, float]
    baselines: dict[str, dict[str, Any]]  # window kind -> calibrated thresholds
    meta: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return self.__dict__.copy()

    @classmethod
    def load(cls, path: Path) -> Reference:
        return cls(**json.loads(path.read_text()))


def regime_mix(regimes: pl.DataFrame) -> dict[str, float]:
    """Share of trading days per NIFTY trend/volatility regime (unknown days are ignored)."""
    r = regimes.drop_nulls(["nifty_trend", "nifty_vol"])
    if not r.height:
        return {k: 0.0 for k in REGIMES}
    keys = (r["nifty_trend"] + "/" + r["nifty_vol"]).to_list()
    return {k: keys.count(k) / len(keys) for k in REGIMES}


def fold_metrics(y: np.ndarray, proba: np.ndarray) -> dict[str, Any]:
    """y: class index (DOWN=0, NEUTRAL=1, UP=2); proba: raw probabilities (n, 3)."""
    pred = proba.argmax(axis=1)
    return {
        "n": int(len(y)),
        "accuracy": float(np.mean(pred == y)),
        "balanced_accuracy": float(skm.balanced_accuracy_score(y, pred)),
        "mcc": float(skm.matthews_corrcoef(y, pred)),
        "ece_top": top_class_ece(y, proba),
    }


def _feature_baseline(
    train: pl.DataFrame, feats: dict[str, dict[str, Any]], imp: dict[str, float], fmt: str, min_rows: int
) -> dict[str, Any]:
    groups, n, sizes = _groups(train["trade_date"], fmt)
    keep = sizes >= min_rows
    per: dict[str, list[float] | None] = {}
    weighted = np.zeros(n)
    for f, r in feats.items():
        x = train[f].cast(pl.Float64).fill_null(np.nan).to_numpy()
        v = _group_psi(bin_index(x, r["edges"]), groups, n, r["fractions"])
        per[f] = _q(v[keep], (0.95, 0.99))
        weighted += v * imp.get(f, 0.0)
    return {"windows": int(keep.sum()), "feature_psi": per, "weighted_psi": _q(weighted[keep], (0.95, 0.99))}


def _prediction_baseline(ref_preds: pl.DataFrame, preds: dict[str, Any], share: dict[str, float],
                         fmt: str, min_rows: int) -> dict[str, Any]:  # fmt: skip
    groups, n, sizes = _groups(ref_preds["ts"], fmt)
    keep = sizes >= min_rows
    proba = ref_preds.select("p_down", "p_neutral", "p_up").to_numpy().astype(np.float64)
    worst = np.zeros(n)
    for k, name in enumerate(PROBS):
        r = preds[name]
        worst = np.maximum(worst, _group_psi(bin_index(proba[:, k], r["edges"]), groups, n, r["fractions"]))
    worst = np.maximum(worst, _group_psi(proba.argmax(axis=1), groups, n, list(share.values())))
    y = ref_preds["y"].to_numpy()
    metrics = [fold_metrics(y[groups == g], proba[groups == g]) for g in np.flatnonzero(keep)]

    def col(key: str) -> np.ndarray:
        return np.array([m[key] for m in metrics], dtype=np.float64)

    return {
        "windows": int(keep.sum()),
        "prediction_psi": _q(worst[keep], (0.95, 0.99)),
        "mcc": {"mean": _mean(col("mcc")), "low": _q(col("mcc"), (0.05, 0.01))},
        "accuracy": {"mean": _mean(col("accuracy")), "low": _q(col("accuracy"), (0.05, 0.01))},
        "ece_top": {"mean": _mean(col("ece_top")), "high": _q(col("ece_top"), (0.95, 0.99))},
    }


def _regime_baseline(regimes: pl.DataFrame, mix: dict[str, float], fmt: str) -> dict[str, Any]:
    r = regimes.drop_nulls(["nifty_trend", "nifty_vol"])
    if not r.height:
        return {"windows": 0, "regime_psi": None}
    groups, n, _ = _groups(r["trade_date"], fmt)
    bins = np.array(
        [REGIMES.index(f"{t}/{v}") for t, v in zip(r["nifty_trend"], r["nifty_vol"], strict=True)]
    )
    v = _group_psi(bins, groups, n, [mix[k] for k in REGIMES])
    return {"windows": n, "regime_psi": _q(v, (0.95, 0.99))}


def build_reference(
    model: str,
    train_features: pl.DataFrame,
    feature_names: list[str],
    importance: dict[str, float],
    ref_predictions: pl.DataFrame,
    train_regimes: pl.DataFrame,
    meta: dict[str, Any],
    min_window_rows: int = MIN_WINDOW_ROWS,
) -> Reference:
    """`train_features`: trade_date + features; `ref_predictions`: ts, fold, y (class index), p_down,
    p_neutral, p_up (out-of-sample folds only); `train_regimes`: trade_date, nifty_trend, nifty_vol."""
    feats = {}
    for f in feature_names:
        x = train_features[f].cast(pl.Float64).fill_null(np.nan).to_numpy()
        edges = decile_edges(x)
        feats[f] = {"edges": edges, "fractions": bin_fractions(x, edges)}
    total = sum(max(importance.get(f, 0.0), 0.0) for f in feature_names) or 1.0
    imp = {f: max(importance.get(f, 0.0), 0.0) / total for f in feature_names}
    proba = ref_predictions.select("p_down", "p_neutral", "p_up").to_numpy().astype(np.float64)
    preds = {}
    for k, name in enumerate(PROBS):
        edges = decile_edges(proba[:, k])
        preds[name] = {"edges": edges, "fractions": bin_fractions(proba[:, k], edges)}
    am = proba.argmax(axis=1)
    share = {name.upper(): float(np.mean(am == k)) for k, name in enumerate(PROBS)}
    folds = []
    for fold in sorted(ref_predictions["fold"].unique().to_list()):
        g = ref_predictions.filter(pl.col("fold") == fold)
        rep = fold_metrics(g["y"].to_numpy(), g.select("p_down", "p_neutral", "p_up").to_numpy())
        folds.append({"fold": fold, "start": str(g["ts"].min()), "end": str(g["ts"].max()), **rep})
    mix = regime_mix(train_regimes)
    baselines = {
        kind: {
            **_feature_baseline(train_features, feats, imp, fmt, min_window_rows),
            **{
                f"pred_{k}": v
                for k, v in _prediction_baseline(ref_predictions, preds, share, fmt, min_window_rows).items()
            },
            **_regime_baseline(train_regimes, mix, fmt),
        }
        for kind, fmt in KINDS.items()
    }
    return Reference(
        model=model, features=feats, importance=imp, predictions=preds, pred_share=share, folds=folds,
        regime_mix=mix, baselines=baselines,
        meta={"reference_version": REFERENCE_VERSION, "train_rows": train_features.height,
              "prediction_rows": ref_predictions.height, "min_window_rows": min_window_rows, **meta},
    )  # fmt: skip


# --- window report --------------------------------------------------------------------------------
_ORDER = {"INSUFFICIENT_DATA": 0, "OK": 1, "WARN": 2, "DRIFT": 3}


def _worse(a: str, b: str) -> str:
    return a if _ORDER[a] >= _ORDER[b] else b


def _high(v: float, q: list[float] | None, floor: tuple[float, float]) -> tuple[str, list[float]]:
    """Level of a 'higher is worse' statistic against calibrated quantiles with floors."""
    warn, drift = (max(floor[0], q[0]), max(floor[1], q[1])) if q else floor
    return ("DRIFT" if v > drift else "WARN" if v > warn else "OK"), [warn, drift]


def feature_drift(ref: Reference, window: pl.DataFrame, kind: str, min_rows: int = 500) -> dict[str, Any]:
    if window.height < min_rows:
        return {"status": "INSUFFICIENT_DATA", "rows": window.height, "min_rows": min_rows}
    base = ref.baselines[kind]
    per: list[dict[str, Any]] = []
    weighted = 0.0
    for f, r in ref.features.items():
        if f not in window.columns:
            continue
        x = window[f].cast(pl.Float64).fill_null(np.nan).to_numpy()
        v = psi(r["fractions"], bin_fractions(x, r["edges"]))
        level, thr = _high(v, base["feature_psi"].get(f), (PSI_WARN, PSI_DRIFT))
        imp = ref.importance.get(f, 0.0)
        per.append({"feature": f, "psi": v, "level": level, "thresholds": thr, "importance": imp})
        weighted += v * imp
    level, thr = _high(weighted, base["weighted_psi"], (PSI_WARN, PSI_DRIFT))
    per.sort(key=lambda p: (-_ORDER[p["level"]], -p["psi"]))
    drifted = [p for p in per if p["level"] == "DRIFT"]
    return {
        "status": level,
        "rows": window.height,
        "window_kind": kind,
        "features": len(per),
        "drifted": len(drifted),
        "importance_weighted_psi": weighted,
        "thresholds": thr,
        "top": per[:10],
        "regime_features": [p for p in per if p["feature"] in REGIME_FEATURES],
    }


def prediction_drift(ref: Reference, proba: np.ndarray, kind: str, min_rows: int = 500) -> dict[str, Any]:
    if len(proba) < min_rows:
        return {"status": "INSUFFICIENT_DATA", "rows": int(len(proba)), "min_rows": min_rows}
    per = {}
    for k, name in enumerate(PROBS):
        r = ref.predictions[name]
        per[name] = psi(r["fractions"], bin_fractions(proba[:, k], r["edges"]))
    am = proba.argmax(axis=1)
    share = {name.upper(): float(np.mean(am == k)) for k, name in enumerate(PROBS)}
    share_psi = psi(list(ref.pred_share.values()), [share[k] for k in ref.pred_share])
    worst = max([*per.values(), share_psi])
    level, thr = _high(worst, ref.baselines[kind]["pred_prediction_psi"], (PSI_WARN, PSI_DRIFT))
    return {"status": level, "rows": int(len(proba)), "window_kind": kind, "max_psi": worst,
            "thresholds": thr, "probability_psi": per, "argmax_share": share,
            "reference_argmax_share": ref.pred_share, "argmax_share_psi": share_psi}  # fmt: skip


def accuracy_drift(
    ref: Reference, y: np.ndarray, proba: np.ndarray, kind: str, min_outcomes: int = 1000
) -> dict[str, Any]:
    if len(y) < min_outcomes:
        return {"status": "INSUFFICIENT_DATA", "outcomes": int(len(y)), "min_outcomes": min_outcomes}
    win = fold_metrics(y, proba)
    base = ref.baselines[kind]
    out: dict[str, Any] = {"outcomes": int(len(y)), "window_kind": kind, "window": win, "checks": {}}
    worst = "INSUFFICIENT_DATA"
    for key in ("mcc", "accuracy"):
        b = base[f"pred_{key}"]
        if not b["low"]:  # no reference window of this length: nothing to compare with
            out["checks"][key] = {"reference_mean": None, "level": "INSUFFICIENT_DATA"}
            continue
        warn, drift = b["low"]
        level = "DRIFT" if win[key] < drift else "WARN" if win[key] < warn else "OK"
        out["checks"][key] = {"reference_mean": b["mean"], "warn_below": warn, "drift_below": drift,
                              "level": level}  # fmt: skip
        worst = _worse(worst, level)
    measured = any(c["level"] != "INSUFFICIENT_DATA" for c in out["checks"].values())
    out["status"] = worst if measured else "INSUFFICIENT_DATA"
    return out


def calibration_drift(
    ref: Reference, y: np.ndarray, proba: np.ndarray, kind: str, min_outcomes: int = 1000
) -> dict[str, Any]:
    if len(y) < min_outcomes:
        return {"status": "INSUFFICIENT_DATA", "outcomes": int(len(y)), "min_outcomes": min_outcomes}
    ece = top_class_ece(y, proba)
    b = ref.baselines[kind]["pred_ece_top"]
    if not b["high"]:
        return {"status": "INSUFFICIENT_DATA", "outcomes": int(len(y)), "window_kind": kind, "ece_top": ece,
                "reason": f"no reference {kind} windows"}  # fmt: skip
    level, thr = _high(ece, b["high"], (0.0, 0.0))
    return {"status": level, "outcomes": int(len(y)), "window_kind": kind, "ece_top": ece,
            "reference_mean": b["mean"], "thresholds": thr}  # fmt: skip


def regime_drift(ref: Reference, window_regimes: pl.DataFrame, kind: str) -> dict[str, Any]:
    days = window_regimes.drop_nulls(["nifty_trend", "nifty_vol"]).height
    if not days:
        return {"status": "INSUFFICIENT_DATA", "days": 0}
    mix = regime_mix(window_regimes)
    v = psi([ref.regime_mix[k] for k in REGIMES], [mix[k] for k in REGIMES])
    level, thr = _high(v, ref.baselines[kind]["regime_psi"], (PSI_WARN, PSI_DRIFT))
    return {"status": level, "days": days, "window_kind": kind, "psi": v, "thresholds": thr, "mix": mix,
            "reference_mix": ref.regime_mix}  # fmt: skip


def drift_report(
    ref: Reference,
    features: pl.DataFrame,
    proba: np.ndarray,
    y: np.ndarray,
    y_proba: np.ndarray,
    regimes: pl.DataFrame,
    window: dict[str, Any],
    days: int,
    min_rows: int = 500,
    min_outcomes: int = 1000,
) -> dict[str, Any]:
    """One monitoring window over `days` trading days. `proba`: raw probabilities of every prediction in
    the window; `y`, `y_proba`: realised class index and raw probabilities where the outcome is known."""
    kind = window_kind(days)
    comp = {
        "feature": feature_drift(ref, features, kind, min_rows),
        "prediction": prediction_drift(ref, proba, kind, min_rows),
        "accuracy": accuracy_drift(ref, y, y_proba, kind, min_outcomes),
        "calibration": calibration_drift(ref, y, y_proba, kind, min_outcomes),
        "regime": regime_drift(ref, regimes, kind),
    }
    levels = {k: v["status"] for k, v in comp.items()}
    reasons = [f"{k} {v}" for k, v in levels.items() if v in ("WARN", "DRIFT")]
    if (
        levels["accuracy"] == "DRIFT"
        or levels["calibration"] == "DRIFT"
        or (levels["feature"] == "DRIFT" and levels["prediction"] == "DRIFT")
    ):
        status = "MODEL_DRIFT_DETECTED"
    elif reasons:
        status = "WARN"
    elif all(v == "INSUFFICIENT_DATA" for v in levels.values()):
        status = "INSUFFICIENT_DATA"
    else:
        status = "OK"
    return {
        "model": ref.model,
        "status": status,
        "reasons": reasons,
        "components": comp,
        "window": {**window, "days": days, "kind": window.get("kind", kind), "threshold_kind": kind},
        "action": "none: the model is never replaced automatically; review before any change",
        "reference": ref.meta,
    }


def window_bounds(ts: pl.Series) -> dict[str, Any]:
    if not ts.len():
        return {"start": None, "end": None}
    return {"start": str(ts.min()), "end": str(ts.max())}


def trading_days(ts: pl.Series) -> list[date]:
    return sorted(set(ts.dt.date().to_list()))
