# Backtesting (Phase 12)

Code: `ml/src/pulsetrader/backtest/engine.py` (engine) and `ml/src/pulsetrader/experiments/backtest.py`
(runner). Command: `PULSETRADER_DATA_DIR=../data .venv/bin/pulsetrader backtest` writes
`data/experiments/*-p12-backtest-*` and `reports/phase12_backtest.{md,json}`.

## Timing (no look-ahead)
- A prediction at bar `t` uses features up to bar `t`'s close, so it is known at `t + 1 min`.
- Entry: open of bar `t+1`, moved against the trader by `slippage_bp`.
- Exit: close of bar `t + horizon`, or the last bar of the session if that comes first. An optional
  stop-loss / take-profit is checked on each bar's low/high; if both are touched in one bar, the
  stop is assumed to fill first.
- No trade when the signal bar is the last bar of its session.

## Portfolio
- Event loop over entries and exits in time order. Exits at or before an entry time are processed first.
- One open position per symbol, at most `max_positions` (10), each `position_frac` (10%) of current
  equity, long or short (intraday shorting in Indian cash equities).
- When several signals share a bar, higher `priority` (model: P(direction)) is taken first.
- Skipped entries are counted: symbol already held, book full, not enough cash.

## Costs (`CostConfig`, illustrative; check current broker and exchange rates)
| Charge | Default |
|---|---|
| Brokerage | 3 bp per order, capped at Rs 20 |
| STT (intraday) | 2.5 bp on the sell side |
| NSE transaction charge | 0.297 bp both sides |
| SEBI fee | 0.01 bp both sides |
| Stamp duty | 0.3 bp on the buy side |
| GST | 18% of brokerage + exchange + SEBI |
| Slippage | 1 bp per side, in the fill price |

At a Rs 1 lakh position this is about 10 bp per round trip including slippage. Buy-and-hold uses the
same charges (delivery STT is higher in practice, so its cost is understated slightly; it trades twice).

## Metrics
Daily closing equity over every validation trading day: total return, CAGR (252 days), Sharpe and
Sortino (daily, annualised), Calmar, max drawdown; per trade: win rate, profit factor, average and median
return on margin (bp), costs paid, gross and net P&L; turnover per day (traded notional / capital) and
exposure (notional-minutes / capital × session minutes).

## Strategies compared
`model` (every UP/DOWN call), `model_gated` (P(direction) gate chosen on pre-validation folds by net
per-call return), `momentum` (Phase 7 baseline), `naive_random` (coin-flip direction at the model's
signal times, seed 0), `naive_long` (always long at the model's signal times), `buy_and_hold`
(equal weight). Each with costs and with zero costs. Only validation bars are read.
