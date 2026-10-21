"""Phase 14 end-to-end check on real data: the HTTP service must reproduce the walk-forward predictions.

A fixed-seed sample of validation rows is sent through POST /predict/batch in HISTORICAL mode (features
read from the research dataset) and through the `features` input (the same row sent by a client). Raw
probabilities must match the stored Phase 9 validation predictions. The report also gives the
abstention mix and the selective accuracy / coverage of served calls on that sample. Test period not used.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from pulsetrader.eval.multiclass import to_index

SAMPLE = 3000
TOL = 1e-5


def check(data_root: Path, n: int = SAMPLE, seed: int = 0) -> dict[str, Any]:
    from fastapi.testclient import TestClient

    from pulsetrader.serve import app as service

    service.reset()
    client = TestClient(service.app)
    srv = service.server()
    out: dict[str, Any] = {"ready": client.get("/ready").json(), "models": []}
    for key, m in sorted(srv.models.items()):
        src = m.record.source_experiments["walk_forward"]
        preds = pl.read_parquet(data_root / "experiments" / src / "predictions.parquet")
        val = preds.filter(pl.col("fold") == preds["fold"].max())
        rows = val.sample(n=min(n, val.height), seed=seed).sort("ts", "symbol")
        items = [
            {"symbol": s, "timestamp": t.isoformat(), "model_id": m.record.model_id,
             "model_version": m.record.version}
            for s, t in rows.select("symbol", "ts").iter_rows()
        ]  # fmt: skip
        t0 = time.perf_counter()
        served: list[dict[str, Any]] = []
        for i in range(0, len(items), 500):
            r = client.post("/predict/batch", json={"items": items[i : i + 500]})
            r.raise_for_status()
            served += r.json()["predictions"]
        secs = time.perf_counter() - t0
        got = np.array([[p["raw_probability"][c] for c in ("down", "neutral", "up")] for p in served])
        want = rows.select("p_down", "p_neutral", "p_up").to_numpy()
        hist_diff = float(np.max(np.abs(got - want)))

        # same rows sent as client-supplied features (live-style input)
        st = service.store()
        assert st is not None
        k = min(200, len(items))
        feat_items = [
            {**items[i], "features": st.lookup(items[i]["symbol"], rows["ts"][i])["features"]}
            for i in range(k)
        ]
        r = client.post("/predict/batch", json={"items": json.loads(json.dumps(feat_items, default=str))})
        r.raise_for_status()
        got_f = np.array([[p["raw_probability"][c] for c in ("down", "neutral", "up")]
                          for p in r.json()["predictions"]])  # fmt: skip
        feat_diff = float(np.max(np.abs(got_f - want[:k])))

        y = to_index(rows["y_raw"].to_numpy())
        fret = rows["fret"].to_numpy().astype(float)
        dirs = np.array([p["direction"] for p in served])
        called = np.isin(dirs, ["UP", "DOWN"])
        right = np.where(dirs == "UP", fret > 0, fret < 0)
        reasons: dict[str, int] = {}
        for p in served:
            reasons[str(p["abstain_reason"])] = reasons.get(str(p["abstain_reason"]), 0) + 1
        out["models"].append(
            {
                "model": key,
                "status": m.record.status,
                "rows": len(served),
                "seconds": round(secs, 2),
                "rows_per_second": round(len(served) / secs, 1),
                "historical_max_abs_diff": hist_diff,
                "features_input_max_abs_diff": feat_diff,
                "parity_passed": hist_diff <= TOL and feat_diff <= TOL,
                "abstain_reasons": reasons,
                "coverage": float(called.mean()),
                "called": int(called.sum()),
                "sign_accuracy_when_called": float(right[called].mean()) if called.any() else None,
                "label_accuracy_when_called": float(
                    np.mean(np.where(dirs[called] == "UP", 2, 0) == y[called])
                )
                if called.any()
                else None,  # fmt: skip
            }
        )
    test_probe = _test_probe(client, srv, data_root)
    out["test_period_locked"] = test_probe
    out["no_model_named"] = client.post(
        "/predict", json={"symbol": "RELIANCE", "timestamp": "2025-01-06T10:30:00+05:30"}
    ).json()
    out["metrics"] = client.get("/metrics").json()
    return out


def _test_probe(client: Any, srv: Any, data_root: Path) -> dict[str, Any]:
    """A test-period request must be refused (only the timestamp is read, never the row's label)."""
    m = next(iter(srv.models.values()))
    manifest = json.loads((data_root / "datasets" / "core100_s5" / "dataset_manifest.json").read_text())
    test = next(p for p in manifest["periods"] if p["name"] == "test")
    r = client.post(
        "/predict",
        json={"symbol": "RELIANCE", "timestamp": f"{test['start']}T11:00:00+05:30",
              "model_id": m.record.model_id},
    )  # fmt: skip
    return {"status_code": r.status_code, "body": r.json()}


def render(res: dict[str, Any]) -> str:
    lines = [
        "# Phase 14 — ML inference service check (validation sample)",
        "",
        "FastAPI service (`pulsetrader.serve.app`) loaded from the model registry. A fixed-seed sample of",
        "validation rows was sent through `POST /predict/batch`: HISTORICAL mode (features read from the",
        "research dataset) and client-supplied `features`. Raw probabilities are compared with the stored",
        "Phase 9 validation predictions. Test period not used.",
        "",
        f"`/ready`: ready={res['ready']['ready']}, reason={res['ready']['reason']}, "
        f"loaded={', '.join(res['ready']['loaded_models'])}.",
        "",
        "| Model | Status | Rows | Max abs diff (historical) | Max abs diff (features) | Parity | "
        "Coverage | Called | Sign acc when called | Label acc when called | Rows/s |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in res["models"]:
        sa, la = m["sign_accuracy_when_called"], m["label_accuracy_when_called"]
        lines.append(
            f"| {m['model']} | {m['status']} | {m['rows']:,} | {m['historical_max_abs_diff']:.1e} | "
            f"{m['features_input_max_abs_diff']:.1e} | {'PASSED' if m['parity_passed'] else 'FAILED'} | "
            f"{100 * m['coverage']:.1f}% | {m['called']} | {'–' if sa is None else f'{100 * sa:.1f}%'} | "
            f"{'–' if la is None else f'{100 * la:.1f}%'} | {m['rows_per_second']} |"
        )
    lines += ["", "Abstention reasons:", ""]
    for m in res["models"]:
        lines.append(
            f"- {m['model']}: " + ", ".join(f"{k} {v}" for k, v in sorted(m["abstain_reasons"].items()))
        )
    tp = res["test_period_locked"]
    lines += [
        "",
        f"Test-period request: HTTP {tp['status_code']} `{tp['body'].get('detail', {}).get('code')}`.",
        f"Request without model_id: `{res['no_model_named'].get('detail', {}).get('code')}` "
        "(no PRODUCTION model exists).",
        "",
    ]
    return "\n".join(lines)
