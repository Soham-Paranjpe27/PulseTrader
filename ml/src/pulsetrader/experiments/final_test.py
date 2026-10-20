"""Final evaluation of the frozen registry models on the held-out test period (run once).

The user approved a single run on 2026-10-19. Rules, fixed before the run:
- The registered artifacts are used exactly as they are (verified SHA-256, no refit, no retuning).
  Decisions use the serving logic (`LoadedModel.score`): raw argmax for the full-coverage view, the
  Phase 12 confidence gate plus the abstain rules for the selective view.
- `test_passed` uses the validation-gate rule: MCC >= 0.05, MCC above the momentum rule on the same
  rows, balanced accuracy above chance (1/3).
- The run refuses to start when any model's test period is already marked used or the report
  exists, so it cannot be repeated by accident. Nothing measured here may feed back into model
  choices; a new model needs a new untouched period (knowledge.md).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from sklearn import metrics as skm

from pulsetrader.backtest.engine import (
    ZERO_COSTS,
    BacktestConfig,
    buy_and_hold,
    metrics,
    plan_trades,
    simulate,
)
from pulsetrader.eval.calibration import classwise_ece
from pulsetrader.eval.multiclass import (
    CLASSES,
    DOWN,
    UP,
    multiclass_report,
    selective_direction_table,
    to_index,
)
from pulsetrader.experiments.backtest import _signals, load_bars, round_trip_bp
from pulsetrader.experiments.classical import MOMENTUM_COL
from pulsetrader.labels.labels import label_name
from pulsetrader.models.classical import momentum_classes, rule_proba
from pulsetrader.registry.registry import FAILED, PASSED, Registry, gate
from pulsetrader.serve.models import load_model

RUNNER_VERSION = "final-test-v1"
MODELS = ("lightgbm-y_1m_5bp-tuned", "lightgbm-y_5m_10bp-tuned")
MIN_TEST_MCC = 0.05
REPORT = "final_test"


class AlreadyRun(RuntimeError):
    pass


def _mcc_ba(y: np.ndarray, p: np.ndarray) -> tuple[float | None, float | None]:
    if len(y) == 0:
        return None, None
    return float(skm.matthews_corrcoef(y, p)), float(skm.balanced_accuracy_score(y, p))


def _calls(y: np.ndarray, sc: dict[str, np.ndarray], fret: np.ndarray, cost_bp: float) -> dict[str, Any]:
    """Selective view: rows the service would answer UP or DOWN."""
    m = sc["reason"] == ""
    k = int(m.sum())
    reasons = {r: int(np.sum(sc["reason"] == r)) for r in np.unique(sc["reason"]) if r}
    out: dict[str, Any] = {"calls": k, "coverage": k / len(y) if len(y) else 0.0, "abstained": reasons}
    if k:
        yt, pt = y[m], sc["cls"][m]
        sign = np.where(pt == UP, 1.0, -1.0)
        gross = float(np.mean(sign * fret[m]) * 1e4)
        mcc, ba = _mcc_ba(yt, pt)
        out.update(
            accuracy=float(np.mean(yt == pt)),
            balanced_accuracy=ba,
            mcc=mcc,
            sign_accuracy=float(np.mean(sign * fret[m] > 0)),
            share_up=float(np.mean(pt == UP)),
            gross_bp_per_call=gross,
            net_bp_per_call=gross - cost_bp,
        )
    return out


def _monthly(df: pl.DataFrame, y: np.ndarray, pred: np.ndarray, calls: np.ndarray) -> list[dict[str, Any]]:
    month = df["trade_date"].dt.strftime("%Y-%m").to_numpy()
    rows = []
    for mo in sorted(set(month)):
        m = month == mo
        mcc, ba = _mcc_ba(y[m], pred[m])
        rows.append({"month": mo, "n": int(m.sum()), "accuracy": float(np.mean(y[m] == pred[m])),
                     "balanced_accuracy": ba, "mcc": mcc, "calls": int(calls[m].sum())})  # fmt: skip
    return rows


def _backtest(
    data_root: Path, df: pl.DataFrame, sc: dict[str, np.ndarray], h: int, thr: float, start: date, end: date
) -> dict[str, Any]:
    pred = sc["cls"]
    model_dir = np.where(pred == UP, 1, np.where(pred == DOWN, -1, 0))
    gated = np.where(sc["reason"] == "", model_dir, 0)
    past = df[MOMENTUM_COL[h]].to_numpy().astype(np.float64)
    mom = momentum_classes(np.nan_to_num(past, nan=0.0), thr)
    mom_dir = np.where(mom == UP, 1, np.where(mom == DOWN, -1, 0))
    strategies = {
        "model": (model_dir, sc["p_dir"]),
        "model_gated": (gated, sc["p_dir"]),
        "momentum": (mom_dir, np.abs(np.nan_to_num(past))),
    }
    symbols = sorted(df["symbol"].unique().to_list())
    bars = load_bars(data_root, symbols, start, end)
    days = sorted({int(d) for b in bars.values() for d in np.unique(b.day)})
    base = BacktestConfig(horizon=h)
    res: dict[str, Any] = {}
    for name, (direction, prio) in strategies.items():
        sig = _signals(df, direction, prio)
        for cname, costs in (("costs", base.costs), ("zero_costs", ZERO_COSTS)):
            cfg = BacktestConfig(horizon=h, costs=costs)
            m = metrics(simulate(plan_trades(sig, bars, cfg), cfg), cfg, days)
            m["signals"] = sig.height
            res[f"{name}|{cname}"] = m
    day_bars = pl.read_parquet(data_root / "reference" / "day_bars.parquet")
    for cname, costs in (("costs", base.costs), ("zero_costs", ZERO_COSTS)):
        res[f"buy_and_hold|{cname}"] = buy_and_hold(
            day_bars, symbols, start, end, BacktestConfig(horizon=h, costs=costs)
        )
    return res


def evaluate_model(data_root: Path, reg: Registry, model_id: str, test: pl.DataFrame,
                   train_major: dict[str, int], start: date, end: date) -> dict[str, Any]:  # fmt: skip
    rec = reg.get(model_id)
    lm = load_model(reg, rec)  # refuses an artifact whose files changed
    h, thr = int(lm.meta["horizon"]), float(lm.meta["threshold"])
    label = label_name(h, thr)
    df = test.filter(pl.col(label).is_not_null() & pl.col(f"fret_{h}").is_not_null()).sort("ts", "symbol")
    X = df.select([pl.col(f).cast(pl.Float64) for f in lm.features]).to_numpy()
    sc = lm.score(X, df["symbol"].to_list())
    y = to_index(df[label].to_numpy())
    fret = df[f"fret_{h}"].to_numpy().astype(np.float64)
    full = multiclass_report(y, sc["raw"])
    cal = multiclass_report(y, sc["cal"])
    mom = multiclass_report(
        y, rule_proba(momentum_classes(df[MOMENTUM_COL[h]].to_numpy().astype(float), thr))
    )
    base = BacktestConfig(horizon=h)
    cost_bp = round_trip_bp(base.costs, base.capital * base.position_frac)
    calls = _calls(y, sc, fret, cost_bp)
    ok = full["mcc"] >= MIN_TEST_MCC and full["mcc"] > mom["mcc"] and full["balanced_accuracy"] > 1 / 3
    evidence = (
        f"test {start}..{end}, {len(y):,} rows: MCC {full['mcc']:.3f} (min {MIN_TEST_MCC}, momentum "
        f"{mom['mcc']:.3f}), balanced accuracy {full['balanced_accuracy']:.3f} (chance 0.333), accuracy "
        f"{full['accuracy']:.3f}; service calls {calls['calls']:,} ({calls['coverage']:.2%} coverage)"
    )
    val = rec.metrics["validation"]
    return {
        "model": rec.key,
        "label": label,
        "rows": int(len(y)),
        "full_coverage_raw": {
            k: full[k]
            for k in (
                "n",
                "coverage",
                "accuracy",
                "balanced_accuracy",
                "macro_f1",
                "mcc",
                "roc_auc_ovr",
                "brier",
                "log_loss",
                "ece_top",
                "updown_auc",
                "confusion_matrix",
                "class_distribution",
                "pred_distribution",
                "verdict",
            )
        },  # fmt: skip
        "full_coverage_calibrated": {
            "accuracy": cal["accuracy"],
            "balanced_accuracy": cal["balanced_accuracy"],
            "mcc": cal["mcc"],
            "brier": cal["brier"],
            "ece_classwise": classwise_ece(y, sc["cal"]),
            "ece_classwise_raw": classwise_ece(y, sc["raw"]),
        },  # fmt: skip
        "baselines": {
            "majority_class_from_train": CLASSES[train_major[label]],
            "majority_accuracy": float(np.mean(y == train_major[label])),
            "momentum_mcc": mom["mcc"],
            "momentum_accuracy": mom["accuracy"],
            "momentum_balanced_accuracy": mom["balanced_accuracy"],
        },
        "validation_for_comparison": {
            k: val[k] for k in ("accuracy", "balanced_accuracy", "mcc", "roc_auc_ovr")
        },
        "service_calls": calls,
        "round_trip_cost_bp": cost_bp,
        "selective_table": selective_direction_table(y, sc["raw"], fret),
        "monthly": _monthly(df, y, sc["cls"], sc["reason"] == ""),
        "backtest": _backtest(data_root, df, sc, h, thr, start, end),
        "gate": gate(PASSED if ok else FAILED, evidence),
    }


def run(data_root: Path, reports: Path, confirm: bool, models: tuple[str, ...] = MODELS,
        dataset: str = "core100_s5") -> dict[str, Any]:  # fmt: skip
    reg = Registry(data_root / "registry")
    out_json = reports / f"{REPORT}.json"
    if out_json.exists():
        raise AlreadyRun(f"{out_json} exists: the final test has already been run")
    used = [m for m in models if reg.get(m).test_period.get("used")]
    if used:
        raise AlreadyRun(f"test period already used by {used}")
    if not confirm:
        raise AlreadyRun("the final test runs once; pass --confirm-single-run to run it")
    ds = data_root / "datasets" / dataset
    man = json.loads((ds / "dataset_manifest.json").read_text())
    tp = next(p for p in man["periods"] if p["name"] == "test")
    start, end = date.fromisoformat(tp["start"]), date.fromisoformat(tp["end"])
    feats = json.loads((ds / "features.json").read_text())["features"]
    metas = [load_model(reg, reg.get(m)).meta for m in models]
    hs = sorted({int(m["horizon"]) for m in metas})
    labels = [label_name(int(m["horizon"]), float(m["threshold"])) for m in metas]
    cols = list(dict.fromkeys(["symbol", "ts", "trade_date", *labels, *[f"fret_{h}" for h in hs],
                               *[MOMENTUM_COL[h] for h in hs], *feats]))  # fmt: skip
    scan = pl.scan_parquet(ds / "part-*.parquet")
    train = scan.filter(pl.col("split") == "train").select(labels).collect()
    train_major = {lb: int(np.argmax(np.bincount(to_index(train[lb].drop_nulls().to_numpy()), minlength=3)))
                   for lb in labels}  # fmt: skip
    test = scan.filter(pl.col("split") == "test").select(cols).collect()
    started = datetime.now(UTC).isoformat()
    results = [evaluate_model(data_root, reg, m, test, train_major, start, end) for m in models]
    payload = {"runner_version": RUNNER_VERSION, "started_at": started,
               "finished_at": datetime.now(UTC).isoformat(), "dataset_id": man.get("dataset_id"),
               "test_period": {"start": str(start), "end": str(end)}, "models": results}  # fmt: skip
    reports.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=1, default=str))
    (reports / f"{REPORT}.md").write_text(render(payload))
    for r in results:
        mid, ver = r["model"].split("@v")
        reg.record_test(mid, int(ver), {k: r[k] for k in ("full_coverage_raw", "full_coverage_calibrated",
                        "baselines", "service_calls")}, r["gate"], f"reports/{REPORT}.json")  # fmt: skip
    return payload


def _p(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.1f}%"


def _n(x: float | None, nd: int = 3) -> str:
    return "–" if x is None else f"{x:.{nd}f}"


def render(p: dict[str, Any]) -> str:
    tp = p["test_period"]
    L = [f"# Final test-period evaluation ({tp['start']}..{tp['end']})", "",
         f"Run once ({p['started_at'][:10]}) after the user approved it on 2026-10-19. Frozen registry",
         "artifacts (SHA-256 verified), no refit or tuning. Full coverage = argmax of the raw",
         "probabilities on every test row; service calls = rows the ML service would answer UP/DOWN",
         "(confidence gate from Phase 12 plus abstain rules). Gate `test_passed` = MCC >= 0.05, above",
         "momentum, balanced accuracy above 1/3.", "",
         "## Full coverage", "",
         "| model | rows | accuracy | majority | balanced acc. | MCC | momentum MCC | AUC | val. MCC "
         "| gate |",
         "|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for r in p["models"]:
        f, b, v = r["full_coverage_raw"], r["baselines"], r["validation_for_comparison"]
        L.append(f"| {r['model']} | {r['rows']:,} | {_p(f['accuracy'])} | {_p(b['majority_accuracy'])} | "
                 f"{_p(f['balanced_accuracy'])} | {_n(f['mcc'])} | {_n(b['momentum_mcc'])} | "
                 f"{_n(f['roc_auc_ovr'])} | {_n(v['mcc'])} | {r['gate']['status']} |")  # fmt: skip
    L += ["", "## Calibration", "", "| model | Brier raw | Brier cal. | classwise ECE raw | ECE cal. |",
          "|---|---|---|---|---|"]  # fmt: skip
    for r in p["models"]:
        f, c = r["full_coverage_raw"], r["full_coverage_calibrated"]
        L.append(f"| {r['model']} | {_n(f['brier'])} | {_n(c['brier'])} | {_n(c['ece_classwise_raw'])} | "
                 f"{_n(c['ece_classwise'])} |")  # fmt: skip
    L += ["", "## Service calls (selective)", "",
          "| model | calls | coverage | accuracy | balanced acc. | MCC | sign right | gross bp "
          "| net bp after costs |",
          "|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for r in p["models"]:
        c = r["service_calls"]
        L.append(f"| {r['model']} | {c['calls']:,} | {_p(c['coverage'])} | {_p(c.get('accuracy'))} | "
                 f"{_p(c.get('balanced_accuracy'))} | {_n(c.get('mcc'))} | {_p(c.get('sign_accuracy'))} | "
                 f"{_n(c.get('gross_bp_per_call'), 2)} | {_n(c.get('net_bp_per_call'), 2)} |")  # fmt: skip
    L += ["", "## Backtest on the test period (same engine and costs as Phase 12)", "",
          "| model | strategy | costs | total return | trades | win rate | avg bp/trade |",
          "|---|---|---|---|---|---|---|"]  # fmt: skip
    for r in p["models"]:
        for k, m in r["backtest"].items():
            name, cost = k.split("|")
            L.append(f"| {r['model']} | {name} | {cost} | {_p(m.get('total_return'))} | "
                     f"{m.get('trades', '–')} | "
                     f"{_p(m.get('win_rate'))} | {_n(m.get('avg_trade_return_bp'), 2)} |")  # fmt: skip
    L += ["", "## By month (full coverage)", "",
          "| model | month | rows | accuracy | balanced acc. | MCC | calls |",
          "|---|---|---|---|---|---|---|"]  # fmt: skip
    for r in p["models"]:
        for m in r["monthly"]:
            L.append(f"| {r['model']} | {m['month']} | {m['n']:,} | {_p(m['accuracy'])} | "
                     f"{_p(m['balanced_accuracy'])} | {_n(m['mcc'])} | {m['calls']} |")  # fmt: skip
    L += ["", "The test period is now used. Any new model must be judged on a new untouched period."]
    return "\n".join(L) + "\n"
