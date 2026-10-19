"""Candle aggregator: ticks -> closed 1-minute OHLCV bars (bar start convention, IST minutes).

Volume: when ticks carry the cumulative day volume (Kite `volume_traded`), a bar's volume is the
increase over the previous tick's cumulative volume; otherwise each tick's `volume` is summed.
A bar is emitted when the first tick of a later minute arrives, or by `flush(now)` once the minute
plus `grace` has passed (so a quiet symbol's last bar is not held back forever).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from pulsetrader.live.events import BAR, Bar, Tick


def minute_floor(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


@dataclass
class _Open:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    received: datetime | None


@dataclass
class CandleAggregator:
    cumulative_volume: bool = True
    grace: timedelta = timedelta(seconds=2)
    _open: dict[str, _Open] = field(default_factory=dict)
    _last_cum: dict[str, float] = field(default_factory=dict)
    _last_tick: dict[str, datetime] = field(default_factory=dict)

    def _vol(self, t: Tick) -> float:
        if t.volume is None:
            return 0.0
        if not self.cumulative_volume:
            return t.volume
        prev = self._last_cum.get(t.symbol)
        self._last_cum[t.symbol] = t.volume
        # first tick of the day, or a provider reset: no increment can be measured
        return 0.0 if prev is None or t.volume < prev else t.volume - prev

    def add(self, t: Tick) -> list[Bar]:
        """Feed one tick; returns bars closed by it. Ticks older than the open bar are dropped."""
        last = self._last_tick.get(t.symbol)
        if last is not None and t.ts < last:
            return []
        self._last_tick[t.symbol] = t.ts
        m = minute_floor(t.ts)
        out: list[Bar] = []
        cur = self._open.get(t.symbol)
        vol = self._vol(t)
        if cur is not None and m > cur.ts:
            out.append(self._close(t.symbol, cur))
            cur = None
        if cur is None:
            self._open[t.symbol] = _Open(m, t.price, t.price, t.price, t.price, vol, t.received)
        else:
            cur.high = max(cur.high, t.price)
            cur.low = min(cur.low, t.price)
            cur.close = t.price
            cur.volume += vol
            cur.received = t.received or cur.received
        return out

    def _close(self, symbol: str, o: _Open) -> Bar:
        return Bar(symbol, o.ts, o.open, o.high, o.low, o.close, o.volume, o.received)

    def flush(self, now: datetime) -> list[Bar]:
        """Close every open bar whose minute ended at least `grace` ago."""
        out = []
        for sym, o in list(self._open.items()):
            if now >= o.ts + BAR + self.grace:
                out.append(self._close(sym, o))
                del self._open[sym]
        return out
