# Phase 20: production hardening summary (2026-10-19)

All checks ran on the local stack (PostgreSQL 16, Redis, ML service, NestJS API, Next.js web) on one
4-CPU container with real data. Figures are measured, not estimated.

## Issues found and fixed
| # | Issue | Found by | Fix |
|---|---|---|---|
| 1 | Browser could spoof `X-Forwarded-For` via the web proxy: bypassed the login rate limit, faked audit IPs | security check (rotating XFF) | `web/xff-guard.cjs` preload; `WEB_TRUSTED_PROXY_HOPS` |
| 2 | compose published API port 3001, bypassing the trusted proxy hop | config review | `expose` only; smoke test asserts 3001 is closed |
| 3 | Concurrent paper trades lost cash updates and could oversell | concurrency e2e test | transaction + `SELECT … FOR UPDATE` |
| 4 | Duplicate-create races answered 500 | concurrency e2e test | global Prisma error filter: 409 / 404 / 503 |
| 5 | PostgreSQL outage answered 500 | failure test | 503 `DATABASE_UNAVAILABLE`; API recovers without restart |
| 6 | Live pipeline dropped predictions while the API was down | outage replay | ordered retry queue with backoff in `ApiSink` |
| 7 | Accuracy endpoint 4.6 req/s, p95 11 s at concurrency 32 | load test | 15 s cache + index: 575 req/s, p95 83 ms |
| 8 | CSP allowed inline scripts | header review | per-request nonce CSP (`strict-dynamic`) |
| 9 | A changed model file would be served silently | reproducibility review | `sha256.json` per artifact, enforced at load |
| 10 | A monitoring request arriving during a running check got the previous (stale) result; seen once as a flaky e2e failure | full e2e run | callers share the in-flight check |

## Results by area
| Area | Result | Report |
|---|---|---|
| Security | 52/52 black-box checks (JWT forgery, cookies, CSRF, IDOR, roles, ingest token, injection, input limits, headers, rate limits); npm audit 0 (api, web), pip-audit 0, gitleaks 0 leaks over the full history; detect-secrets: 21 hits, all placeholders / fixtures | phase20_security.md |
| Load | 0 errors on 7 scenarios at concurrency 1/8/32; e.g. search 618 req/s p95 70 ms, POST prediction via ML 174 req/s p95 260 ms (c=32) | phase20_load.md |
| Failure | 22/22: ML, Redis, PostgreSQL stopped and restarted one at a time; clean 503s, alerts raised and cleared, recovery without API restart, sessions kept | phase20_failure.md |
| API outage in a live run | REPLAY of 2025-02-04, API killed 45 s mid-run: 6 failed posts retried, 0 dropped; database holds 15,000/15,000 predictions and outcomes | this file |
| Database | `pg_dump -Fc` 49.6 MB in 14 s, restore 14 s; all 19 tables match (row counts; md5 of MarketData 2,073,963 rows, User, and the 83,275 predictions present before the dump); migration drift check "No difference detected"; restore DB dropped afterwards | this file |
| ML reproducibility | refit of both models byte-identical (model, preprocessor, features, calibrator); validation predictions max diff 2.98e-08 over 1.1M rows each; dataset rebuilt from canonical for 6 random symbols: 0 mismatches | phase20_repro.md |
| Docker | `docker compose config` valid; ml `.dockerignore`; image builds cannot run here (package mirrors blocked by the network policy), so CI builds every image and runs `scripts/hardening/compose_smoke.sh` (health, readiness, register/login via web, API port closed, CSP nonce, non-root) | ci.yml docker job |
| CI/CD | new `security` job (gitleaks, actionlint), migration drift check in the api job, compose smoke in the docker job; actionlint passes locally | .github/workflows/ci.yml |

## Test suites (final run)
ML 103 pytest + ruff + mypy; API 31 unit + 16 e2e (e2e run 3 times after the monitoring fix), lint, typecheck, build; web 16 unit + 14 browser e2e, lint, typecheck, build. All pass.

## Known limits
- Load numbers are from one machine with the load generator on it; they show headroom and the absence of
  errors, not production capacity.
- With the ML service down, `/api/health/ready` still reports ready (degraded: data pages work, predictions 503).
- Real LIVE data is untested (no Kite credentials; Kite hosts blocked here). Everything live-related is REPLAY.
- The final test period is untouched (test NOT_RUN).
