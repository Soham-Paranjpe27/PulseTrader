"""Evaluation metrics, selective-prediction tables and the success gate.

Accuracy is never reported alone: every result carries balanced accuracy, MCC and coverage.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn import metrics as skm


def ece(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> float:
    """Expected calibration error for binary probabilities p = P(y=1)."""
    bins = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, bins) - 1, 0, n_bins - 1)
    total = 0.0
    for b in range(n_bins):
        m = idx == b
        if m.any():
            total += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(total)


def reliability_curve(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> list[dict[str, float]]:
    bins = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, bins) - 1, 0, n_bins - 1)
    out = []
    for b in range(n_bins):
        m = idx == b
        if m.any():
            out.append(
                {"bin": b, "n": int(m.sum()), "mean_p": float(p[m].mean()), "frac_pos": float(y[m].mean())}
            )
    return out


def binary_report(y: np.ndarray, p_up: np.ndarray, n_total: int | None = None) -> dict[str, Any]:
    """Metrics for a binary UP(1)/DOWN(0) task. n_total = eligible events (for coverage)."""
    y = np.asarray(y).astype(int)
    p_up = np.asarray(p_up, dtype=float)
    pred = (p_up >= 0.5).astype(int)
    n = len(y)
    both = len(np.unique(y)) == 2
    rep: dict[str, Any] = {
        "n_predictions": n,
        "coverage": float(n / n_total) if n_total else 1.0,
        "accuracy": float(skm.accuracy_score(y, pred)) if n else None,
        "balanced_accuracy": float(skm.balanced_accuracy_score(y, pred)) if n and both else None,
        "precision": float(skm.precision_score(y, pred, zero_division=0)) if n else None,
        "recall": float(skm.recall_score(y, pred, zero_division=0)) if n else None,
        "macro_f1": float(skm.f1_score(y, pred, average="macro", zero_division=0)) if n else None,
        "mcc": float(skm.matthews_corrcoef(y, pred)) if n and both else None,
        "roc_auc": float(skm.roc_auc_score(y, p_up)) if n and both else None,
        "pr_auc": float(skm.average_precision_score(y, p_up)) if n and both else None,
        "brier": float(skm.brier_score_loss(y, p_up)) if n else None,
        "ece": ece(y, p_up) if n else None,
        "confusion_matrix": skm.confusion_matrix(y, pred, labels=[0, 1]).tolist() if n else None,
        "positive_rate": float(y.mean()) if n else None,
    }
    rep["verdict"] = verdict(rep)
    return rep


def selective_table(
    y: np.ndarray, p_up: np.ndarray, thresholds=(0.5, 0.6, 0.7, 0.8, 0.9)
) -> list[dict[str, Any]]:
    """Abstain unless max(p, 1-p) >= threshold. Coverage is relative to all eligible events."""
    conf = np.maximum(p_up, 1 - p_up)
    rows = []
    for t in thresholds:
        m = conf >= t
        r = binary_report(y[m], p_up[m], n_total=len(y)) if m.any() else {"n_predictions": 0, "coverage": 0.0}
        r["threshold"] = t
        rows.append(r)
    return rows


def verdict(r: dict[str, Any]) -> str:
    acc, bal, mcc = r.get("accuracy"), r.get("balanced_accuracy"), r.get("mcc")
    if acc is None or bal is None or mcc is None:
        return "INSUFFICIENT_DATA"
    if acc >= 0.70 and (bal < 0.55 or mcc < 0.10):
        return "FAILED — MAJORITY/IMBALANCE BEHAVIOR"
    return "NOT VERIFIED"  # HIGH_ACCURACY_CANDIDATE is only granted by the full gate in eval/gate.py


def regression_report(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    nz = np.abs(y_true) > 1e-12
    return {
        "mae": float(skm.mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(skm.mean_squared_error(y_true, y_pred))),
        "mape": float(np.mean(np.abs((y_true[nz] - y_pred[nz]) / y_true[nz]))) if nz.any() else float("nan"),
        "r2": float(skm.r2_score(y_true, y_pred)),
        "directional_accuracy": float(np.mean(np.sign(y_true) == np.sign(y_pred))),
    }
