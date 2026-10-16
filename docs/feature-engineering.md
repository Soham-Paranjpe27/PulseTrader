# Feature engineering

Single engine: `ml/src/pulsetrader/features/engine.py`, version `features-v1`. Training and live
inference must both call `compute_symbol_features` (+ `add_market_context`, `add_relative_strength`).

Groups (names from `FeatureSet.group`): OHLCV (returns 1–60m, gap, body, wicks, range, close
position), TECHNICAL (SMA 5–200 and EMA 5–50 ratios, RSI14, ROC10, stochastic, Williams %R,
CCI20, MACD/signal/hist, ADX/DI, ATR, volatilities, Bollinger width), VOLUME (change, relative
volume, z-score, log volume, price–volume correlation, distance from session VWAP), INTRADAY
(minutes since open / to close, return since open, intraday range, opening gap, first 5/15/30-minute
returns, last 5/15-minute returns, opening-range distances), MARKET (index's own same-bar features,
e.g. NIFTY), RELATIVE (leave-one-out relative returns, cross-sectional ranks, optional sector).

Notes
- Price-level features are expressed as ratios to close so they are comparable across symbols.
- CCI uses rolling standard deviation instead of mean absolute deviation (`cci_20_std`), because MAD
  has no vectorised rolling form; documented deviation from the textbook formula.
- inf/NaN are mapped to null. Imputation (train medians) and scaling happen only in `Preprocessor`.
- `feature_ts = ts` (bar open), `availability_ts = ts + 1 min` (bar close). Predictions for bar t are
  made at `availability_ts`.
- Sector features need a sector mapping, which the dataset does not contain. Not yet available.
- India VIX / BANK NIFTY / breadth are added only if present in the real data.
