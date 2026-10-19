from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
import pytest

from pulsetrader.backtest.engine import (
    ZERO_COSTS,
    BacktestConfig,
    Bars,
    CostConfig,
    metrics,
    plan_trades,
    simulate,
)
from pulsetrader.experiments.backtest import choose_gate, round_trip_bp

IST = ZoneInfo("Asia/Kolkata")
T0 = datetime(2025, 1, 6, 9, 15, tzinfo=IST)


def _bars(closes: list[float], day: date = date(2025, 1, 6), start: datetime = T0) -> pl.DataFrame:
    n = len(closes)
    c = np.array(closes, dtype=float)
    o = np.r_[c[0], c[:-1]]  # open = previous close
    return pl.DataFrame(
        {
            "ts": [start + timedelta(minutes=i) for i in range(n)],
            "trade_date": [day] * n,
            "open": o,
            "high": np.maximum(o, c) + 0.05,
            "low": np.minimum(o, c) - 0.05,
            "close": c,
        }
    )


def test_order_cost_components():
    c = CostConfig()
    buy = c.order_cost(100_000, "buy")
    sell = c.order_cost(100_000, "sell")
    brokerage = 20.0  # 3 bp of 1 lakh = 30, capped at 20
    exch, sebi = 100_000 * 0.297e-4, 100_000 * 0.01e-4
    gst = 0.18 * (brokerage + exch + sebi)
    assert np.isclose(buy, brokerage + exch + sebi + gst + 3.0)  # stamp 0.3 bp
    assert np.isclose(sell, brokerage + exch + sebi + gst + 25.0)  # STT 2.5 bp
    assert ZERO_COSTS.order_cost(1e6, "sell") == 0
    assert round_trip_bp(c, 100_000) == pytest.approx(1e4 * (buy + sell) / 1e5 + 2.0)


def test_plan_trades_uses_next_open_and_horizon_close():
    df = _bars([100, 101, 102, 103, 104, 105, 106, 107])
    bars = {"A": Bars.from_frame(df)}
    sig = pl.DataFrame({"symbol": ["A"], "ts": [T0 + timedelta(minutes=1)], "direction": [1]})
    cfg = BacktestConfig(horizon=2, costs=ZERO_COSTS)
    t = plan_trades(sig, bars, cfg).row(0, named=True)
    assert t["entry_px"] == 101  # open of bar 2 = close of bar 1 (signal bar)
    assert t["exit_px"] == 103  # close of bar 1 + 2
    assert t["exit_reason"] == "horizon"
    us = int((T0 + timedelta(minutes=4)).timestamp() * 1e6)  # close of bar 3 = start of bar 4
    assert t["exit_us"] == us


def test_plan_trades_session_close_and_stop():
    df = _bars([100, 100, 100, 99, 98])
    bars = {"A": Bars.from_frame(df)}
    sig = pl.DataFrame({"symbol": ["A"], "ts": [T0 + timedelta(minutes=2)], "direction": [1]})
    t = plan_trades(sig, bars, BacktestConfig(horizon=30, costs=ZERO_COSTS)).row(0, named=True)
    assert t["exit_reason"] == "session_close" and t["exit_px"] == 98
    cfg = BacktestConfig(horizon=30, stop_loss_bp=50, costs=ZERO_COSTS)
    t = plan_trades(sig, bars, cfg).row(0, named=True)
    assert t["exit_reason"] == "stop_loss" and np.isclose(t["exit_px"], 100 * (1 - 0.005))
    # the last bar of the day has no next bar: no trade
    late = pl.DataFrame({"symbol": ["A"], "ts": [T0 + timedelta(minutes=4)], "direction": [1]})
    assert plan_trades(late, bars, BacktestConfig(costs=ZERO_COSTS)).height == 0


def test_simulate_constraints_and_pnl():
    df = _bars([100, 100, 110, 110, 110, 110])
    bars = {s: Bars.from_frame(df) for s in ("A", "B", "C")}
    ts = T0
    sig = pl.DataFrame(
        {
            "symbol": ["A", "A", "B", "C"],
            "ts": [ts, ts + timedelta(minutes=1), ts, ts],
            "direction": [1, 1, -1, 1],
            "priority": [0.9, 0.9, 0.8, 0.1],
        }
    )
    cfg = BacktestConfig(capital=1000, position_frac=0.5, max_positions=2, horizon=3, costs=ZERO_COSTS)
    trades = plan_trades(sig, bars, cfg)
    sim = simulate(trades, cfg)
    assert sim["skipped"]["book_full"] == 1  # C has the lowest priority
    assert sim["skipped"]["symbol_held"] == 1  # second A while A is open
    pnl = {t["symbol"]: t["pnl"] for t in sim["trades"]}
    assert np.isclose(pnl["A"], 50)  # long 500 at 100 -> 110
    assert np.isclose(pnl["B"], -50)  # short 500 at 100 -> 110
    m = metrics(sim, cfg, [int(df["trade_date"].cast(pl.Int32)[0])])
    assert m["trades"] == 2 and m["total_return"] == pytest.approx(0.0)
    assert m["win_rate"] == 0.5 and m["profit_factor"] == pytest.approx(1.0)


def test_costs_reduce_pnl():
    df = _bars([100, 100, 101, 101])
    bars = {"A": Bars.from_frame(df)}
    sig = pl.DataFrame({"symbol": ["A"], "ts": [T0], "direction": [1]})
    out = {}
    for name, costs in (("zero", ZERO_COSTS), ("real", CostConfig())):
        cfg = BacktestConfig(horizon=2, costs=costs)
        out[name] = simulate(plan_trades(sig, bars, cfg), cfg)["trades"][0]
    assert out["real"]["pnl"] < out["zero"]["pnl"]
    assert out["real"]["costs"] > 0 and out["zero"]["costs"] == 0


def test_choose_gate_prefers_profitable_confident_calls():
    rng = np.random.default_rng(1)
    n = 4000
    conf = rng.uniform(0.34, 0.8, n)
    P = np.column_stack([1 - conf, np.zeros(n), conf])
    P[:, 1] = 0.0
    fret = np.where(conf > 0.6, 0.002, -0.0005)  # only confident UP calls make money
    g = choose_gate(P, fret, cost_bp=5.0)["chosen"]
    assert g["gate"] >= 0.6 and g["net_bp_per_call"] > 0


def test_backtest_runner_on_golden(golden_dataset, tmp_path):
    from pulsetrader.experiments import optimize as opt
    from pulsetrader.experiments.backtest import backtest, render_summary

    dev = opt.load_dev(golden_dataset, 5, (0.001,), dataset="ds", n_pre=1, min_train_frac=0.67,
                       embargo_minutes=15, train_every=5)  # fmt: skip
    r = opt.walk_forward(dev, tmp_path / "exp", "y_5m_10bp")
    d = tmp_path / "exp" / r["experiment"]["experiment_id"]
    res = backtest(d, golden_dataset, tmp_path / "exp", dataset="ds")
    keys = set(res["result"])
    for s in ("model", "model_gated", "momentum", "naive_random", "naive_long", "buy_and_hold"):
        assert {f"{s}|costs", f"{s}|zero_costs"} <= keys
    m, z = res["result"]["model|costs"], res["result"]["model|zero_costs"]
    assert m["trades"] == 0 or m["total_costs"] > 0
    assert z["total_costs"] == 0
    assert res["experiment"]["test_period"]["used"] is False
    assert "Phase 12" in render_summary([res])
