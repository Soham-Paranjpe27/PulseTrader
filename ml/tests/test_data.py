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
    v = pl.read_parquet(root / "validated" / "DIRTY.parquet")
    assert v.height == 9  # validated keeps every raw row
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
    assert (tmp_path / "reports" / "data_inventory.md").exists()
