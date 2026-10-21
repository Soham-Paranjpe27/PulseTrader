# Monitoring (Phase 19)

Health, latency, model drift and system alerts. Drift never replaces a model automatically: a
`MODEL_DRIFT_DETECTED` alert asks a person to review the model.

## Drift references (`pulsetrader monitor`)
`ml/src/pulsetrader/monitor/` builds one reference per registry model in
`data/monitoring/reference/<model>@v<version>.json` (version `monitor-ref-v2`), from out-of-sample data only:
- features: decile bins of every model feature from the training split (every 8th row), plus a null bin;
- predictions, accuracy (accuracy, balanced accuracy, MCC) and calibration (top-class ECE): the model's
  walk-forward folds before the validation period (raw probabilities);
- market regime mix: NIFTY trend (up/down) x volatility (low/mid/high) over training days;
- feature importance from the walk-forward run (weights the feature PSI).

The command then runs the monitor over the validation period month by month and week by week and writes
`reports/phase19_monitoring.{md,json}`. The test period is never read.

## Checks and thresholds
| component | statistic |
|---|---|
| feature | importance-weighted PSI over features (top 10 most shifted listed) |
| prediction | max PSI of each class probability and of the argmax share |
| accuracy | window MCC and accuracy (needs >= 1,000 outcomes) |
| calibration | top-class ECE |
| regime | PSI of the window's regime mix |

PSI = sum((a - e) ln(a / e)). Persistent market series sit in a narrow band inside any short window, so
fixed PSI cut-offs flag every window. Thresholds are therefore calibrated per window length (day, week,
month) on historical windows of the same length: WARN when the window is more extreme than 95% of them,
DRIFT beyond 99% (with PSI floors 0.1 / 0.25). Too little data gives `INSUFFICIENT_DATA`, never OK.

Overall: `MODEL_DRIFT_DETECTED` if accuracy or calibration is DRIFT, or feature and prediction are both
DRIFT; `WARN` if any component warns; `INSUFFICIENT_DATA` if nothing could be measured; otherwise `OK`.

## Live pipeline
`pulsetrader live` loads the references (`LiveDriftMonitor`) and, after every completed session (day
change or end of stream), reports per model on that session (day thresholds) and on the last 5 sessions
(week thresholds), with inference and feature-build latency. Part-day windows are not judged: the
time-of-day pattern would look like drift every morning. Reports go to every sink: `<out>.monitoring.jsonl`
and `POST /api/live/monitoring`. `--dates d1 d2 ...` replays several sessions with one monitor. Every
report carries its mode (REPLAY or LIVE).

## API and dashboard
- Tables `MonitoringReport` and `SystemAlert` (one open alert per kind and key; repeats raise `count`;
  closed automatically when the check passes again, or by an ADMIN).
- Health checks every `MONITOR_INTERVAL_SECONDS` (default 60, 0 disables): database, Redis, ML service
  (`/ready`, `/metrics`), feed state, latency. Alerts: `ML_SERVICE_DOWN`, `REDIS_DOWN`, `FEED_DOWN` (only
  with a provider configured and during NSE hours, Mon-Fri 09:15-15:30 IST), `LATENCY_HIGH` (API p95 over
  5 min > `API_LATENCY_P95_MS` with >= 20 requests, or ML p95 > `ML_LATENCY_P95_MS`), `MODEL_DRIFT_DETECTED`
  (key = model, mode, window length; an OK report for the same key clears it).
- API latency: a global interceptor records every request per route pattern (SSE excluded).
- Routes: see docs/backend.md (`/monitoring`). Dashboard: `/monitoring`.
