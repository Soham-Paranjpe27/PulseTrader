"""Phase 8 runner: sequence models trained on TRAIN, early-stopped on the end of TRAIN, scored on
VALIDATION. The test split is never loaded (datasets/sequences.py stops at the test start date).

Each run writes a new experiment folder (never overwritten) with the same files as Phase 7 plus
model.pt (weights) and training_log.json.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from pulsetrader.config import FEATURE_VERSION, LABEL_VERSION
from pulsetrader.datasets.sequences import SequenceData
from pulsetrader.eval.multiclass import CLASSES, multiclass_report, selective_direction_table
from pulsetrader.experiments.classical import _new_dir, _num, _pct
from pulsetrader.labels.labels import label_name

log = logging.getLogger(__name__)

RUNNER_VERSION = "deep-v1"
SEED = 20261017


@dataclass
class DeepConfig:
    arch: str = "gru"
    length: int = 60
    horizon: int = 5
    threshold: float = 0.0010
    hidden: int = 64
    layers: int = 1
    attn: int = 32
    d_model: int = 64
    heads: int = 4
    dropout: float = 0.1
    lr: float = 1e-3
    weight_decay: float = 1e-5
    batch: int = 512
    samples_per_epoch: int = 400_000
    max_epochs: int = 6
    patience: int = 2
    es_samples: int = 100_000
    threads: int = 4
    seed: int = SEED
    extra: dict[str, Any] = field(default_factory=dict)

    def model_params(self) -> dict[str, Any]:
        return {
            "hidden": self.hidden,
            "layers": self.layers,
            "attn": self.attn,
            "d_model": self.d_model,
            "heads": self.heads,
            "dropout": self.dropout,
        }


def _predict(model: Any, sd: SequenceData, idx: np.ndarray, length: int, batch: int = 4096) -> np.ndarray:
    import torch

    model.eval()
    out = np.empty((len(idx), 3), dtype=np.float64)
    with torch.no_grad():
        for a in range(0, len(idx), batch):
            x = torch.from_numpy(sd.windows(idx[a : a + batch], length))
            out[a : a + batch] = torch.softmax(model(x), dim=1).numpy()
    return out


def train_eval(sd: SequenceData, cfg: DeepConfig, out_root: Path, dataset: dict[str, Any]) -> dict[str, Any]:
    import torch
    from torch import nn

    from pulsetrader.models.deep import make

    torch.manual_seed(cfg.seed)
    torch.set_num_threads(cfg.threads)
    rng = np.random.default_rng(cfg.seed)
    lab = label_name(cfg.horizon, cfg.threshold)
    y_all = sd.labels[lab]
    fit = sd.usable(sd.fit_idx, cfg.length)
    fit = fit[y_all[fit] >= 0]
    es = sd.usable(sd.es_idx, cfg.length)
    es = np.sort(rng.choice(es, size=min(cfg.es_samples, len(es)), replace=False))
    val = sd.usable(sd.val_idx, cfg.length)

    model = make(cfg.arch, sd.X.shape[1], cfg.length, cfg.model_params())
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    loss_fn = nn.CrossEntropyLoss()
    y_es = torch.from_numpy(y_all[es])
    best, best_state, bad, history = float("inf"), None, 0, []
    t0 = time.time()
    for epoch in range(cfg.max_epochs):
        model.train()
        order = rng.choice(fit, size=min(cfg.samples_per_epoch, len(fit)), replace=False)
        total = 0.0
        for a in range(0, len(order), cfg.batch):
            b = order[a : a + cfg.batch]
            x = torch.from_numpy(sd.windows(b, cfg.length))
            y = torch.from_numpy(y_all[b])
            opt.zero_grad()
            loss = loss_fn(model(x), y)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            total += float(loss) * len(b)
        p_es = _predict(model, sd, es, cfg.length)
        es_loss = float(loss_fn(torch.from_numpy(np.log(np.clip(p_es, 1e-7, 1))), y_es))
        history.append(
            {
                "epoch": epoch,
                "train_loss": total / len(order),
                "es_loss": es_loss,
                "s": round(time.time() - t0),
            }
        )
        log.info(
            "%s L=%d %s epoch %d train %.4f es %.4f (%ds)",
            cfg.arch, cfg.length, lab, epoch, total / len(order), es_loss, time.time() - t0,
        )  # fmt: skip
        if es_loss < best - 1e-5:
            best, bad = es_loss, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= cfg.patience:
                break
    assert best_state is not None
    model.load_state_dict(best_state)
    train_seconds = time.time() - t0

    y_val = y_all[val]
    proba = _predict(model, sd, val, cfg.length)
    rep = multiclass_report(y_val, proba)
    rep["selective"] = selective_direction_table(y_val, proba, sd.fret[val])
    tr_idx = np.sort(rng.choice(fit, size=min(200_000, len(fit)), replace=False))
    tr = multiclass_report(y_all[tr_idx], _predict(model, sd, tr_idx, cfg.length))
    rep["train_sample"] = {k: tr[k] for k in ("accuracy", "balanced_accuracy", "mcc", "macro_f1")}
    rep["best_epoch"] = int(np.argmin([h["es_loss"] for h in history]))
    rep["seconds"] = round(time.time() - t0, 1)
    rep["n_parameters"] = int(sum(p.numel() for p in model.parameters()))

    cfg_dict = asdict(cfg)
    cfg_dict.update({"label": lab, "features": sd.features})
    key = hashlib.sha1(json.dumps(cfg_dict, sort_keys=True, default=str).encode()).hexdigest()[:8]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    d = _new_dir(out_root, f"{stamp}-p8-{cfg.arch}-L{cfg.length}-{lab}-{key}")
    experiment = {
        "experiment_id": d.name,
        "runner_version": RUNNER_VERSION,
        "phase": 8,
        **dataset,
        "feature_version": FEATURE_VERSION,
        "label_version": LABEL_VERSION,
        "label": lab,
        "horizon_minutes": cfg.horizon,
        "threshold": cfg.threshold,
        "model": cfg.arch,
        "sequence_length": cfg.length,
        "seed": cfg.seed,
        "rows": {"fit": len(fit), "early_stop": len(es), "validation": len(val)},
        "train_seconds": round(train_seconds),
        "created_at": datetime.now(UTC).isoformat(),
    }
    preds = sd.meta[val].with_columns(
        pl.Series("y", y_val, dtype=pl.Int8),
        *[pl.Series(f"p_{c.lower()}", proba[:, k], dtype=pl.Float32) for k, c in enumerate(CLASSES)],
    )
    (d / "experiment.json").write_text(json.dumps(experiment, indent=2, default=str))
    (d / "config.json").write_text(json.dumps(cfg_dict, indent=2, default=str))
    (d / "metrics.json").write_text(json.dumps({cfg.arch: rep}, indent=2, default=str))
    (d / "training_log.json").write_text(json.dumps(history, indent=1))
    (d / "feature_importance.json").write_text(json.dumps({"note": "not computed for sequence models"}))
    sd.preprocessor.save(d / "preprocessor.json")
    preds.write_parquet(d / "predictions.parquet")
    torch.save(model.state_dict(), d / "model.pt")
    (d / "report.md").write_text(_report(experiment, rep, history))
    return {"experiment": experiment, "metrics": {cfg.arch: _compact(rep)}}


def _compact(r: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "accuracy", "balanced_accuracy", "macro_f1", "mcc", "roc_auc_ovr", "updown_auc", "brier",
        "ece_top", "log_loss", "coverage", "verdict", "class_distribution", "pred_distribution",
        "train_sample", "best_epoch", "seconds", "n_parameters",
    )  # fmt: skip
    return {**{k: r.get(k) for k in keys}, "selective": r["selective"]}


def _report(e: dict[str, Any], r: dict[str, Any], history: list[dict[str, Any]]) -> str:
    lines = [
        f"# {e['experiment_id']}",
        "",
        f"{e['model']} (sequence length {e['sequence_length']}) on `{e['label']}`. "
        "Validation only; test unused.",
        "",
        f"Accuracy {_pct(r['accuracy'])}, balanced accuracy {_pct(r['balanced_accuracy'])}, macro F1 "
        f"{_num(r['macro_f1'])}, MCC {_num(r['mcc'])}, ROC-AUC {_num(r['roc_auc_ovr'])}, up/down AUC "
        f"{_num(r['updown_auc'])}, Brier {_num(r['brier'])}, ECE {_num(r['ece_top'])}, coverage 100%. "
        f"Verdict: {r['verdict']}.",
        "",
        "| Epoch | Train loss | Early-stop loss |",
        "|---|---|---|",
        *[f"| {h['epoch']} | {h['train_loss']:.4f} | {h['es_loss']:.4f} |" for h in history],
        "",
        "| P threshold | Predictions | Coverage | Accuracy | Sign accuracy | MCC |",
        "|---|---|---|---|---|---|",
        *[
            f"| {s['threshold']:.2f} | {s['n_predictions']:,} | {_pct(s['coverage'])} | "
            f"{_pct(s.get('accuracy'))} | {_pct(s.get('sign_accuracy'))} | {_num(s.get('mcc'))} |"
            for s in r["selective"]
        ],
        "",
    ]
    return "\n".join(lines)


STAGE_C_LABELS = ((1, 0.0005), (15, 0.0020), (30, 0.0020), (60, 0.0030))


def run_plan(
    data_root: Path,
    out_root: Path,
    dataset: str = "core100_s5",
    stages: str = "ABC",
    arch: str | None = None,
    length: int | None = None,
    lengths: tuple[int, ...] = (30, 120, 252),
    **overrides: Any,
) -> list[dict[str, Any]]:
    """A: every architecture, length 60, on y_5m_10bp. B: the best of A at lengths 30/120/252.
    C: the best (architecture, length) on the best Phase 7 threshold of the other horizons.
    "Best" = highest validation MCC (validation is the model-selection set; test stays unused).
    `arch` / `length` fix the choice when earlier stages ran in a previous invocation. Longer
    windows cost more per sample, so stage B scales samples per epoch by 60/length (equal compute)
    and caps epochs at 4."""
    from pulsetrader.config import THRESHOLDS
    from pulsetrader.datasets.sequences import build
    from pulsetrader.models.deep import ARCHITECTURES

    ds_dir = data_root / "datasets" / dataset
    manifest = json.loads((ds_dir / "dataset_manifest.json").read_text())
    periods = {p["name"]: p for p in manifest["periods"]}
    info = {
        "dataset_id": manifest["dataset_id"],
        "dataset": dataset,
        "train_period": periods["train"],
        "validation_period": periods["validation"],
        "test_period": {**periods["test"], "used": False},
    }
    results: list[dict[str, Any]] = []

    def mcc(r: dict[str, Any]) -> float:
        return float(next(iter(r["metrics"].values()))["mcc"])

    best_arch, best_len = arch or "gru", length or 60
    sd = build(ds_dir, 5, THRESHOLDS) if ("A" in stages or "B" in stages) else None
    if "A" in stages and sd is not None:
        stage = [
            train_eval(sd, DeepConfig(arch=a, length=60, **overrides), out_root, info) for a in ARCHITECTURES
        ]
        results += stage
        best_arch = max(stage, key=mcc)["experiment"]["model"]
    if "B" in stages and sd is not None:
        stage = [
            train_eval(
                sd,
                DeepConfig(
                    arch=best_arch,
                    length=n,
                    samples_per_epoch=min(400_000, 400_000 * 60 // n),
                    max_epochs=6 if n <= 60 else 4,
                    **overrides,
                ),
                out_root,
                info,
            )
            for n in lengths
        ]
        results += stage
        pool = stage + [r for r in results if r["experiment"]["model"] == best_arch]
        best_len = max(pool, key=mcc)["experiment"]["sequence_length"]
    del sd
    if "C" in stages:
        for h, t in STAGE_C_LABELS:
            sdh = build(ds_dir, h, THRESHOLDS)
            cfg = DeepConfig(arch=best_arch, length=best_len, horizon=h, threshold=t, **overrides)
            results.append(train_eval(sdh, cfg, out_root, info))
            del sdh
    return results


def collect(out_root: Path) -> list[dict[str, Any]]:
    """All Phase 8 experiment folders (metrics + experiment.json), oldest first."""
    rows = []
    for d in sorted(out_root.glob("*-p8-*")):
        if not (d / "metrics.json").exists():
            continue
        e = json.loads((d / "experiment.json").read_text())
        if e.get("dataset_id") == "probe":
            continue
        m = json.loads((d / "metrics.json").read_text())
        rows.append({"experiment": e, "metrics": {k: _compact(v) for k, v in m.items()}})
    return rows


def render_summary(rows: list[dict[str, Any]], phase7: list[dict[str, Any]]) -> str:
    """Phase 8 report: every deep run next to the best Phase 7 model on the same label."""
    p7: dict[str, tuple[str, dict[str, Any]]] = {}
    for s in phase7:
        lab = s["experiment"]["label"]
        m = s["metrics"]
        best = max(
            (n for n in ("logistic", "random_forest", "xgboost", "lightgbm") if n in m),
            key=lambda n: m[n]["mcc"],
        )
        p7[lab] = (best, m[best])
    e0 = rows[0]["experiment"]
    lines = [
        "# Phase 8 — deep sequence models (validation)",
        "",
        f"Dataset `{e0['dataset_id']}`. Trained on "
        f"{e0['train_period']['start']}..{e0['train_period']['end']},"
        f" scored on validation {e0['validation_period']['start']}..{e0['validation_period']['end']}."
        " Test period not used. PyTorch on 4 CPU threads, no GPU.",
        "",
        "Each time step is one 5-minute dataset row of the same stock (84 features after the train-fitted",
        "preprocessor). Stage A compares architectures at 60 steps on `y_5m_10bp`; stage B varies the",
        "history length for the best architecture (samples per epoch scaled by 60/length, 4 epochs max);",
        "stage C runs the best (architecture, length) on the best Phase 7 threshold of each other horizon.",
        "Selection uses validation MCC.",
        "",
        "| Label | Model | Steps | Accuracy | Balanced acc | Macro F1 | MCC | ROC-AUC | Up/down AUC* |"
        " Brier | ECE | Train-sample acc | Best Phase 7 (MCC) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        e = r["experiment"]
        m = next(iter(r["metrics"].values()))
        b = p7.get(e["label"])
        ref = f"{b[0]} ({_num(b[1]['mcc'])})" if b else "–"
        tr = (m.get("train_sample") or {}).get("accuracy")
        lines.append(
            f"| {e['label']} | {e['model']} | {e['sequence_length']} | {_pct(m['accuracy'])} | "
            f"{_pct(m['balanced_accuracy'])} | {_num(m['macro_f1'])} | {_num(m['mcc'])} | "
            f"{_num(m['roc_auc_ovr'])} | {_num(m.get('updown_auc'))} | {_num(m['brier'])} | "
            f"{_num(m['ece_top'])} | {_pct(tr)} | {ref} |"
        )
    lines += [
        "",
        "*Up/down AUC: diagnostic on rows whose label moved (subset chosen by the outcome).",
        "",
        "## Selective UP/DOWN (best deep run per label)",
        "",
        "| Label | Model | P threshold | Predictions | Coverage | Accuracy | Sign accuracy | MCC |",
        "|---|---|---|---|---|---|---|---|",
    ]
    best_by_label: dict[str, dict[str, Any]] = {}
    for r in rows:
        lab = r["experiment"]["label"]
        m = next(iter(r["metrics"].values()))
        if lab not in best_by_label or m["mcc"] > next(iter(best_by_label[lab]["metrics"].values()))["mcc"]:
            best_by_label[lab] = r
    for lab, r in best_by_label.items():
        m = next(iter(r["metrics"].values()))
        for s in m["selective"]:
            lines.append(
                f"| {lab} | {r['experiment']['model']} L{r['experiment']['sequence_length']} | "
                f"{s['threshold']:.2f} | {s['n_predictions']:,} | {_pct(s['coverage'])} | "
                f"{_pct(s.get('accuracy'))} | {_pct(s.get('sign_accuracy'))} | {_num(s.get('mcc'))} |"
            )
    lines.append("")
    return "\n".join(lines)
