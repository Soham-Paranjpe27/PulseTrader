# Architecture

```
 Hugging Face minute + daily bars (raw, read-only)
        │  pulsetrader fetch / discover / pipeline / security / dataset        (ml/, Python)
        ▼
 data/canonical (regular-session bars per symbol) ── data/reference (security master, day bars)
        │  shared feature engine (features/engine.py) + labels (labels/labels.py)
        ▼
 data/datasets/core100_s5 (train / validation / test, purge + embargo)
        │  classical, deep, optimize (walk-forward), calibrate, robustness, backtest
        ▼
 data/registry (artifacts + gates, SHA-256 per file) ──► ML service (FastAPI :8000)
                                                          ▲             │ predictions
 Market data provider (Kite / replay) ─► live pipeline ───┘ same engine │
        (candles, validation, features, outcomes, drift) ──► API (NestJS :3001, internal)
                                                          PostgreSQL · Redis
                                                                         │ /api proxy
                                                          Web (Next.js :3000) ◄── browser
```

## Components
| Component | Code | Role |
|---|---|---|
| Data pipeline | `ml/src/pulsetrader/data/` | Validate raw bars, keep regular sessions, write canonical files (docs/data-pipeline.md) |
| Security master | `security/` | Instrument types, eligibility, corporate-action audit |
| Feature engine | `features/engine.py` | The only implementation of every feature, used by the dataset builder, the ML service and the live pipeline (docs/feature-engineering.md) |
| Labels and splits | `labels/`, `splits/` | Direction labels per horizon and threshold; chronological splits with purge and embargo (docs/labels.md, docs/leakage-prevention.md) |
| Experiments | `experiments/` | Phase 7-13 runners; every run gets its own directory in `data/experiments` |
| Registry | `registry/registry.py` | Model records, statuses, gate evidence, artifact digests (docs/model-registry.md) |
| ML service | `serve/` | FastAPI inference, abstention, test-period lock, /metrics (docs/ml-service.md) |
| Live pipeline | `live/` | Providers, candle aggregation, validation, features, predictions, outcomes, API sink with retry queue (docs/live-data.md) |
| Monitoring | `monitor/` | Drift references and checks (docs/monitoring.md) |
| API | `api/src/` | NestJS 11 + Prisma 6: auth, stocks, market data, predictions, live ingestion, monitoring, watchlists, alerts, paper portfolios, research assistant (docs/backend.md) |
| Web | `web/src/` | Next.js 15 dashboard; same-origin `/api` proxy, nonce CSP (docs/frontend.md) |

## Data flow rules
- Raw data is never modified. Each stage writes a new versioned output (`canonical-v1`, `features-v2`,
  `labels-v1`, `dataset-v1`).
- Training, serving and live use the same feature code; parity is tested (Phase 14: 3e-8, Phase 17:
  84/84 features equal on every row).
- The test period (2025-06-16..2026-01-21) is refused by the ML service and the replay provider.
- Predictions carry their mode: HISTORICAL, CLIENT_FEATURES, REPLAY or LIVE. Only the token-authenticated
  live pipeline can store REPLAY/LIVE, and a replay is never stored as LIVE.

## Storage
| Store | Holds |
|---|---|
| Parquet under `data/` | Bars, features, labels, datasets, experiment outputs (git-ignored, rebuildable) |
| `data/registry` | Model artifacts and registry.json (in git) |
| PostgreSQL | Users, sessions, instruments, daily bars, predictions + outcomes, watchlists, alerts, portfolios, audit log, monitoring reports, system alerts (`api/prisma/schema.prisma`) |
| Redis | Live feed status (120 s TTL), prediction stream fan-out between API instances |

## Deployment
docker-compose services and health checks: docs/deployment.md. Security controls: docs/security.md.
