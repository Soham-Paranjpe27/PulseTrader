# Feature engineering

Single engine: `ml/src/pulsetrader/features/engine.py`, version `features-v2`. Training and live
inference must both call `compute_symbol_features` (+ `add_market_context`, `add_relative_strength`).

Groups (names from `FeatureSet.group`): OHLCV (returns 1–60m, gap, body, wicks, range, close
position), TECHNICAL (SMA 5–200 and EMA 5–50 ratios, RSI14, ROC10, stochastic, Williams %R,
CCI20, MACD/signal/hist, ADX/DI, ATR as % of close, volatilities, Bollinger width), VOLUME (change,
relative volume, z-score, price–volume correlation, distance from session VWAP), INTRADAY
(minutes since open / to close, return since open, intraday range, opening gap, first 5/15/30-minute
returns, last 5/15-minute returns, opening-range distances), MARKET (index's own same-bar features,
NIFTY and BANKNIFTY, plus the INDIA VIX level), RELATIVE (leave-one-out relative returns,
cross-sectional ranks, leave-one-out breadth = share of other stocks up over 15 minutes, optional sector).

Notes
- Only scale-free features are allowed. The vendor back-adjusts prices for splits and bonuses, so
  a raw price or volume level on a past date depends on actions announced later (look-ahead).
  features-v2 therefore removed `atr_14` (price units) and `log_volume` (share units); ATR is kept
  only as `atr_pct_14`. Ratios, returns and z-scores are unchanged by back-adjustment.
- INDIA VIX is a volatility percentage and is never split-adjusted, so its level is a valid feature.
- CCI uses rolling standard deviation instead of mean absolute deviation (`cci_20_std`), because MAD
  has no vectorised rolling form; documented deviation from the textbook formula.
- inf/NaN are mapped to null. Imputation (train medians) and scaling happen only in `Preprocessor`.
- `feature_ts = ts` (bar open), `availability_ts = ts + 1 min` (bar close). Predictions for bar t are
  made at `availability_ts`.
- Sector features need a sector mapping, which the dataset does not contain. Not yet available.
- Research datasets (`datasets/build.py`) compute features per symbol over its full history (so long
  windows warm up), drop the first 250 bars, then sample every 5 minutes on a common clock so each
  sampled timestamp holds the whole cross-section.
