# Leakage audit

Automated checks live in `ml/tests/test_leakage.py` and run on every test run.

| Check | Method | Status (golden dataset) |
|---|---|---|
| Feature availability | Perturb all bars after a cut-off; every feature at or before the cut-off must be unchanged (5 cut-offs, incl. day boundaries) | PASSED |
| Cross-sectional features | Perturb another symbol's future; this symbol's relative features unchanged | PASSED |
| Market context | Perturb index future; joined market features unchanged | PASSED |
| Row-order independence | Shuffled input gives identical features | PASSED |
| availability_ts <= prediction_ts | Asserted; availability = bar close | PASSED |
| Labels after features | label_end_ts > availability_ts for every horizon | PASSED |
| Temporal split | Chronological date split; purge + embargo verified | PASSED |
| Scaler isolation | Preprocessor refuses non-train rows; statistics equal train-only stats | PASSED |
| Label audit | Exact values, no cross-session labels, null on gaps | PASSED |

Finding during development: a join in the feature engine did not preserve row order, so a `shift`
read a later bar (a real future leak). The perturbation test caught it; fixed by re-sorting after
joins and adding the row-order test.

Phase 6 gate must be re-run on the real canonical dataset before any model training.
