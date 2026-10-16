# Data pipeline

`raw -> validated -> canonical`, processed one source file at a time so memory stays bounded by the
largest single file (`ml/src/pulsetrader/data/pipeline.py`).

- **raw/**: downloaded files, read-only. Hashed (SHA-256) into the manifest; the test suite checks
  they are byte-identical after processing.
- **validated/**: every raw row, normalised to the canonical schema, plus flags: `f_null`,
  `f_nonpos_price`, `f_neg_volume`, `f_high_lt_low`, `f_ohlc_inconsistent`, `f_duplicate`,
  `session` (REGULAR / PRE_MARKET / POST_MARKET / WEEKEND), `is_valid`.
- **canonical/**: `is_valid` rows, exact (symbol, ts) duplicates removed keeping the first, REGULAR
  session only by default. `_manifest.json` records dataset_version, source_hash, schema_version,
  processing_version, row/symbol counts, min/max timestamp, created_at and per-file drop counts.

Canonical schema: `symbol: str, ts: datetime[us, Asia/Kolkata], open/high/low/close/volume: f64,
session, trade_date`. Naive raw timestamps are treated as IST wall-clock.

## Decisions
- Non-regular bars (pre/post-market, weekends) are excluded from canonical but counted and reported.
  Weekend bars in NSE data are usually special sessions (e.g. Muhurat, budget-day trading) or errors;
  they will be inspected individually once the real data is available, and the decision recorded here.
- Exchange holidays: no offline NSE holiday calendar is bundled. Holidays are to be detected from the
  data (days with near-zero market-wide bars) in Phase 2 on real data.
- Missing candles are not forward-filled. `validate.missing_candles` reports per symbol-day gaps
  against the 375 expected regular bars; labels requiring a missing bar are null.
