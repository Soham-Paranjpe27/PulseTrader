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
