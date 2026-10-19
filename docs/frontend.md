# Web dashboard (Phase 16)

Next.js 15 (App Router) + React 19 + TypeScript 5.9 + Tailwind CSS 4 + shadcn/ui-style components
(Radix Slot/Label + class-variance-authority, in `web/src/components/ui`) + TanStack Query 5 + Zustand 5
+ React Hook Form 7 + Zod 3 + lightweight-charts 5. Code: `web/`.

## How it talks to the backend
The browser calls only its own origin. `src/app/api/[...path]/route.ts` forwards `/api/*` to the NestJS
API at `API_URL` (read at runtime, so one image works in every environment):
- allow-listed request headers only (cookie, content-type, x-csrf-token, accept, user-agent,
  last-event-id, x-forwarded-for); path segments that could leave `/api` are rejected;
- every `Set-Cookie` is passed back, so the httpOnly `access_token` / `refresh_token` cookies and the
  readable `csrf_token` cookie are first-party;
- SSE (`/api/predictions/stream`) streams through unbuffered.

`src/lib/api.ts` echoes `csrf_token` in `x-csrf-token` on writes (double submit). On a 401 it rotates the
refresh token once (only when a session cookie exists) and retries. Errors keep the API's code
(`TEST_PERIOD_LOCKED`, `DATA_UNAVAILABLE`, `NO_PRODUCTION_MODEL`, `RATE_LIMITED`, ...) and the UI shows it.
The API runs with `TRUST_PROXY=1` behind the proxy so rate limits and audit logs see the client address.

## Pages
| Path | Login | Shows |
|---|---|---|
| `/` | no | what the platform is, dataset facts, registry models with measured validation metrics |
| `/login`, `/register` | no | RHF + Zod forms mirroring the API rules; post-login redirect only to same-site paths |
| `/dashboard` | yes | DB / Redis / ML service / feed health, no-production-model notice (from the gates), models + gates, stored-prediction accuracy, watchlists, latest predictions |
| `/stocks` | no | search, type and universe filters, pagination over all 2,535 instruments |
| `/stocks/[symbol]` | no (actions need login) | section 57 fields, see below |
| `/predictions` | no (stream needs login) | filtered list incl. abstentions, accuracy with coverage, SSE stream of new predictions |
| `/watchlist` | yes | create/delete lists, add/remove symbols |
| `/portfolio` | yes | paper portfolios, trades at the latest stored close, valuation |
| `/alerts` | yes | price / prediction alerts, enable/disable/delete |
| `/research` | yes | research assistant; shows OK / DATA_UNAVAILABLE / UNSUPPORTED and sources |
| `/settings` | yes | display name, theme (browser-only, Zustand persist), logout |

### Stock detail (spec section 57)
| Field | Source |
|---|---|
| Current price, today's change, volume | latest stored daily bar vs previous (labelled "not live") |
| Latest market timestamp | last loaded minute bar (IST), else the daily bar date |
| Candlestick chart | daily: 12 months from Postgres; intraday: 1-minute canonical bars via ML `/bars` (time axis in IST) |
| Technical indicators | ML `GET /indicators/{symbol}?date`: the shared feature engine run on that session + 5 prior sessions |
| Market regime | Phase 11 definition: previous-day NIFTY vs 50-day average, 20-day vol tercile (training cut-offs) |
| Prediction, probability, horizon, model version, feature version, data quality | latest stored prediction; raw and calibrated probabilities; research-only badge |
| Live status | API feed state; `DISCONNECTED` until Phase 17 (never shown LIVE because the page is connected) |
| Recent prediction accuracy | rolling 20/50/100/500 evaluated calls; `DATA_UNAVAILABLE` until outcomes exist |

"Run a historical prediction" sends `{symbol, timestamp (IST bar start), modelId, modelVersion}`. It defaults
to the model's last validation day; the test period answers `TEST_PERIOD_LOCKED`.

Indicator parity: for RELIANCE on 2025-01-06 (75 dataset rows), the 63 float features from the dashboard
path match the research dataset to a max abs diff of 6.5e-6 (float32 storage). `test_indicators_use_shared_engine`
checks the same on the golden fixture.

## Run locally
```
service postgresql start; redis-server --daemonize yes
cd ml && PULSETRADER_DATA_DIR=../data .venv/bin/uvicorn pulsetrader.serve.app:app --port 8000 &
cd api && npm run build && TRUST_PROXY=1 node dist/main.js &            # :3001
cd web && npm ci && npm run build
cp -r .next/static .next/standalone/.next/ && API_URL=http://localhost:3001 node .next/standalone/server.js   # :3000
```
Dev server: `API_URL=http://localhost:3001 npm run dev`.

## Checks
```
npm run format:check && npm run lint && npm run typecheck && npm test && npm run build
npm run test:e2e        # needs the stack above; CHROMIUM_PATH=/opt/pw-browsers/... if browsers live elsewhere
```
- `npm test`: Playwright test runner, `unit` project (pure TS, no browser): proxy, API client, schemas,
  chart data, formatting.
- `npm run test:e2e`: 11 browser flows on the real stack and data: registration, login, protected pages,
  stock search, stock detail (chart actually drawn, indicators, regime, live status), prediction on
  validation data + test-period lock, watchlist, alerts, paper portfolio, research assistant, settings, logout.
  CI runs format/lint/typecheck/unit/build/audit; e2e needs the dataset and model artifacts, so it runs locally.

## Notes
- CSP allows `'unsafe-inline'` scripts because Next.js injects inline bootstrap scripts; a nonce-based CSP
  needs per-request rendering and is left for Phase 20 hardening. `connect-src 'self'`, `frame-ancestors 'none'`.
- lightweight-charts uses the browser locale; the chart sets `en-IN` explicitly. Headless test browsers must
  have a valid locale (the Playwright config sets `en-IN`, `Asia/Kolkata`).
- The TradingView attribution logo stays on (lightweight-charts licence).
