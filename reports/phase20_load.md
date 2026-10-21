# Phase 20: load test (local stack, one machine)

Closed loop, 15 s per level; API at http://localhost:3002 with the per-IP rate limit raised for this measurement; load generator on the same 4-CPU machine as API, ML service, PostgreSQL and Redis. Errors = non-2xx or transport errors.

| scenario | concurrency | requests | req/s | p50 ms | p95 ms | p99 ms | max ms | errors |
|---|---|---|---|---|---|---|---|---|
| API GET /stocks?q (search) | 1 | 3224 | 214.9 | 4.4 | 6.9 | 9.9 | 60.6 | 0 |
| API GET /stocks?q (search) | 8 | 9005 | 599.7 | 12.7 | 21.1 | 27.9 | 68.7 | 0 |
| API GET /stocks?q (search) | 32 | 9286 | 618.0 | 50.5 | 70.4 | 83.8 | 355.3 | 0 |
| API GET /stocks/:symbol (quote, latest prediction) | 1 | 1280 | 85.3 | 11.3 | 15.7 | 19.3 | 30.8 | 0 |
| API GET /stocks/:symbol (quote, latest prediction) | 8 | 4970 | 331.1 | 23.7 | 33.7 | 40.2 | 62.5 | 0 |
| API GET /stocks/:symbol (quote, latest prediction) | 32 | 5825 | 386.9 | 80.9 | 110.2 | 124.7 | 151.8 | 0 |
| API GET /market-data/:symbol/daily (1y bars) | 1 | 1278 | 85.1 | 11.4 | 15.6 | 18.5 | 33.7 | 0 |
| API GET /market-data/:symbol/daily (1y bars) | 8 | 3737 | 248.7 | 31.4 | 47.4 | 56.3 | 77.2 | 0 |
| API GET /market-data/:symbol/daily (1y bars) | 32 | 4396 | 291.3 | 107.0 | 149.6 | 175.7 | 245.3 | 0 |
| API GET /predictions/accuracy?mode=REPLAY (20k outcomes) | 1 | 10710 | 713.9 | 1.2 | 2.4 | 4.1 | 485.3 | 0 |
| API GET /predictions/accuracy?mode=REPLAY (20k outcomes) | 8 | 10368 | 675.2 | 9.9 | 20.8 | 29.6 | 434.5 | 0 |
| API GET /predictions/accuracy?mode=REPLAY (20k outcomes) | 32 | 8647 | 574.5 | 51.4 | 82.5 | 119.5 | 690.9 | 0 |
| API GET /monitoring (health summary) | 1 | 255 | 16.9 | 55.4 | 82.4 | 93.2 | 131.3 | 0 |
| API GET /monitoring (health summary) | 8 | 3963 | 263.7 | 20.1 | 69.1 | 140.7 | 203.7 | 0 |
| API GET /monitoring (health summary) | 32 | 5155 | 342.1 | 84.3 | 132.0 | 204.3 | 731.5 | 0 |
| API POST /predictions (historical, via ML, stored) | 1 | 552 | 36.7 | 26.0 | 34.1 | 42.0 | 203.5 | 0 |
| API POST /predictions (historical, via ML, stored) | 8 | 2071 | 137.7 | 57.2 | 81.2 | 97.1 | 133.7 | 0 |
| API POST /predictions (historical, via ML, stored) | 32 | 2624 | 173.5 | 178.0 | 259.8 | 308.1 | 661.7 | 0 |
| ML POST /predict (historical features) | 1 | 2133 | 142.2 | 6.8 | 9.0 | 11.6 | 20.0 | 0 |
| ML POST /predict (historical features) | 8 | 3544 | 236.1 | 32.8 | 48.5 | 55.9 | 76.7 | 0 |
| ML POST /predict (historical features) | 32 | 5184 | 344.6 | 91.8 | 117.0 | 142.5 | 215.9 | 0 |

## Before vs after the Phase 20 accuracy cache
Baseline run (same machine, same settings, before the change) for `GET /predictions/accuracy?mode=REPLAY`:
2.5 / 4.5 / 4.6 req/s at concurrency 1 / 8 / 32 (p95 544 ms / 2.5 s / 11.2 s). The query recomputed
metrics over 20k outcomes on every request. With the per-instance cache (`ACCURACY_CACHE_SECONDS`,
default 15 s, cleared on every new prediction or outcome) and the `(mode, marketDataTimestamp)` index:
714 / 675 / 575 req/s (p95 2.4 / 21 / 83 ms). Other endpoints are within run-to-run noise of the baseline.
Every scenario finished with 0 errors.
