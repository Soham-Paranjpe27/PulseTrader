# Live market data (Phases 17 and 18)

The live system turns real-time market data into predictions with the same feature engine and the same
model artifacts as research. It runs as its own process (`pulsetrader live`) and pushes predictions and
feed status to the API, which stores them and streams them to the dashboard.

```
Zerodha Kite (WebSocket ticks)  or  recorded session (replay)
        -> provider adapter         ml/src/pulsetrader/live/kite.py, providers.py
        -> candle aggregator        live/candles.py   ticks -> closed 1-minute OHLCV bars
        -> validation + feed state  live/validate.py  LIVE / DELAYED / STALE / DISCONNECTED / INVALID / REPLAY
        -> real-time cache          live/cache.py     5 warm-up sessions + today's validated bars
        -> shared feature engine    live/features.py  features.engine.compute_symbol_features + add_cross_sectional
        -> model inference          serve/models.py   LoadedModel.predict (training-fit preprocessor, calibrator)
        -> prediction store         POST /api/live/ingest -> PostgreSQL (Prediction.mode = LIVE | REPLAY)
        -> SSE                      GET /api/predictions/stream
        -> dashboard                feed badge, stock page price, predictions table
```

## Providers (`MarketDataProvider`)

| provider | `is_live` | use |
|---|---|---|
| `KiteProvider` (`MARKET_DATA_PROVIDER=kite`) | yes | Zerodha Kite Connect: ticks over `wss://ws.kite.trade` (full mode, exchange timestamps), warm-up minute candles from the historical API |
| `HistoricalProvider` (`MARKET_DATA_PROVIDER=replay`) | no | replays a recorded canonical session bar by bar (`--speed` x real time). Refuses test-period dates unless `PULSETRADER_ALLOW_TEST_PERIOD=1` |
| `SnapshotProvider` | no | latest stored bar per symbol |
| `MockProvider` | yes | scripted ticks, **tests only**: refuses to start outside pytest (`PULSETRADER_TESTING=1` for other test runners) |

The core ML code never imports Kite; the provider is chosen by `provider_from_env`.

## Feed states

`FeedMonitor` derives the state from the provider kind and recent bars, never from browser connections:

- `REPLAY`: recorded data. A replay can never be shown as LIVE (the API also forces this).
- `DISCONNECTED`: no provider connection, or no status report in the last 120 s (Redis key TTL).
- `INVALID`: more than 20% of the last 200 bars failed validation. No predictions are made.
- `STALE`: connected but no accepted bar for 5 minutes (or market closed).
- `DELAYED`: median bar latency (receipt minus bar close) above 90 s.
- `LIVE`: real-time provider, fresh validated bars.

Bar validation rejects (and counts by reason): `UNKNOWN_SYMBOL`, `NAIVE_TIMESTAMP`, `OUTSIDE_SESSION`,
`FUTURE_TIMESTAMP`, `BAD_PRICE`, `BAD_OHLC`, `BAD_VOLUME`, `DUPLICATE`, `OUT_OF_SEQUENCE`.

## Timing and feature parity

- A minute is finalised when a bar of a later minute arrives or 4 s after it closed (live clock).
- Predictions are made at bars with minute-of-session % 5 == 0, the cadence the models were trained on.
- Features at bar `t` use only bars with start <= `t` (`BarCache.frame(upto=t)`); the prediction time is
  the bar close (`t + 1 min`), and staleness is measured from when the minute's bars became available.
- Cross-sectional features (market context, VIX level, relative strength) use `add_cross_sectional`,
  the function the dataset builder now calls, so names, order and formulas cannot drift.
- `check_features` refuses a model whose feature version differs from the engine's or whose features
  the engine does not produce. Missing values stay missing (the model's training-fit imputer applies).

`pulsetrader live-parity --dates 2024-12-02 2025-03-17 2025-06-13` replays validation sessions and
compares every live feature row and prediction with the research dataset and the stored walk-forward
predictions. Results are in `reports/phase17_live.md`.

## Running

```bash
# replay a validation session into the running API (shown as REPLAY on the dashboard)
export LIVE_INGEST_TOKEN=...                        # same value in the API's environment
LIVE_API_URL=http://localhost:3001/api PULSETRADER_DATA_DIR=../data \
  .venv/bin/pulsetrader live --date 2025-06-13 --speed 20

# real time with Zerodha Kite Connect
pip install -e ".[live]"                            # websockets
export MARKET_DATA_PROVIDER=kite MARKET_DATA_API_KEY=... MARKET_DATA_API_SECRET=...
.venv/bin/pulsetrader kite-login                    # prints the Zerodha login URL
.venv/bin/pulsetrader kite-login --request-token <token from the redirect URL>   # prints today's access token
export MARKET_DATA_ACCESS_TOKEN=...
LIVE_API_URL=http://localhost:3001/api .venv/bin/pulsetrader live
```

Docker: `docker compose --profile live up live-pipeline` (set the variables above in `.env`).

Requirements for real time: a Kite Connect subscription (API key and secret), a fresh access token each
trading day (Kite tokens expire every morning), and outbound network access to `api.kite.trade` and
`ws.kite.trade`. Credentials are read only from the environment and are never written to disk or logs.

## API endpoints

- `POST /api/live/ingest` (header `x-ingest-token`, compared in constant time with `LIVE_INGEST_TOKEN`;
  not rate-limited, no cookie/CSRF): up to 500 predictions, stored idempotently by `prediction_id` with
  `mode` LIVE or REPLAY and published to the SSE stream. Predictions requested by users are stored as
  `HISTORICAL` or `CLIENT_FEATURES`, never LIVE.
- `POST /api/live/status` (same token): feed status plus the latest 1-minute close per symbol, kept in
  Redis for 120 s.
- `GET /api/live/status`, `GET /api/market-data/status`: the feed state shown everywhere.
- `GET /api/market-data/:symbol/live`: latest pipeline price with its state (404 when none).

- `POST /api/live/outcomes` (same token): up to 500 realised outcomes, upserted into `PredictionOutcome`
  for stored predictions (unknown ids are counted and skipped).
- `GET /api/predictions/accuracy?mode=LIVE|REPLAY|HISTORICAL|CLIENT_FEATURES&model=&symbol=`: live
  performance (below). `GET /api/predictions?mode=...` filters the list the same way.

## Live paper evaluation (Phase 18)

After each prediction's horizon the pipeline scores it (`live/outcomes.py`) with the research label
definition itself: `labels.add_labels` on the bars the live system received, so `actual_return` is
`close[t+h] / close[t] - 1` with `t+h` the bar exactly h minutes later in the same session, and
`actual_class` uses the model's own label threshold. A prediction is resolved once its target minute
is finalised; when the target lies after the session close there is no label (null, as in research).
`direction_correct` is set for UP/DOWN calls only and is true only when the realised class equals the
call (a NEUTRAL outcome counts as wrong). Outcomes go to every sink: the API, and
`<out>.outcomes.jsonl` next to the predictions file.

Performance (`live/evaluate.py` in Python, `api/src/predictions/performance.ts` for the dashboard,
same definitions), always per mode so replayed results are never mixed with live ones:

- full coverage: the model's argmax class vs the realised class on every evaluated prediction:
  accuracy, balanced accuracy, 3-class MCC, Brier and top-class ECE (raw and calibrated);
- served calls: coverage (calls / evaluated predictions), accuracy, balanced accuracy, MCC, rolling
  accuracy over the last 20 / 50 / 100 / 500 calls, daily / weekly / monthly accuracy (IST dates);
- paper trading per call (Python report only): gross return of following the call over its horizon
  and the same after the Phase 12 round-trip costs. Calls are scored independently, so this is an
  upper bound, not a backtest.

`pulsetrader live-eval --last 20` replays the last 20 validation sessions through the live pipeline and
writes `reports/phase18_live_eval.{md,json}`, including two checks: every outcome equals the dataset
label for the same row, and live probabilities equal the stored walk-forward predictions. With no live
provider connected these are REPLAY figures. The dashboard's Predictions page shows the same metrics with
a mode filter.
