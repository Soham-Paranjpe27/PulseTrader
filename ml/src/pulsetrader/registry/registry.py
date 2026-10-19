"""Model registry (Phase 13).

One JSON file (`registry.json`) under the registry root lists every model version with the fields the
spec requires (model_id, version, dataset/feature/label versions, periods, hyperparameters, metrics,
backtest metrics, calibration version, artifact path, status, created_at), its promotion gates and the
full status history. Artifacts live under `artifacts/{model_id}/v{version}/`.

Statuses and allowed transitions:
    EXPERIMENT -> CANDIDATE | REJECTED
    CANDIDATE  -> SHADOW | REJECTED
    SHADOW     -> PRODUCTION | CANDIDATE | REJECTED
    PRODUCTION -> RETIRED
    RETIRED, REJECTED: final
A transition is refused unless every gate required for the target status is PASSED. Promoting a
version to PRODUCTION retires the previous PRODUCTION version of the same task (label); nothing is
ever promoted automatically.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

REGISTRY_VERSION = "registry-v1"


class Status(StrEnum):
    EXPERIMENT = "EXPERIMENT"
    CANDIDATE = "CANDIDATE"
    SHADOW = "SHADOW"
    PRODUCTION = "PRODUCTION"
    RETIRED = "RETIRED"
    REJECTED = "REJECTED"


TRANSITIONS: dict[Status, set[Status]] = {
    Status.EXPERIMENT: {Status.CANDIDATE, Status.REJECTED},
    Status.CANDIDATE: {Status.SHADOW, Status.REJECTED},
    Status.SHADOW: {Status.PRODUCTION, Status.CANDIDATE, Status.REJECTED},
    Status.PRODUCTION: {Status.RETIRED},
    Status.RETIRED: set(),
    Status.REJECTED: set(),
}


class Gate(StrEnum):
    NO_LEAKAGE = "no_leakage"
    DATA_QUALITY = "no_critical_data_quality"
    VALIDATION = "validation_passed"
    WALK_FORWARD = "walk_forward_passed"
    CALIBRATION = "calibration_passed"
    REPRODUCIBLE = "reproducible"
    BACKTEST = "backtest_passed"
    TEST = "test_passed"
    SHADOW = "shadow_passed"


PASSED, FAILED, NOT_RUN = "PASSED", "FAILED", "NOT_RUN"

_CANDIDATE_GATES = (
    Gate.NO_LEAKAGE,
    Gate.DATA_QUALITY,
    Gate.VALIDATION,
    Gate.WALK_FORWARD,
    Gate.CALIBRATION,
    Gate.REPRODUCIBLE,
)
REQUIRED_GATES: dict[Status, tuple[Gate, ...]] = {
    Status.CANDIDATE: _CANDIDATE_GATES,
    Status.SHADOW: (*_CANDIDATE_GATES, Gate.BACKTEST, Gate.TEST),
    Status.PRODUCTION: (*_CANDIDATE_GATES, Gate.BACKTEST, Gate.TEST, Gate.SHADOW),
}


class RegistryError(ValueError):
    pass


def gate(status: str, evidence: str, **values: Any) -> dict[str, Any]:
    if status not in (PASSED, FAILED, NOT_RUN):
        raise RegistryError(f"bad gate status {status}")
    return {"status": status, "evidence": evidence, **values}


@dataclass
class ModelRecord:
    model_id: str
    version: int
    task: str  # label, e.g. y_5m_10bp
    model_type: str
    dataset_version: str
    feature_version: str
    label_version: str
    training_period: dict[str, Any]
    validation_period: dict[str, Any]
    test_period: dict[str, Any]
    hyperparameters: dict[str, Any]
    metrics: dict[str, Any]
    backtest_metrics: dict[str, Any]
    calibration_version: str | None
    artifact_path: str
    status: str = Status.EXPERIMENT.value
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    gates: dict[str, dict[str, Any]] = field(default_factory=dict)
    accuracy_gate: str = "NOT VERIFIED"  # spec section 39: HIGH_ACCURACY_CANDIDATE or NOT VERIFIED
    source_experiments: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.model_id}@v{self.version}"

    def missing_gates(self, target: Status) -> list[str]:
        return [
            g.value
            for g in REQUIRED_GATES.get(target, ())
            if self.gates.get(g.value, {}).get("status") != PASSED
        ]


class Registry:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "registry.json"

    # storage -------------------------------------------------------------------------------
    def _load(self) -> list[ModelRecord]:
        if not self.path.exists():
            return []
        d = json.loads(self.path.read_text())
        if d.get("registry_version") != REGISTRY_VERSION:
            raise RegistryError(f"unsupported registry version {d.get('registry_version')}")
        return [ModelRecord(**m) for m in d["models"]]

    def _save(self, models: list[ModelRecord]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "registry_version": REGISTRY_VERSION,
            "updated_at": datetime.now(UTC).isoformat(),
            "models": [asdict(m) for m in models],
        }
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".registry-", suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=1, default=str)
        os.replace(tmp, self.path)  # atomic: readers never see a half-written file

    # queries -------------------------------------------------------------------------------
    def models(self, status: Status | None = None) -> list[ModelRecord]:
        ms = self._load()
        return [m for m in ms if status is None or m.status == status]

    def get(self, model_id: str, version: int | None = None) -> ModelRecord:
        ms = [m for m in self._load() if m.model_id == model_id]
        if version is not None:
            ms = [m for m in ms if m.version == version]
        if not ms:
            raise RegistryError(f"no model {model_id}" + (f" v{version}" if version else ""))
        return max(ms, key=lambda m: m.version)

    def active(self, task: str | None = None) -> list[ModelRecord]:
        """PRODUCTION models (one per task at most)."""
        return [m for m in self.models(Status.PRODUCTION) if task is None or m.task == task]

    def next_version(self, model_id: str) -> int:
        return 1 + max((m.version for m in self._load() if m.model_id == model_id), default=0)

    def artifact_dir(self, model_id: str, version: int) -> Path:
        return self.root / "artifacts" / model_id / f"v{version}"

    # mutations -----------------------------------------------------------------------------
    def register(self, rec: ModelRecord, reason: str = "registered") -> ModelRecord:
        ms = self._load()
        if any(m.model_id == rec.model_id and m.version == rec.version for m in ms):
            raise RegistryError(f"{rec.key} already registered")
        if rec.status != Status.EXPERIMENT:
            raise RegistryError("new models start as EXPERIMENT")
        rec.history = [{"at": rec.created_at, "from": None, "to": rec.status, "reason": reason}]
        ms.append(rec)
        self._save(ms)
        return rec

    def update_gates(self, model_id: str, version: int, gates: dict[str, dict[str, Any]]) -> ModelRecord:
        ms = self._load()
        rec = _find(ms, model_id, version)
        rec.gates.update(gates)
        self._save(ms)
        return rec

    def transition(self, model_id: str, version: int, target: Status | str, reason: str) -> ModelRecord:
        target = Status(target)
        ms = self._load()
        rec = _find(ms, model_id, version)
        cur = Status(rec.status)
        if target not in TRANSITIONS[cur]:
            raise RegistryError(f"{rec.key}: {cur} -> {target} is not allowed")
        missing = rec.missing_gates(target)
        if missing:
            raise RegistryError(f"{rec.key}: cannot move to {target}; gates not passed: {missing}")
        if not reason.strip():
            raise RegistryError("a reason is required")
        now = datetime.now(UTC).isoformat()
        if target == Status.PRODUCTION:
            for other in ms:
                if other.status == Status.PRODUCTION and other.task == rec.task and other is not rec:
                    other.history.append(
                        {"at": now, "from": other.status, "to": Status.RETIRED.value,
                         "reason": f"replaced by {rec.key}"}
                    )  # fmt: skip
                    other.status = Status.RETIRED.value
        rec.history.append({"at": now, "from": cur.value, "to": target.value, "reason": reason})
        rec.status = target.value
        self._save(ms)
        return rec


DIGEST_FILE = "sha256.json"


def artifact_digests(art: Path) -> dict[str, str]:
    """SHA-256 of every file in an artifact directory (except the digest file itself)."""
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(art.iterdir())
        if p.is_file() and p.name != DIGEST_FILE
    }


def write_digests(art: Path) -> dict[str, str]:
    d = artifact_digests(art)
    (art / DIGEST_FILE).write_text(json.dumps(d, indent=1, sort_keys=True))
    return d


def verify_digests(art: Path) -> list[str]:
    """Problems with an artifact against its recorded digests; [] when intact or never recorded."""
    f = art / DIGEST_FILE
    if not f.exists():
        return []
    want: dict[str, str] = json.loads(f.read_text())
    have = artifact_digests(art)
    bad = [f"{n} changed" for n in want if n in have and have[n] != want[n]]
    bad += [f"{n} missing" for n in want if n not in have]
    bad += [f"{n} not recorded" for n in have if n not in want]
    return bad


def _find(ms: list[ModelRecord], model_id: str, version: int) -> ModelRecord:
    for m in ms:
        if m.model_id == model_id and m.version == version:
            return m
    raise RegistryError(f"no model {model_id} v{version}")
