"""Phase 7 runner and 3-class metrics on the golden dataset."""

import json

import numpy as np
import polars as pl

from pulsetrader.eval.multiclass import multiclass_report, selective_direction_table, to_index
from pulsetrader.experiments.classical import RunConfig, inner_split, render_summary, run
from pulsetrader.models.classical import momentum_classes


def test_multiclass_report_perfect_and_majority():
    y = np.array([0, 1, 2, 1, 1, 1, 1, 1, 1, 1])
    perfect = np.eye(3)[y]
    r = multiclass_report(y, perfect)
    assert r["accuracy"] == 1 and r["mcc"] == 1 and r["brier"] == 0
    maj = multiclass_report(y, np.tile([0, 1.0, 0], (10, 1)))
    assert maj["accuracy"] == 0.8 and maj["mcc"] == 0
    assert maj["verdict"].startswith("FAILED")


def test_selective_coverage_is_relative_to_all_rows():
    y = to_index(np.array([1, -1, 0, 1]))
    proba = np.array([[0.1, 0.1, 0.8], [0.7, 0.2, 0.1], [0.3, 0.4, 0.3], [0.45, 0.1, 0.45]])
    fret = np.array([0.01, -0.01, 0.0, 0.002])
    rows = {r["threshold"]: r for r in selective_direction_table(y, proba, fret, (0.4, 0.75))}
    assert rows[0.4]["n_predictions"] == 3 and rows[0.4]["coverage"] == 0.75
    assert rows[0.4]["accuracy"] == 1.0  # ties go UP; row 4 is an UP label
    assert rows[0.75]["n_predictions"] == 1 and rows[0.75]["coverage"] == 0.25


def test_momentum_rule():
    assert momentum_classes(np.array([0.002, -0.002, 0.0, np.nan]), 0.001).tolist() == [2, 0, 1, 1]


def test_runner_on_golden(golden_dataset, tmp_path):
    cfg = RunConfig(dataset="ds", horizons=(5,), thresholds=(0.001,), train_every=5, train_eval_rows=50)
    out = tmp_path / "exp"
    s1 = run(golden_dataset, out, cfg)
    run(golden_dataset, out, cfg)
    dirs = sorted(out.iterdir())
    assert len(dirs) == 2  # never overwrites
    d = dirs[0]
    for f in ("experiment.json", "config.json", "metrics.json", "feature_importance.json", "report.md",
              "predictions.parquet", "preprocessor.json"):  # fmt: skip
        assert (d / f).exists(), f
    exp = json.loads((d / "experiment.json").read_text())
    assert exp["test_period"]["used"] is False
    m = json.loads((d / "metrics.json").read_text())
    assert set(m) == set(cfg.models)
    for r in m.values():
        assert {"accuracy", "balanced_accuracy", "mcc", "coverage", "selective"} <= set(r)
    preds = pl.read_parquet(d / "predictions.parquet")
    ds = pl.read_parquet(golden_dataset / "datasets" / "ds" / "part-*.parquet")
    val_ts = ds.filter(pl.col("split") == "validation")["ts"]
    assert preds["ts"].is_in(val_ts.implode()).all()  # only validation rows are scored
    probs = preds.select(pl.selectors.starts_with("lightgbm_p_")).to_numpy()
    assert np.allclose(probs.sum(axis=1), 1, atol=1e-5)
    assert s1[0]["metrics"]["majority"]["coverage"] == 1.0
    md = render_summary(s1)
    assert "not used" in md and "Best learned model" in md


def test_inner_split_is_purged_and_chronological(golden_dataset):
    ds = pl.read_parquet(golden_dataset / "datasets" / "ds" / "part-*.parquet").filter(
        (pl.col("split") == "train") & pl.col("fret_5").is_not_null()
    )
    fit, es = inner_split(ds, 5, 0.34, 15)
    f, e = ds.filter(fit), ds.filter(es)
    assert f.height > 0 and e.height > 0
    es_first = ds.filter(pl.col("trade_date") >= e["trade_date"].min())["ts"].min()
    assert f["label_end_ts_5"].max() <= es_first
    assert e["ts"].min() >= es_first + __import__("datetime").timedelta(minutes=15)


def test_sequences_are_causal_and_within_symbol(golden_dataset):
    from pulsetrader.datasets.sequences import build

    sd = build(
        golden_dataset / "datasets" / "ds", 5, (0.001,), train_every=5, es_frac=0.34, embargo_minutes=15
    )
    assert set(sd.meta["split"].drop_nulls().unique()) <= {"train", "validation"}  # no test rows
    idx = sd.usable(sd.val_idx, 4)
    w = sd.windows(idx, 4)
    assert w.shape == (len(idx), 4, len(sd.features))
    assert np.array_equal(w[:, -1, :], sd.X[idx])  # window ends at the prediction row
    starts = sd.first_row[idx]
    assert (idx - 3 >= starts).all()  # never spans another symbol
    ts = sd.meta["ts"].to_numpy()
    assert (ts[idx - 3] < ts[idx]).all()  # history strictly earlier
    assert sd.preprocessor.fit_rows == len(sd.fit_idx)


def test_deep_models_train_on_golden(golden_dataset, tmp_path):
    import pytest

    pytest.importorskip("torch")
    from pulsetrader.datasets.sequences import build
    from pulsetrader.experiments.deep import DeepConfig, train_eval
    from pulsetrader.models.deep import ARCHITECTURES

    sd = build(
        golden_dataset / "datasets" / "ds", 5, (0.001,), train_every=5, es_frac=0.34, embargo_minutes=15
    )
    for arch in ARCHITECTURES:
        cfg = DeepConfig(arch=arch, length=8, samples_per_epoch=64, batch=32, max_epochs=2, hidden=8,
                         attn=4, d_model=8, heads=2, threads=1)  # fmt: skip
        r = train_eval(sd, cfg, tmp_path / "exp", {"dataset_id": "golden"})
        m = r["metrics"][arch]
        assert 0 <= m["accuracy"] <= 1 and m["coverage"] == 1.0
        d = tmp_path / "exp" / r["experiment"]["experiment_id"]
        assert (d / "model.pt").exists() and (d / "predictions.parquet").exists()
        p = pl.read_parquet(d / "predictions.parquet")
        assert np.allclose(p.select("p_down", "p_neutral", "p_up").to_numpy().sum(axis=1), 1, atol=1e-5)
        assert set(p["split"].unique()) == {"validation"}
