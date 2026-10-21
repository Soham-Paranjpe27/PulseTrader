# Final audit (spec section 74), 2026-10-19

Short answer: the platform is complete and hardened, the research was done on real data without
leakage, and the result is negative for trading. **No model reaches 70-80% directional accuracy.** The
best models have a small, real, measurable edge (validation MCC 0.17-0.19) that is too small to survive
Indian intraday costs. Both stay CANDIDATE. The final test period was run once (2026-10-20) and
confirmed the validation result: MCC 0.200 / 0.186, still not tradeable.

## 1. Data
| Check | Result | Evidence |
|---|---|---|
| Source | Hugging Face `xxparthparekhxx/indian-stock-market-minute-data`, 720,421,072 rows, 2,535 symbols, minute bars 2022-01-03..2026-01-21 | reports/dataset_manifest.json |
| Raw data untouched | read-only, never written | data/raw permissions, AGENTS.md |
| Quality | 2.99e-05 of rows flagged and excluded (non-positive prices, OHLC-inconsistent, negative volume) | reports/data_quality_report.md |
| Known biases | survivorship (no delisted stocks), vendor back-adjusted prices (scale-free features only), no offline sector master | knowledge.md |

## 2. Leakage
| Check | Result | Evidence |
|---|---|---|
| Leakage audit (perturbation, timestamps, labels recomputed, purge/embargo, point-in-time universe, scaler isolation) | PASSED | reports/leakage_audit_real.md |
| Chronological splits, 60-minute purge + embargo | yes | docs/leakage-prevention.md |
| Preprocessing fit on train only | enforced by `Preprocessor.fit` | ml/src/pulsetrader/features/preprocess.py |
| One feature engine for training, serving and live | parity 3e-8 (service), 84/84 features exact (live) | reports/phase14_inference.md, reports/phase17_live.md |
| Test period untouched during development | yes; ML service and replay provider refuse it (403 TEST_PERIOD_LOCKED); used once at the end with the user's approval | registry `test_period.used_at` 2026-10-20 |

## 3. Models (validation, full coverage)
| Model | Accuracy | Balanced acc. | MCC | Coverage | Baseline |
|---|---|---|---|---|---|
| lightgbm-y_1m_5bp-tuned | 50.1% | 45.2% | 0.194 | 100% | majority 58.1%, momentum MCC 0.089 |
| lightgbm-y_5m_10bp-tuned | 48.0% | 43.1% | 0.168 | 100% | majority 55.1%, momentum MCC 0.087 |
| Deep (transformer L=120, y_1m_5bp) | 59.2% | – | 0.167 | 100% | ties gradient boosting |
- High raw accuracies seen in Phase 7 (82-99.7%) are majority-NEUTRAL behaviour (balanced accuracy
  35-36%) and are not counted as success.
- Selective calls: 0.03-0.27% coverage, 40-43% accurate in the Phase 18 REPLAY. No confidence level gives
  a usable high-accuracy subset.
- Walk-forward: MCC 0.223 ± 0.018 (1m), 0.200 ± 0.010 (5m) over 4 pre-validation folds; edge shrinks over
  time (0.241 in 2023 -> 0.194 on validation).
- Final test (2025-06-16..2026-01-21, frozen models, run once): 1m MCC 0.200, accuracy 62.4% (majority
  69.0%), balanced 44.0%; 5m MCC 0.186, accuracy 61.2% (majority 66.2%), balanced 42.5%. Service calls
  0.03% / 0.16% coverage, negative after costs. Gated backtest -3.1% / -13.8% vs buy-and-hold +3.9%
  (reports/final_test.md).
- Accuracy target 70-80%: **NOT VERIFIED** (registry `accuracy_gate`).

## 4. Trading viability
Backtest on validation (reports/phase12_backtest.md): zero costs +47.9% (1m) / +21.3% (5m); after ~10.2 bp
round-trip costs every strategy loses (gated -9.5% / -34.4%, ungated ~-100%). Gross edge 0.4-2.5 bp per
trade versus ~10 bp costs. Registry gate `backtest_passed`: FAILED. **Not tradeable.**

## 5. Registry gates
| Gate | 1m_5bp | 5m_10bp |
|---|---|---|
| no_leakage, no_critical_data_quality, validation, walk_forward, calibration, reproducible | PASSED | PASSED |
| backtest_passed | FAILED | FAILED |
| test_passed | PASSED | PASSED |
| shadow_passed | NOT_RUN | NOT_RUN |
Status: CANDIDATE. No PRODUCTION model; the API answers unnamed prediction requests with NO_PRODUCTION_MODEL.

## 6. Live system
- Kite Connect adapter built and tested on recorded packets only. Real LIVE is **unverified**: no Kite
  credentials yet, and api.kite.trade / ws.kite.trade are blocked in this environment.
- REPLAY of recorded sessions runs end to end (features, predictions, outcomes, drift, alerts) and is
  always labelled REPLAY, never LIVE.
- Monitoring flags January 2025 as MODEL_DRIFT_DETECTED (accuracy drop); feature drift never fired.

## 7. Production hardening (Phase 20)
| Area | Result | Evidence |
|---|---|---|
| Security | 52/52 black-box checks; 6 issues found and fixed; audits 0; gitleaks 0 | reports/phase20_security.md, docs/security.md |
| Load | 0 errors at concurrency 1/8/32 on every endpoint | reports/phase20_load.md |
| Failure | 22/22 (ML, Redis, PostgreSQL stopped and restarted; no 500s, alerts raised and cleared) | reports/phase20_failure.md |
| Database | backup/restore exact; concurrent writes safe; migration drift check | reports/phase20_hardening.md |
| ML reproducibility | byte-identical refit, exact dataset rebuild, artifact digests enforced | reports/phase20_repro.md |
| Docker | compose config valid; images built and smoke-tested in CI (local builds blocked by network policy) | scripts/hardening/compose_smoke.sh |

## 8. Open items
1. The test period is used. Any new or changed model must be judged on a new untouched period
   (data after 2026-01-21, not in the current download).
2. Real LIVE: Kite Connect key, secret and daily access token, plus network access to Kite.
3. Shadow evaluation on live data before any PRODUCTION promotion (gate `shadow_passed`).
4. A model with an edge large enough to beat costs: longer horizons, lower-cost instruments, or a
   different signal. Not achieved in this project.
