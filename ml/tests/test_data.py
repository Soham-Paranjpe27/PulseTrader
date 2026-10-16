from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from golden import write_raw

from pulsetrader.data import discovery, pipeline
from pulsetrader.data.io import sha256_file
from pulsetrader.data.schema import SchemaError, resolve_columns, symbol_from_path


def test_resolve_columns_aliases():
    m = resolve_columns(["Date", "Open", "High", "Low", "Close", "Volume"])
    assert m["ts"] == "Date" and m["close"] == "Close"
    with pytest.raises(SchemaError):
        resolve_columns(["date", "open", "close"])


def test_symbol_from_path():
    assert symbol_from_path(Path("x/RELIANCE_minute.csv")) == "RELIANCE"
    assert symbol_from_path(Path("NIFTY 50_minute.csv")) == "NIFTY 50"
    assert symbol_from_path(Path("tcs.parquet")) == "TCS"


@pytest.fixture()
def processed(tmp_path):
    raw = tmp_path / "raw"
    write_raw(raw)
    before = {p.name: sha256_file(p) for p in raw.iterdir()}
    m = pipeline.run(raw, tmp_path)
    return tmp_path, raw, before, m


def test_raw_immutable(processed):
    _, raw, before, _ = processed
    assert {p.name: sha256_file(p) for p in raw.iterdir()} == before


def test_dirty_file_flags(processed):
    root, *_ = processed
    v = pl.read_parquet(root / "validated" / "DIRTY" / "*.parquet")
    assert v.height == 9  # every DIRTY row is an exception (the clean 09:15 bar is duplicated)
    assert v["f_duplicate"].sum() == 2
    assert v["f_high_lt_low"].sum() == 1
    assert v["f_neg_volume"].sum() == 1
    assert v["f_nonpos_price"].sum() == 1
    assert v["f_ohlc_inconsistent"].sum() >= 2  # high<low row and close>high row
    sess = dict(v.group_by("session").len().iter_rows())
    assert sess["PRE_MARKET"] == 1 and sess["POST_MARKET"] == 1 and sess["WEEKEND"] == 1


def test_dirty_file_canonical(processed):
    root, *_ = processed
    c = pl.read_parquet(root / "canonical" / "DIRTY.parquet")
    # only the clean 09:15 bar survives (its duplicate removed)
    assert c.height == 1
    assert str(c["ts"][0].time()) == "09:15:00"
    assert c.schema["ts"] == pl.Datetime("us", "Asia/Kolkata")


def test_manifest(processed):
    _, _, _, m = processed
    assert m["symbol_count"] == 5
    assert m["row_count"] == 4 * 5 * 375 + 1
    assert m["dataset_version"].startswith("canonical-v1-")
    assert len(m["source_hash"]) == 64


def test_discovery(tmp_path):
    raw = tmp_path / "raw"
    write_raw(raw)
    m = discovery.discover(raw, tmp_path / "reports")
    assert m["file_count"] == 5 and m["row_count"] == 4 * 1875 + 9
    assert m["by_frequency"]["minute"]["symbol_count"] == 5
    assert (tmp_path / "reports" / "data_inventory.md").exists()


def _write_shards(raw):
    """Two HF-style shards: several symbols per file, tz-aware UTC timestamps, plus a daily file."""
    (raw / "minute").mkdir(parents=True)
    (raw / "day").mkdir(parents=True)
    start = datetime(2024, 1, 1, 3, 45, tzinfo=UTC)  # 09:15 IST
    for shard, syms in enumerate((["AAA", "BBB", "CCC"], ["CCC", "DDD", "NIFTY_50"])):
        rows = [
            {
                "symbol": s,
                "timestamp": start + timedelta(minutes=k),
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 100,
                "oi": 0,
            }
            for s in syms
            for k in range(375)
            if not (s == "CCC" and (k < 200) == bool(shard))  # CCC split across the two shards
        ]
        rows.append({**rows[0], "timestamp": start + timedelta(hours=9)})  # 18:15 IST: post-market
        pl.DataFrame(rows).write_parquet(raw / "minute" / f"train-{shard:05d}.parquet")
    daily = [
        {
            "symbol": s,
            "timestamp": datetime(2024, 1, d, 18, 30, tzinfo=UTC),  # midnight IST next day
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 1000,
            "oi": 0,
        }
        for s in ("AAA", "DDD")
        for d in range(1, 11)
    ]
    pl.DataFrame(daily).write_parquet(raw / "day" / "train-00000.parquet")


def test_sharded_utc_parquet(tmp_path):
    raw = tmp_path / "raw"
    _write_shards(raw)
    m = pipeline.run(raw, tmp_path)
    assert m["symbol_count"] == 5 and m["row_count"] == 5 * 375
    a = pl.read_parquet(tmp_path / "canonical" / "AAA.parquet")
    assert a.schema["ts"] == pl.Datetime("us", "Asia/Kolkata")
    assert str(a["ts"][0].time()) == "09:15:00" and str(a["ts"][-1].time()) == "15:29:00"
    c = pl.read_parquet(tmp_path / "canonical" / "CCC.parquet")
    assert c.height == 375 and c["ts"].is_sorted()
    assert "CCC" in next(f for f in m["files"] if f["source_id"] == "minute_train-00001")["symbol_collisions"]
    assert m["daily"]["rows"] == 20 and m["daily"]["symbols"] == 2
    d = pl.read_parquet(tmp_path / "canonical_daily" / "*.parquet")
    assert str(d["trade_date"].min()) == "2024-01-02" and set(d["session"]) == {"DAY"}
    shard = next(f for f in m["files"] if f["source_id"] == "minute_train-00000")
    assert shard["dropped_non_regular"] == 1 and shard["frequency"] == "minute"
    # small batches give the same answer as one batch
    (tmp_path / "c2").mkdir()
    small = pipeline.process_file(
        raw / "minute" / "train-00000.parquet", tmp_path / "v2", tmp_path / "c2", batch_size=1
    )
    assert small["canonical_rows"] == shard["canonical_rows"]
    assert small["raw"]["rows"] == shard["raw"]["rows"]


def test_discovery_shards(tmp_path):
    raw = tmp_path / "raw"
    _write_shards(raw)
    m = discovery.discover(raw, tmp_path / "reports", hash_files=False)
    mb = m["by_frequency"]["minute"]
    assert mb["symbol_count"] == 5 and mb["symbols_in_several_files"] == ["CCC"]
    assert mb["session_counts"]["POST_MARKET"] == 2
    assert m["by_frequency"]["day"]["row_count"] == 20
