# Final test-period evaluation (2025-06-16..2026-01-21)

Run once (2026-10-20) after the user approved it on 2026-10-19. Frozen registry
artifacts (SHA-256 verified), no refit or tuning. Full coverage = argmax of the raw
probabilities on every test row; service calls = rows the ML service would answer UP/DOWN
(confidence gate from Phase 12 plus abstain rules). Gate `test_passed` = MCC >= 0.05, above
momentum, balanced accuracy above 1/3.

## Full coverage

| model | rows | accuracy | majority | balanced acc. | MCC | momentum MCC | AUC | val. MCC | gate |
|---|---|---|---|---|---|---|---|---|---|
| lightgbm-y_1m_5bp-tuned@v1 | 1,123,575 | 62.4% | 69.0% | 44.0% | 0.200 | 0.100 | 0.682 | 0.194 | PASSED |
| lightgbm-y_5m_10bp-tuned@v1 | 1,108,578 | 61.2% | 66.2% | 42.5% | 0.186 | 0.098 | 0.663 | 0.168 | PASSED |

## Calibration

| model | Brier raw | Brier cal. | classwise ECE raw | ECE cal. |
|---|---|---|---|---|
| lightgbm-y_1m_5bp-tuned@v1 | 0.515 | 0.441 | 0.148 | 0.029 |
| lightgbm-y_5m_10bp-tuned@v1 | 0.534 | 0.471 | 0.136 | 0.016 |

## Service calls (selective)

| model | calls | coverage | accuracy | balanced acc. | MCC | sign right | gross bp | net bp after costs |
|---|---|---|---|---|---|---|---|---|
| lightgbm-y_1m_5bp-tuned@v1 | 349 | 0.0% | 47.9% | 41.9% | 0.213 | 59.3% | 3.47 | -6.78 |
| lightgbm-y_5m_10bp-tuned@v1 | 1,774 | 0.2% | 36.2% | 36.4% | 0.054 | 53.5% | 2.15 | -8.09 |

## Backtest on the test period (same engine and costs as Phase 12)

| model | strategy | costs | total return | trades | win rate | avg bp/trade |
|---|---|---|---|---|---|---|
| lightgbm-y_1m_5bp-tuned@v1 | model | costs | -100.0% | 97762 | 7.7% | -12.43 |
| lightgbm-y_1m_5bp-tuned@v1 | model | zero_costs | 14.3% | 100380 | 47.7% | 0.13 |
| lightgbm-y_1m_5bp-tuned@v1 | model_gated | costs | -3.1% | 349 | 18.1% | -9.06 |
| lightgbm-y_1m_5bp-tuned@v1 | model_gated | zero_costs | 0.4% | 349 | 47.9% | 1.25 |
| lightgbm-y_1m_5bp-tuned@v1 | momentum | costs | -100.0% | 101107 | 6.7% | -12.70 |
| lightgbm-y_1m_5bp-tuned@v1 | momentum | zero_costs | -14.0% | 103838 | 43.8% | -0.14 |
| lightgbm-y_1m_5bp-tuned@v1 | buy_and_hold | costs | 3.9% | 200 | – | – |
| lightgbm-y_1m_5bp-tuned@v1 | buy_and_hold | zero_costs | 4.0% | 200 | – | – |
| lightgbm-y_5m_10bp-tuned@v1 | model | costs | -100.0% | 90743 | 23.8% | -12.32 |
| lightgbm-y_5m_10bp-tuned@v1 | model | zero_costs | 23.3% | 92898 | 51.0% | 0.23 |
| lightgbm-y_5m_10bp-tuned@v1 | model_gated | costs | -13.8% | 1557 | 34.4% | -9.51 |
| lightgbm-y_5m_10bp-tuned@v1 | model_gated | zero_costs | 1.7% | 1562 | 52.0% | 1.06 |
| lightgbm-y_5m_10bp-tuned@v1 | momentum | costs | -100.0% | 99745 | 18.9% | -12.51 |
| lightgbm-y_5m_10bp-tuned@v1 | momentum | zero_costs | 3.3% | 101931 | 46.5% | 0.04 |
| lightgbm-y_5m_10bp-tuned@v1 | buy_and_hold | costs | 3.9% | 200 | – | – |
| lightgbm-y_5m_10bp-tuned@v1 | buy_and_hold | zero_costs | 4.0% | 200 | – | – |

## By month (full coverage)

| model | month | rows | accuracy | balanced acc. | MCC | calls |
|---|---|---|---|---|---|---|
| lightgbm-y_1m_5bp-tuned@v1 | 2025-06 | 81,300 | 58.3% | 44.1% | 0.193 | 46 |
| lightgbm-y_1m_5bp-tuned@v1 | 2025-07 | 172,500 | 63.0% | 44.2% | 0.204 | 51 |
| lightgbm-y_1m_5bp-tuned@v1 | 2025-08 | 142,500 | 62.1% | 44.1% | 0.197 | 81 |
| lightgbm-y_1m_5bp-tuned@v1 | 2025-09 | 165,000 | 64.5% | 43.3% | 0.196 | 39 |
| lightgbm-y_1m_5bp-tuned@v1 | 2025-10 | 149,850 | 61.3% | 43.7% | 0.192 | 29 |
| lightgbm-y_1m_5bp-tuned@v1 | 2025-11 | 142,500 | 65.1% | 43.9% | 0.201 | 31 |
| lightgbm-y_1m_5bp-tuned@v1 | 2025-12 | 164,925 | 65.5% | 44.0% | 0.202 | 36 |
| lightgbm-y_1m_5bp-tuned@v1 | 2026-01 | 105,000 | 54.6% | 44.0% | 0.184 | 36 |
| lightgbm-y_5m_10bp-tuned@v1 | 2025-06 | 80,200 | 57.6% | 42.9% | 0.180 | 140 |
| lightgbm-y_5m_10bp-tuned@v1 | 2025-07 | 170,200 | 62.2% | 43.0% | 0.195 | 219 |
| lightgbm-y_5m_10bp-tuned@v1 | 2025-08 | 140,600 | 61.0% | 42.5% | 0.185 | 297 |
| lightgbm-y_5m_10bp-tuned@v1 | 2025-09 | 162,800 | 63.4% | 42.2% | 0.190 | 208 |
| lightgbm-y_5m_10bp-tuned@v1 | 2025-10 | 147,852 | 60.3% | 42.4% | 0.180 | 145 |
| lightgbm-y_5m_10bp-tuned@v1 | 2025-11 | 140,600 | 63.4% | 42.1% | 0.185 | 157 |
| lightgbm-y_5m_10bp-tuned@v1 | 2025-12 | 162,726 | 63.9% | 41.4% | 0.175 | 197 |
| lightgbm-y_5m_10bp-tuned@v1 | 2026-01 | 103,600 | 52.6% | 42.3% | 0.168 | 411 |

The test period is now used. Any new model must be judged on a new untouched period.
