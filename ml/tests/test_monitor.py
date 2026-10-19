"""Phase 19 drift monitoring: PSI and binning maths, calibrated thresholds, the drift report and the live
pipeline's per-session reports (golden fixture, offline)."""

from __future__ import annotations

import asyncio
import json
from datetime import date

import numpy as np
import polars as pl
import pytest
from test_live import StubModel, _validation_day

from pulsetrader.live.features import LiveUniverse
from pulsetrader.live.pipeline import LivePipeline, MemorySink, PipelineConfig
from pulsetrader.live.providers import HistoricalProvider
from pulsetrader.monitor.drift import (
    REGIMES,
    Reference,
    bin_fractions,
    bin_index,
    build_reference,
    decile_edges,
    drift_report,
    psi,
    regime_mix,
    window_kind,
)
from pulsetrader.monitor.live import LiveDriftMonitor


def test_psi_and_bins():
    assert psi([0.5, 0.5], [0.5, 0.5]) == 0.0
    assert psi([0.5, 0.5], [0.9, 0.1]) == pytest.approx(0.4 * np.log(1.8) + -0.4 * np.log(0.2), rel=1e-12)
    x = np.array([1.0, 2.0, 3.0, np.nan])
    assert list(bin_index(x, [1.5, 2.5])) == [0, 1, 2, 3]  # last bin = missing values
    assert bin_fractions(x, [1.5, 2.5]) == [0.25, 0.25, 0.25, 0.25]
    assert decile_edges(np.array([np.nan])) == []
    assert window_kind(1) == "day" and window_kind(5) == "week" and window_kind(20) == "month"
    mix = regime_mix(pl.DataFrame({"nifty_trend": ["up", "up", None], "nifty_vol": ["low", "high", "low"]}))
    assert mix["up/low"] == 0.5 and mix["up/high"] == 0.5 and set(mix) == set(REGIMES)


def _proba(frame: pl.DataFrame) -> np.ndarray:
    """Deterministic class probabilities from two fixture features (a stand-in model)."""
    z = frame.select(pl.col("ret_1").fill_null(0) * 500, pl.col("ret_5").fill_null(0) * 200).to_numpy()
    logits = np.column_stack([-z[:, 0], np.zeros(len(z)), z[:, 1]])
    e = np.exp(logits - logits.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


@pytest.fixture(scope="module")
def golden_ref(golden_dataset):
    root = golden_dataset
    ds = pl.read_parquet(root / "datasets" / "ds" / "part-*.parquet")
    feats = json.loads((root / "datasets" / "ds" / "features.json").read_text())["features"]
    train = ds.filter(pl.col("split") == "train")
    p = _proba(train)
    preds = train.select("ts").with_columns(
        pl.Series("fold", np.where(np.arange(train.height) < train.height // 2, "F1", "F2")),
        pl.Series("y", p.argmax(axis=1)),  # perfect labels in the reference: accuracy 1.0
        pl.Series("p_down", p[:, 0]), pl.Series("p_neutral", p[:, 1]), pl.Series("p_up", p[:, 2]),
    )  # fmt: skip
    regimes = (
        train.select("trade_date")
        .unique()
        .with_columns(pl.lit("up").alias("nifty_trend"), pl.lit("mid").alias("nifty_vol"))
    )
    ref = build_reference("stub@v1", train, feats, {"ret_1": 3.0, "ret_5": 1.0}, preds, regimes, {}, 50)
    return ref, ds, feats


def test_reference_roundtrip_and_baselines(golden_ref, tmp_path):
    ref, _, feats = golden_ref
    assert set(ref.features) == set(feats)
    assert sum(ref.importance.values()) == pytest.approx(1.0)
    assert sum(ref.features["ret_1"]["fractions"]) == pytest.approx(1.0)
    assert set(ref.baselines) == {"day", "week", "month"}
    assert ref.folds[0]["accuracy"] == 1.0
    f = tmp_path / "ref.json"
    f.write_text(json.dumps(ref.to_json(), default=str))
    again = Reference.load(f)
    assert again.features["ret_1"] == ref.features["ret_1"] and again.baselines.keys() == ref.baselines.keys()


def test_drift_report_flags_a_shifted_feature_and_lost_accuracy(golden_ref):
    ref, ds, feats = golden_ref
    train = ds.filter(pl.col("split") == "train")
    day = train["trade_date"].unique().sort()[0]
    win = train.filter(pl.col("trade_date") == day)
    p = _proba(win)
    reg = pl.DataFrame({"trade_date": [day], "nifty_trend": ["up"], "nifty_vol": ["mid"]})
    same = drift_report(ref, win.select(feats), p, p.argmax(axis=1), p, reg, {"kind": "t"}, 1, 50, 50)
    assert same["components"]["feature"]["status"] in ("OK", "WARN")
    assert same["components"]["accuracy"]["status"] == "OK"
    assert same["components"]["regime"]["status"] == "OK"
    assert same["status"] != "MODEL_DRIFT_DETECTED"
    # shift the most important feature far outside its training range and flip every label
    shifted = win.with_columns(pl.col("ret_1") + 1.0)
    wrong = (p.argmax(axis=1) + 1) % 3
    bad = drift_report(ref, shifted.select(feats), p, wrong, p, reg, {"kind": "t"}, 1, 50, 50)
    top = bad["components"]["feature"]["top"][0]
    assert top["feature"] == "ret_1" and top["level"] == "DRIFT"
    assert bad["components"]["feature"]["status"] == "DRIFT"  # ret_1 carries 75% of the importance
    assert bad["components"]["accuracy"]["status"] == "DRIFT"
    assert bad["status"] == "MODEL_DRIFT_DETECTED" and "accuracy DRIFT" in bad["reasons"]
    assert "never replaced automatically" in bad["action"]
    small = drift_report(ref, win.head(5).select(feats), p[:5], wrong[:5], p[:5], reg.head(0), {}, 1)
    assert small["status"] == "INSUFFICIENT_DATA"


def test_live_pipeline_reports_drift_after_each_session(golden_dataset, golden_ref):
    ref, _, feats = golden_ref
    root = golden_dataset
    day: date = _validation_day(root)
    uni = LiveUniverse.from_manifest(root / "datasets" / "ds")
    sink = MemorySink()
    drift = LiveDriftMonitor(refs={"stub@v1": ref})
    for d in (day, day):  # the same session twice: one per-session report, no duplicate
        pipe = LivePipeline(HistoricalProvider(root, d), uni, [StubModel(feats)], [sink],  # type: ignore[list-item]
                            PipelineConfig(), drift=drift)  # fmt: skip
        asyncio.run(pipe.run())
    assert len(sink.reports) == 1
    (rep,) = sink.reports
    assert rep["model"] == "stub@v1" and rep["mode"] == "REPLAY"
    assert rep["window"]["kind"] == "session" and rep["window"]["start"] == str(day)
    assert rep["components"]["feature"]["rows"] == 75 * 3  # 75 sampled bars x 3 stocks
    assert rep["latency"]["inference_ms_p50"] is None or rep["latency"]["inference_ms_p50"] >= 0
    assert rep["latency"]["feature_build_seconds_p50"] > 0
    assert rep["status"] in ("OK", "WARN", "MODEL_DRIFT_DETECTED", "INSUFFICIENT_DATA")
