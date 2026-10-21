# Phase 17: live pipeline parity (replayed validation session)

Session 2024-12-02 (split: validation) replayed bar by bar through the live pipeline: provider, validation, real-time cache, shared feature engine, local inference. Feed state REPLAY throughout (recorded data is never shown as LIVE). Test period not used.

- Bars: 38625 (38625 accepted, rejected none), minutes 375, sampled prediction bars 75, predictions 15000.
- Feature build per sampled bar: median 0.97s, max 1.30s (100 stocks + indices). Whole replay 76.2s.
- Feature rows: live 7500, research 7500, joined 7500.
- Features matching within tolerance (abs 0.0001 + rel 0.001) on every joined row: 84 of 84.

## Features that differ on some rows

| feature | rows matching | max abs diff | null mismatches |
|---|---|---|---|

## Predictions vs stored walk-forward validation predictions

| model | status | live preds | matched rows | max abs prob diff | median | rows within 0.001 | same argmax class |
|---|---|---|---|---|---|---|---|
| lightgbm-y_1m_5bp-tuned@v1 | CANDIDATE | 7500 | 7500 | 2.98e-08 | 1.17e-08 | 1.0000 | 1.0000 |
| lightgbm-y_5m_10bp-tuned@v1 | CANDIDATE | 7500 | 7400 | 2.98e-08 | 1.18e-08 | 1.0000 | 1.0000 |

Abstention reasons per model: {"lightgbm-y_1m_5bp-tuned@v1": {"LOW_CONFIDENCE": 7485, "null": 4, "MODEL_OUT_OF_DISTRIBUTION": 11}, "lightgbm-y_5m_10bp-tuned@v1": {"null": 17, "LOW_CONFIDENCE": 7472, "MODEL_OUT_OF_DISTRIBUTION": 11}}

# Phase 17: live pipeline parity (replayed validation session)

Session 2025-03-17 (split: validation) replayed bar by bar through the live pipeline: provider, validation, real-time cache, shared feature engine, local inference. Feed state REPLAY throughout (recorded data is never shown as LIVE). Test period not used.

- Bars: 38625 (38625 accepted, rejected none), minutes 375, sampled prediction bars 75, predictions 15000.
- Feature build per sampled bar: median 0.99s, max 3.08s (100 stocks + indices). Whole replay 90.0s.
- Feature rows: live 7500, research 7500, joined 7500.
- Features matching within tolerance (abs 0.0001 + rel 0.001) on every joined row: 84 of 84.

## Features that differ on some rows

| feature | rows matching | max abs diff | null mismatches |
|---|---|---|---|

## Predictions vs stored walk-forward validation predictions

| model | status | live preds | matched rows | max abs prob diff | median | rows within 0.001 | same argmax class |
|---|---|---|---|---|---|---|---|
| lightgbm-y_1m_5bp-tuned@v1 | CANDIDATE | 7500 | 7500 | 2.98e-08 | 1.18e-08 | 1.0000 | 1.0000 |
| lightgbm-y_5m_10bp-tuned@v1 | CANDIDATE | 7500 | 7400 | 2.98e-08 | 1.17e-08 | 1.0000 | 1.0000 |

Abstention reasons per model: {"lightgbm-y_1m_5bp-tuned@v1": {"LOW_CONFIDENCE": 7491, "null": 6, "MODEL_OUT_OF_DISTRIBUTION": 3}, "lightgbm-y_5m_10bp-tuned@v1": {"null": 24, "LOW_CONFIDENCE": 7473, "MODEL_OUT_OF_DISTRIBUTION": 3}}

# Phase 17: live pipeline parity (replayed validation session)

Session 2025-06-13 (split: validation) replayed bar by bar through the live pipeline: provider, validation, real-time cache, shared feature engine, local inference. Feed state REPLAY throughout (recorded data is never shown as LIVE). Test period not used.

- Bars: 38625 (38625 accepted, rejected none), minutes 375, sampled prediction bars 75, predictions 15000.
- Feature build per sampled bar: median 0.97s, max 1.46s (100 stocks + indices). Whole replay 80.6s.
- Feature rows: live 7500, research 7500, joined 7500.
- Features matching within tolerance (abs 0.0001 + rel 0.001) on every joined row: 84 of 84.

## Features that differ on some rows

| feature | rows matching | max abs diff | null mismatches |
|---|---|---|---|

## Predictions vs stored walk-forward validation predictions

| model | status | live preds | matched rows | max abs prob diff | median | rows within 0.001 | same argmax class |
|---|---|---|---|---|---|---|---|
| lightgbm-y_1m_5bp-tuned@v1 | CANDIDATE | 7500 | 7500 | 2.98e-08 | 1.18e-08 | 1.0000 | 1.0000 |
| lightgbm-y_5m_10bp-tuned@v1 | CANDIDATE | 7500 | 7400 | 2.98e-08 | 1.18e-08 | 1.0000 | 1.0000 |

Abstention reasons per model: {"lightgbm-y_1m_5bp-tuned@v1": {"null": 2, "MODEL_OUT_OF_DISTRIBUTION": 25, "LOW_CONFIDENCE": 7473}, "lightgbm-y_5m_10bp-tuned@v1": {"null": 58, "LOW_CONFIDENCE": 7417, "MODEL_OUT_OF_DISTRIBUTION": 25}}
