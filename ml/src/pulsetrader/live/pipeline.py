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
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import polars as pl

from pulsetrader.config import FEATURE_VERSION
from pulsetrader.live.cache import BarCache
from pulsetrader.live.events import BAR, Bar, FeedState, minute_of_session
from pulsetrader.live.features import LiveUniverse, check_features, feature_rows
from pulsetrader.live.outcomes import OutcomeTracker
from pulsetrader.live.providers import LiveProvider, MarketDataProvider
from pulsetrader.live.validate import BarValidator, FeedMonitor, ValidationConfig
from pulsetrader.monitor.live import LiveDriftMonitor
from pulsetrader.serve.models import LoadedModel

log = logging.getLogger(__name__)


class Sink(Protocol):
    def predictions(self, preds: list[dict[str, Any]]) -> None: ...
    def outcomes(self, outs: list[dict[str, Any]]) -> None: ...
    def status(self, snapshot: dict[str, Any]) -> None: ...
    def monitoring(self, reports: list[dict[str, Any]]) -> None: ...


@dataclass
class MemorySink:
    preds: list[dict[str, Any]] = field(default_factory=list)
    statuses: list[dict[str, Any]] = field(default_factory=list)
    outs: list[dict[str, Any]] = field(default_factory=list)
    reports: list[dict[str, Any]] = field(default_factory=list)

    def predictions(self, preds: list[dict[str, Any]]) -> None:
        self.preds.extend(preds)

    def monitoring(self, reports: list[dict[str, Any]]) -> None:
        self.reports.extend(reports)

    def outcomes(self, outs: list[dict[str, Any]]) -> None:
        self.outs.extend(outs)

    def status(self, snapshot: dict[str, Any]) -> None:
        self.statuses.append(snapshot)


@dataclass
class JsonlSink:
    """Predictions to `path`, outcomes and drift reports next to it (`.outcomes.jsonl`,
    `.monitoring.jsonl`)."""

    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("")
        self.outcomes_path = self.path.with_suffix(".outcomes.jsonl")
        self.outcomes_path.write_text("")
        self.monitoring_path = self.path.with_suffix(".monitoring.jsonl")
        self.monitoring_path.write_text("")

    @staticmethod
    def _append(path: Path, rows: list[dict[str, Any]]) -> None:
        with path.open("a") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")

    def predictions(self, preds: list[dict[str, Any]]) -> None:
        self._append(self.path, preds)

    def outcomes(self, outs: list[dict[str, Any]]) -> None:
        self._append(self.outcomes_path, outs)

    def monitoring(self, reports: list[dict[str, Any]]) -> None:
        self._append(self.monitoring_path, reports)

    def status(self, snapshot: dict[str, Any]) -> None:
        return None


@dataclass
class ApiSink:
    """POSTs to the API's ingestion endpoints (token in `x-ingest-token`, from LIVE_INGEST_TOKEN).

    When the API is unreachable or answers 5xx/429, requests wait in an ordered queue (predictions stay
    ahead of their outcomes) and are retried with exponential backoff, so a short API outage loses
    nothing. The queue is bounded (`max_pending` requests); beyond it the oldest request is dropped and
    counted. A 4xx answer means the request itself is wrong: it is logged and not retried.
    """

    base_url: str
    token: str
    timeout: float = 10.0
    max_pending: int = 5000
    max_backoff: float = 60.0
    failures: int = 0
    sent: int = 0
    rejected: int = 0
    dropped: int = 0
    pending: deque[tuple[str, dict[str, Any]]] = field(default_factory=deque)
    backoff: float = 0.0
    retry_at: float = 0.0

    def _send(self, path: str, body: dict[str, Any]) -> bool:
        """True when the request is done with (stored, or rejected as invalid); False to retry."""
        req = urllib.request.Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=json.dumps(body, default=str).encode(),
            headers={"content-type": "application/json", "x-ingest-token": self.token},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 (configured API URL)
                r.read()
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                self.rejected += 1
                log.error("API sink %s rejected (HTTP %d): %s", path, e.code, e.read()[:300])
                return True
            self.failures += 1
            log.warning("API sink %s failed (HTTP %d); queued for retry", path, e.code)
            return False
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            self.failures += 1
            log.warning("API sink %s failed (%s); queued for retry", path, e)
            return False
        self.sent += 1
        return True

    def _failed(self) -> None:
        self.backoff = min(self.max_backoff, max(1.0, self.backoff * 2))
        self.retry_at = time.monotonic() + self.backoff

    def flush(self) -> bool:
        """Send queued requests in order; stops at the first failure. True when the queue is empty."""
        while self.pending:
            if time.monotonic() < self.retry_at:
                return False
            if not self._send(*self.pending[0]):
                self._failed()
                return False
            self.pending.popleft()
            self.backoff = 0.0
        return True

    def _post(self, path: str, body: dict[str, Any]) -> None:
        if self.flush() and time.monotonic() >= self.retry_at:
            if self._send(path, body):
                self.backoff = 0.0
                return
            self._failed()
        self.pending.append((path, body))
        if len(self.pending) > self.max_pending:
            self.pending.popleft()
            self.dropped += 1
            log.error("API sink queue full (%d requests); dropped the oldest", self.max_pending)

    def stats(self) -> dict[str, int]:
        return {"sent": self.sent, "failures": self.failures, "rejected": self.rejected,
                "pending": len(self.pending), "dropped": self.dropped}  # fmt: skip

    def predictions(self, preds: list[dict[str, Any]]) -> None:
        for i in range(0, len(preds), 50):  # stays under the API body limit (100 kB)
            self._post("/live/ingest", {"predictions": preds[i : i + 50]})

    def outcomes(self, outs: list[dict[str, Any]]) -> None:
        keep = ("prediction_id", "actual_price", "actual_return", "actual_class", "prediction_error",
                "direction_correct")  # fmt: skip
        rows = [{k: o[k] for k in keep} for o in outs]
        for i in range(0, len(rows), 200):
            self._post("/live/outcomes", {"outcomes": rows[i : i + 200]})

    def status(self, snapshot: dict[str, Any]) -> None:
        self._post("/live/status", snapshot)

    def monitoring(self, reports: list[dict[str, Any]]) -> None:
        for r in reports:  # one report per request keeps each body small
            self._post("/live/monitoring", {"reports": [r]})


@dataclass
class PipelineConfig:
    max_staleness_s: float = 120.0
    finalize_grace: timedelta = timedelta(seconds=4)
    keep_features: bool = False  # keep feature rows in memory (parity checks)
    track_outcomes: bool = True  # evaluate every prediction after its horizon (Phase 18)
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
    drift: LiveDriftMonitor | None = None  # Phase 19: drift reports after each completed session
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
        self.tracker = OutcomeTracker()
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

    def check_drift(self, current: datetime | None) -> list[dict[str, Any]]:
        """Drift reports for sessions completed before `current` (None: every session with data)."""
        if self.drift is None:
            return []
        reps: list[dict[str, Any]] = []
        for d in self.drift.pending_sessions(current.date() if current else None):
            reps += self.drift.reports_for(d, self.mode)
        if reps:
            self.stats["drift_reports"] = self.stats.get("drift_reports", 0) + len(reps)
            for s in self.sinks:
                s.monitoring(reps)
        return reps

    def finalize(self, ts: datetime) -> None:
        now = self._avail or ts + BAR
        self.check_drift(ts)  # a new session started: report on the completed one
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
        self.resolve_outcomes()
        self.publish_status(now)

    def resolve_outcomes(self, final: bool = False) -> list[dict[str, Any]]:
        if not self.cfg.track_outcomes:
            return []
        outs = self.tracker.resolve(self.cache, self._done, final)
        if outs and self.drift is not None:
            self.drift.observe_outcomes(outs)
        if outs:
            self.stats["outcomes"] = self.stats.get("outcomes", 0) + len(outs)
            for s in self.sinks:
                s.outcomes(outs)
        return outs

    def predict(self, ts: datetime, now: datetime, state: FeedState) -> list[dict[str, Any]]:
        t0 = time.perf_counter()
        rows, names = feature_rows(self.cache, self.universe, ts)
        fsec = time.perf_counter() - t0
        self.stats["feature_seconds"].append(fsec)
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
        if self.drift is not None:
            self.drift.observe(rows, out, fsec)
        if self.cfg.track_outcomes:
            self.tracker.add(out)
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
        self.resolve_outcomes(final=True)  # stream ended: no later bar can arrive
        self.check_drift(None)
        self.publish_status(self._last_now or datetime.now().astimezone())
        sinks = {}
        for sink in self.sinks:
            if isinstance(sink, ApiSink):
                for _ in range(5):  # last chance for requests queued during an API outage
                    if sink.flush():
                        break
                    await asyncio.sleep(max(0.0, sink.retry_at - time.monotonic()))
                sinks["api"] = sink.stats()
        fsec = self.stats["feature_seconds"]
        return {
            **({"sinks": sinks} if sinks else {}),
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
