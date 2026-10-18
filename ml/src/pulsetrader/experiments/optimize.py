"""Phase 9: walk-forward evaluation, Optuna tuning, feature selection, threshold optimisation, ensembles.

Everything here uses the development period only (train + validation). The test split is filtered
out in the scan and never read.

Walk-forward folds (see `make_folds`): the first `min_train_frac` of training dates is always
training data; the rest of the training period is cut into `n_pre` chronological evaluation windows,
and the validation period is the last window. Each window is scored by a model trained only on
earlier rows: purged (training labels end before the window starts) and embargoed (the first
`embargo_minutes` of the window are not scored). "expanding" trains on everything before the window,
"rolling" on the last `rolling_days` before it.

Selection discipline:
- Optuna scores trials on the last two pre-validation windows only, so validation stays a clean
  check of the tuned parameters.
- Feature selection is decided on the last pre-validation window (fit on the rows before it).
- Ensemble weights, the stacked meta-model and probability thresholds are fit on out-of-fold
  predictions of the pre-validation windows and then applied unchanged to validation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from pulsetrader.config import FEATURE_VERSION, LABEL_VERSION
from pulsetrader.eval.multiclass import (
    CLASSES,
    DOWN,
    NEUTRAL,
    UP,
    multiclass_report,
    selective_direction_table,
    to_index,
)
from pulsetrader.experiments.classical import MOMENTUM_COL, _new_dir, inner_split
from pulsetrader.features.preprocess import Preprocessor
from pulsetrader.labels.labels import label_name
from pulsetrader.models.classical import LEARNED, SEED, momentum_classes, rule_proba

log = logging.getLogger(__name__)

RUNNER_VERSION = "optimize-v1"
HEADLINE = ("accuracy", "balanced_accuracy", "macro_f1", "mcc", "roc_auc_ovr", "brier", "ece_top")
GROUPS = ("OHLCV", "TECHNICAL", "VOLUME", "INTRADAY", "MARKET", "RELATIVE")


# ---------------------------------------------------------------------------------------------
# feature groups (names are produced by features/engine.py; tests check this agrees with it)


def feature_group(name: str) -> str:
    if name.startswith(("nifty_", "banknifty_", "vix_")) or name == "breadth_15":
        return "MARKET"
    if name.startswith(("rel_ret_", "rs_rank_")) or name in ("volume_rank", "volatility_rank"):
        return "RELATIVE"
    if name in ("volume_chg", "rel_volume_20", "volume_z_20", "pv_corr_20", "vwap_dist"):
        return "VOLUME"
    if name.startswith(("min_", "first_", "last_", "or_")) or name in (
        "ret_since_open",
        "intraday_range",
        "opening_gap",
    ):
        return "INTRADAY"
    if name in ("log_ret_1", "gap", "body", "upper_wick", "lower_wick", "range", "close_pos") or (
        name.startswith("ret_") and name[4:].isdigit()
    ):
        return "OHLCV"
    return "TECHNICAL"


# ---------------------------------------------------------------------------------------------
# data and folds


@dataclass(frozen=True)
class Fold:
    name: str
    start: date  # first evaluation trade date (inclusive)
    end: date  # last evaluation trade date (inclusive)
    is_validation: bool = False


def make_folds(
    train_dates: list[date], validation: tuple[date, date], n_pre: int = 4, min_train_frac: float = 0.4
) -> list[Fold]:
    dates = sorted(train_dates)
    first = int(len(dates) * min_train_frac)
    cuts = np.linspace(first, len(dates), n_pre + 1).astype(int)
    folds = [
        Fold(f"F{k + 1}", dates[cuts[k]], dates[cuts[k + 1] - 1])
        for k in range(n_pre)
        if cuts[k + 1] > cuts[k]
    ]
    return [*folds, Fold(f"F{len(folds) + 1}", validation[0], validation[1], is_validation=True)]


@dataclass
class DevData:
    ds_dir: Path
    horizon: int
    thresholds: tuple[float, ...]
    features: list[str]
    df: pl.DataFrame  # train + validation rows with a label, sorted by (ts, symbol)
    manifest: dict[str, Any]
    folds: list[Fold]
    embargo_minutes: int = 60
    train_every: int = 15
    _cache: dict[tuple[Any, ...], FoldData] = field(default_factory=dict, repr=False)

    @property
    def periods(self) -> dict[str, Any]:
        return {p["name"]: p for p in self.manifest["periods"]}

    def info(self) -> dict[str, Any]:
        p = self.periods
        return {
            "dataset_id": self.manifest["dataset_id"],
            "dataset": self.ds_dir.name,
            "feature_version": FEATURE_VERSION,
            "label_version": LABEL_VERSION,
            "train_period": p["train"],
            "validation_period": p["validation"],
            "test_period": {**p["test"], "used": False},
            "folds": [asdict(f) for f in self.folds],
            "embargo_minutes": self.embargo_minutes,
            "train_every": self.train_every,
        }

    def fold_data(
        self,
        fold: Fold,
        scheme: str = "expanding",
        features: tuple[str, ...] | None = None,
        rolling_days: int = 365,
    ) -> FoldData:
        feats = tuple(features or self.features)
        key = (fold.name, scheme, feats, rolling_days)
        if key not in self._cache:
            if len(self._cache) >= 2:  # bound memory: keep the two most recent folds
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = build_fold(self, fold, scheme, list(feats), rolling_days)
        return self._cache[key]


def load_dev(
    data_root: Path,
    horizon: int,
    thresholds: tuple[float, ...],
    dataset: str = "core100_s5",
    n_pre: int = 4,
    min_train_frac: float = 0.4,
    embargo_minutes: int = 60,
    train_every: int = 15,
) -> DevData:
    ds_dir = data_root / "datasets" / dataset
    manifest = json.loads((ds_dir / "dataset_manifest.json").read_text())
    features = json.loads((ds_dir / "features.json").read_text())["features"]
    labels = [label_name(horizon, t) for t in thresholds]
    h = horizon
    cols = list(
        dict.fromkeys(
            ["symbol", "ts", "trade_date", "split", "min_since_open", f"fret_{h}", f"label_end_ts_{h}"]
            + [MOMENTUM_COL[h], *labels, *features]
        )
    )
    df = (
        pl.scan_parquet(ds_dir / "part-*.parquet")
        .filter(pl.col("split").is_in(["train", "validation"]) & pl.col(f"fret_{h}").is_not_null())
        .select(cols)
        .collect()
        .sort("ts", "symbol")
    )
    periods = {p["name"]: p for p in manifest["periods"]}
    train_dates = df.filter(pl.col("split") == "train")["trade_date"].unique().to_list()
    val = (
        date.fromisoformat(periods["validation"]["start"]),
        date.fromisoformat(periods["validation"]["end"]),
    )
    folds = make_folds(train_dates, val, n_pre, min_train_frac)
    return DevData(ds_dir, h, thresholds, features, df, manifest, folds, embargo_minutes, train_every)


@dataclass
class FoldData:
    fold: Fold
    scheme: str
    features: list[str]
    fit: pl.DataFrame
    es: pl.DataFrame
    ev: pl.DataFrame
    X_fit: np.ndarray
    X_es: np.ndarray
    X_ev: np.ndarray
    preprocessor: Preprocessor


def build_fold(dev: DevData, fold: Fold, scheme: str, features: list[str], rolling_days: int) -> FoldData:
    h, df = dev.horizon, dev.df
    in_window = (pl.col("trade_date") >= fold.start) & (pl.col("trade_date") <= fold.end)
    window_start = df.filter(in_window)["ts"].min()
    assert isinstance(window_start, datetime), f"empty fold {fold}"
    tr_filter = (
        (pl.col("split") == "train")
        & (pl.col("min_since_open") % dev.train_every == 0)
        & (pl.col("trade_date") < fold.start)
        & (pl.col(f"label_end_ts_{h}") <= window_start)  # purge: training labels end before the window
    )
    if scheme == "rolling":
        tr_filter = tr_filter & (pl.col("trade_date") >= fold.start - timedelta(days=rolling_days))
    elif scheme != "expanding":
        raise ValueError(f"unknown scheme {scheme}")
    tr = df.filter(tr_filter)
    fit_m, es_m = inner_split(tr, h, 0.10, dev.embargo_minutes)
    fit, es = tr.filter(fit_m), tr.filter(es_m)
    if fit.height == 0 or es.height == 0:
        raise ValueError(f"fold {fold.name}: not enough training dates before {fold.start}")
    if fold.is_validation:
        ev = df.filter(pl.col("split") == "validation")  # dataset split is already purged + embargoed
    else:
        ev = df.filter(in_window & (pl.col("ts") >= window_start + timedelta(minutes=dev.embargo_minutes)))
    pp = Preprocessor.fit(fit, features, FEATURE_VERSION)
    X_fit, X_es, X_ev = pp.transform(fit), pp.transform(es), pp.transform(ev)
    keep = [c for c in df.columns if c not in dev.features or c == MOMENTUM_COL[h]]  # drop feature copies
    return FoldData(
        fold, scheme, features, fit.select(keep), es.select(keep), ev.select(keep), X_fit, X_es, X_ev, pp
    )


# ---------------------------------------------------------------------------------------------
# walk-forward


def fit_predict(
    fd: FoldData, label: str, model_name: str, params: dict[str, Any] | None = None
) -> tuple[Any, np.ndarray]:
    model = LEARNED[model_name]()
    model.params.update(params or {})
    model.fit(fd.X_fit, to_index(fd.fit[label].to_numpy()), fd.X_es, to_index(fd.es[label].to_numpy()))
    return model, model.predict_proba(fd.X_ev)


def summarize(per_fold: list[dict[str, Any]], keys: tuple[str, ...] = HEADLINE) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in keys:
        v = np.array([f[k] for f in per_fold if f.get(k) is not None], dtype=float)
        if len(v):
            out[k] = {
                "mean": float(v.mean()),
                "median": float(np.median(v)),
                "std": float(v.std(ddof=1)) if len(v) > 1 else 0.0,
                "min": float(v.min()),
                "max": float(v.max()),
            }
    return out


def _fold_report(fd: FoldData, label: str, proba: np.ndarray, h: int, thr: float) -> dict[str, Any]:
    y = to_index(fd.ev[label].to_numpy())
    fret = fd.ev[f"fret_{h}"].to_numpy().astype(np.float64)
    rep = multiclass_report(y, proba)
    rep["selective"] = selective_direction_table(y, proba, fret)
    y_fit = to_index(fd.fit[label].to_numpy())
    major = int(np.argmax(np.bincount(y_fit, minlength=3)))
    mom = multiclass_report(
        y, rule_proba(momentum_classes(fd.ev[MOMENTUM_COL[h]].to_numpy().astype(float), thr))
    )
    rep["baselines"] = {
        "majority_accuracy": float(np.mean(y == major)),
        "momentum_mcc": mom["mcc"],
        "momentum_accuracy": mom["accuracy"],
    }
    rep["fold"] = {
        **asdict(fd.fold),
        "scheme": fd.scheme,
        "fit_rows": fd.fit.height,
        "es_rows": fd.es.height,
        "eval_rows": fd.ev.height,
        "fit_period": [str(fd.fit["trade_date"].min()), str(fd.fit["trade_date"].max())],
    }
    return rep


def walk_forward(
    dev: DevData,
    out_root: Path,
    label: str,
    model_name: str = "lightgbm",
    scheme: str = "expanding",
    params: dict[str, Any] | None = None,
    features: list[str] | None = None,
    tag: str = "default",
    folds: list[Fold] | None = None,
) -> dict[str, Any]:
    """Train/score every fold; one experiment folder with per-fold metrics and OOF predictions."""
    h = dev.horizon
    thr = next(t for t in dev.thresholds if label_name(h, t) == label)
    per_fold, preds, importance = [], [], {}
    pp_last: Preprocessor | None = None
    t0 = time.time()
    for fold in folds or dev.folds:
        t1 = time.time()
        fd = dev.fold_data(fold, scheme, tuple(features) if features else None)
        model, proba = fit_predict(fd, label, model_name, params)
        rep = _fold_report(fd, label, proba, h, thr)
        rep["best_iteration"] = getattr(model, "best_iteration", None)
        rep["seconds"] = round(time.time() - t1, 1)
        per_fold.append(rep)
        preds.append(
            fd.ev.select(
                "symbol", "ts", pl.col(label).alias("y_raw"), pl.col(f"fret_{h}").alias("fret")
            ).with_columns(
                pl.lit(fold.name).alias("fold"),
                *[pl.Series(f"p_{c.lower()}", proba[:, k], dtype=pl.Float32) for k, c in enumerate(CLASSES)],
            )
        )
        importance = dict(sorted(model.importance(fd.features).items(), key=lambda kv: -kv[1]))
        pp_last = fd.preprocessor
        log.info(
            "%s %s %s %s %s acc=%.4f bal=%.4f mcc=%.4f (%.0fs)",
            label, model_name, scheme, tag, fold.name, rep["accuracy"], rep["balanced_accuracy"], rep["mcc"],
            rep["seconds"],
        )  # fmt: skip
    pre = [r for r in per_fold if not r["fold"]["is_validation"]]
    result = {
        "per_fold": per_fold,
        "summary_all": summarize(per_fold),
        "summary_pre_validation": summarize(pre),
        "validation": next((r for r in per_fold if r["fold"]["is_validation"]), None),
        "beats_momentum_folds": int(sum(r["mcc"] > r["baselines"]["momentum_mcc"] for r in per_fold)),
        "seconds": round(time.time() - t0, 1),
    }
    cfg = {
        "step": "walk_forward",
        "label": label,
        "horizon": h,
        "threshold": thr,
        "model": model_name,
        "scheme": scheme,
        "tag": tag,
        "params": {**LEARNED[model_name]().params, **(params or {})},
        "features": features or dev.features,
        "seed": SEED,
    }
    d = _experiment_dir(out_root, f"wf-{scheme}-{model_name}-{label}-{tag}", cfg)
    exp = {**_experiment_header(d, dev, cfg), "rows": [r["fold"] for r in per_fold]}
    _write(d, exp, cfg, result, importance, pl.concat(preds), pp_last)
    (d / "report.md").write_text(render_walk_forward(exp, result))
    return {"experiment": exp, "result": _compact_result(result), "dir": str(d)}


# ---------------------------------------------------------------------------------------------
# Optuna


def lgb_space(trial: Any) -> dict[str, Any]:
    return {
        "learning_rate": trial.suggest_float("learning_rate", 0.03, 0.2, log=True),
        "num_leaves": trial.suggest_int("num_leaves", 15, 255, log=True),
        "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 100, 5000, log=True),
        "feature_fraction": trial.suggest_float("feature_fraction", 0.4, 1.0),
        "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
        "lambda_l2": trial.suggest_float("lambda_l2", 1e-3, 100.0, log=True),
        "max_depth": trial.suggest_categorical("max_depth", [-1, 6, 10]),
        "class_weight": trial.suggest_categorical("class_weight", ["none", "balanced"]),
    }


def tune(
    dev: DevData,
    out_root: Path,
    label: str,
    n_trials: int = 25,
    model_name: str = "lightgbm",
    space: Callable[[Any], dict[str, Any]] = lgb_space,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    """TPE search; objective = mean MCC over the last two pre-validation folds (validation unused)."""
    import optuna

    tune_folds = [f for f in dev.folds if not f.is_validation][-2:]
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial: Any) -> float:
        params = space(trial)
        scores = []
        for step, fold in enumerate(tune_folds):
            fd = dev.fold_data(fold)
            _, proba = fit_predict(fd, label, model_name, params)
            from sklearn.metrics import matthews_corrcoef

            scores.append(float(matthews_corrcoef(to_index(fd.ev[label].to_numpy()), proba.argmax(axis=1))))
            trial.report(float(np.mean(scores)), step)
            if trial.should_prune():
                raise optuna.TrialPruned()
        log.info("trial %d %s mcc=%.4f", trial.number, params, np.mean(scores))
        return float(np.mean(scores))

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=SEED),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=5),
    )
    # trial 0 = the Phase 7 defaults, so the search can only report an improvement it measured
    default = LEARNED[model_name]().params
    study.enqueue_trial({k: default.get(k, v) for k, v in _DEFAULT_TRIAL.items()})
    t0 = time.time()
    study.optimize(objective, n_trials=n_trials, timeout=timeout_s)
    trials = [
        {"number": t.number, "state": t.state.name, "value": t.value, "params": t.params}
        for t in study.trials
    ]
    best = study.best_trial
    cfg = {
        "step": "optuna",
        "label": label,
        "model": model_name,
        "n_trials": n_trials,
        "objective": "mean validation-free MCC over folds " + ",".join(f.name for f in tune_folds),
        "sampler": "TPE",
        "seed": SEED,
    }
    result = {
        "best_params": best.params,
        "best_value": best.value,
        "default_value": trials[0]["value"],
        "trials": trials,
        "seconds": round(time.time() - t0, 1),
    }
    d = _experiment_dir(out_root, f"optuna-{model_name}-{label}", cfg)
    exp = _experiment_header(d, dev, cfg)
    (d / "experiment.json").write_text(json.dumps(exp, indent=2, default=str))
    (d / "config.json").write_text(json.dumps(cfg, indent=2, default=str))
    (d / "metrics.json").write_text(json.dumps(result, indent=2, default=str))
    (d / "report.md").write_text(render_tune(exp, result))
    return {"experiment": exp, "result": result, "dir": str(d)}


_DEFAULT_TRIAL = {
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 1000,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "lambda_l2": 1.0,
    "max_depth": -1,
    "class_weight": "none",
}


# ---------------------------------------------------------------------------------------------
# feature selection


def feature_selection(
    dev: DevData,
    out_root: Path,
    label: str,
    params: dict[str, Any] | None = None,
    top_k: tuple[int, ...] = (10, 20, 30, 50),
    sample: int = 200_000,
) -> dict[str, Any]:
    """Importance by correlation, mutual information, SHAP and permutation; group and top-k ablation.

    All decisions use the last pre-validation fold (model fit on the rows before it). Validation is
    used once at the end to compare the chosen set with all features."""
    from sklearn.feature_selection import mutual_info_classif
    from sklearn.metrics import log_loss, matthews_corrcoef

    sel_fold = [f for f in dev.folds if not f.is_validation][-1]
    val_fold = next(f for f in dev.folds if f.is_validation)
    fd = dev.fold_data(sel_fold)
    feats = fd.features
    rng = np.random.default_rng(SEED)
    y_fit = to_index(fd.fit[label].to_numpy())
    y_ev = to_index(fd.ev[label].to_numpy())
    t0 = time.time()
    model, proba = fit_predict(fd, label, "lightgbm", params)
    base_mcc = float(matthews_corrcoef(y_ev, proba.argmax(axis=1)))
    base_ll = float(log_loss(y_ev, np.clip(proba, 1e-7, 1), labels=[0, 1, 2]))

    i_fit = np.sort(rng.choice(len(y_fit), size=min(sample, len(y_fit)), replace=False))
    Xs, ys = fd.X_fit[i_fit], y_fit[i_fit]
    mi = mutual_info_classif(Xs[:50_000], ys[:50_000], random_state=SEED)
    contrib = model.model.predict(Xs[:50_000], num_iteration=model.best_iteration, pred_contrib=True)
    nf = len(feats)
    shap = np.abs(contrib.reshape(len(contrib), 3, nf + 1)[:, :, :nf]).mean(axis=0).sum(axis=0)
    corr = np.corrcoef(Xs, rowvar=False)

    i_ev = np.sort(rng.choice(len(y_ev), size=min(sample, len(y_ev)), replace=False))
    Xe, ye = fd.X_ev[i_ev].copy(), y_ev[i_ev]
    p0 = model.predict_proba(Xe)
    ll0 = float(log_loss(ye, np.clip(p0, 1e-7, 1), labels=[0, 1, 2]))
    mcc0 = float(matthews_corrcoef(ye, p0.argmax(axis=1)))
    perm_ll, perm_mcc = np.zeros(nf), np.zeros(nf)
    for j in range(nf):
        col = Xe[:, j].copy()
        Xe[:, j] = rng.permutation(col)
        pj = model.predict_proba(Xe)
        perm_ll[j] = float(log_loss(ye, np.clip(pj, 1e-7, 1), labels=[0, 1, 2])) - ll0
        perm_mcc[j] = mcc0 - float(matthews_corrcoef(ye, pj.argmax(axis=1)))
        Xe[:, j] = col
    gain = model.importance(feats)
    importance = {
        f: {
            "group": feature_group(f),
            "mutual_info": float(mi[j]),
            "shap_mean_abs": float(shap[j]),
            "permutation_logloss": float(perm_ll[j]),
            "permutation_mcc": float(perm_mcc[j]),
            "gain": float(gain[f]),
        }
        for j, f in enumerate(feats)
    }
    # correlation filter: of each pair with |r| > 0.95, drop the one with lower mutual information
    drop: set[str] = set()
    pairs = []
    for a in range(nf):
        for b in range(a + 1, nf):
            if abs(corr[a, b]) > 0.95:
                pairs.append((feats[a], feats[b], float(corr[a, b])))
                drop.add(feats[b] if mi[a] >= mi[b] else feats[a])
    ranked = [feats[j] for j in np.argsort(-perm_ll)]

    candidates: dict[str, list[str]] = {"all": feats}
    for g in GROUPS:
        members = [f for f in feats if feature_group(f) == g]
        if members:
            candidates[f"only_{g.lower()}"] = members
            candidates[f"without_{g.lower()}"] = [f for f in feats if feature_group(f) != g]
    candidates["corr_filtered"] = [f for f in feats if f not in drop]
    for k in top_k:
        if k < nf:
            candidates[f"top{k}_permutation"] = ranked[:k]
    scores: dict[str, dict[str, Any]] = {}
    for name, fs in candidates.items():
        if name == "all":
            scores[name] = {"n": nf, "mcc": base_mcc, "log_loss": base_ll}
            continue
        sub = dev.fold_data(sel_fold, features=tuple(fs))
        _, pr = fit_predict(sub, label, "lightgbm", params)
        scores[name] = {
            "n": len(fs),
            "mcc": float(matthews_corrcoef(y_ev, pr.argmax(axis=1))),
            "log_loss": float(log_loss(y_ev, np.clip(pr, 1e-7, 1), labels=[0, 1, 2])),
        }
        log.info("feature set %s n=%d mcc=%.4f", name, len(fs), scores[name]["mcc"])
    # choose the smallest set within 0.002 MCC of the best (ties go to fewer features)
    best_mcc = max(s["mcc"] for s in scores.values())
    chosen = min((n for n, s in scores.items() if s["mcc"] >= best_mcc - 0.002), key=lambda n: scores[n]["n"])

    validation = {}
    for name in dict.fromkeys(["all", chosen]):
        vfd = dev.fold_data(val_fold, features=tuple(candidates[name]))
        _, pv = fit_predict(vfd, label, "lightgbm", params)
        rep = _fold_report(
            vfd,
            label,
            pv,
            dev.horizon,
            next(t for t in dev.thresholds if label_name(dev.horizon, t) == label),
        )
        validation[name] = rep
    cfg = {
        "step": "feature_selection",
        "label": label,
        "model": "lightgbm",
        "params": params or {},
        "selection_fold": asdict(sel_fold),
        "sample": sample,
        "seed": SEED,
        "rule": "smallest set within 0.002 MCC of the best on the selection fold",
    }
    result = {
        "selection_fold_scores": scores,
        "chosen": chosen,
        "chosen_features": candidates[chosen],
        "correlated_pairs": pairs,
        "dropped_by_correlation": sorted(drop),
        "validation": {k: _compact_fold(v) for k, v in validation.items()},
        "seconds": round(time.time() - t0, 1),
    }
    d = _experiment_dir(out_root, f"features-lightgbm-{label}", cfg)
    exp = _experiment_header(d, dev, cfg)
    (d / "experiment.json").write_text(json.dumps(exp, indent=2, default=str))
    (d / "config.json").write_text(json.dumps(cfg, indent=2, default=str))
    (d / "metrics.json").write_text(json.dumps(result, indent=2, default=str))
    (d / "feature_importance.json").write_text(json.dumps(importance, indent=1))
    (d / "report.md").write_text(render_features(exp, result, importance))
    return {"experiment": exp, "result": result, "dir": str(d)}


# ---------------------------------------------------------------------------------------------
# probability thresholds and ensembles (fit on pre-validation OOF, applied to validation)


def _probs(df: pl.DataFrame, prefix: str = "p_") -> np.ndarray:
    return _norm(df.select(f"{prefix}down", f"{prefix}neutral", f"{prefix}up").to_numpy().astype(np.float64))


def _norm(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-9, None)
    return np.asarray(p / p.sum(axis=1, keepdims=True))


def class_bias_fit(y: np.ndarray, proba: np.ndarray, grid: np.ndarray | None = None) -> np.ndarray:
    """Multiplicative weights on (DOWN, NEUTRAL, UP) maximising MCC of argmax(w * p); NEUTRAL fixed at 1."""
    from sklearn.metrics import matthews_corrcoef

    grid = np.round(np.arange(0.7, 1.61, 0.05), 2) if grid is None else grid
    best, best_w = -1.0, np.ones(3)
    for wd in grid:
        for wu in grid:
            w = np.array([wd, 1.0, wu])
            m = float(matthews_corrcoef(y, (proba * w).argmax(axis=1)))
            if m > best:
                best, best_w = m, w
    return best_w


def selective_threshold_fit(
    y: np.ndarray, proba: np.ndarray, min_coverage: float = 0.05, grid: np.ndarray | None = None
) -> dict[str, Any]:
    """Probability threshold with the highest selective accuracy at >= `min_coverage` (OOF rows)."""
    grid = np.round(np.arange(0.34, 0.80, 0.01), 2) if grid is None else grid
    p_dir = np.maximum(proba[:, UP], proba[:, DOWN])
    direction = np.where(proba[:, UP] >= proba[:, DOWN], UP, DOWN)
    best: dict[str, Any] = {"threshold": None, "accuracy": None, "coverage": None}
    for t in grid:
        m = (p_dir >= t) & (p_dir > proba[:, NEUTRAL])
        cov = float(m.mean())
        if cov < min_coverage or not m.any():
            continue
        acc = float(np.mean(y[m] == direction[m]))
        if best["accuracy"] is None or acc > best["accuracy"]:
            best = {"threshold": float(t), "accuracy": acc, "coverage": cov}
    return best


def apply_selective(y: np.ndarray, proba: np.ndarray, fret: np.ndarray, t: float) -> dict[str, Any]:
    return selective_direction_table(y, proba, fret, thresholds=(t,))[0]


def ensembles(
    out_root: Path,
    label: str,
    lgb_dir: Path,
    xgb_dir: Path | None,
    deep_dir: Path | None,
    dev_info: dict[str, Any],
) -> dict[str, Any]:
    from sklearn.linear_model import LogisticRegression

    lgb = pl.read_parquet(lgb_dir / "predictions.parquet")
    folds = sorted(lgb["fold"].unique().to_list(), key=lambda s: int(s[1:]))
    val_name = folds[-1]
    frame = lgb.rename({"p_down": "lgb_down", "p_neutral": "lgb_neutral", "p_up": "lgb_up"})
    if xgb_dir is not None:
        x = pl.read_parquet(xgb_dir / "predictions.parquet").select(
            "symbol", "ts", "fold", pl.col("p_down").alias("xgb_down"),
            pl.col("p_neutral").alias("xgb_neutral"),
            pl.col("p_up").alias("xgb_up"),
        )  # fmt: skip
        frame = frame.join(x, on=["symbol", "ts", "fold"], how="inner")
    frame = frame.with_columns(pl.Series("y", to_index(frame["y_raw"].to_numpy())))
    oof, val = frame.filter(pl.col("fold") != val_name), frame.filter(pl.col("fold") == val_name)
    y_oof, y_val = oof["y"].to_numpy(), val["y"].to_numpy()
    f_val = val["fret"].to_numpy().astype(float)
    P_oof = {"lightgbm": _probs(oof, "lgb_")}
    P_val = {"lightgbm": _probs(val, "lgb_")}
    if xgb_dir is not None:
        P_oof["xgboost"], P_val["xgboost"] = _probs(oof, "xgb_"), _probs(val, "xgb_")
    from sklearn.metrics import matthews_corrcoef

    def mcc(y: np.ndarray, p: np.ndarray) -> float:
        return float(matthews_corrcoef(y, p.argmax(axis=1)))

    results: dict[str, Any] = {}
    fitted: dict[str, Any] = {}
    if "xgboost" in P_oof:
        ws = np.round(np.arange(0, 1.01, 0.1), 1)
        w = float(max(ws, key=lambda w: mcc(y_oof, w * P_oof["lightgbm"] + (1 - w) * P_oof["xgboost"])))
        P_oof["weighted_lgb_xgb"] = w * P_oof["lightgbm"] + (1 - w) * P_oof["xgboost"]
        P_val["weighted_lgb_xgb"] = w * P_val["lightgbm"] + (1 - w) * P_val["xgboost"]
        fitted["weighted_lgb_xgb"] = {"w_lightgbm": w}
        Z_oof = np.log(np.clip(np.hstack([P_oof["lightgbm"], P_oof["xgboost"]]), 1e-6, 1))
        Z_val = np.log(np.clip(np.hstack([P_val["lightgbm"], P_val["xgboost"]]), 1e-6, 1))
        meta = LogisticRegression(C=1.0, max_iter=500, random_state=SEED).fit(Z_oof, y_oof)
        P_val["stacked_lgb_xgb"] = meta.predict_proba(Z_val)
        fitted["stacked_lgb_xgb"] = {"meta": "multinomial logistic on log-probabilities, fit on OOF folds"}
    for name in list(P_val):
        bias = class_bias_fit(y_oof, P_oof[name]) if name in P_oof else None
        rep = multiclass_report(y_val, P_val[name])
        rep["selective"] = selective_direction_table(y_val, P_val[name], f_val)
        if bias is not None:
            rep_b = multiclass_report(y_val, _norm(P_val[name] * bias))
            rep["class_bias"] = {"weights": bias.tolist(), **{k: rep_b[k] for k in HEADLINE}}
            sel = selective_threshold_fit(y_oof, P_oof[name])
            rep["selective_tuned"] = {
                "chosen_on_oof": sel,
                "validation": apply_selective(y_val, P_val[name], f_val, sel["threshold"])
                if sel["threshold"]
                else None,
            }
        results[name] = rep
        log.info("%s %s val mcc=%.4f", label, name, rep["mcc"])

    # LightGBM + transformer: the deep model only has validation predictions, so the weight is fit on
    # the first half of validation dates and scored on the second half (both models on the same rows)
    halves: dict[str, Any] = {}
    if deep_dir is not None:
        dp = pl.read_parquet(deep_dir / "predictions.parquet").select(
            "symbol", "ts", pl.col("p_down").alias("dl_down"), pl.col("p_neutral").alias("dl_neutral"),
            pl.col("p_up").alias("dl_up"),
        )  # fmt: skip
        j = val.join(dp, on=["symbol", "ts"], how="inner").sort("ts", "symbol")
        dates = j["ts"].dt.date().unique().sort()
        cut = dates[len(dates) // 2]
        a, b = j.filter(pl.col("ts").dt.date() < cut), j.filter(pl.col("ts").dt.date() >= cut)
        ya, yb = a["y"].to_numpy(), b["y"].to_numpy()
        La, Lb, Da, Db = _probs(a, "lgb_"), _probs(b, "lgb_"), _probs(a, "dl_"), _probs(b, "dl_")
        ws = np.round(np.arange(0, 1.01, 0.1), 1)
        w = float(max(ws, key=lambda w: mcc(ya, w * La + (1 - w) * Da)))
        fb = b["fret"].to_numpy().astype(float)
        for name, p in (
            ("lightgbm", Lb),
            ("transformer", Db),
            ("weighted_lgb_transformer", w * Lb + (1 - w) * Db),
        ):
            r = multiclass_report(yb, p)
            r["selective"] = selective_direction_table(yb, p, fb)
            halves[name] = r
        halves["fit"] = {"w_lightgbm": w, "fit_dates": [str(dates[0]), str(cut)], "score_from": str(cut),
                         "rows_fit": a.height, "rows_score": b.height}  # fmt: skip
    cfg = {
        "step": "ensembles",
        "label": label,
        "inputs": {"lightgbm": str(lgb_dir), "xgboost": str(xgb_dir), "transformer": str(deep_dir)},
        "fitted": fitted,
        "rule": "weights / meta-model / class bias / selective threshold fit on OOF folds "
        + ",".join(folds[:-1])
        + f"; scored on {val_name} (validation)",
        "seed": SEED,
    }
    result = {
        "validation": {
            k: _compact_fold(v)
            | {"class_bias": v.get("class_bias"), "selective_tuned": v.get("selective_tuned")}
            for k, v in results.items()
        },
        "lgb_transformer_second_half": {
            k: (_compact_fold(v) if k != "fit" else v) for k, v in halves.items()
        },
        "oof_rows": oof.height,
        "validation_rows": val.height,
    }
    d = _experiment_dir(out_root, f"ensemble-{label}", cfg)
    exp = {"experiment_id": d.name, "runner_version": RUNNER_VERSION, "phase": 9, **dev_info, "config": cfg,
           "created_at": datetime.now(UTC).isoformat()}  # fmt: skip
    (d / "experiment.json").write_text(json.dumps(exp, indent=2, default=str))
    (d / "config.json").write_text(json.dumps(cfg, indent=2, default=str))
    (d / "metrics.json").write_text(json.dumps(result, indent=2, default=str))
    val.select("symbol", "ts", "y", "fret").with_columns(
        *[
            pl.Series(f"{n}_p_{c.lower()}", P_val[n][:, k], dtype=pl.Float32)
            for n in P_val
            for k, c in enumerate(CLASSES)
        ]
    ).write_parquet(d / "predictions.parquet")
    (d / "report.md").write_text(render_ensembles(exp, result))
    return {"experiment": exp, "result": result, "dir": str(d)}


# ---------------------------------------------------------------------------------------------
# helpers and reports


def _experiment_dir(out_root: Path, base: str, cfg: dict[str, Any]) -> Path:
    key = hashlib.sha1(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:8]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return _new_dir(out_root, f"{stamp}-p9-{base}-{key}")


def _experiment_header(d: Path, dev: DevData, cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "experiment_id": d.name,
        "runner_version": RUNNER_VERSION,
        "phase": 9,
        **dev.info(),
        "config": cfg,
        "created_at": datetime.now(UTC).isoformat(),
    }


def _write(
    d: Path,
    exp: dict[str, Any],
    cfg: dict[str, Any],
    result: dict[str, Any],
    importance: dict[str, float],
    preds: pl.DataFrame,
    pp: Preprocessor | None,
) -> None:
    (d / "experiment.json").write_text(json.dumps(exp, indent=2, default=str))
    (d / "config.json").write_text(json.dumps(cfg, indent=2, default=str))
    (d / "metrics.json").write_text(json.dumps(result, indent=2, default=str))
    (d / "feature_importance.json").write_text(json.dumps(importance, indent=1))
    preds.write_parquet(d / "predictions.parquet")
    if pp is not None:
        pp.save(d / "preprocessor.json")


_FOLD_KEYS = (*HEADLINE, "precision_macro", "recall_macro", "pr_auc_macro", "log_loss", "coverage", "verdict",
              "class_distribution", "pred_distribution", "selective", "baselines", "fold", "best_iteration",
              "seconds")  # fmt: skip


def _compact_fold(r: dict[str, Any]) -> dict[str, Any]:
    return {k: r.get(k) for k in _FOLD_KEYS if k in r}


def _compact_result(res: dict[str, Any]) -> dict[str, Any]:
    out = dict(res)
    out["per_fold"] = [_compact_fold(r) for r in res["per_fold"]]
    out["validation"] = _compact_fold(res["validation"]) if res["validation"] else None
    return out


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.1f}%"


def _num(x: float | None, nd: int = 3) -> str:
    return "–" if x is None else f"{x:.{nd}f}"


def fold_table(per_fold: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Fold | Eval dates | Fit rows | Eval rows | Accuracy | Majority acc | Balanced acc | Macro F1 |"
        " MCC |"
        " Momentum MCC | ROC-AUC | Brier | ECE |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in per_fold:
        f = r["fold"]
        name = f["name"] + (" (validation)" if f["is_validation"] else "")
        lines.append(
            f"| {name} | {f['start']}..{f['end']} | {f['fit_rows']:,} | {f['eval_rows']:,} | "
            f"{_pct(r['accuracy'])} | {_pct(r['baselines']['majority_accuracy'])} | "
            f"{_pct(r['balanced_accuracy'])} | {_num(r['macro_f1'])} | "
            f"{_num(r['mcc'])} | {_num(r['baselines']['momentum_mcc'])} | {_num(r['roc_auc_ovr'])} | "
            f"{_num(r['brier'])} | {_num(r['ece_top'])} |"
        )
    return lines


def summary_table(summary: dict[str, Any]) -> list[str]:
    lines = ["| Metric | Mean | Median | Std | Min | Max |", "|---|---|---|---|---|---|"]
    for k, v in summary.items():
        fmt = _pct if k in ("accuracy", "balanced_accuracy") else _num
        lines.append(
            f"| {k} | {fmt(v['mean'])} | {fmt(v['median'])} | {_num(v['std'], 4)} | {fmt(v['min'])} | "
            f"{fmt(v['max'])} |"
        )
    return lines


def render_walk_forward(exp: dict[str, Any], res: dict[str, Any]) -> str:
    c = exp["config"]
    lines = [
        f"# {exp['experiment_id']}",
        "",
        f"Walk-forward ({c['scheme']}) {c['model']} on `{c['label']}` ({c['tag']} parameters). "
        "Test period not used.",
        "",
        *fold_table(res["per_fold"]),
        "",
        "All folds:",
        "",
        *summary_table(res["summary_all"]),
        "",
        f"Beats momentum (MCC) in {res['beats_momentum_folds']} of {len(res['per_fold'])} folds.",
        "",
    ]
    return "\n".join(lines)


def render_tune(exp: dict[str, Any], res: dict[str, Any]) -> str:
    c = exp["config"]
    done = [t for t in res["trials"] if t["state"] == "COMPLETE"]
    lines = [
        f"# {exp['experiment_id']}",
        "",
        f"Optuna ({c['sampler']}, {len(res['trials'])} trials, {len(done)} complete) for {c['model']} on "
        f"`{c['label']}`. Objective: {c['objective']}. Validation and test not used.",
        "",
        f"Default parameters (trial 0): {_num(res['default_value'], 4)}. Best: {_num(res['best_value'], 4)}.",
        "",
        "Best parameters: `" + json.dumps(res["best_params"]) + "`",
        "",
    ]
    return "\n".join(lines)


def render_features(exp: dict[str, Any], res: dict[str, Any], imp: dict[str, Any]) -> str:
    c = exp["config"]
    lines = [
        f"# {exp['experiment_id']}",
        "",
        f"Feature selection for LightGBM on `{c['label']}`. Decided on fold {c['selection_fold']['name']} "
        f"({c['selection_fold']['start']}..{c['selection_fold']['end']}, training period); "
        "validation used once.",
        "",
        "| Feature set | Features | MCC (selection fold) | Log loss |",
        "|---|---|---|---|",
    ]
    for n, s in sorted(res["selection_fold_scores"].items(), key=lambda kv: -kv[1]["mcc"]):
        lines.append(f"| {n} | {s['n']} | {_num(s['mcc'], 4)} | {_num(s['log_loss'], 4)} |")
    lines += ["", f"Chosen: **{res['chosen']}** ({c['rule']}).", "", "Validation:", "",
              "| Feature set | Accuracy | Balanced acc | MCC |", "|---|---|---|---|"]  # fmt: skip
    for n, r in res["validation"].items():
        lines.append(
            f"| {n} | {_pct(r['accuracy'])} | {_pct(r['balanced_accuracy'])} | {_num(r['mcc'], 4)} |"
        )
    top = sorted(imp.items(), key=lambda kv: -kv[1]["permutation_logloss"])[:20]
    lines += ["", "Top 20 by permutation importance (log-loss increase on the selection fold):", "",
              "| Feature | Group | Permutation Δlog-loss | Permutation ΔMCC | SHAP mean abs | Mutual info |",
              "|---|---|---|---|---|---|"]  # fmt: skip
    for f, v in top:
        lines.append(
            f"| {f} | {v['group']} | {v['permutation_logloss']:.5f} | {v['permutation_mcc']:.4f} | "
            f"{v['shap_mean_abs']:.4f} | {v['mutual_info']:.4f} |"
        )
    lines += ["", f"Correlated pairs (|r| > 0.95): {len(res['correlated_pairs'])}; dropped by the filter: "
              + (", ".join(res["dropped_by_correlation"]) or "none"), ""]  # fmt: skip
    return "\n".join(lines)


def render_ensembles(exp: dict[str, Any], res: dict[str, Any]) -> str:
    c = exp["config"]
    lines = [
        f"# {exp['experiment_id']}",
        "",
        f"Ensembles and threshold optimisation on `{c['label']}`. {c['rule']}.",
        "",
        "| Model | Accuracy | Balanced acc | MCC | + class bias: MCC | Selective t (OOF) | Val coverage |"
        " Val selective acc | Val sign acc |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for n, r in res["validation"].items():
        cb = r.get("class_bias") or {}
        st = r.get("selective_tuned") or {}
        v = st.get("validation") or {}
        t = (st.get("chosen_on_oof") or {}).get("threshold")
        lines.append(
            f"| {n} | {_pct(r['accuracy'])} | {_pct(r['balanced_accuracy'])} | {_num(r['mcc'])} | "
            f"{_num(cb.get('mcc'))} | {_num(t, 2)} | {_pct(v.get('coverage'))} | {_pct(v.get('accuracy'))} | "
            f"{_pct(v.get('sign_accuracy'))} |"
        )
    h = res.get("lgb_transformer_second_half") or {}
    if h:
        f = h["fit"]
        lines += ["", f"LightGBM + transformer (weight {f['w_lightgbm']} on LightGBM fit on validation dates "
                  f"{f['fit_dates'][0]}..{f['fit_dates'][1]}, scored from {f['score_from']}, "
                  f"{f['rows_score']:,} rows):",
                  "", "| Model | Accuracy | Balanced acc | MCC |", "|---|---|---|---|"]  # fmt: skip
        for n, r in h.items():
            if n != "fit":
                lines.append(
                    f"| {n} | {_pct(r['accuracy'])} | {_pct(r['balanced_accuracy'])} | {_num(r['mcc'])} |"
                )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# orchestration

KEY_LABELS = ((5, 0.0010), (1, 0.0005))  # default horizon + best Phase 7 label


def candidate_thresholds(phase7: list[dict[str, Any]], per_horizon: int = 2) -> dict[int, list[float]]:
    """Top `per_horizon` thresholds per horizon by Phase 7 validation MCC of the best learned model."""
    by_h: dict[int, list[tuple[float, float]]] = {}
    for s in phase7:
        e, m = s["experiment"], s["metrics"]
        learned = [n for n in ("logistic", "random_forest", "xgboost", "lightgbm") if n in m]
        best = max(m[n]["mcc"] for n in learned)
        by_h.setdefault(int(e["horizon_minutes"]), []).append((float(e["threshold"]), float(best)))
    return {
        h: sorted(t for t, _ in sorted(v, key=lambda x: -x[1])[:per_horizon]) for h, v in sorted(by_h.items())
    }


def latest(out_root: Path, pattern: str) -> Path | None:
    hits = sorted(d for d in out_root.glob(f"*-p9-{pattern}-*") if (d / "metrics.json").exists())
    return hits[-1] if hits else None


def run_phase9(
    data_root: Path,
    out_root: Path,
    steps: str = "WTFE",
    dataset: str = "core100_s5",
    phase7: list[dict[str, Any]] | None = None,
    n_trials: int = 25,
    key_labels: tuple[tuple[int, float], ...] = KEY_LABELS,
    deep_root: Path | None = None,
) -> list[dict[str, Any]]:
    out_root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    keys = {label_name(h, t) for h, t in key_labels}
    if "W" in steps:
        cands = candidate_thresholds(phase7) if phase7 else {}
        for h, t in key_labels:
            cands.setdefault(h, [])
            if t not in cands[h]:
                cands[h] = sorted([*cands[h], t])
        for h, ts in cands.items():
            dev = load_dev(data_root, h, tuple(ts), dataset)
            for t in ts:
                lab = label_name(h, t)
                results.append(walk_forward(dev, out_root, lab))
                if lab in keys:
                    results.append(walk_forward(dev, out_root, lab, "xgboost"))
                    results.append(walk_forward(dev, out_root, lab, scheme="rolling"))
            del dev
    if "T" in steps:
        for h, t in key_labels:
            lab = label_name(h, t)
            dev = load_dev(data_root, h, (t,), dataset)
            tr = tune(dev, out_root, lab, n_trials)
            results.append(tr)
            results.append(walk_forward(dev, out_root, lab, params=tr["result"]["best_params"], tag="tuned"))
            del dev
    if "F" in steps:
        h, t = key_labels[0]
        dev = load_dev(data_root, h, (t,), dataset)
        results.append(feature_selection(dev, out_root, label_name(h, t)))
        del dev
    if "E" in steps:
        for h, t in key_labels:
            lab = label_name(h, t)
            lgb_dir = latest(out_root, f"wf-expanding-lightgbm-{lab}-default")
            xgb_dir = latest(out_root, f"wf-expanding-xgboost-{lab}-default")
            deep = sorted((deep_root or out_root).glob(f"*-p8-transformer-L120-{lab}-*"))
            if lgb_dir is None:
                raise FileNotFoundError(f"run step W first: no walk-forward LightGBM for {lab}")
            info = json.loads((lgb_dir / "experiment.json").read_text())
            dev_info = {
                k: info[k]
                for k in (
                    "dataset_id",
                    "dataset",
                    "train_period",
                    "validation_period",
                    "test_period",
                    "folds",
                )
            }
            results.append(ensembles(out_root, lab, lgb_dir, xgb_dir, deep[-1] if deep else None, dev_info))
    return results


# ---------------------------------------------------------------------------------------------
# Phase 9 summary report


def collect(out_root: Path) -> dict[str, list[dict[str, Any]]]:
    """Latest Phase 9 experiment per (step, name) from the experiment folders."""
    found: dict[str, dict[str, Any]] = {}
    for d in sorted(out_root.glob("*-p9-*")):
        if not (d / "metrics.json").exists():
            continue
        exp = json.loads((d / "experiment.json").read_text())
        if exp.get("dataset_id") == "golden":
            continue
        name = d.name.split("-p9-", 1)[1].rsplit("-", 1)[0]  # strip the stamp and config hash
        found[name] = {
            "dir": d.name,
            "experiment": exp,
            "result": json.loads((d / "metrics.json").read_text()),
        }
    out: dict[str, list[dict[str, Any]]] = {"wf": [], "optuna": [], "features": [], "ensemble": []}
    for name, r in sorted(found.items()):
        out[name.split("-", 1)[0]].append(r)
    return out


def _wf_row(r: dict[str, Any]) -> str:
    c, res = r["experiment"]["config"], r["result"]
    s = res["summary_all"]
    v = res["validation"] or {}
    n = len(res["per_fold"])
    return (
        f"| {c['label']} | {c['model']} | {c['scheme']} | {c['tag']} | {_pct(s['accuracy']['mean'])} | "
        f"{_pct(s['balanced_accuracy']['mean'])} | {_num(s['mcc']['mean'])} | {_num(s['mcc']['median'])} | "
        f"{_num(s['mcc']['std'])} | {_num(s['mcc']['min'])} | {_num(s['mcc']['max'])} | "
        f"{_num(v.get('mcc'))} | {res['beats_momentum_folds']}/{n} |"
    )


WF_HEADER = [
    "| Label | Model | Scheme | Params | Mean acc | Mean bal acc | Mean MCC | Median MCC | Std MCC |"
    " Min MCC | Max MCC | Validation MCC | Beats momentum |",
    "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
]


def render_report(out_root: Path) -> str:
    c = collect(out_root)
    wf = c["wf"]
    if not wf:
        return "# Phase 9 — optimisation\n\nNo results yet.\n"
    e0 = wf[0]["experiment"]
    folds = e0["folds"]
    lines = [
        "# Phase 9 — optimisation and walk-forward (development period only)",
        "",
        f"Dataset `{e0['dataset_id']}`. Development period {e0['train_period']['start']}.."
        f"{e0['validation_period']['end']}; the test period ({e0['test_period']['start']}.."
        f"{e0['test_period']['end']}) was not read.",
        "",
        "Walk-forward folds (each scored by a model trained only on earlier, purged rows; first 60 minutes",
        "of each pre-validation fold embargoed; expanding = all earlier data, rolling = last 365 days):",
        "",
        "| Fold | Evaluation dates | Role |",
        "|---|---|---|",
        *[
            f"| {f['name']} | {f['start']}..{f['end']} | "
            + ("validation" if f["is_validation"] else "training period (out-of-fold)")
            + " |"
            for f in folds
        ],
        "",
        "## Walk-forward results",
        "",
        *WF_HEADER,
        *[
            _wf_row(r)
            for r in sorted(
                wf, key=lambda r: (r["experiment"]["config"]["horizon"], r["experiment"]["config"]["label"])
            )
        ],
        "",
        "Accuracy and MCC are averaged over all folds including validation. Beats momentum = folds where",
        "MCC is above the momentum rule on the same rows.",
        "",
        "## Label threshold per horizon (chosen by mean walk-forward MCC, LightGBM expanding defaults)",
        "",
        "| Horizon | Candidates (mean MCC) | Chosen |",
        "|---|---|---|",
    ]
    by_h: dict[int, list[tuple[str, float]]] = {}
    for r in wf:
        cfg = r["experiment"]["config"]
        if cfg["model"] == "lightgbm" and cfg["scheme"] == "expanding" and cfg["tag"] == "default":
            by_h.setdefault(cfg["horizon"], []).append(
                (cfg["label"], r["result"]["summary_all"]["mcc"]["mean"])
            )
    for h in sorted(by_h):
        cands = sorted(by_h[h], key=lambda x: -x[1])
        lines.append(f"| {h}m | " + ", ".join(f"{lab} ({m:.3f})" for lab, m in cands) + f" | {cands[0][0]} |")
    if c["optuna"]:
        lines += ["", "## Optuna (LightGBM)", "",
                  "| Label | Trials | Objective folds | Default objective | Best objective |"
                  " Best parameters |",
                  "|---|---|---|---|---|---|"]  # fmt: skip
        for r in c["optuna"]:
            cfg, res = r["experiment"]["config"], r["result"]
            lines.append(
                f"| {cfg['label']} | {len(res['trials'])} | {cfg['objective'].split('folds ')[-1]} | "
                f"{_num(res['default_value'], 4)} | {_num(res['best_value'], 4)} | "
                f"`{json.dumps(res['best_params'])}` |"
            )
        lines += ["", "Tuned vs default parameters, full walk-forward (the objective folds are in-sample "
                  "for the",
                  "tuned row, so its validation MCC is the clean comparison):", "", *WF_HEADER]  # fmt: skip
        for r in wf:
            cfg = r["experiment"]["config"]
            if (
                cfg["model"] == "lightgbm"
                and cfg["scheme"] == "expanding"
                and cfg["label"] in {o["experiment"]["config"]["label"] for o in c["optuna"]}
            ):
                lines.append(_wf_row(r))
    for r in c["features"]:
        cfg, res = r["experiment"]["config"], r["result"]
        title = f"## Feature selection ({cfg['label']}, decided on fold {cfg['selection_fold']['name']})"
        lines += ["", title, "",
                  "| Feature set | Features | MCC (selection fold) |", "|---|---|---|"]  # fmt: skip
        for n, s in sorted(res["selection_fold_scores"].items(), key=lambda kv: -kv[1]["mcc"]):
            lines.append(f"| {n} | {s['n']} | {_num(s['mcc'], 4)} |")
        chosen = f"Chosen: **{res['chosen']}** ({len(res['chosen_features'])} features; {cfg['rule']})."
        lines += ["", chosen, "",
                  "| Validation | Accuracy | Balanced acc | MCC |", "|---|---|---|---|"]  # fmt: skip
        for n, v in res["validation"].items():
            lines.append(
                f"| {n} | {_pct(v['accuracy'])} | {_pct(v['balanced_accuracy'])} | {_num(v['mcc'], 4)} |"
            )
    for r in c["ensemble"]:
        lines += ["", f"## Ensembles and thresholds ({r['experiment']['config']['label']})", "",
                  *render_ensembles(r["experiment"], r["result"]).split("\n")[4:]]  # fmt: skip
    passing = [
        r["experiment"]["config"]["label"]
        for r in wf
        if r["result"]["validation"]
        and r["result"]["validation"]["accuracy"] >= 0.70
        and r["result"]["validation"]["balanced_accuracy"] >= 0.60
        and r["result"]["validation"]["mcc"] >= 0.30
    ]
    gate = (
        f"Configurations meeting accuracy >= 70%, balanced accuracy >= 60% and MCC >= 0.30 on validation: "
        f"{', '.join(passing)}. Still NOT VERIFIED until walk-forward stability and the test period "
        "confirm it."
        if passing
        else "No configuration reaches 70% accuracy together with balanced accuracy >= 60% and MCC >= 0.30 "
        "on validation. Status: **NOT VERIFIED** (spec section 39)."
    )
    lines += ["", "## Success gate", "", gate, "Test accuracy: not measured (test period unused).", ""]
    return "\n".join(lines)
