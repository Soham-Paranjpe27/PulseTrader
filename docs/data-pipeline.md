# Data pipeline

`raw -> validated -> canonical`, processed one batch of whole symbols at a time so memory stays
bounded even for the 100M-row Hugging Face shards (`ml/src/pulsetrader/data/pipeline.py`,
`processing_version pipeline-v2`).

- **raw/**: downloaded files, read-only. Hashed (SHA-256) into the manifest; the test suite checks
  they are byte-identical after processing.
- **validated/<source_id>/part-*.parquet**: the exception rows of each source (flagged, duplicated or
  outside the regular session), normalised to the canonical schema, plus flags: `f_null`,
  `f_nonpos_price`, `f_neg_volume`, `f_high_lt_low`, `f_ohlc_inconsistent`, `f_duplicate`,
  `session` (REGULAR / PRE_MARKET / POST_MARKET / WEEKEND / DAY), `is_valid`. Clean regular rows are
  not copied here: they are in canonical/, and raw/ remains the complete source. (pipeline-v1 kept
  every row; on the ~720M-row dataset that would be a second full copy the disk cannot hold.)
- **canonical/<SYMBOL>.parquet**: minute bars, one file per symbol: `is_valid` rows, exact (symbol, ts) duplicates removed keeping the first, REGULAR
  session only by default. `_manifest.json` records dataset_version, source_hash, schema_version,
  processing_version, row/symbol counts, min/max timestamp, created_at and per-file drop counts.

Canonical schema: `symbol: str, ts: datetime[us, Asia/Kolkata], open/high/low/close/volume: f64,
session, trade_date`. tz-aware raw timestamps (the HF dataset is UTC) are converted to IST; naive
ones are treated as IST wall-clock.

- **canonical_daily/**: daily bars (frequency detected from the median bar spacing), `session = DAY`.
  The HF daily file stamps bars at 18:30 UTC, which is 00:00 IST of the trading day.
- A symbol found in two source files gets a second file `<SYMBOL>__<source_id>.parquet` and is listed
  under `symbol_collisions` in the manifest.

## Decisions
- Non-regular bars (pre/post-market, weekends) are excluded from canonical but counted and reported.
  Weekend bars in NSE data are usually special sessions (e.g. Muhurat, budget-day trading) or errors;
  they will be inspected individually once the real data is available, and the decision recorded here.
- Exchange holidays: no offline NSE holiday calendar is bundled. Holidays are to be detected from the
  data (days with near-zero market-wide bars) in Phase 2 on real data.
- Missing candles are not forward-filled. `validate.missing_candles` reports per symbol-day gaps
  against the 375 expected regular bars; labels requiring a missing bar are null.
