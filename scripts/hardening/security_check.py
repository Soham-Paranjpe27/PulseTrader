"""Phase 20 black-box security checks against a running PulseTrader stack.

Talks to the web app (WEB_URL, default http://localhost:3000) exactly as a browser does: every API call
goes through the same-origin /api proxy with cookies and the CSRF header. Optional API_URL checks the
API directly (ingestion token). Standard library only. Creates two throw-away users.

    python3 scripts/hardening/security_check.py --out reports/phase20_security

Exit code 1 if any check fails. The login rate-limit check runs last because it locks the client's
address out of login for a minute.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import http.cookiejar
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

PASSWORD = "correct horse 123"


@dataclass
class Resp:
    status: int
    headers: dict[str, str]
    body: str

    def json(self) -> Any:
        return json.loads(self.body) if self.body else None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a: Any, **k: Any) -> None:
        return None


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), NoRedirect, urllib.request.ProxyHandler({})
        )

    def cookie(self, name: str) -> str | None:
        return next((c.value for c in self.jar if c.name == name), None)

    def req(
        self,
        method: str,
        path: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
        csrf: bool = True,
        raw: bytes | None = None,
    ) -> Resp:
        h = {"accept": "application/json", **(headers or {})}
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
        if data is not None:
            h.setdefault("content-type", "application/json")
        tok = self.cookie("csrf_token")
        if csrf and tok and method != "GET":
            h.setdefault("x-csrf-token", tok)
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with self.op.open(r, timeout=30) as f:
                return Resp(f.status, {k.lower(): v for k, v in f.headers.items()}, f.read().decode())
        except urllib.error.HTTPError as e:
            return Resp(e.code, {k.lower(): v for k, v in e.headers.items()}, e.read().decode())


@dataclass
class Report:
    checks: list[dict[str, Any]] = field(default_factory=list)

    def check(self, area: str, name: str, ok: bool, evidence: str) -> bool:
        self.checks.append({"area": area, "check": name, "passed": bool(ok), "evidence": evidence})
        print(f"{'PASS' if ok else 'FAIL'}  [{area}] {name}: {evidence}")
        return ok


def b64(d: bytes) -> str:
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode()


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def forge(token: str, alg: str, payload_patch: dict[str, Any], key: bytes | None) -> str:
    _, p, _ = token.split(".")
    payload = {**json.loads(unb64(p)), **payload_patch}
    head = b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    body = b64(json.dumps(payload).encode())
    if alg == "none":
        return f"{head}.{body}."
    assert key is not None
    sig = hmac.new(key, f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{b64(sig)}"


def with_access(base: str, token: str) -> Client:
    c = Client(base)
    c.jar.set_cookie(
        http.cookiejar.Cookie(
            0,
            "access_token",
            token,
            None,
            False,
            base.split("//")[1].split(":")[0],
            False,
            False,
            "/",
            True,
            False,
            None,
            False,
            None,
            None,
            {},
        )
    )
    return c


def user(base: str, tag: str) -> Client:
    c = Client(base)
    email = f"sec-{tag}-{secrets.token_hex(4)}@example.test"
    r = c.req("POST", "/api/auth/register", {"email": email, "password": PASSWORD})
    if r.status != 201:
        raise SystemExit(f"cannot register a test user: {r.status} {r.body[:200]}")
    r = c.req("POST", "/api/auth/login", {"email": email, "password": PASSWORD})
    if r.status != 200:
        raise SystemExit(f"cannot log in: {r.status} {r.body[:200]}")
    return c


def run(web: str, api: str | None, auth_limit: int) -> Report:
    rep = Report()
    a, b = user(web, "a"), user(web, "b")
    anon = Client(web)

    # --- authentication and session tokens
    tok = a.cookie("access_token") or ""
    rep.check("auth", "login sets an access token cookie", bool(tok), "access_token cookie present")
    for label, forged in [
        ("alg=none", forge(tok, "none", {"role": "ADMIN"}, None)),
        ("HS256 with a guessed key", forge(tok, "HS256", {"role": "ADMIN"}, b"secret")),
        ("payload edited, original signature", tok.rsplit(".", 2)[0].rsplit(".", 1)[0] + "."
         + b64(json.dumps({**json.loads(unb64(tok.split(".")[1])), "role": "ADMIN"}).encode())
         + "." + tok.split(".")[2]),
        ("expired token re-signed with a guessed key", forge(tok, "HS256", {"exp": int(time.time()) - 60}, b"x")),
    ]:  # fmt: skip
        r = with_access(web, forged).req("GET", "/api/auth/me")
        rep.check(
            "auth", f"forged JWT rejected ({label})", r.status == 401, f"GET /api/auth/me -> {r.status}"
        )
    r = anon.req("GET", "/api/auth/me")
    rep.check("auth", "no session -> 401", r.status == 401, f"{r.status}")
    unknown = anon.req(
        "POST", "/api/auth/login", {"email": "nobody-x@example.test", "password": "wrong pass 123"}
    )
    wrong = anon.req(
        "POST", "/api/auth/login", {"email": "nobody-x@example.test", "password": "wrong pass 124"}
    )
    rep.check("auth", "unknown user and wrong password look the same", unknown.status == wrong.status == 401
              and unknown.json().get("message") == wrong.json().get("message"),
              f"{unknown.status}/{wrong.status}, same message")  # fmt: skip
    me = a.req("GET", "/api/auth/me").body
    rep.check("auth", "no password hash in responses", "argon2" not in me and "passwordHash" not in me,
              "GET /api/auth/me has no hash")  # fmt: skip
    r = anon.req("POST", "/api/auth/register",
                 {"email": f"mass-{secrets.token_hex(3)}@example.test", "password": PASSWORD, "role": "ADMIN"})  # fmt: skip
    rep.check(
        "auth", "mass assignment of role rejected", r.status == 400, f"register with role=ADMIN -> {r.status}"
    )

    # --- cookies
    c = {ck.name: ck for ck in a.jar}
    rep.check("cookies", "access and refresh cookies are httpOnly",
              all(c[n].has_nonstandard_attr("HttpOnly") for n in ("access_token", "refresh_token")),
              "HttpOnly set")  # fmt: skip
    rep.check("cookies", "refresh cookie scoped to /api/auth", c["refresh_token"].path == "/api/auth",
              f"path={c['refresh_token'].path}")  # fmt: skip

    # --- CSRF
    r = a.req("POST", "/api/watchlists", {"name": "csrf"}, csrf=False)
    rep.check("csrf", "write without x-csrf-token rejected", r.status == 403, f"{r.status}")
    r = a.req("POST", "/api/watchlists", {"name": "csrf"}, headers={"x-csrf-token": "forged"})
    rep.check("csrf", "write with a wrong x-csrf-token rejected", r.status == 403, f"{r.status}")

    # --- authorisation (IDOR and roles)
    w = a.req("POST", "/api/watchlists", {"name": "Private"}).json()
    p = a.req("POST", "/api/portfolios", {"name": "Private", "cash": 1000}).json()
    al = a.req(
        "POST", "/api/alerts", {"condition": "PRICE_ABOVE", "symbol": "RELIANCE", "threshold": 99999}
    ).json()
    for label, method, path, body in [
        ("read A's portfolio", "GET", f"/api/portfolios/{p['id']}", None),
        ("trade in A's portfolio", "POST", f"/api/portfolios/{p['id']}/trades",
         {"symbol": "RELIANCE", "side": "BUY", "quantity": 1}),
        ("delete A's portfolio", "DELETE", f"/api/portfolios/{p['id']}", None),
        ("add to A's watchlist", "POST", f"/api/watchlists/{w['id']}/items", {"symbol": "TCS"}),
        ("delete A's watchlist", "DELETE", f"/api/watchlists/{w['id']}", None),
        ("disable A's alert", "PATCH", f"/api/alerts/{al['id']}", {"status": "DISABLED"}),
        ("delete A's alert", "DELETE", f"/api/alerts/{al['id']}", None),
    ]:  # fmt: skip
        r = b.req(method, path, body)
        rep.check("access", f"user B cannot {label}", r.status == 404, f"{method} -> {r.status}")
    for method, path in [("GET", "/api/users"), ("GET", "/api/admin/audit"), ("POST", "/api/admin/sync/registry"),
                         ("POST", "/api/monitoring/check"), ("GET", "/api/admin/audit?limit=1")]:  # fmt: skip
        r = a.req(method, path, {} if method == "POST" else None)
        rep.check("access", f"USER role cannot {method} {path}", r.status == 403, f"{r.status}")
    for path in ["/api/watchlists", "/api/portfolios", "/api/alerts", "/api/monitoring/alerts"]:
        r = anon.req("GET", path)
        rep.check("access", f"anonymous GET {path} -> 401", r.status == 401, f"{r.status}")
    r = a.req("POST", "/api/live/ingest", {"predictions": []})
    rep.check(
        "access", "browser session cannot use live ingestion", r.status in (401, 403, 503), f"{r.status}"
    )
    if api:
        d = Client(api)
        for label, hdr in [("missing", {}), ("wrong", {"x-ingest-token": "x" * 40})]:
            r = d.req("POST", "/api/live/ingest", {"predictions": []}, headers=hdr)
            rep.check(
                "access", f"ingestion with {label} token rejected", r.status in (403, 503), f"{r.status}"
            )

    # --- injection and input handling
    for q in ["' OR 1=1--", 'RELIANCE\'; DROP TABLE "User";--', "%' AND pg_sleep(3)--", '{"$gt":""}']:
        t0 = time.monotonic()
        r = anon.req("GET", "/api/stocks?q=" + urllib.request.quote(q))
        dt = time.monotonic() - t0
        n = len((r.json() or {}).get("items", [])) if r.status == 200 else -1
        rep.check("injection", f"stock search treats {q!r} as text", r.status in (200, 400) and n <= 0 and dt < 2.5,
                  f"{r.status}, {n} results, {dt:.2f}s")  # fmt: skip
    for sym in ["RELIANCE'--", "..%2f..%2fetc%2fpasswd", "A" * 300]:
        r = anon.req("GET", f"/api/stocks/{sym}")
        rep.check("injection", f"bad symbol {sym[:24]!r} -> 4xx", 400 <= r.status < 500, f"{r.status}")
    r = anon.req("GET", "/api/..%2f..%2fhealth")
    rep.check("injection", "proxy path traversal rejected", r.status in (400, 404), f"{r.status}")
    r = anon.req("POST", "/api/auth/login", {"email": {"$ne": ""}, "password": {"$ne": ""}})
    rep.check("injection", "object instead of string in login -> 400", r.status == 400, f"{r.status}")
    r = a.req("POST", "/api/watchlists", raw=b'{"name": "x"' + b" " * 10 + b"oops")
    rep.check("input", "malformed JSON -> 400", r.status == 400, f"{r.status}")
    r = a.req("POST", "/api/watchlists", raw=json.dumps({"name": "x" * 2_000_000}).encode())
    rep.check("input", "2 MB body rejected", r.status == 413, f"{r.status}")
    r = a.req(
        "POST",
        "/api/predictions",
        {
            "symbol": "RELIANCE",
            "timestamp": "2025-09-01T10:00:00+05:30",
            "modelId": "lightgbm-y_5m_10bp-tuned",
        },
    )
    rep.check("input", "historical prediction in the locked test period refused",
              r.status in (400, 403, 409) and "TEST_PERIOD" in r.body, f"{r.status} {r.body[:80]}")  # fmt: skip
    r = anon.req("GET", "/api/predictions/not-a-uuid")
    rep.check("input", "errors carry no stack traces", "    at " not in r.body and "node_modules" not in r.body,
              f"{r.status}")  # fmt: skip

    # --- headers
    page = anon.req("GET", "/")
    csp = page.headers.get("content-security-policy", "")
    rep.check("headers", "web CSP blocks framing and foreign scripts",
              "frame-ancestors 'none'" in csp and "default-src 'self'" in csp, csp[:90])  # fmt: skip
    for h, v in [("x-frame-options", "DENY"), ("x-content-type-options", "nosniff")]:
        rep.check(
            "headers",
            f"web sends {h}",
            page.headers.get(h, "").upper() == v.upper(),
            page.headers.get(h, "-"),
        )
    rep.check("headers", "web hides X-Powered-By", "x-powered-by" not in page.headers, "absent")
    if api:
        h = Client(api).req("GET", "/api/health", headers={"origin": "https://evil.example"})
        rep.check("headers", "API CORS refuses foreign origins", "access-control-allow-origin" not in h.headers,
                  h.headers.get("access-control-allow-origin", "no ACAO header"))  # fmt: skip
        rep.check("headers", "API sends helmet headers", h.headers.get("x-content-type-options") == "nosniff"
                  and "x-powered-by" not in h.headers, "nosniff, no x-powered-by")  # fmt: skip

    # --- rate limiting (last: locks this address out of login for a minute)
    codes = []
    for i in range(auth_limit + 5):
        r = anon.req("POST", "/api/auth/login", {"email": "nobody-y@example.test", "password": "wrong pass 123"},
                     headers={"x-forwarded-for": f"198.51.100.{i % 250 + 1}"})  # fmt: skip
        codes.append(r.status)
    rep.check("rate-limit", f"login brute force throttled even with rotating X-Forwarded-For ({auth_limit}/min)",
              429 in codes, f"first 429 at attempt {codes.index(429) + 1 if 429 in codes else 'never'}")  # fmt: skip
    return rep


def render(rep: Report, web: str) -> str:
    passed = sum(c["passed"] for c in rep.checks)
    lines = [
        "# Phase 20: security checks (black-box, running stack)",
        "",
        f"Target: {web} (through the web app's /api proxy, as a browser). {passed}/{len(rep.checks)} passed.",
        "",
        "| area | check | result | evidence |",
        "|---|---|---|---|",
    ]
    for c in rep.checks:
        ev = c["evidence"].replace("|", "\\|")
        lines.append(f"| {c['area']} | {c['check']} | {'PASS' if c['passed'] else 'FAIL'} | {ev} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", default=os.environ.get("WEB_URL", "http://localhost:3000"))
    ap.add_argument("--api", default=os.environ.get("API_URL"))
    ap.add_argument("--auth-limit", type=int, default=int(os.environ.get("AUTH_RATE_LIMIT_PER_MINUTE", "10")))
    ap.add_argument("--out")
    a = ap.parse_args()
    rep = run(a.web, a.api, a.auth_limit)
    if a.out:
        with open(a.out + ".json", "w") as f:
            json.dump({"target": a.web, "checks": rep.checks}, f, indent=1)
        with open(a.out + ".md", "w") as f:
            f.write(render(rep, a.web))
    failed = [c for c in rep.checks if not c["passed"]]
    print(f"{len(rep.checks) - len(failed)}/{len(rep.checks)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
