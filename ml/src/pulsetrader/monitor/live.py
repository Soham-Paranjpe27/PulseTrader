"""Drift and latency monitoring inside the live pipeline (Phase 19).

The pipeline hands every sampled feature frame, prediction and realised outcome to `LiveDriftMonitor`.
Drift is checked on completed sessions only: intraday windows are dominated by the time-of-day pattern
(time-since-open features, opening volatility, weak accuracy at the open), so a part-day window would
look drifted every morning. When the trading day changes, or the stream ends, the monitor reports per
model on the last session (day thresholds) and on the last `sessions` sessions (week thresholds), using
the same `drift_report` as the offline check. Reports go to every sink; the API raises alerts.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from pulsetrader.monitor.drift import Reference, drift_report

log = logging.getLogger(__name__)
IDX = {"DOWN": 0, "NEUTRAL": 1, "UP": 2}


@dataclass
class _Day:
    features: list[pl.DataFrame] = field(default_factory=list)
    proba: list[list[float]] = field(default_factory=list)
    y: list[int] = field(default_factory=list)
    y_proba: list[list[float]] = field(default_factory=list)
    inference_ms: list[float] = field(default_factory=list)


def _p(d: dict[str, float]) -> list[float]:
    return [float(d["down"]), float(d["neutral"]), float(d["up"])]


def _q(v: list[float], q: float) -> float | None:
    return float(np.quantile(v, q)) if v else None


@dataclass
class LiveDriftMonitor:
    refs: dict[str, Reference]  # model key -> reference
    regimes: pl.DataFrame = field(
        default_factory=lambda: pl.DataFrame()
    )  # trade_date, nifty_trend, nifty_vol
    sessions: int = 5
    days: dict[str, OrderedDict[date, _Day]] = field(default_factory=dict)
    feature_seconds: list[float] = field(default_factory=list)
    reported: set[date] = field(default_factory=set)

    @classmethod
    def from_dir(
        cls, ref_dir: Path, keys: list[str], regimes: pl.DataFrame | None = None
    ) -> LiveDriftMonitor:
        refs = {}
        for k in keys:
            f = ref_dir / f"{k}.json"
            if f.exists():
                refs[k] = Reference.load(f)
            else:
                log.warning("no drift reference for %s (run `pulsetrader monitor`)", k)
        return cls(refs=refs, regimes=regimes if regimes is not None else pl.DataFrame())

    def _day(self, model: str, d: date) -> _Day:
        days = self.days.setdefault(model, OrderedDict())
        if d not in days:
            days[d] = _Day()
            while len(days) > self.sessions:
                days.popitem(last=False)
        return days[d]

    def observe(self, rows: pl.DataFrame, preds: list[dict[str, Any]], feature_seconds: float) -> None:
        self.feature_seconds = [*self.feature_seconds[-999:], feature_seconds]
        by_model: dict[str, list[dict[str, Any]]] = {}
        for p in preds:
            by_model.setdefault(f"{p['model_id']}@v{p['model_version']}", []).append(p)
        for key, ps in by_model.items():
            if key not in self.refs:
                continue
            d = datetime.fromisoformat(ps[0]["market_data_timestamp"]).date()
            day = self._day(key, d)
            feats = [f for f in self.refs[key].features if f in rows.columns]
            day.features.append(rows.select(feats))
            day.proba += [_p(p["raw_probability"]) for p in ps]
            day.inference_ms += [float(p["latency_ms"]) for p in ps if p.get("latency_ms") is not None]

    def observe_outcomes(self, outs: list[dict[str, Any]]) -> None:
        for o in outs:
            key = f"{o['model_id']}@v{o['model_version']}"
            if key not in self.refs or o.get("actual_class") is None:
                continue
            day = self._day(key, datetime.fromisoformat(o["market_data_timestamp"]).date())
            day.y.append(IDX[o["actual_class"]])
            day.y_proba.append(_p(o["raw_probability"]))

    def _report(self, key: str, days: list[tuple[date, _Day]], mode: str) -> dict[str, Any]:
        ref = self.refs[key]
        feats = [f for d in days for f in d[1].features]
        frame = pl.concat(feats, how="diagonal_relaxed") if feats else pl.DataFrame()
        proba = np.array([p for d in days for p in d[1].proba], dtype=np.float64).reshape(-1, 3)
        y = np.array([v for d in days for v in d[1].y], dtype=np.int64)
        yp = np.array([p for d in days for p in d[1].y_proba], dtype=np.float64).reshape(-1, 3)
        dates = [d[0] for d in days]
        reg = (
            self.regimes.filter(pl.col("trade_date").is_in(dates))
            if self.regimes.height
            else pl.DataFrame(schema={"trade_date": pl.Date, "nifty_trend": pl.Utf8, "nifty_vol": pl.Utf8})
        )
        inf = [v for d in days for v in d[1].inference_ms]
        rep = drift_report(
            ref, frame, proba, y, yp, reg,
            {"kind": "session" if len(days) == 1 else f"last_{len(days)}_sessions", "mode": mode,
             "start": str(dates[0]), "end": str(dates[-1])},
            len(days),
        )  # fmt: skip
        rep["latency"] = {
            "inference_ms_p50": _q(inf, 0.5),
            "inference_ms_p95": _q(inf, 0.95),
            "feature_build_seconds_p50": _q(self.feature_seconds, 0.5),
            "feature_build_seconds_p95": _q(self.feature_seconds, 0.95),
        }
        rep["mode"] = mode
        return rep

    def reports_for(self, d: date, mode: str) -> list[dict[str, Any]]:
        """Reports for the completed session `d` (and the sessions before it)."""
        out = []
        for key, days in self.days.items():
            done = [(k, v) for k, v in days.items() if k <= d]
            if not done or done[-1][0] != d:
                continue
            out.append(self._report(key, done[-1:], mode))
            if len(done) > 1:
                out.append(self._report(key, done, mode))
        self.reported.add(d)
        return out

    def pending_sessions(self, current: date | None) -> list[date]:
        """Sessions with data, before `current` (None: all), not reported yet."""
        seen = sorted({d for days in self.days.values() for d in days})
        return [d for d in seen if d not in self.reported and (current is None or d < current)]
