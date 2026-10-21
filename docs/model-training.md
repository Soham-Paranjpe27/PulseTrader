# Model training

All numbers are measured on real data; full tables in `reports/`. Labels: 3 classes (DOWN / NEUTRAL /
UP) for a move beyond a threshold over a horizon, e.g. `y_5m_10bp` = 5 minutes, 0.10%. Because NEUTRAL
dominates, every result reports accuracy together with balanced accuracy, MCC and coverage.

## Data
`core100_s5`: the 100 most liquid eligible equities (chosen on 2022 turnover), rows every 5 minutes,
84 scale-free features (features-v2), labels for 1/5/15/30/60 minutes at 5-50 bp. Train 5,227,860 rows,
validation 1,116,225, test 1,123,575 (untouched).

## Phases
| Phase | What was trained | Result (validation) |
|---|---|---|
| 7 classical | majority, random, momentum, logistic, LightGBM on 25 labels; RF and XGBoost on two thresholds | best MCC 0.166 (LightGBM y_1m_5bp, acc 59.3% vs majority 58.1%); high accuracies are majority-NEUTRAL behaviour |
| 8 deep | LSTM, GRU, attention, transformer on sequences of 30-252 rows | transformer L=120 ties boosting (MCC 0.167 on y_1m_5bp) |
| 9 optimisation | 5-fold expanding walk-forward, Optuna (25 TPE trials on F3+F4), feature selection, ensembles | tuned LightGBM y_1m_5bp MCC 0.194 (acc 50.1%, balanced 45.2%); y_5m_10bp 0.168; ensembles no gain |
| 10 calibration | Platt and isotonic on out-of-fold predictions | isotonic: classwise ECE 0.14 -> 0.02; decisions keep raw argmax |
| 11 robustness | stocks, regimes, sectors, time of day, time | edge broad (all 100 stocks MCC > 0) but weak at the open and shrinking over time |
| 12 backtest | event-driven, Indian intraday costs (~10.2 bp round trip) | positive before costs, every strategy loses after costs |

## Registered models
`lightgbm-y_1m_5bp-tuned@v1` and `lightgbm-y_5m_10bp-tuned@v1`, status CANDIDATE: refit on the
expanding window before validation, early stopping on the last 10% of training dates (purged), balanced
class weights, seed fixed, 4 threads. Artifacts: LightGBM booster, preprocessor, feature list,
isotonic calibrator, serving rules, SHA-256 digests. Model card: docs/model-card.md.

## Reproduce
```
cd ml
PULSETRADER_DATA_DIR=../data .venv/bin/pulsetrader optimize --steps WT     # Phase 9 walk-forward + tuning
PULSETRADER_DATA_DIR=../data .venv/bin/pulsetrader calibrate
PULSETRADER_DATA_DIR=../data .venv/bin/pulsetrader registry register
PULSETRADER_DATA_DIR=../data .venv/bin/pulsetrader repro                  # Phase 20 check
```
`repro` refits each registered model from its walk-forward experiment and requires byte-identical
artifact files and the stored validation predictions (max diff 3e-8, reports/phase20_repro.md).
