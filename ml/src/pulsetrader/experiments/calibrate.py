"""Phase 10 runner: Platt and isotonic calibration of walk-forward predictions.

Input: a Phase 9 walk-forward experiment (out-of-fold predictions per fold, last fold = validation).
- The method is chosen without validation: calibrators are fit on F1..F(n-2) and scored on the last
  pre-validation fold; the lower Brier score wins (raw probabilities are a candidate too).
- Every method is then refit on all pre-validation folds and applied unchanged to validation.
Raw and calibrated probabilities are both stored. The test period is not used.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from pulsetrader.eval.calibration import CALIBRATORS, classwise_ece, reliability_curve
from pulsetrader.eval.multiclass import CLASSES, multiclass_report, selective_direction_table, to_index
from pulsetrader.experiments.classical import _new_dir

RUNNER_VERSION = "calibrate-v1"
KEYS = ("accuracy", "balanced_accuracy", "macro_f1", "mcc", "brier", "log_loss", "ece_top")


def _probs(df: pl.DataFrame) -> np.ndarray:
    p = df.select("p_down", "p_neutral", "p_up").to_numpy().astype(np.float64)
    return np.asarray(p / p.sum(axis=1, keepdims=True))


def _score(y: np.ndarray, p: np.ndarray, fret: np.ndarray | None = None) -> dict[str, Any]:
    r = multiclass_report(y, p)
    out: dict[str, Any] = {k: r[k] for k in KEYS}
    out["ece_classwise"] = classwise_ece(y, p)
    out["pred_distribution"] = r["pred_distribution"]
    if fret is not None:
        out["selective"] = selective_direction_table(y, p, fret)
        out["reliability_top"] = reliability_curve(y, p)
        out["reliability_by_class"] = {CLASSES[k]: reliability_curve(y, p, cls=k) for k in range(3)}
    return out


def calibrate(wf_dir: Path, out_root: Path) -> dict[str, Any]:
    exp_in = json.loads((wf_dir / "experiment.json").read_text())
    preds = pl.read_parquet(wf_dir / "predictions.parquet")
    folds = sorted(preds["fold"].unique().to_list(), key=lambda s: int(s[1:]))
    if len(folds) < 3:
        raise ValueError("need at least two pre-validation folds and a validation fold")
    val_f, sel_f, fit_sel = folds[-1], folds[-2], folds[:-2]
    y_all = to_index(preds["y_raw"].to_numpy())
    p_all = _probs(preds)
    fold = preds["fold"].to_numpy()

    def part(names: list[str]) -> np.ndarray:
        return np.isin(fold, names)

    # 1) choose the method on the last pre-validation fold
    m_fit, m_sel = part(fit_sel), part([sel_f])
    selection = {"raw": _score(y_all[m_sel], p_all[m_sel])}
    for name, cls in CALIBRATORS.items():
        c = cls().fit(y_all[m_fit], p_all[m_fit])
        selection[name] = _score(y_all[m_sel], c.transform(p_all[m_sel]))
    chosen = min(selection, key=lambda n: selection[n]["brier"])

    # 2) refit on every pre-validation fold, apply to validation
    m_oof, m_val = part(folds[:-1]), part([val_f])
    y_val, p_val = y_all[m_val], p_all[m_val]
    fret_val = preds.filter(pl.col("fold") == val_f)["fret"].to_numpy().astype(np.float64)
    validation = {"raw": _score(y_val, p_val, fret_val)}
    calibrators: dict[str, Any] = {}
    out_cols = {"raw": p_val}
    for name, cls in CALIBRATORS.items():
        c = cls().fit(y_all[m_oof], p_all[m_oof])
        pv = c.transform(p_val)
        validation[name] = _score(y_val, pv, fret_val)
        calibrators[name] = c.to_json()
        out_cols[name] = pv

    cfg = {
        "step": "calibration",
        "source_experiment": wf_dir.name,
        "label": exp_in["config"]["label"],
        "model": exp_in["config"]["model"],
        "tag": exp_in["config"]["tag"],
        "methods": ["raw", *CALIBRATORS],
        "selection": f"fit on {','.join(fit_sel)}, lowest Brier on {sel_f}",
        "final_fit": f"fit on {','.join(folds[:-1])}, applied to {val_f} (validation)",
    }
    key = hashlib.sha1(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:8]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    d = _new_dir(out_root, f"{stamp}-p10-calibration-{cfg['model']}-{cfg['label']}-{cfg['tag']}-{key}")
    exp = {
        "experiment_id": d.name,
        "runner_version": RUNNER_VERSION,
        "phase": 10,
        **{
            k: exp_in[k]
            for k in ("dataset_id", "dataset", "train_period", "validation_period", "test_period")
        },
        "config": cfg,
        "created_at": datetime.now(UTC).isoformat(),
    }
    result = {"chosen": chosen, "selection_fold": selection, "validation": validation}
    (d / "experiment.json").write_text(json.dumps(exp, indent=2, default=str))
    (d / "config.json").write_text(json.dumps(cfg, indent=2))
    (d / "metrics.json").write_text(json.dumps(result, indent=2, default=str))
    (d / "calibrators.json").write_text(json.dumps(calibrators))
    val_rows = preds.filter(pl.col("fold") == val_f).select("symbol", "ts", "y_raw", "fret")
    val_rows.with_columns(
        *[
            pl.Series(
                f"{'raw_probability' if n == 'raw' else n + '_probability'}_{c.lower()}",
                p[:, k],
                dtype=pl.Float32,
            )  # fmt: skip
            for n, p in out_cols.items()
            for k, c in enumerate(CLASSES)
        ]
    ).write_parquet(d / "predictions.parquet")
    (d / "report.md").write_text(render(exp, result))
    return {"experiment": exp, "result": result, "dir": str(d)}


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.1f}%"


def _num(x: float | None, nd: int = 4) -> str:
    return "–" if x is None else f"{x:.{nd}f}"


def metric_table(scores: dict[str, dict[str, Any]], chosen: str | None = None) -> list[str]:
    lines = [
        "| Method | Brier | Log loss | ECE (top class) | ECE (classwise) | Accuracy | Balanced acc | MCC |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for n, s in scores.items():
        mark = " (chosen)" if n == chosen else ""
        lines.append(
            f"| {n}{mark} | {_num(s['brier'])} | {_num(s['log_loss'])} | {_num(s['ece_top'])} | "
            f"{_num(s['ece_classwise'])} | {_pct(s['accuracy'])} | {_pct(s['balanced_accuracy'])} | "
            f"{_num(s['mcc'], 3)} |"
        )
    return lines


def render(exp: dict[str, Any], res: dict[str, Any]) -> str:
    c = exp["config"]
    v = res["validation"]
    lines = [
        f"# {exp['experiment_id']}",
        "",
        f"Calibration of {c['model']} ({c['tag']}) on `{c['label']}`. Method selection: {c['selection']}. "
        f"Final: {c['final_fit']}. Test period not used.",
        "",
        "Selection fold:",
        "",
        *metric_table(res["selection_fold"], res["chosen"]),
        "",
        "Validation:",
        "",
        *metric_table(v, res["chosen"]),
        "",
        "Reliability (top-class confidence vs accuracy, validation):",
        "",
        "| Bin | Rows | Raw: predicted / observed | Platt: predicted / observed |"
        " Isotonic: predicted / observed |",
        "|---|---|---|---|---|",
    ]
    curves = {n: {(b["bin_low"]): b for b in v[n]["reliability_top"]} for n in v}
    for lo in sorted(set().union(*[set(cv) for cv in curves.values()])):
        cells = []
        for n in ("raw", "platt", "isotonic"):
            b = curves.get(n, {}).get(lo)
            cells.append(f"{_pct(b['mean_predicted'])} / {_pct(b['observed'])}" if b else "–")
        n_rows = curves["raw"].get(lo, {}).get("n")
        lines.append(f"| {lo:.1f}–{lo + 0.1:.1f} | {n_rows if n_rows else '–'} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "Selective UP/DOWN on validation after calibration (chosen method):",
        "",
        "| P threshold | Predictions | Coverage | Accuracy | Sign accuracy | MCC |",
        "|---|---|---|---|---|---|",
    ]
    for s in v[res["chosen"]]["selective"]:
        lines.append(
            f"| {s['threshold']:.2f} | {s['n_predictions']:,} | {_pct(s['coverage'])} | "
            f"{_pct(s.get('accuracy'))} | "
            f"{_pct(s.get('sign_accuracy'))} | {_num(s.get('mcc'), 3)} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_summary(rows: list[dict[str, Any]]) -> str:
    e0 = rows[0]["experiment"]
    lines = [
        "# Phase 10 — probability calibration (validation)",
        "",
        f"Dataset `{e0['dataset_id']}`. Inputs: Phase 9 walk-forward out-of-fold predictions. Platt and",
        "isotonic (one-vs-rest, renormalised) are chosen on the last pre-validation fold (lowest Brier),",
        "refit on all pre-validation folds and applied unchanged to validation "
        f"({e0['validation_period']['start']}..{e0['validation_period']['end']}). Test period not used.",
        "",
    ]
    for r in rows:
        c, res = r["experiment"]["config"], r["result"]
        lines += [f"## {c['model']} ({c['tag']}) — `{c['label']}`", "",
                  f"Chosen method: **{res['chosen']}**.", "",
                  *metric_table(res["validation"], res["chosen"]), ""]  # fmt: skip
    lines.append("")
    return "\n".join(lines)


def run(out_root: Path, patterns: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = []
    for pat in patterns:
        hits = sorted(d for d in out_root.glob(f"*-p9-{pat}-*") if (d / "predictions.parquet").exists())
        if not hits:
            raise FileNotFoundError(f"no Phase 9 walk-forward experiment matches {pat}")
        rows.append(calibrate(hits[-1], out_root))
    return rows


DEFAULT_INPUTS = (
    "wf-expanding-lightgbm-y_1m_5bp-tuned",
    "wf-expanding-lightgbm-y_5m_10bp-tuned",
    "wf-expanding-lightgbm-y_1m_5bp-default",
    "wf-expanding-lightgbm-y_5m_10bp-default",
)
