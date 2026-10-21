"""Phase 12 runner: portfolio backtests of walk-forward predictions on the validation period.

Signals come from Phase 9 walk-forward predictions of the validation fold (out-of-sample for the
model). Strategies, all traded by the same engine and costs:
- model: every UP/DOWN argmax call (long on UP, short on DOWN), priority = P(direction);
- model_gated: only calls whose P(direction) clears a gate chosen on the pre-validation folds
  (best mean per-call return after the round-trip cost, at least 0.5% coverage);
- momentum: the class of the past h-minute return with the label threshold (Phase 7 baseline);
- naive_random: same signal times as `model`, direction from a fixed-seed coin flip;
- naive_long: same signal times as `model`, always long;
- buy_and_hold: equal-weight buy of the universe at the first validation open, sell at the last close.
Each runs with Indian intraday costs and with zero costs. Bars are read for the validation dates only;
the test period is not read.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from pulsetrader.backtest.engine import (
    ZERO_COSTS,
    BacktestConfig,
    Bars,
    CostConfig,
    buy_and_hold,
    describe,
    metrics,
    plan_trades,
    simulate,
)
from pulsetrader.eval.multiclass import DOWN, UP
from pulsetrader.experiments.classical import MOMENTUM_COL, _new_dir
from pulsetrader.models.classical import momentum_classes

RUNNER_VERSION = "backtest-v1"
GATE_GRID = tuple(np.round(np.arange(0.34, 0.71, 0.02), 2))
MIN_GATE_COVERAGE = 0.005


def round_trip_bp(costs: CostConfig, notional: float) -> float:
    """Charges plus slippage of a buy and a sell of `notional`, in basis points of notional."""
    charges = costs.order_cost(notional, "buy") + costs.order_cost(notional, "sell")
    return 1e4 * charges / notional + 2 * costs.slippage_bp


def choose_gate(proba: np.ndarray, fret: np.ndarray, cost_bp: float) -> dict[str, Any]:
    """Gate on P(direction) with the best mean per-call return net of `cost_bp` (pre-validation rows)."""
    pred = proba.argmax(axis=1)
    p_dir = np.maximum(proba[:, UP], proba[:, DOWN])
    sign = np.where(pred == UP, 1.0, np.where(pred == DOWN, -1.0, 0.0))
    rows = []
    for g in GATE_GRID:
        m = (sign != 0) & (p_dir >= g)
        cov = float(m.mean())
        if cov < MIN_GATE_COVERAGE:
            continue
        net = float(np.mean(sign[m] * fret[m]) * 1e4 - cost_bp)
        rows.append({"gate": float(g), "coverage": cov, "net_bp_per_call": net})
    best = max(rows, key=lambda r: r["net_bp_per_call"]) if rows else {"gate": 1.0}
    return {"chosen": best, "grid": rows}


def _signals(frame: pl.DataFrame, direction: np.ndarray, priority: np.ndarray) -> pl.DataFrame:
    s = frame.select("symbol", "ts").with_columns(
        pl.Series("direction", direction.astype(np.int64)), pl.Series("priority", priority.astype(float))
    )
    return s.filter(pl.col("direction") != 0)


def load_bars(data_root: Path, symbols: list[str], start: date, end: date) -> dict[str, Bars]:
    bars = {}
    for s in symbols:
        f = data_root / "canonical" / f"{s}.parquet"
        if not f.exists():
            continue
        df = (
            pl.scan_parquet(f)
            .filter(pl.col("trade_date").is_between(start, end) & (pl.col("session") == "REGULAR"))
            .select("ts", "trade_date", "open", "high", "low", "close")
            .collect()
        )
        if df.height:
            bars[s] = Bars.from_frame(df)
    return bars


def backtest(wf_dir: Path, data_root: Path, out_root: Path, dataset: str = "core100_s5") -> dict[str, Any]:
    exp_in = json.loads((wf_dir / "experiment.json").read_text())
    c_in = exp_in["config"]
    h, thr, label = int(c_in["horizon"]), float(c_in["threshold"]), c_in["label"]
    v_start = date.fromisoformat(exp_in["validation_period"]["start"])
    v_end = date.fromisoformat(exp_in["validation_period"]["end"])
    preds = pl.read_parquet(wf_dir / "predictions.parquet")
    folds = sorted(preds["fold"].unique().to_list(), key=lambda s: int(s[1:]))
    val_f = folds[-1]
    pre = preds.filter(pl.col("fold") != val_f)
    val = preds.filter(pl.col("fold") == val_f).sort("ts", "symbol")
    mom_col = MOMENTUM_COL[h]
    extra = (
        pl.scan_parquet(data_root / "datasets" / dataset / "part-*.parquet")
        .filter(pl.col("split") == "validation")
        .select("symbol", "ts", mom_col)
        .collect()
    )
    val = val.join(extra, on=["symbol", "ts"], how="left")

    base = BacktestConfig(horizon=h)
    notional = base.capital * base.position_frac
    cost_bp = round_trip_bp(base.costs, notional)
    P_pre = pre.select("p_down", "p_neutral", "p_up").to_numpy().astype(np.float64)
    gate = choose_gate(P_pre, pre["fret"].to_numpy().astype(np.float64), cost_bp)
    g = float(gate["chosen"]["gate"])

    P = val.select("p_down", "p_neutral", "p_up").to_numpy().astype(np.float64)
    pred = P.argmax(axis=1)
    p_dir = np.maximum(P[:, UP], P[:, DOWN])
    model_dir = np.where(pred == UP, 1, np.where(pred == DOWN, -1, 0))
    past = val[mom_col].to_numpy().astype(np.float64)
    mom = momentum_classes(np.nan_to_num(past, nan=0.0), thr)
    mom_dir = np.where(mom == UP, 1, np.where(mom == DOWN, -1, 0))
    rng = np.random.default_rng(0)
    coin = np.where(rng.random(len(val)) < 0.5, 1, -1)
    strategies = {
        "model": (model_dir, p_dir),
        "model_gated": (np.where(p_dir >= g, model_dir, 0), p_dir),
        "momentum": (mom_dir, np.abs(np.nan_to_num(past))),
        "naive_random": (np.where(model_dir != 0, coin, 0), p_dir),
        "naive_long": (np.where(model_dir != 0, 1, 0), p_dir),
    }

    symbols = sorted(val["symbol"].unique().to_list())
    bars = load_bars(data_root, symbols, v_start, v_end)
    days = sorted({int(d) for b in bars.values() for d in np.unique(b.day)})
    results: dict[str, Any] = {}
    for name, (direction, prio) in strategies.items():
        sig = _signals(val, direction, prio)
        for cname, costs in (("costs", base.costs), ("zero_costs", ZERO_COSTS)):
            cfg = BacktestConfig(horizon=h, costs=costs)
            trades = plan_trades(sig, bars, cfg)
            sim = simulate(trades, cfg)
            m = metrics(sim, cfg, days)
            m["signals"] = sig.height
            results[f"{name}|{cname}"] = m
    day_bars = pl.read_parquet(data_root / "reference" / "day_bars.parquet")
    for cname, costs in (("costs", base.costs), ("zero_costs", ZERO_COSTS)):
        results[f"buy_and_hold|{cname}"] = buy_and_hold(
            day_bars, symbols, v_start, v_end, BacktestConfig(horizon=h, costs=costs)
        )

    cfg_out = {
        "step": "backtest",
        "source_experiment": wf_dir.name,
        "label": label,
        "model": c_in["model"],
        "tag": c_in["tag"],
        "horizon": h,
        "threshold": thr,
        "engine": describe(base),
        "round_trip_cost_bp": cost_bp,
        "gate": gate,
        "period": {"start": str(v_start), "end": str(v_end), "fold": val_f},
    }
    key = hashlib.sha1(json.dumps(cfg_out, sort_keys=True, default=str).encode()).hexdigest()[:8]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    d = _new_dir(out_root, f"{stamp}-p12-backtest-{cfg_out['model']}-{label}-{cfg_out['tag']}-{key}")
    exp = {
        "experiment_id": d.name,
        "runner_version": RUNNER_VERSION,
        "phase": 12,
        **{
            k: exp_in[k]
            for k in ("dataset_id", "dataset", "train_period", "validation_period", "test_period")
        },
        "config": cfg_out,
        "created_at": datetime.now(UTC).isoformat(),
    }
    (d / "experiment.json").write_text(json.dumps(exp, indent=2, default=str))
    (d / "config.json").write_text(json.dumps(cfg_out, indent=2, default=str))
    (d / "metrics.json").write_text(json.dumps(results, indent=2, default=str))
    (d / "report.md").write_text(render(exp, results))
    return {"experiment": exp, "result": results, "dir": str(d)}


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.2f}%"


def _num(x: float | None, nd: int = 2) -> str:
    return "–" if x is None else f"{x:.{nd}f}"


def table(results: dict[str, Any]) -> list[str]:
    lines = [
        "| Strategy | Costs | Trades | Total return | CAGR | Sharpe | Sortino | Calmar | Max DD | "
        "Win rate | Profit factor | Avg trade (bp) | Median trade (bp) | Costs paid (Rs) | "
        "Turnover/day | Exposure |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for k, m in results.items():
        name, c = k.split("|")
        lines.append(
            f"| {name} | {'yes' if c == 'costs' else 'no'} | {m['trades']:,} | {_pct(m['total_return'])} | "
            f"{_pct(m['cagr'])} | {_num(m['sharpe'])} | {_num(m['sortino'])} | {_num(m['calmar'])} | "
            f"{_pct(m['max_drawdown'])} | {_pct(m['win_rate'])} | {_num(m['profit_factor'])} | "
            f"{_num(m['avg_trade_return_bp'])} | {_num(m['median_trade_return_bp'])} | "
            f"{m['total_costs']:,.0f} | {_num(m['turnover_per_day'])} | {_pct(m['exposure'])} |"
        )
    return lines


def render(exp: dict[str, Any], res: dict[str, Any]) -> str:
    c = exp["config"]
    e = c["engine"]
    gate = c["gate"]["chosen"]
    lines = [
        f"# {exp['experiment_id']}",
        "",
        f"Backtest of {c['model']} ({c['tag']}) `{c['label']}` signals on validation "
        f"{c['period']['start']}..{c['period']['end']}. Test period not used.",
        "",
        f"Engine: capital Rs {e['capital']:,.0f}, {100 * e['position_frac']:.0f}% of equity per position, "
        f"at most {e['max_positions']} positions, hold {e['horizon']} min (squared off at session close), "
        f"entry at the next bar's open. Round-trip cost at Rs {e['capital'] * e['position_frac']:,.0f}: "
        f"{c['round_trip_cost_bp']:.1f} bp including slippage.",
        "",
        f"Gate for `model_gated` (chosen on pre-validation folds): P(direction) >= {gate['gate']:.2f} "
        f"(pre-validation coverage {_pct(gate.get('coverage'))}, "
        f"net {_num(gate.get('net_bp_per_call'))} bp per call).",
        "",
        *table(res),
        "",
    ]
    return "\n".join(lines)


def render_summary(rows: list[dict[str, Any]]) -> str:
    e0 = rows[0]["experiment"]
    lines = [
        "# Phase 12 — portfolio backtests (validation)",
        "",
        f"Dataset `{e0['dataset_id']}`. Signals: Phase 9 walk-forward predictions of the validation fold "
        f"({e0['validation_period']['start']}..{e0['validation_period']['end']}). Test period not used.",
        "Each strategy is traded by the same event-driven engine (`pulsetrader.backtest.engine`): entry at",
        "the next bar's open, exit at the close of the label horizon or the session close, one position",
        "per symbol, at most 10 positions of 10% of equity each, Indian intraday charges (brokerage capped",
        "at Rs 20, STT on sells, exchange, SEBI, stamp duty, GST) and 1 bp slippage per side. The charge",
        "rates are illustrative defaults and must be checked against current broker and exchange rates.",
        "",
    ]
    for r in rows:
        c = r["experiment"]["config"]
        g = c["gate"]["chosen"]
        lines += [
            f"## {c['model']} ({c['tag']}) — `{c['label']}`, hold {c['horizon']} min",
            "",
            f"Round-trip cost {c['round_trip_cost_bp']:.1f} bp. Gate chosen on pre-validation folds: "
            f"P(direction) >= {g['gate']:.2f}.",
            "",
            *table(r["result"]),
            "",
        ]
    return "\n".join(lines)


DEFAULT_INPUTS = ("wf-expanding-lightgbm-y_1m_5bp-tuned", "wf-expanding-lightgbm-y_5m_10bp-tuned")


def run(data_root: Path, out_root: Path, patterns: tuple[str, ...] = DEFAULT_INPUTS) -> list[dict[str, Any]]:
    rows = []
    for pat in patterns:
        hits = sorted(d for d in out_root.glob(f"*-p9-{pat}-*") if (d / "predictions.parquet").exists())
        if not hits:
            raise FileNotFoundError(f"no Phase 9 walk-forward experiment matches {pat}")
        rows.append(backtest(hits[-1], data_root, out_root))
    return rows
