# Phase 18: live paper evaluation (REPLAY of recorded validation sessions)

Sessions: 2025-05-19 .. 2025-06-13 (20 sessions, validation period). Each session was replayed bar by bar through the live pipeline; every prediction was scored after its horizon from the replayed bars. No live provider is connected here, so these are REPLAY results, not LIVE ones. Test period not used.

## Outcome checks

- lightgbm-y_1m_5bp-tuned@v1: 150000 outcomes joined to research labels; class match 1.0000, max return diff 4.63e-10.
- lightgbm-y_5m_10bp-tuned@v1: 150000 outcomes joined to research labels; class match 1.0000, max return diff 1.62e-09.
- lightgbm-y_1m_5bp-tuned@v1: 150000 rows joined to walk-forward validation predictions; max P(up) diff 1.73e-03.
- lightgbm-y_5m_10bp-tuned@v1: 148000 rows joined to walk-forward validation predictions; max P(up) diff 1.83e-05.

## Full coverage (argmax class on every evaluated prediction)

| model | predictions | evaluated | accuracy | balanced acc | MCC | Brier raw | ECE raw | Brier cal | ECE cal |
|---|---|---|---|---|---|---|---|---|---|
| lightgbm-y_1m_5bp-tuned@v1 | 150000 | 150000 | 0.585 | 0.451 | 0.206 | 0.544 | 0.089 | 0.468 | 0.043 |
| lightgbm-y_5m_10bp-tuned@v1 | 150000 | 148000 | 0.568 | 0.436 | 0.188 | 0.566 | 0.089 | 0.495 | 0.032 |

## Served calls (UP/DOWN after the confidence gate; everything else is NO PREDICTION)

| model | calls | coverage | accuracy | sign accuracy | balanced acc | MCC | last 20 | last 50 | last 100 | last 500 |
|---|---|---|---|---|---|---|---|---|---|---|
| lightgbm-y_1m_5bp-tuned@v1 | 47 | 0.0003 | 0.404 | 0.511 | 0.294 | -0.133 | 0.450 | 0.404 | 0.404 | 0.404 |
| lightgbm-y_5m_10bp-tuned@v1 | 401 | 0.0027 | 0.431 | 0.599 | 0.422 | 0.163 | 0.600 | 0.340 | 0.390 | 0.431 |

## Paper trading per call (independent calls, no capital limits: an upper bound)

| model | calls | mean gross bp | round-trip cost bp | mean net bp | hit rate gross | hit rate net | total net bp |
|---|---|---|---|---|---|---|---|
| lightgbm-y_1m_5bp-tuned@v1 | 47 | -3.49 | 10.24 | -13.73 | 0.511 | 0.170 | -645.5 |
| lightgbm-y_5m_10bp-tuned@v1 | 401 | 3.86 | 10.24 | -6.38 | 0.599 | 0.424 | -2558.2 |

## Daily, lightgbm-y_1m_5bp-tuned@v1

| day | evaluated | calls | coverage | accuracy |
|---|---|---|---|---|
| 2025-05-19 | 7500 | 2 | 0.0003 | 0.500 |
| 2025-05-20 | 7500 | 2 | 0.0003 | 0.500 |
| 2025-05-21 | 7500 | 2 | 0.0003 | 0.000 |
| 2025-05-22 | 7500 | 1 | 0.0001 | 0.000 |
| 2025-05-23 | 7500 | 3 | 0.0004 | 0.333 |
| 2025-05-26 | 7500 | 2 | 0.0003 | 0.000 |
| 2025-05-27 | 7500 | 2 | 0.0003 | 0.500 |
| 2025-05-28 | 7500 | 0 | 0.0000 | – |
| 2025-05-29 | 7500 | 3 | 0.0004 | 0.333 |
| 2025-05-30 | 7500 | 3 | 0.0004 | 0.333 |
| 2025-06-02 | 7500 | 2 | 0.0003 | 0.500 |
| 2025-06-03 | 7500 | 3 | 0.0004 | 0.667 |
| 2025-06-04 | 7500 | 3 | 0.0004 | 0.333 |
| 2025-06-05 | 7500 | 3 | 0.0004 | 0.667 |
| 2025-06-06 | 7500 | 5 | 0.0007 | 0.600 |
| 2025-06-09 | 7500 | 2 | 0.0003 | 0.500 |
| 2025-06-10 | 7500 | 1 | 0.0001 | 0.000 |
| 2025-06-11 | 7500 | 0 | 0.0000 | – |
| 2025-06-12 | 7500 | 6 | 0.0008 | 0.333 |
| 2025-06-13 | 7500 | 2 | 0.0003 | 0.500 |

Weekly: 2025-W21 10 calls acc 0.300, 2025-W22 10 calls acc 0.300, 2025-W23 16 calls acc 0.562, 2025-W24 11 calls acc 0.364
Monthly: 2025-05 20 calls acc 0.300, 2025-06 27 calls acc 0.481

## Daily, lightgbm-y_5m_10bp-tuned@v1

| day | evaluated | calls | coverage | accuracy |
|---|---|---|---|---|
| 2025-05-19 | 7400 | 10 | 0.0014 | 0.500 |
| 2025-05-20 | 7400 | 58 | 0.0078 | 0.379 |
| 2025-05-21 | 7400 | 50 | 0.0068 | 0.800 |
| 2025-05-22 | 7400 | 3 | 0.0004 | 0.000 |
| 2025-05-23 | 7400 | 8 | 0.0011 | 0.375 |
| 2025-05-26 | 7400 | 8 | 0.0011 | 0.500 |
| 2025-05-27 | 7400 | 18 | 0.0024 | 0.278 |
| 2025-05-28 | 7400 | 9 | 0.0012 | 0.556 |
| 2025-05-29 | 7400 | 1 | 0.0001 | 1.000 |
| 2025-05-30 | 7400 | 30 | 0.0041 | 0.133 |
| 2025-06-02 | 7400 | 3 | 0.0004 | 0.667 |
| 2025-06-03 | 7400 | 23 | 0.0031 | 0.304 |
| 2025-06-04 | 7400 | 8 | 0.0011 | 0.750 |
| 2025-06-05 | 7400 | 10 | 0.0014 | 0.600 |
| 2025-06-06 | 7400 | 10 | 0.0014 | 0.300 |
| 2025-06-09 | 7400 | 2 | 0.0003 | 0.000 |
| 2025-06-10 | 7400 | 9 | 0.0012 | 0.333 |
| 2025-06-11 | 7400 | 7 | 0.0009 | 0.429 |
| 2025-06-12 | 7400 | 76 | 0.0103 | 0.487 |
| 2025-06-13 | 7400 | 58 | 0.0078 | 0.293 |

Weekly: 2025-W21 129 calls acc 0.543, 2025-W22 66 calls acc 0.288, 2025-W23 54 calls acc 0.444, 2025-W24 152 calls acc 0.395
Monthly: 2025-05 195 calls acc 0.456, 2025-06 206 calls acc 0.408
