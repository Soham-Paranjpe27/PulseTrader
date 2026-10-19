# Phase 20: security checks (black-box, running stack)

Target: http://localhost:3000 (through the web app's /api proxy, as a browser). 52/52 passed.

| area | check | result | evidence |
|---|---|---|---|
| auth | login sets an access token cookie | PASS | access_token cookie present |
| auth | forged JWT rejected (alg=none) | PASS | GET /api/auth/me -> 401 |
| auth | forged JWT rejected (HS256 with a guessed key) | PASS | GET /api/auth/me -> 401 |
| auth | forged JWT rejected (payload edited, original signature) | PASS | GET /api/auth/me -> 401 |
| auth | forged JWT rejected (expired token re-signed with a guessed key) | PASS | GET /api/auth/me -> 401 |
| auth | no session -> 401 | PASS | 401 |
| auth | unknown user and wrong password look the same | PASS | 401/401, same message |
| auth | no password hash in responses | PASS | GET /api/auth/me has no hash |
| auth | mass assignment of role rejected | PASS | register with role=ADMIN -> 400 |
| cookies | access and refresh cookies are httpOnly | PASS | HttpOnly set |
| cookies | refresh cookie scoped to /api/auth | PASS | path=/api/auth |
| csrf | write without x-csrf-token rejected | PASS | 403 |
| csrf | write with a wrong x-csrf-token rejected | PASS | 403 |
| access | user B cannot read A's portfolio | PASS | GET -> 404 |
| access | user B cannot trade in A's portfolio | PASS | POST -> 404 |
| access | user B cannot delete A's portfolio | PASS | DELETE -> 404 |
| access | user B cannot add to A's watchlist | PASS | POST -> 404 |
| access | user B cannot delete A's watchlist | PASS | DELETE -> 404 |
| access | user B cannot disable A's alert | PASS | PATCH -> 404 |
| access | user B cannot delete A's alert | PASS | DELETE -> 404 |
| access | USER role cannot GET /api/users | PASS | 403 |
| access | USER role cannot GET /api/admin/audit | PASS | 403 |
| access | USER role cannot POST /api/admin/sync/registry | PASS | 403 |
| access | USER role cannot POST /api/monitoring/check | PASS | 403 |
| access | USER role cannot GET /api/admin/audit?limit=1 | PASS | 403 |
| access | anonymous GET /api/watchlists -> 401 | PASS | 401 |
| access | anonymous GET /api/portfolios -> 401 | PASS | 401 |
| access | anonymous GET /api/alerts -> 401 | PASS | 401 |
| access | anonymous GET /api/monitoring/alerts -> 401 | PASS | 401 |
| access | browser session cannot use live ingestion | PASS | 403 |
| access | ingestion with missing token rejected | PASS | 403 |
| access | ingestion with wrong token rejected | PASS | 403 |
| injection | stock search treats "' OR 1=1--" as text | PASS | 200, 0 results, 0.01s |
| injection | stock search treats 'RELIANCE\'; DROP TABLE "User";--' as text | PASS | 200, 0 results, 0.01s |
| injection | stock search treats "%' AND pg_sleep(3)--" as text | PASS | 200, 0 results, 0.01s |
| injection | stock search treats '{"$gt":""}' as text | PASS | 200, 0 results, 0.01s |
| injection | bad symbol "RELIANCE'--" -> 4xx | PASS | 400 |
| injection | bad symbol '..%2f..%2fetc%2fpasswd' -> 4xx | PASS | 400 |
| injection | bad symbol 'AAAAAAAAAAAAAAAAAAAAAAAA' -> 4xx | PASS | 404 |
| injection | proxy path traversal rejected | PASS | 400 |
| injection | object instead of string in login -> 400 | PASS | 400 |
| input | malformed JSON -> 400 | PASS | 400 |
| input | 2 MB body rejected | PASS | 413 |
| input | historical prediction in the locked test period refused | PASS | 403 {"code":"TEST_PERIOD_LOCKED","message":"TEST_PERIOD_LOCKED: the final test perio |
| input | errors carry no stack traces | PASS | 404 |
| headers | web CSP blocks framing and foreign scripts | PASS | default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; i |
| headers | web sends x-frame-options | PASS | DENY |
| headers | web sends x-content-type-options | PASS | nosniff |
| headers | web hides X-Powered-By | PASS | absent |
| headers | API CORS refuses foreign origins | PASS | no ACAO header |
| headers | API sends helmet headers | PASS | nosniff, no x-powered-by |
| rate-limit | login brute force throttled even with rotating X-Forwarded-For (40/min) | PASS | first 429 at attempt 36 |
