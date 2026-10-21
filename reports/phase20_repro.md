# Phase 20: ML reproducibility

Overall: PASSED.

## Artifact integrity (SHA-256 per file)

| model | files | digests | result |
|---|---|---|---|
| lightgbm-y_1m_5bp-tuned@v1 | 7 | recorded now | PASS |
| lightgbm-y_5m_10bp-tuned@v1 | 7 | recorded now | PASS |

## Dataset rebuild from canonical bars (seed 20, dates before 2025-06-16)

| symbol | rows recomputed / stored / matched | columns | mismatched values | result |
|---|---|---|---|---|
| BHEL | 63,399 / 63,399 / 63,399 | 110 | 0 | PASS |
| FEDERALBNK | 63,399 / 63,399 / 63,399 | 110 | 0 | PASS |
| TCS | 63,473 / 63,473 / 63,473 | 110 | 0 | PASS |
| TECHM | 63,473 / 63,473 / 63,473 | 110 | 0 | PASS |
| UNITDSPR | 63,472 / 63,472 / 63,472 | 110 | 0 | PASS |
| YESBANK | 63,399 / 63,399 / 63,399 | 110 | 0 | PASS |

## Model refit from the walk-forward experiment

| model | refit time | stored validation predictions | identical artifact files | result |
|---|---|---|---|---|
| lightgbm-y_1m_5bp-tuned@v1 | 230.1 s | refit reproduces 1,116,225/1,116,225 stored validation predictions, max abs diff 2.98e-08 (tol 0.0001); saved model reload diff 0.0e+00 | model.txt yes, preprocessor.json yes, features.json yes, calibrator.json yes | PASS |
| lightgbm-y_5m_10bp-tuned@v1 | 189.2 s | refit reproduces 1,101,326/1,101,326 stored validation predictions, max abs diff 2.98e-08 (tol 0.0001); saved model reload diff 0.0e+00 | model.txt yes, preprocessor.json yes, features.json yes, calibrator.json yes | PASS |
