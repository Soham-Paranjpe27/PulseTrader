"""Loading registered models and turning feature rows into predictions (Phase 14).

Inference applies exactly what training used: the artifact's feature order, the training-fit
preprocessor (median imputation + standardisation, never refit), the LightGBM booster at its best
iteration and the Phase 10 calibrator. The direction decision uses the raw probabilities (argmax),
because the calibrated argmax loses MCC (Phase 10); the calibrated probabilities are reported.

A prediction abstains (direction NO_PREDICTION) when:
- FEATURES_INVALID: a feature is non-numeric, or more than `max_missing_fraction` are missing;
- MODEL_OUT_OF_DISTRIBUTION: more than `max_ood_fraction` of the features lie more than `ood_abs_z`
  training standard deviations from the training mean, or the symbol is outside the training universe;
- STALE_DATA: the market data is older than the caller's `max_staleness_seconds`;
- LOW_CONFIDENCE: P(predicted direction) is below the model's `min_confidence` (Phase 12 gate chosen
  on pre-validation folds), or the argmax class is NEUTRAL.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from pulsetrader.config import BAR_MINUTES
from pulsetrader.eval.calibration import calibrator_from_json
from pulsetrader.eval.multiclass import CLASSES, DOWN, NEUTRAL, UP
from pulsetrader.features.preprocess import Preprocessor
from pulsetrader.registry.registry import ModelRecord, Registry, Status

SERVABLE = (Status.PRODUCTION, Status.SHADOW, Status.CANDIDATE)


class ModelUnavailable(LookupError):
    pass


@dataclass
class LoadedModel:
    record: ModelRecord
    booster: Any
    preprocessor: Preprocessor
    calibrator: Any
    features: list[str]
    feature_version: str
    universe: set[str]
    serving: dict[str, Any]
    meta: dict[str, Any]
    _mean: np.ndarray = field(init=False, repr=False)
    _std: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.features != self.preprocessor.feature_names:
            raise ValueError(f"{self.record.key}: feature order differs from the preprocessor")
        self._mean = np.asarray(self.preprocessor.means)
        self._std = np.asarray(self.preprocessor.stds)

    @property
    def research_only(self) -> bool:
        return self.record.status != Status.PRODUCTION

    def summary(self) -> dict[str, Any]:
        r = self.record
        return {
            "model_id": r.model_id,
            "version": r.version,
            "status": r.status,
            "task": r.task,
            "horizon_minutes": int(self.meta["horizon"]),
            "label_threshold": float(self.meta["threshold"]),
            "feature_version": self.feature_version,
            "dataset_version": r.dataset_version,
            "calibration_version": r.calibration_version,
            "min_confidence": self.serving["min_confidence"],
            "research_only": self.research_only,
        }

    # ---------------------------------------------------------------------------------------
    def matrix(self, rows: list[dict[str, Any]]) -> tuple[np.ndarray, list[str | None]]:
        """Raw feature matrix in training order (NaN for missing) and a per-row error, if any."""
        X = np.full((len(rows), len(self.features)), np.nan)
        errors: list[str | None] = [None] * len(rows)
        for i, row in enumerate(rows):
            for j, name in enumerate(self.features):
                v = row.get(name)
                if v is None:
                    continue
                if isinstance(v, bool) or not isinstance(v, int | float):
                    errors[i] = f"feature {name} is not numeric"
                    break
                if math.isfinite(v):
                    X[i, j] = float(v)
        return X, errors

    def predict(
        self,
        items: list[dict[str, Any]],
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """items: {symbol, market_data_timestamp (bar start, tz-aware), features, max_staleness_seconds?,
        data_quality?}. Returns one prediction record per item."""
        t0 = datetime.now(UTC)
        X, errors = self.matrix([it["features"] for it in items])
        missing = np.isnan(X)
        Xs = self.preprocessor.transform_array(X)
        z = np.abs(np.where(missing, 0.0, (X - self._mean) / self._std))
        raw = np.asarray(self.booster.predict(Xs)) if len(items) else np.zeros((0, 3))
        cal = self.calibrator.transform(raw) if self.calibrator is not None and len(items) else raw
        latency_ms = (datetime.now(UTC) - t0).total_seconds() * 1e3
        now = now or datetime.now(UTC)
        out = []
        h = int(self.meta["horizon"])
        for i, it in enumerate(items):
            reason = None
            miss_frac = float(missing[i].mean())
            ood_frac = float((z[i] > self.serving["ood_abs_z"]).mean())
            ts: datetime = it["market_data_timestamp"]
            pred_ts = ts + timedelta(minutes=BAR_MINUTES)  # bar closes one minute after its start
            stale = it.get("max_staleness_seconds")
            if errors[i] or miss_frac > self.serving["max_missing_fraction"]:
                reason = "FEATURES_INVALID"
            elif ood_frac > self.serving["max_ood_fraction"] or (
                self.universe and it["symbol"] not in self.universe
            ):
                reason = "MODEL_OUT_OF_DISTRIBUTION"
            elif stale is not None and (now - pred_ts).total_seconds() > float(stale):
                reason = "STALE_DATA"
            k = int(np.argmax(raw[i]))
            p_dir = float(raw[i, k])
            if reason is None and (k == NEUTRAL or p_dir < self.serving["min_confidence"]):
                reason = "LOW_CONFIDENCE"
            out.append(
                {
                    "prediction_id": str(uuid.uuid4()),
                    "symbol": it["symbol"],
                    "prediction_timestamp": pred_ts.isoformat(),
                    "market_data_timestamp": ts.isoformat(),
                    "target_timestamp": (ts + timedelta(minutes=h)).isoformat(),
                    "latency_ms": round(latency_ms / max(len(items), 1), 3),
                    "direction": "NO_PREDICTION" if reason else CLASSES[k],
                    "model_class": CLASSES[k],
                    "abstain_reason": reason,
                    "error": errors[i],
                    "raw_probability": {c.lower(): float(raw[i, j]) for j, c in enumerate(CLASSES)},
                    "calibrated_probability": {c.lower(): float(cal[i, j]) for j, c in enumerate(CLASSES)},
                    "confidence": p_dir if k in (UP, DOWN) else None,
                    "prediction_horizon_minutes": h,
                    "label_threshold": float(self.meta["threshold"]),
                    "current_price": it.get("current_price"),
                    "predicted_price": None,  # no regression model is registered
                    "predicted_return": None,
                    "model_id": self.record.model_id,
                    "model_version": self.record.version,
                    "model_status": self.record.status,
                    "research_only": self.research_only,
                    "feature_version": self.feature_version,
                    "data_version": self.record.dataset_version,
                    "data_quality": it.get("data_quality", "UNKNOWN"),
                    "missing_feature_fraction": miss_frac,
                    "out_of_range_feature_fraction": ood_frac,
                }
            )
        return out


def load_model(registry: Registry, rec: ModelRecord) -> LoadedModel:
    import lightgbm as lgb

    art = registry.root / rec.artifact_path
    for f in ("model.txt", "preprocessor.json", "features.json", "calibrator.json", "model_meta.json",
              "serving.json"):  # fmt: skip
        if not (art / f).exists():
            raise ModelUnavailable(f"{rec.key}: artifact file {f} missing in {art}")
    feats = json.loads((art / "features.json").read_text())
    symbols = art / "symbols.json"
    return LoadedModel(
        record=rec,
        booster=lgb.Booster(model_file=str(art / "model.txt")),
        preprocessor=Preprocessor.load(art / "preprocessor.json"),
        calibrator=calibrator_from_json(json.loads((art / "calibrator.json").read_text())),
        features=list(feats["features"]),
        feature_version=feats["feature_version"],
        universe=set(json.loads(symbols.read_text())["training_universe"]) if symbols.exists() else set(),
        serving=json.loads((art / "serving.json").read_text()),
        meta=json.loads((art / "model_meta.json").read_text()),
    )


class ModelServer:
    """Loads every servable registry model once; resolves which model answers a request."""

    def __init__(self, registry_root: Path) -> None:
        self.registry = Registry(registry_root)
        self.models: dict[str, LoadedModel] = {}
        self.load_errors: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        self.models, self.load_errors = {}, {}
        if not self.registry.path.exists():
            self.load_errors["registry"] = f"no registry at {self.registry.path}"
            return
        for rec in self.registry.models():
            if rec.status not in SERVABLE:
                continue
            try:
                self.models[rec.key] = load_model(self.registry, rec)
            except (ModelUnavailable, OSError, ValueError, KeyError) as e:
                self.load_errors[rec.key] = str(e)

    def active(self, task: str | None = None) -> list[LoadedModel]:
        return [
            m for m in self.models.values()
            if m.record.status == Status.PRODUCTION and (task is None or m.record.task == task)
        ]  # fmt: skip

    def resolve(self, model_id: str | None, version: int | None, task: str | None) -> LoadedModel:
        if model_id:
            hits = [m for m in self.models.values() if m.record.model_id == model_id]
            if version is not None:
                hits = [m for m in hits if m.record.version == version]
            if not hits:
                raise ModelUnavailable(f"model {model_id}" + (f" v{version}" if version else "")
                                       + " is not loaded (not servable or missing)")  # fmt: skip
            return max(hits, key=lambda m: m.record.version)
        active = self.active(task)
        if not active:
            raise ModelUnavailable(
                "NO_PRODUCTION_MODEL: no model has passed the production gates"
                + (f" for task {task}" if task else "")
                + "; pass model_id to query a CANDIDATE/SHADOW model (research only)"
            )
        return active[0]
