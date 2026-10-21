"""Phase 11: robustness of walk-forward predictions across regimes, sectors, symbols, volatility,
time of day and transaction costs.

Inputs are Phase 9 walk-forward out-of-fold predictions (no retraining). Every bucket boundary is
derived from information available before the prediction and from the training period only:
- market regime: previous-day NIFTY close vs its 50-day average (trend), previous-day 20-day realised
  volatility of NIFTY (terciles fit on training-period dates);
- stock volatility: the row's own `vol_20` feature (terciles fit on pre-validation rows);
- inferred sector: the sector index whose daily returns, after removing NIFTY, correlate most with the
  stock's own NIFTY-removed returns over the training period (no offline sector master is available);
- time of day: minutes since the open.
Results are reported for the pre-validation folds and for validation separately. The test period is
not used.

Cost sensitivity is a per-signal expectancy, not a portfolio backtest (that is Phase 12): each
UP/DOWN call is a trade over the label horizon with return sign * future return, minus a round-trip
cost. Signals overlap in time, so the numbers are averages per call, not achievable P&L.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from sklearn.metrics import balanced_accuracy_score, matthews_corrcoef

from pulsetrader.eval.multiclass import DOWN, NEUTRAL, UP, to_index
from pulsetrader.experiments.classical import MOMENTUM_COL, _new_dir
from pulsetrader.models.classical import momentum_classes

RUNNER_VERSION = "robustness-v1"
SECTOR_INDICES = (
    "NIFTY AUTO",
    "NIFTY CONSR DURBL",
    "NIFTY ENERGY",
    "NIFTY FINSRV25 50",
    "NIFTY FMCG",
    "NIFTY HEALTHCARE",
    "NIFTY INFRA",
    "NIFTY IT",
    "NIFTY MEDIA",
    "NIFTY METAL",
    "NIFTY OIL AND GAS",
    "NIFTY PHARMA",
    "NIFTY PSU BANK",
    "NIFTY PVT BANK",
    "NIFTY REALTY",
)
MARKET_INDEX = "NIFTY"
COSTS_BP = (0.0, 2.0, 5.0, 10.0, 20.0, 30.0)
TIME_BUCKETS = (
    (0, 30, "09:15-09:45"),
    (30, 120, "09:45-11:15"),
    (120, 285, "11:15-14:00"),
    (285, 330, "14:00-14:45"),
    (330, 376, "14:45-15:30"),
)


def bucket_metrics(
    y: np.ndarray, pred: np.ndarray, fret: np.ndarray, mom: np.ndarray | None = None
) -> dict[str, Any]:
    n = len(y)
    if n == 0:
        return {"n": 0}
    directional = pred != NEUTRAL
    sign = np.sign(fret[directional])
    pd_ = pred[directional]
    out: dict[str, Any] = {
        "n": int(n),
        "accuracy": float(np.mean(y == pred)),
        "majority_share": float(np.max(np.bincount(y, minlength=3)) / n),
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)) if len(np.unique(y)) > 1 else None,
        "mcc": float(matthews_corrcoef(y, pred)) if len(np.unique(y)) > 1 else None,
        "directional_share": float(directional.mean()),
        "sign_accuracy": float(np.mean(np.where(pd_ == UP, sign > 0, sign < 0)))
        if directional.any()
        else None,
    }
    # split skill into "will it move" (NEUTRAL vs not) and "which way" (on rows that moved and were called)
    moved = y != NEUTRAL
    if moved.any() and (~moved).any():
        out["move_mcc"] = float(matthews_corrcoef(moved, directional))
    both = moved & directional
    out["direction_accuracy_when_moved"] = float(np.mean(pred[both] == y[both])) if both.any() else None
    if mom is not None and len(np.unique(y)) > 1:
        out["momentum_mcc"] = float(matthews_corrcoef(y, mom))
    return out


def daily_regimes(day_bars: pl.DataFrame, train_end: date) -> pl.DataFrame:
    """Per trade date: NIFTY trend and volatility regime known at the open (previous-day data only)."""
    nf = day_bars.filter(pl.col("symbol") == MARKET_INDEX).sort("trade_date")
    nf = nf.with_columns((pl.col("close") / pl.col("close").shift(1) - 1).alias("r")).with_columns(
        (pl.col("close") / pl.col("close").rolling_mean(50) - 1).shift(1).alias("trend_prev"),
        pl.col("r").rolling_std(20).shift(1).alias("vol_prev"),
    )
    train = nf.filter(pl.col("trade_date") <= train_end)["vol_prev"].drop_nulls().to_numpy()
    if len(train) < 3:  # index history missing or too short: regimes unknown
        lo = hi = float("nan")
    else:
        lo, hi = np.quantile(train, [1 / 3, 2 / 3])
    return nf.select(
        "trade_date",
        pl.when(pl.col("trend_prev") > 0)
        .then(pl.lit("up"))
        .when(pl.col("trend_prev") <= 0)
        .then(pl.lit("down"))
        .otherwise(None)
        .alias("nifty_trend"),
        pl.when(pl.col("vol_prev") <= lo)
        .then(pl.lit("low"))
        .when(pl.col("vol_prev") <= hi)
        .then(pl.lit("mid"))
        .when(pl.col("vol_prev").is_not_null())
        .then(pl.lit("high"))
        .otherwise(None)
        .alias("nifty_vol"),
    ).with_columns(pl.lit(json.dumps({"vol_terciles": [float(lo), float(hi)]})).alias("_cuts"))


def infer_sectors(day_bars: pl.DataFrame, symbols: list[str], train_end: date) -> dict[str, dict[str, Any]]:
    """Sector index with the highest correlation of NIFTY-removed daily returns (training period only)."""
    names = [MARKET_INDEX, *SECTOR_INDICES, *symbols]
    wide = (
        day_bars.filter(pl.col("symbol").is_in(names) & (pl.col("trade_date") <= train_end))
        .sort("trade_date")
        .with_columns((pl.col("close") / pl.col("close").shift(1).over("symbol") - 1).alias("r"))
        .pivot(on="symbol", index="trade_date", values="r")
    )
    if MARKET_INDEX not in wide.columns:
        return {sym: {"sector": "UNKNOWN", "corr": None} for sym in symbols}
    wide = wide.drop_nulls(MARKET_INDEX)
    m = wide[MARKET_INDEX].to_numpy()

    def resid(col: str) -> np.ndarray | None:
        if col not in wide.columns:
            return None
        x = wide[col].to_numpy().astype(float)
        ok = ~np.isnan(x) & ~np.isnan(m)
        if ok.sum() < 100:
            return None
        beta = np.cov(x[ok], m[ok])[0, 1] / np.var(m[ok])
        r = np.full_like(x, np.nan)
        r[ok] = x[ok] - beta * m[ok]
        return r

    sec = {s: resid(s) for s in SECTOR_INDICES}
    out: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        rs = resid(sym)
        best, best_c = "UNKNOWN", -1.0
        if rs is not None:
            for s, rr in sec.items():
                if rr is None:
                    continue
                ok = ~np.isnan(rs) & ~np.isnan(rr)
                c = float(np.corrcoef(rs[ok], rr[ok])[0, 1]) if ok.sum() > 100 else -1.0
                if c > best_c:
                    best, best_c = s, c
        out[sym] = {"sector": best.replace("NIFTY ", ""), "corr": best_c}
    return out


def cost_table(
    pred: np.ndarray, fret: np.ndarray, p_dir: np.ndarray, gates: tuple[float, ...] = (0.0, 0.40, 0.45, 0.50)
) -> list[dict[str, Any]]:
    rows = []
    for g in gates:
        m = (pred != NEUTRAL) & (p_dir >= g)
        k = int(m.sum())
        if not k:
            rows.append({"min_prob": g, "trades": 0})
            continue
        gross = np.where(pred[m] == UP, fret[m], -fret[m]) * 1e4  # basis points
        row: dict[str, Any] = {
            "min_prob": g,
            "trades": k,
            "share_of_rows": k / len(pred),
            "hit_rate": float(np.mean(gross > 0)),
            "gross_bp": float(gross.mean()),
            "net_bp": {f"{c:g}": float(gross.mean() - c) for c in COSTS_BP},
            "break_even_cost_bp": float(gross.mean()),
        }
        rows.append(row)
    return rows


def analyse(wf_dir: Path, data_root: Path, out_root: Path, dataset: str = "core100_s5") -> dict[str, Any]:
    exp_in = json.loads((wf_dir / "experiment.json").read_text())
    cfg_in = exp_in["config"]
    h, label = int(cfg_in["horizon"]), cfg_in["label"]
    thr = float(cfg_in["threshold"])
    train_end = date.fromisoformat(exp_in["train_period"]["end"])
    preds = pl.read_parquet(wf_dir / "predictions.parquet")
    folds = sorted(preds["fold"].unique().to_list(), key=lambda s: int(s[1:]))
    val_f = folds[-1]
    extra = (
        pl.scan_parquet(data_root / "datasets" / dataset / "part-*.parquet")
        .filter(pl.col("split").is_in(["train", "validation"]))
        .select("symbol", "ts", "trade_date", "min_since_open", "vol_20", MOMENTUM_COL[h])
        .collect()
    )
    df = preds.join(extra, on=["symbol", "ts"], how="left")
    day_bars = pl.read_parquet(data_root / "reference" / "day_bars.parquet")
    reg = daily_regimes(day_bars, train_end)
    cuts = json.loads(reg["_cuts"][0]) if reg.height else {"vol_terciles": [None, None]}
    df = df.join(reg.drop("_cuts"), on="trade_date", how="left")
    symbols = sorted(df["symbol"].unique().to_list())
    sectors = infer_sectors(day_bars, symbols, train_end)
    df = df.with_columns(
        pl.col("symbol").replace_strict({s: v["sector"] for s, v in sectors.items()}).alias("sector")
    )
    pre_vol = df.filter(pl.col("fold") != val_f)["vol_20"].drop_nulls().to_numpy()
    v_lo, v_hi = np.quantile(pre_vol, [1 / 3, 2 / 3])
    tod = pl.lit(None, dtype=pl.Utf8)
    for a, b, name in reversed(TIME_BUCKETS):
        tod = (
            pl.when((pl.col("min_since_open") >= a) & (pl.col("min_since_open") < b))
            .then(pl.lit(name))
            .otherwise(tod)
        )
    df = df.with_columns(
        pl.when(pl.col("vol_20") <= v_lo)
        .then(pl.lit("low"))
        .when(pl.col("vol_20") <= v_hi)
        .then(pl.lit("mid"))
        .when(pl.col("vol_20").is_not_null())
        .then(pl.lit("high"))
        .otherwise(pl.lit("missing"))
        .alias("stock_vol"),
        tod.alias("time_of_day"),
        pl.col("ts").dt.strftime("%Y-%m").alias("month"),
    )
    P = df.select("p_down", "p_neutral", "p_up").to_numpy().astype(float)
    df = df.with_columns(
        pl.Series("y", to_index(df["y_raw"].to_numpy())),
        pl.Series("pred", P.argmax(axis=1)),
        pl.Series("p_dir", np.maximum(P[:, UP], P[:, DOWN])),
        pl.Series("mom", momentum_classes(df[MOMENTUM_COL[h]].to_numpy().astype(float), thr)),
    )

    def by(col: str, frame: pl.DataFrame) -> dict[str, Any]:
        out = {}
        for key, g in sorted(frame.group_by(col), key=lambda kv: str(kv[0][0])):
            out[str(key[0])] = bucket_metrics(
                g["y"].to_numpy(),
                g["pred"].to_numpy(),
                g["fret"].to_numpy().astype(float),
                g["mom"].to_numpy(),
            )
        return out

    parts = {
        "pre_validation": df.filter(pl.col("fold") != val_f),
        "validation": df.filter(pl.col("fold") == val_f),
    }
    result: dict[str, Any] = {
        "label": label,
        "cuts": {"nifty_vol": cuts["vol_terciles"], "stock_vol_20": [float(v_lo), float(v_hi)]},
    }
    for pname, frame in parts.items():
        sym = by("symbol", frame)
        mccs = np.array([v["mcc"] for v in sym.values() if v.get("mcc") is not None])
        beats = np.array(
            [v["mcc"] > v.get("momentum_mcc", -1) for v in sym.values() if v.get("mcc") is not None]
        )
        result[pname] = {
            "overall": bucket_metrics(
                frame["y"].to_numpy(),
                frame["pred"].to_numpy(),
                frame["fret"].to_numpy().astype(float),
                frame["mom"].to_numpy(),
            ),
            "fold": by("fold", frame),
            "month": by("month", frame),
            "nifty_trend": by("nifty_trend", frame),
            "nifty_vol": by("nifty_vol", frame),
            "stock_vol": by("stock_vol", frame),
            "time_of_day": by("time_of_day", frame),
            "sector": by("sector", frame),
            "symbols": {
                "n": int(len(mccs)),
                "mcc_mean": float(mccs.mean()),
                "mcc_median": float(np.median(mccs)),
                "mcc_p10": float(np.quantile(mccs, 0.1)),
                "mcc_min": float(mccs.min()),
                "mcc_max": float(mccs.max()),
                "share_mcc_positive": float(np.mean(mccs > 0)),
                "share_beats_momentum": float(beats.mean()),
                "worst5": sorted(
                    ((s, v["mcc"]) for s, v in sym.items() if v.get("mcc") is not None), key=lambda x: x[1]
                )[:5],
                "best5": sorted(
                    ((s, v["mcc"]) for s, v in sym.items() if v.get("mcc") is not None), key=lambda x: -x[1]
                )[:5],
            },
            "costs": cost_table(
                frame["pred"].to_numpy(), frame["fret"].to_numpy().astype(float), frame["p_dir"].to_numpy()
            ),
        }
    cfg = {
        "step": "robustness",
        "source_experiment": wf_dir.name,
        "label": label,
        "model": cfg_in["model"],
        "tag": cfg_in["tag"],
        "costs_bp": COSTS_BP,
        "sector_method": "max residual daily-return correlation",
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    d = _new_dir(out_root, f"{stamp}-p11-robustness-{cfg['model']}-{label}-{cfg['tag']}")
    exp = {
        "experiment_id": d.name,
        "runner_version": RUNNER_VERSION,
        "phase": 11,
        **{
            k: exp_in[k]
            for k in ("dataset_id", "dataset", "train_period", "validation_period", "test_period")
        },
        "config": cfg,
        "created_at": datetime.now(UTC).isoformat(),
    }
    (d / "experiment.json").write_text(json.dumps(exp, indent=2, default=str))
    (d / "config.json").write_text(json.dumps(cfg, indent=2))
    (d / "metrics.json").write_text(json.dumps(result, indent=2, default=str))
    (d / "sectors.json").write_text(json.dumps(sectors, indent=1))
    (d / "report.md").write_text(render(exp, result))
    return {"experiment": exp, "result": result, "dir": str(d)}


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.1f}%"


def _num(x: float | None, nd: int = 3) -> str:
    return "–" if x is None else f"{x:.{nd}f}"


def _table(title: str, pre: dict[str, Any], val: dict[str, Any]) -> list[str]:
    lines = [
        f"### {title}",
        "",
        "| Bucket | Val rows | Val acc | Val majority | Val bal acc | Val MCC | Val momentum MCC |"
        " Val sign acc (UP/DOWN calls) | Pre-val MCC |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for k in sorted(set(pre) | set(val)):
        v, p = val.get(k, {}), pre.get(k, {})
        lines.append(
            f"| {k} | {v.get('n', 0):,} | {_pct(v.get('accuracy'))} | {_pct(v.get('majority_share'))} | "
            f"{_pct(v.get('balanced_accuracy'))} | {_num(v.get('mcc'))} | {_num(v.get('momentum_mcc'))} | "
            f"{_pct(v.get('sign_accuracy'))} | {_num(p.get('mcc'))} |"
        )
    return [*lines, ""]


def render(exp: dict[str, Any], res: dict[str, Any]) -> str:
    c = exp["config"]
    pre, val = res["pre_validation"], res["validation"]
    lines = [f"## {c['model']} ({c['tag']}) — `{c['label']}`", ""]
    o = val["overall"]
    lines += [
        f"Validation overall: {o['n']:,} rows, accuracy {_pct(o['accuracy'])}, balanced accuracy "
        f"{_pct(o['balanced_accuracy'])}, MCC {_num(o['mcc'])} (momentum {_num(o.get('momentum_mcc'))}), "
        f"UP/DOWN calls {_pct(o['directional_share'])} of rows with sign accuracy "
        f"{_pct(o['sign_accuracy'])}. Skill split: move-vs-no-move MCC {_num(o.get('move_mcc'))}; "
        f"direction right on {_pct(o.get('direction_accuracy_when_moved'))} of rows that "
        "moved and were called.",
        "",
    ]
    for key, title in (
        ("nifty_trend", "Market trend (NIFTY vs 50-day average, previous day)"),
        ("nifty_vol", "Market volatility (NIFTY 20-day, terciles from training dates)"),
        ("stock_vol", "Stock volatility (vol_20, terciles from pre-validation rows)"),
        ("time_of_day", "Time of day (IST)"),
        ("sector", "Inferred sector"),
        ("fold", "Walk-forward fold"),
    ):
        lines += _table(title, pre[key], val[key])
    lines += _table("Month (validation)", {}, val["month"])
    for pname in ("pre_validation", "validation"):
        s = res[pname]["symbols"]
        lines += [
            f"### Symbols ({pname.replace('_', '-')})",
            "",
            f"{s['n']} symbols. MCC mean {_num(s['mcc_mean'])}, median {_num(s['mcc_median'])}, "
            "10th percentile "
            f"{_num(s['mcc_p10'])}, min {_num(s['mcc_min'])}, max {_num(s['mcc_max'])}. MCC > 0 for "
            f"{_pct(s['share_mcc_positive'])} of symbols; beats momentum on "
            f"{_pct(s['share_beats_momentum'])}.",
            "Worst: "
            + ", ".join(f"{a} {b:.3f}" for a, b in s["worst5"])
            + ". Best: "
            + ", ".join(f"{a} {b:.3f}" for a, b in s["best5"])
            + ".",
            "",
        ]
    lines += [
        "### Cost sensitivity (validation, per UP/DOWN call over the label horizon)",
        "",
        "| Min P(direction) | Calls | Share of rows | Hit rate | Gross bp | Net @2bp | Net @5bp | Net @10bp |"
        " Net @20bp | Break-even bp |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in val["costs"]:
        if not r["trades"]:
            lines.append(f"| {r['min_prob']:.2f} | 0 | – | – | – | – | – | – | – | – |")
            continue
        nb = r["net_bp"]
        lines.append(
            f"| {r['min_prob']:.2f} | {r['trades']:,} | {_pct(r['share_of_rows'])} | {_pct(r['hit_rate'])} | "
            f"{r['gross_bp']:.2f} | {nb['2']:.2f} | {nb['5']:.2f} | {nb['10']:.2f} | {nb['20']:.2f} | "
            f"{r['break_even_cost_bp']:.2f} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_summary(rows: list[dict[str, Any]]) -> str:
    e0 = rows[0]["experiment"]
    head = [
        "# Phase 11 — robustness (validation and pre-validation walk-forward folds)",
        "",
        f"Dataset `{e0['dataset_id']}`. Inputs: Phase 9 walk-forward out-of-fold predictions "
        "(no retraining).",
        f"Validation {e0['validation_period']['start']}..{e0['validation_period']['end']}; "
        "pre-validation = folds",
        "F1–F4 inside the training period. Test period not used. Bucket boundaries use training-period",
        "information only; sectors are inferred from daily-return correlation with NIFTY sector indices",
        "(no offline sector master). Cost rows are per-call expectancy, not portfolio P&L (Phase 12).",
        "",
    ]
    return "\n".join(head + [render(r["experiment"], r["result"]) for r in rows])


DEFAULT_INPUTS = ("wf-expanding-lightgbm-y_1m_5bp-tuned", "wf-expanding-lightgbm-y_5m_10bp-tuned")


def run(data_root: Path, out_root: Path, patterns: tuple[str, ...] = DEFAULT_INPUTS) -> list[dict[str, Any]]:
    rows = []
    for pat in patterns:
        hits = sorted(d for d in out_root.glob(f"*-p9-{pat}-*") if (d / "predictions.parquet").exists())
        if not hits:
            raise FileNotFoundError(f"no Phase 9 walk-forward experiment matches {pat}")
        rows.append(analyse(hits[-1], data_root, out_root))
    return rows
