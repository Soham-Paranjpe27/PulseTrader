"""Command-line entry points: `pulsetrader fetch|discover|pipeline|security|dataset|audit`."""

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
    au = sub.add_parser("audit", help="Phase 6: leakage gate on real data for a built dataset")
    au.add_argument("--name", default="core100_s5")
    au.add_argument("--reports", default="../reports")
    au.set_defaults(func=cmd_audit)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
