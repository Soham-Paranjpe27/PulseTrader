# Phase 20: failure tests (local stack)

API http://localhost:3003; one dependency stopped at a time, then restarted. 22/22 passed.

| scenario | check | result | evidence |
|---|---|---|---|
| ML service down | liveness stays up | PASS | GET /api/health -> 200 |
| ML service down | prediction request fails with 503 and a code, not 500 | PASS | 503 {'code': 'ML_SERVICE_UNAVAILABLE', 'message': 'fetch failed'} |
| ML service down | stock detail still served from the database | PASS | 200 |
| ML service down | readiness reports the ML service | PASS | 200 {'ready': True, 'database': True, 'redis': True, 'mlService': {'reachable': False, 'error': 'fetch failed'}, 'marketData': {'state': 'DISCONNECTED', 'provider': None, 'mode': None, 'reason': 'no live market data provider configured', 'lastBarClose': None, 'latencyP50Seconds': None, 'accepted': None, 'rejected': None, 'observedAt': None}} |
| ML service down | ML_SERVICE_DOWN alert raised | PASS | after 0.0 s |
| ML service down | predictions work again after restart (no API restart) | PASS | after 2.4 s |
| ML service down | ML_SERVICE_DOWN alert cleared | PASS | after 0.0 s |
| Redis down | liveness stays up | PASS | GET /api/health -> 200 |
| Redis down | stock search unaffected | PASS | 200 |
| Redis down | predictions still stored (stream falls back to this instance) | PASS | 201 |
| Redis down | feed status answers without Redis | PASS | 200 {'state': 'DISCONNECTED', 'provider': None, 'mode': None, 'reason': 'no live market data provider configured', 'lastBarClose': None, 'latencyP50Seconds': None, 'accepted': None, 'rejected': None, 'observedAt': None} |
| Redis down | REDIS_DOWN alert raised | PASS | after 0.0 s |
| Redis down | API reconnects to Redis by itself | PASS | after 1.0 s |
| Redis down | REDIS_DOWN alert cleared | PASS | after 0.0 s |
| PostgreSQL down | liveness stays up | PASS | GET /api/health -> 200 |
| PostgreSQL down | readiness fails (503, database false) | PASS | 503 {'ready': False, 'database': False, 'redis': True, 'mlService': {'reachable': True, 'ready': True, 'reason': 'NO_PRODUCTION_MODEL', 'production_models': [], 'loaded_models': ['lightgbm-y_1m_5bp-tuned@v1', 'lightgbm-y_5m_10bp-tuned@v1'], 'historical_mode': True, 'load_errors': {}}, 'marketData': {'state': 'DISCONNECTED', 'provider': None, 'mode': None, 'reason': 'no live market data provider configured', 'lastBarClose': None, 'latencyP50Seconds': None, 'accepted': None, 'rejected': None, 'observedAt': None}} |
| PostgreSQL down | GET /api/stocks?q=REL -> 503 with a code, not 500 | PASS | 503 {'code': 'DATABASE_UNAVAILABLE', 'message': 'The database is not reachable. Try again shortly.'} |
| PostgreSQL down | GET /api/auth/me -> 503 with a code, not 500 | PASS | 503 {'code': 'DATABASE_UNAVAILABLE', 'message': 'The database is not reachable. Try again shortly.'} |
| PostgreSQL down | GET /api/monitoring -> 503 with a code, not 500 | PASS | 503 {'code': 'DATABASE_UNAVAILABLE', 'message': 'The database is not reachable. Try again shortly.'} |
| PostgreSQL down | API process survives the outage | PASS | 200 |
| PostgreSQL down | API recovers without a restart | PASS | after 0.0 s |
| PostgreSQL down | existing sessions still valid | PASS | 200 |
