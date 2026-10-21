"""Phase 7 runner: baselines + classical models, trained on TRAIN, scored on VALIDATION.

The test split is never read here (rows are filtered to train/validation in the scan itself).

For every (horizon, threshold) an experiment directory is written and never overwritten:
experiment.json, config.json, metrics.json, feature_importance.json, report.md,
predictions.parquet (validation rows, class probabilities of every model) and preprocessor.json.

Training uses a time-grid subsample of the training split (bars with minute-of-session divisible
by `train_every`) to bound memory and run time. The last `es_frac` of training dates (purged and
embargoed) is held out for boosted-tree early stopping, so validation never steers training.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from pulsetrader.config import FEATURE_VERSION, LABEL_VERSION
from pulsetrader.eval.multiclass import (
    CLASSES,
    UP,
    multiclass_report,
    selective_direction_table,
    to_index,
)
from pulsetrader.features.preprocess import Preprocessor
from pulsetrader.labels.labels import label_name
from pulsetrader.models.classical import LEARNED, SEED, StratifiedRandom, momentum_classes, rule_proba

log = logging.getLogger(__name__)

RUNNER_VERSION = "classical-v1"
MOMENTUM_COL = {1: "ret_1", 5: "ret_5", 15: "ret_15", 30: "ret_30", 60: "ret_60"}


@dataclass
class RunConfig:
    dataset: str = "core100_s5"
    horizons: tuple[int, ...] = (1, 5, 15, 30, 60)
    thresholds: tuple[float, ...] = (0.0005, 0.0010, 0.0020, 0.0030, 0.0050)
    models: tuple[str, ...] = (
        "majority",
        "random",
        "no_change",
        "always_up",
        "momentum",
        "logistic",
        "random_forest",
        "xgboost",
        "lightgbm",
    )
    # slow models run only at these thresholds (None = every threshold)
    model_thresholds: dict[str, tuple[float, ...]] = field(
        default_factory=lambda: {"random_forest": (0.0010, 0.0020), "xgboost": (0.0010, 0.0020)}
    )
    train_every: int = 15  # minutes; training rows on this grid only
    es_frac: float = 0.10  # last share of training dates used for early stopping
    embargo_minutes: int = 60
    train_eval_rows: int = 200_000  # in-sample metrics on a fixed subsample (overfit check)
    seed: int = SEED
    feature_subset: list[str] | None = None  # None = all features in features.json
    extra: dict[str, Any] = field(default_factory=dict)


def _load(ds_dir: Path, h: int, features: list[str], cfg: RunConfig) -> tuple[pl.DataFrame, pl.DataFrame]:
    labels = [label_name(h, t) for t in cfg.thresholds]
    cols = list(
        dict.fromkeys(
            ["symbol", "ts", "trade_date", "split", f"fret_{h}", f"label_end_ts_{h}", MOMENTUM_COL[h]]
            + labels
            + features
        )
    )
    lf = pl.scan_parquet(ds_dir / "part-*.parquet").filter(
        pl.col("split").is_in(["train", "validation"]) & pl.col(f"fret_{h}").is_not_null()
    )
    train = (
        lf.filter((pl.col("split") == "train") & (pl.col("min_since_open") % cfg.train_every == 0))
        .select(cols)
        .collect()
        .sort("ts", "symbol")
    )
    valid = lf.filter(pl.col("split") == "validation").select(cols).collect().sort("ts", "symbol")
    return train, valid


def inner_split(
    train: pl.DataFrame, h: int, es_frac: float, embargo_minutes: int
) -> tuple[pl.Series, pl.Series]:
    """Boolean masks (fit, early_stop) over `train`: chronological, purged and embargoed."""
    dates = train["trade_date"].unique().sort()
    es_start_date = dates[int(len(dates) * (1 - es_frac))]
    es_start = train.filter(pl.col("trade_date") >= es_start_date)["ts"].min()
    assert isinstance(es_start, datetime)
    fit = (train["trade_date"] < es_start_date) & (train[f"label_end_ts_{h}"] <= es_start)
    es = train["ts"] >= es_start + timedelta(minutes=embargo_minutes)
    return fit, es


def _new_dir(root: Path, base: str) -> Path:
    d = root / base
    k = 1
    while d.exists():
        k += 1
        d = root / f"{base}-r{k}"
    d.mkdir(parents=True)
    return d


def run(data_root: Path, out_root: Path, cfg: RunConfig | None = None) -> list[dict[str, Any]]:
    cfg = cfg or RunConfig()
    ds_dir = data_root / "datasets" / cfg.dataset
    manifest = json.loads((ds_dir / "dataset_manifest.json").read_text())
    all_features = json.loads((ds_dir / "features.json").read_text())["features"]
    features = cfg.feature_subset or all_features
    periods = {p["name"]: p for p in manifest["periods"]}
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    summary: list[dict[str, Any]] = []

    for h in cfg.horizons:
        t0 = time.time()
        train, valid = _load(ds_dir, h, features, cfg)
        fit_m, es_m = inner_split(train, h, cfg.es_frac, cfg.embargo_minutes)
        fit_df, es_df = train.filter(fit_m), train.filter(es_m)
        pp = Preprocessor.fit(fit_df.with_columns(pl.lit("train").alias("split")), features, FEATURE_VERSION)
        X_fit, X_es, X_val = pp.transform(fit_df), pp.transform(es_df), pp.transform(valid)
        rng = np.random.default_rng(cfg.seed)
        tr_idx = np.sort(rng.choice(len(fit_df), size=min(cfg.train_eval_rows, len(fit_df)), replace=False))
        fret_val = valid[f"fret_{h}"].to_numpy().astype(np.float64)
        log.info(
            "h=%d loaded fit=%d es=%d val=%d in %.0fs",
            h,
            len(fit_df),
            len(es_df),
            len(valid),
            time.time() - t0,
        )

        for thr in cfg.thresholds:
            lab = label_name(h, thr)
            y_fit = to_index(fit_df[lab].to_numpy())
            y_es = to_index(es_df[lab].to_numpy())
            y_val = to_index(valid[lab].to_numpy())
            preds = valid.select("symbol", "ts", pl.Series("y", y_val, dtype=pl.Int8), pl.col(f"fret_{h}"))
            metrics: dict[str, Any] = {}
            importance: dict[str, Any] = {}
            for name in cfg.models:
                if name in cfg.model_thresholds and thr not in cfg.model_thresholds[name]:
                    continue
                t1 = time.time()
                info: dict[str, Any] = {}
                pred_override = None
                if name == "no_change":  # naive price predictor: future price = current price
                    proba = rule_proba(np.full(len(valid), 1))
                elif name == "always_up":  # buy-and-hold view
                    proba = rule_proba(np.full(len(valid), UP))
                elif name == "momentum":
                    past = valid[MOMENTUM_COL[h]].to_numpy().astype(np.float64)
                    proba = rule_proba(momentum_classes(past, thr))
                    info["rule"] = f"class of {MOMENTUM_COL[h]} with the same threshold"
                else:
                    model = LEARNED[name]()
                    model.fit(X_fit, y_fit, X_es, y_es)
                    proba = model.predict_proba(X_val)
                    if isinstance(model, StratifiedRandom):
                        pred_override = model.predict(len(valid))
                    else:
                        tr = multiclass_report(y_fit[tr_idx], model.predict_proba(X_fit[tr_idx]))
                        info["train_sample"] = {
                            k: tr[k] for k in ("accuracy", "balanced_accuracy", "mcc", "macro_f1")
                        }
                    info["params"] = model.params
                    if hasattr(model, "best_iteration"):
                        info["best_iteration"] = model.best_iteration
                    imp = model.importance(features)
                    if imp:
                        importance[name] = dict(sorted(imp.items(), key=lambda kv: -kv[1]))
                    if name in ("logistic", "random_forest", "xgboost", "lightgbm"):
                        preds = preds.with_columns(
                            pl.Series(f"{name}_p_{c.lower()}", proba[:, k], dtype=pl.Float32)
                            for k, c in enumerate(CLASSES)
                        )
                rep = multiclass_report(y_val, proba, pred_override)
                rep["selective"] = selective_direction_table(y_val, proba, fret_val)
                rep.update(info)
                rep["seconds"] = round(time.time() - t1, 1)
                metrics[name] = rep
                log.info(
                    "h=%d %s %s acc=%.4f bal=%.4f mcc=%.4f (%.0fs)",
                    h,
                    lab,
                    name,
                    rep["accuracy"],
                    rep["balanced_accuracy"],
                    rep["mcc"],
                    rep["seconds"],
                )
            cfg_dict = asdict(cfg)
            cfg_dict.update({"horizon": h, "threshold": thr, "label": lab, "features": features})
            key = hashlib.sha1(json.dumps(cfg_dict, sort_keys=True, default=str).encode()).hexdigest()[:8]
            d = _new_dir(out_root, f"{stamp}-p7-h{h}-{lab}-{key}")
            experiment = {
                "experiment_id": d.name,
                "runner_version": RUNNER_VERSION,
                "phase": 7,
                "dataset_id": manifest["dataset_id"],
                "dataset": cfg.dataset,
                "feature_version": FEATURE_VERSION,
                "label_version": LABEL_VERSION,
                "label": lab,
                "horizon_minutes": h,
                "threshold": thr,
                "seed": cfg.seed,
                "train_period": periods["train"],
                "validation_period": periods["validation"],
                "test_period": {**periods["test"], "used": False},
                "rows": {"fit": len(fit_df), "early_stop": len(es_df), "validation": len(valid)},
                "early_stop_window": [str(es_df["ts"].min()), str(es_df["ts"].max())],
                "created_at": datetime.now(UTC).isoformat(),
            }
            (d / "experiment.json").write_text(json.dumps(experiment, indent=2, default=str))
            (d / "config.json").write_text(json.dumps(cfg_dict, indent=2, default=str))
            (d / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
            (d / "feature_importance.json").write_text(json.dumps(importance, indent=1))
            pp.save(d / "preprocessor.json")
            preds.write_parquet(d / "predictions.parquet")
            (d / "report.md").write_text(render_experiment(experiment, metrics))
            summary.append({"experiment": experiment, "metrics": _compact(metrics)})
        del train, valid, X_fit, X_es, X_val
    return summary


def _compact(metrics: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "accuracy", "balanced_accuracy", "macro_f1", "mcc", "precision_macro", "recall_macro",
        "roc_auc_ovr", "updown_auc", "pr_auc_macro", "brier", "ece_top", "log_loss", "coverage", "verdict",
        "class_distribution", "pred_distribution", "train_sample", "best_iteration", "seconds",
    )  # fmt: skip
    return {m: {**{k: r.get(k) for k in keys}, "selective": r["selective"]} for m, r in metrics.items()}


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.1f}%"


def _num(x: float | None, nd: int = 3) -> str:
    return "–" if x is None else f"{x:.{nd}f}"


def render_experiment(exp: dict[str, Any], metrics: dict[str, Any]) -> str:
    lines = [
        f"# {exp['experiment_id']}",
        "",
        f"Label `{exp['label']}` ({exp['horizon_minutes']}-minute horizon, threshold "
        f"{100 * exp['threshold']:.2f}%). Trained on "
        f"{exp['train_period']['start']}..{exp['train_period']['end']}"
        f" ({exp['rows']['fit']:,} rows), scored on validation {exp['validation_period']['start']}.."
        f"{exp['validation_period']['end']} ({exp['rows']['validation']:,} rows). Test split not used.",
        "",
        "| Model | Accuracy | Balanced acc | Macro F1 | MCC | ROC-AUC | Up/down AUC* | Brier | ECE |"
        " Coverage | Verdict |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m, r in metrics.items():
        lines.append(
            f"| {m} | {_pct(r['accuracy'])} | {_pct(r['balanced_accuracy'])} | {_num(r['macro_f1'])} | "
            f"{_num(r['mcc'])} | {_num(r['roc_auc_ovr'])} | {_num(r['updown_auc'])} | "
            f"{_num(r['brier'])} | {_num(r['ece_top'])} | "
            f"{_pct(r['coverage'])} | {r['verdict']} |"
        )
    lines += ["", "*Up/down AUC is a diagnostic on rows whose label moved (subset chosen by the outcome).",
              "", "Validation class distribution: " + ", ".join(
        f"{k} {_pct(v)}" for k, v in next(iter(metrics.values()))["class_distribution"].items()
    ), ""]  # fmt: skip
    for m in ("logistic", "random_forest", "xgboost", "lightgbm"):
        if m not in metrics:
            continue
        lines += [
            f"## Selective UP/DOWN — {m}",
            "",
            "| P threshold | Predictions | Coverage | Accuracy | Sign accuracy | Balanced acc | MCC |",
            "|---|---|---|---|---|---|---|",
        ]
        for s in metrics[m]["selective"]:
            lines.append(
                f"| {s['threshold']:.2f} | {s['n_predictions']:,} | {_pct(s['coverage'])} | "
                f"{_pct(s.get('accuracy'))} | {_pct(s.get('sign_accuracy'))} | "
                f"{_pct(s.get('balanced_accuracy'))} | {_num(s.get('mcc'))} |"
            )
        lines.append("")
    return "\n".join(lines)


LEARNED_NAMES = ("logistic", "random_forest", "xgboost", "lightgbm")
BASELINE_NAMES = ("majority", "random", "no_change", "always_up", "momentum")


def render_summary(summary: list[dict[str, Any]]) -> str:
    """Phase 7 report across all (horizon, threshold) experiments. Validation only."""
    first = summary[0]["experiment"]
    lines = [
        "# Phase 7 — baselines and classical models (validation)",
        "",
        f"Dataset `{first['dataset_id']}`. Trained on {first['train_period']['start']}.."
        f"{first['train_period']['end']}, scored on validation {first['validation_period']['start']}.."
        f"{first['validation_period']['end']}. The test period ({first['test_period']['start']}.."
        f"{first['test_period']['end']}) was not used. Walk-forward evaluation is Phase 9.",
        "",
        "Task: 3 classes (DOWN / NEUTRAL / UP) per horizon and threshold. MCC and balanced accuracy",
        "are the headline numbers because NEUTRAL dominates at larger thresholds.",
        "",
        "## Best learned model per label vs best baseline (by validation MCC)",
        "",
        "| Horizon | Threshold | Majority acc | Best baseline (MCC) | Best model | Accuracy | Balanced acc |"
        " MCC | Up/down AUC* | Train-sample acc |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summary:
        e, m = s["experiment"], s["metrics"]
        base = max((n for n in BASELINE_NAMES if n in m), key=lambda n: m[n]["mcc"])
        learned = [n for n in LEARNED_NAMES if n in m]
        best = max(learned, key=lambda n: m[n]["mcc"])
        r = m[best]
        tr = (r.get("train_sample") or {}).get("accuracy")
        lines.append(
            f"| {e['horizon_minutes']}m | {100 * e['threshold']:.2f}% | {_pct(m['majority']['accuracy'])} | "
            f"{base} ({_num(m[base]['mcc'])}) | {best} | {_pct(r['accuracy'])} | "
            f"{_pct(r['balanced_accuracy'])} | {_num(r['mcc'])} | {_num(r.get('updown_auc'))} | {_pct(tr)} |"
        )
    lines += [
        "",
        "*Up/down AUC ranks P(UP) - P(DOWN) on rows whose label moved; a diagnostic of pure direction",
        "skill (the row subset is chosen by the outcome, so it is not a deployable accuracy).",
        "",
        "## All models",
        "",
        "| Horizon | Threshold | Model | Accuracy | Balanced acc | Macro F1 | MCC | ROC-AUC | Up/down AUC* |"
        " Brier | ECE | Coverage | Walk-forward | Test |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summary:
        e, m = s["experiment"], s["metrics"]
        for n, r in m.items():
            lines.append(
                f"| {e['horizon_minutes']}m | {100 * e['threshold']:.2f}% | {n} | {_pct(r['accuracy'])} | "
                f"{_pct(r['balanced_accuracy'])} | {_num(r['macro_f1'])} | {_num(r['mcc'])} | "
                f"{_num(r['roc_auc_ovr'])} | {_num(r.get('updown_auc'))} | {_num(r['brier'])} | "
                f"{_num(r['ece_top'])} | {_pct(r['coverage'])} | Phase 9 | not used |"
            )
    lines += [
        "",
        "## Selective UP/DOWN for the best model per horizon",
        "",
        "Predict only when max(P(UP), P(DOWN)) >= threshold and beats P(NEUTRAL); otherwise NO PREDICTION.",
        "Coverage is the share of all validation rows. Accuracy counts an actual NEUTRAL as wrong;",
        "sign accuracy compares with the sign of the realised return.",
        "",
        "| Horizon | Threshold | Model | P threshold | Predictions | Coverage | Accuracy | Sign accuracy |"
        " Balanced acc | MCC |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    by_h: dict[int, dict[str, Any]] = {}
    for s in summary:
        e, m = s["experiment"], s["metrics"]
        best = max((n for n in LEARNED_NAMES if n in m), key=lambda n: m[n]["mcc"])
        h = e["horizon_minutes"]
        if h not in by_h or m[best]["mcc"] > by_h[h]["mcc"]:
            by_h[h] = {"mcc": m[best]["mcc"], "e": e, "name": best, "sel": m[best]["selective"]}
    for h in sorted(by_h):
        b = by_h[h]
        for r in b["sel"]:
            lines.append(
                f"| {h}m | {100 * b['e']['threshold']:.2f}% | {b['name']} | {r['threshold']:.2f} | "
                f"{r['n_predictions']:,} | {_pct(r['coverage'])} | {_pct(r.get('accuracy'))} | "
                f"{_pct(r.get('sign_accuracy'))} | {_pct(r.get('balanced_accuracy'))} | "
                f"{_num(r.get('mcc'))} |"
            )
    lines.append("")
    return "\n".join(lines)
