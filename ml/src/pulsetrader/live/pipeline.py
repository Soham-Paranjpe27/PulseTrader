"""Live pipeline (spec section 44): provider -> validation -> real-time cache -> shared feature engine ->
inference -> prediction store (sinks) -> API, which streams to the dashboard over SSE.

A minute is finalised when a bar of a later minute arrives (replay, and busy live feeds) or, for live
providers, `finalize_grace` after the minute closed. Predictions are made only at sampled bars
(minute-of-session % sample_every == 0), the cadence the models were trained and validated on.
`now` for staleness is when the minute's last bar became available (replay: the bar close, since
recorded data has no network latency), so a replayed session is judged by the clock it ran on.

Feed state comes from `FeedMonitor`; recorded data is always REPLAY and never LIVE. No predictions are
made while the feed is INVALID or DISCONNECTED.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import polars as pl

from pulsetrader.config import FEATURE_VERSION
from pulsetrader.live.cache import BarCache
from pulsetrader.live.events import BAR, Bar, FeedState, minute_of_session
from pulsetrader.live.features import LiveUniverse, check_features, feature_rows
from pulsetrader.live.providers import LiveProvider, MarketDataProvider
from pulsetrader.live.validate import BarValidator, FeedMonitor, ValidationConfig
from pulsetrader.serve.models import LoadedModel

log = logging.getLogger(__name__)


class Sink(Protocol):
    def predictions(self, preds: list[dict[str, Any]]) -> None: ...
    def status(self, snapshot: dict[str, Any]) -> None: ...


@dataclass
class MemorySink:
    preds: list[dict[str, Any]] = field(default_factory=list)
    statuses: list[dict[str, Any]] = field(default_factory=list)

    def predictions(self, preds: list[dict[str, Any]]) -> None:
        self.preds.extend(preds)

    def status(self, snapshot: dict[str, Any]) -> None:
        self.statuses.append(snapshot)


@dataclass
class JsonlSink:
    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("")

    def predictions(self, preds: list[dict[str, Any]]) -> None:
        with self.path.open("a") as f:
            for p in preds:
                f.write(json.dumps(p, default=str) + "\n")

    def status(self, snapshot: dict[str, Any]) -> None:
        return None


@dataclass
class ApiSink:
    """POSTs to the API's ingestion endpoints (token in `x-ingest-token`, from LIVE_INGEST_TOKEN)."""

    base_url: str
    token: str
    timeout: float = 10.0
    failures: int = 0
    sent: int = 0

    def _post(self, path: str, body: dict[str, Any]) -> None:
        req = urllib.request.Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=json.dumps(body, default=str).encode(),
            headers={"content-type": "application/json", "x-ingest-token": self.token},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 (configured API URL)
                r.read()
            self.sent += 1
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            self.failures += 1
            log.warning("API sink %s failed: %s", path, e)

    def predictions(self, preds: list[dict[str, Any]]) -> None:
        for i in range(0, len(preds), 50):  # stays under the API body limit (100 kB)
            self._post("/live/ingest", {"predictions": preds[i : i + 50]})

    def status(self, snapshot: dict[str, Any]) -> None:
        self._post("/live/status", snapshot)


@dataclass
class PipelineConfig:
    max_staleness_s: float = 120.0
    finalize_grace: timedelta = timedelta(seconds=4)
    keep_features: bool = False  # keep feature rows in memory (parity checks)
    validation: ValidationConfig = field(default_factory=ValidationConfig)


@dataclass
class LivePipeline:
    provider: MarketDataProvider
    universe: LiveUniverse
    models: list[LoadedModel]
    sinks: list[Sink]
    cfg: PipelineConfig = field(default_factory=PipelineConfig)
    current: datetime | None = None
    feature_frames: list[pl.DataFrame] = field(default_factory=list)
    stats: dict[str, Any] = field(
        default_factory=lambda: {
            "minutes": 0, "sampled": 0, "predictions": 0, "late_bars": 0, "feature_seconds": []
        }
    )  # fmt: skip

    def __post_init__(self) -> None:
        self.validator = BarValidator(set(self.universe.symbols), self.cfg.validation)
        self.monitor = FeedMonitor(self.provider.name, self.provider.is_live, self.cfg.validation)
        self._avail: datetime | None = None
        self._last_now: datetime | None = None
        self._done: datetime | None = None
        for m in self.models:
            if m.feature_version != FEATURE_VERSION:
                raise ValueError(f"{m.record.key} uses {m.feature_version}, engine is {FEATURE_VERSION}")

    @property
    def mode(self) -> str:
        return "LIVE" if self.provider.is_live else "REPLAY"

    def _state(self, now: datetime) -> FeedState:
        return self.monitor.state(now, self.validator)[0]

    def publish_status(self, now: datetime) -> dict[str, Any]:
        self.monitor.connected = self.provider.connected
        snap = self.monitor.snapshot(now, self.validator)
        snap["mode"] = self.mode
        snap["prices"] = {s: {"ts": b.ts.isoformat(), "close": b.close} for s, b in self.cache.latest.items()}
        for s in self.sinks:
            s.status(snap)
        return snap

    def on_bar(self, b: Bar, now: datetime) -> None:
        self._last_now = now
        if not self.validator.accept(b, now):
            return
        self.monitor.on_bar(b, now)
        self.cache.add(b)
        if (self._done is not None and b.ts <= self._done) or (
            self.current is not None and b.ts < self.current
        ):
            self.stats["late_bars"] += 1  # its minute is already finalised; it still warms later bars
            return
        if self.current is not None and b.ts > self.current:
            self.finalize(self.current)
        if self.current is None or b.ts > self.current:
            self.current, self._avail = b.ts, now
        self._avail = max(self._avail or now, now)

    def tick(self, now: datetime) -> None:
        """Clock-driven finalisation for live feeds whose next-minute bar has not arrived yet."""
        if self.current is not None and now >= self.current + BAR + self.cfg.finalize_grace:
            self.finalize(self.current)
            self.current = None

    def finalize(self, ts: datetime) -> None:
        now = self._avail or ts + BAR
        self._done = ts
        self.stats["minutes"] += 1
        state = self._state(now)
        mos = minute_of_session(ts)
        if (
            mos >= 0
            and self.universe.is_sample_bar(mos)
            and state not in (FeedState.INVALID, FeedState.DISCONNECTED)
        ):
            self.predict(ts, now, state)
        self.publish_status(now)

    def predict(self, ts: datetime, now: datetime, state: FeedState) -> list[dict[str, Any]]:
        t0 = time.perf_counter()
        rows, names = feature_rows(self.cache, self.universe, ts)
        self.stats["feature_seconds"].append(time.perf_counter() - t0)
        self.stats["sampled"] += 1
        if self.cfg.keep_features:
            self.feature_frames.append(rows)
        out: list[dict[str, Any]] = []
        if rows.height == 0:
            return out
        quality = f"{state.value}_VALIDATED"
        records = rows.to_dicts()
        for m in self.models:
            check_features(names, m.features, FEATURE_VERSION, m.feature_version)
            items = [
                {"symbol": r["symbol"], "market_data_timestamp": r["ts"],
                 "features": {f: r.get(f) for f in m.features},
                 "max_staleness_seconds": self.cfg.max_staleness_s,
                 "current_price": r["close"], "data_quality": quality}
                for r in records
            ]  # fmt: skip
            preds = m.predict(items, now=now)
            for p in preds:
                p.update(mode=self.mode, feed_state=state.value, provider=self.provider.name)
            out += preds
        self.stats["predictions"] += len(out)
        for s in self.sinks:
            s.predictions(out)
        return out

    async def run(self, max_bars: int | None = None) -> dict[str, Any]:
        self.cache = BarCache(self.provider.history(self.universe.symbols))
        clock: asyncio.Task[None] | None = None
        if isinstance(self.provider, LiveProvider):
            clock = asyncio.create_task(self._clock(self.provider))
        n = 0
        try:
            async for b in self.provider.bars(self.universe.symbols):
                self.monitor.connected = True
                self.on_bar(b, b.received or b.close_ts)
                n += 1
                if max_bars is not None and n >= max_bars:
                    break
        finally:
            if clock is not None:
                clock.cancel()
                await asyncio.gather(clock, return_exceptions=True)
            await self.provider.close()
        if self.current is not None:
            self.finalize(self.current)
            self.current = None
        self.publish_status(self._last_now or datetime.now().astimezone())
        fsec = self.stats["feature_seconds"]
        return {
            **{k: v for k, v in self.stats.items() if k != "feature_seconds"},
            "bars": n,
            "accepted": self.validator.accepted,
            "rejected": dict(self.validator.rejects),
            "feature_seconds_p50": sorted(fsec)[len(fsec) // 2] if fsec else None,
            "feature_seconds_max": max(fsec) if fsec else None,
            "mode": self.mode,
            "provider": self.provider.name,
        }

    async def _clock(self, provider: LiveProvider) -> None:
        last_status = 0.0
        while True:
            await asyncio.sleep(1.0)
            now = provider.now()
            self.tick(now)
            if time.monotonic() - last_status > 15:
                self.publish_status(now)
                last_status = time.monotonic()
