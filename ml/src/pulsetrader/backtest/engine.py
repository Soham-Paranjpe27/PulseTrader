"""Event-driven intraday backtester (Phase 12).

Timing (no future information is used to decide or execute):
- A signal at bar t is known after bar t closes (features use bar t's close).
- Entry: open of bar t+1. Exit: close of bar t+horizon, or earlier if a stop-loss / take-profit
  level is touched by a bar's low/high in between (if both are touched in the same bar, the stop is
  assumed first). Every position is squared off at the last bar of the trading day.
- Fills are adjusted by `slippage_bp` against the trader on both sides.

Portfolio: event loop over entries and exits in time order. One open position per symbol, at most
`max_positions` at once, each sized at `position_frac` of current equity (long or short; intraday
shorting is allowed in Indian cash equities). An entry is skipped when its symbol is already held,
the book is full, or there is not enough free capital.

Costs: `CostConfig` holds Indian intraday-equity charges. The defaults are illustrative values for a
discount broker and must be checked against current broker and exchange rates before relying on them.
"""

from __future__ import annotations

import heapq
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

import numpy as np
import polars as pl


@dataclass(frozen=True)
class CostConfig:
    brokerage_bp: float = 3.0  # 0.03% per order ...
    brokerage_cap_inr: float = 20.0  # ... capped at Rs 20 per order
    stt_sell_bp: float = 2.5  # 0.025% on the sell side (intraday)
    exchange_bp: float = 0.297  # NSE transaction charge, both sides
    sebi_bp: float = 0.01  # Rs 10 per crore, both sides
    stamp_buy_bp: float = 0.3  # 0.003% on the buy side
    gst_rate: float = 0.18  # on brokerage + exchange + SEBI charges
    slippage_bp: float = 1.0  # per side, applied to the fill price

    def order_cost(self, notional: float, side: str) -> float:
        """Charges in rupees for one order (excluding slippage, which is in the fill price)."""
        brokerage = min(notional * self.brokerage_bp / 1e4, self.brokerage_cap_inr)
        exchange = notional * self.exchange_bp / 1e4
        sebi = notional * self.sebi_bp / 1e4
        gst = self.gst_rate * (brokerage + exchange + sebi)
        stt = notional * self.stt_sell_bp / 1e4 if side == "sell" else 0.0
        stamp = notional * self.stamp_buy_bp / 1e4 if side == "buy" else 0.0
        return brokerage + exchange + sebi + gst + stt + stamp


ZERO_COSTS = CostConfig(0, 0, 0, 0, 0, 0, 0, 0)


@dataclass
class BacktestConfig:
    capital: float = 1_000_000.0
    position_frac: float = 0.10
    max_positions: int = 10
    horizon: int = 5  # bars (minutes)
    stop_loss_bp: float | None = None
    take_profit_bp: float | None = None
    costs: CostConfig = field(default_factory=CostConfig)


@dataclass
class Bars:
    """Minute bars for one symbol as numpy arrays (sorted by ts)."""

    ts: np.ndarray  # int64 microseconds
    day: np.ndarray  # int32 day ordinal
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray

    @classmethod
    def from_frame(cls, df: pl.DataFrame) -> Bars:
        df = df.sort("ts")
        return cls(
            ts=df["ts"].dt.epoch("us").to_numpy(),
            day=df["trade_date"].cast(pl.Int32).to_numpy(),
            open=df["open"].to_numpy().astype(float),
            high=df["high"].to_numpy().astype(float),
            low=df["low"].to_numpy().astype(float),
            close=df["close"].to_numpy().astype(float),
        )


def plan_trades(signals: pl.DataFrame, bars: dict[str, Bars], cfg: BacktestConfig) -> pl.DataFrame:
    """Entry/exit time and price of every signal on its own (before portfolio constraints).

    signals: symbol, ts (bar start, tz-aware), direction (+1 long / -1 short) and optionally
    priority (higher is taken first when several entries share a bar and the book is nearly full)."""
    rows: list[tuple[Any, ...]] = []
    slip = cfg.costs.slippage_bp / 1e4
    for (sym,), g in signals.group_by("symbol"):
        b = bars.get(str(sym))
        if b is None:
            continue
        sig_ts = g["ts"].dt.epoch("us").to_numpy()
        dirs = g["direction"].to_numpy()
        prio = g["priority"].to_numpy() if "priority" in g.columns else np.zeros(len(g))
        pos = np.searchsorted(b.ts, sig_ts)
        for i, p in enumerate(pos):
            if p >= len(b.ts) or b.ts[p] != sig_ts[i]:
                continue  # signal bar not in the bar data
            e = p + 1
            if e >= len(b.ts) or b.day[e] != b.day[p]:
                continue  # no next bar in the same session
            d = int(dirs[i])
            entry = b.open[e] * (1 + slip * d)
            last = p + cfg.horizon
            day_end = int(np.searchsorted(b.day, b.day[p], side="right")) - 1
            x, reason = min(last, day_end), "horizon" if last <= day_end else "session_close"
            exit_px = b.close[x]
            if cfg.stop_loss_bp or cfg.take_profit_bp:
                sl = entry * (1 - d * cfg.stop_loss_bp / 1e4) if cfg.stop_loss_bp else None
                tp = entry * (1 + d * cfg.take_profit_bp / 1e4) if cfg.take_profit_bp else None
                for k in range(e, x + 1):
                    lo, hi = b.low[k], b.high[k]
                    hit_sl = sl is not None and (lo <= sl if d > 0 else hi >= sl)
                    hit_tp = tp is not None and (hi >= tp if d > 0 else lo <= tp)
                    if hit_sl:
                        x, exit_px, reason = k, float(sl), "stop_loss"  # type: ignore[arg-type]
                        break
                    if hit_tp:
                        x, exit_px, reason = k, float(tp), "take_profit"  # type: ignore[arg-type]
                        break
            exit_fill = exit_px * (1 - slip * d)
            rows.append((str(sym), int(sig_ts[i]), int(b.ts[e]), int(b.ts[x]) + 60_000_000, int(b.day[p]), d,
                         float(entry), float(exit_fill), reason, float(prio[i])))  # fmt: skip
    schema = [
        "symbol",
        "signal_us",
        "entry_us",
        "exit_us",
        "day",
        "direction",
        "entry_px",
        "exit_px",
        "exit_reason",
        "priority",
    ]
    if not rows:
        return pl.DataFrame(schema=dict.fromkeys(schema, pl.Int64))
    out = pl.DataFrame(rows, schema=schema, orient="row")
    return out.sort(["entry_us", "priority", "symbol"], descending=[False, True, False])


def simulate(trades: pl.DataFrame, cfg: BacktestConfig) -> dict[str, Any]:
    """Run the portfolio event loop over planned trades."""
    cash = cfg.capital
    open_pos: dict[str, dict[str, Any]] = {}
    exits: list[tuple[int, str]] = []  # heap of (exit_us, symbol)
    done: list[dict[str, Any]] = []
    skipped = {"symbol_held": 0, "book_full": 0, "no_capital": 0}
    day_equity: dict[int, float] = {}
    notional_time = 0.0

    def equity_now() -> float:
        return cash + sum(p["margin"] for p in open_pos.values())

    def close(sym: str) -> None:
        nonlocal cash, notional_time
        p = open_pos.pop(sym)
        qty, d = p["qty"], p["direction"]
        exit_notional = qty * p["exit_px"]
        side = "sell" if d > 0 else "buy"
        c = cfg.costs.order_cost(exit_notional, side)
        pnl = d * qty * (p["exit_px"] - p["entry_px"]) - p["entry_cost"] - c
        cash += p["margin"] + pnl
        notional_time += p["weight"] * (p["exit_us"] - p["entry_us"]) / 60e6
        done.append({**{k: p[k] for k in ("symbol", "direction", "entry_us", "exit_us", "entry_px", "exit_px",
                                          "exit_reason", "qty", "margin", "weight")},
                     "costs": p["entry_cost"] + c, "pnl": pnl, "return": pnl / p["margin"]})  # fmt: skip
        day_equity[p["day"]] = cash + sum(q["margin"] for q in open_pos.values())

    for t in trades.iter_rows(named=True):
        while exits and exits[0][0] <= t["entry_us"]:
            _, s = heapq.heappop(exits)
            close(s)
        if t["symbol"] in open_pos:
            skipped["symbol_held"] += 1
            continue
        if len(open_pos) >= cfg.max_positions:
            skipped["book_full"] += 1
            continue
        eq_now = equity_now()
        margin = eq_now * cfg.position_frac
        side = "buy" if t["direction"] > 0 else "sell"
        entry_cost = cfg.costs.order_cost(margin, side)
        if margin + entry_cost > cash or margin <= 0:
            skipped["no_capital"] += 1
            continue
        cash -= margin
        open_pos[t["symbol"]] = {
            **t,
            "qty": margin / t["entry_px"],
            "margin": margin,
            "entry_cost": entry_cost,
            "weight": margin / eq_now,
        }
        heapq.heappush(exits, (t["exit_us"], t["symbol"]))
    while exits:
        _, s = heapq.heappop(exits)
        close(s)
    return {"trades": done, "skipped": skipped, "day_equity": day_equity, "notional_minutes": notional_time}


def metrics(
    sim: dict[str, Any], cfg: BacktestConfig, days: list[int], session_minutes: int = 375
) -> dict[str, Any]:
    """Portfolio metrics from daily closing equity over every trading day in `days`."""
    eq = []
    last = cfg.capital
    for d in sorted(days):
        last = sim["day_equity"].get(d, last)
        eq.append(last)
    eq_a = np.array([cfg.capital, *eq])
    r = eq_a[1:] / eq_a[:-1] - 1
    n_days = len(days)
    years = n_days / 252
    total = eq_a[-1] / cfg.capital - 1
    peak = np.maximum.accumulate(eq_a)
    dd = eq_a / peak - 1
    max_dd = float(np.min(dd))
    std = r.std(ddof=1) if len(r) > 1 else 0.0
    downside = r[r < 0]
    dstd = np.sqrt(np.mean(downside**2)) if len(downside) else 0.0
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else -1.0
    tr = sim["trades"]
    pnl = np.asarray([t["pnl"] for t in tr], dtype=np.float64)
    rets = np.asarray([t["return"] for t in tr], dtype=np.float64)
    traded = sum(2 * t["weight"] for t in tr)  # as a fraction of equity at entry
    return {
        "days": n_days,
        "start_equity": cfg.capital,
        "end_equity": float(eq_a[-1]),
        "total_return": float(total),
        "cagr": float(cagr),
        "sharpe": float(r.mean() / std * np.sqrt(252)) if std > 0 else None,
        "sortino": float(r.mean() / dstd * np.sqrt(252)) if dstd > 0 else None,
        "calmar": float(cagr / abs(max_dd)) if max_dd < 0 else None,
        "max_drawdown": max_dd,
        "trades": len(tr),
        "win_rate": float(np.mean(pnl > 0)) if len(pnl) else None,
        "profit_factor": float(np.sum(pnl[pnl > 0]) / -np.sum(pnl[pnl < 0])) if (pnl < 0).any() else None,
        "avg_trade_return_bp": float(rets.mean() * 1e4) if len(rets) else None,
        "median_trade_return_bp": float(np.median(rets) * 1e4) if len(rets) else None,
        "total_costs": float(sum(t["costs"] for t in tr)),
        "gross_pnl": float(pnl.sum() + sum(t["costs"] for t in tr)),
        "net_pnl": float(pnl.sum()),
        "turnover_per_day": float(traded / n_days) if n_days else None,
        "exposure": float(sim["notional_minutes"] / (session_minutes * n_days)) if n_days else None,
        "skipped": sim["skipped"],
        "exit_reasons": {
            k: int(v)
            for k, v in zip(*np.unique([t["exit_reason"] for t in tr], return_counts=True), strict=True)
        }
        if tr
        else {},
    }


def buy_and_hold(
    day_bars: pl.DataFrame, symbols: list[str], start: date, end: date, cfg: BacktestConfig
) -> dict[str, Any]:
    """Equal-weight buy at the first open, hold to the last close (daily marks); costs on both trades."""
    d = day_bars.filter(pl.col("symbol").is_in(symbols) & pl.col("trade_date").is_between(start, end)).sort(
        "trade_date"
    )
    wide = (
        d.pivot(on="symbol", index="trade_date", values="close")
        .sort("trade_date")
        .fill_null(strategy="forward")
    )
    first_open = d.group_by("symbol").agg(pl.col("open").first())
    syms = [s for s in symbols if s in wide.columns]
    per = cfg.capital / len(syms)
    opens = dict(zip(first_open["symbol"], first_open["open"], strict=True))
    buy_cost = sum(cfg.costs.order_cost(per, "buy") for _ in syms)
    qty = {s: per * (1 - cfg.costs.slippage_bp / 1e4) / opens[s] for s in syms}
    eq = np.array(
        [
            sum(qty[s] * (row[s] if row[s] is not None else opens[s]) for s in syms)
            for row in wide.iter_rows(named=True)
        ]
    )
    eq = eq - buy_cost
    slip_out = sum(qty[s] * wide[s][-1] * cfg.costs.slippage_bp / 1e4 for s in syms)
    eq[-1] -= slip_out + sum(cfg.costs.order_cost(qty[s] * wide[s][-1], "sell") for s in syms)
    fake = {"trades": [], "skipped": {}, "day_equity": dict(enumerate(eq)), "notional_minutes": 0.0}
    m = metrics(fake, cfg, list(range(len(eq))))
    m["exposure"] = 1.0
    m["trades"] = 2 * len(syms)
    m["total_costs"] = float(buy_cost + _sell_cost(cfg, qty, wide, syms))
    return m


def _sell_cost(cfg: BacktestConfig, qty: dict[str, float], wide: pl.DataFrame, syms: list[str]) -> float:
    return float(sum(cfg.costs.order_cost(qty[s] * wide[s][-1], "sell") for s in syms))


def describe(cfg: BacktestConfig) -> dict[str, Any]:
    return asdict(cfg)
