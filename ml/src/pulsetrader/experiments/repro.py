"""Phase 20 ML reproducibility check.

1. Artifact integrity: every registry artifact file matches its recorded SHA-256 (sha256.json; recorded
   now for artifacts registered before Phase 20). The inference server refuses a changed artifact.
2. Model refit: each registry model is refitted from its walk-forward experiment into a scratch
   directory with the registry's own export code (same rows, preprocessor fit on training rows, params,
   seed). The refit must reproduce the stored validation predictions and the artifact files byte for
   byte.
3. Dataset rebuild: per-symbol features and labels of a seeded sample of symbols are recomputed from
   the canonical bars with the shared feature engine and compared with the stored research dataset,
   value by value. Only training and validation dates are compared; the test period is not read.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import tempfile
import time
from dataclasses import fields
from pathlib import Path
from typing import Any

import polars as pl

from pulsetrader.datasets.build import DatasetConfig, _f32, symbol_rows
from pulsetrader.registry.registry import DIGEST_FILE, Registry, verify_digests, write_digests
from pulsetrader.security.master import flagged_days

log = logging.getLogger(__name__)
KEYS = {"symbol", "ts", "trade_date", "split"}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def artifact_check(reg: Registry) -> list[dict[str, Any]]:
    out = []
    for rec in reg.models():
        art = reg.root / rec.artifact_path
        recorded_now = not (art / DIGEST_FILE).exists()
        if recorded_now:
            write_digests(art)
        bad = verify_digests(art)
        files = json.loads((art / DIGEST_FILE).read_text())
        out.append({"model": rec.key, "files": len(files), "recorded_now": recorded_now, "problems": bad,
                    "passed": not bad})  # fmt: skip
    return out


def refit_check(data_root: Path, reg: Registry, dataset: str) -> list[dict[str, Any]]:
    from pulsetrader.experiments.register import export_artifact

    out = []
    exp_root = data_root / "experiments"
    for rec in reg.models():
        src = rec.source_experiments
        art = reg.root / rec.artifact_path
        with tempfile.TemporaryDirectory(dir=data_root) as tmp:
            t0 = time.monotonic()
            res = export_artifact(exp_root / src["walk_forward"], exp_root / src["calibration"], data_root,
                                  Path(tmp) / "art", dataset)  # fmt: skip
            new = Path(tmp) / "art"
            files = ("model.txt", "preprocessor.json", "features.json", "calibrator.json")
            same = {f: _sha(new / f) == _sha(art / f) for f in files}
            out.append({
                "model": rec.key,
                "seconds": round(time.monotonic() - t0, 1),
                "prediction_gate": res["gate"],
                "best_iteration": res["info"]["best_iteration"],
                "registry_best_iteration": rec.hyperparameters.get("best_iteration"),
                "identical_files": same,
                "passed": res["gate"]["status"] == "PASSED" and all(same.values()),
            })  # fmt: skip
            log.info("refit %s: %s", rec.key, out[-1])
    return out


def _equal(a: pl.Series, b: pl.Series) -> pl.Series:
    """Element-wise equality where null == null and NaN == NaN."""
    both_null = a.is_null() & b.is_null()
    if a.dtype.is_float():
        both_nan = (a.is_nan() & b.is_nan()).fill_null(False)
        return (both_null | both_nan | (a == b).fill_null(False)).fill_null(False)
    return (both_null | (a == b).fill_null(False)).fill_null(False)


def feature_check(data_root: Path, dataset: str, n_symbols: int, seed: int) -> dict[str, Any]:
    ds_dir = data_root / "datasets" / dataset
    man = json.loads((ds_dir / "dataset_manifest.json").read_text())
    names = {f.name for f in fields(DatasetConfig)}
    kw: dict[str, Any] = {k: (tuple(v) if isinstance(v, list) else v) for k, v in man["config"].items()
                          if k in names}  # fmt: skip
    cfg = DatasetConfig(**kw)
    test_start = next(p["start"] for p in man["periods"] if p["name"] == "test")
    rng = random.Random(seed)
    symbols = sorted(rng.sample(sorted(man["universe"]), n_symbols))
    ref = data_root / "reference"
    days = pl.read_parquet(ref / "day_bars.parquet")
    exclude = flagged_days(pl.read_parquet(ref / "corporate_action_events.parquet"), days)
    session_bars = days.select("symbol", "trade_date", "bars")
    cutoff = pl.lit(test_start).str.to_date()
    per: list[dict[str, Any]] = []
    schema = pl.scan_parquet(ds_dir / "part-*.parquet").collect_schema()
    for sym in symbols:
        rows, _ = symbol_rows(data_root / "canonical", sym, cfg, exclude, session_bars)
        rows = _f32(rows).filter(pl.col("trade_date") < cutoff)
        stored = (
            pl.scan_parquet(ds_dir / "part-*.parquet")
            .filter((pl.col("symbol") == sym) & (pl.col("trade_date") < cutoff))
            .select([c for c in rows.columns if c in schema])
            .collect()
        )
        cols = [c for c in rows.columns if c in stored.columns and c not in KEYS]
        j = rows.select("ts", *cols).join(stored.select("ts", *cols), on="ts", how="inner", suffix="__s")
        mismatched = {c: int((~_equal(j[c], j[f"{c}__s"])).sum()) for c in cols}
        bad = {c: n for c, n in mismatched.items() if n}
        per.append({"symbol": sym, "recomputed_rows": rows.height, "stored_rows": stored.height,
                    "matched_rows": j.height, "columns": len(cols), "mismatched_values": bad,
                    "passed": rows.height == stored.height == j.height and not bad})  # fmt: skip
        log.info("features %s: %s", sym, per[-1])
    return {"symbols": per, "compared_before": test_start, "seed": seed,
            "passed": all(p["passed"] for p in per)}  # fmt: skip


def run(data_root: Path, dataset: str = "core100_s5", n_symbols: int = 6, seed: int = 20) -> dict[str, Any]:
    reg = Registry(data_root / "registry")
    res: dict[str, Any] = {"artifacts": artifact_check(reg)}
    res["features"] = feature_check(data_root, dataset, n_symbols, seed)
    res["refit"] = refit_check(data_root, reg, dataset)
    res["passed"] = (all(a["passed"] for a in res["artifacts"]) and res["features"]["passed"]
                     and all(r["passed"] for r in res["refit"]))  # fmt: skip
    return res


def render(res: dict[str, Any]) -> str:
    lines = ["# Phase 20: ML reproducibility", "", f"Overall: {'PASSED' if res['passed'] else 'FAILED'}.", "",
             "## Artifact integrity (SHA-256 per file)", "", "| model | files | digests | result |",
             "|---|---|---|---|"]  # fmt: skip
    for a in res["artifacts"]:
        how = "recorded now" if a["recorded_now"] else "verified"
        ok = "PASS" if a["passed"] else "FAIL: " + ", ".join(a["problems"])
        lines.append(f"| {a['model']} | {a['files']} | {how} | {ok} |")
    f = res["features"]
    title = f"## Dataset rebuild from canonical bars (seed {f['seed']}, dates before {f['compared_before']})"
    lines += ["", title,
              "", "| symbol | rows recomputed / stored / matched | columns | mismatched values | result |",
              "|---|---|---|---|---|"]  # fmt: skip
    for s in f["symbols"]:
        mm = ", ".join(f"{k} {v}" for k, v in s["mismatched_values"].items()) or "0"
        n = f"{s['recomputed_rows']:,} / {s['stored_rows']:,} / {s['matched_rows']:,}"
        lines.append(f"| {s['symbol']} | {n} | {s['columns']} | {mm} | {'PASS' if s['passed'] else 'FAIL'} |")
    lines += ["", "## Model refit from the walk-forward experiment", "",
              "| model | refit time | stored validation predictions | identical artifact files | result |",
              "|---|---|---|---|---|"]  # fmt: skip
    for r in res["refit"]:
        same = ", ".join(f"{k} {'yes' if v else 'NO'}" for k, v in r["identical_files"].items())
        lines.append(f"| {r['model']} | {r['seconds']} s | {r['prediction_gate']['evidence']} | {same} | "
                     f"{'PASS' if r['passed'] else 'FAIL'} |")  # fmt: skip
    return "\n".join(lines) + "\n"
