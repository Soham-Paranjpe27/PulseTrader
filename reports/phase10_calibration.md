# Phase 10 — probability calibration (validation)

Dataset `dataset-v1-features-v2-labels-v1-u100-s5`. Inputs: Phase 9 walk-forward out-of-fold predictions. Platt and
isotonic (one-vs-rest, renormalised) are chosen on the last pre-validation fold (lowest Brier),
refit on all pre-validation folds and applied unchanged to validation (2024-11-05..2025-06-13). Test period not used.

## lightgbm (tuned) — `y_1m_5bp`

Chosen method: **isotonic**.

| Method | Brier | Log loss | ECE (top class) | ECE (classwise) | Accuracy | Balanced acc | MCC |
|---|---|---|---|---|---|---|---|
| raw | 0.6008 | 1.0082 | 0.0369 | 0.1423 | 50.1% | 45.2% | 0.194 |
| platt | 0.5316 | 0.9057 | 0.0233 | 0.0179 | 59.3% | 39.2% | 0.166 |
| isotonic (chosen) | 0.5316 | 0.9057 | 0.0262 | 0.0192 | 59.3% | 39.1% | 0.165 |

## lightgbm (tuned) — `y_5m_10bp`

Chosen method: **isotonic**.

| Method | Brier | Log loss | ECE (top class) | ECE (classwise) | Accuracy | Balanced acc | MCC |
|---|---|---|---|---|---|---|---|
| raw | 0.6184 | 1.0352 | 0.0276 | 0.1327 | 48.0% | 43.1% | 0.168 |
| platt | 0.5583 | 0.9466 | 0.0135 | 0.0124 | 56.3% | 39.3% | 0.157 |
| isotonic (chosen) | 0.5579 | 0.9460 | 0.0140 | 0.0129 | 56.4% | 39.0% | 0.155 |

## lightgbm (default) — `y_1m_5bp`

Chosen method: **isotonic**.

| Method | Brier | Log loss | ECE (top class) | ECE (classwise) | Accuracy | Balanced acc | MCC |
|---|---|---|---|---|---|---|---|
| raw | 0.5301 | 0.9034 | 0.0134 | 0.0115 | 59.3% | 39.2% | 0.166 |
| platt | 0.5298 | 0.9030 | 0.0070 | 0.0067 | 59.3% | 39.0% | 0.164 |
| isotonic (chosen) | 0.5298 | 0.9031 | 0.0102 | 0.0083 | 59.3% | 38.9% | 0.163 |

## lightgbm (default) — `y_5m_10bp`

Chosen method: **isotonic**.

| Method | Brier | Log loss | ECE (top class) | ECE (classwise) | Accuracy | Balanced acc | MCC |
|---|---|---|---|---|---|---|---|
| raw | 0.5564 | 0.9435 | 0.0057 | 0.0057 | 56.4% | 39.0% | 0.155 |
| platt | 0.5562 | 0.9433 | 0.0043 | 0.0043 | 56.5% | 38.7% | 0.153 |
| isotonic (chosen) | 0.5561 | 0.9430 | 0.0057 | 0.0043 | 56.5% | 38.5% | 0.150 |

## Findings

- **Default models are already well calibrated.** Top-class ECE is 0.006–0.013. Platt and isotonic
  change Brier by less than 0.001.
- **Tuned models are badly calibrated.** Balanced class weights push probabilities away from the true
  class frequencies: classwise ECE is 0.13–0.14. Calibration fixes this (classwise ECE 0.012–0.019,
  Brier 0.601 to 0.532 on y_1m_5bp). Isotonic was chosen on the selection fold for all four models.
  Platt and isotonic are within 0.001 Brier of each other.
- **Calibration changes the decisions of the tuned models.** argmax of the calibrated probabilities
  falls back to the default model's behaviour (y_1m_5bp MCC 0.194 to 0.165, accuracy 50% to 59%).
  - Use the calibrated probability as the reported probability.
  - Keep the class decision on the raw tuned output, or on the Phase 9 class-bias rule.
  - Both probabilities are stored (raw_probability and calibrated_probability in each experiment's
    predictions.parquet).
- **High-confidence predictions are almost all NEUTRAL (no move), not direction.** On y_1m_5bp
  (tuned, raw), rows with top-class confidence ≥ 0.70 are 2.9% of validation, and 32,007 of 32,012 of
  them predict NEUTRAL (accuracy 89.7%). After isotonic, rows ≥ 0.70 are 18.8% of validation and all
  predict NEUTRAL (accuracy 80.7%).
- **Confident UP/DOWN calls stay rare and weak.** At P ≥ 0.50 after calibration they cover 0.3% of rows,
  with sign accuracy 57.2%.
- Success gate: NOT VERIFIED. Test period not used.
