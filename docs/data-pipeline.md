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
- Non-regular bars are excluded from canonical but counted, kept in validated/, and reported.
  Investigated on the real data (reports/data_inventory.md, 2026-10-16):
  - Weekend bars are NSE special sessions, not errors: Muhurat 2023-11-12; full Saturday sessions
    2024-01-20 and 2025-02-01 (Union Budget); DR-site drill sessions 2024-03-02 and 2024-05-18; plus
    57 stray bars on 2025-04-26. Weekday Muhurat sessions (2022-10-24, 2024-11-01) appear as
    POST_MARKET. Excluded by default because their liquidity and timing are atypical and labels never
    cross sessions. The two full Saturday sessions could be added later as regular days if needed.
  - Pre/post-market bars on ~65 symbols per day in Mar-Apr 2022 (small counts per symbol) look like
    vendor artefacts; excluded.
- Exchange holidays are detected from the data: weekdays with no bars at all (59 in the minute data,
  e.g. 2024-01-22, 2024-05-20, 2025-02-26) match published NSE holidays; listed in the inventory.
- Missing candles are not forward-filled. `validate.missing_candles` reports per symbol-day gaps
  against the 375 expected regular bars; labels requiring a missing bar are null.
