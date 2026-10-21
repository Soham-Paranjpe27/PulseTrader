"""The real-data leakage gate must pass on a clean golden dataset and catch injected leaks."""

from datetime import timedelta

import polars as pl
import pytest

from pulsetrader.audit import leakage


@pytest.fixture(scope="module")
def built(golden_dataset, tmp_path_factory):
    import shutil

    root = tmp_path_factory.mktemp("audit")
    shutil.copytree(golden_dataset / "canonical", root / "canonical")
    shutil.copytree(golden_dataset / "datasets" / "ds", root / "ds")
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
