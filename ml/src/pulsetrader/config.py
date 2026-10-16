"""Central constants and paths. Secrets come only from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path

IST = "Asia/Kolkata"
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)  # last regular 1-minute bar starts at 15:29
BAR_MINUTES = 1

SCHEMA_VERSION = "canonical-v1"
PROCESSING_VERSION = "pipeline-v2"
FEATURE_VERSION = "features-v1"
LABEL_VERSION = "labels-v1"

HORIZONS = (1, 5, 15, 30, 60)
THRESHOLDS = (0.0005, 0.0010, 0.0020, 0.0030, 0.0050)  # 0.05% .. 0.50%


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def validated(self) -> Path:
        return self.root / "validated"

    @property
    def canonical(self) -> Path:
        return self.root / "canonical"

    @property
    def features(self) -> Path:
        return self.root / "features"

    @property
    def labels(self) -> Path:
        return self.root / "labels"

    @property
    def datasets(self) -> Path:
        return self.root / "datasets"


def data_paths() -> Paths:
    return Paths(Path(os.environ.get("PULSETRADER_DATA_DIR", "data")).resolve())
