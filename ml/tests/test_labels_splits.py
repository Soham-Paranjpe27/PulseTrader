from datetime import date, timedelta

import polars as pl
import pytest
from golden import golden_canonical

from pulsetrader.labels.labels import DOWN, NEUTRAL, UP, add_labels, label_name
from pulsetrader.splits.splits import assign, date_split, walk_forward


@pytest.fixture(scope="module")
def labelled():
    return add_labels(golden_canonical(("AAA",)).sort("ts"), (1, 5, 60), (0.001,))


def test_label_values(labelled):
    df = labelled
    c = df["close"].to_list()
    assert df["fret_5"][0] == pytest.approx(c[5] / c[0] - 1)
    y = df[label_name(5, 0.001)][0]
    f = c[5] / c[0] - 1
    assert y == (UP if f > 0.001 else DOWN if f < -0.001 else NEUTRAL)
    assert df["label_end_ts_5"][0] == df["ts"][0] + timedelta(minutes=6)


def test_labels_never_cross_session(labelled):
    d0 = labelled.filter(pl.col("trade_date") == labelled["trade_date"].min())
    # last 5 bars of the day have no 5-minute label; last 60 have no 60-minute label
    assert d0["fret_5"][-5:].null_count() == 5
    assert d0["fret_5"][-6] is not None
    assert d0["fret_60"][-60:].null_count() == 60


def test_labels_null_on_gap():
    df = golden_canonical(("AAA",)).sort("ts")
    gap_ts = df["ts"][10]
    holed = df.filter(pl.col("ts") != gap_ts)
    out = add_labels(holed, (5,))
    assert out.filter(pl.col("ts") == df["ts"][5])["fret_5"][0] is None


def test_date_split_chronological():
    days = [date(2024, 1, d) for d in range(1, 21)]
    p = date_split(days)
    assert p[0].end < p[1].start and p[1].end < p[2].start
    assert p[0].start == days[0] and p[2].end == days[-1]


def test_purge_and_embargo(labelled):
    days = sorted(labelled["trade_date"].unique().to_list())
    periods = date_split(days, (0.6, 0.2, 0.2))
    out = assign(labelled, periods, "label_end_ts_60", embargo_minutes=10)
    val_start = out.filter(pl.col("split") == "validation")["ts"].min()
    train = out.filter(pl.col("split") == "train")
    assert train["label_end_ts_60"].max() <= val_start
    assert out["purged"].sum() > 0
    # embargo: no validation row within 10 minutes of the raw validation start
    raw_val_start = out.filter(pl.col("trade_date") == periods[1].start)["ts"].min()
    assert out.filter(pl.col("split") == "validation")["ts"].min() >= raw_val_start + timedelta(minutes=10)


def test_walk_forward_windows():
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(50)]
    for mode in ("expanding", "rolling"):
        w = walk_forward(days, 4, mode=mode)
        assert len(w) == 4
        for x in w:
            assert x.train.end < x.valid.start
        assert w[-1].valid.end == days[-1]
    exp = walk_forward(days, 4, "expanding")
    assert all(x.train.start == days[0] for x in exp)
