import json

import numpy as np
import polars as pl

from pulsetrader.eval.calibration import Isotonic, Platt, classwise_ece, reliability_curve
from pulsetrader.eval.multiclass import multiclass_report


def _overconfident():
    # deterministic: true class probabilities are flatter than the stated ones
    n = 3000
    y = np.arange(n) % 3
    stated = np.full((n, 3), 0.1)
    stated[np.arange(n), (y + (np.arange(n) % 5 == 0)) % 3] = 0.8  # 80% stated, ~80% right... then shift
    stated = stated / stated.sum(axis=1, keepdims=True)
    wrong = np.arange(n) % 2 == 0  # make half the confident calls wrong -> overconfident
    pred = stated.argmax(axis=1)
    y = np.where(wrong, (pred + 1) % 3, pred)
    return y, stated


def test_calibrators_reduce_brier_and_keep_simplex():
    y, p = _overconfident()
    raw = multiclass_report(y, p)["brier"]
    for cal in (Platt(), Isotonic()):
        q = cal.fit(y, p).transform(p)
        assert np.allclose(q.sum(axis=1), 1)
        assert (q >= 0).all()
        assert multiclass_report(y, q)["brier"] < raw
        assert json.dumps(cal.to_json())


def test_reliability_curve_counts_rows():
    y, p = _overconfident()
    curve = reliability_curve(y, p)
    assert sum(b["n"] for b in curve) == len(y)
    assert 0 <= classwise_ece(y, p) <= 1


def test_calibration_runner_on_golden(golden_dataset, tmp_path):
    from pulsetrader.experiments import optimize as opt
    from pulsetrader.experiments.calibrate import calibrate, render_summary

    dev = opt.load_dev(golden_dataset, 5, (0.001,), dataset="ds", n_pre=1, min_train_frac=0.67,
                       embargo_minutes=15, train_every=5)  # fmt: skip
    r = opt.walk_forward(dev, tmp_path / "exp", "y_5m_10bp")
    d = tmp_path / "exp" / r["experiment"]["experiment_id"]
    # the golden data is too short for three folds: split the validation fold in two by time
    pr = pl.read_parquet(d / "predictions.parquet").sort("ts")
    val = pr.filter(pl.col("fold") == "F2")
    cut = val["ts"][len(val) // 2]
    pr = pr.with_columns(
        pl.when(pl.col("fold") == "F2")
        .then(pl.when(pl.col("ts") < cut).then(pl.lit("F2")).otherwise(pl.lit("F3")))
        .otherwise(pl.col("fold")).alias("fold")
    )  # fmt: skip
    pr.write_parquet(d / "predictions.parquet")
    res = calibrate(d, tmp_path / "exp")
    out = tmp_path / "exp" / res["experiment"]["experiment_id"]
    for f in (
        "experiment.json",
        "config.json",
        "metrics.json",
        "calibrators.json",
        "predictions.parquet",
        "report.md",
    ):
        assert (out / f).exists(), f
    p = pl.read_parquet(out / "predictions.parquet")
    for m in ("raw_probability", "platt_probability", "isotonic_probability"):
        s = p.select(pl.selectors.starts_with(m)).to_numpy().sum(axis=1)
        assert np.allclose(s, 1, atol=1e-4)
    assert res["result"]["chosen"] in ("raw", "platt", "isotonic")
    assert res["experiment"]["test_period"]["used"] is False
    assert "Phase 10" in render_summary([res])
