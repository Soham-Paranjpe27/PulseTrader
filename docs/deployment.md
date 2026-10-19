# Deployment

PulseTrader runs as five containers (`docker-compose.yml`): `postgres`, `redis`, `ml-service`, `api`,
`web`, plus the optional `live-pipeline` (profile `live`). Only the web app (port 3000) and the ML
service (port 8000, for research use) are published. The API is reachable only through the web app's
same-origin `/api` proxy and the internal network, because it trusts one proxy hop for client
addresses (`TRUST_PROXY=1`).

## What the host needs
- Docker with compose v2, about 4 CPUs and 8 GB RAM for the stack (the research pipeline itself needs
  up to 15 GB, see knowledge.md).
- The data directory produced by the ML pipeline: `data/registry` (committed), `data/datasets`,
  `data/canonical`, `data/reference` (all built by `pulsetrader fetch/pipeline/security/dataset`).
  The ML service mounts them read-only.
- Optional live data: a Zerodha Kite Connect key, secret and a daily access token, and outbound access
  to `api.kite.trade` and `ws.kite.trade`.

## First start
```
cp .env.example .env                      # then set real values; never commit .env
openssl rand -hex 32                      # use for JWT_SECRET and LIVE_INGEST_TOKEN
openssl rand -hex 16                      # use for POSTGRES_PASSWORD
docker compose up -d --build              # postgres, redis, ml-service, api, web
docker compose ps                         # every service should become "healthy"
```
The API container runs `prisma migrate deploy` before it starts, so the schema is always current.
Seed reference data once (instruments and daily bars from the research data):
```
cd ml && PULSETRADER_DATA_DIR=../data .venv/bin/pulsetrader export-app        # data/app
docker compose cp ../data/app api:/tmp/app
docker compose exec -e APP_DATA_DIR=/tmp/app api node dist/seed/seed.js   # ADMIN_EMAIL/ADMIN_PASSWORD optional
```
Open http://localhost:3000. Swagger: http://localhost:3000/api/docs.

## Live data
`MARKET_DATA_PROVIDER=kite` plus `MARKET_DATA_API_KEY`, `MARKET_DATA_API_SECRET` and today's
`MARKET_DATA_ACCESS_TOKEN` (from `pulsetrader kite-login`, valid one trading day), then
`docker compose --profile live up -d live-pipeline`. Without credentials use a replay
(`MARKET_DATA_PROVIDER=replay LIVE_REPLAY_DATE=2025-06-13`), which is always shown as REPLAY, never LIVE.
See docs/live-data.md.

## Production settings
| Setting | Value |
|---|---|
| `COOKIE_SECURE` | `true` behind HTTPS (cookies are then Secure) |
| `WEB_ORIGIN` | the public origin of the web app (CORS) |
| `WEB_TRUSTED_PROXY_HOPS` | number of proxies in front of the web app that append `X-Forwarded-For` (0 if clients connect directly) |
| `RATE_LIMIT_PER_MINUTE`, `AUTH_RATE_LIMIT_PER_MINUTE` | 120 and 10 per client address |
| `MONITOR_INTERVAL_SECONDS` | 60; alerts appear on /monitoring |
| `API_LATENCY_P95_MS`, `ML_LATENCY_P95_MS` | 1000 and 500 (LATENCY_HIGH alert) |

Terminate TLS in front of the web container (a reverse proxy or load balancer) and set
`WEB_TRUSTED_PROXY_HOPS=1` there.

## Health checks
Every image has a `HEALTHCHECK`: web `GET /`, api `GET /api/health`, ml-service `GET /health`;
compose adds `pg_isready` and `redis-cli ping`. Readiness with dependency detail:
`GET /api/health/ready` (503 when the database is down) and the ML service `GET /ready`.

## Backups
```
docker compose exec postgres pg_dump -U pulsetrader -Fc pulsetrader > backup.dump
docker compose exec -T postgres pg_restore -U pulsetrader -d pulsetrader --clean < backup.dump
```
Verified in Phase 20 (reports/phase20_hardening.md): dump 14 s, restore 14 s, every table's row count
and checksums equal. Model artifacts live in `data/registry` (in git); research data can be rebuilt
from the raw download.

## CI
`.github/workflows/ci.yml`: ML (format, lint, mypy, pytest, pip-audit), API (format, lint, typecheck,
build, unit, e2e on PostgreSQL + Redis, migration drift check, npm audit), web (format, lint, typecheck,
unit, build, npm audit), docker (builds all images and runs `scripts/hardening/compose_smoke.sh`:
compose up, health checks, register/login through the web app, API port not published, non-root
containers), security (gitleaks over the full git history, actionlint).

## Upgrading
Pull, `docker compose up -d --build`. Migrations apply on API start. A model change goes through the
registry (docs/model-registry.md); the ML service refuses an artifact whose files no longer match their
recorded SHA-256 (`sha256.json`).
