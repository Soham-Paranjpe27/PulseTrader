# Troubleshooting

Start with `GET /api/health/ready` (database, Redis, ML service, feed) and the Monitoring page
(`/monitoring`: component status, open alerts, drift). Every error the API returns carries a `code`.

## API answers
| Code / status | Meaning | What to do |
|---|---|---|
| `DATABASE_UNAVAILABLE` (503) | PostgreSQL unreachable | Start PostgreSQL; the API reconnects by itself (no restart). Liveness `/api/health` stays 200 |
| `ML_SERVICE_UNAVAILABLE` (503) | ML service unreachable; alert `ML_SERVICE_DOWN` | Start the ML service; predictions work again within seconds |
| `NO_PRODUCTION_MODEL` (409) | No model passed the production gates (the current state) | Pass `modelId` to query a CANDIDATE model; results are research only |
| `TEST_PERIOD_LOCKED` (403) | The request falls in the held-out test period | Use a validation-period timestamp |
| `MODEL_OUT_OF_DISTRIBUTION`, `LOW_CONFIDENCE`, `FEATURES_INVALID` | The model abstained | Expected for most rows; see docs/ml-service.md |
| `DATA_UNAVAILABLE` | No stored data for the question | Seed the database or run a replay |
| 409 "this record already exists" | Duplicate create (two requests at once, or a name in use) | Nothing; the first request won |
| 429 | Rate limit (120/min per address, 10/min on login and register) | Wait a minute |
| 403 "CSRF token missing or invalid" | A write without the `x-csrf-token` header | Send the `csrf_token` cookie value in `x-csrf-token` |
| `API_UNAVAILABLE` (502, from the web app) | The web proxy cannot reach the API | Check the `api` container and `API_URL` |

## Alerts on /monitoring
- `REDIS_DOWN`: feed status and the prediction stream fall back to the local instance; start Redis, the
  API reconnects.
- `FEED_DOWN`: only with a provider configured and during NSE hours (Mon-Fri 09:15-15:30 IST). Check the
  live pipeline container and the Kite access token (valid one trading day).
- `LATENCY_HIGH`: API p95 over 5 minutes above `API_LATENCY_P95_MS`, or ML p95 above `ML_LATENCY_P95_MS`.
  Phase 20 load numbers are in reports/phase20_load.md.
- `MODEL_DRIFT_DETECTED`: accuracy or calibration degraded beyond 99% of historical windows. The model
  is never replaced automatically; review it (docs/monitoring.md).

## Live pipeline
- "API sink ... queued for retry": the API was unreachable. Requests wait in order and are resent with
  backoff (up to 60 s); the run summary `sinks.api` shows `pending` and `dropped`. Every prediction is
  also in the local JSONL file.
- Feed shows REPLAY, never LIVE: the replay provider is in use (by design). LIVE needs Kite credentials
  and network access to api.kite.trade / ws.kite.trade.
- Predictions all abstain: the confidence gate leaves well under 1% of rows as calls (Phase 18).

## ML service
- A model missing from `/models` with "artifact integrity check failed": a file in
  `data/registry/artifacts/<model>/v<n>/` changed after registration. Restore it from git; never edit
  artifacts by hand.
- `PULSETRADER_DATA_DIR` must point to the data directory with `registry/` and `datasets/`.

## Local development
- PostgreSQL or Redis down after a container restart: `service postgresql start; redis-server --daemonize yes`.
- Web e2e login failures: start the API with `AUTH_RATE_LIMIT_PER_MINUTE=40` (the suite logs in often).
- Stop servers by exact PID (`ps -eo pid,args`), never by pattern.
- Disk full: build caches (`npm cache clean --force`, `~/.cache/pip`, `~/.cache/uv`) are safe to delete;
  never delete `data/raw`.
- `prisma migrate reset` deletes all data: do not run it without explicit consent. Use
  `prisma migrate deploy`; e2e tests use their own schema.
