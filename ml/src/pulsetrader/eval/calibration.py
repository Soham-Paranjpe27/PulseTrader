"""Probability calibration for the 3-class direction models (Phase 10).

Both calibrators are one-vs-rest: each class's probability is mapped on its own, then the three
outputs are renormalised to sum to one.
- Platt: logistic regression of the class indicator on logit(p_k).
- Isotonic: monotone step function of p_k (sklearn IsotonicRegression, clipped to [0, 1]).

Calibrators are fit on out-of-fold predictions only (never on the rows they are scored on).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

EPS = 1e-6


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return np.asarray(np.log(p / (1 - p)))


def _renorm(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, None)
    return np.asarray(p / p.sum(axis=1, keepdims=True))


@dataclass
class Platt:
    name: str = "platt"
    coef: list[tuple[float, float]] = field(default_factory=list)  # (slope, intercept) per class

    def fit(self, y: np.ndarray, proba: np.ndarray) -> Platt:
        from sklearn.linear_model import LogisticRegression

        self.coef = []
        for k in range(proba.shape[1]):
            lr = LogisticRegression(C=1e6, max_iter=1000)
            lr.fit(_logit(proba[:, k])[:, None], (y == k).astype(int))
            self.coef.append((float(lr.coef_[0, 0]), float(lr.intercept_[0])))
        return self

    def transform(self, proba: np.ndarray) -> np.ndarray:
        cols = [1 / (1 + np.exp(-(a * _logit(proba[:, k]) + b))) for k, (a, b) in enumerate(self.coef)]
        return _renorm(np.column_stack(cols))

    def to_json(self) -> dict[str, Any]:
        return {"method": self.name, "coef": self.coef}


@dataclass
class Isotonic:
    name: str = "isotonic"
    models: list[Any] = field(default_factory=list)

    def fit(self, y: np.ndarray, proba: np.ndarray) -> Isotonic:
        from sklearn.isotonic import IsotonicRegression

        self.models = [
            IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(
                proba[:, k], (y == k).astype(float)
            )
            for k in range(proba.shape[1])
        ]
        return self

    def transform(self, proba: np.ndarray) -> np.ndarray:
        return _renorm(np.column_stack([m.predict(proba[:, k]) for k, m in enumerate(self.models)]))

    def to_json(self) -> dict[str, Any]:
        return {
            "method": self.name,
            "thresholds": [
                {"x": m.X_thresholds_.tolist(), "y": m.y_thresholds_.tolist()} for m in self.models
            ],
        }


CALIBRATORS: dict[str, type[Platt] | type[Isotonic]] = {"platt": Platt, "isotonic": Isotonic}


def reliability_curve(
    y: np.ndarray, proba: np.ndarray, n_bins: int = 10, cls: int | None = None
) -> list[dict[str, float]]:
    """Bins of predicted probability vs observed frequency.

    cls=None: confidence of the predicted class vs accuracy. cls=k: P(class k) vs frequency of k."""
    if cls is None:
        conf = proba.max(axis=1)
        hit = (proba.argmax(axis=1) == y).astype(float)
    else:
        conf = proba[:, cls]
        hit = (y == cls).astype(float)
    edges = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(conf, edges) - 1, 0, n_bins - 1)
    out = []
    for b in range(n_bins):
        m = idx == b
        if m.any():
            out.append(
                {
                    "bin_low": float(edges[b]),
                    "bin_high": float(edges[b + 1]),
                    "n": int(m.sum()),
                    "mean_predicted": float(conf[m].mean()),
                    "observed": float(hit[m].mean()),
                }
            )
    return out


def classwise_ece(y: np.ndarray, proba: np.ndarray, n_bins: int = 10) -> float:
    """Mean over classes of the one-vs-rest ECE of P(class k)."""
    total = 0.0
    for k in range(proba.shape[1]):
        curve = reliability_curve(y, proba, n_bins, cls=k)
        n = sum(c["n"] for c in curve)
        total += sum(c["n"] / n * abs(c["observed"] - c["mean_predicted"]) for c in curve)
    return float(total / proba.shape[1])


def calibrator_from_json(d: dict[str, Any]) -> Any:
    """Rebuild a fitted calibrator's transform from its `to_json()` output (no sklearn needed)."""
    method = d.get("method")
    if method == "platt":
        return Platt(coef=[(float(a), float(b)) for a, b in d["coef"]])
    if method == "isotonic":
        return IsotonicTable([(np.asarray(t["x"]), np.asarray(t["y"])) for t in d["thresholds"]])
    if method == "raw":
        return None
    raise ValueError(f"unknown calibration method {method}")


@dataclass
class IsotonicTable:
    """Isotonic step functions stored as thresholds; identical to IsotonicRegression.predict with
    out_of_bounds='clip' (linear interpolation between thresholds, clipped at the ends)."""

    tables: list[tuple[np.ndarray, np.ndarray]]
    name: str = "isotonic"

    def transform(self, proba: np.ndarray) -> np.ndarray:
        cols = [np.interp(proba[:, k], x, y) for k, (x, y) in enumerate(self.tables)]
        return _renorm(np.column_stack(cols))
