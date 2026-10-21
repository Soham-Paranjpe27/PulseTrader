# Phase 12 — portfolio backtests (validation)

Dataset `dataset-v1-features-v2-labels-v1-u100-s5`. Signals: Phase 9 walk-forward predictions of the validation fold (2024-11-05..2025-06-13). Test period not used.
Each strategy is traded by the same event-driven engine (`pulsetrader.backtest.engine`): entry at
the next bar's open, exit at the close of the label horizon or the session close, one position
per symbol, at most 10 positions of 10% of equity each, Indian intraday charges (brokerage capped
at Rs 20, STT on sells, exchange, SEBI, stamp duty, GST) and 1 bp slippage per side. The charge
rates are illustrative defaults and must be checked against current broker and exchange rates.

## lightgbm (tuned) — `y_1m_5bp`, hold 1 min

Round-trip cost 10.2 bp. Gate chosen on pre-validation folds: P(direction) >= 0.60.

| Strategy | Costs | Trades | Total return | CAGR | Sharpe | Sortino | Calmar | Max DD | Win rate | Profit factor | Avg trade (bp) | Median trade (bp) | Costs paid (Rs) | Turnover/day | Exposure |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| model | yes | 100,327 | -100.00% | -100.00% | -225.80 | -15.84 | -1.00 | -100.00% | 11.02% | 0.10 | -12.18 | -12.60 | 852,495 | 134.67 | 17.96% |
| model | no | 103,611 | 47.88% | 93.81% | 7.54 | 7.57 | 24.50 | -3.83% | 48.51% | 1.09 | 0.38 | 0.00 | 0 | 139.08 | 18.54% |
| model_gated | yes | 1,059 | -9.52% | -15.56% | -12.61 | -9.17 | -1.63 | -9.56% | 19.45% | 0.19 | -9.44 | -10.36 | 85,390 | 1.42 | 0.19% |
| model_gated | no | 1,061 | 1.13% | 1.92% | 1.75 | 1.82 | 2.00 | -0.96% | 48.54% | 1.22 | 1.06 | 0.00 | 0 | 1.42 | 0.19% |
| momentum | yes | 100,466 | -100.00% | -100.00% | -264.15 | -15.85 | -1.00 | -100.00% | 10.14% | 0.11 | -12.82 | -12.61 | 824,746 | 134.85 | 17.98% |
| momentum | no | 103,489 | -23.69% | -36.70% | -6.16 | -5.23 | -1.51 | -24.33% | 44.77% | 0.94 | -0.26 | 0.00 | 0 | 138.91 | 18.52% |
| naive_random | yes | 100,327 | -100.00% | -100.00% | -333.82 | -15.86 | -1.00 | -100.00% | 10.57% | 0.11 | -12.52 | -12.60 | 839,486 | 134.67 | 17.96% |
| naive_random | no | 102,568 | 3.22% | 5.51% | 0.99 | 1.15 | 1.82 | -3.03% | 46.21% | 1.01 | 0.03 | 0.00 | 0 | 137.68 | 18.36% |
| naive_long | yes | 100,327 | -100.00% | -100.00% | -218.32 | -15.83 | -1.00 | -100.00% | 10.62% | 0.11 | -12.48 | -12.60 | 846,908 | 134.67 | 17.96% |
| naive_long | no | 102,754 | 8.28% | 14.40% | 1.58 | 1.64 | 1.84 | -7.83% | 45.73% | 1.02 | 0.08 | 0.00 | 0 | 137.92 | 18.39% |
| buy_and_hold | yes | 200 | 1.53% | 2.59% | 0.23 | 0.22 | 0.17 | -14.90% | – | – | – | – | 1,071 | 0.00 | 100.00% |
| buy_and_hold | no | 200 | 1.65% | 2.81% | 0.24 | 0.23 | 0.19 | -14.89% | – | – | – | – | 0 | 0.00 | 100.00% |

## lightgbm (tuned) — `y_5m_10bp`, hold 5 min

Round-trip cost 10.2 bp. Gate chosen on pre-validation folds: P(direction) >= 0.56.

| Strategy | Costs | Trades | Total return | CAGR | Sharpe | Sortino | Calmar | Max DD | Win rate | Profit factor | Avg trade (bp) | Median trade (bp) | Costs paid (Rs) | Turnover/day | Exposure |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| model | yes | 98,527 | -100.00% | -100.00% | -115.33 | -15.73 | -1.00 | -100.00% | 27.81% | 0.33 | -12.33 | -11.75 | 829,451 | 132.25 | 88.17% |
| model | no | 100,790 | 21.31% | 38.65% | 1.90 | 1.89 | 3.41 | -11.33% | 50.86% | 1.02 | 0.20 | 0.78 | 0 | 135.29 | 90.19% |
| model_gated | yes | 4,640 | -34.36% | -50.93% | -11.35 | -8.33 | -1.48 | -34.45% | 36.44% | 0.52 | -9.05 | -8.83 | 349,945 | 6.23 | 4.15% |
| model_gated | no | 4,682 | 12.02% | 21.16% | 3.73 | 4.38 | 14.08 | -1.50% | 52.97% | 1.20 | 2.45 | 2.79 | 0 | 6.28 | 4.19% |
| momentum | yes | 99,125 | -100.00% | -100.00% | -123.10 | -15.75 | -1.00 | -100.00% | 23.53% | 0.32 | -12.92 | -13.47 | 834,681 | 133.05 | 88.70% |
| momentum | no | 102,550 | -32.14% | -48.09% | -3.63 | -3.41 | -1.40 | -34.39% | 46.30% | 0.96 | -0.37 | -0.91 | 0 | 137.65 | 91.77% |
| naive_random | yes | 98,527 | -100.00% | -100.00% | -167.28 | -15.80 | -1.00 | -100.00% | 26.90% | 0.34 | -12.46 | -12.60 | 851,631 | 132.25 | 88.17% |
| naive_random | no | 101,625 | 10.26% | 17.96% | 1.37 | 1.42 | 1.75 | -10.27% | 49.13% | 1.01 | 0.10 | 0.00 | 0 | 136.41 | 90.94% |
| naive_long | yes | 98,527 | -100.00% | -100.00% | -91.56 | -15.64 | -1.00 | -100.00% | 26.18% | 0.35 | -12.42 | -12.60 | 841,091 | 132.25 | 88.17% |
| naive_long | no | 100,712 | 9.79% | 17.12% | 0.80 | 0.83 | 1.17 | -14.64% | 47.62% | 1.01 | 0.10 | -0.34 | 0 | 135.18 | 90.12% |
| buy_and_hold | yes | 200 | 1.53% | 2.59% | 0.23 | 0.22 | 0.17 | -14.90% | – | – | – | – | 1,071 | 0.00 | 100.00% |
| buy_and_hold | no | 200 | 1.65% | 2.81% | 0.24 | 0.23 | 0.19 | -14.89% | – | – | – | – | 0 | 0.00 | 100.00% |
## Findings
- Before costs the model has an edge over every baseline: 1m model +47.9% (Sharpe 7.5, avg trade 0.38 bp)
  vs momentum -23.7%, random direction +3.2%, always-long +8.3%; 5m model +21.3% vs momentum -32.1%,
  random +10.3%, always-long +9.8%. Buy-and-hold made +1.5% after costs (max DD -14.9%).
- After costs every intraday strategy loses. Ungated model, momentum and naive strategies all go to
  about zero equity (~100k trades, about 12 bp of costs per trade against 0.1-0.4 bp of gross edge).
- The pre-validation gate cuts trading by ~95% and raises the gross edge (1m 1.06 bp, 5m 2.45 bp per
  trade, 5m win rate 53.0%, profit factor 1.20), but it is still far below the ~10 bp round trip:
  1m gated -9.5%, 5m gated -34.4% after costs.
- Conclusion: the signal is real but roughly 4-10x too small to pay Indian intraday costs at these
  horizons. Nothing here is tradeable; the test period stays unused.
