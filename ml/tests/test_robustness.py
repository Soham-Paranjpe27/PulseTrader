import numpy as np
import polars as pl

from pulsetrader.eval.multiclass import DOWN, NEUTRAL, UP
from pulsetrader.experiments.robustness import bucket_metrics, cost_table


def test_bucket_metrics_and_costs():
    y = np.array([UP, DOWN, NEUTRAL, UP, DOWN, NEUTRAL])
    pred = np.array([UP, UP, NEUTRAL, UP, DOWN, DOWN])
    fret = np.array([0.002, -0.001, 0.0, 0.003, -0.002, 0.0005])
    m = bucket_metrics(y, pred, fret)
    assert m["n"] == 6 and m["accuracy"] == 4 / 6
    assert m["directional_share"] == 5 / 6
    assert m["sign_accuracy"] == 3 / 5  # UP right, UP wrong, UP right, DOWN right, DOWN wrong
    c = cost_table(pred, fret, np.full(6, 0.6), gates=(0.0,))[0]
    gross = np.array([20, -10, 30, 20, -5]).mean()
    assert c["trades"] == 5 and np.isclose(c["gross_bp"], gross)
    assert np.isclose(c["net_bp"]["10"], gross - 10)


def test_robustness_runner_on_golden(golden_dataset, tmp_path):
    from pulsetrader.experiments import optimize as opt
    from pulsetrader.experiments.robustness import analyse, render_summary

    dev = opt.load_dev(golden_dataset, 5, (0.001,), dataset="ds", n_pre=1, min_train_frac=0.67,
                       embargo_minutes=15, train_every=5)  # fmt: skip
    r = opt.walk_forward(dev, tmp_path / "exp", "y_5m_10bp")
    d = tmp_path / "exp" / r["experiment"]["experiment_id"]
    res = analyse(d, golden_dataset, tmp_path / "exp", dataset="ds")
    v = res["result"]["validation"]
    assert (
        v["overall"]["n"] == pl.read_parquet(d / "predictions.parquet").filter(pl.col("fold") == "F2").height
    )
    assert {"nifty_trend", "stock_vol", "time_of_day", "sector", "symbols", "costs"} <= set(v)
    assert res["experiment"]["test_period"]["used"] is False
    assert "Phase 11" in render_summary([res])
