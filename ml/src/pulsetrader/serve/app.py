"""ML inference service (Phase 14).

Endpoints: GET /health, GET /ready, POST /predict, POST /predict/batch, GET /models,
GET /models/active, GET /features, GET /metrics.

Models come from the registry (`PULSETRADER_REGISTRY_DIR`, default `$PULSETRADER_DATA_DIR/registry`).
CANDIDATE and SHADOW models are served only when asked for by `model_id`, and every response says
`research_only: true` for them. Without a PRODUCTION model, a request that names no model is refused
with NO_PRODUCTION_MODEL instead of silently using a candidate.

Input per prediction, one of:
- `features`: a feature row produced by the shared feature engine (live pipeline, Phase 17);
- `symbol` + `timestamp` only (HISTORICAL mode): features are read from the research dataset
  (`PULSETRADER_DATASET`, default core100_s5). The test period is refused unless
  `PULSETRADER_ALLOW_TEST_PERIOD=1`.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import Counter, deque
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from pulsetrader import __version__
from pulsetrader.serve.models import ModelServer, ModelUnavailable
from pulsetrader.serve.store import DataUnavailable, HistoricalFeatureStore, TestPeriodLocked

log = logging.getLogger(__name__)
MAX_BATCH = 1000
BT_KEYS = ("total_return", "sharpe", "max_drawdown")

app = FastAPI(title="PulseTrader ML service", version=__version__)


def _data_root() -> Path:
    return Path(os.environ.get("PULSETRADER_DATA_DIR", "data")).resolve()


@lru_cache(maxsize=1)
def server() -> ModelServer:
    root = Path(os.environ.get("PULSETRADER_REGISTRY_DIR", str(_data_root() / "registry")))
    return ModelServer(root)


@lru_cache(maxsize=1)
def store() -> HistoricalFeatureStore | None:
    ds = _data_root() / "datasets" / os.environ.get("PULSETRADER_DATASET", "core100_s5")
    if not (ds / "dataset_manifest.json").exists():
        return None
    return HistoricalFeatureStore(ds, allow_test=os.environ.get("PULSETRADER_ALLOW_TEST_PERIOD") == "1")


def reset() -> None:
    """Drop cached registry/store (tests, or after a registry change)."""
    server.cache_clear()
    store.cache_clear()
    METRICS.clear()


class _Metrics:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.clear()

    def clear(self) -> None:
        self.started = time.time()
        self.requests: Counter[str] = Counter()
        self.errors: Counter[str] = Counter()
        self.directions: Counter[str] = Counter()
        self.abstain: Counter[str] = Counter()
        self.by_model: Counter[str] = Counter()
        self.latency_ms: deque[float] = deque(maxlen=5000)

    def record(self, endpoint: str, preds: list[dict[str, Any]], ms: float) -> None:
        with self.lock:
            self.requests[endpoint] += 1
            self.latency_ms.append(ms)
            for p in preds:
                self.directions[p["direction"]] += 1
                self.by_model[f"{p['model_id']}@v{p['model_version']}"] += 1
                if p["abstain_reason"]:
                    self.abstain[p["abstain_reason"]] += 1

    def error(self, code: str) -> None:
        with self.lock:
            self.errors[code] += 1

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            lat = sorted(self.latency_ms)

            def q(f: float) -> float | None:
                return round(lat[min(len(lat) - 1, int(f * len(lat)))], 3) if lat else None

            n = sum(self.directions.values())
            return {
                "uptime_seconds": round(time.time() - self.started, 1),
                "requests": dict(self.requests),
                "errors": dict(self.errors),
                "predictions": n,
                "directions": dict(self.directions),
                "abstentions": dict(self.abstain),
                "coverage": (n - sum(self.abstain.values())) / n if n else None,
                "by_model": dict(self.by_model),
                "request_latency_ms": {"p50": q(0.5), "p95": q(0.95), "p99": q(0.99)},
            }


METRICS = _Metrics()


class PredictRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=64)
    timestamp: datetime = Field(description="bar start of the latest closed 1-minute bar, with timezone")
    features: dict[str, float | int | None] | None = None
    current_price: float | None = Field(default=None, gt=0)
    model_id: str | None = None
    model_version: int | None = Field(default=None, ge=1)
    task: str | None = None
    max_staleness_seconds: float | None = Field(default=None, gt=0)

    @field_validator("timestamp")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must include a timezone, e.g. 2025-01-06T10:30:00+05:30")
        return v


class BatchRequest(BaseModel):
    items: list[PredictRequest] = Field(min_length=1, max_length=MAX_BATCH)


def _fail(status: int, code: str, detail: str) -> HTTPException:
    METRICS.error(code)
    return HTTPException(status_code=status, detail={"code": code, "message": detail})


def _item(req: PredictRequest) -> dict[str, Any]:
    if req.features is not None:
        return {
            "symbol": req.symbol,
            "market_data_timestamp": req.timestamp,
            "features": req.features,
            "current_price": req.current_price,
            "max_staleness_seconds": req.max_staleness_seconds,
            "data_quality": "CLIENT_SUPPLIED",
        }
    st = store()
    if st is None:
        raise _fail(503, "DATA_UNAVAILABLE", "no historical dataset loaded; send `features`")
    try:
        row = st.lookup(req.symbol, req.timestamp)
    except TestPeriodLocked as e:
        raise _fail(403, "TEST_PERIOD_LOCKED", str(e)) from e
    except DataUnavailable as e:
        raise _fail(404, "DATA_UNAVAILABLE", str(e)) from e
    return {
        **row,
        "current_price": req.current_price,
        "max_staleness_seconds": req.max_staleness_seconds,
        "data_quality": f"VALIDATED_HISTORICAL:{row['split']}",
    }


def _predict(reqs: list[PredictRequest], endpoint: str) -> list[dict[str, Any]]:
    t0 = time.perf_counter()
    srv = server()
    groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    models = {}
    for i, r in enumerate(reqs):
        try:
            m = srv.resolve(r.model_id, r.model_version, r.task)
        except ModelUnavailable as e:
            code = "NO_PRODUCTION_MODEL" if str(e).startswith("NO_PRODUCTION_MODEL") else "MODEL_UNAVAILABLE"
            raise _fail(409 if code == "NO_PRODUCTION_MODEL" else 404, code, str(e)) from e
        models[m.record.key] = m
        groups.setdefault(m.record.key, []).append((i, _item(r)))
    out: list[dict[str, Any] | None] = [None] * len(reqs)
    for key, items in groups.items():
        preds = models[key].predict([it for _, it in items])
        for (i, _), p in zip(items, preds, strict=True):
            out[i] = p
    res = [p for p in out if p is not None]
    METRICS.record(endpoint, res, (time.perf_counter() - t0) * 1e3)
    return res


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/ready")
def ready() -> dict[str, Any]:
    srv = server()
    prod = srv.active()
    if not srv.models:
        return {"ready": False, "reason": "NO_MODEL_LOADED", "load_errors": srv.load_errors}
    return {
        "ready": True,
        "reason": None if prod else "NO_PRODUCTION_MODEL",
        "production_models": [m.record.key for m in prod],
        "loaded_models": sorted(srv.models),
        "historical_mode": store() is not None,
        "load_errors": srv.load_errors,
    }


@app.post("/predict")
def predict(req: PredictRequest) -> dict[str, Any]:
    return _predict([req], "predict")[0]


@app.post("/predict/batch")
def predict_batch(req: BatchRequest) -> dict[str, Any]:
    preds = _predict(req.items, "predict_batch")
    return {"count": len(preds), "predictions": preds}


@app.get("/models")
def models() -> dict[str, Any]:
    srv = server()
    regs = srv.registry.models() if srv.registry.path.exists() else []
    rows = []
    for r in regs:
        v = r.metrics.get("validation", {})
        bt = r.backtest_metrics.get("model_gated|costs", {})
        rows.append(
            {
                "model_id": r.model_id,
                "version": r.version,
                "status": r.status,
                "task": r.task,
                "loaded": r.key in srv.models,
                "created_at": r.created_at,
                "accuracy_gate": r.accuracy_gate,
                "validation": {k: v.get(k) for k in ("accuracy", "balanced_accuracy", "mcc", "coverage")},
                "backtest_gated_after_costs": {k: bt.get(k) for k in BT_KEYS},
                "gates": {g: x["status"] for g, x in r.gates.items()},
                **({"serving": srv.models[r.key].summary()} if r.key in srv.models else {}),
            }
        )  # fmt: skip
    return {"models": rows}


@app.get("/models/active")
def models_active() -> dict[str, Any]:
    prod = server().active()
    return {
        "active": [m.summary() for m in prod],
        "reason": None if prod else "NO_PRODUCTION_MODEL: no model has passed the production gates",
    }


@app.get("/features")
def features(model_id: str | None = None) -> dict[str, Any]:
    srv = server()
    ms = [m for m in srv.models.values() if model_id is None or m.record.model_id == model_id]
    if model_id and not ms:
        raise _fail(404, "MODEL_UNAVAILABLE", f"model {model_id} is not loaded")
    return {
        "models": [
            {
                "model": m.record.key,
                "feature_version": m.feature_version,
                "count": len(m.features),
                "features": [
                    {
                        "name": n,
                        "order": i,
                        "train_median": m.preprocessor.medians[i],
                        "train_mean": m.preprocessor.means[i],
                        "train_std": m.preprocessor.stds[i],
                    }
                    for i, n in enumerate(m.features)
                ],  # fmt: skip
                "missing_value_rule": "missing/non-finite -> training median, then (x - mean) / std",
                "preprocessor_fit_rows": m.preprocessor.fit_rows,
                "preprocessor_fit_period": m.preprocessor.fit_period,
            }
            for m in ms
        ]
    }


@app.get("/metrics")
def metrics() -> dict[str, Any]:
    return METRICS.snapshot()
