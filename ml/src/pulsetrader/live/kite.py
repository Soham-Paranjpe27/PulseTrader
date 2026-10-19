"""Zerodha Kite Connect adapter (live ticks over WebSocket, warm-up bars over REST).

Credentials come only from the environment and are never written to disk or logs:
MARKET_DATA_API_KEY (Kite Connect app key), MARKET_DATA_API_SECRET (only needed to exchange a login
request token) and MARKET_DATA_ACCESS_TOKEN (valid for one trading day; `pulsetrader kite-login`
prints a fresh one after the user logs in at Zerodha).

Network: the host must be allowed to reach api.kite.trade (REST) and ws.kite.trade (WebSocket).

Binary tick format (Kite Connect v3): a message is a 2-byte packet count, then for each packet a
2-byte length and the packet. Packet sizes: 8 (LTP), 28/32 (index quote/full), 44 (quote), 184
(full, adds the exchange timestamp). Integers are big-endian; prices are in paise (/100) for NSE.
Single-byte messages are heartbeats; text messages are JSON (errors, order updates).
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
import os
import struct
import time
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import polars as pl

from pulsetrader.live.events import IST, Tick
from pulsetrader.live.providers import WARMUP_SESSIONS, LiveProvider, ProviderError

log = logging.getLogger(__name__)

API = "https://api.kite.trade"
WS = "wss://ws.kite.trade"
LOGIN = "https://kite.zerodha.com/connect/login"
SEGMENT_INDICES = 9
# our canonical symbol -> Kite trading symbol, where they differ
ALIASES = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK", "INDIA VIX": "INDIA VIX"}


def checksum(api_key: str, request_token: str, api_secret: str) -> str:
    return hashlib.sha256((api_key + request_token + api_secret).encode()).hexdigest()


def login_url(api_key: str) -> str:
    return f"{LOGIN}?{urllib.parse.urlencode({'v': 3, 'api_key': api_key})}"


def _i(b: bytes, a: int, z: int) -> int:
    return int(struct.unpack(">i", b[a:z])[0])


def split_packets(msg: bytes) -> list[bytes]:
    if len(msg) < 2:
        return []  # heartbeat
    n = struct.unpack(">H", msg[0:2])[0]
    out, j = [], 2
    for _ in range(n):
        if j + 2 > len(msg):
            raise ValueError("truncated Kite message")
        ln = struct.unpack(">H", msg[j : j + 2])[0]
        pkt = msg[j + 2 : j + 2 + ln]
        if len(pkt) != ln:
            raise ValueError("truncated Kite packet")
        out.append(pkt)
        j += 2 + ln
    return out


def parse_packet(p: bytes) -> dict[str, Any]:
    token = _i(p, 0, 4)
    segment = token & 0xFF
    div = 10_000_000.0 if segment == 3 else 10_000.0 if segment == 6 else 100.0
    d: dict[str, Any] = {"instrument_token": token, "tradable": segment != SEGMENT_INDICES}
    if len(p) == 8:
        d.update(mode="ltp", last_price=_i(p, 4, 8) / div)
    elif len(p) in (28, 32):  # index
        d.update(
            mode="quote" if len(p) == 28 else "full",
            last_price=_i(p, 4, 8) / div,
            high=_i(p, 8, 12) / div,
            low=_i(p, 12, 16) / div,
            open=_i(p, 16, 20) / div,
            close=_i(p, 20, 24) / div,
        )
        if len(p) == 32:
            d["exchange_timestamp"] = datetime.fromtimestamp(_i(p, 28, 32), UTC)
    elif len(p) in (44, 184):
        d.update(
            mode="quote" if len(p) == 44 else "full",
            last_price=_i(p, 4, 8) / div,
            last_traded_quantity=_i(p, 8, 12),
            average_traded_price=_i(p, 12, 16) / div,
            volume_traded=_i(p, 16, 20),
            open=_i(p, 28, 32) / div,
            high=_i(p, 32, 36) / div,
            low=_i(p, 36, 40) / div,
            close=_i(p, 40, 44) / div,
        )
        if len(p) == 184:
            d["last_trade_time"] = datetime.fromtimestamp(_i(p, 44, 48), UTC)
            d["exchange_timestamp"] = datetime.fromtimestamp(_i(p, 60, 64), UTC)
    else:
        raise ValueError(f"unknown Kite packet length {len(p)}")
    return d


def parse_message(msg: bytes) -> list[dict[str, Any]]:
    return [parse_packet(p) for p in split_packets(msg)]


def to_tick(d: dict[str, Any], symbol: str, received: datetime) -> Tick:
    ts = d.get("exchange_timestamp") or d.get("last_trade_time") or received
    vol = d.get("volume_traded")
    return Tick(
        symbol, ts.astimezone(IST), float(d["last_price"]), None if vol is None else float(vol), received
    )


def instrument_map(csv_text: str, symbols: list[str], exchange: str = "NSE") -> dict[str, int]:
    """Our symbol -> Kite instrument token, from the instruments dump (equities and NSE indices)."""
    want = {ALIASES.get(s, s): s for s in symbols}
    out: dict[str, int] = {}
    for r in csv.DictReader(io.StringIO(csv_text)):
        if r.get("exchange") != exchange or r.get("tradingsymbol") not in want:
            continue
        if r.get("segment") not in (exchange, "INDICES") or r.get("instrument_type") not in ("EQ", ""):
            continue
        out[want[r["tradingsymbol"]]] = int(r["instrument_token"])
    return out


@dataclass
class KiteREST:
    api_key: str
    access_token: str
    timeout: float = 20.0

    def _get(self, path: str, params: dict[str, str] | None = None) -> bytes:
        url = f"{API}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        req = urllib.request.Request(
            url,
            headers={"X-Kite-Version": "3", "Authorization": f"token {self.api_key}:{self.access_token}"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 (fixed https host)
            body: bytes = r.read()
            return body

    def instruments(self, exchange: str = "NSE") -> str:
        return self._get(f"/instruments/{exchange}").decode()

    def minute_candles(self, token: int, start: date, end: date) -> list[list[Any]]:
        body = json.loads(
            self._get(
                f"/instruments/historical/{token}/minute",
                {"from": f"{start} 09:15:00", "to": f"{end} 15:30:00"},
            )
        )
        if body.get("status") != "success":
            raise ProviderError(f"Kite historical: {body.get('message', 'error')}")
        candles: list[list[Any]] = body["data"]["candles"]
        return candles


def exchange_request_token(api_key: str, api_secret: str, request_token: str, timeout: float = 20.0) -> str:
    """Exchange the request token from the Zerodha login redirect for a one-day access token."""
    data = urllib.parse.urlencode(
        {"api_key": api_key, "request_token": request_token,
         "checksum": checksum(api_key, request_token, api_secret)}
    ).encode()  # fmt: skip
    req = urllib.request.Request(f"{API}/session/token", data=data, headers={"X-Kite-Version": "3"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed https host)
        body = json.loads(r.read())
    if body.get("status") != "success":
        raise ProviderError(f"Kite login failed: {body.get('message', 'error')}")
    token: str = body["data"]["access_token"]
    return token


class KiteProvider(LiveProvider):
    name = "zerodha-kite"

    def __init__(self, api_key: str, access_token: str, warmup_days: int = 10) -> None:
        super().__init__(cumulative_volume=True)
        if not api_key or not access_token:
            raise ProviderError("Kite needs MARKET_DATA_API_KEY and MARKET_DATA_ACCESS_TOKEN")
        self.rest = KiteREST(api_key, access_token)
        self.api_key, self._access = api_key, access_token
        self.warmup_days = warmup_days
        self.tokens: dict[str, int] = {}
        self.last_error: str | None = None

    @classmethod
    def from_env(cls) -> KiteProvider:
        return cls(os.environ.get("MARKET_DATA_API_KEY", ""), os.environ.get("MARKET_DATA_ACCESS_TOKEN", ""))

    def _resolve(self, symbols: list[str]) -> dict[str, int]:
        if not self.tokens:
            self.tokens = instrument_map(self.rest.instruments("NSE"), symbols)
            missing = sorted(set(symbols) - set(self.tokens))
            if missing:
                log.warning("Kite has no NSE instrument for %d symbols: %s", len(missing), missing[:10])
        return self.tokens

    def history(self, symbols: list[str]) -> pl.DataFrame:
        """Last WARMUP_SESSIONS sessions of minute candles before today, from Kite's historical API."""
        tokens = self._resolve(symbols)
        today = datetime.now(IST).date()
        start = today - timedelta(days=self.warmup_days)
        rows: list[dict[str, Any]] = []
        for s, tok in tokens.items():
            time.sleep(0.35)  # Kite historical API allows ~3 requests per second
            for ts, o, h, lo, c, v, *_ in self.rest.minute_candles(tok, start, today - timedelta(days=1)):
                rows.append({"symbol": s, "ts": datetime.fromisoformat(ts), "open": o, "high": h,
                             "low": lo, "close": c, "volume": float(v)})  # fmt: skip
        if not rows:
            raise ProviderError("Kite returned no warm-up candles")
        df = pl.DataFrame(rows).with_columns(pl.col("ts").dt.convert_time_zone("Asia/Kolkata"))
        df = df.with_columns(pl.col("ts").dt.date().alias("trade_date"))
        keep = df["trade_date"].unique().sort().tail(WARMUP_SESSIONS).implode()
        return df.filter(pl.col("trade_date").is_in(keep)).sort("symbol", "ts")

    async def ticks(self, symbols: list[str]) -> AsyncIterator[Tick]:
        import websockets  # optional dependency: pip install -e ".[live]"

        tokens = self._resolve(symbols)
        by_token = {v: k for k, v in tokens.items()}
        url = f"{WS}?{urllib.parse.urlencode({'api_key': self.api_key, 'access_token': self._access})}"
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(url, max_size=2**22, ping_interval=None) as ws:
                    self.connected, backoff, self.last_error = True, 1.0, None
                    toks = list(by_token)
                    await ws.send(json.dumps({"a": "subscribe", "v": toks}))
                    await ws.send(json.dumps({"a": "mode", "v": ["full", toks]}))
                    async for msg in ws:
                        now = datetime.now(UTC)
                        if isinstance(msg, str):
                            self._on_text(msg)
                            continue
                        for d in parse_message(msg):
                            sym = by_token.get(d["instrument_token"])
                            if sym is not None:
                                yield to_tick(d, sym, now)
            except (OSError, ValueError, websockets.WebSocketException) as e:
                self.connected, self.last_error = False, f"{type(e).__name__}: {e}"
                log.warning("Kite WebSocket dropped (%s); reconnecting in %.0fs", self.last_error, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    def _on_text(self, msg: str) -> None:
        try:
            body = json.loads(msg)
        except json.JSONDecodeError:
            log.warning("Kite sent non-JSON text")
            return
        if body.get("type") == "error":
            self.last_error = str(body.get("data"))
            log.warning("Kite error: %s", self.last_error)
