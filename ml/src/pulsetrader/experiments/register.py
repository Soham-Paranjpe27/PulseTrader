"""Phase 13 runner: export walk-forward models as registry artifacts and evaluate promotion gates.

For each Phase 9 walk-forward experiment:
1. Refit the model of the validation window exactly as the walk-forward did (same rows, purge, inner
   early-stopping split, preprocessor fit on training rows, parameters, seed) and check that it
   reproduces the stored validation predictions (`reproducible` gate).
2. Save the artifact: LightGBM booster, preprocessor, feature schema/order, Phase 10 calibrator.
3. Evaluate every promotion gate from stored evidence (leakage audit, data quality report, Phase 9
   walk-forward, Phase 10 calibration, Phase 12 backtest). The test period has not been used, so
   `test_passed` and `shadow_passed` are NOT_RUN.
4. Register the version as EXPERIMENT and move it to CANDIDATE only if every CANDIDATE gate passed.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from pulsetrader.eval.multiclass import CLASSES
from pulsetrader.experiments import optimize as opt
from pulsetrader.registry.registry import (
    FAILED,
    NOT_RUN,
    PASSED,
    Gate,
    ModelRecord,
    Registry,
    RegistryError,
    Status,
    gate,
)

log = logging.getLogger(__name__)
RUNNER_VERSION = "register-v1"
REPRO_TOL = 1e-4
MAX_ECE = 0.05
MAX_WF_MCC_STD = 0.05
MIN_VAL_MCC = 0.05
MAX_FLAGGED_FRAC = 1e-3


def latest_dir(out_root: Path, pattern: str) -> Path:
    hits = sorted(d for d in out_root.glob(pattern) if (d / "metrics.json").exists())
    if not hits:
        raise FileNotFoundError(f"no experiment matches {pattern}")
    return hits[-1]


# gates ---------------------------------------------------------------------------------------


def leakage_gate(reports: Path, dataset_id: str) -> dict[str, Any]:
    f = reports / "leakage_audit_real.json"
    if not f.exists():
        return gate(NOT_RUN, "reports/leakage_audit_real.json missing")
    d = json.loads(f.read_text())
    ok = bool(d.get("passed")) and d.get("dataset_id") == dataset_id
    return gate(PASSED if ok else FAILED, f"leakage audit {d.get('audit_version')} on {d.get('dataset_id')}")


def data_quality_gate(reports: Path) -> dict[str, Any]:
    f = reports / "data_quality_report.md"
    if not f.exists():
        return gate(NOT_RUN, "reports/data_quality_report.md missing")
    txt = f.read_text()
    raw = re.search(r"\| raw rows \| (\d+) \|", txt)
    flags = [int(n) for n in re.findall(r"\| f_\w+ \| (\d+) \|", txt)]
    if raw is None or not flags:
        return gate(NOT_RUN, "data quality report has no row counts")
    frac = sum(flags) / int(raw.group(1))
    ok = frac <= MAX_FLAGGED_FRAC
    return gate(
        PASSED if ok else FAILED,
        f"flagged raw rows {sum(flags):,} of {int(raw.group(1)):,} ({frac:.2e}); flagged rows are "
        f"excluded from canonical; limit {MAX_FLAGGED_FRAC:g}",
        flagged_fraction=frac,
    )


def validation_gate(m: dict[str, Any]) -> dict[str, Any]:
    v = m["validation"]
    mom = v["baselines"]["momentum_mcc"]
    ok = v["mcc"] >= MIN_VAL_MCC and v["mcc"] > mom and v["balanced_accuracy"] > 1 / 3
    return gate(
        PASSED if ok else FAILED,
        f"validation MCC {v['mcc']:.3f} (min {MIN_VAL_MCC}, momentum {mom:.3f}), balanced accuracy "
        f"{v['balanced_accuracy']:.3f} (chance 0.333), accuracy {v['accuracy']:.3f} "
        f"(majority {v['baselines']['majority_accuracy']:.3f})",
    )


def walk_forward_gate(m: dict[str, Any]) -> dict[str, Any]:
    folds = m["per_fold"]
    mccs = [f["mcc"] for f in folds]
    std = float(np.std(mccs))
    beats = m["beats_momentum_folds"]
    ok = min(mccs) > 0 and beats == len(folds) and std <= MAX_WF_MCC_STD
    return gate(
        PASSED if ok else FAILED,
        f"{len(folds)} folds: MCC min {min(mccs):.3f}, max {max(mccs):.3f}, std {std:.3f} "
        f"(max {MAX_WF_MCC_STD}); beats momentum in {beats}/{len(folds)}",
    )


def calibration_gate(c: dict[str, Any]) -> dict[str, Any]:
    ch = c["chosen"]
    ece = c["validation"][ch]["ece_classwise"]
    ok = ece <= MAX_ECE
    return gate(
        PASSED if ok else FAILED,
        f"{ch} calibration, validation classwise ECE {ece:.3f} (max {MAX_ECE}); "
        f"raw {c['validation']['raw']['ece_classwise']:.3f}",
    )


def backtest_gate(b: dict[str, Any]) -> dict[str, Any]:
    g, bh = b["model_gated|costs"], b["buy_and_hold|costs"]
    ok = g["total_return"] > 0 and g["total_return"] > bh["total_return"] and (g["sharpe"] or 0) > 0
    return gate(
        PASSED if ok else FAILED,
        f"gated strategy after costs: total return {g['total_return']:.1%}, Sharpe {g['sharpe']:.2f}, "
        f"max DD {g['max_drawdown']:.1%}; buy-and-hold {bh['total_return']:.1%}",
    )


# artifact export -----------------------------------------------------------------------------


def export_artifact(
    wf_dir: Path,
    cal_dir: Path,
    data_root: Path,
    art_dir: Path,
    dataset: str,
    min_train_frac: float = 0.4,
) -> dict[str, Any]:
    exp = json.loads((wf_dir / "experiment.json").read_text())
    cfg = exp["config"]
    h, thr, label = int(cfg["horizon"]), float(cfg["threshold"]), cfg["label"]
    if cfg["model"] != "lightgbm" or cfg["scheme"] != "expanding":
        raise RegistryError("only expanding-window LightGBM walk-forward runs are exportable")
    dev = opt.load_dev(
        data_root, h, (thr,), dataset=dataset, n_pre=len(exp["folds"]) - 1,
        embargo_minutes=exp["embargo_minutes"], train_every=exp["train_every"],
        min_train_frac=min_train_frac,
    )  # fmt: skip
    val_fold = dev.folds[-1]
    stored = [(f["name"], f["start"], f["end"]) for f in exp["folds"]]
    if [(f.name, str(f.start), str(f.end)) for f in dev.folds] != stored:
        raise RegistryError(f"fold layout differs from {wf_dir.name}")
    fd = dev.fold_data(val_fold, "expanding", tuple(cfg["features"]))
    model, proba = opt.fit_predict(fd, label, "lightgbm", cfg["params"])
    art_dir.mkdir(parents=True, exist_ok=True)
    model.model.save_model(str(art_dir / "model.txt"), num_iteration=model.best_iteration)
    fd.preprocessor.save(art_dir / "preprocessor.json")
    (art_dir / "features.json").write_text(
        json.dumps({"feature_version": exp["feature_version"], "features": cfg["features"]}, indent=1)
    )
    cal = json.loads((cal_dir / "calibrators.json").read_text())
    chosen = json.loads((cal_dir / "metrics.json").read_text())["chosen"]
    (art_dir / "calibrator.json").write_text(
        json.dumps({"method": chosen, "source_experiment": cal_dir.name, **cal.get(chosen, {})})
    )

    # reproducibility: refit vs stored predictions, and reloaded booster vs in-memory model
    import lightgbm as lgb

    stored_p = pl.read_parquet(wf_dir / "predictions.parquet").filter(pl.col("fold") == val_fold.name)
    ours = fd.ev.select("symbol", "ts").with_columns(
        *[pl.Series(f"q_{c.lower()}", proba[:, k]) for k, c in enumerate(CLASSES)]
    )
    j = ours.join(stored_p, on=["symbol", "ts"], how="inner")
    diff = float(
        np.max(np.abs(j.select("q_down", "q_neutral", "q_up").to_numpy()
                      - j.select("p_down", "p_neutral", "p_up").to_numpy()))
    ) if j.height else float("inf")  # fmt: skip
    booster = lgb.Booster(model_file=str(art_dir / "model.txt"))
    n_chk = min(5000, fd.X_ev.shape[0])
    reload_diff = float(np.max(np.abs(booster.predict(fd.X_ev[:n_chk]) - proba[:n_chk])))
    rows_match = j.height == stored_p.height == ours.height
    ok = rows_match and diff <= REPRO_TOL and reload_diff <= 1e-9
    repro = gate(
        PASSED if ok else FAILED,
        f"refit reproduces {j.height:,}/{stored_p.height:,} stored validation predictions, max abs diff "
        f"{diff:.2e} (tol {REPRO_TOL:g}); saved model reload diff {reload_diff:.1e}",
    )
    info = {
        "label": label,
        "horizon": h,
        "threshold": thr,
        "best_iteration": model.best_iteration,
        "fit_rows": fd.fit.height,
        "fit_period": fd.preprocessor.fit_period,
        "early_stopping_rows": fd.es.height,
        "calibration": chosen,
        "dev_info": dev.info(),
        "params": cfg["params"],
    }
    (art_dir / "model_meta.json").write_text(json.dumps({"runner_version": RUNNER_VERSION, **info},
                                                        indent=1, default=str))  # fmt: skip
    opt._free(dev)
    return {"gate": repro, "info": info}


# registration --------------------------------------------------------------------------------


def register_from_walk_forward(
    wf_dir: Path,
    cal_dir: Path,
    bt_dir: Path,
    data_root: Path,
    reports: Path,
    registry: Registry,
    dataset: str = "core100_s5",
) -> ModelRecord:
    exp = json.loads((wf_dir / "experiment.json").read_text())
    cfg = exp["config"]
    m = json.loads((wf_dir / "metrics.json").read_text())
    c = json.loads((cal_dir / "metrics.json").read_text())
    b = json.loads((bt_dir / "metrics.json").read_text())
    model_id = f"{cfg['model']}-{cfg['label']}-{cfg['tag']}"
    version = registry.next_version(model_id)
    art = registry.artifact_dir(model_id, version)
    out = export_artifact(wf_dir, cal_dir, data_root, art, dataset)
    v = m["validation"]
    metric_keys = ("accuracy", "balanced_accuracy", "macro_f1", "mcc", "roc_auc_ovr", "brier",
                   "ece_top", "coverage", "n")  # fmt: skip
    rec = ModelRecord(
        model_id=model_id,
        version=version,
        task=cfg["label"],
        model_type=cfg["model"],
        dataset_version=exp["dataset_id"],
        feature_version=exp["feature_version"],
        label_version=exp["label_version"],
        training_period={**exp["train_period"], "fit_period": out["info"]["fit_period"]},
        validation_period=exp["validation_period"],
        test_period=exp["test_period"],
        hyperparameters={**cfg["params"], "best_iteration": out["info"]["best_iteration"]},
        metrics={
            "validation": {k: v[k] for k in metric_keys if k in v},
            "validation_baselines": v["baselines"],
            "validation_calibrated": {
                k: c["validation"][c["chosen"]][k]
                for k in ("accuracy", "balanced_accuracy", "mcc", "brier", "ece_classwise")
            },
            "walk_forward_pre_validation": m["summary_pre_validation"],
            "selective": v.get("selective"),
        },
        backtest_metrics={
            k: {
                f: b[k][f]
                for f in (
                    "total_return",
                    "cagr",
                    "sharpe",
                    "sortino",
                    "calmar",
                    "max_drawdown",
                    "trades",
                    "win_rate",
                    "profit_factor",
                    "avg_trade_return_bp",
                    "total_costs",
                )
            }
            for k in b
        },  # fmt: skip
        calibration_version=f"calibrate-v1:{c['chosen']}",
        artifact_path=str(art.relative_to(registry.root)),
        source_experiments={
            "walk_forward": wf_dir.name,
            "calibration": cal_dir.name,
            "backtest": bt_dir.name,
        },
        notes=[
            "Decisions use the raw tuned probabilities (argmax); calibrated probabilities are for display "
            "(Phase 10: calibrated argmax lowers MCC).",
            "Accuracy target (70-80%) not reached; spec section 39 verdict NOT VERIFIED.",
        ],
    )
    registry.register(rec, reason=f"exported from {wf_dir.name}")
    gates = {
        Gate.NO_LEAKAGE.value: leakage_gate(reports, exp["dataset_id"]),
        Gate.DATA_QUALITY.value: data_quality_gate(reports),
        Gate.VALIDATION.value: validation_gate(m),
        Gate.WALK_FORWARD.value: walk_forward_gate(m),
        Gate.CALIBRATION.value: calibration_gate(c),
        Gate.REPRODUCIBLE.value: out["gate"],
        Gate.BACKTEST.value: backtest_gate(b),
        Gate.TEST.value: gate(NOT_RUN, "test period untouched until model development is finished"),
        Gate.SHADOW.value: gate(NOT_RUN, "no live shadow run yet (Phase 17-18)"),
    }
    rec = registry.update_gates(model_id, version, gates)
    missing = rec.missing_gates(Status.CANDIDATE)
    if not missing:
        rec = registry.transition(model_id, version, Status.CANDIDATE, "all CANDIDATE gates passed")
    else:
        log.info("%s stays EXPERIMENT; failed gates %s", rec.key, missing)
    return rec


def run(
    data_root: Path, reports: Path, patterns: tuple[str, ...], dataset: str = "core100_s5"
) -> list[ModelRecord]:
    out_root = data_root / "experiments"
    reg = Registry(data_root / "registry")
    recs = []
    for pat in patterns:  # e.g. lightgbm-y_5m_10bp-tuned
        wf = latest_dir(out_root, f"*-p9-wf-expanding-{pat}-*")
        cal = latest_dir(out_root, f"*-p10-calibration-{pat}-*")
        bt = latest_dir(out_root, f"*-p12-backtest-{pat}-*")
        recs.append(register_from_walk_forward(wf, cal, bt, data_root, reports, reg, dataset))
    return recs


DEFAULT_INPUTS = ("lightgbm-y_1m_5bp-tuned", "lightgbm-y_5m_10bp-tuned")


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.1f}%"


def render(models: list[ModelRecord]) -> str:
    lines = [
        "# Phase 13 — model registry",
        "",
        "Registry: `data/registry/registry.json` (registry-v1); artifacts under `data/registry/artifacts/`.",
        "Statuses: EXPERIMENT -> CANDIDATE -> SHADOW -> PRODUCTION -> RETIRED, or REJECTED. A transition",
        "needs every gate for its target status PASSED (docs/model-registry.md). Test period not used.",
        "",
        "| Model | Version | Status | Task | Val accuracy | Val balanced acc | Val MCC | Coverage | "
        "Backtest (gated, after costs) | Accuracy gate |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in models:
        v = m.metrics["validation"]
        bt = m.backtest_metrics.get("model_gated|costs", {})
        lines.append(
            f"| {m.model_id} | v{m.version} | **{m.status}** | {m.task} | {_pct(v['accuracy'])} | "
            f"{_pct(v['balanced_accuracy'])} | {v['mcc']:.3f} | {_pct(v.get('coverage'))} | "
            f"{_pct(bt.get('total_return'))} | {m.accuracy_gate} |"
        )
    for m in models:
        lines += ["", f"## {m.key} — {m.status}", "", "| Gate | Status | Evidence |", "|---|---|---|"]
        for g, r in m.gates.items():
            lines.append(f"| {g} | {r['status']} | {r['evidence']} |")
        lines += ["", "Blocked from SHADOW by: " + (", ".join(m.missing_gates(Status.SHADOW)) or "nothing")]
        lines += ["", "History:", ""]
        lines += [f"- {h['at']}: {h['from']} -> {h['to']} ({h['reason']})" for h in m.history]
    lines.append("")
    return "\n".join(lines)
