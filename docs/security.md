# Security (backend, Phase 15)

| Control | Implementation |
|---|---|
| Password hashing | argon2id (m=19456 KiB, t=2, p=1); unknown-user logins verify a dummy hash to equalise timing |
| Password policy | 12-128 chars with a letter and a digit |
| Sessions | 15-min HS256 JWT (issuer-checked) in httpOnly `access_token` cookie; random 256-bit refresh token in httpOnly `refresh_token` cookie (path /api/auth), stored as SHA-256 in `Session` |
| Refresh rotation | every refresh revokes the old session; replay of a revoked token revokes all of the user's sessions and is audited |
| CSRF | double submit: non-httpOnly `csrf_token` cookie must be echoed in `x-csrf-token` on every POST/PATCH/DELETE (login/register exempt); SameSite=Lax cookies |
| Cookies | `Secure` when COOKIE_SECURE=true (default in production) |
| Authorization | global guard: login required unless `@Public()`; `@Roles(ADMIN)` for admin routes; per-user resources return 404 to non-owners |
| Rate limiting | 120 req/min per IP globally, 10/min on login and register (configurable) |
| Input validation | class-validator DTOs, whitelist + forbidNonWhitelisted (unknown fields such as `role` are rejected) |
| Headers | helmet defaults; CORS limited to WEB_ORIGIN with credentials |
| Audit log | `AuditLog` rows for register, login, failed login, logout, refresh reuse, predictions, watchlist, alerts, portfolio trades, admin actions |
| Secrets | env only, validated at start (JWT_SECRET >= 32 chars, placeholder refused); `.env` gitignored |
| Dependencies | `npm audit --omit=dev` and `pip-audit` in CI; js-yaml and deepmerge-ts pinned via overrides |
| Errors | no blind catches (ESLint/ruff rules); failures are logged and surfaced with a code |

## Web app (Phase 16)
- The browser talks only to the web origin; `/api/*` is proxied to the API with an allow-list of headers,
  so session cookies stay httpOnly and first-party. Path segments that could escape `/api` are rejected.
- Writes send the `csrf_token` cookie value in `x-csrf-token` (double submit); refresh is a CSRF-checked POST.
- Post-login redirects accept only same-site relative paths (no open redirect).
- Security headers on every page: CSP (`connect-src 'self'`, `frame-ancestors 'none'`, `form-action 'self'`),
  `X-Frame-Options: DENY`, `nosniff`, strict referrer policy, permissions policy. Since Phase 20 scripts
  run under a per-request nonce CSP (see below).
- Only UI preferences (theme, chart mode, chosen model) are stored in localStorage.
- `npm audit --omit=dev`: 0 (postcss pinned to 8.5.31 via overrides). Dev-only `braces` advisory remains.
- The API trusts one proxy hop when `TRUST_PROXY=1`; expose the API directly only without that setting.

## Production hardening (Phase 20)
Evidence: reports/phase20_security.md (52/52 black-box checks on the running stack), reports/phase20_hardening.md.

| Finding / control | Change |
|---|---|
| Client could spoof `X-Forwarded-For` through the web proxy and so dodge the login rate limit and fake audit-log IPs | `web/xff-guard.cjs` (preloaded with `node -r`) rewrites the header to the real peer address, trusting only `WEB_TRUSTED_PROXY_HOPS` proxies in front of the web app |
| API port 3001 was published by compose, bypassing the one trusted hop | compose uses `expose` only; the API is reachable through the web app and the internal network |
| Inline scripts allowed by CSP | per-request nonce CSP from `web/src/middleware.ts` (`script-src 'self' 'nonce-…' 'strict-dynamic'`, `object-src 'none'`, `frame-ancestors 'none'`, `base-uri`/`form-action 'self'`); browser e2e checks there are no violations |
| Concurrent paper trades lost cash updates / could oversell | trade runs in one transaction with `SELECT … FOR UPDATE` on the portfolio row |
| Duplicate-create races returned 500 | Prisma errors mapped globally: unique violation 409, missing record 404, database unreachable 503 `DATABASE_UNAVAILABLE` |
| A changed model file would be served silently | `sha256.json` per artifact; the ML service refuses an artifact whose files no longer match |
| Secrets in history | gitleaks over the full history in CI (0 leaks); detect-secrets hits are placeholders and test fixtures only |
| Dependencies | `npm audit --omit=dev` 0 (api, web), `pip-audit` 0 (setuptools >= 83) |
| CI workflow mistakes | actionlint in CI |
