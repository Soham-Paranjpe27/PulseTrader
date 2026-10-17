"""The single shared feature engine, used unchanged by training and by live inference.

Every feature at bar t is computed only from bars <= t of the same symbol (or, for cross-sectional
and market features, other instruments' bars <= t). A 1-minute bar stamped t closes at t+1min, so
availability_timestamp = ts + 1 minute, which is also the earliest prediction_timestamp.
This is enforced by the perturbation tests in tests/test_leakage.py.

Rolling windows run over consecutive bars of a symbol (they span overnight gaps); intraday
features reset each trade_date.

All model features are scale-free (returns, ratios, normalised indicators). Historical prices and
volumes are back-adjusted by the data vendor using later corporate actions, so absolute price or
volume levels (ATR in rupees, log volume) are not point-in-time and are not features (features-v2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

import polars as pl

from pulsetrader.config import BAR_MINUTES, FEATURE_VERSION

S = "symbol"
D = ("symbol", "trade_date")

RET_WINDOWS = (1, 2, 3, 5, 10, 15, 30, 60)
SMA_WINDOWS = (5, 10, 20, 50, 100, 200)
EMA_WINDOWS = (5, 10, 20, 50)


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    group: str  # OHLCV | TECHNICAL | VOLUME | INTRADAY | MARKET | RELATIVE


@dataclass
class FeatureSet:
    specs: list[FeatureSpec] = field(default_factory=list)

    def add(self, group: str, *names: str) -> None:
        self.specs += [FeatureSpec(n, group) for n in names]

    @property
    def names(self) -> list[str]:
        return [s.name for s in self.specs]

    def group(self, g: str) -> list[str]:
        return [s.name for s in self.specs if s.group == g]


def _safe(e: pl.Expr) -> pl.Expr:
    """Map +/-inf and NaN to null so missing-value handling is uniform."""
    return pl.when(e.is_infinite() | e.is_nan()).then(None).otherwise(e)


def _wilder(e: pl.Expr, n: int, over: str | tuple[str, ...] = S) -> pl.Expr:
    return e.ewm_mean(alpha=1.0 / n, adjust=False, min_samples=n).over(over)


def single_symbol_exprs(fs: FeatureSet) -> list[list[pl.Expr]]:
    """Per-symbol features, returned as stages (later stages may reference earlier columns)."""
    c, o, h, lo, v = (pl.col(x) for x in ("close", "open", "high", "low", "volume"))
    prev_c = c.shift(1).over(S)
    st1: list[pl.Expr] = []
    st2: list[pl.Expr] = []
    st3: list[pl.Expr] = []

    # --- price / OHLCV
    st1 += [
        _safe(c / prev_c - 1).alias("ret_1"),
        _safe((c / prev_c).log()).alias("log_ret_1"),
        _safe(o / prev_c - 1).alias("gap"),
        _safe((c - o) / o).alias("body"),
        _safe((h - pl.max_horizontal(o, c)) / c).alias("upper_wick"),
        _safe((pl.min_horizontal(o, c) - lo) / c).alias("lower_wick"),
        _safe((h - lo) / c).alias("range"),
        _safe((c - lo) / (h - lo)).alias("close_pos"),
    ]
    fs.add("OHLCV", "ret_1", "log_ret_1", "gap", "body", "upper_wick", "lower_wick", "range", "close_pos")
    for k in RET_WINDOWS[1:]:
        st1.append(_safe(c / c.shift(k).over(S) - 1).alias(f"ret_{k}"))
        fs.add("OHLCV", f"ret_{k}")

    # --- moving averages (as ratios so they are scale-free across symbols)
    for n in SMA_WINDOWS:
        st1.append(_safe(c / c.rolling_mean(n).over(S) - 1).alias(f"sma_{n}_ratio"))
        fs.add("TECHNICAL", f"sma_{n}_ratio")
    for n in EMA_WINDOWS:
        st1.append(
            _safe(c / c.ewm_mean(span=n, adjust=False, min_samples=n).over(S) - 1).alias(f"ema_{n}_ratio")
        )
        fs.add("TECHNICAL", f"ema_{n}_ratio")

    # --- momentum
    delta = c - prev_c
    gain = _wilder(pl.when(delta > 0).then(delta).otherwise(0.0), 14)
    loss = _wilder(pl.when(delta < 0).then(-delta).otherwise(0.0), 14)
    st1.append(_safe(100 - 100 / (1 + gain / loss)).alias("rsi_14"))
    st1.append(_safe(c / c.shift(10).over(S) - 1).alias("roc_10"))
    hh14 = h.rolling_max(14).over(S)
    ll14 = lo.rolling_min(14).over(S)
    st1.append(_safe((c - ll14) / (hh14 - ll14) * 100).alias("stoch_k_14"))
    st1.append(_safe((hh14 - c) / (hh14 - ll14) * -100).alias("williams_r_14"))
    tp = (h + lo + c) / 3
    st1.append(
        _safe((tp - tp.rolling_mean(20).over(S)) / (0.015 * tp.rolling_std(20).over(S))).alias("cci_20_std")
    )
    st2.append(pl.col("stoch_k_14").rolling_mean(3).over(S).alias("stoch_d_3"))
    fs.add("TECHNICAL", "rsi_14", "roc_10", "stoch_k_14", "williams_r_14", "cci_20_std", "stoch_d_3")

    # --- trend: MACD (normalised by close), ADX / DI
    ema12 = c.ewm_mean(span=12, adjust=False, min_samples=12).over(S)
    ema26 = c.ewm_mean(span=26, adjust=False, min_samples=26).over(S)
    st1.append(_safe((ema12 - ema26) / c).alias("macd"))
    st2.append(pl.col("macd").ewm_mean(span=9, adjust=False, min_samples=9).over(S).alias("macd_signal"))
    st3.append((pl.col("macd") - pl.col("macd_signal")).alias("macd_hist"))
    up = h - h.shift(1).over(S)
    dn = lo.shift(1).over(S) - lo
    plus_dm = pl.when((up > dn) & (up > 0)).then(up).otherwise(0.0)
    minus_dm = pl.when((dn > up) & (dn > 0)).then(dn).otherwise(0.0)
    tr = pl.max_horizontal(h - lo, (h - prev_c).abs(), (lo - prev_c).abs())
    atr = _wilder(tr, 14)
    st1 += [
        _safe(100 * _wilder(plus_dm, 14) / atr).alias("di_plus_14"),
        _safe(100 * _wilder(minus_dm, 14) / atr).alias("di_minus_14"),
        _safe(atr / c).alias("atr_pct_14"),
    ]
    dx = _safe(
        100
        * (pl.col("di_plus_14") - pl.col("di_minus_14")).abs()
        / (pl.col("di_plus_14") + pl.col("di_minus_14"))
    )
    st2.append(_wilder(dx, 14).alias("adx_14"))
    fs.add("TECHNICAL", "macd", "macd_signal", "macd_hist", "di_plus_14", "di_minus_14", "adx_14")

    # --- volatility
    r1 = pl.col("ret_1")
    st2 += [
        r1.rolling_std(20).over(S).alias("vol_20"),
        r1.rolling_std(60).over(S).alias("vol_60"),
        (r1.pow(2).rolling_sum(30).over(S)).sqrt().alias("realized_vol_30"),
        pl.when(r1 < 0).then(r1).otherwise(0.0).rolling_std(20).over(S).alias("downside_vol_20"),
    ]
    st1.append(_safe(4 * c.rolling_std(20).over(S) / c.rolling_mean(20).over(S)).alias("bb_width_20"))
    fs.add(
        "TECHNICAL",
        "atr_pct_14",
        "vol_20",
        "vol_60",
        "realized_vol_30",
        "downside_vol_20",
        "bb_width_20",
    )

    # --- volume
    vma20 = v.rolling_mean(20).over(S)
    st1 += [
        _safe(v / v.shift(1).over(S) - 1).alias("volume_chg"),
        _safe(v / vma20).alias("rel_volume_20"),
        _safe((v - vma20) / v.rolling_std(20).over(S)).alias("volume_z_20"),
    ]
    st2.append(_safe(pl.rolling_corr(r1, (v + 1).log(), window_size=20).over(S)).alias("pv_corr_20"))
    tpv = (tp * v).cum_sum().over(D)
    cv = v.cum_sum().over(D)
    st1.append(_safe(tpv / cv).alias("vwap"))
    st2.append(_safe(c / pl.col("vwap") - 1).alias("vwap_dist"))
    fs.add("VOLUME", "volume_chg", "rel_volume_20", "volume_z_20", "pv_corr_20", "vwap_dist")

    # --- intraday (reset per trade_date)
    bar_idx = pl.int_range(pl.len()).over(D)
    minutes = pl.col("ts").dt.hour().cast(pl.Int32) * 60 + pl.col("ts").dt.minute().cast(pl.Int32)
    day_open = o.first().over(D)
    prev_day_close = pl.col("_prev_day_close")
    st1 += [
        bar_idx.alias("_bar_idx"),
        (minutes - (9 * 60 + 15)).alias("min_since_open"),
        ((15 * 60 + 30) - minutes - BAR_MINUTES).alias("min_to_close"),
        _safe(c / day_open - 1).alias("ret_since_open"),
        _safe(h.cum_max().over(D) / lo.cum_min().over(D) - 1).alias("intraday_range"),
        _safe(day_open / prev_day_close - 1).alias("opening_gap"),
    ]
    for k in (5, 15, 30):
        # first-k-minute return is only known once bar k-1 has closed; null before that.
        st2.append(
            pl.when(pl.col("_bar_idx") >= k - 1)
            .then(_safe(pl.col(f"_close_at_{k - 1}") / day_open - 1))
            .otherwise(None)
            .alias(f"first_{k}m_ret")
        )
    for k in (5, 15):
        st1.append(_safe(c / c.shift(k).over(D) - 1).alias(f"last_{k}m_ret"))
    # opening range: running high/low of the first 15 bars, frozen after; distance of close from it.
    in_or = bar_idx < 15
    or_hi = pl.when(in_or).then(h).otherwise(None).cum_max().over(D).forward_fill().over(D)
    or_lo = pl.when(in_or).then(lo).otherwise(None).cum_min().over(D).forward_fill().over(D)
    st1 += [_safe(c / or_hi - 1).alias("or_high_dist"), _safe(c / or_lo - 1).alias("or_low_dist")]
    fs.add(
        "INTRADAY",
        "min_since_open",
        "min_to_close",
        "ret_since_open",
        "intraday_range",
        "opening_gap",
        "first_5m_ret",
        "first_15m_ret",
        "first_30m_ret",
        "last_5m_ret",
        "last_15m_ret",
        "or_high_dist",
        "or_low_dist",
    )
    return [st1, st2, st3]


def _helpers(df: pl.LazyFrame) -> pl.LazyFrame:
    """Causal helpers: previous day's last close; close at bar k of the day (null before bar k)."""
    last = (
        df.group_by(S, "trade_date")
        .agg(pl.col("close").last().alias("_day_close"))
        .sort(S, "trade_date")
        .with_columns(pl.col("_day_close").shift(1).over(S).alias("_prev_day_close"))
        .drop("_day_close")
    )
    idx = pl.int_range(pl.len()).over(D)
    out = df.join(last, on=[S, "trade_date"], how="left", maintain_order="left").sort(S, "ts")
    for k in (4, 14, 29):
        # value of close at bar k, broadcast only to bars >= k (so never visible earlier)
        at_k = pl.when(idx == k).then(pl.col("close")).otherwise(None)
        out = out.with_columns(at_k.forward_fill().over(D).alias(f"_close_at_{k}"))
    return out


def compute_symbol_features(canonical: pl.LazyFrame | pl.DataFrame) -> tuple[pl.DataFrame, FeatureSet]:
    lf = canonical.lazy().sort(S, "ts")
    if "trade_date" not in lf.collect_schema().names():
        lf = lf.with_columns(pl.col("ts").dt.date().alias("trade_date"))
    # joins do not guarantee row order; every shift/rolling below assumes (symbol, ts) order
    lf = _helpers(lf).sort(S, "ts")
    fs = FeatureSet()
    for stage in single_symbol_exprs(fs):
        lf = lf.with_columns(stage)
    helpers = [c for c in lf.collect_schema().names() if c.startswith("_")]
    lf = lf.drop(helpers + ["vwap"]).with_columns(
        (pl.col("ts") + timedelta(minutes=BAR_MINUTES)).alias("availability_ts"),
        pl.col("ts").alias("feature_ts"),
        pl.lit(FEATURE_VERSION).alias("feature_version"),
    )
    return lf.collect(), fs


MARKET_COLS = ("ret_1", "ret_5", "ret_15", "ret_60", "rsi_14", "vol_20", "sma_50_ratio", "adx_14")


def add_market_context(
    feats: pl.DataFrame, index_feats: pl.DataFrame, prefix: str, fs: FeatureSet
) -> pl.DataFrame:
    """Join an index's own same-bar features (e.g. NIFTY 50). Same ts => same availability."""
    cols = [c for c in MARKET_COLS if c in index_feats.columns]
    right = index_feats.select("ts", *[pl.col(c).alias(f"{prefix}_{c}") for c in cols])
    fs.add("MARKET", *[f"{prefix}_{c}" for c in cols])
    return feats.join(right, on="ts", how="left", maintain_order="left")


def add_level(
    feats: pl.DataFrame, series: pl.DataFrame, name: str, fs: FeatureSet, group: str = "MARKET"
) -> pl.DataFrame:
    """Join another instrument's same-bar close as a level feature (e.g. INDIA VIX, which is a
    volatility percentage and not split-adjusted, so its level is meaningful)."""
    right = series.select("ts", pl.col("close").alias(name))
    fs.add(group, name)
    return feats.join(right, on="ts", how="left", maintain_order="left")


def add_relative_strength(
    feats: pl.DataFrame, fs: FeatureSet, sector: pl.DataFrame | None = None
) -> pl.DataFrame:
    """Cross-sectional features per timestamp, leave-one-out so a stock never averages itself in."""
    exprs = []
    names = []
    for k in (5, 15, 60):
        r = pl.col(f"ret_{k}")
        n = r.count().over("ts")
        loo = (r.sum().over("ts") - r) / (n - 1)
        exprs.append(_safe(pl.when(n > 1).then(r - loo).otherwise(None)).alias(f"rel_ret_{k}"))
        names.append(f"rel_ret_{k}")
    exprs += [
        (pl.col("ret_15").rank("average").over("ts") / pl.col("ret_15").count().over("ts")).alias(
            "rs_rank_15"
        ),
        (
            pl.col("rel_volume_20").rank("average").over("ts") / pl.col("rel_volume_20").count().over("ts")
        ).alias("volume_rank"),
        (pl.col("vol_20").rank("average").over("ts") / pl.col("vol_20").count().over("ts")).alias(
            "volatility_rank"
        ),
        pl.col("symbol").count().over("ts").alias("xs_count"),
    ]
    # market breadth: share of the *other* stocks up over 15 minutes (leave-one-out)
    up = (pl.col("ret_15") > 0).cast(pl.Float64)
    others = pl.col("ret_15").count().over("ts") - pl.col("ret_15").is_not_null().cast(pl.Int64)
    exprs.append(
        _safe(
            pl.when(others > 0).then((up.sum().over("ts") - up.fill_null(0)) / others).otherwise(None)
        ).alias("breadth_15")
    )
    names += ["rs_rank_15", "volume_rank", "volatility_rank", "breadth_15"]
    out = feats.with_columns(exprs)
    if sector is not None:
        out = out.join(sector, on="symbol", how="left", maintain_order="left")
        r = pl.col("ret_15")
        g = ["ts", "sector"]
        n = r.count().over(g)
        loo = (r.sum().over(g) - r) / (n - 1)
        out = out.with_columns(_safe(pl.when(n > 1).then(r - loo).otherwise(None)).alias("sector_rel_ret_15"))
        names.append("sector_rel_ret_15")
    fs.add("RELATIVE", *names)
    return out
