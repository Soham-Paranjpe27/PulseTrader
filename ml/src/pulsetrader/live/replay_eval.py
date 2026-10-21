"""Phase 18 on recorded data: replay validation sessions through the live pipeline (outcome tracking on)
and evaluate the predictions as a live paper run. No live provider is connected in this environment,
so every figure here is REPLAY, never LIVE.

Two cross-checks keep the evaluation honest:
- every live outcome (realised class and return) must equal the research label for the same
  (symbol, ts) in the dataset (same definition, computed independently from the replayed bars);
- the run is compared with the model's walk-forward validation predictions on the same rows.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from pulsetrader.labels.labels import label_name
from pulsetrader.live.evaluate import evaluate
from pulsetrader.live.features import LiveUniverse
from pulsetrader.live.pipeline import JsonlSink, LivePipeline, MemorySink, PipelineConfig, Sink
from pulsetrader.live.providers import HistoricalProvider, session_dates
from pulsetrader.serve.models import ModelServer


def validation_sessions(data_root: Path, dataset: str, last: int) -> list[date]:
    m = json.loads((data_root / "datasets" / dataset / "dataset_manifest.json").read_text())
    val = next(p for p in m["periods"] if p["name"] == "validation")
    lo, hi = date.fromisoformat(val["start"]), date.fromisoformat(val["end"])
    return [d for d in session_dates(data_root) if lo <= d <= hi][-last:]


def run(
    data_root: Path, days: list[date], dataset: str = "core100_s5", out: Path | None = None
) -> dict[str, Any]:
    ds_dir = data_root / "datasets" / dataset
    uni = LiveUniverse.from_manifest(ds_dir)
    srv = ModelServer(data_root / "registry")
    models = sorted(srv.models.values(), key=lambda m: m.record.key)
    if not models:
        raise RuntimeError(f"no servable models: {srv.load_errors}")
    mem = MemorySink()
    sinks: list[Sink] = [mem]
    if out is not None:
        sinks.append(JsonlSink(out))
    runs = []
    for day in days:
        t0 = time.perf_counter()
        pipe = LivePipeline(HistoricalProvider(data_root, day), uni, models, sinks, PipelineConfig())
        r = asyncio.run(pipe.run())
        runs.append({"date": day.isoformat(), "seconds": round(time.perf_counter() - t0, 1),
                     **{k: r[k] for k in ("predictions", "outcomes", "rejected", "late_bars")}})  # fmt: skip
    return {
        "dates": [d.isoformat() for d in days],
        "runs": runs,
        "evaluation": evaluate(mem.outs),
        "label_check": label_check(ds_dir, mem.outs, models),
        "walk_forward": walk_forward_check(data_root, mem.outs, models),
    }


def label_check(ds_dir: Path, outs: list[dict[str, Any]], models: list[Any]) -> list[dict[str, Any]]:
    o = pl.DataFrame(
        [{"model": x["model_id"], "symbol": x["symbol"], "ts": x["market_data_timestamp"],
          "actual_class": x["actual_class"], "actual_return": x["actual_return"]} for x in outs],
        infer_schema_length=None,
    ).with_columns(pl.col("ts").str.to_datetime(time_zone="Asia/Kolkata"))  # fmt: skip
    days = o["ts"].dt.date().unique().implode()
    res = []
    for m in models:
        h, thr = int(m.meta["horizon"]), float(m.meta["threshold"])
        col = label_name(h, thr)
        ds = (
            pl.scan_parquet(ds_dir / "part-*.parquet")
            .filter(pl.col("trade_date").is_in(days))
            .select("symbol", "ts", col, f"fret_{h}")
            .collect()
        )
        j = o.filter(pl.col("model") == m.record.model_id).join(ds, on=["symbol", "ts"], how="inner")
        cls = j[col].replace_strict({-1: "DOWN", 0: "NEUTRAL", 1: "UP"}, default=None)
        same_class = (cls == j["actual_class"]) | (cls.is_null() & j["actual_class"].is_null())
        diff = (j["actual_return"] - j[f"fret_{h}"].cast(pl.Float64)).abs().drop_nulls()
        res.append({
            "model": m.record.key,
            "rows_joined": j.height,
            "class_match": float(same_class.mean()) if j.height else None,  # type: ignore[arg-type]
            "max_abs_return_diff": float(diff.max()) if diff.len() else None,  # type: ignore[arg-type]
        })  # fmt: skip
    return res


def walk_forward_check(
    data_root: Path, outs: list[dict[str, Any]], models: list[Any]
) -> list[dict[str, Any]]:
    o = pl.DataFrame(
        [{"model": x["model_id"], "symbol": x["symbol"], "ts": x["market_data_timestamp"],
          "p_up_live": x["raw_probability"]["up"], "direction": x["direction"],
          "correct": x["direction_correct"]} for x in outs],
        infer_schema_length=None,
    ).with_columns(pl.col("ts").str.to_datetime(time_zone="Asia/Kolkata"))  # fmt: skip
    res = []
    for m in models:
        wf = pl.read_parquet(
            data_root / "experiments" / m.record.source_experiments["walk_forward"] / "predictions.parquet"
        ).with_columns(pl.col("ts").dt.convert_time_zone("Asia/Kolkata"))
        j = o.filter(pl.col("model") == m.record.model_id).join(wf, on=["symbol", "ts"], how="inner")
        d = np.abs(j["p_up_live"].to_numpy() - j["p_up"].to_numpy()) if j.height else np.zeros(0)
        res.append({"model": m.record.key, "rows_joined": j.height,
                    "max_abs_p_up_diff": float(np.max(d)) if len(d) else None})  # fmt: skip
    return res


def _f(x: Any, nd: int = 3) -> str:
    return "–" if x is None else f"{x:.{nd}f}"


def _e(x: float | None) -> str:
    return "–" if x is None else f"{x:.2e}"


def render(res: dict[str, Any]) -> str:
    ev = res["evaluation"]
    lines = [
        "# Phase 18: live paper evaluation (REPLAY of recorded validation sessions)",
        "",
        f"Sessions: {res['dates'][0]} .. {res['dates'][-1]} ({len(res['dates'])} sessions, validation "
        "period). Each session was replayed bar by bar through the live pipeline; every prediction was "
        "scored after its horizon from the replayed bars. No live provider is connected here, so these are "
        "REPLAY results, not LIVE ones. Test period not used.",
        "",
        "## Outcome checks",
        "",
    ]
    for c in res["label_check"]:
        rd = c["max_abs_return_diff"]
        lines.append(f"- {c['model']}: {c['rows_joined']} outcomes joined to research labels; class "
                     f"match {_f(c['class_match'], 4)}, max return diff {_e(rd)}.")  # fmt: skip
    for c in res["walk_forward"]:
        pd_ = c["max_abs_p_up_diff"]
        lines.append(f"- {c['model']}: {c['rows_joined']} rows joined to walk-forward validation "
                     f"predictions; max P(up) diff {_e(pd_)}.")  # fmt: skip
    lines += [
        "",
        "## Full coverage (argmax class on every evaluated prediction)",
        "",
        "| model | predictions | evaluated | accuracy | balanced acc | MCC | Brier raw | ECE raw | "
        "Brier cal | ECE cal |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for e in ev:
        f, c = e["full_coverage"] or {}, e["calibrated"] or {}
        lines.append(
            f"| {e['model']} | {e['predictions']} | {e['evaluated']} | {_f(f.get('accuracy'))} | "
            f"{_f(f.get('balanced_accuracy'))} | {_f(f.get('mcc'))} | {_f(f.get('brier'))} | "
            f"{_f(f.get('ece_top'))} | {_f(c.get('brier'))} | {_f(c.get('ece_top'))} |"
        )
    lines += [
        "",
        "## Served calls (UP/DOWN after the confidence gate; everything else is NO PREDICTION)",
        "",
        "| model | calls | coverage | accuracy | sign accuracy | balanced acc | MCC | last 20 | last 50 | "
        "last 100 | last 500 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for e in ev:
        s, r = e["selective"], e["rolling"]
        lines.append(
            f"| {e['model']} | {s['calls']} | {_f(s['coverage'], 4)} | {_f(s['accuracy'])} | "
            f"{_f(s['sign_accuracy'])} | {_f(s['balanced_accuracy'])} | {_f(s['mcc'])} | "
            + " | ".join(_f(r[f"last_{w}"]["accuracy"]) for w in (20, 50, 100, 500))
            + " |"
        )
    lines += [
        "",
        "## Paper trading per call (independent calls, no capital limits: an upper bound)",
        "",
        "| model | calls | mean gross bp | round-trip cost bp | mean net bp | hit rate gross | "
        "hit rate net | total net bp |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in ev:
        p = e["paper"]
        lines.append(
            f"| {e['model']} | {p['calls']} | {_f(p['mean_gross_bp'], 2)} | "
            f"{_f(p['round_trip_cost_bp'], 2)} | "
            f"{_f(p['mean_net_bp'], 2)} | {_f(p['hit_rate_gross'])} | {_f(p['hit_rate_net'])} | "
            f"{_f(p['sum_net_bp'], 1)} |"
        )
    for e in ev:
        lines += ["", f"## Daily, {e['model']}", "", "| day | evaluated | calls | coverage | accuracy |",
                  "|---|---|---|---|---|"]  # fmt: skip
        for d in e["daily"]:
            lines.append(
                f"| {d['p']} | {d['n']} | {d['calls']} | {_f(d['coverage'], 4)} | {_f(d['accuracy'])} |"
            )
        lines.append("")
        lines.append("Weekly: " + ", ".join(f"{w['p']} {w['calls']} calls acc {_f(w['accuracy'])}"
                                             for w in e["weekly"]))  # fmt: skip
        lines.append("Monthly: " + ", ".join(f"{w['p']} {w['calls']} calls acc {_f(w['accuracy'])}"
                                              for w in e["monthly"]))  # fmt: skip
    return "\n".join(lines) + "\n"
