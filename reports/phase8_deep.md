# Phase 8 — deep sequence models (validation) — IN PROGRESS

Paused 2026-10-17 by request: stage C still needs y_30m_20bp and y_60m_30bp.

Dataset `dataset-v1-features-v2-labels-v1-u100-s5`. Trained on 2022-01-03..2024-11-04, scored on validation 2024-11-05..2025-06-13. Test period not used. PyTorch on 4 CPU threads, no GPU.

Each time step is one 5-minute dataset row of the same stock (84 features after the train-fitted
preprocessor). Stage A compares architectures at 60 steps on `y_5m_10bp`; stage B varies the
history length for the best architecture (samples per epoch scaled by 60/length, 4 epochs max);
stage C runs the best (architecture, length) on the best Phase 7 threshold of each other horizon.
Selection uses validation MCC.

| Label | Model | Steps | Accuracy | Balanced acc | Macro F1 | MCC | ROC-AUC | Up/down AUC* | Brier | ECE | Train-sample acc | Best Phase 7 (MCC) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| y_5m_10bp | lstm | 60 | 56.4% | 38.9% | 0.363 | 0.153 | 0.648 | 0.533 | 0.558 | 0.012 | 57.6% | xgboost (0.157) |
| y_5m_10bp | gru | 60 | 56.3% | 38.6% | 0.359 | 0.150 | 0.650 | 0.534 | 0.557 | 0.016 | 57.4% | xgboost (0.157) |
| y_5m_10bp | lstm_attn | 60 | 56.3% | 39.0% | 0.366 | 0.154 | 0.650 | 0.532 | 0.557 | 0.015 | 57.6% | xgboost (0.157) |
| y_5m_10bp | gru_attn | 60 | 56.4% | 39.0% | 0.365 | 0.155 | 0.650 | 0.533 | 0.557 | 0.014 | 57.5% | xgboost (0.157) |
| y_5m_10bp | transformer | 60 | 56.3% | 39.1% | 0.364 | 0.157 | 0.650 | 0.529 | 0.558 | 0.016 | 57.1% | xgboost (0.157) |
| y_5m_10bp | transformer | 30 | 56.5% | 38.2% | 0.348 | 0.146 | 0.650 | 0.539 | 0.557 | 0.011 | 57.3% | xgboost (0.157) |
| y_5m_10bp | transformer | 120 | 56.4% | 39.4% | 0.370 | 0.161 | 0.652 | 0.537 | 0.557 | 0.009 | 57.2% | xgboost (0.157) |
| y_5m_10bp | transformer | 252 | 56.4% | 37.7% | 0.338 | 0.139 | 0.648 | 0.533 | 0.558 | 0.015 | 57.0% | xgboost (0.157) |
| y_1m_5bp | transformer | 120 | 59.1% | 39.4% | 0.375 | 0.167 | 0.667 | 0.584 | 0.533 | 0.016 | 58.1% | lightgbm (0.166) |
| y_15m_20bp | transformer | 120 | 61.2% | 37.2% | 0.336 | 0.136 | 0.655 | 0.517 | 0.519 | 0.006 | 63.0% | xgboost (0.134) |

*Up/down AUC: diagnostic on rows whose label moved (subset chosen by the outcome).

## Selective UP/DOWN (best deep run per label)

| Label | Model | P threshold | Predictions | Coverage | Accuracy | Sign accuracy | MCC |
|---|---|---|---|---|---|---|---|
| y_5m_10bp | transformer L120 | 0.40 | 78,630 | 7.1% | 39.9% | 51.8% | 0.026 |
| y_5m_10bp | transformer L120 | 0.50 | 2,537 | 0.2% | 44.5% | 52.0% | 0.011 |
| y_5m_10bp | transformer L120 | 0.60 | 1 | 0.0% | 0.0% | 0.0% | 0.000 |
| y_5m_10bp | transformer L120 | 0.70 | 0 | 0.0% | – | – | – |
| y_5m_10bp | transformer L120 | 0.80 | 0 | 0.0% | – | – | – |
| y_5m_10bp | transformer L120 | 0.90 | 0 | 0.0% | – | – | – |
| y_1m_5bp | transformer L120 | 0.40 | 70,880 | 6.3% | 40.7% | 51.5% | 0.047 |
| y_1m_5bp | transformer L120 | 0.50 | 2,935 | 0.3% | 44.6% | 51.1% | 0.030 |
| y_1m_5bp | transformer L120 | 0.60 | 3 | 0.0% | 66.7% | 66.7% | 0.000 |
| y_1m_5bp | transformer L120 | 0.70 | 0 | 0.0% | – | – | – |
| y_1m_5bp | transformer L120 | 0.80 | 0 | 0.0% | – | – | – |
| y_1m_5bp | transformer L120 | 0.90 | 0 | 0.0% | – | – | – |
| y_15m_20bp | transformer L120 | 0.40 | 45,996 | 4.3% | 37.9% | 51.5% | 0.022 |
| y_15m_20bp | transformer L120 | 0.50 | 1,496 | 0.1% | 49.1% | 60.4% | 0.061 |
| y_15m_20bp | transformer L120 | 0.60 | 2 | 0.0% | 50.0% | 50.0% | 0.000 |
| y_15m_20bp | transformer L120 | 0.70 | 0 | 0.0% | – | – | – |
| y_15m_20bp | transformer L120 | 0.80 | 0 | 0.0% | – | – | – |
| y_15m_20bp | transformer L120 | 0.90 | 0 | 0.0% | – | – | – |
