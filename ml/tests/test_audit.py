"""The real-data leakage gate must pass on a clean golden dataset and catch injected leaks."""

from datetime import timedelta

import polars as pl
import pytest
from golden import write_raw

from pulsetrader.audit import leakage
from pulsetrader.data import pipeline
from pulsetrader.datasets.build import DatasetConfig, build
from pulsetrader.security import master


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("audit")
    write_raw(root / "raw")
    pipeline.run(root / "raw", root)
    master.build(
        root / "canonical",
        root / "reference",
        root / "reports",
        master.Eligibility(min_days=1, max_zero_volume_frac=1.0, min_median_daily_turnover=0),
    )
    cfg = DatasetConfig(
        universe_size=3,
        universe_days=2,
        warmup_bars=50,
        horizons=(5, 15),
        thresholds=(0.001,),
        fractions=(0.6, 0.2, 0.2),
        embargo_minutes=15,
        market_indices={"NIFTY 50": "nifty"},
        vix_symbol=None,
    )
    build(root, root / "ds", cfg)
    return root


def _run(root):
    return leakage.run(root, root / "ds", perturb_symbols=2, cuts_per_symbol=2, label_symbols=3)


def test_gate_passes_on_clean_dataset(built):
    r = _run(built)
    failed = [c["name"] for c in r["checks"] if not c["passed"]]
    assert r["passed"], failed
    assert "PASSED" in leakage.render(r)


def _rewrite(root, fn):
    for p in (root / "ds").glob("part-*.parquet"):
        fn(pl.read_parquet(p)).write_parquet(p)


def test_gate_catches_wrong_labels_and_broken_purge(built, tmp_path):
    import shutil

    root = tmp_path / "copy"
    shutil.copytree(built / "canonical", root / "canonical")
    shutil.copytree(built / "ds", root / "ds")
    # label shifted by one bar (a classic off-by-one) and a train row whose label ends late
    _rewrite(
        root,
        lambda d: d.with_columns(
            pl.col("fret_5").shift(-1).over("symbol"),
            pl.when(pl.col("split") == "train")
            .then(pl.col("label_end_ts_15") + timedelta(days=30))
            .otherwise(pl.col("label_end_ts_15"))
            .alias("label_end_ts_15"),
        ),
    )
    r = _run(root)
    status = {c["name"]: c["passed"] for c in r["checks"]}
    assert not r["passed"]
    assert not status["label recomputation from canonical"]
    assert not status["chronological split, purge and embargo"]
