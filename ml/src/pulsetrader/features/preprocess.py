"""Train-only preprocessing. Fitted once on the training split, saved, and reused verbatim.

The saved artefact pins feature names and order, imputation values and scaling, so live inference
receives exactly the transformation used in training. Refitting on other data is refused.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import polars as pl


class PreprocessError(ValueError):
    pass


@dataclass
class Preprocessor:
    feature_names: list[str]
    medians: list[float]
    means: list[float]
    stds: list[float]
    fit_rows: int
    fit_period: tuple[str, str]
    feature_version: str

    @classmethod
    def fit(cls, train: pl.DataFrame, feature_names: list[str], feature_version: str) -> Preprocessor:
        if "split" in train.columns and set(train["split"].drop_nulls().unique().to_list()) - {"train"}:
            raise PreprocessError("Preprocessor.fit received non-training rows")
        x = train.select(feature_names).to_numpy().astype(np.float64)
        med = np.nanmedian(x, axis=0)
        med = np.where(np.isnan(med), 0.0, med)
        xi = np.where(np.isnan(x), med, x)
        mean = xi.mean(axis=0)
        std = xi.std(axis=0)
        std = np.where(std < 1e-12, 1.0, std)
        ts = train["ts"]
        return cls(
            list(feature_names),
            med.tolist(),
            mean.tolist(),
            std.tolist(),
            int(train.height),
            (str(ts.min()), str(ts.max())),
            feature_version,
        )

    def transform(self, df: pl.DataFrame, scale: bool = True) -> np.ndarray:
        missing = [c for c in self.feature_names if c not in df.columns]
        if missing:
            raise PreprocessError(f"missing features {missing[:5]}... ({len(missing)})")
        x = df.select(self.feature_names).to_numpy().astype(np.float64)
        med = np.asarray(self.medians)
        x = np.where(np.isnan(x), med, x)
        if scale:
            x = (x - np.asarray(self.means)) / np.asarray(self.stds)
        return x

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=1))

    @classmethod
    def load(cls, path: Path) -> Preprocessor:
        d = json.loads(path.read_text())
        d["fit_period"] = tuple(d["fit_period"])
        return cls(**d)
