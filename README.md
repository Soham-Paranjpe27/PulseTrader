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
scripts/hardening/  Phase 20 security, load, failure and compose smoke tests
experiments/   one directory per experiment, never overwritten
```

## Documentation
Architecture and operations: docs/architecture.md, docs/deployment.md, docs/security.md,
docs/troubleshooting.md, docs/monitoring.md. Data and models: docs/data-pipeline.md,
docs/feature-engineering.md, docs/labels.md, docs/leakage-prevention.md, docs/model-training.md,
docs/model-evaluation.md, docs/walk-forward.md, docs/backtesting.md, docs/model-registry.md,
docs/ml-service.md, docs/live-data.md. Results: docs/model-card.md, docs/final-audit.md.

**Result in one line:** the best models reach validation MCC 0.19 at full coverage (accuracy ~50%,
balanced accuracy ~45%), far from the 70-80% accuracy target, and lose money after Indian intraday
costs. They stay CANDIDATE, research only.

## Quick start
```
cd ml && python -m venv .venv && .venv/bin/pip install -e ".[dev,serve,fetch]"
.venv/bin/pytest
docker compose up -d   # from repo root: postgres, redis, ml-service, api, web (:3000)
```
Copy `.env.example` to `.env` for secrets. Never commit `.env`.
