# Phase 14 — ML inference service check (validation sample)

FastAPI service (`pulsetrader.serve.app`) loaded from the model registry. A fixed-seed sample of
validation rows was sent through `POST /predict/batch`: HISTORICAL mode (features read from the
research dataset) and client-supplied `features`. Raw probabilities are compared with the stored
Phase 9 validation predictions. Test period not used.

`/ready`: ready=True, reason=NO_PRODUCTION_MODEL, loaded=lightgbm-y_1m_5bp-tuned@v1, lightgbm-y_5m_10bp-tuned@v1.

| Model | Status | Rows | Max abs diff (historical) | Max abs diff (features) | Parity | Coverage | Called | Sign acc when called | Label acc when called | Rows/s |
|---|---|---|---|---|---|---|---|---|---|---|
| lightgbm-y_1m_5bp-tuned@v1 | CANDIDATE | 3,000 | 3.0e-08 | 2.9e-08 | PASSED | 0.1% | 4 | 100.0% | 100.0% | 454.8 |
| lightgbm-y_5m_10bp-tuned@v1 | CANDIDATE | 3,000 | 3.0e-08 | 2.9e-08 | PASSED | 0.7% | 21 | 38.1% | 38.1% | 472.2 |

Abstention reasons:

- lightgbm-y_1m_5bp-tuned@v1: LOW_CONFIDENCE 2993, MODEL_OUT_OF_DISTRIBUTION 3, None 4
- lightgbm-y_5m_10bp-tuned@v1: LOW_CONFIDENCE 2971, MODEL_OUT_OF_DISTRIBUTION 8, None 21

Test-period request: HTTP 403 `TEST_PERIOD_LOCKED`.
Request without model_id: `NO_PRODUCTION_MODEL` (no PRODUCTION model exists).
## Findings
- The service reproduces the walk-forward validation predictions exactly (max abs diff 3e-8), both from
  dataset rows and from client-supplied feature rows, so training and serving use the same features,
  order, preprocessing and model.
- With the confidence gates chosen on pre-validation folds the models almost always abstain: 0.1%
  (1m) and 0.7% (5m) coverage on this sample. 4 and 21 calls are far too few to judge accuracy.
- No model is in PRODUCTION (Phase 13 gates), so the service refuses requests that do not name a model.
