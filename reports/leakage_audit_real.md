# Leakage audit on real data

Audit `leakage-audit-v1` on dataset `dataset-v1-features-v2-labels-v1-u100-s5`. Gate: **PASSED**.

| Check | Result | Detail |
|---|---|---|
| single-symbol feature perturbation | PASS | 18 cut-offs on 3 real symbols, 4,696,559 past rows compared, 0 leaks |
| market-context perturbation | PASS | NIFTY perturbed after 3 cut-offs, joined to RELIANCE; 8 market features compared, 0 leaks |
| cross-sectional perturbation | PASS | other stocks' inputs distorted after 3 cut-offs; ADANIENSOL's 7 relative features compared, 0 leaks |
| timestamps and session boundaries | PASS | 7,470,060 rows: availability_ts = bar close, label_end_ts > availability_ts and no label crosses a session for horizons [1, 5, 15, 30, 60]; violations 0 |
| label recomputation from canonical | PASS | 3,735,775 (row, horizon) labels recomputed for 10 symbols; 0 mismatching series |
| chronological split, purge and embargo | PASS | periods train 2022-01-03..2024-11-04, validation 2024-11-05..2025-06-13, test 2025-06-16..2026-01-21; 2,400 rows purged/embargoed; problems: none |
| point-in-time universe | PASS | liquidity ranking window ends 2023-01-04; training ends 2024-11-04 |
| scaler isolation | PASS | fit on mixed splits refused=True; train-only means match=True; fit period ends 2024-11-04 15:00:00+05:30 (train max) |
