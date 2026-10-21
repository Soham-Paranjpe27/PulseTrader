# Phase 19: drift monitoring on real data

References: features from the training split (2022-01-03..2024-11-04, every 8th row); predictions, accuracy and calibration from the model's walk-forward folds before validation (out-of-sample); regime mix from training-period days. The monitor then ran over the validation period 2024-11-05..2025-06-13 month by month and week by week, as it would over live windows (validation rows equal live features and probabilities, Phase 17; outcomes equal live outcomes, Phase 18). Test period not read.

Thresholds are calibrated per window length (day, week, month) on historical windows of the same length: WARN when a window is more extreme than 95% of them, DRIFT beyond 99% (MCC and accuracy: below the 5% / 1% quantiles of out-of-sample fold windows; ECE: above the 95% / 99% quantiles; PSI: above the 95% / 99% quantiles of training windows, at least 0.1 / 0.25). MODEL_DRIFT_DETECTED = accuracy or calibration DRIFT, or feature and prediction DRIFT together. The model is never replaced automatically.

## Reference folds (walk-forward, out-of-sample, raw probabilities)

| model | fold | period | rows | accuracy | balanced acc | MCC | ECE top |
|---|---|---|---|---|---|---|---|
| lightgbm-y_1m_5bp-tuned@v1 | F1 | 2023-02-17..2023-07-21 | 778724 | 0.596 | 0.473 | 0.241 | 0.079 |
| lightgbm-y_1m_5bp-tuned@v1 | F2 | 2023-07-24..2023-12-26 | 786200 | 0.580 | 0.472 | 0.235 | 0.063 |
| lightgbm-y_1m_5bp-tuned@v1 | F3 | 2023-12-27..2024-06-03 | 784350 | 0.504 | 0.465 | 0.210 | 0.031 |
| lightgbm-y_1m_5bp-tuned@v1 | F4 | 2024-06-04..2024-11-04 | 786284 | 0.519 | 0.457 | 0.205 | 0.036 |
| lightgbm-y_5m_10bp-tuned@v1 | F1 | 2023-02-17..2023-07-21 | 768326 | 0.603 | 0.439 | 0.209 | 0.095 |
| lightgbm-y_5m_10bp-tuned@v1 | F2 | 2023-07-24..2023-12-26 | 775600 | 0.584 | 0.444 | 0.208 | 0.102 |
| lightgbm-y_5m_10bp-tuned@v1 | F3 | 2023-12-27..2024-06-03 | 773800 | 0.495 | 0.447 | 0.190 | 0.036 |
| lightgbm-y_5m_10bp-tuned@v1 | F4 | 2024-06-04..2024-11-04 | 775787 | 0.509 | 0.443 | 0.191 | 0.042 |

## lightgbm-y_1m_5bp-tuned@v1: monthly windows (1116225 validation rows)

Each cell: value (WARN / DRIFT threshold for a window of that length).

| month | days | status | MCC | accuracy | ECE top | feature weighted PSI | prediction PSI | regime PSI | most shifted features (PSI) |
|---|---|---|---|---|---|---|---|---|---|
| 2024-11 | 17 | WARN | 0.179 (0.185 / 0.177) | 0.477 (0.470 / 0.446) | 0.029 (0.088 / 0.090) | 0.131 (0.345 / 0.500) | 0.204 (0.182 / 0.422) | 6.20 (8.22 / 9.95) | gap 0.15, vix_level 5.74, nifty_vol_20 0.10 |
| 2024-12 | 21 | OK | 0.199 (0.185 / 0.177) | 0.549 (0.470 / 0.446) | 0.070 (0.088 / 0.090) | 0.118 (0.345 / 0.500) | 0.058 (0.182 / 0.422) | 3.09 (8.22 / 9.95) | gap 0.15, vix_level 5.24, opening_gap 0.13 |
| 2025-01 | 23 | MODEL_DRIFT_DETECTED | 0.163 (0.185 / 0.177) | 0.453 (0.470 / 0.446) | 0.031 (0.088 / 0.090) | 0.138 (0.345 / 0.500) | 0.285 (0.182 / 0.422) | 5.57 (8.22 / 9.95) | gap 0.17, vix_level 4.28, atr_pct_14 0.17 |
| 2025-02 | 19 | WARN | 0.184 (0.185 / 0.177) | 0.464 (0.470 / 0.446) | 0.033 (0.088 / 0.090) | 0.130 (0.345 / 0.500) | 0.242 (0.182 / 0.422) | 8.03 (8.22 / 9.95) | gap 0.15, vix_level 5.00, intraday_range 0.20 |
| 2025-03 | 19 | OK | 0.196 (0.185 / 0.177) | 0.505 (0.470 / 0.446) | 0.039 (0.088 / 0.090) | 0.113 (0.345 / 0.500) | 0.113 (0.182 / 0.422) | 5.47 (8.22 / 9.95) | gap 0.17, vix_level 5.85, banknifty_vol_20 0.20 |
| 2025-04 | 19 | WARN | 0.192 (0.185 / 0.177) | 0.476 (0.470 / 0.446) | 0.034 (0.088 / 0.090) | 0.078 (0.345 / 0.500) | 0.209 (0.182 / 0.422) | 3.25 (8.22 / 9.95) | gap 0.15, or_low_dist 0.13, vix_level 2.54 |
| 2025-05 | 21 | OK | 0.201 (0.185 / 0.177) | 0.528 (0.470 / 0.446) | 0.056 (0.088 / 0.090) | 0.108 (0.345 / 0.500) | 0.074 (0.182 / 0.422) | 7.61 (8.22 / 9.95) | gap 0.17, vix_level 5.46, banknifty_vol_20 0.10 |
| 2025-06 | 10 | MODEL_DRIFT_DETECTED | 0.212 (0.185 / 0.177) | 0.598 (0.470 / 0.446) | 0.094 (0.088 / 0.090) | 0.169 (0.345 / 0.500) | 0.038 (0.182 / 0.422) | 2.99 (8.22 / 9.95) | banknifty_ret_60 0.25, gap 0.16, vix_level 4.38 |

Weekly windows (32): MODEL_DRIFT_DETECTED 4, OK 21, WARN 7.
Per component (weeks): feature: OK 32; prediction: DRIFT 1, OK 28, WARN 3; accuracy: DRIFT 3, OK 23, WARN 6; calibration: DRIFT 1, OK 30, WARN 1; regime: OK 32.

## lightgbm-y_5m_10bp-tuned@v1: monthly windows (1101326 validation rows)

Each cell: value (WARN / DRIFT threshold for a window of that length).

| month | days | status | MCC | accuracy | ECE top | feature weighted PSI | prediction PSI | regime PSI | most shifted features (PSI) |
|---|---|---|---|---|---|---|---|---|---|
| 2024-11 | 17 | WARN | 0.144 (0.156 / 0.138) | 0.453 (0.449 / 0.410) | 0.021 (0.111 / 0.130) | 0.120 (0.381 / 0.527) | 0.218 (0.300 / 0.669) | 6.20 (8.22 / 9.95) | gap 0.15, vix_level 5.73, nifty_vol_20 0.10 |
| 2024-12 | 21 | OK | 0.170 (0.156 / 0.138) | 0.530 (0.449 / 0.410) | 0.063 (0.111 / 0.130) | 0.110 (0.381 / 0.527) | 0.022 (0.300 / 0.669) | 3.09 (8.22 / 9.95) | gap 0.14, vix_level 5.24, opening_gap 0.13 |
| 2025-01 | 23 | MODEL_DRIFT_DETECTED | 0.136 (0.156 / 0.138) | 0.430 (0.449 / 0.410) | 0.025 (0.111 / 0.130) | 0.141 (0.381 / 0.527) | 0.365 (0.300 / 0.669) | 5.57 (8.22 / 9.95) | gap 0.17, vix_level 4.28, atr_pct_14 0.17 |
| 2025-02 | 19 | WARN | 0.158 (0.156 / 0.138) | 0.444 (0.449 / 0.410) | 0.023 (0.111 / 0.130) | 0.129 (0.381 / 0.527) | 0.302 (0.300 / 0.669) | 8.03 (8.22 / 9.95) | gap 0.15, vix_level 5.00, intraday_range 0.20 |
| 2025-03 | 19 | OK | 0.167 (0.156 / 0.138) | 0.482 (0.449 / 0.410) | 0.029 (0.111 / 0.130) | 0.095 (0.381 / 0.527) | 0.101 (0.300 / 0.669) | 5.47 (8.22 / 9.95) | gap 0.17, vix_level 5.85, banknifty_vol_20 0.20 |
| 2025-04 | 19 | OK | 0.163 (0.156 / 0.138) | 0.453 (0.449 / 0.410) | 0.020 (0.111 / 0.130) | 0.079 (0.381 / 0.527) | 0.273 (0.300 / 0.669) | 3.25 (8.22 / 9.95) | gap 0.15, or_low_dist 0.13, vix_level 2.54 |
| 2025-05 | 21 | OK | 0.183 (0.156 / 0.138) | 0.508 (0.449 / 0.410) | 0.051 (0.111 / 0.130) | 0.092 (0.381 / 0.527) | 0.072 (0.300 / 0.669) | 7.61 (8.22 / 9.95) | gap 0.17, vix_level 5.47, banknifty_vol_20 0.10 |
| 2025-06 | 10 | OK | 0.195 (0.156 / 0.138) | 0.584 (0.449 / 0.410) | 0.096 (0.111 / 0.130) | 0.166 (0.381 / 0.527) | 0.025 (0.300 / 0.669) | 2.99 (8.22 / 9.95) | gap 0.16, vix_level 4.38, banknifty_vol_20 0.80 |

Weekly windows (32): MODEL_DRIFT_DETECTED 3, OK 22, WARN 7.
Per component (weeks): feature: OK 32; prediction: DRIFT 1, OK 28, WARN 3; accuracy: DRIFT 3, OK 22, WARN 7; calibration: OK 32; regime: OK 32.
