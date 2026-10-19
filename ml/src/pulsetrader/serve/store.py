"""Historical feature lookup for HISTORICAL mode (Phase 14).

Rows come from the research dataset, which the shared feature engine built, so a historical
prediction sees exactly the features the model was evaluated on. Rows in the test period are refused
unless `allow_test` is set, so serving cannot quietly evaluate the untouched test period.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl


class DataUnavailable(LookupError):
    pass


class TestPeriodLocked(PermissionError):
    pass


class HistoricalFeatureStore:
    def __init__(self, ds_dir: Path, allow_test: bool = False) -> None:
        self.ds_dir = ds_dir
        self.allow_test = allow_test
        self.manifest: dict[str, Any] = json.loads((ds_dir / "dataset_manifest.json").read_text())
        self.features: list[str] = json.loads((ds_dir / "features.json").read_text())["features"]
        self._months: OrderedDict[str, pl.DataFrame] = OrderedDict()
        self.cache_months = 2

    def _month(self, part: Path) -> pl.DataFrame:
        """One monthly partition in memory (bounded LRU), sorted for fast (symbol, ts) lookups."""
        key = part.name
        if key in self._months:
            self._months.move_to_end(key)
            return self._months[key]
        df = (
            pl.scan_parquet(part)
            .select("symbol", "ts", "trade_date", "split", *self.features)
            .collect()
            .sort("symbol", "ts")
        )
        self._months[key] = df
        while len(self._months) > self.cache_months:
            self._months.popitem(last=False)
        return df

    @property
    def dataset_id(self) -> str:
        return str(self.manifest["dataset_id"])

    def lookup(self, symbol: str, ts: datetime) -> dict[str, Any]:
        """Feature row for (symbol, bar start ts). ts must be timezone-aware."""
        if ts.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        part = self.ds_dir / f"part-{ts.astimezone(_ist()):%Y-%m}.parquet"
        if not part.exists():
            raise DataUnavailable(f"DATA_UNAVAILABLE: no dataset rows for {ts:%Y-%m}")
        row = self._month(part).filter((pl.col("symbol") == symbol) & (pl.col("ts") == ts.astimezone(_ist())))
        if row.height == 0:
            raise DataUnavailable(
                f"DATA_UNAVAILABLE: no row for {symbol} at {ts.isoformat()} (the dataset holds the "
                "research universe sampled every 5 minutes)"
            )
        r = row.row(0, named=True)
        if r["split"] == "test" and not self.allow_test:
            raise TestPeriodLocked(
                "TEST_PERIOD_LOCKED: the final test period stays untouched until model development "
                "is finished"
            )
        return {
            "symbol": symbol,
            "market_data_timestamp": r["ts"],
            "split": r["split"],
            "features": {k: (None if r[k] is None else float(r[k])) for k in self.features},
        }


def _ist() -> Any:
    from zoneinfo import ZoneInfo

    return ZoneInfo("Asia/Kolkata")
