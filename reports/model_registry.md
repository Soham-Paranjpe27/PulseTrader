# Phase 13 — model registry

Registry: `data/registry/registry.json` (registry-v1); artifacts under `data/registry/artifacts/`.
Statuses: EXPERIMENT -> CANDIDATE -> SHADOW -> PRODUCTION -> RETIRED, or REJECTED. A transition
needs every gate for its target status PASSED (docs/model-registry.md). Test period not used.

| Model | Version | Status | Task | Val accuracy | Val balanced acc | Val MCC | Coverage | Backtest (gated, after costs) | Accuracy gate |
|---|---|---|---|---|---|---|---|---|---|
| lightgbm-y_1m_5bp-tuned | v1 | **CANDIDATE** | y_1m_5bp | 50.1% | 45.2% | 0.194 | 100.0% | -9.5% | NOT VERIFIED |
| lightgbm-y_5m_10bp-tuned | v1 | **CANDIDATE** | y_5m_10bp | 48.0% | 43.1% | 0.168 | 100.0% | -34.4% | NOT VERIFIED |

## lightgbm-y_1m_5bp-tuned@v1 — CANDIDATE

| Gate | Status | Evidence |
|---|---|---|
| no_leakage | PASSED | leakage audit leakage-audit-v1 on dataset-v1-features-v2-labels-v1-u100-s5 |
| no_critical_data_quality | PASSED | flagged raw rows 21,556 of 720,421,072 (2.99e-05); flagged rows are excluded from canonical; limit 0.001 |
| validation_passed | PASSED | validation MCC 0.194 (min 0.05, momentum 0.089), balanced accuracy 0.452 (chance 0.333), accuracy 0.501 (majority 0.581) |
| walk_forward_passed | PASSED | 5 folds: MCC min 0.194, max 0.241, std 0.018 (max 0.05); beats momentum in 5/5 |
| calibration_passed | PASSED | isotonic calibration, validation classwise ECE 0.019 (max 0.05); raw 0.142 |
| reproducible | PASSED | refit reproduces 1,116,225/1,116,225 stored validation predictions, max abs diff 2.98e-08 (tol 0.0001); saved model reload diff 0.0e+00 |
| backtest_passed | FAILED | gated strategy after costs: total return -9.5%, Sharpe -12.61, max DD -9.6%; buy-and-hold 1.5% |
| test_passed | PASSED | test 2025-06-16..2026-01-21, 1,123,575 rows: MCC 0.200 (min 0.05, momentum 0.100), balanced accuracy 0.440 (chance 0.333), accuracy 0.624; service calls 349 (0.03% coverage) |
| shadow_passed | NOT_RUN | no live shadow run yet (Phase 17-18) |

Blocked from SHADOW by: backtest_passed

History:

- 2026-10-19T07:29:48.761070+00:00: None -> EXPERIMENT (exported from 20261018T192847-p9-wf-expanding-lightgbm-y_1m_5bp-tuned-cc45c314)
- 2026-10-19T07:29:48.765049+00:00: EXPERIMENT -> CANDIDATE (all CANDIDATE gates passed)

## lightgbm-y_5m_10bp-tuned@v1 — CANDIDATE

| Gate | Status | Evidence |
|---|---|---|
| no_leakage | PASSED | leakage audit leakage-audit-v1 on dataset-v1-features-v2-labels-v1-u100-s5 |
| no_critical_data_quality | PASSED | flagged raw rows 21,556 of 720,421,072 (2.99e-05); flagged rows are excluded from canonical; limit 0.001 |
| validation_passed | PASSED | validation MCC 0.168 (min 0.05, momentum 0.087), balanced accuracy 0.431 (chance 0.333), accuracy 0.480 (majority 0.551) |
| walk_forward_passed | PASSED | 5 folds: MCC min 0.168, max 0.209, std 0.015 (max 0.05); beats momentum in 5/5 |
| calibration_passed | PASSED | isotonic calibration, validation classwise ECE 0.013 (max 0.05); raw 0.133 |
| reproducible | PASSED | refit reproduces 1,101,326/1,101,326 stored validation predictions, max abs diff 2.98e-08 (tol 0.0001); saved model reload diff 0.0e+00 |
| backtest_passed | FAILED | gated strategy after costs: total return -34.4%, Sharpe -11.35, max DD -34.5%; buy-and-hold 1.5% |
| test_passed | PASSED | test 2025-06-16..2026-01-21, 1,108,578 rows: MCC 0.186 (min 0.05, momentum 0.098), balanced accuracy 0.425 (chance 0.333), accuracy 0.612; service calls 1,774 (0.16% coverage) |
| shadow_passed | NOT_RUN | no live shadow run yet (Phase 17-18) |

Blocked from SHADOW by: backtest_passed

History:

- 2026-10-19T07:32:32.226470+00:00: None -> EXPERIMENT (exported from 20261018T181358-p9-wf-expanding-lightgbm-y_5m_10bp-tuned-1a2aa277)
- 2026-10-19T07:32:32.240933+00:00: EXPERIMENT -> CANDIDATE (all CANDIDATE gates passed)
