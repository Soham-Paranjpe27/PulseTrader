from datetime import date, datetime, timedelta

import polars as pl

from pulsetrader.security import master
from pulsetrader.security.master import EQUITY, ETF, INDEX, OTHER, classify


def test_classify():
    assert classify("NIFTY", 1.0)[0] == INDEX
    assert classify("NIFTY BANK", 1.0)[0] == INDEX
    assert classify("NIFTYBEES", 0.0)[0] == ETF
    assert classify("GOLDBND", 0.0)[0] == OTHER
    assert classify("RELIANCE", 0.0)[0] == EQUITY
    assert classify("NIFTYNEWINDEX", 1.0)[0] == INDEX  # NIFTY-prefixed, never traded
    assert classify("SKYGOLD", 0.0)[0] == EQUITY  # equity whose name contains GOLD


def _write_symbol(cdir, sym, days, price_fn, volume=100.0):
    rows = []
    for di, d in enumerate(days):
        for k in range(10):
            ts = datetime(d.year, d.month, d.day, 9, 15) + timedelta(minutes=k)
            p = price_fn(di, k)
            rows.append(
                {
                    "symbol": sym,
                    "ts": ts,
                    "open": p,
                    "high": p,
                    "low": p,
                    "close": p,
                    "volume": volume,
                    "trade_date": d,
                }
            )
    pl.DataFrame(rows).with_columns(pl.col("ts").dt.replace_time_zone("Asia/Kolkata")).write_parquet(
        cdir / f"{sym}.parquet"
    )


def test_build(tmp_path):
    cdir = tmp_path / "canonical"
    cdir.mkdir()
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(20)]
    _write_symbol(cdir, "AAA", days, lambda d, k: 100.0)
    # unadjusted 1:2 split on day 10: price halves overnight
    _write_symbol(cdir, "SPLT", days, lambda d, k: 200.0 if d < 10 else 100.0)
    # intraday jump of 50% at minute 5 on day 3
    _write_symbol(cdir, "JUMP", days, lambda d, k: 150.0 if (d == 3 and k == 5) else 100.0)
    _write_symbol(cdir, "NIFTY", days, lambda d, k: 20000.0, volume=0.0)
    # OLD stops on day 9, NEW starts on day 10 at the same price: a rename candidate
    _write_symbol(cdir, "OLD", days[:10], lambda d, k: 50.0)
    _write_symbol(cdir, "NEW", days[10:], lambda d, k: 50.0)
    s = master.build(
        cdir,
        tmp_path / "ref",
        tmp_path / "reports",
        master.Eligibility(min_days=15, min_median_daily_turnover=0),
    )
    assert s["symbols"] == 6 and s["by_type"] == {"EQUITY": 5, "INDEX": 1}
    m = pl.read_parquet(tmp_path / "ref" / "security_master.parquet")
    elig = set(m.filter("experiment_eligible")["symbol"])
    assert elig == {"AAA", "SPLT", "JUMP"}  # OLD/NEW too short, NIFTY is an index
    ev = pl.read_parquet(tmp_path / "ref" / "corporate_action_events.parquet")
    g = ev.filter(pl.col("symbol") == "SPLT")
    assert g.height == 1 and g["kind"][0] == "OVERNIGHT_GAP" and g["trade_date"][0] == days[10]
    assert g["ratio_match"][0] == "split/bonus 2:1"
    assert ev.filter(pl.col("symbol") == "JUMP")["kind"].to_list() == ["INTRADAY_JUMP"]
    h = pl.read_parquet(tmp_path / "ref" / "symbol_history.parquet")
    assert h.filter(pl.col("symbol") == "NEW")["rename_candidate_of"][0] == "OLD"
    assert dict(h.select("symbol", "status").iter_rows())["OLD"] == "ENDED"
    assert (tmp_path / "reports" / "corporate_action_audit.md").exists()
    d = pl.read_parquet(tmp_path / "ref" / "day_bars.parquet")
    f = master.flagged_days(ev, d)
    assert f.filter(pl.col("symbol") == "SPLT")["trade_date"].to_list() == [days[10], days[11]]
    assert f.filter(pl.col("symbol") == "JUMP").is_empty()
    assert d.height == 20 * 4 + 20 and d["bars"].unique().to_list() == [10]
