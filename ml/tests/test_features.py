import math

import polars as pl
import pytest
from golden import golden_canonical

from pulsetrader.features.engine import compute_symbol_features


@pytest.fixture(scope="module")
def feats():
    return compute_symbol_features(golden_canonical(("AAA",)))


def test_feature_count_and_groups(feats):
    df, fs = feats
    assert len(fs.names) == len(set(fs.names))
    for g in ("OHLCV", "TECHNICAL", "VOLUME", "INTRADAY"):
        assert fs.group(g), g
    assert all(n in df.columns for n in fs.names)
    assert not any(c.startswith("_") for c in df.columns)


def test_exact_returns_and_sma(feats):
    df, _ = feats
    c = df["close"].to_list()
    assert df["ret_1"][10] == pytest.approx(c[10] / c[9] - 1)
    assert df["ret_5"][10] == pytest.approx(c[10] / c[5] - 1)
    assert df["ret_5"][4] is None
    sma5 = sum(c[6:11]) / 5
    assert df["sma_5_ratio"][10] == pytest.approx(c[10] / sma5 - 1)
    assert df["sma_200_ratio"][198] is None


def test_vwap_resets_daily(feats):
    df, _ = feats
    day2 = df.filter(pl.col("trade_date") == df["trade_date"].unique().sort()[1])
    r = day2.row(0, named=True)
    tp = (r["high"] + r["low"] + r["close"]) / 3
    assert r["vwap_dist"] == pytest.approx(r["close"] / tp - 1)


def test_first_k_minute_returns_only_after_k_bars(feats):
    df, _ = feats
    d0 = df.filter(pl.col("trade_date") == df["trade_date"].min())
    assert d0["first_5m_ret"][:4].null_count() == 4
    assert d0["first_5m_ret"][4] == pytest.approx(d0["close"][4] / d0["open"][0] - 1)
    assert d0["first_5m_ret"][100] == pytest.approx(d0["close"][4] / d0["open"][0] - 1)
    assert d0["first_30m_ret"][28] is None


def test_opening_gap_uses_previous_day(feats):
    df, _ = feats
    days = df["trade_date"].unique().sort()
    d0 = df.filter(pl.col("trade_date") == days[0])
    d1 = df.filter(pl.col("trade_date") == days[1])
    assert d0["opening_gap"].null_count() == d0.height
    assert d1["opening_gap"][0] == pytest.approx(d1["open"][0] / d0["close"][-1] - 1)


def test_rsi_bounds_and_no_inf(feats):
    df, fs = feats
    r = df["rsi_14"].drop_nulls()
    assert r.min() >= 0 and r.max() <= 100
    for n in fs.names:
        s = df[n].drop_nulls()
        if s.dtype.is_float():
            assert not any(math.isinf(x) for x in s.to_list()), n
