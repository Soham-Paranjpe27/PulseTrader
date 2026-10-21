# Model card: PulseTrader tuned LightGBM direction models

Status: **CANDIDATE, research only. Not tradeable. No PRODUCTION model exists.** Test gate PASSED,
backtest gate FAILED.
Every number below was measured on real NSE data (reports/ and data/registry/registry.json). Nothing
here reaches the 70-80% accuracy target in the spec, and no number claims it does.

## Models
| | lightgbm-y_1m_5bp-tuned@v1 | lightgbm-y_5m_10bp-tuned@v1 |
|---|---|---|
| Predicts | Direction of the close 1 minute ahead: UP / NEUTRAL / DOWN with a ±0.05% band | 5 minutes ahead with a ±0.10% band |
| Algorithm | LightGBM multiclass, balanced class weights, Optuna-tuned (25 trials, Phase 9) | same |
| Inputs | 84 scale-free features (features-v2): price/volume technicals, intraday context, NIFTY and VIX market context, cross-sectional ranks | same |
| Probability | Isotonic calibration fit on walk-forward folds (Phase 10) | same |
| Artifacts | `data/registry/artifacts/<id>/v1/` with `sha256.json`; the ML service refuses changed files | same |

## Data
- Universe: top 100 NSE equities by median daily turnover over 2022-01-03..2023-01-04 (chosen with
  training-period information only). Rows every 5 minutes of the regular session; first 250 bars of
  history, short sessions and corporate-action sessions excluded.
- Train 2022-01-03..2024-11-04 (5,227,860 rows), validation 2024-11-05..2025-06-13 (1,116,225), test
  2025-06-16..2026-01-21 (1,123,575, **never read**). 60-minute purge and embargo between splits.
- Known biases: survivorship (delisted stocks absent from the source), vendor back-adjusted prices
  (only scale-free features used), large liquid stocks only.

## Performance (validation, full coverage)
| Metric | 1m_5bp | 5m_10bp |
|---|---|---|
| Accuracy | 50.1% (majority class 58.1%) | 48.0% (majority 55.1%) |
| Balanced accuracy | 45.2% (chance 33.3%) | 43.1% |
| MCC | 0.194 (momentum rule 0.089) | 0.168 (momentum 0.087) |
| ROC AUC (one vs rest) | 0.667 | 0.646 |
| Brier raw / calibrated | 0.601 / 0.532 | 0.618 / 0.558 |
| Walk-forward MCC (4 pre-validation folds) | 0.223 ± 0.018 | 0.200 ± 0.010 |
| Coverage | 100% | 100% |

Accuracy is below the majority-class rate because balanced class weights trade NEUTRAL hits for UP/DOWN
recall; MCC and balanced accuracy are the meaningful measures here.

### Selective (confidence-gated) calls
The ML service abstains unless the calibrated directional probability clears a gate chosen on
pre-validation folds. In the Phase 18 REPLAY of the last 20 validation sessions (300k predictions):
| | 1m_5bp | 5m_10bp |
|---|---|---|
| Calls / coverage | 47 / 0.03% | 401 / 0.27% |
| Call accuracy / BA / MCC | 40.4% / 29.4% / -0.133 | 43.1% / 42.2% / 0.163 |
| Net per call after 10.24 bp costs | -13.7 bp | -6.4 bp |
These are REPLAY figures (recorded data replayed through the live pipeline), not LIVE.

### Final test period (2025-06-16..2026-01-21, run once on 2026-10-20)
Frozen artifacts, no refit or tuning (reports/final_test.md). Gate `test_passed`: PASSED for both.
| Metric | 1m_5bp | 5m_10bp |
|---|---|---|
| Rows | 1,123,575 | 1,108,578 |
| Accuracy | 62.4% (majority class 69.0%) | 61.2% (majority 66.2%) |
| Balanced accuracy | 44.0% | 42.5% |
| MCC | 0.200 (momentum 0.100) | 0.186 (momentum 0.098) |
| ROC AUC | 0.682 | 0.663 |
| Classwise ECE raw / calibrated | 0.148 / 0.029 | 0.136 / 0.016 |
| Service calls / coverage | 349 / 0.03% | 1,774 / 0.16% |
| Call accuracy / MCC / sign right | 47.9% / 0.213 / 59.3% | 36.2% / 0.054 / 53.5% |
| Net per call after costs | -6.8 bp | -8.1 bp |
| Gated backtest after costs | -3.1% | -13.8% (buy-and-hold +3.9%) |
The test result matches validation (MCC 0.194 / 0.168), so the edge held out of sample and every month
stayed between MCC 0.17 and 0.20. Accuracy rose only because the test period was quieter (more NEUTRAL
rows); it is still below the majority-class rate. Still not tradeable. The test period is now used.

## Economic result (Phase 12 backtest, validation)
Zero costs: 1m +47.9%, 5m +21.3% (beating momentum, random and always-long baselines). With Indian
intraday charges and 1 bp slippage per side (~10.2 bp round trip) every strategy loses: ungated ~-100%,
gated -9.5% (1m) and -34.4% (5m). The signal is real but 4-10x too small for intraday costs. Registry
gate `backtest_passed`: FAILED.

## Where it works and where it does not (Phase 11, Phase 19)
- Positive MCC on all 100 stocks and in every trend, volatility and sector bucket (0.16-0.21 on 1m).
- Weak in the first 30 minutes of the session (MCC 0.04).
- Skill is mostly "will it move" rather than "which way" (55.8% sign accuracy on moved, called rows).
- Edge is shrinking: fold MCC 0.241 (2023) -> 0.194 (validation). Monitoring flags January 2025 as
  MODEL_DRIFT_DETECTED (accuracy drop); input features do not drift measurably.

## Intended use
Research and paper evaluation of short-horizon direction signals on liquid NSE stocks, shown with its
coverage and REPLAY/LIVE mode. **Not** for real-money trading, not for other markets, not for illiquid
or newly listed stocks, not for the first 30 minutes of the session.

## Reproducibility
Phase 20 refit from the registry recipe gives byte-identical model, preprocessor, feature list and
calibrator files; validation predictions match within 2.98e-08 (reports/phase20_repro.md). Dataset
rows rebuilt from canonical bars match the stored dataset exactly.
