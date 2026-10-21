import json
from datetime import date

import polars as pl
from golden import write_raw

from pulsetrader.data import pipeline
from pulsetrader.datasets.build import DatasetConfig, build
from pulsetrader.security import master


def test_build_dataset(tmp_path):
    raw = tmp_path / "raw"
    write_raw(raw)
    pipeline.run(raw, tmp_path)
    master.build(
        tmp_path / "canonical",
        tmp_path / "reference",
        tmp_path / "reports",
        master.Eligibility(min_days=1, max_zero_volume_frac=1.0, min_median_daily_turnover=0),
    )
    cfg = DatasetConfig(
        universe_size=3,
        universe_days=5,
        sample_every=5,
        warmup_bars=50,
        horizons=(5, 15),
        thresholds=(0.001,),
        fractions=(0.6, 0.2, 0.2),
        embargo_minutes=15,
        market_indices={"NIFTY 50": "nifty"},
        vix_symbol=None,
    )
    m = build(tmp_path, tmp_path / "ds", cfg)
    assert m["universe"] == ["CCC", "BBB", "AAA"]  # by turnover; DIRTY has one session only
    assert [p["name"] for p in m["periods"]] == ["train", "validation", "test"]
    assert m["periods"][1]["start"] == "2024-01-04" and m["periods"][2]["start"] == "2024-01-05"
    df = pl.read_parquet(tmp_path / "ds" / "part-*.parquet")
    feats = json.loads((tmp_path / "ds" / "features.json").read_text())["features"]
    assert {"nifty_ret_5", "rel_ret_5", "breadth_15", "rs_rank_15"} <= set(feats)
    assert "atr_14" not in feats and "log_volume" not in feats
    assert (df["min_since_open"] % 5 == 0).all()
    assert (df["xs_count"] == 3).all()  # whole cross-section at every sampled timestamp
    # warm-up rows dropped: first 50 bars of day 1 never appear
    assert df.filter(pl.col("trade_date") == date(2024, 1, 1))["min_since_open"].min() >= 50
    # embargo: the first 15 minutes of validation and test are not labelled rows of those splits
    for name, d in (("validation", date(2024, 1, 4)), ("test", date(2024, 1, 5))):
        first = df.filter(pl.col("split") == name)["min_since_open"].min()
        assert df.filter(pl.col("split") == name)["trade_date"].min() == d and first >= 15
    # purging: no row's label ends after the next split starts
    v0 = df.filter(pl.col("split") == "validation")["ts"].min()
    assert (df.filter(pl.col("split") == "train")["label_end_ts_15"] <= v0).all()
    assert m["rows"] == df.height and sum(m["rows_by_split"].values()) == df.height
    assert set(m["label_distribution"]["y_5m_10bp"]) == {"train", "validation", "test"}
    assert df.schema["ret_5"] == pl.Float32
