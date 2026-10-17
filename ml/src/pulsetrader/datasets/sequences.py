"""Sequence inputs for Phase 8 deep models, built from a research dataset (framework independent).

Each time step is one sampled dataset row (every `sample_every` minutes) of the same symbol, so a
window of length L covers the L most recent sampled rows up to and including the prediction row.
Rows are only ever looked up backwards, so a window never contains information after its last row.
Windows never span two symbols; rows without a full window are not used as targets.

Feature matrix: the 84 features after the train-fitted Preprocessor (median imputation + scaling),
stored once as float32; windows are gathered on the fly by index arithmetic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from pulsetrader.config import FEATURE_VERSION
from pulsetrader.eval.multiclass import to_index
from pulsetrader.features.preprocess import Preprocessor
from pulsetrader.labels.labels import label_name


@dataclass
class SequenceData:
    X: np.ndarray  # (n_rows, n_features) float32, rows ordered by (symbol, ts)
    first_row: np.ndarray  # (n_rows,) index of the symbol's first row
    labels: dict[str, np.ndarray]  # label name -> class index (0/1/2), -1 where missing
    fret: np.ndarray  # realised return of the horizon (validation scoring)
    fit_idx: np.ndarray
    es_idx: np.ndarray
    val_idx: np.ndarray
    meta: pl.DataFrame  # symbol, ts, split per row
    preprocessor: Preprocessor
    features: list[str]

    def windows(self, idx: np.ndarray, length: int) -> np.ndarray:
        """(len(idx), length, n_features) windows ending at each idx (inclusive)."""
        offs = np.arange(-length + 1, 1)
        return self.X[idx[:, None] + offs[None, :]]

    def usable(self, idx: np.ndarray, length: int) -> np.ndarray:
        """Targets with a full window inside their own symbol."""
        return idx[idx - length + 1 >= self.first_row[idx]]


def build(
    dataset_dir: Path,
    horizon: int,
    thresholds: tuple[float, ...],
    train_every: int = 15,
    es_frac: float = 0.10,
    embargo_minutes: int = 60,
) -> SequenceData:
    from pulsetrader.experiments.classical import inner_split

    features = json.loads((dataset_dir / "features.json").read_text())["features"]
    labels = [label_name(horizon, t) for t in thresholds]
    fret, end = f"fret_{horizon}", f"label_end_ts_{horizon}"
    cols = list(
        dict.fromkeys(
            ["symbol", "ts", "trade_date", "split", "min_since_open", fret, end, *labels, *features]
        )
    )
    df = (
        pl.scan_parquet(dataset_dir / "part-*.parquet")
        # test rows are never loaded; purged rows (split null) are kept only as window history
        .filter(pl.col("trade_date") < _test_start(dataset_dir))
        .select(cols)
        .collect()
        .sort("symbol", "ts")
    )
    n = df.height
    row = np.arange(n)
    sym = df["symbol"].to_numpy()
    starts = np.r_[0, np.flatnonzero(sym[1:] != sym[:-1]) + 1]
    first_row = np.repeat(starts, np.diff(np.r_[starts, n]))

    has_label = df[fret].is_not_null().to_numpy()
    is_train = (df["split"] == "train").fill_null(False).to_numpy()
    on_grid = (df["min_since_open"] % train_every == 0).to_numpy()
    tr_rows = row[is_train & has_label & on_grid]
    tr = df[tr_rows]
    fit_m, es_m = inner_split(tr, horizon, es_frac, embargo_minutes)
    fit_idx, es_idx = tr_rows[fit_m.to_numpy()], tr_rows[es_m.to_numpy()]
    val_idx = row[(df["split"] == "validation").fill_null(False).to_numpy() & has_label]

    pp = Preprocessor.fit(df[fit_idx], features, FEATURE_VERSION)
    X = np.empty((n, len(features)), dtype=np.float32)
    for a in range(0, n, 500_000):  # chunked: a float64 copy of all rows does not fit in RAM
        X[a : a + 500_000] = pp.transform(df[a : a + 500_000])
    lab = {
        name: np.where(df[name].is_null().to_numpy(), -1, to_index(df[name].fill_null(0).to_numpy()))
        for name in labels
    }
    return SequenceData(
        X=X,
        first_row=first_row,
        labels=lab,
        fret=df[fret].fill_null(np.nan).to_numpy().astype(np.float64),
        fit_idx=fit_idx,
        es_idx=es_idx,
        val_idx=val_idx,
        meta=df.select("symbol", "ts", "split"),
        preprocessor=pp,
        features=features,
    )


def _test_start(dataset_dir: Path) -> pl.Expr:
    manifest = json.loads((dataset_dir / "dataset_manifest.json").read_text())
    test = next(p for p in manifest["periods"] if p["name"] == "test")
    return pl.lit(test["start"]).str.to_date()
