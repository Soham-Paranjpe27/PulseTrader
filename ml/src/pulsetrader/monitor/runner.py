"""Phase 19 on real data: build monitoring references per registry model and measure drift.

`build_references` writes data/monitoring/reference/<model>@v<version>.json from the training split and
the walk-forward folds before validation. `evaluate_validation` then runs the monitor over the
validation period month by month and week by week, exactly as it would run over live windows: the
validation rows are what the live system produces (Phase 17 parity: same features, same
probabilities), with outcomes from the research labels (Phase 18: same as live outcomes). The test
period is never read.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from pulsetrader.eval.multiclass import to_index
from pulsetrader.experiments.robustness import MARKET_INDEX, daily_regimes
from pulsetrader.labels.labels import label_name
from pulsetrader.monitor.drift import Reference, build_reference, drift_report, window_bounds
from pulsetrader.serve.models import ModelServer

TRAIN_SAMPLE_EVERY = 8  # every 8th training row (deterministic) keeps the reference build light


def reference_dir(data_root: Path) -> Path:
    return data_root / "monitoring" / "reference"


def reference_path(data_root: Path, key: str) -> Path:
    return reference_dir(data_root) / f"{key}.json"


def _periods(ds_dir: Path) -> dict[str, tuple[date, date]]:
    m = json.loads((ds_dir / "dataset_manifest.json").read_text())
    return {p["name"]: (date.fromisoformat(p["start"]), date.fromisoformat(p["end"])) for p in m["periods"]}


def _regimes(data_root: Path, train_end: date) -> pl.DataFrame:
    bars = pl.read_parquet(data_root / "reference" / "day_bars.parquet").filter(
        pl.col("symbol") == MARKET_INDEX
    )
    return daily_regimes(bars, train_end).drop("_cuts")


def live_monitor(data_root: Path, keys: list[str], dataset: str = "core100_s5") -> Any:
    """The live pipeline's drift monitor: references for `keys` plus the daily regime table."""
    from pulsetrader.monitor.live import LiveDriftMonitor

    per = _periods(data_root / "datasets" / dataset)
    return LiveDriftMonitor.from_dir(reference_dir(data_root), keys, _regimes(data_root, per["train"][1]))


def _wf(data_root: Path, model: Any) -> tuple[pl.DataFrame, Path]:
    d = data_root / "experiments" / model.record.source_experiments["walk_forward"]
    wf = pl.read_parquet(d / "predictions.parquet")
    wf = wf.with_columns(
        pl.col("ts").dt.convert_time_zone("Asia/Kolkata"), pl.Series("y", to_index(wf["y_raw"].to_numpy()))
    )
    return wf, d


def build_references(data_root: Path, dataset: str = "core100_s5") -> list[dict[str, Any]]:
    ds_dir = data_root / "datasets" / dataset
    per = _periods(ds_dir)
    tr_lo, tr_hi = per["train"]
    val_lo = per["validation"][0]
    srv = ModelServer(data_root / "registry")
    models = sorted(srv.models.values(), key=lambda m: m.record.key)
    if not models:
        raise RuntimeError(f"no servable models: {srv.load_errors}")
    feats = sorted({f for m in models for f in m.features})
    train = (
        pl.scan_parquet(ds_dir / "part-*.parquet")
        .filter(pl.col("trade_date").is_between(tr_lo, tr_hi))
        .select("ts", "trade_date", *feats)
        .with_row_index("_i")
        .filter(pl.col("_i") % TRAIN_SAMPLE_EVERY == 0)
        .collect()
    )
    regimes = _regimes(data_root, tr_hi)
    train_regimes = regimes.filter(pl.col("trade_date").is_between(tr_lo, tr_hi))
    reference_dir(data_root).mkdir(parents=True, exist_ok=True)
    out = []
    for m in models:
        wf, d = _wf(data_root, m)
        ref_preds = wf.filter(pl.col("ts").dt.date() < val_lo)  # folds before validation only
        imp_file = d / "feature_importance.json"
        imp = json.loads(imp_file.read_text()) if imp_file.exists() else {}
        ref = build_reference(
            m.record.key, train, m.features, imp, ref_preds, train_regimes,
            {"dataset": dataset, "train_period": [str(tr_lo), str(tr_hi)],
             "train_sample_every": TRAIN_SAMPLE_EVERY,
             "prediction_source": m.record.source_experiments["walk_forward"],
             "prediction_period": [str(ref_preds["ts"].min()), str(ref_preds["ts"].max())],
             "label": label_name(int(m.meta["horizon"]), float(m.meta["threshold"]))},
        )  # fmt: skip
        reference_path(data_root, m.record.key).write_text(json.dumps(ref.to_json(), default=str))
        out.append({"model": m.record.key, "folds": ref.folds, "regime_mix": ref.regime_mix,
                    "train_rows": train.height, "prediction_rows": ref_preds.height})  # fmt: skip
    return out


def evaluate_validation(data_root: Path, dataset: str = "core100_s5") -> dict[str, Any]:
    ds_dir = data_root / "datasets" / dataset
    per = _periods(ds_dir)
    val_lo, val_hi = per["validation"]
    srv = ModelServer(data_root / "registry")
    models = sorted(srv.models.values(), key=lambda m: m.record.key)
    regimes = _regimes(data_root, per["train"][1])
    res: dict[str, Any] = {"validation_period": [str(val_lo), str(val_hi)], "models": []}
    for m in models:
        ref = Reference.load(reference_path(data_root, m.record.key))
        val = (
            pl.scan_parquet(ds_dir / "part-*.parquet")
            .filter(pl.col("trade_date").is_between(val_lo, val_hi))
            .select("symbol", "ts", "trade_date", *m.features)
            .collect()
            .with_columns(pl.col("ts").dt.convert_time_zone("Asia/Kolkata"))
        )
        wf, _ = _wf(data_root, m)
        wf = wf.filter(pl.col("ts").dt.date().is_between(val_lo, val_hi))
        rows = val.join(wf.select("symbol", "ts", "y", "p_down", "p_neutral", "p_up"), on=["symbol", "ts"])
        windows = []
        for freq, fmt in (("month", "%Y-%m"), ("week", "%G-W%V")):
            keyed = rows.with_columns(pl.col("ts").dt.strftime(fmt).alias("_w"))
            for w in sorted(keyed["_w"].unique().to_list()):
                g = keyed.filter(pl.col("_w") == w)
                proba = g.select("p_down", "p_neutral", "p_up").to_numpy().astype(np.float64)
                y = g["y"].to_numpy()
                ok = y >= 0
                days = g["trade_date"].unique()
                rep = drift_report(
                    ref, g.select(m.features), proba, y[ok], proba[ok],
                    regimes.filter(pl.col("trade_date").is_in(days.implode())),
                    {"kind": freq, "label": w, **window_bounds(g["ts"])},
                    days.len(),
                )  # fmt: skip
                windows.append(rep)
        res["models"].append({"model": m.record.key, "rows": rows.height, "reference_folds": ref.folds,
                              "windows": windows})  # fmt: skip
    return res


def _f(x: Any, nd: int = 3) -> str:
    return "–" if x is None else f"{x:.{nd}f}"


def render(refs: list[dict[str, Any]], res: dict[str, Any]) -> str:
    lines = [
        "# Phase 19: drift monitoring on real data",
        "",
        "References: features from the training split (2022-01-03..2024-11-04, every "
        f"{TRAIN_SAMPLE_EVERY}th row); predictions, accuracy and calibration from the model's walk-forward "
        "folds before validation (out-of-sample); regime mix from training-period days. The monitor then "
        f"ran over the validation period {res['validation_period'][0]}..{res['validation_period'][1]} "
        "month by month and week by week, as it would over live windows (validation rows equal live "
        "features and probabilities, Phase 17; outcomes equal live outcomes, Phase 18). "
        "Test period not read.",
        "",
        "Thresholds are calibrated per window length (day, week, month) on historical windows of the same "
        "length: WARN when a window is more extreme than 95% of them, DRIFT beyond 99% (MCC and accuracy: "
        "below the 5% / 1% quantiles of out-of-sample fold windows; ECE: above the 95% / 99% quantiles; "
        "PSI: above the 95% / 99% quantiles of training windows, at least 0.1 / 0.25). "
        "MODEL_DRIFT_DETECTED = accuracy or calibration DRIFT, or feature and prediction DRIFT together. "
        "The model is never replaced automatically.",
        "",
        "## Reference folds (walk-forward, out-of-sample, raw probabilities)",
        "",
        "| model | fold | period | rows | accuracy | balanced acc | MCC | ECE top |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in refs:
        for f in r["folds"]:
            lines.append(
                f"| {r['model']} | {f['fold']} | {f['start'][:10]}..{f['end'][:10]} | {f['n']} | "
                f"{_f(f['accuracy'])} | {_f(f['balanced_accuracy'])} | {_f(f['mcc'])} | {_f(f['ece_top'])} |"
            )
    for mres in res["models"]:
        months = [w for w in mres["windows"] if w["window"]["kind"] == "month"]
        weeks = [w for w in mres["windows"] if w["window"]["kind"] == "week"]
        lines += [
            "",
            f"## {mres['model']}: monthly windows ({mres['rows']} validation rows)",
            "",
            "Each cell: value (WARN / DRIFT threshold for a window of that length).",
            "",
            "| month | days | status | MCC | accuracy | ECE top | feature weighted PSI | prediction PSI | "
            "regime PSI | most shifted features (PSI) |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]

        def cell(v: Any, thr: Any, nd: int = 3) -> str:
            return f"{_f(v, nd)} ({_f(thr[0], nd)} / {_f(thr[1], nd)})" if thr else _f(v, nd)

        for w in months:
            c = w["components"]
            acc, cal, fe, pr, rg = c["accuracy"], c["calibration"], c["feature"], c["prediction"], c["regime"]
            win = acc.get("window", {})
            ch = acc.get("checks", {})
            low = {k: (ch[k]["warn_below"], ch[k]["drift_below"]) for k in ch}
            top = ", ".join(f"{t['feature']} {t['psi']:.2f}" for t in fe.get("top", [])[:3])
            lines.append(
                f"| {w['window']['label']} | {w['window']['days']} | {w['status']} | "
                f"{cell(win.get('mcc'), low.get('mcc'))} | "
                f"{cell(win.get('accuracy'), low.get('accuracy'))} | "
                f"{cell(cal.get('ece_top'), cal.get('thresholds'))} | "
                f"{cell(fe.get('importance_weighted_psi'), fe.get('thresholds'))} | "
                f"{cell(pr.get('max_psi'), pr.get('thresholds'))} | "
                f"{cell(rg.get('psi'), rg.get('thresholds'), 2)} | "
                f"{top} |"
            )
        counts: dict[str, int] = {}
        for w in weeks:
            counts[w["status"]] = counts.get(w["status"], 0) + 1
        comp_counts: dict[str, dict[str, int]] = {}
        for w in weeks:
            for k, v in w["components"].items():
                comp_counts.setdefault(k, {}).setdefault(v["status"], 0)
                comp_counts[k][v["status"]] += 1
        lines += [
            "",
            f"Weekly windows ({len(weeks)}): "
            + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
            + ".",
            "Per component (weeks): " + "; ".join(
                f"{k}: " + ", ".join(f"{s} {n}" for s, n in sorted(v.items())) for k, v in comp_counts.items()
            ) + ".",
        ]  # fmt: skip
    return "\n".join(lines) + "\n"
