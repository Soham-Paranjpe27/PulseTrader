"""ML inference service (Phase 14). Phase 0 baseline exposes health/readiness only.

/ready stays false until a model is registered; it never claims readiness without one.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from pulsetrader import __version__

app = FastAPI(title="PulseTrader ML service", version=__version__)
MODEL_DIR = Path(os.environ.get("PULSETRADER_MODEL_DIR", "models"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/ready")
def ready() -> dict[str, object]:
    active = MODEL_DIR / "active.json"
    return {"ready": active.exists(), "reason": None if active.exists() else "NO_ACTIVE_MODEL"}
