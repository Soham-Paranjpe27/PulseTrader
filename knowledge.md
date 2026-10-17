# knowledge.md — PulseTrader V4 project state

Last updated: 2026-10-17 (phase 7).

## Current phase
Phases 0–7 DONE on real data. Next: Phase 8 (deep learning) on `data/datasets/core100_s5`.

## Next exact action
1. Phase 8 deep learning (LSTM, GRU, attention, temporal transformer) on train -> validation only.
   torch is not installed (`pip install -e ".[dl]"`, CPU only, no GPU): build per-symbol sequences of
   the 84 features (lengths 30/60/120) from `core100_s5`, keep the same labels and inner early-stop
   split as Phase 7 (`experiments/classical.py: inner_split`), report with `eval/multiclass.py`.
   Budget: 4 CPUs, ~15 GB RAM; subsample training rows as in Phase 7.
2. Compare against Phase 7 (reports/phase7_classical.md), including the momentum baseline.
3. Test split (2025-06-16..2026-01-21) stays untouched.

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

## Architecture
- `ml/src/pulsetrader/`: config, data/{schema,validate,io,discovery,pipeline},
  security/{lists,master}, features/{engine,preprocess}, labels/labels, splits/splits, eval/metrics,
  datasets/build, audit/leakage, eval/multiclass, models/classical,
  experiments/classical, serve/app (health/ready only),
  cli (fetch, discover, pipeline, security, dataset, audit, classical).
- Docker baseline: docker-compose (postgres, redis, ml-service). ml/Dockerfile. CI: .github/workflows/ci.yml.
- Backend (NestJS) and frontend (Next.js): not started.

## Versions
- schema `canonical-v1`, processing `pipeline-v2`, security master `secmaster-v1`,
  features `features-v2` (scale-free only), labels `labels-v1`, dataset builder `dataset-v1`,
  audit `leakage-audit-v1`.
- Dataset: `canonical-v1-8cc94bf262aa`.
- Experiments: 25 Phase 7 runs, `classical-v1`, ids 20261017T115408-p7-*. No model registered.

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
| 8–20 | NOT STARTED |

## Known issues
- No market-data provider credentials; live phases will use the provider interface, MockProvider in tests only.
- No sector mapping offline (nseindia.com blocked); sector context can only use sector indices.
- Instrument classification of 8 tickers is uncertain (listed in reports/security_master.md).

## Commands
See AGENTS.md. From ml/: `PULSETRADER_DATA_DIR=../data .venv/bin/pulsetrader {fetch,discover,pipeline,security,dataset,audit,classical}`.
Tests: `.venv/bin/pytest` (48 passed on 2026-10-17).
