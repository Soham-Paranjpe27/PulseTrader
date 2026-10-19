# Model registry (Phase 13)

Code: `ml/src/pulsetrader/registry/registry.py` (registry) and `ml/src/pulsetrader/experiments/register.py`
(artifact export and gate evaluation). Storage: `data/registry/registry.json` (atomic writes) and
`data/registry/artifacts/{model_id}/v{version}/`. Summary: `reports/model_registry.md`.

```
PULSETRADER_DATA_DIR=../data .venv/bin/pulsetrader registry register      # export + gates + register
PULSETRADER_DATA_DIR=../data .venv/bin/pulsetrader registry list
PULSETRADER_DATA_DIR=../data .venv/bin/pulsetrader registry transition \
    --model-id lightgbm-y_5m_10bp-tuned --version 1 --to REJECTED --reason "..."
```

## Record fields
model_id, version, task (label), model_type, dataset_version, feature_version, label_version,
training_period (incl. actual fit rows period), validation_period, test_period (`used` flag),
hyperparameters (incl. best_iteration), metrics (validation, baselines, calibrated, walk-forward,
selective), backtest_metrics (every Phase 12 strategy), calibration_version, artifact_path, status,
created_at, gates, accuracy_gate (spec section 39), source_experiments, notes, history.

## Artifact
| File | Content |
|---|---|
| model.txt | LightGBM booster at its best iteration |
| preprocessor.json | median imputation + standardisation fit on training rows only |
| features.json | feature_version and the exact feature order |
| calibrator.json | Phase 10 calibrator (method chosen on pre-validation folds) |
| model_meta.json | label, horizon, threshold, fit rows/period, params, fold layout |

The artifact is the walk-forward model of the validation window, refit exactly as Phase 9 did it.
Export fails the `reproducible` gate unless the refit reproduces the stored validation predictions
(max abs difference <= 1e-4) and the saved booster reloads identically.

## Statuses and transitions
`EXPERIMENT -> CANDIDATE | REJECTED`, `CANDIDATE -> SHADOW | REJECTED`,
`SHADOW -> PRODUCTION | CANDIDATE | REJECTED`, `PRODUCTION -> RETIRED`; RETIRED and REJECTED are final.
Every transition needs a reason and is appended to the history. Promoting to PRODUCTION retires the
previous PRODUCTION version of the same task. Nothing is promoted automatically; drift detection
(Phase 19) only flags `MODEL_DRIFT_DETECTED`.

## Gates (PASSED / FAILED / NOT_RUN, each with evidence)
| Gate | Rule | Needed for |
|---|---|---|
| no_leakage | Phase 6 real-data leakage audit passed for this dataset | CANDIDATE |
| no_critical_data_quality | flagged raw rows <= 0.1% (excluded from canonical) | CANDIDATE |
| validation_passed | validation MCC >= 0.05 and > momentum MCC, balanced accuracy > 1/3 | CANDIDATE |
| walk_forward_passed | MCC > 0 in every fold, beats momentum in every fold, fold MCC std <= 0.05 | CANDIDATE |
| calibration_passed | chosen calibrator's validation classwise ECE <= 0.05 | CANDIDATE |
| reproducible | refit reproduces stored validation predictions | CANDIDATE |
| backtest_passed | gated strategy after costs: total return > 0, > buy-and-hold, Sharpe > 0 | SHADOW |
| test_passed | final test period evaluated (only once development is finished) | SHADOW |
| shadow_passed | live shadow evaluation vs production on the same events | PRODUCTION |

A CANDIDATE is a research candidate. It cannot reach SHADOW, and therefore cannot be served as
production, until it is profitable after costs in the backtest and has passed the untouched test.
