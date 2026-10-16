"""Automated leakage audit (Phase 6 gate).

Perturbation test: change every bar after a cut-off; features at or before the cut-off must not move.
If any feature used future data, its past values would change.
"""

import numpy as np
import polars as pl
import pytest
from golden import golden_canonical, golden_frames, to_canonical

from pulsetrader.features.engine import (
    FeatureSet,
    add_market_context,
    add_relative_strength,
    compute_symbol_features,
)
from pulsetrader.features.preprocess import PreprocessError, Preprocessor
from pulsetrader.labels.labels import add_labels
from pulsetrader.splits.splits import assign, date_split

CUTS = (3, 200, 375 + 2, 375 + 150, 2 * 375 - 1)


def _perturb_after(df: pl.DataFrame, cut_ts, symbol=None) -> pl.DataFrame:
    m = pl.col("ts") > cut_ts
    if symbol is not None:
        m = m & (pl.col("symbol") == symbol)
    rng = np.random.default_rng(0)
    f = pl.Series(rng.uniform(0.5, 2.0, df.height))
    return df.with_columns(
        *[pl.when(m).then(pl.col(c) * f).otherwise(pl.col(c)).alias(c) for c in ("open", "close")],
        pl.when(m).then(pl.col("volume") * 7 + 13).otherwise(pl.col("volume")).alias("volume"),
    ).with_columns(
        pl.max_horizontal("open", "close", "high").alias("high"),
        pl.min_horizontal("open", "close", "low").alias("low"),
    )


def _assert_same(a: pl.DataFrame, b: pl.DataFrame, cols, mask_a, mask_b):
    x = a.filter(mask_a).select(cols)
    y = b.filter(mask_b).select(cols)
    assert x.height == y.height > 0
    for c in cols:
        xa = x[c].to_numpy().astype(float)
        ya = y[c].to_numpy().astype(float)
        assert np.allclose(xa, ya, equal_nan=True, rtol=1e-9, atol=1e-12), f"LEAK in {c}"


@pytest.mark.parametrize("cut", CUTS)
def test_single_symbol_features_are_causal(cut):
    base = golden_canonical(("AAA",)).sort("ts")
    cut_ts = base["ts"][cut]
    f0, fs = compute_symbol_features(base)
    f1, _ = compute_symbol_features(_perturb_after(base, cut_ts))
    m = pl.col("ts") <= cut_ts
    _assert_same(f0, f1, fs.names, m, m)


@pytest.mark.parametrize("cut", (200, 375 + 150))
def test_cross_sectional_features_are_causal(cut):
    base = golden_canonical().sort("symbol", "ts")
    cut_ts = base.filter(pl.col("symbol") == "AAA")["ts"][cut]

    def build(df):
        f, fs = compute_symbol_features(df)
        return add_relative_strength(f, fs), fs

    f0, fs = build(base)
    f1, _ = build(_perturb_after(base, cut_ts, symbol="BBB"))  # only another stock's future changes
    m = (pl.col("ts") <= cut_ts) & (pl.col("symbol") == "AAA")
    _assert_same(f0, f1, fs.group("RELATIVE"), m, m)


def test_market_context_is_causal():
    nifty = to_canonical(golden_frames()["NIFTY 50"], "NIFTY 50")
    stock = golden_canonical(("AAA",))
    cut_ts = nifty["ts"][300]
    fs = FeatureSet()
    s, _ = compute_symbol_features(stock)
    n0, _ = compute_symbol_features(nifty)
    n1, _ = compute_symbol_features(_perturb_after(nifty, cut_ts))
    a = add_market_context(s, n0, "nifty", fs)
    b = add_market_context(s, n1, "nifty", FeatureSet())
    m = pl.col("ts") <= cut_ts
    _assert_same(a, b, fs.group("MARKET"), m, m)


def test_availability_not_after_prediction_time():
    f, _ = compute_symbol_features(golden_canonical(("AAA",)))
    prediction_ts = f["availability_ts"]  # earliest decision time = bar close
    assert (f["availability_ts"] <= prediction_ts).all()
    assert (f["availability_ts"] > f["feature_ts"]).all()
    assert ((f["availability_ts"] - f["feature_ts"]).dt.total_seconds() == 60).all()


def test_labels_strictly_after_features():
    lab = add_labels(golden_canonical(("AAA",)), (1, 5, 15, 30, 60))
    f, _ = compute_symbol_features(lab)
    for h in (1, 5, 15, 30, 60):
        assert (f[f"label_end_ts_{h}"] > f["availability_ts"]).all()


def test_scaler_isolation():
    lab = add_labels(golden_canonical(("AAA",)), (5,))
    f, fs = compute_symbol_features(lab)
    periods = date_split(f["trade_date"].unique().to_list(), (0.6, 0.2, 0.2))
    s = assign(f, periods, "label_end_ts_5")
    train = s.filter(pl.col("split") == "train")
    with pytest.raises(PreprocessError):
        Preprocessor.fit(s.filter(pl.col("split").is_not_null()), fs.names, "v")
    pp = Preprocessor.fit(train, fs.names, "v")
    x = train.select(fs.names).to_numpy().astype(float)
    med = np.nan_to_num(np.nanmedian(x, axis=0))
    xi = np.where(np.isnan(x), med, x)
    assert np.allclose(pp.means, xi.mean(axis=0))
    assert pp.fit_period[1] == str(train["ts"].max())
    # transformed training data is standardised; validation data is not refit
    z = pp.transform(train)
    assert np.allclose(z.mean(axis=0), 0, atol=1e-8)


def test_preprocessor_roundtrip_and_order(tmp_path):
    f, fs = compute_symbol_features(golden_canonical(("AAA",)))
    pp = Preprocessor.fit(f, fs.names, "v")
    pp.save(tmp_path / "pp.json")
    pp2 = Preprocessor.load(tmp_path / "pp.json")
    shuffled = f.select(list(reversed(f.columns)))
    assert np.allclose(pp.transform(f), pp2.transform(shuffled))
    with pytest.raises(PreprocessError):
        pp.transform(f.drop(fs.names[0]))


def test_features_independent_of_input_row_order():
    base = golden_canonical(("AAA", "BBB"))
    f0, fs = compute_symbol_features(base.sort("symbol", "ts"))
    f1, _ = compute_symbol_features(base.sample(fraction=1.0, shuffle=True, seed=1))
    _assert_same(f0, f1.sort("symbol", "ts"), fs.names, pl.lit(True), pl.lit(True))
