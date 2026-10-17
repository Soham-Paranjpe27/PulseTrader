import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest  # noqa: E402
from golden import write_raw  # noqa: E402


@pytest.fixture(scope="session")
def golden_dataset(tmp_path_factory):
    """Golden raw -> canonical -> security master -> research dataset `ds` (built once)."""
    from pulsetrader.data import pipeline
    from pulsetrader.datasets.build import DatasetConfig, build
    from pulsetrader.security import master

    root = tmp_path_factory.mktemp("golden_ds")
    write_raw(root / "raw")
    pipeline.run(root / "raw", root)
    master.build(
        root / "canonical",
        root / "reference",
        root / "reports",
        master.Eligibility(min_days=1, max_zero_volume_frac=1.0, min_median_daily_turnover=0),
    )
    cfg = DatasetConfig(
        universe_size=3,
        universe_days=2,
        warmup_bars=50,
        horizons=(5, 15),
        thresholds=(0.001,),
        fractions=(0.6, 0.2, 0.2),
        embargo_minutes=15,
        market_indices={"NIFTY 50": "nifty"},
        vix_symbol=None,
    )
    build(root, root / "datasets" / "ds", cfg)
    return root
