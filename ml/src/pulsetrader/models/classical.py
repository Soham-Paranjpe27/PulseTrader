"""Baselines and classical models for the 3-class direction task (Phase 7).

All models expose `fit(X, y, X_es, y_es)` and `predict_proba(X) -> (n, 3)` in class order
DOWN / NEUTRAL / UP. X_es/y_es is an inner early-stopping set cut from the END of the training
period (never validation or test), used only by boosted trees.

Rule-based baselines (momentum, always-up, no-change) do not learn from features; they read
the raw columns they need from the evaluation frame via `predict_frame`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from pulsetrader.eval.multiclass import DOWN, NEUTRAL, UP

SEED = 20261017


class Model(Protocol):
    name: str
    params: dict[str, Any]

    def fit(self, X: np.ndarray, y: np.ndarray, X_es: np.ndarray, y_es: np.ndarray) -> None: ...

    def predict_proba(self, X: np.ndarray) -> np.ndarray: ...

    def importance(self, names: list[str]) -> dict[str, float]: ...


def _priors(y: np.ndarray) -> np.ndarray:
    return np.bincount(y, minlength=3).astype(float) / max(len(y), 1)


@dataclass
class Majority:
    name: str = "majority"
    params: dict[str, Any] = field(default_factory=dict)
    prior: np.ndarray = field(default_factory=lambda: np.full(3, 1 / 3))

    def fit(self, X: np.ndarray, y: np.ndarray, X_es: np.ndarray, y_es: np.ndarray) -> None:
        self.prior = _priors(y)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        p = np.zeros((len(X), 3))
        p[:, int(np.argmax(self.prior))] = 1.0
        return p

    def importance(self, names: list[str]) -> dict[str, float]:
        return {}


@dataclass
class StratifiedRandom:
    """Samples a class from the training prior; probabilities = the prior."""

    name: str = "random"
    params: dict[str, Any] = field(default_factory=lambda: {"seed": SEED})
    prior: np.ndarray = field(default_factory=lambda: np.full(3, 1 / 3))

    def fit(self, X: np.ndarray, y: np.ndarray, X_es: np.ndarray, y_es: np.ndarray) -> None:
        self.prior = _priors(y)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return np.tile(self.prior, (len(X), 1))

    def predict(self, n: int) -> np.ndarray:
        rng = np.random.default_rng(self.params["seed"])
        return rng.choice(3, size=n, p=self.prior)

    def importance(self, names: list[str]) -> dict[str, float]:
        return {}


def rule_proba(cls: np.ndarray) -> np.ndarray:
    """One-hot probabilities for a rule-based class prediction."""
    p = np.zeros((len(cls), 3))
    p[np.arange(len(cls)), cls] = 1.0
    return p


def momentum_classes(past_return: np.ndarray, threshold: float) -> np.ndarray:
    """Momentum rule: the next move repeats the past move over the same horizon (same threshold)."""
    r = np.nan_to_num(past_return, nan=0.0)
    return np.where(r > threshold, UP, np.where(r < -threshold, DOWN, NEUTRAL))


@dataclass
class Logistic:
    name: str = "logistic"
    params: dict[str, Any] = field(default_factory=lambda: {"C": 1.0, "max_iter": 300})
    model: Any = None

    def fit(self, X: np.ndarray, y: np.ndarray, X_es: np.ndarray, y_es: np.ndarray) -> None:
        from sklearn.linear_model import LogisticRegression

        self.model = LogisticRegression(**self.params, random_state=SEED)
        self.model.fit(X, y)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(self.model.predict_proba(X))

    def importance(self, names: list[str]) -> dict[str, float]:
        # inputs are standardised, so |coef| is comparable across features
        w = np.abs(self.model.coef_).sum(axis=0)
        return dict(zip(names, map(float, w), strict=True))


@dataclass
class RandomForest:
    name: str = "random_forest"
    params: dict[str, Any] = field(
        default_factory=lambda: {
            "n_estimators": 100,
            "max_depth": 14,
            "min_samples_leaf": 500,
            "max_features": "sqrt",
            "max_samples": 0.3,
            "n_jobs": -1,
        }
    )
    model: Any = None

    def fit(self, X: np.ndarray, y: np.ndarray, X_es: np.ndarray, y_es: np.ndarray) -> None:
        from sklearn.ensemble import RandomForestClassifier

        self.model = RandomForestClassifier(**self.params, random_state=SEED)
        self.model.fit(X, y)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(self.model.predict_proba(X))

    def importance(self, names: list[str]) -> dict[str, float]:
        return dict(zip(names, map(float, self.model.feature_importances_), strict=True))


@dataclass
class LightGBM:
    name: str = "lightgbm"
    params: dict[str, Any] = field(
        default_factory=lambda: {
            "objective": "multiclass",
            "num_class": 3,
            "learning_rate": 0.05,
            "num_leaves": 63,
            "min_data_in_leaf": 1000,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 1,
            "lambda_l2": 1.0,
            "num_threads": 4,
            "verbose": -1,
            "max_rounds": 1000,
            "early_stopping": 50,
        }
    )
    model: Any = None
    best_iteration: int = 0

    def fit(self, X: np.ndarray, y: np.ndarray, X_es: np.ndarray, y_es: np.ndarray) -> None:
        import lightgbm as lgb

        p = {k: v for k, v in self.params.items() if k not in ("max_rounds", "early_stopping")}
        p["seed"] = SEED
        dtrain = lgb.Dataset(X, y, free_raw_data=True)
        des = lgb.Dataset(X_es, y_es, reference=dtrain)
        self.model = lgb.train(
            p,
            dtrain,
            num_boost_round=self.params["max_rounds"],
            valid_sets=[des],
            callbacks=[lgb.early_stopping(self.params["early_stopping"], verbose=False)],
        )
        self.best_iteration = int(self.model.best_iteration)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(self.model.predict(X, num_iteration=self.best_iteration))

    def importance(self, names: list[str]) -> dict[str, float]:
        g = self.model.feature_importance(importance_type="gain")
        return dict(zip(names, map(float, g), strict=True))


@dataclass
class XGBoost:
    name: str = "xgboost"
    params: dict[str, Any] = field(
        default_factory=lambda: {
            "objective": "multi:softprob",
            "num_class": 3,
            "eta": 0.05,
            "max_depth": 6,
            "min_child_weight": 100,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "lambda": 1.0,
            "tree_method": "hist",
            "nthread": 4,
            "eval_metric": "mlogloss",
            "max_rounds": 1000,
            "early_stopping": 50,
        }
    )
    model: Any = None
    best_iteration: int = 0

    def fit(self, X: np.ndarray, y: np.ndarray, X_es: np.ndarray, y_es: np.ndarray) -> None:
        import xgboost as xgb

        p = {k: v for k, v in self.params.items() if k not in ("max_rounds", "early_stopping")}
        p["seed"] = SEED
        dtrain = xgb.DMatrix(X, label=y)
        des = xgb.DMatrix(X_es, label=y_es)
        self.model = xgb.train(
            p,
            dtrain,
            num_boost_round=self.params["max_rounds"],
            evals=[(des, "early_stop")],
            early_stopping_rounds=self.params["early_stopping"],
            verbose_eval=False,
        )
        self.best_iteration = int(self.model.best_iteration)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        import xgboost as xgb

        return np.asarray(self.model.predict(xgb.DMatrix(X), iteration_range=(0, self.best_iteration + 1)))

    def importance(self, names: list[str]) -> dict[str, float]:
        g = self.model.get_score(importance_type="gain")
        return {n: float(g.get(f"f{i}", 0.0)) for i, n in enumerate(names)}


LEARNED: dict[str, type[Model]] = {
    "majority": Majority,
    "random": StratifiedRandom,
    "logistic": Logistic,
    "random_forest": RandomForest,
    "xgboost": XGBoost,
    "lightgbm": LightGBM,
}
RULES = ("no_change", "always_up", "momentum")
