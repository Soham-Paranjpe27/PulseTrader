"""Command-line entry points: `pulsetrader fetch|discover|pipeline|security|dataset|audit|classical|deep`."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from pathlib import Path

from pulsetrader.config import data_paths

HF_DATASET = "xxparthparekhxx/indian-stock-market-minute-data"

log = logging.getLogger("pulsetrader")


def resources() -> dict[str, float]:
    import os

    total, _, free = shutil.disk_usage(".")
    mem_avail = 0.0
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable"):
                mem_avail = int(line.split()[1]) / 1024**2
    return {
        "cpus": float(os.cpu_count() or 0),
        "ram_available_gb": round(mem_avail, 2),
        "disk_free_gb": round(free / 1024**3, 2),
    }


def cmd_fetch(args: argparse.Namespace) -> None:
    raw = data_paths().raw
    existing = [p for p in raw.rglob("*") if p.is_file() and p.name != ".gitkeep"]
    if existing and not args.force:
        log.info("data/raw already has %d files; not re-downloading (use --force)", len(existing))
        return
    from huggingface_hub import snapshot_download  # optional dependency, only needed here

    snapshot_download(repo_id=HF_DATASET, repo_type="dataset", local_dir=raw, max_workers=4)


def cmd_discover(args: argparse.Namespace) -> None:
    from pulsetrader.data.discovery import discover

    p = data_paths()
    log.info("resources: %s", resources())
    m = discover(p.raw, Path(args.reports), hash_files=not args.no_hash)
    print(json.dumps({k: v for k, v in m.items() if k != "files"}, indent=2, default=str))


def cmd_pipeline(args: argparse.Namespace) -> None:
    from pulsetrader.data import pipeline

    p = data_paths()
    log.info("resources: %s", resources())
    m = pipeline.run(p.raw, p.root, include_non_regular=args.include_non_regular)
    Path(args.reports).mkdir(parents=True, exist_ok=True)
    (Path(args.reports) / "data_quality_report.md").write_text(pipeline.render_quality_report(m))
    print(json.dumps({k: v for k, v in m.items() if k != "files"}, indent=2, default=str))


def cmd_security(args: argparse.Namespace) -> None:
    from pulsetrader.security import master

    p = data_paths()
    log.info("resources: %s", resources())
    s = master.build(p.canonical, p.reference, Path(args.reports))
    print(json.dumps(s, indent=2, default=str))


def cmd_dataset(args: argparse.Namespace) -> None:
    from pulsetrader.datasets.build import DatasetConfig, build

    p = data_paths()
    log.info("resources: %s", resources())
    cfg = DatasetConfig(universe_size=args.universe, sample_every=args.sample_every)
    m = build(p.root, p.datasets / args.name, cfg)
    print(json.dumps({k: v for k, v in m.items() if k not in ("label_distribution", "universe")}, indent=2))


def cmd_audit(args: argparse.Namespace) -> None:
    from pulsetrader.audit import leakage

    p = data_paths()
    report = leakage.run(p.root, p.datasets / args.name)
    out = Path(args.reports)
    out.mkdir(parents=True, exist_ok=True)
    (out / "leakage_audit_real.json").write_text(json.dumps(report, indent=2, default=str))
    (out / "leakage_audit_real.md").write_text(leakage.render(report))
    print(leakage.render(report))
    if not report["passed"]:
        raise SystemExit("leakage gate FAILED")


def cmd_classical(args: argparse.Namespace) -> None:
    from datetime import UTC, datetime

    from pulsetrader.experiments.classical import RunConfig, run

    p = data_paths()
    log.info("resources: %s", resources())
    cfg = RunConfig(dataset=args.name)
    if args.horizons:
        cfg.horizons = tuple(int(h) for h in args.horizons.split(","))
    if args.thresholds:
        cfg.thresholds = tuple(float(t) for t in args.thresholds.split(","))
    out = p.root / "experiments"
    summary = run(p.root, out, cfg)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    (out / f"phase7_summary-{stamp}.json").write_text(json.dumps(summary, indent=1, default=str))
    print(f"{len(summary)} experiments written to {out}")


def cmd_deep(args: argparse.Namespace) -> None:
    from datetime import UTC, datetime

    from pulsetrader.experiments.deep import run_plan

    p = data_paths()
    log.info("resources: %s", resources())
    out = p.root / "experiments"
    out.mkdir(parents=True, exist_ok=True)
    results = run_plan(p.root, out, args.name, args.stages)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    (out / f"phase8_summary-{stamp}.json").write_text(json.dumps(results, indent=1, default=str))
    print(f"{len(results)} experiments written to {out}")


def cmd_optimize(args: argparse.Namespace) -> None:
    from datetime import UTC, datetime

    from pulsetrader.experiments.optimize import run_phase9

    p = data_paths()
    log.info("resources: %s", resources())
    out = p.root / "experiments"
    phase7_path = Path(args.phase7)
    phase7 = json.loads(phase7_path.read_text()) if phase7_path.exists() else None
    results = run_phase9(p.root, out, args.steps, args.name, phase7, n_trials=args.trials)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    (out / f"phase9_{args.steps}-{stamp}.json").write_text(json.dumps(results, indent=1, default=str))
    print(f"{len(results)} experiments written to {out}")


def cmd_calibrate(args: argparse.Namespace) -> None:
    from pulsetrader.experiments.calibrate import DEFAULT_INPUTS, render_summary, run

    p = data_paths()
    out = p.root / "experiments"
    rows = run(out, tuple(args.inputs.split(",")) if args.inputs else DEFAULT_INPUTS)
    reports = Path(args.reports)
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "phase10_calibration.md").write_text(render_summary(rows))
    slim = [{"experiment": r["experiment"], "result": r["result"]} for r in rows]
    (reports / "phase10_calibration.json").write_text(json.dumps(slim, indent=1, default=str))
    print(f"{len(rows)} calibration experiments written to {out}")


def cmd_robustness(args: argparse.Namespace) -> None:
    from pulsetrader.experiments.robustness import render_summary, run

    p = data_paths()
    rows = run(p.root, p.root / "experiments")
    reports = Path(args.reports)
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "phase11_robustness.md").write_text(render_summary(rows))
    slim = [{"experiment": r["experiment"], "result": r["result"]} for r in rows]
    (reports / "phase11_robustness.json").write_text(json.dumps(slim, indent=1, default=str))
    print(f"{len(rows)} robustness experiments written")


def cmd_backtest(args: argparse.Namespace) -> None:
    from pulsetrader.experiments.backtest import render_summary, run

    p = data_paths()
    rows = run(p.root, p.root / "experiments")
    reports = Path(args.reports)
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "phase12_backtest.md").write_text(render_summary(rows))
    slim = [{"experiment": r["experiment"], "result": r["result"]} for r in rows]
    (reports / "phase12_backtest.json").write_text(json.dumps(slim, indent=1, default=str))
    print(f"{len(rows)} backtest experiments written")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="pulsetrader")
    sub = ap.add_subparsers(required=True)
    f = sub.add_parser("fetch", help="download the Hugging Face dataset into data/raw")
    f.add_argument("--force", action="store_true")
    f.set_defaults(func=cmd_fetch)
    d = sub.add_parser("discover", help="Phase 1: dataset_manifest.json + data_inventory.md")
    d.add_argument("--reports", default="../reports")
    d.add_argument("--no-hash", action="store_true")
    d.set_defaults(func=cmd_discover)
    pp = sub.add_parser("pipeline", help="Phase 2: raw -> validated -> canonical")
    pp.add_argument("--reports", default="../reports")
    pp.add_argument("--include-non-regular", action="store_true")
    pp.set_defaults(func=cmd_pipeline)
    sm = sub.add_parser("security", help="Phase 3: security master, symbol history, corporate actions")
    sm.add_argument("--reports", default="../reports")
    sm.set_defaults(func=cmd_security)
    ds = sub.add_parser("dataset", help="Phases 4-5: features + labels + splits for a research universe")
    ds.add_argument("--name", default="core100_s5")
    ds.add_argument("--universe", type=int, default=100)
    ds.add_argument("--sample-every", type=int, default=5)
    ds.set_defaults(func=cmd_dataset)
    cl = sub.add_parser("classical", help="Phase 7: baselines + classical models, train -> validation")
    cl.add_argument("--name", default="core100_s5")
    cl.add_argument("--horizons", default="", help="comma list, e.g. 5,15 (default: all)")
    cl.add_argument("--thresholds", default="", help="comma list, e.g. 0.001,0.002 (default: all)")
    cl.set_defaults(func=cmd_classical)
    dp = sub.add_parser("deep", help="Phase 8: LSTM/GRU/attention/transformer, train -> validation")
    dp.add_argument("--name", default="core100_s5")
    dp.add_argument("--stages", default="ABC", help="A: architectures, B: lengths, C: other horizons")
    dp.set_defaults(func=cmd_deep)
    op = sub.add_parser("optimize", help="Phase 9: walk-forward, Optuna, feature selection, ensembles")
    op.add_argument("--name", default="core100_s5")
    op.add_argument("--steps", default="WTFE", help="W walk-forward, T Optuna, F features, E ensembles")
    op.add_argument("--trials", type=int, default=25)
    op.add_argument("--phase7", default="../reports/phase7_classical.json")
    op.set_defaults(func=cmd_optimize)
    ca = sub.add_parser("calibrate", help="Phase 10: Platt / isotonic on walk-forward predictions")
    ca.add_argument("--inputs", default="", help="comma-separated Phase 9 walk-forward experiment names")
    ca.add_argument("--reports", default="../reports")
    ca.set_defaults(func=cmd_calibrate)
    rb = sub.add_parser("robustness", help="Phase 11: regimes, sectors, symbols, volatility, costs")
    rb.add_argument("--reports", default="../reports")
    rb.set_defaults(func=cmd_robustness)
    bt = sub.add_parser("backtest", help="Phase 12: portfolio backtests vs buy-and-hold, naive, momentum")
    bt.add_argument("--reports", default="../reports")
    bt.set_defaults(func=cmd_backtest)
    au = sub.add_parser("audit", help="Phase 6: leakage gate on real data for a built dataset")
    au.add_argument("--name", default="core100_s5")
    au.add_argument("--reports", default="../reports")
    au.set_defaults(func=cmd_audit)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
