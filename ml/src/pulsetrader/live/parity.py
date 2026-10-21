"""Phase 17 live-parity check on real data: replay a recorded validation session through the live
pipeline and compare it with the research system.

1. Features: every live feature row (built bar by bar from the real-time cache with 5 warm-up sessions)
   is joined to the research dataset row for the same (symbol, ts), and each model feature is compared.
2. Predictions: live raw probabilities are compared with the stored walk-forward validation
   predictions of the same model for the same rows.

Expected, documented differences: the dataset computes features over each symbol's full history
(live: 5 warm-up sessions, so long EMAs differ slightly), the dataset is stored as float32, and its
cross-sections exclude rows the live system cannot know about in advance (sessions later found to be
short, corporate-action days), which moves leave-one-out cross-sectional features. Test period refused.
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

from pulsetrader.live.features import LiveUniverse
from pulsetrader.live.pipeline import LivePipeline, MemorySink, PipelineConfig
from pulsetrader.live.providers import HistoricalProvider
from pulsetrader.serve.models import ModelServer

ABS_TOL = 1e-4
REL_TOL = 1e-3
PROB_TOL = 1e-3


def _close(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    both_nan = np.isnan(a) & np.isnan(b)
    ok = np.abs(a - b) <= ABS_TOL + REL_TOL * np.abs(b)
    return both_nan | np.nan_to_num(ok, nan=False)


def check(data_root: Path, day: date, dataset: str = "core100_s5") -> dict[str, Any]:
    ds_dir = data_root / "datasets" / dataset
    uni = LiveUniverse.from_manifest(ds_dir)
    srv = ModelServer(data_root / "registry")
    models = sorted(srv.models.values(), key=lambda m: m.record.key)
    if not models:
        raise RuntimeError(f"no servable models: {srv.load_errors}")
    sink = MemorySink()
    pipe = LivePipeline(
        HistoricalProvider(data_root, day), uni, models, [sink], PipelineConfig(keep_features=True)
    )
    t0 = time.perf_counter()
    run = asyncio.run(pipe.run())
    run["seconds"] = round(time.perf_counter() - t0, 1)
    live = pl.concat(pipe.feature_frames, how="diagonal_relaxed")

    research = pl.scan_parquet(ds_dir / "part-*.parquet").filter(pl.col("trade_date") == day).collect()
    feats = models[0].features
    joined = live.select("symbol", "ts", *feats).join(
        research.select("symbol", "ts", "split", *feats), on=["symbol", "ts"], how="inner", suffix="_r"
    )
    per_feature = []
    for f in feats:
        a = joined[f].cast(pl.Float64).fill_null(np.nan).to_numpy()
        b = joined[f"{f}_r"].cast(pl.Float64).fill_null(np.nan).to_numpy()
        ok = _close(a, b)
        diff = np.abs(a - b)
        per_feature.append({
            "feature": f,
            "match_fraction": float(ok.mean()) if len(ok) else None,
            "max_abs_diff": float(np.nanmax(diff)) if np.isfinite(diff).any() else 0.0,
            "null_mismatch": int((np.isnan(a) != np.isnan(b)).sum()),
        })  # fmt: skip
    exact = [p for p in per_feature if p["match_fraction"] == 1.0]

    preds = pl.DataFrame(
        [{"model_id": p["model_id"], "symbol": p["symbol"], "ts": p["market_data_timestamp"],
          **{f"l_{k}": v for k, v in p["raw_probability"].items()}, "direction": p["direction"],
          "abstain": p["abstain_reason"]} for p in sink.preds]
    ).with_columns(pl.col("ts").str.to_datetime(time_zone="Asia/Kolkata"))  # fmt: skip
    pred_out = []
    for m in models:
        wf = pl.read_parquet(
            data_root / "experiments" / m.record.source_experiments["walk_forward"] / "predictions.parquet"
        )
        wf = wf.filter((pl.col("fold") == wf["fold"].max()) & (pl.col("ts").dt.date() == day))
        j = preds.filter(pl.col("model_id") == m.record.model_id).join(
            wf.with_columns(pl.col("ts").dt.convert_time_zone("Asia/Kolkata")), on=["symbol", "ts"]
        )
        got = j.select("l_down", "l_neutral", "l_up").to_numpy()
        want = j.select("p_down", "p_neutral", "p_up").to_numpy()
        d = np.max(np.abs(got - want), axis=1) if len(j) else np.zeros(0)
        same_class = (got.argmax(1) == want.argmax(1)) if len(j) else np.zeros(0, bool)
        pred_out.append({
            "model": m.record.key,
            "status": m.record.status,
            "live_predictions": int(preds.filter(pl.col("model_id") == m.record.model_id).height),
            "matched_walk_forward_rows": len(j),
            "max_abs_prob_diff": float(np.max(d)) if len(d) else None,
            "median_abs_prob_diff": float(np.median(d)) if len(d) else None,
            "rows_within_tol": float((d <= PROB_TOL).mean()) if len(d) else None,
            "same_argmax_class": float(same_class.mean()) if len(d) else None,
            "abstain_reasons": dict(preds.filter(pl.col("model_id") == m.record.model_id)
                                    .group_by("abstain").len().iter_rows()),
        })  # fmt: skip
    return {
        "date": day.isoformat(),
        "split": sorted(set(research["split"].drop_nulls().to_list())),
        "run": run,
        "feature_rows_live": live.height,
        "feature_rows_research": research.height,
        "feature_rows_joined": joined.height,
        "features_compared": len(feats),
        "features_exact": len(exact),
        "per_feature": sorted(per_feature, key=lambda p: p["match_fraction"] or 0),
        "predictions": pred_out,
        "tolerance": {"abs": ABS_TOL, "rel": REL_TOL, "prob": PROB_TOL},
        "final_status": sink.statuses[-1] if sink.statuses else None,
    }


def render(res: dict[str, Any]) -> str:
    r = res["run"]
    lines = [
        "# Phase 17: live pipeline parity (replayed validation session)",
        "",
        f"Session {res['date']} (split: {', '.join(res['split'])}) replayed bar by bar through the live "
        "pipeline: provider, validation, real-time cache, shared feature engine, local inference. "
        "Feed state REPLAY throughout (recorded data is never shown as LIVE). Test period not used.",
        "",
        f"- Bars: {r['bars']} ({r['accepted']} accepted, rejected {r['rejected'] or 'none'}), minutes "
        f"{r['minutes']}, sampled prediction bars {r['sampled']}, predictions {r['predictions']}.",
        f"- Feature build per sampled bar: median {r['feature_seconds_p50']:.2f}s, max "
        f"{r['feature_seconds_max']:.2f}s (100 stocks + indices). Whole replay {r['seconds']}s.",
        f"- Feature rows: live {res['feature_rows_live']}, research {res['feature_rows_research']}, "
        f"joined {res['feature_rows_joined']}.",
        f"- Features matching within tolerance (abs {res['tolerance']['abs']} + rel "
        f"{res['tolerance']['rel']}) on every joined row: {res['features_exact']} of "
        f"{res['features_compared']}.",
        "",
        "## Features that differ on some rows",
        "",
        "| feature | rows matching | max abs diff | null mismatches |",
        "|---|---|---|---|",
    ]
    for p in res["per_feature"]:
        if p["match_fraction"] != 1.0:
            lines.append(f"| {p['feature']} | {p['match_fraction']:.4f} | {p['max_abs_diff']:.3g} | "
                         f"{p['null_mismatch']} |")  # fmt: skip
    lines += [
        "",
        "## Predictions vs stored walk-forward validation predictions",
        "",
        "| model | status | live preds | matched rows | max abs prob diff | median | rows within "
        f"{res['tolerance']['prob']} | same argmax class |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in res["predictions"]:
        lines.append(
            f"| {p['model']} | {p['status']} | {p['live_predictions']} | {p['matched_walk_forward_rows']} | "
            f"{p['max_abs_prob_diff']:.3g} | {p['median_abs_prob_diff']:.3g} | {p['rows_within_tol']:.4f} | "
            f"{p['same_argmax_class']:.4f} |"
        )
    lines += ["", "Abstention reasons per model: " + json.dumps(
        {p["model"]: p["abstain_reasons"] for p in res["predictions"]}, default=str)]  # fmt: skip
    return "\n".join(lines) + "\n"
