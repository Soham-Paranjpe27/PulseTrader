"""Metrics for the 3-class direction task (DOWN / NEUTRAL / UP) and its selective UP/DOWN view.

Class index order is fixed: 0 = DOWN, 1 = NEUTRAL, 2 = UP (label values -1, 0, 1 shifted by +1).
Every report carries accuracy together with balanced accuracy, MCC and coverage.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn import metrics as skm

CLASSES = ("DOWN", "NEUTRAL", "UP")
DOWN, NEUTRAL, UP = 0, 1, 2
SELECTIVE_THRESHOLDS = (0.40, 0.50, 0.60, 0.70, 0.80, 0.90)


def to_index(labels: np.ndarray) -> np.ndarray:
    """Label values -1/0/1 -> class index 0/1/2."""
    return (np.asarray(labels).astype(np.int64) + 1).astype(np.int64)


def _updown_auc(y: np.ndarray, proba: np.ndarray) -> float | None:
    """Diagnostic only: ranking quality of P(UP) - P(DOWN) on rows whose label moved.

    The row subset is defined by the realised label, so this is not a deployable accuracy; it
    separates "can the model tell up from down" from "can it tell moves from no-moves".
    """
    m = y != NEUTRAL
    if m.sum() == 0 or len(np.unique(y[m])) < 2:
        return None
    return float(skm.roc_auc_score(y[m] == UP, proba[m, UP] - proba[m, DOWN]))


def _clip_norm(proba: np.ndarray) -> np.ndarray:
    p = np.clip(proba, 1e-7, 1)
    return p / p.sum(axis=1, keepdims=True)


def top_class_ece(y: np.ndarray, proba: np.ndarray, n_bins: int = 10) -> float:
    """ECE of the predicted class's confidence."""
    conf = proba.max(axis=1)
    correct = (proba.argmax(axis=1) == y).astype(float)
    bins = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(conf, bins) - 1, 0, n_bins - 1)
    total = 0.0
    for b in range(n_bins):
        m = idx == b
        if m.any():
            total += m.mean() * abs(correct[m].mean() - conf[m].mean())
    return float(total)


def multiclass_report(y: np.ndarray, proba: np.ndarray, pred: np.ndarray | None = None) -> dict[str, Any]:
    """Full-coverage metrics. `pred` defaults to argmax(proba); baselines may pass their own."""
    y = np.asarray(y, dtype=np.int64)
    proba = np.asarray(proba, dtype=np.float64)
    pred = proba.argmax(axis=1) if pred is None else np.asarray(pred, dtype=np.int64)
    present = np.unique(y)
    onehot = np.eye(3)[y]
    rep: dict[str, Any] = {
        "n": int(len(y)),
        "coverage": 1.0,
        "accuracy": float(skm.accuracy_score(y, pred)),
        "balanced_accuracy": float(skm.balanced_accuracy_score(y, pred)),
        "precision_macro": float(skm.precision_score(y, pred, average="macro", zero_division=0)),
        "recall_macro": float(skm.recall_score(y, pred, average="macro", zero_division=0)),
        "macro_f1": float(skm.f1_score(y, pred, average="macro", zero_division=0)),
        "mcc": float(skm.matthews_corrcoef(y, pred)),
        "roc_auc_ovr": (
            float(skm.roc_auc_score(y, proba, multi_class="ovr", labels=[0, 1, 2]))
            if len(present) == 3
            else None
        ),
        "pr_auc_macro": float(
            np.mean([skm.average_precision_score(onehot[:, k], proba[:, k]) for k in present])
        ),
        "brier": float(np.mean(np.sum((proba - onehot) ** 2, axis=1))),
        "log_loss": float(skm.log_loss(y, _clip_norm(proba), labels=[0, 1, 2])),
        "ece_top": top_class_ece(y, proba),
        "updown_auc": _updown_auc(y, proba),
        "confusion_matrix": skm.confusion_matrix(y, pred, labels=[0, 1, 2]).tolist(),
        "class_distribution": {CLASSES[k]: float(np.mean(y == k)) for k in range(3)},
        "pred_distribution": {CLASSES[k]: float(np.mean(pred == k)) for k in range(3)},
    }
    rep["verdict"] = verdict(rep)
    return rep


def selective_direction_table(
    y: np.ndarray,
    proba: np.ndarray,
    fret: np.ndarray,
    thresholds: tuple[float, ...] = SELECTIVE_THRESHOLDS,
) -> list[dict[str, Any]]:
    """PREDICT UP / PREDICT DOWN / NO PREDICTION.

    Direction = UP if P(UP) >= P(DOWN) else DOWN; predict only when that probability >= threshold
    and it beats P(NEUTRAL). Coverage is relative to ALL evaluation rows. `accuracy` = predicted
    class equals the label (an actual NEUTRAL counts as wrong); `sign_accuracy` = predicted
    direction equals the sign of the realised return (a zero return counts as wrong).
    """
    y = np.asarray(y, dtype=np.int64)
    p_dir = np.maximum(proba[:, UP], proba[:, DOWN])
    direction = np.where(proba[:, UP] >= proba[:, DOWN], UP, DOWN)
    n_total = len(y)
    n_up, n_down = int(np.sum(y == UP)), int(np.sum(y == DOWN))
    rows = []
    for t in thresholds:
        m = (p_dir >= t) & (p_dir > proba[:, NEUTRAL])
        k = int(m.sum())
        row: dict[str, Any] = {
            "threshold": t,
            "n_predictions": k,
            "coverage": k / n_total if n_total else 0.0,
        }
        if k:
            yt, pt = y[m], direction[m]
            sign = np.sign(fret[m])
            row.update(
                {
                    "accuracy": float(np.mean(yt == pt)),
                    "sign_accuracy": float(np.mean(np.where(pt == UP, sign > 0, sign < 0))),
                    "balanced_accuracy": float(skm.balanced_accuracy_score(yt, pt)),
                    "mcc": float(skm.matthews_corrcoef(yt, pt)),
                    "precision_up": float(np.mean(yt[pt == UP] == UP)) if (pt == UP).any() else None,
                    "precision_down": float(np.mean(yt[pt == DOWN] == DOWN)) if (pt == DOWN).any() else None,
                    "recall_up": float(np.sum((pt == UP) & (yt == UP)) / n_up) if n_up else None,
                    "recall_down": float(np.sum((pt == DOWN) & (yt == DOWN)) / n_down) if n_down else None,
                    "share_up": float(np.mean(pt == UP)),
                }
            )
        rows.append(row)
    return rows


def verdict(r: dict[str, Any]) -> str:
    acc, bal, mcc = r["accuracy"], r["balanced_accuracy"], r["mcc"]
    if acc >= 0.70 and (bal < 0.55 or mcc < 0.10):
        return "FAILED — MAJORITY/IMBALANCE BEHAVIOR"
    return "NOT VERIFIED"
