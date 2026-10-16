# knowledge.md — PulseTrader V4 project state

Last updated: 2026-10-16.

## Current phase
Phase 0 done. Phase 1 (dataset discovery) is BLOCKED: the cloud environment's network policy refuses
huggingface.co and cdn-lfs.huggingface.co, so the dataset cannot be downloaded. PyPI works.
Code for Phases 1, 2, 4, 5 and the Phase 6 leakage tests exists and passes on the golden test
dataset only. No real-data statistics exist yet; none are claimed.

## Next exact action
1. Once huggingface.co is reachable: `cd ml && PULSETRADER_DATA_DIR=../data .venv/bin/pulsetrader fetch`
   (check `df -h` first; ~30 GB free disk, 15 GB RAM in the cloud container).
2. `pulsetrader discover` -> reports/dataset_manifest.json, reports/data_inventory.md. Adapt
   `data/schema.py` aliases if the real schema differs.
3. `pulsetrader pipeline` -> data/canonical + reports/data_quality_report.md. Investigate weekend
   and non-regular sessions, holidays.
4. Phase 3 security master + corporate-action audit, then Phase 4/5 on real data, Phase 6 gate.

## Environment
4 CPU, ~15 GB RAM, ~30 GB free disk, no GPU (cloud container). Python 3.13, Node 22.
Repo is developed in a local clone and mirrored to /mnt/project-files/pulsetrader (network mount).
No GitHub remote yet.

## Architecture (so far)
- `ml/src/pulsetrader/`: config, data/{schema,validate,io,discovery,pipeline}, features/{engine,preprocess},
  labels/labels, splits/splits, eval/metrics, serve/app (health/ready only), cli.
- Docker baseline: docker-compose (postgres, redis, ml-service). ml/Dockerfile. CI: .github/workflows/ci.yml.
- Backend (NestJS) and frontend (Next.js): not started.

## Versions
- schema `canonical-v1`, processing `pipeline-v1`, features `features-v1`, labels `labels-v1`.
- Dataset versions: none (no real data yet).
- Model versions / experiments: none.

## Decisions
- Canonical keeps REGULAR session bars only by default; others counted and reported (docs/data-pipeline.md).
- Labels never cross session boundaries; missing future bar -> null label.
- Rolling technical features span overnight; intraday features reset daily.
- Prediction time for bar t = bar close (t + 1 min).
- CCI uses rolling std (documented variant).

## Phase status
| Phase | Status |
|---|---|
| 0 Repository | DONE (lint, mypy, 36 tests pass) |
| 1 Discovery | CODE DONE, BLOCKED on data access |
| 2 Pipeline | CODE DONE, tested on golden data; not run on real data |
| 3 Security master | NOT STARTED |
| 4 Features | CODE DONE (golden-tested); not run on real data |
| 5 Labels | CODE DONE (golden-tested) |
| 6 Leakage audit | PASSED on golden data; must re-run on real data |
| 7–20 | NOT STARTED |

## Known issues
- Dataset unreachable from the cloud environment (network policy).
- No market-data provider credentials; live phases will use the provider interface, MockProvider in tests only.
- Sector mapping and NSE holiday calendar not available offline.

## Commands
See AGENTS.md. Tests: `cd ml && .venv/bin/pytest` (36 passed on 2026-10-16).
