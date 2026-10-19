# ML inference service (Phase 14)

Code: `ml/src/pulsetrader/serve/{app,models,store,parity}.py`. Run:
```
cd ml && PULSETRADER_DATA_DIR=../data .venv/bin/uvicorn pulsetrader.serve.app:app --port 8000
PULSETRADER_DATA_DIR=../data .venv/bin/pulsetrader serve-check   # parity check -> reports/phase14_inference.md
```
Docker: `docker compose up ml-service` mounts `data/registry` and `data/datasets` read-only.

## Environment
| Variable | Default | Meaning |
|---|---|---|
| PULSETRADER_DATA_DIR | `data` | data root |
| PULSETRADER_REGISTRY_DIR | `$DATA/registry` | model registry |
| PULSETRADER_DATASET | `core100_s5` | dataset for HISTORICAL mode |
| PULSETRADER_ALLOW_TEST_PERIOD | unset | `1` unlocks test-period rows (only after development is finished) |

## Endpoints
| Method | Path | Returns |
|---|---|---|
| GET | /health | process is up |
| GET | /ready | `ready` once a servable model is loaded; `reason: NO_PRODUCTION_MODEL` when none is in production |
| POST | /predict | one prediction record |
| POST | /predict/batch | `{items: [...]}` up to 1,000 |
| GET | /models | every registry version: status, gates, validation and backtest summary, serving config |
| GET | /models/active | PRODUCTION models (empty with a reason when none) |
| GET | /features | per model: feature order, training median/mean/std, missing-value rule, fit period |
| GET | /metrics | requests, errors, directions, abstentions, coverage, latency p50/p95/p99 |

## Request
```json
{"symbol": "RELIANCE", "timestamp": "2025-01-06T10:30:00+05:30",
 "model_id": "lightgbm-y_5m_10bp-tuned", "model_version": 1,
 "features": {"ret_1": 0.0004, "...": "..."}, "max_staleness_seconds": 90, "current_price": 1250.5}
```
- `timestamp` is the start of the latest closed 1-minute bar and must carry a timezone.
- `features` omitted: HISTORICAL mode reads the row from the research dataset (built by the shared
  engine). Test-period rows return 403 `TEST_PERIOD_LOCKED`; unknown rows 404 `DATA_UNAVAILABLE`.
- `model_id` omitted: the PRODUCTION model for `task` answers; with none, 409 `NO_PRODUCTION_MODEL`.
  CANDIDATE/SHADOW models answer only when named, with `research_only: true`.

## Response (prediction record)
prediction_id, symbol, prediction_timestamp (bar close = timestamp + 1 min), market_data_timestamp,
target_timestamp, latency_ms, direction (UP / DOWN / NO_PREDICTION), model_class, abstain_reason,
raw_probability, calibrated_probability, confidence, prediction_horizon_minutes, label_threshold,
current_price, predicted_price / predicted_return (null: no regression model registered), model_id,
model_version, model_status, research_only, feature_version, data_version, data_quality,
missing_feature_fraction, out_of_range_feature_fraction. Live outcome fields (actual price, error,
direction_correct) are filled by the prediction store in Phase 17-18.

## Decisions and abstention
The artifact's preprocessor (fit on training rows, never refit) and feature order are applied; the
direction is the argmax of the raw probabilities; calibrated probabilities are reported (Phase 10).
`NO_PREDICTION` reasons, checked in this order: `FEATURES_INVALID` (non-numeric, or > 10% missing),
`MODEL_OUT_OF_DISTRIBUTION` (> 10% of features beyond 8 training std devs, or symbol outside the
training universe), `STALE_DATA` (older than `max_staleness_seconds`), `LOW_CONFIDENCE` (NEUTRAL
argmax, or P(direction) below the model's gate chosen on pre-validation folds: 0.60 for 1m, 0.56 for 5m).
