import json
from datetime import date

import numpy as np
import polars as pl

from pulsetrader.experiments import optimize as opt


def test_folds_are_chronological_and_end_with_validation():
    dates = [date(2023, 1, 1 + i) for i in range(20)]
    folds = opt.make_folds(dates, (date(2023, 2, 1), date(2023, 2, 10)), n_pre=3, min_train_frac=0.4)
    assert [f.name for f in folds] == ["F1", "F2", "F3", "F4"]
    assert folds[0].start == dates[8] and folds[-1].is_validation
    for a, b in zip(folds, folds[1:], strict=False):
        assert a.end < b.start


def test_feature_groups_match_engine(golden_dataset):
    from pulsetrader.features.engine import compute_symbol_features

    path = next((golden_dataset / "canonical").glob("*.parquet"))
    _, fs = compute_symbol_features(pl.read_parquet(path))
    for spec in fs.specs:
        assert opt.feature_group(spec.name) == spec.group, spec.name
    feats = json.loads((golden_dataset / "datasets" / "ds" / "features.json").read_text())["features"]
    groups = {opt.feature_group(f) for f in feats}
    assert {"MARKET", "RELATIVE"} <= groups


def test_class_bias_and_selective_threshold():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 3, 2000)
    p = rng.dirichlet(np.ones(3), 2000)
    p[np.arange(2000), y] += 0.3
    p /= p.sum(axis=1, keepdims=True)
    w = opt.class_bias_fit(y, p)
    assert w.shape == (3,) and w[1] == 1.0
    s = opt.selective_threshold_fit(y, p, min_coverage=0.05)
    assert s["threshold"] is not None and s["coverage"] >= 0.05


def test_walk_forward_tune_features_ensemble_on_golden(golden_dataset, tmp_path):
    dev = opt.load_dev(
        golden_dataset,
        5,
        (0.001,),
        dataset="ds",
        n_pre=1,
        min_train_frac=0.67,
        embargo_minutes=15,
        train_every=5,
    )
    lab = "y_5m_10bp"
    out = tmp_path / "exp"
    for f in dev.folds[:-1]:
        fd = dev.fold_data(f)
        # purge: every training label ends before the evaluation window starts; never test rows
        assert fd.fit["label_end_ts_5"].max() <= fd.ev["ts"].min()
        assert set(fd.fit["split"].unique()) == {"train"}
    r = opt.walk_forward(dev, out, lab)
    x = opt.walk_forward(dev, out, lab, "xgboost")
    opt.walk_forward(dev, out, lab, scheme="rolling")
    d = out / r["experiment"]["experiment_id"]
    for f in ("experiment.json", "config.json", "metrics.json", "feature_importance.json", "report.md",
              "predictions.parquet", "preprocessor.json"):  # fmt: skip
        assert (d / f).exists(), f
    assert r["experiment"]["test_period"]["used"] is False
    assert len(r["result"]["per_fold"]) == len(dev.folds)
    assert {"mean", "median", "std", "min", "max"} <= set(r["result"]["summary_all"]["mcc"])
    preds = pl.read_parquet(d / "predictions.parquet")
    ds = pl.read_parquet(golden_dataset / "datasets" / "ds" / "part-*.parquet")
    test_ts = ds.filter(pl.col("split") == "test")["ts"]
    assert not preds["ts"].is_in(test_ts.implode()).any()
    t = opt.tune(dev, out, lab, n_trials=3)
    assert t["result"]["trials"][0]["params"]["num_leaves"] == 63  # trial 0 = defaults
    fsel = opt.feature_selection(dev, out, lab, top_k=(5,), sample=500)
    assert fsel["result"]["chosen"] in fsel["result"]["selection_fold_scores"]
    e = opt.ensembles(out, lab, d, out / x["experiment"]["experiment_id"], None, {"dataset_id": "golden"})
    assert {"lightgbm", "xgboost", "weighted_lgb_xgb", "stacked_lgb_xgb"} <= set(e["result"]["validation"])
