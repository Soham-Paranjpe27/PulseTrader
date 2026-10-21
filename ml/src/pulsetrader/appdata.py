"""Export reference data for the application database (Phase 15 seed).

Writes data/app/stocks.json (security master + research universe + inferred sector) and
data/app/day_bars.csv (daily OHLCV from the canonical minute data). The NestJS seed loads these.
Sectors are the Phase 11 inferred sectors (no offline sector master exists) and are labelled so.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl


def export(data_root: Path, out_dir: Path, dataset: str = "core100_s5") -> dict[str, Any]:
    ref = data_root / "reference"
    master = pl.read_parquet(ref / "security_master.parquet")
    hist = pl.read_parquet(ref / "symbol_history.parquet")
    manifest = json.loads((data_root / "datasets" / dataset / "dataset_manifest.json").read_text())
    universe = set(manifest["universe"])
    sectors: dict[str, str] = {}
    for f in sorted((data_root / "experiments").glob("*-p11-robustness-*/sectors.json")):
        sectors.update({k: f"{v['sector']} (inferred)" for k, v in json.loads(f.read_text()).items()})
    renames = {
        r["symbol"]: r["rename_candidate_of"] for r in hist.iter_rows(named=True) if r["rename_candidate_of"]
    }
    stocks = [
        {
            "symbol": r["symbol"],
            "instrumentType": r["instrument_type"],
            "experimentEligible": bool(r["experiment_eligible"]),
            "inResearchUniverse": r["symbol"] in universe,
            "firstDate": str(r["first_date"]) if r["first_date"] else None,
            "lastDate": str(r["last_date"]) if r["last_date"] else None,
            "medianDailyTurnover": r["median_daily_turnover"],
            "sector": sectors.get(r["symbol"]),
            "renameCandidateOf": renames.get(r["symbol"]),
        }
        for r in master.sort("symbol").iter_rows(named=True)
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stocks.json").write_text(json.dumps(stocks))
    bars = pl.read_parquet(ref / "day_bars.parquet").select(
        "symbol", pl.col("trade_date").cast(pl.Utf8), "open", "high", "low", "close", "volume"
    )
    bars = bars.filter(pl.col("symbol").is_in([s["symbol"] for s in stocks])).sort("symbol", "trade_date")
    bars.write_csv(out_dir / "day_bars.csv")
    info = {
        "stocks": len(stocks),
        "universe": len(universe),
        "day_bars": bars.height,
        "sectors": len(sectors),
    }
    (out_dir / "export.json").write_text(json.dumps(info, indent=1))
    return info
