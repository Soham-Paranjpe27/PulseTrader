"""Live data validation (spec section 45) and the feed state machine.

Each bar is checked for symbol, timestamp (tz-aware, inside the session, not in the future), price
(finite, positive, OHLC consistent), volume (finite, >= 0), sequence (strictly increasing per symbol),
duplicates and latency (receive time - bar close). Rejected bars are counted by reason and never reach
the feature engine. The feed state is derived from the provider kind and recent bars:
REPLAY for recorded data, otherwise LIVE / DELAYED / STALE / INVALID / DISCONNECTED.
"""

from __future__ import annotations

import math
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pulsetrader.live.events import Bar, FeedState, in_session


@dataclass
class ValidationConfig:
    delayed_after_s: float = 90.0  # bar close -> receipt latency that counts as delayed
    stale_after_s: float = 300.0  # no accepted bar for this long (in session) -> STALE
    invalid_fraction: float = 0.2  # share of rejects among the last `window` bars -> INVALID
    window: int = 200
    max_future_s: float = 5.0  # clock skew allowed for bars stamped in the future


@dataclass
class BarValidator:
    symbols: set[str]
    cfg: ValidationConfig = field(default_factory=ValidationConfig)
    last_ts: dict[str, datetime] = field(default_factory=dict)
    rejects: Counter[str] = field(default_factory=Counter)
    accepted: int = 0
    recent: deque[bool] = field(default_factory=lambda: deque(maxlen=200))

    def check(self, b: Bar, now: datetime) -> str | None:
        """Reason the bar is rejected, or None if it is accepted."""
        if b.symbol not in self.symbols:
            return "UNKNOWN_SYMBOL"
        if b.ts.tzinfo is None:
            return "NAIVE_TIMESTAMP"
        if not in_session(b.ts):
            return "OUTSIDE_SESSION"
        if (b.close_ts - now).total_seconds() > self.cfg.max_future_s:
            return "FUTURE_TIMESTAMP"
        prices = (b.open, b.high, b.low, b.close)
        if not all(math.isfinite(p) and p > 0 for p in prices):
            return "BAD_PRICE"
        if b.high < max(b.open, b.close, b.low) or b.low > min(b.open, b.close, b.high):
            return "BAD_OHLC"
        if not math.isfinite(b.volume) or b.volume < 0:
            return "BAD_VOLUME"
        prev = self.last_ts.get(b.symbol)
        if prev is not None and b.ts == prev:
            return "DUPLICATE"
        if prev is not None and b.ts < prev:
            return "OUT_OF_SEQUENCE"
        return None

    def accept(self, b: Bar, now: datetime) -> bool:
        reason = self.check(b, now)
        self.recent.append(reason is None)
        if reason is not None:
            self.rejects[reason] += 1
            return False
        self.last_ts[b.symbol] = b.ts
        self.accepted += 1
        return True


@dataclass
class FeedMonitor:
    """Feed state from the provider kind, connection, latency and the validator's recent rejects."""

    provider: str
    is_live: bool
    cfg: ValidationConfig = field(default_factory=ValidationConfig)
    connected: bool = False
    last_bar_close: datetime | None = None
    last_received: datetime | None = None
    latencies: deque[float] = field(default_factory=lambda: deque(maxlen=500))
    note: str = ""

    def on_bar(self, b: Bar, now: datetime) -> None:
        self.last_bar_close = max(self.last_bar_close or b.close_ts, b.close_ts)
        received = b.received or now
        self.last_received = received
        self.latencies.append((received - b.close_ts).total_seconds())

    def latency_p50(self) -> float | None:
        if not self.latencies:
            return None
        xs = sorted(self.latencies)
        return xs[len(xs) // 2]

    def state(self, now: datetime, validator: BarValidator) -> tuple[FeedState, str]:
        if not self.connected:
            return FeedState.DISCONNECTED, f"{self.provider}: not connected"
        if not self.is_live:
            return FeedState.REPLAY, f"{self.provider}: recorded data, not a live feed. {self.note}".strip()
        recent = list(validator.recent)
        if len(recent) >= 20 and recent.count(False) / len(recent) > self.cfg.invalid_fraction:
            return (
                FeedState.INVALID,
                f"{recent.count(False)} of the last {len(recent)} bars failed validation",
            )
        if self.last_bar_close is None:
            return FeedState.STALE, "connected, no bars received yet"
        age = (now - self.last_bar_close).total_seconds()
        if not in_session(now - timedelta(minutes=1)) and age > self.cfg.stale_after_s:
            return FeedState.STALE, "market closed"
        if age > self.cfg.stale_after_s:
            return FeedState.STALE, f"no bar for {age:.0f}s"
        p50 = self.latency_p50()
        if p50 is not None and p50 > self.cfg.delayed_after_s:
            return FeedState.DELAYED, f"median bar latency {p50:.0f}s"
        return FeedState.LIVE, f"{self.provider}: median bar latency {p50 or 0:.1f}s"

    def snapshot(self, now: datetime, validator: BarValidator) -> dict[str, Any]:
        st, reason = self.state(now, validator)
        return {
            "state": st.value,
            "provider": self.provider,
            "source": "LIVE" if self.is_live else "REPLAY",
            "reason": reason,
            "lastBarClose": self.last_bar_close.isoformat() if self.last_bar_close else None,
            "latencyP50Seconds": self.latency_p50() if self.is_live else None,
            "accepted": validator.accepted,
            "rejected": dict(validator.rejects),
            "observedAt": now.isoformat(),
        }
