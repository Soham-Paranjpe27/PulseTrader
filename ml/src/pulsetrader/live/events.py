"""Market events and feed states shared by providers, validation and the pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)
BAR = timedelta(minutes=1)


class FeedState(StrEnum):
    LIVE = "LIVE"  # authorised real-time provider, fresh data inside the session
    DELAYED = "DELAYED"  # real-time provider, but bars arrive late
    STALE = "STALE"  # connected, no fresh bars (or market closed)
    DISCONNECTED = "DISCONNECTED"  # no provider connection
    INVALID = "INVALID"  # data arriving but failing validation
    REPLAY = "REPLAY"  # recorded sessions replayed for testing; never shown as LIVE


@dataclass(frozen=True)
class Tick:
    """One trade/quote update. `volume` is the cumulative day volume when the provider sends it."""

    symbol: str
    ts: datetime  # exchange timestamp, tz-aware
    price: float
    volume: float | None = None
    received: datetime | None = None


@dataclass(frozen=True)
class Bar:
    """Closed 1-minute OHLCV bar; `ts` is the bar start (canonical convention), closes at ts + 1 min."""

    symbol: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    received: datetime | None = None

    @property
    def close_ts(self) -> datetime:
        return self.ts + BAR


def in_session(ts: datetime) -> bool:
    """Bar start inside the NSE regular session (09:15 <= start < 15:30 IST), weekdays only."""
    t = ts.astimezone(IST)
    return t.weekday() < 5 and SESSION_OPEN <= t.time() < SESSION_CLOSE


def minute_of_session(ts: datetime) -> int:
    t = ts.astimezone(IST)
    return (t.hour * 60 + t.minute) - (SESSION_OPEN.hour * 60 + SESSION_OPEN.minute)
