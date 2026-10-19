"""Live prediction outcomes (spec section 47/48): after each prediction horizon, the realised price,
return, class and direction correctness of every live (or replayed) prediction.

Outcomes use the research label definition itself (`labels.add_labels` on the cached validated bars):
fret_h = close[t+h] / close[t] - 1 with t+h the bar exactly h minutes later in the same session, else
null; the class uses the model's own label threshold. So a live outcome is the same number the model
was trained and validated against, computed from the bars the live system actually received.

A prediction is resolved once the minute of its target bar has been finalised, or immediately when
the target lies outside the session (no such bar can exist; the label is null, as in research).
`direction_correct` is set only for UP/DOWN calls: the realised class equals the call (an actual
NEUTRAL counts as wrong, as in every research report); `sign_correct` compares with the return's sign.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import polars as pl

from pulsetrader.labels.labels import add_labels, direction_label
from pulsetrader.live.cache import BarCache
from pulsetrader.live.events import in_session

CLASS_OF = {1: "UP", 0: "NEUTRAL", -1: "DOWN"}


@dataclass
class OutcomeTracker:
    pending: list[dict[str, Any]] = field(default_factory=list)
    resolved: int = 0

    def add(self, preds: list[dict[str, Any]]) -> None:
        for p in preds:
            ts = datetime.fromisoformat(p["market_data_timestamp"])
            h = int(p["prediction_horizon_minutes"])
            self.pending.append({**p, "_ts": ts, "_target": ts + timedelta(minutes=h)})

    def due(self, done: datetime | None, final: bool = False) -> list[dict[str, Any]]:
        return [
            p for p in self.pending
            if final or not in_session(p["_target"]) or (done is not None and p["_target"] <= done)
        ]  # fmt: skip

    def resolve(self, cache: BarCache, done: datetime | None, final: bool = False) -> list[dict[str, Any]]:
        """Outcomes for every due prediction (removed from pending)."""
        due = self.due(done, final)
        if not due:
            return []
        ids = {id(p) for p in due}
        self.pending = [p for p in self.pending if id(p) not in ids]
        symbols = sorted({p["symbol"] for p in due})
        upto = max(p["_target"] for p in due)
        frame = cache.frame(symbols, upto).with_columns(pl.col("ts").dt.date().alias("trade_date"))
        horizons = tuple(sorted({int(p["prediction_horizon_minutes"]) for p in due}))
        lab = add_labels(frame, horizons).select(
            "symbol", "ts", "close", *[f"fret_{h}" for h in horizons], *[f"fprice_{h}" for h in horizons]
        )
        index = {(s, t): r for s, t, *r in lab.iter_rows()}
        out = [self._outcome(p, index.get((p["symbol"], p["_ts"])), horizons) for p in due]
        self.resolved += len(out)
        return out

    @staticmethod
    def _outcome(p: dict[str, Any], row: list[Any] | None, horizons: tuple[int, ...]) -> dict[str, Any]:
        h = int(p["prediction_horizon_minutes"])
        k = horizons.index(h)
        fret = fprice = None
        if row is not None:
            fret, fprice = row[1 + k], row[1 + len(horizons) + k]
        actual = None
        if fret is not None:
            v = pl.select(direction_label(pl.lit(fret), float(p["label_threshold"]))).item()
            actual = CLASS_OF[int(v)]
        called = p["direction"] in ("UP", "DOWN")
        pred_ret = p.get("predicted_return")
        return {
            "prediction_id": p["prediction_id"],
            "model_id": p["model_id"],
            "model_version": p["model_version"],
            "symbol": p["symbol"],
            "market_data_timestamp": p["market_data_timestamp"],
            "target_timestamp": p["_target"].isoformat(),
            "mode": p.get("mode"),
            "direction": p["direction"],
            "model_class": p["model_class"],
            "raw_probability": p["raw_probability"],
            "calibrated_probability": p["calibrated_probability"],
            "label_threshold": p["label_threshold"],
            "horizon_minutes": h,
            "actual_price": fprice,
            "actual_return": fret,
            "actual_class": actual,
            "prediction_error": (pred_ret - fret) if pred_ret is not None and fret is not None else None,
            "direction_correct": (actual == p["direction"]) if called and actual is not None else None,
            "sign_correct": (
                (fret > 0 if p["direction"] == "UP" else fret < 0) if called and fret is not None else None
            ),
        }
