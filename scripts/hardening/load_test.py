"""Phase 20 load test: closed-loop HTTP load against the API and the ML service.

Each scenario runs for --seconds at each concurrency level; every worker thread keeps one keep-alive
connection and sends the next request as soon as the previous one returns. Reports throughput, latency
quantiles and errors (any non-2xx or transport error). Standard library only.

The API rate-limits per client address (120/min by default), so measuring capacity from one machine
needs an API instance started with a high RATE_LIMIT_PER_MINUTE; the throttle itself is checked by
security_check.py.

    python3 scripts/hardening/load_test.py --api http://localhost:3002 --ml http://localhost:8000 \
        --out reports/phase20_load
"""

from __future__ import annotations

import argparse
import http.client
import json
import secrets
import threading
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

PASSWORD = "correct horse 123"


@dataclass
class Call:
    method: str
    path: str
    body: bytes | None = None
    headers: dict[str, str] | None = None


def conn(base: str) -> http.client.HTTPConnection:
    u = urllib.parse.urlparse(base)
    return http.client.HTTPConnection(u.hostname, u.port or 80, timeout=60)


def once(base: str, c: Call) -> tuple[int, dict[str, str], bytes]:
    h = conn(base)
    h.request(c.method, c.path, body=c.body, headers=c.headers or {})
    r = h.getresponse()
    out = r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    h.close()
    return out


def session(api: str) -> dict[str, str]:
    """Register + log in one user; headers carrying its cookies and CSRF token."""
    email = f"load-{secrets.token_hex(4)}@example.test"
    js = {"content-type": "application/json"}
    body = json.dumps({"email": email, "password": PASSWORD}).encode()
    once(api, Call("POST", "/api/auth/register", body, js))
    h = conn(api)
    h.request("POST", "/api/auth/login", body=body, headers=js)
    r = h.getresponse()
    r.read()
    if r.status != 200:
        raise SystemExit(f"login failed: {r.status}")
    cookies = [v.split(";")[0] for k, v in r.getheaders() if k.lower() == "set-cookie"]
    csrf = next(c.split("=", 1)[1] for c in cookies if c.startswith("csrf_token="))
    return {"cookie": "; ".join(cookies), "x-csrf-token": csrf, "content-type": "application/json"}


def q(v: list[float], p: float) -> float | None:
    if not v:
        return None
    s = sorted(v)
    return s[min(len(s) - 1, int(p * len(s)))]


def run_level(base: str, make: Callable[[int], Call], conc: int, seconds: float) -> dict[str, Any]:
    lat: list[float] = []
    errors: dict[str, int] = {}
    lock = threading.Lock()
    stop = time.monotonic() + seconds

    def worker(wid: int) -> None:
        h = conn(base)
        i = 0
        while time.monotonic() < stop:
            c = make(wid * 1_000_000 + i)
            i += 1
            t0 = time.perf_counter()
            try:
                h.request(c.method, c.path, body=c.body, headers=c.headers or {})
                r = h.getresponse()
                r.read()
                ok, key = 200 <= r.status < 300, str(r.status)
            except (OSError, http.client.HTTPException) as e:
                ok, key = False, type(e).__name__
                h.close()
                h = conn(base)
            dt = (time.perf_counter() - t0) * 1000
            with lock:
                lat.append(dt)
                if not ok:
                    errors[key] = errors.get(key, 0) + 1
        h.close()

    t0 = time.monotonic()
    ts = [threading.Thread(target=worker, args=(w,)) for w in range(conc)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    wall = time.monotonic() - t0
    n = len(lat)
    return {
        "concurrency": conc,
        "requests": n,
        "rps": round(n / wall, 1),
        "p50_ms": q(lat, 0.50),
        "p95_ms": q(lat, 0.95),
        "p99_ms": q(lat, 0.99),
        "max_ms": max(lat) if lat else None,
        "errors": errors,
        "error_rate": round(sum(errors.values()) / n, 4) if n else None,
    }


def scenarios(api: str, ml: str | None, auth: dict[str, str]) -> list[tuple[str, str, Callable[[int], Call]]]:
    syms = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "ITC", "LT"]
    stamps = [f"2025-0{m}-{d:02d}T{h}:{mi:02d}:00+05:30" for m in (2, 3) for d in (3, 4, 5, 6) for h in (10, 13)
              for mi in (5, 35)]  # fmt: skip
    pred = "lightgbm-y_5m_10bp-tuned"
    out: list[tuple[str, str, Callable[[int], Call]]] = [
        ("API GET /stocks?q (search)", api, lambda i: Call("GET", f"/api/stocks?q={syms[i % 8][:3]}")),
        ("API GET /stocks/:symbol (quote, latest prediction)", api,
         lambda i: Call("GET", f"/api/stocks/{syms[i % 8]}")),
        ("API GET /market-data/:symbol/daily (1y bars)", api,
         lambda i: Call("GET", f"/api/market-data/{syms[i % 8]}/daily?from=2024-06-01&to=2025-06-01")),
        ("API GET /predictions/accuracy?mode=REPLAY (20k outcomes)", api,
         lambda i: Call("GET", "/api/predictions/accuracy?mode=REPLAY", headers={"cookie": auth["cookie"]})),
        ("API GET /monitoring (health summary)", api, lambda i: Call("GET", "/api/monitoring")),
        ("API POST /predictions (historical, via ML, stored)", api,
         lambda i: Call("POST", "/api/predictions",
                        json.dumps({"symbol": syms[i % 8], "timestamp": stamps[i % len(stamps)],
                                    "modelId": pred}).encode(), auth)),
    ]  # fmt: skip
    if ml:
        js = {"content-type": "application/json"}
        out.append(("ML POST /predict (historical features)", ml,
                    lambda i: Call("POST", "/predict", json.dumps({"symbol": syms[i % 8],
                                   "timestamp": stamps[i % len(stamps)], "model_id": pred}).encode(), js)))  # fmt: skip
    return out


def render(res: dict[str, Any]) -> str:
    lines = [
        "# Phase 20: load test (local stack, one machine)",
        "",
        f"{res['note']}",
        "",
        "| scenario | concurrency | requests | req/s | p50 ms | p95 ms | p99 ms | max ms | errors |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    def f(x: float | None) -> str:
        return "–" if x is None else f"{x:.1f}"

    for s in res["scenarios"]:
        for lv in s["levels"]:
            err = ", ".join(f"{k}: {v}" for k, v in lv["errors"].items()) or "0"
            lines.append(
                f"| {s['name']} | {lv['concurrency']} | {lv['requests']} | {lv['rps']} | {f(lv['p50_ms'])} | "
                f"{f(lv['p95_ms'])} | {f(lv['p99_ms'])} | {f(lv['max_ms'])} | {err} |"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:3002")
    ap.add_argument("--ml")
    ap.add_argument("--levels", default="1,8,32")
    ap.add_argument("--seconds", type=float, default=15)
    ap.add_argument("--only", help="substring filter on scenario names")
    ap.add_argument("--out")
    a = ap.parse_args()
    auth = session(a.api)
    levels = [int(x) for x in a.levels.split(",")]
    res: dict[str, Any] = {
        "note": f"Closed loop, {a.seconds:.0f} s per level; API at {a.api} with the per-IP rate limit raised "
        "for this measurement; load generator on the same 4-CPU machine as API, ML service, PostgreSQL and "
        "Redis. Errors = non-2xx or transport errors.",
        "scenarios": [],
    }
    for name, base, make in scenarios(a.api, a.ml, auth):
        if a.only and a.only not in name:
            continue
        lv = []
        for c in levels:
            r = run_level(base, make, c, a.seconds)
            print(name, json.dumps(r))
            lv.append(r)
        res["scenarios"].append({"name": name, "levels": lv})
    if a.out:
        with open(a.out + ".json", "w") as fh:
            json.dump(res, fh, indent=1)
        with open(a.out + ".md", "w") as fh:
            fh.write(render(res))


if __name__ == "__main__":
    main()
