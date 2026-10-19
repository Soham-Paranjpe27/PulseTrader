# Backend API (Phase 15)

NestJS 11 + TypeScript 5.9 + Prisma 6 (PostgreSQL 16) + Redis, in `api/`. Swagger UI: `/api/docs`
(JSON at `/api/docs-json`). All routes are under `/api`.

## Run locally
```
cd ml && PULSETRADER_DATA_DIR=../data .venv/bin/pulsetrader export-app      # data/app/{stocks.json,day_bars.csv}
cd api && npm ci && cp ../.env.example .env   # fill in DATABASE_URL, JWT_SECRET (>= 32 random chars)
npx prisma migrate deploy && npm run build && APP_DATA_DIR=../data/app npm run seed
npm start                                      # :3001; needs the ML service on ML_SERVICE_URL for predictions
npm test && npm run test:e2e                   # e2e needs TEST_DATABASE_URL (own schema per run)
```

## Modules and main routes
| Module | Routes |
|---|---|
| auth | POST /auth/register, /auth/login, /auth/refresh, /auth/logout; GET /auth/me |
| users | GET/PATCH /users/me; GET /users (ADMIN) |
| stocks | GET /stocks?q&type&universe&page&pageSize; GET /stocks/:symbol (quote, latest prediction, recent accuracy, live status) |
| market-data | GET /market-data/status; /market-data/:symbol/daily?from&to; /market-data/:symbol/intraday?date (ML /bars); /market-data/:symbol/indicators?date (ML /indicators). Without `date`: the latest stored session that has minute data |
| predictions | POST /predictions, /predictions/batch; GET /predictions, /predictions/:id, /predictions/accuracy; SSE /predictions/stream |
| models | GET /models, /models/active, /models/:id (mirror of the ML registry) |
| features | GET /features/versions, /features/versions/:v, /features/schema |
| watchlist | GET/POST /watchlists; DELETE /watchlists/:id; POST/DELETE /watchlists/:id/items[/:symbol] |
| alerts | GET/POST /alerts; PATCH/DELETE /alerts/:id |
| portfolio | GET/POST /portfolios; GET/DELETE /portfolios/:id; POST /portfolios/:id/trades (paper, long-only) |
| research | POST /research/ask |
| health | GET /health (liveness), GET /health/ready (db, redis, ML service, feed state) |
| admin | POST /admin/sync/registry, /admin/alerts/evaluate; GET /admin/audit (ADMIN) |

## Behaviour that matters
- Behind the web app's `/api` proxy set `TRUST_PROXY=1` so throttling and the audit log see client addresses.
- Predictions come only from the ML service. With no PRODUCTION model, a request without `modelId`
  returns 409 `NO_PRODUCTION_MODEL`; candidate predictions are stored with `researchOnly: true`.
- Live feed state is `DISCONNECTED` until the Phase 17 pipeline runs; it is never reported LIVE.
- Quotes and portfolio valuations use the latest stored daily bar and say so (`note` / `pricing`).
- The research assistant parses a fixed set of intents and answers only from stored data; it returns
  `DATA_UNAVAILABLE` (e.g. no per-prediction attributions, no evaluated outcomes yet) or `UNSUPPORTED`.
- Sectors are inferred (Phase 11) and labelled "(inferred)".
- Seed data is real (`export-app` from the canonical dataset): 2,535 instruments, 2.07M daily bars.

## Database
Schema: `api/prisma/schema.prisma` (16 entities from spec section 53), migrations in `api/prisma/migrations`.
Minute bars and features stay in Parquet.
