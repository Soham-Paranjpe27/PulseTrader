# Corporate-action audit

Generated from canonical minute data (regular session). Suspicious events are overnight gaps above 20% (NSE price bands cap most stocks at 20%/day) and single-minute moves above 20% inside a session. Gaps close to a split/bonus ratio are labelled.

## Finding: prices are already adjusted

Known corporate actions show no price discontinuity in this dataset, e.g. RELIANCE 1:1 bonus (ex-date 2024-10-28): close 1328.15 on 2024-10-25, open 1337.00 on 2024-10-28. The vendor (Upstox, per the dataset card) back-adjusts history. Consequences:

- Absolute price levels before an action are not what traded at the time; only scale-free features (returns, ratios, normalised indicators) are point-in-time safe. Raw price levels must not be used as model inputs.
- Adjustment uses information from after the action date (future corporate actions). Returns and ratios are unaffected by a multiplicative adjustment, so they carry no leakage from it.
- Residual unadjusted actions show up as the events below and are handled by the policy.

## Event counts

| Scope | Events | Symbols |
|---|---|---|
| all instruments | 409 | 288 |
| equities: overnight gaps | 148 | 134 |
| equities: gaps at split/bonus ratios | 18 | 16 |
| equities: intraday jumps | 178 | 123 |

## Largest equity overnight gaps

| symbol | trade_date | calendar_days_since_prev | move | prev_close | open | ratio_match |
|---|---|---|---|---|---|---|
| VINNY | 2022-11-28 | 28 | 19.09 | 2.85 | 57.27 |  |
| EXCEL | 2022-04-21 | 1 | 12.91 | 0.55 | 7.65 |  |
| BSHSL | 2022-03-29 | 1 | 9.049 | 40.8 | 410 | consolidation 10:1 |
| MINDTECK | 2024-09-30 | 3 | 8.966 | 293 | 2920 | consolidation 10:1 |
| SHEKHAWATI | 2024-09-10 | 14 | 8.799 | 8.82 | 86.43 | consolidation 10:1 |
| GVPTECH | 2022-09-22 | 1 | 4.481 | 6.75 | 37 |  |
| BCG | 2025-07-14 | 196 | 1.121 | 10.28 | 21.8 |  |
| SHRADHA | 2022-09-22 | 1 | 1.081 | 11.92 | 24.8 |  |
| VINNY | 2023-01-12 | 1 | -0.9586 | 114.6 | 4.74 |  |
| EXCEL | 2022-06-21 | 1 | -0.9346 | 5.35 | 0.35 |  |
| EXCEL | 2022-03-29 | 1 | -0.9296 | 7.1 | 0.5 |  |
| DRCSYSTEMS | 2022-03-21 | 7 | -0.9044 | 128.1 | 12.25 |  |
| BSHSL | 2022-06-21 | 1 | -0.9028 | 391 | 38 | split/bonus 10:1 |
| DEVIT | 2022-05-06 | 1 | 0.901 | 38.98 | 74.1 |  |
| MINDTECK | 2024-11-08 | 1 | -0.9 | 2830 | 283 | split/bonus 10:1 |
| FISCHER | 2025-07-11 | 1 | -0.8963 | 775 | 80.4 |  |
| NDLVENTURE | 2022-11-22 | 1 | -0.8539 | 448 | 65.45 |  |
| GVPTECH | 2022-12-06 | 1 | -0.7982 | 91.2 | 18.4 | split/bonus 5:1 |
| KSHITIJPOL | 2022-08-25 | 1 | -0.7981 | 66.87 | 13.5 | split/bonus 5:1 |
| AKI | 2023-05-23 | 1 | -0.7913 | 110.2 | 23 |  |
| SUMEETINDS | 2025-06-20 | 1 | -0.79 | 55.96 | 11.75 |  |
| TVSHLTD | 2023-08-24 | 1 | 0.7727 | 3159 | 5600 |  |
| BOROLTD | 2023-12-05 | 1 | 0.7581 | 238.9 | 420 |  |
| SHANKARA | 2025-09-24 | 1 | -0.7551 | 989 | 242.2 | split/bonus 4:1 |
| MIRZAINT | 2023-03-29 | 1 | -0.7513 | 148.4 | 36.9 | split/bonus 4:1 |
| NMDC | 2022-10-27 | 2 | 0.7083 | 16.32 | 27.88 |  |
| DCMSRIND | 2025-12-26 | 2 | -0.7045 | 172.6 | 51 |  |
| NIITLTD | 2023-06-08 | 1 | -0.6953 | 408 | 124.3 |  |
| ROSSELLIND | 2024-09-20 | 1 | -0.6827 | 630.4 | 200 |  |
| ALLCARGO | 2025-11-12 | 1 | -0.6636 | 33.89 | 11.4 | split/bonus 3:1 |
| RAYMOND | 2025-05-14 | 1 | -0.6617 | 1552 | 525 | split/bonus 3:1 |
| ESSENTIA | 2022-02-07 | 7 | -0.6531 | 2.45 | 0.85 |  |
| ABFRL | 2025-05-22 | 1 | -0.6399 | 270.9 | 97.55 |  |
| STAR | 2024-12-06 | 1 | -0.5623 | 1485 | 650 |  |
| MHLXMIRU | 2024-04-19 | 1 | 0.5538 | 128.6 | 199.9 |  |
| SKFINDIA | 2025-10-15 | 1 | -0.5534 | 5040 | 2251 |  |
| DCI | 2022-01-10 | 3 | -0.5458 | 96 | 43.6 |  |
| QUESS | 2025-04-15 | 4 | -0.5298 | 604 | 284 |  |
| SONAMLTD | 2022-07-14 | 1 | -0.5265 | 44.35 | 21 |  |
| DEVIT | 2022-06-21 | 1 | -0.5002 | 60.02 | 30 | split/bonus 2:1 |

## Gaps matching split/bonus ratios

| symbol | trade_date | move | prev_close | open | ratio_match | volume_vs_median |
|---|---|---|---|---|---|---|
| BSHSL | 2022-03-29 | 9.049 | 40.8 | 410 | consolidation 10:1 |  |
| BSHSL | 2022-06-21 | -0.9028 | 391 | 38 | split/bonus 10:1 |  |
| DEVIT | 2022-06-21 | -0.5002 | 60.02 | 30 | split/bonus 2:1 |  |
| KSHITIJPOL | 2022-08-25 | -0.7981 | 66.87 | 13.5 | split/bonus 5:1 |  |
| GVPTECH | 2022-12-06 | -0.7982 | 91.2 | 18.4 | split/bonus 5:1 |  |
| SHRADHA | 2022-12-06 | -0.4865 | 26.64 | 13.68 | split/bonus 2:1 |  |
| MIRZAINT | 2023-03-29 | -0.7513 | 148.4 | 36.9 | split/bonus 4:1 |  |
| DCMFINSERV | 2023-10-16 | -0.3333 | 6.75 | 4.5 | split/bonus 1.5:1 |  |
| SHEKHAWATI | 2024-09-10 | 8.799 | 8.82 | 86.43 | consolidation 10:1 |  |
| MINDTECK | 2024-09-30 | 8.966 | 293 | 2920 | consolidation 10:1 |  |
| MASKINVEST | 2024-10-28 | 0.499 | 144 | 215.9 | consolidation 1.5:1 |  |
| MINDTECK | 2024-11-08 | -0.9 | 2830 | 283 | split/bonus 10:1 |  |
| SIEMENS | 2025-04-07 | -0.4902 | 4904 | 2500 | split/bonus 2:1 |  |
| CPCAP | 2025-05-09 | -0.3367 | 392 | 260 | split/bonus 1.5:1 |  |
| RAYMOND | 2025-05-14 | -0.6617 | 1552 | 525 | split/bonus 3:1 |  |
| VRLLOG | 2025-08-14 | -0.4982 | 558 | 280 | split/bonus 2:1 |  |
| SHANKARA | 2025-09-24 | -0.7551 | 989 | 242.2 | split/bonus 4:1 |  |
| ALLCARGO | 2025-11-12 | -0.6636 | 33.89 | 11.4 | split/bonus 3:1 |  |

## Policy

- Events are stored in `data/reference/corporate_action_events.parquet`.
- Labels never cross a session boundary, so an overnight gap never enters a label.
- Features whose rolling window spans a flagged OVERNIGHT_GAP for that symbol are distorted; the event session and the next session of that symbol are excluded from training/evaluation datasets (`flagged_days`, applied when datasets are built). Extreme returns are never treated as opportunities by default.
- Large gaps that match no ratio are mostly unadjusted demergers (e.g. RAYMOND 2025-05-14, ABFRL 2025-05-22, SKFINDIA 2025-10-15) or resumption after a suspension (calendar_days_since_prev large); both are excluded by the same rule.
