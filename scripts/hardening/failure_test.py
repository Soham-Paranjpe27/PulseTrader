"""Phase 20 failure tests: stop one dependency at a time and check the API degrades cleanly and recovers.

For each of ML service, Redis and PostgreSQL: stop it (shell command you pass), check what still works,
which error codes clients get (never a bare 500), that the monitoring loop raises the right alert, then
start it again and check the API recovers without a restart and the alert clears. Run against an API
instance with a short MONITOR_INTERVAL_SECONDS (e.g. 3). Standard library only.

    python3 scripts/hardening/failure_test.py --api http://localhost:3003 \
        --stop-ml 'kill <pid>' --start-ml '...' --stop-redis 'redis-cli shutdown nosave' \
        --start-redis 'redis-server --daemonize yes' --stop-db 'service postgresql stop' \
        --start-db 'service postgresql start' --out reports/phase20_failure
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

PASSWORD = "correct horse 123"


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar),
                                              urllib.request.ProxyHandler({}))  # fmt: skip

    def req(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        h = {"accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["content-type"] = "application/json"
        tok = next((c.value for c in self.jar if c.name == "csrf_token"), None)
        if tok and method != "GET":
            h["x-csrf-token"] = tok
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with self.op.open(r, timeout=30) as f:
                raw = f.read().decode()
                return f.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            try:
                return e.code, json.loads(raw)
            except json.JSONDecodeError:
                return e.code, raw[:200]
        except (urllib.error.URLError, OSError) as e:
            return 0, str(e)


def sh(cmd: str) -> None:
    # detached output: a started daemon must not hold this process's stdout open
    subprocess.run(
        cmd, shell=True, check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def wait_for(pred: Callable[[], bool], timeout: float = 45, every: float = 1) -> float | None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            if pred():
                return round(time.monotonic() - t0, 1)
        except (KeyError, TypeError, ValueError):
            pass
        time.sleep(every)
    return None


class Run:
    def __init__(self, api: str) -> None:
        self.api = api
        self.checks: list[dict[str, Any]] = []
        self.c = Client(api)
        email = f"fail-{secrets.token_hex(4)}@example.test"
        self.c.req("POST", "/api/auth/register", {"email": email, "password": PASSWORD})
        st, _ = self.c.req("POST", "/api/auth/login", {"email": email, "password": PASSWORD})
        if st != 200:
            raise SystemExit(f"login failed ({st})")

    def check(self, scenario: str, name: str, ok: bool, evidence: Any) -> None:
        ev = evidence if isinstance(evidence, str) else json.dumps(evidence, default=str)[:160]
        self.checks.append({"scenario": scenario, "check": name, "passed": bool(ok), "evidence": ev})
        print(f"{'PASS' if ok else 'FAIL'}  [{scenario}] {name}: {ev}")

    def alerts(self) -> list[str]:
        st, b = self.c.req("GET", "/api/monitoring")
        return [a["kind"] for a in b["alerts"]] if st == 200 else []

    def predict(self) -> tuple[int, Any]:
        return self.c.req("POST", "/api/predictions", {"symbol": "RELIANCE", "timestamp": "2025-02-04T10:05:00+05:30",
                                                       "modelId": "lightgbm-y_5m_10bp-tuned"})  # fmt: skip

    def common_down(self, sc: str) -> None:
        st, _ = self.c.req("GET", "/api/health")
        self.check(sc, "liveness stays up", st == 200, f"GET /api/health -> {st}")

    def ml(self, stop: str, start: str) -> None:
        sc = "ML service down"
        sh(stop)
        self.common_down(sc)
        st, b = self.predict()
        self.check(sc, "prediction request fails with 503 and a code, not 500", st == 503, f"{st} {b}")
        st, b = self.c.req("GET", "/api/stocks/RELIANCE")
        self.check(sc, "stock detail still served from the database", st == 200, f"{st}")
        st, b = self.c.req("GET", "/api/health/ready")
        self.check(
            sc, "readiness reports the ML service", st in (200, 503) and isinstance(b, dict), f"{st} {b}"
        )
        t = wait_for(lambda: "ML_SERVICE_DOWN" in self.alerts())
        self.check(sc, "ML_SERVICE_DOWN alert raised", t is not None, f"after {t} s")
        sh(start)
        t = wait_for(lambda: self.predict()[0] == 201, timeout=90, every=2)
        self.check(sc, "predictions work again after restart (no API restart)", t is not None, f"after {t} s")
        t = wait_for(lambda: "ML_SERVICE_DOWN" not in self.alerts())
        self.check(sc, "ML_SERVICE_DOWN alert cleared", t is not None, f"after {t} s")

    def redis(self, stop: str, start: str) -> None:
        sc = "Redis down"
        sh(stop)
        self.common_down(sc)
        st, _ = self.c.req("GET", "/api/stocks?q=REL")
        self.check(sc, "stock search unaffected", st == 200, f"{st}")
        st, b = self.predict()
        self.check(sc, "predictions still stored (stream falls back to this instance)", st == 201, f"{st}")
        st, b = self.c.req("GET", "/api/market-data/status")
        self.check(sc, "feed status answers without Redis", st == 200, f"{st} {b}")
        t = wait_for(lambda: "REDIS_DOWN" in self.alerts())
        self.check(sc, "REDIS_DOWN alert raised", t is not None, f"after {t} s")
        sh(start)
        t = wait_for(lambda: self.c.req("GET", "/api/health/ready")[1].get("redis") is True)
        self.check(sc, "API reconnects to Redis by itself", t is not None, f"after {t} s")
        t = wait_for(lambda: "REDIS_DOWN" not in self.alerts())
        self.check(sc, "REDIS_DOWN alert cleared", t is not None, f"after {t} s")

    def db(self, stop: str, start: str) -> None:
        sc = "PostgreSQL down"
        sh(stop)
        self.common_down(sc)
        st, b = self.c.req("GET", "/api/health/ready")
        self.check(sc, "readiness fails (503, database false)", st == 503, f"{st} {b}")
        for path in ("/api/stocks?q=REL", "/api/auth/me", "/api/monitoring"):
            st, b = self.c.req("GET", path)
            self.check(sc, f"GET {path} -> 503 with a code, not 500", st == 503, f"{st} {b}")
        time.sleep(8)  # several monitoring cycles run with the database down
        st, _ = self.c.req("GET", "/api/health")
        self.check(sc, "API process survives the outage", st == 200, f"{st}")
        sh(start)
        t = wait_for(lambda: self.c.req("GET", "/api/stocks?q=REL")[0] == 200, timeout=90, every=2)
        self.check(sc, "API recovers without a restart", t is not None, f"after {t} s")
        st, _ = self.c.req("GET", "/api/auth/me")
        self.check(sc, "existing sessions still valid", st == 200, f"{st}")


def render(checks: list[dict[str, Any]], api: str) -> str:
    ok = sum(c["passed"] for c in checks)
    lines = ["# Phase 20: failure tests (local stack)", "",
             f"API {api}; one dependency stopped at a time, then restarted. {ok}/{len(checks)} passed.", "",
             "| scenario | check | result | evidence |", "|---|---|---|---|"]  # fmt: skip
    for c in checks:
        ev = c["evidence"].replace("|", "\\|")
        lines.append(f"| {c['scenario']} | {c['check']} | {'PASS' if c['passed'] else 'FAIL'} | {ev} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:3003")
    for dep in ("ml", "redis", "db"):
        ap.add_argument(f"--stop-{dep}")
        ap.add_argument(f"--start-{dep}")
    ap.add_argument("--out")
    a = ap.parse_args()
    r = Run(a.api)
    if a.stop_ml:
        r.ml(a.stop_ml, a.start_ml)
    if a.stop_redis:
        r.redis(a.stop_redis, a.start_redis)
    if a.stop_db:
        r.db(a.stop_db, a.start_db)
    if a.out:
        with open(a.out + ".json", "w") as f:
            json.dump({"api": a.api, "checks": r.checks}, f, indent=1)
        with open(a.out + ".md", "w") as f:
            f.write(render(r.checks, a.api))
    failed = [c for c in r.checks if not c["passed"]]
    print(f"{len(r.checks) - len(failed)}/{len(r.checks)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
