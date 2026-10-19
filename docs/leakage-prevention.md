# Leakage prevention

How the pipeline keeps future information out of features, training and evaluation. The checks that
prove it are in docs/leakage-audit.md (Phase 6 real-data gate: PASSED, reports/leakage_audit_real.md).

| Rule | Where it is enforced |
|---|---|
| A feature for bar t uses only bars up to t; it becomes available at the bar close (t + 1 min) | `features/engine.py`; perturbation tests change every later bar and require identical features |
| Joins keep row order (a reordered join once let a `shift` read a later bar) | engine re-sorts after joins; row-order test |
| Labels start after availability and never cross a session; a missing future bar gives a null label | `labels/labels.py`; label audit recomputed 3.7M labels from canonical bars |
| Chronological splits only: train 2022-01-03..2024-11-04, validation ..2025-06-13, test 2025-06-16..2026-01-21 | `splits/splits.py`; nothing is shuffled |
| Purge: a training row's label must end before the next window starts; 60-minute embargo | `splits/splits.py`, walk-forward folds (docs/walk-forward.md) |
| Scalers, imputers and feature selection are fit on training rows only | `Preprocessor.fit` refuses non-training rows |
| The universe is chosen from training-period turnover only | `datasets/build.py` (`select_universe`) |
| Thresholds, calibrators and confidence gates are chosen on pre-validation folds | Phases 9, 10 and 12 |
| The test period is not read until model development is finished | ML service and replay provider refuse it (`TEST_PERIOD_LOCKED`); drift references, monitoring and the reproducibility check stop before it |
| Corporate-action sessions (and the next session) are excluded | `security/master.py` (`flagged_days`) |
| Only scale-free features (prices are back-adjusted by the vendor) | features-v2 |

Known limits: the source has no delisted symbols (survivorship bias), and sector membership is
inferred from returns because no point-in-time sector master is available offline.
