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

## Real-data gate (Phase 6)

`pulsetrader audit` (`ml/src/pulsetrader/audit/leakage.py`) re-runs the checks on the real
canonical data and on a built research dataset. Result for `core100_s5` on 2026-10-17: **PASSED**,
full table in `reports/leakage_audit_real.md`.

- Perturbation: 18 cut-offs (session open, mid-session, last bar) on 3 random universe stocks,
  4.7M past rows compared; NIFTY perturbed and joined; other stocks' inputs distorted for the
  cross-sectional features. 0 leaks.
- 7.47M rows: availability = bar close, every label ends after availability, no label crosses a session.
- 3.7M labels recomputed from canonical closes for 10 symbols: 0 mismatches.
- Splits chronological with purge + 60-minute embargo; universe ranking window (2022-01-03..2023-01-04)
  ends before training ends; Preprocessor refuses mixed splits and fits train-only statistics.
- `tests/test_audit.py` proves the gate passes on clean golden data and fails when a one-bar label
  shift and a late label end are injected.
