# PulseTrader V4

Research platform for short-horizon direction prediction on Indian equities (NSE minute data), built
to measure honestly whether high directional accuracy is achievable, with leakage-safe evaluation.

Status and results: see `knowledge.md`. Rules for contributors and agents: see `AGENTS.md`.

## Layout
```
ml/            Python package `pulsetrader`: data pipeline, feature engine, labels, splits, metrics, ML service
  tests/       unit + leakage tests on a deterministic offline golden dataset
data/          raw (immutable) and derived datasets — git-ignored
reports/       generated data inventory and quality reports
docs/          design and audit documents
api/           NestJS backend (Prisma/PostgreSQL, Redis, JWT cookies)
web/           Next.js dashboard (docs/frontend.md)
experiments/   one directory per experiment, never overwritten
```

## Quick start
```
cd ml && python -m venv .venv && .venv/bin/pip install -e ".[dev,serve,fetch]"
.venv/bin/pytest
docker compose up -d   # from repo root: postgres, redis, ml-service, api, web (:3000)
```
Copy `.env.example` to `.env` for secrets. Never commit `.env`.
