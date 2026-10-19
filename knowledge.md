# knowledge.md — PulseTrader V4 project state

Last updated: 2026-10-19 (phase 18 done).

## Current phase
Phases 0–18 DONE on real data (Phase 18 finished 2026-10-19). Next: Phase 19 (monitoring).

## Next exact action
1. Phase 19 (monitoring, spec sections 48-50): drift and health monitoring on top of the Phase 18
   outcomes: feature drift (PSI/KS vs training) per feature from live feature rows, prediction/confidence
   drift, rolling live accuracy/MCC/coverage vs validation with alert thresholds, feed health history,
   API/ML latency and error rates; surface on the dashboard and as alerts. Keep LIVE and REPLAY separate.
   Real LIVE still needs the user's Kite Connect key/secret + daily access token and network access to
   api.kite.trade / ws.kite.trade (both blocked here). Local stack: `service postgresql start;
   redis-server --daemonize yes`; ML :8000, API :3001 (`AUTH_RATE_LIMIT_PER_MINUTE=40 TRUST_PROXY=1
   LIVE_INGEST_TOKEN=... node dist/main.js`), web :3000 (docs/frontend.md), replay: docs/live-data.md.
2. If the container was recycled, data/ is gone: torch needs `pip install torch --index-url
   https://download.pytorch.org/whl/cpu`, then `pulsetrader fetch`, `pipeline`, `security`, `dataset`
   (~35 min), then `pulsetrader optimize --steps W` / `T` to recreate Phase 9 predictions.

## Environment
4 CPU, ~15 GB RAM, ~252 GB disk but ~12 GB free after data, no GPU. Python 3.13 venv in ml/.venv.
Network: huggingface.co + *.hf.co allowed (cloud env "SohamParanjpe"); nseindia.com blocked.
Repo: https://github.com/Soham-Paranjpe27/PulseTrader (canonical). `main` = empty root commit;
work on `claude/pulsetrader-phase0`, draft PR #1. Working clone: /home/user/pulsetrader (container
disk; data/ lives there and is NOT in git). /mnt/project-files/pulsetrader is an older mirror.
- Polars streaming group_by over all canonical files spilled 11 GB to /var/tmp and filled the disk.
  Process canonical data one symbol file at a time instead (each file is one symbol).

## Data (all figures computed, see reports/)
- Source: HF xxparthparekhxx/indian-stock-market-minute-data, 9 parquet files, 10.5 GB, raw read-only
  in data/raw (minute/train-0000[0-7], day/train-00000). Timestamps are UTC (tz-aware); 03:45 UTC = 09:15 IST.
- Raw rows 720,421,072: minute 713,452,456 (2022-01-03 .. 2026-01-21, 999 trading dates),
  daily 6,968,616 (2000-01-01 .. 2026-01-22). 2,535 symbols in both.
- Canonical (pipeline-v2, dataset_version canonical-v1-8cc94bf262aa): 711,154,701 regular-session
  minute bars, one file per symbol in data/canonical (6.7 GB); daily bars in data/canonical_daily.
- Quality: 0 nulls, 0 duplicates, 18,637 non-positive prices, 2,915 OHLC-inconsistent, 2 negative volume.
- Special sessions (excluded, documented in docs/data-pipeline.md): Muhurat 2022-10-24, 2023-11-12,
  2024-11-01; Saturdays 2024-01-20, 2024-03-02, 2024-05-18, 2025-02-01. 59 weekday holidays found.
- Prices are back-adjusted by the vendor for splits/bonuses (not demergers). Only scale-free features
  are point-in-time safe.
- Survivorship bias: no symbol ends before the dataset end; delisted stocks are absent.

## Security master (Phase 3, secmaster-v1) — data/reference/, reports/security_master.md
- 2,116 EQUITY, 287 ETF, 129 INDEX, 3 OTHER. 783 symbols listed after 2022-01; 0 ended.
- 1,311 experiment-eligible equities (>=250 days, <=20% zero-volume days, median daily turnover
  >= INR 1 crore).
- Corporate-action audit: 198 overnight gaps >20% and 211 intraday jumps >20% (all instruments);
  equities 148 gaps in 134 symbols, 18 at split ratios. Policy: exclude event session + next session.
- Index series for market context: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50, INDIA VIX,
  sector indices ("NIFTY IT", ...).

## Research dataset (Phases 4-5, dataset-v1) — data/datasets/core100_s5, reports/research_dataset_core100_s5.json
- `pulsetrader dataset` (373 s, 2.6 GB peak RAM, 1.8 GB on disk, 51 monthly parquet files).
- Universe: top 100 eligible equities by median daily turnover over 2022-01-03..2023-01-04 only.
- Rows sampled every 5 minutes; first 250 bars, sessions <370 bars and corporate-action sessions
  (+ next session) excluded. 7,470,060 rows, 84 features (features-v2), labels for 1/5/15/30/60 min
  at 5/10/20/30/50 bp.
- Splits: train 2022-01-03..2024-11-04 (5,227,860 rows), validation 2024-11-05..2025-06-13
  (1,116,225), test 2025-06-16..2026-01-21 (1,123,575); 2,400 rows purged/embargoed (60 min).
- Train label balance (down/flat/up): y_15m_10bp 0.317/0.382/0.300, y_15m_20bp 0.192/0.625/0.183,
  y_60m_30bp 0.248/0.522/0.230. The flat class dominates at higher thresholds, so plain accuracy
  is misleading; balanced accuracy and MCC are required.

## Leakage gate (Phase 6) — reports/leakage_audit_real.md: PASSED on real data
`pulsetrader audit`: perturbation (single-symbol, NIFTY market context, cross-sectional), timestamps,
3.7M labels recomputed from canonical, purge/embargo, point-in-time universe, scaler isolation.

## Phase 7 results (classical-v1) — reports/phase7_classical.md, data/experiments/ (824 MB)
`pulsetrader classical` (6,233 s, 5.5 GB peak RAM). 25 labels (5 horizons x 5 thresholds), validation only.
Models: majority, random, no-change, always-up, momentum, logistic, LightGBM on all labels; RF and
XGBoost at 0.10% and 0.20% only (run-time budget). Trained on every 15th minute of train (~1.57M rows);
boosted trees early-stop on the last 10% of train dates (purged + 60-min embargo).
- No model is near the 70-80% target on a meaningful basis. High accuracies (82-99.7% at 1m/5m with
  large thresholds) are majority NEUTRAL behaviour: balanced accuracy 35-36%, verdict FAILED.
- Best validation MCC: 0.166 (LightGBM, 1m, 0.05%, acc 59.3% vs majority 58.1%, bal acc 39.2%),
  0.157 (XGBoost, 5m, 0.10%, acc 56.4% vs 55.1%, bal acc 39.1%). Skill is mostly "move vs no move";
  pure direction skill is weak: up/down AUC 0.51-0.59.
- Momentum rule beats every learned model on MCC for 9 of 25 labels (all at large thresholds).
- Selective UP/DOWN: sign accuracy 50-55% at 0.2-8% coverage; no confidence level >= 0.6 gives a
  usable number of predictions. Learned probabilities are well calibrated (ECE <= 0.02).
- Train-sample accuracy is close to validation (no large overfit).

## Phase 8 results (deep-v1, DONE 2026-10-18) — reports/phase8_deep.md
PyTorch 2.14 CPU. Sequences = last L 5-minute dataset rows of the same stock (datasets/sequences.py).
- Stage A (y_5m_10bp, L=60): transformer MCC 0.157, GRU+attn 0.155, LSTM+attn 0.154, LSTM 0.153,
  GRU 0.150; all ~56.4% accuracy vs majority 55.1%. Same level as XGBoost (0.157).
- Stage B (transformer): L=30 0.146, L=60 0.157, L=120 0.161 (best), L=252 0.139 (L>=120 trained with
  samples scaled by 60/L, max 4 epochs, to fit CPU time).
- Stage C (transformer L=120): y_1m_5bp MCC 0.167 (acc 59.2%, LightGBM 0.166); y_15m_20bp 0.136
  (acc 61.2%, XGBoost 0.134); y_30m_20bp 0.128 (acc 49.2%, bal 38.6%, XGBoost 0.123); y_60m_30bp 0.113
  (acc 50.6%, bal 37.3%, LightGBM 0.108).
- Conclusion: deep models tie gradient boosting (gaps 0.001-0.005 MCC, single seed = noise); selective
  UP/DOWN sign accuracy 50-58% at <=7% coverage. No usable high-confidence regime.

## Phase 9 results (optimize-v1, DONE 2026-10-18) — reports/phase9_optimization.md, docs/walk-forward.md
Folds: first 40% of train dates = training only; F1-F4 = 4 equal windows over the rest of train; F5 = validation.
Purge (train label end <= window start), 60-min embargo, preprocessor fit per window, test never read.
- Walk-forward LightGBM (defaults), mean MCC over 5 folds, std ~0.01: 1m_5bp 0.174, 5m_10bp 0.165,
  15m_20bp 0.142, 30m_20bp 0.137, 60m_20bp 0.119 (chosen threshold per horizon). Validation is the weakest fold.
- Optuna (25 TPE trials, objective = mean MCC on F3+F4): balanced class weights + lr ~0.03 win.
  Validation MCC y_1m_5bp 0.166 -> 0.194 (acc 50.1%, bal 45.2%); y_5m_10bp 0.155 -> 0.168 (acc 48.0%, bal 43.1%).
- Feature selection (decided on F4): top-20 by permutation ~= all 84 (val MCC 0.154 vs 0.155); technical
  group matters most. Ensembles (LGB+XGB weighted/stacked, LGB+transformer) within +-0.004 MCC: no gain.
- Selective UP/DOWN (threshold chosen OOF): ~4-5% coverage, sign accuracy 51-54%. Gate: NOT VERIFIED.
- Lesson: loading a new horizon while the previous DevData lives exceeds 15 GB; `_free(dev)` between horizons.

## Phase 10 results (calibrate-v1, DONE 2026-10-19) — reports/phase10_calibration.md
Calibrators fit on Phase 9 OOF folds F1-F4 (method chosen by Brier on F4 after fitting on F1-F3), applied to F5.
- Default LightGBM already calibrated (top-class ECE 0.006-0.013); calibration changes Brier < 0.001.
- Tuned (balanced-weight) LightGBM: classwise ECE 0.13-0.14 -> 0.012-0.019; Brier 0.601 -> 0.532 (1m).
  Isotonic chosen everywhere; Platt within 0.001 Brier. Argmax of calibrated probs reverts to default
  behaviour (MCC 0.194 -> 0.165), so decisions use raw tuned output / class bias, reported probability = calibrated.
- High-confidence (top prob >= 0.7) rows are ~all NEUTRAL (acc 81-90%); directional P>=0.5 covers 0.3%, sign acc 57%.

## Phase 11 results (robustness-v1, DONE 2026-10-19) — reports/phase11_robustness.md
Tuned LightGBM walk-forward OOF predictions; buckets from training-period info only; sectors inferred
(max residual daily-return correlation with NIFTY sector indices, no offline sector master).
- Skill is mostly move-vs-no-move (binary MCC 0.27 on 1m) not direction (55.8% right on moved+called rows).
- All 100 stocks MCC > 0 and beat momentum; trend/vol/sector buckets MCC 0.16-0.21 (1m). Weak at 09:15-09:45 (0.04).
- Fold MCC declines 0.241 (2023) -> 0.194 (validation): edge shrinking over time.
- Per-call gross 0.5-1.9 bp; break-even < 2 bp round trip, so negative after realistic NSE costs.

## Phase 12 results (backtest-v1, DONE 2026-10-19) — reports/phase12_backtest.md, docs/backtesting.md
Event-driven engine (backtest/engine.py): entry next bar open, exit at horizon close or session close,
optional SL/TP, 10 positions x 10% equity, one per symbol, Indian intraday charges + 1 bp slippage per side
(~10.2 bp round trip at Rs 1 lakh). Validation 2024-11-05..2025-06-13, tuned LightGBM signals.
- Zero costs: 1m model +47.9% (avg 0.38 bp/trade) and 5m +21.3% beat momentum (-24%/-32%), random
  (+3%/+10%) and always-long (+8%/+10%). Buy-and-hold +1.5% after costs.
- With costs all intraday strategies lose: ungated -> ~-100%; gate chosen on pre-validation folds
  (1m P>=0.60, 5m P>=0.56) gives 1.1/2.5 bp gross per trade, still -9.5% / -34.4% net.
- Signal is real but 4-10x too small for intraday costs. Not tradeable.

## Phase 13 results (registry-v1, DONE 2026-10-19) — reports/model_registry.{md,json}, docs/model-registry.md
- Registry data/registry/registry.json (atomic JSON) + artifacts/{model_id}/v{n}/ (model.txt booster,
  preprocessor.json, features.json, calibrator.json, model_meta.json). data/registry (12 MB) IS committed so later phases survive a container
  recycle; copy also in reports/model_registry.json. Rebuild: `pulsetrader registry register`.
- Statuses EXPERIMENT/CANDIDATE/SHADOW/PRODUCTION/RETIRED/REJECTED with gate-checked transitions.
- lightgbm-y_1m_5bp-tuned@v1 and lightgbm-y_5m_10bp-tuned@v1: CANDIDATE. All candidate gates PASSED
  (refit reproduces stored validation predictions, max diff 3e-8). backtest_passed FAILED,
  test_passed/shadow_passed NOT_RUN, so neither can reach SHADOW/PRODUCTION. Accuracy gate NOT VERIFIED.

## Phase 14 results (DONE 2026-10-19) — reports/phase14_inference.{md,json}, docs/ml-service.md
- FastAPI: /health /ready /predict /predict/batch /models /models/active /features /metrics, loaded from
  the registry. HISTORICAL mode reads dataset rows; `features` input for live. Test period -> 403
  TEST_PERIOD_LOCKED. No PRODUCTION model -> unnamed requests 409 NO_PRODUCTION_MODEL; CANDIDATE
  models served only by model_id with research_only=true.
- Parity on 3,000 real validation rows per model (historical and features input): max abs diff 3e-8
  vs stored Phase 9 predictions. Abstention on that sample: 1m covers 0.1% (4 calls), 5m 0.7% (21 calls),
  rest LOW_CONFIDENCE, ~0.2% OOD. ~460 rows/s via batch incl. partition loads.
- Docker: Dockerfile adds libgomp1 (LightGBM); compose mounts data/registry + data/datasets read-only.
  No docker daemon here; CI runs `docker build ml`.

## Phase 15 results (DONE 2026-10-19) — docs/backend.md, docs/security.md
- api/: NestJS 11.2, Prisma 6.19 (pinned known majors, not Nest 12 / Prisma 7+), TypeScript 5.9.
  Modules auth, users, stocks, market-data, predictions (+SSE), models, features, watchlist, alerts,
  portfolio (paper), research (intent parser, DATA_UNAVAILABLE), health, admin. 16 Prisma entities.
- Seeded from `pulsetrader export-app` (data/app, gitignored): 2,535 instruments, 2,073,963 daily bars
  (~3 min). Local dev DB: postgres 16 `pulsetrader` / `pulsetrader_test`, creds in api/.env (gitignored).
- Tests: 21 unit (jest) + 12 e2e on real PostgreSQL with a test-only ML HTTP stub. e2e uses a fresh
  schema per run (`migrate deploy`) and drops only that schema; `prisma migrate reset` is blocked
  for agents and must not be used without the user's consent.
- Smoke test with the real ML service: register/login, prediction stored (CANDIDATE, research only,
  LOW_CONFIDENCE abstain), research answer from stored data, models/active NO_PRODUCTION_MODEL.
- ML service gained GET /bars/{symbol}?date and richer /models rows. CI: new api job (postgres+redis
  services) and docker build api. npm audit --omit=dev: 0 (overrides js-yaml ^5.4.1, deepmerge-ts ^8);
  dev-only `braces` advisory remains.

## Phase 16 results (DONE 2026-10-19) — docs/frontend.md
- web/: Next.js 15.5 App Router, React 19.1, Tailwind 4.1, shadcn-style components, TanStack Query 5,
  Zustand 5, RHF 7 + Zod 3, lightweight-charts 5.0 (pinned exact). All 12 spec pages. Same-origin
  `/api` proxy route (API_URL at runtime, standalone output, Dockerfile, compose `web` service).
- Stock detail covers all section 57 fields. Indicators come from a new ML endpoint
  `GET /indicators/{symbol}?date` (shared feature engine on the session + 5 prior sessions; parity vs the
  research dataset max abs diff 6.5e-6 on RELIANCE 2025-01-06) plus the Phase 11 NIFTY regime. API
  proxies it as `/api/market-data/:symbol/indicators` (no date: latest session with minute data).
- Honest states shown: CANDIDATE / RESEARCH ONLY, NO_PRODUCTION_MODEL notice built from the gates,
  feed DISCONNECTED, TEST_PERIOD_LOCKED, DATA_UNAVAILABLE for accuracy until outcomes exist.
- Fixed while testing: refresh-token retry must send x-csrf-token (API checks CSRF on /auth/refresh);
  lightweight-charts fails to draw when the browser locale is invalid (headless `en-US@posix`), so the
  chart sets `en-IN` and Playwright runs with locale en-IN.
- Tests: web 13 unit (Playwright runner, no browser) + 11 browser e2e on the real stack, all pass
  (e2e not in CI: needs dataset + artifacts). ML 82 pass (new indicators test), API 21 unit + 12 e2e
  (new indicators fallback test). npm audit --omit=dev 0 for web (postcss override).
- API: `TRUST_PROXY` env (hops) so throttling/audit see client IPs behind the web proxy.

## Phase 17 results (DONE 2026-10-19) — docs/live-data.md, reports/phase17_live.{md,json}
- ml/src/pulsetrader/live/: events (Tick, Bar, FeedState incl. REPLAY), providers (MarketDataProvider;
  HistoricalProvider replay refuses the test period; SnapshotProvider; LiveProvider tick->bar base;
  MockProvider refuses to run outside tests), kite (Zerodha Kite Connect: binary tick parser, instruments
  map, historical warm-up candles, login checksum; credentials from env only), candles (aggregator,
  cumulative-volume increments), validate (9 reject reasons, FeedMonitor states), cache, features
  (shared engine + `add_cross_sectional`, which the dataset builder now also calls), pipeline (sinks:
  memory, JSONL, API), parity. CLI: `live`, `live-parity`, `kite-login`. Optional dep `.[live]` = websockets.
- Parity on 3 replayed validation sessions (2024-12-02, 2025-03-17, 2025-06-13): 84/84 features match
  the research dataset on every row (7,500 rows/day), raw probabilities match stored walk-forward
  predictions to 3e-8 for both CANDIDATE models. Feature build ~1 s per sampled bar (100 stocks).
- On 2025-06-13 the 1m model called 2 of 7,500 rows and the 5m model 58 (rest LOW_CONFIDENCE / OOD):
  the confidence gate makes live coverage very low; no live accuracy is claimed (Phase 18 measures it).
- API: new `live` module. `POST /api/live/ingest` and `/api/live/status` (x-ingest-token vs
  LIVE_INGEST_TOKEN, constant-time, no throttle/CSRF); status in Redis (TTL 120 s, else DISCONNECTED);
  a replay can never show as LIVE (forced server-side). `GET /api/market-data/:symbol/live`. User-requested
  predictions are now stored as HISTORICAL or CLIENT_FEATURES (were LIVE for client features: fixed).
  `recentAccuracy` moved to stocks/accuracy.ts (circular import broke DI).
- Web: FEED REPLAY badge, REPLAY notice with the replay price, live/delayed price replaces the stored close
  only for a real feed, LIVE/REPLAY badge in prediction tables.
- Verified end to end: replay of 2025-06-13 at 20x into the running API/web; dashboard showed
  "FEED REPLAY (recorded, not live)" and predictions stored with mode REPLAY.
- Tests: ML 95 (13 new: Kite packets, candles, validation, feed states, providers, golden replay parity,
  Mock ticks -> bars -> features parity); API 21 unit + 13 e2e (new live ingestion test); web 13 unit.

## Phase 18 results (DONE 2026-10-19) — docs/live-data.md, reports/phase18_live_eval.{md,json}
- ml live/outcomes.py: OutcomeTracker scores every prediction after its horizon with `add_labels` on the
  bars the pipeline received (same definition as training labels); target after the close -> null label.
  direction_correct only for UP/DOWN calls (actual NEUTRAL = wrong). Outcomes go to all sinks
  (API `POST /api/live/outcomes`, `<out>.outcomes.jsonl`). live/evaluate.py: per model+mode full-coverage
  acc/BA/MCC/Brier/ECE (raw+calibrated), selective calls/coverage/acc/BA/MCC, rolling 20/50/100/500,
  daily/weekly/monthly, per-call paper P&L after 10.24 bp round-trip costs (upper bound, not a backtest).
  CLI `live-eval --last N`.
- REPLAY of the last 20 validation sessions (2025-05-19..2025-06-13, 300k predictions): outcomes equal
  research labels on every row (class match 1.0, return diff <2e-9); probabilities vs walk-forward max diff
  1.8e-5 (5m) and 1.7e-3 (1m).
  | model | full acc | BA | MCC | ECE raw->cal | calls | coverage | call acc | call BA | call MCC | net bp/call |
  | 1m_5bp | 0.585 | 0.451 | 0.206 | 0.089->0.043 | 47 | 0.03% | 0.404 | 0.294 | -0.133 | -13.7 |
  | 5m_10bp | 0.568 | 0.436 | 0.188 | 0.089->0.032 | 401 | 0.27% | 0.431 | 0.422 | 0.163 | -6.4 |
  The confidence-gated calls are NOT more accurate than the full argmax (the gate picks rare extreme rows;
  many end NEUTRAL). 5m calls get the sign right 59.9% (+3.9 bp gross) but lose after costs. No 70-80%.
- API: accuracy endpoint takes mode/model/symbol and returns `performance` (pure performance.ts, unit
  tested vs scikit-learn; one raw SQL query, latest 20k outcomes, whole IST days only); list has `mode`.
- Web: Predictions page performance panel with a Mode filter (REPLAY labelled "not live ones") and an
  outcome column. Verified end to end with 2025-06-12/13 replayed into the local API.
- Tests: ML 97, API 26 unit + 13 e2e, web 13 unit + 12 e2e.
- Note: each replay run creates new prediction ids, so replaying the same day twice into the API
  duplicates predictions; delete old REPLAY rows first (local data only).

## Architecture
- `ml/src/pulsetrader/`: config, data/{schema,validate,io,discovery,pipeline},
  security/{lists,master}, features/{engine,preprocess}, labels/labels, splits/splits, eval/metrics,
  datasets/build, audit/leakage, eval/multiclass, models/classical,
  experiments/classical, datasets/sequences, models/deep, experiments/deep, serve/{app,models,store,parity},
  experiments/{optimize,calibrate,robustness,backtest,register}, eval/calibration, backtest/engine,
  registry/registry,
  live/{events,providers,kite,candles,validate,cache,features,pipeline,parity},
  cli (fetch, discover, pipeline, security, dataset, audit, classical, deep, optimize, calibrate, robustness, backtest, registry, serve-check, export-app, live, live-parity, kite-login).
- Docker baseline: docker-compose (postgres, redis, ml-service). ml/Dockerfile. CI: .github/workflows/ci.yml.
- Backend: api/ (NestJS, Phase 15). Frontend: web/ (Next.js, Phase 16). ML service also serves /bars and /indicators.
- Docker: compose services postgres, redis, ml-service, api, web, live-pipeline (profile `live`); CI jobs ml, api, web, docker (ml, api, web images).

## Versions
- schema `canonical-v1`, processing `pipeline-v2`, security master `secmaster-v1`,
  features `features-v2` (scale-free only), labels `labels-v1`, dataset builder `dataset-v1`,
  audit `leakage-audit-v1`.
- Dataset: `canonical-v1-8cc94bf262aa`.
- Experiments: 25 Phase 7 runs, `classical-v1`, ids 20261017T115408-p7-*. Registered models: see Phase 13 results.

## Decisions
- Canonical keeps REGULAR session bars only; non-regular bars are kept in validated/ and reported.
- validated/ keeps exception rows only (pipeline-v2), to avoid a second full copy of the dataset.
- Multi-symbol shards are processed in batches of 40 whole symbols; symbols split across shards merged.
- Labels never cross session boundaries; missing future bar -> null label.
- Rolling technical features span overnight; intraday features reset daily.
- Prediction time for bar t = bar close (t + 1 min).
- CCI uses rolling std (documented variant).
- Instrument types come from a curated list (no NSE master offline); uncertain tickers reported.

## Phase status
| Phase | Status |
|---|---|
| 0 Repository | DONE |
| 1 Discovery | DONE on real data (reports/dataset_manifest.json, data_inventory.md) |
| 2 Pipeline | DONE on real data (reports/data_quality_report.md), 9 min, 6.9 GB peak RAM |
| 3 Security master | DONE (reports/security_master.md, corporate_action_audit.md), 40 tests pass |
| 4 Features | DONE on real data (features-v2, 84 features, core100_s5) |
| 5 Labels | DONE on real data (labels recomputed from canonical in the audit) |
| 6 Leakage audit | PASSED on real data (reports/leakage_audit_real.md) |
| 7 Classical ML | DONE (reports/phase7_classical.md); no model verified, see Phase 7 results |
| 8 Deep learning | DONE 2026-10-18: transformer L120 ties GBM (best MCC 0.167 on y_1m_5bp); reports/phase8_deep.md |
| 9 Optimisation | DONE 2026-10-18: walk-forward, Optuna, feature selection, ensembles; best val MCC 0.194 (tuned LightGBM y_1m_5bp); reports/phase9_optimization.md |
| 10 Calibration | DONE 2026-10-19: Platt + isotonic; tuned models need calibration (classwise ECE 0.14 -> 0.02); reports/phase10_calibration.md |
| 11 Robustness | DONE 2026-10-19: edge broad across stocks/regimes/sectors, weak at the open, shrinking over time, break-even < 2 bp; reports/phase11_robustness.md |
| 12 Backtesting | DONE 2026-10-19: model beats baselines before costs, all intraday strategies lose after ~10 bp costs |
| 13 Model registry | DONE 2026-10-19: both tuned models CANDIDATE (backtest gate FAILED, test NOT_RUN) |
| 14 ML inference API | DONE 2026-10-19: FastAPI, parity 3e-8 |
| 15 Backend | DONE 2026-10-19: NestJS + Prisma, seeded with real data |
| 16 Frontend | DONE 2026-10-19: Next.js dashboard, 11 e2e flows on the real stack |
| 17 Live market system | DONE 2026-10-19: Kite adapter + replay; live features/predictions match research exactly |
| 18 Live paper evaluation | DONE 2026-10-19: REPLAY of 20 validation sessions; outcomes match labels exactly; gated calls 40-43% accurate, lose after costs |
| 19–20 | NOT STARTED |

## Known issues
- No Kite Connect credentials yet and api.kite.trade / ws.kite.trade are blocked by this environment's
  network policy, so the Kite adapter is tested on synthetic packets only; real LIVE is unverified.
- No sector mapping offline (nseindia.com blocked); sector context can only use sector indices.
- Instrument classification of 8 tickers is uncertain (listed in reports/security_master.md).

## Commands
See AGENTS.md. From ml/: `PULSETRADER_DATA_DIR=../data .venv/bin/pulsetrader {fetch,discover,pipeline,security,dataset,audit,classical,deep,optimize,calibrate,robustness,live,live-parity,live-eval}`.
Tests: `.venv/bin/pytest` (97 passed on 2026-10-19). api/: `npm test`, `npm run test:e2e`. web/: `npm test`, `npm run test:e2e` (docs/frontend.md).
