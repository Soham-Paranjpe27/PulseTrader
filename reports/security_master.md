# Security master

`secmaster-v1`, built 2026-10-17T10:33:41.150542+00:00 from canonical minute data 2022-01-03 .. 2026-01-21. All figures computed from the data.

| Metric | Value |
|---|---|
| symbols | 2535 |
| type EQUITY | 2116 |
| type ETF | 287 |
| type INDEX | 129 |
| type OTHER | 3 |
| status ACTIVE | 1752 |
| status LISTED_LATER | 783 |
| experiment-eligible equities | 1311 |
| rename candidates | 0 |

Eligibility (EQUITY only): min_days=250, max_zero_volume_frac=0.2, min_median_daily_turnover=10000000.0. Turnover is close x volume summed over regular-session minute bars, in INR.

## Limitations

- No official NSE security master is reachable offline; ETF and other types come from a curated list (`ml/src/pulsetrader/security/lists.py`), indices from names and zero volume.
- Symbol history covers only symbols present in this dataset (2022-01 onward). Renames are inferred candidates, not confirmed. Securities delisted before 2022 are absent, so survivorship bias before the data start cannot be measured; symbols that ENDED inside the window are kept.

- **Survivorship bias:** no symbol stops trading before the dataset end, so the dataset holds only securities still listed when it was downloaded. Stocks delisted or merged away during 2022-2026 are missing. Results are therefore biased toward survivors; this cannot be corrected offline and must be stated with every result.

## Indices with traded volume (check)

None.

## Equities with almost no traded volume (excluded by eligibility)

None.

## Uncertain classifications

| symbol | instrument_type | basis | median_close |
|---|---|---|---|
| ABGSEC | ETF | curated ETF list | 108.5 |
| CONS | ETF | curated ETF list | 104.9 |
| EUROBOND | EQUITY | default (not index/ETF/other) | 162.4 |
| GOLDBND | OTHER | curated debt/commodity list | 136.3 |
| IT | ETF | curated ETF list | 36.35 |
| SILVERBND | OTHER | curated debt/commodity list | 233.4 |
| SILVERTUC | EQUITY | default (not index/ETF/other) | 657 |
| SSDL | OTHER | curated debt/commodity list | 96.33 |

## Rename candidates

None.
