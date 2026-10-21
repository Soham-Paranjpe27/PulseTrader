# Phase 9 — optimisation and walk-forward (development period only)

Dataset `dataset-v1-features-v2-labels-v1-u100-s5`. Development period 2022-01-03..2025-06-13; the test period (2025-06-16..2026-01-21) was not read.

Walk-forward folds (each scored by a model trained only on earlier, purged rows; first 60 minutes
of each pre-validation fold embargoed; expanding = all earlier data, rolling = last 365 days):

| Fold | Evaluation dates | Role |
|---|---|---|
| F1 | 2023-02-17..2023-07-21 | training period (out-of-fold) |
| F2 | 2023-07-24..2023-12-26 | training period (out-of-fold) |
| F3 | 2023-12-27..2024-06-03 | training period (out-of-fold) |
| F4 | 2024-06-04..2024-11-04 | training period (out-of-fold) |
| F5 | 2024-11-05..2025-06-13 | validation |

## Walk-forward results

| Label | Model | Scheme | Params | Mean acc | Mean bal acc | Mean MCC | Median MCC | Std MCC | Min MCC | Max MCC | Validation MCC | Beats momentum |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| y_1m_20bp | lightgbm | expanding | default | 95.8% | 35.2% | 0.126 | 0.115 | 0.036 | 0.094 | 0.182 | 0.101 | 1/5 |
| y_1m_5bp | lightgbm | expanding | default | 60.9% | 39.4% | 0.174 | 0.174 | 0.006 | 0.166 | 0.181 | 0.166 | 5/5 |
| y_1m_5bp | lightgbm | expanding | tuned | 54.0% | 46.4% | 0.217 | 0.210 | 0.020 | 0.194 | 0.241 | 0.194 | 5/5 |
| y_1m_5bp | xgboost | expanding | default | 60.9% | 39.6% | 0.177 | 0.180 | 0.007 | 0.168 | 0.184 | 0.168 | 5/5 |
| y_1m_5bp | lightgbm | rolling | default | 60.8% | 39.4% | 0.173 | 0.178 | 0.011 | 0.154 | 0.183 | 0.154 | 5/5 |
| y_5m_10bp | lightgbm | expanding | default | 59.5% | 39.1% | 0.165 | 0.167 | 0.006 | 0.155 | 0.170 | 0.155 | 5/5 |
| y_5m_10bp | lightgbm | expanding | tuned | 53.4% | 44.1% | 0.193 | 0.191 | 0.017 | 0.168 | 0.209 | 0.168 | 5/5 |
| y_5m_10bp | xgboost | expanding | default | 59.5% | 39.2% | 0.167 | 0.169 | 0.006 | 0.157 | 0.171 | 0.157 | 5/5 |
| y_5m_10bp | lightgbm | rolling | default | 59.5% | 38.7% | 0.161 | 0.163 | 0.006 | 0.150 | 0.166 | 0.150 | 5/5 |
| y_5m_20bp | lightgbm | expanding | default | 82.2% | 35.6% | 0.136 | 0.140 | 0.009 | 0.120 | 0.142 | 0.120 | 0/5 |
| y_15m_10bp | lightgbm | expanding | default | 44.7% | 41.1% | 0.140 | 0.141 | 0.010 | 0.123 | 0.149 | 0.123 | 5/5 |
| y_15m_20bp | lightgbm | expanding | default | 65.0% | 37.0% | 0.142 | 0.144 | 0.006 | 0.132 | 0.147 | 0.132 | 5/5 |
| y_30m_20bp | lightgbm | expanding | default | 53.1% | 38.3% | 0.137 | 0.140 | 0.008 | 0.122 | 0.143 | 0.122 | 5/5 |
| y_30m_30bp | lightgbm | expanding | default | 67.3% | 35.7% | 0.116 | 0.116 | 0.010 | 0.105 | 0.129 | 0.107 | 4/5 |
| y_60m_20bp | lightgbm | expanding | default | 43.5% | 39.7% | 0.119 | 0.122 | 0.008 | 0.104 | 0.124 | 0.104 | 5/5 |
| y_60m_30bp | lightgbm | expanding | default | 54.8% | 36.9% | 0.118 | 0.118 | 0.010 | 0.108 | 0.128 | 0.108 | 5/5 |

Accuracy and MCC are averaged over all folds including validation. Beats momentum = folds where
MCC is above the momentum rule on the same rows.

## Label threshold per horizon (chosen by mean walk-forward MCC, LightGBM expanding defaults)

| Horizon | Candidates (mean MCC) | Chosen |
|---|---|---|
| 1m | y_1m_5bp (0.174), y_1m_20bp (0.126) | y_1m_5bp |
| 5m | y_5m_10bp (0.165), y_5m_20bp (0.136) | y_5m_10bp |
| 15m | y_15m_20bp (0.142), y_15m_10bp (0.140) | y_15m_20bp |
| 30m | y_30m_20bp (0.137), y_30m_30bp (0.116) | y_30m_20bp |
| 60m | y_60m_20bp (0.119), y_60m_30bp (0.118) | y_60m_20bp |

## Optuna (LightGBM)

| Label | Trials | Objective folds | Default objective | Best objective | Best parameters |
|---|---|---|---|---|---|
| y_1m_5bp | 25 | F3,F4 | 0.1756 | 0.2077 | `{"learning_rate": 0.030798097215384172, "num_leaves": 197, "min_data_in_leaf": 955, "feature_fraction": 0.4740892774009289, "bagging_fraction": 0.7149935014212363, "lambda_l2": 1.5703794150659582, "max_depth": -1, "class_weight": "balanced"}` |
| y_5m_10bp | 25 | F3,F4 | 0.1683 | 0.1909 | `{"learning_rate": 0.030079096692800344, "num_leaves": 18, "min_data_in_leaf": 529, "feature_fraction": 0.4433952597692443, "bagging_fraction": 0.9121370318954606, "lambda_l2": 12.058556610651252, "max_depth": -1, "class_weight": "balanced"}` |

Tuned vs default parameters, full walk-forward (the objective folds are in-sample for the
tuned row, so its validation MCC is the clean comparison):

| Label | Model | Scheme | Params | Mean acc | Mean bal acc | Mean MCC | Median MCC | Std MCC | Min MCC | Max MCC | Validation MCC | Beats momentum |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| y_1m_5bp | lightgbm | expanding | default | 60.9% | 39.4% | 0.174 | 0.174 | 0.006 | 0.166 | 0.181 | 0.166 | 5/5 |
| y_1m_5bp | lightgbm | expanding | tuned | 54.0% | 46.4% | 0.217 | 0.210 | 0.020 | 0.194 | 0.241 | 0.194 | 5/5 |
| y_5m_10bp | lightgbm | expanding | default | 59.5% | 39.1% | 0.165 | 0.167 | 0.006 | 0.155 | 0.170 | 0.155 | 5/5 |
| y_5m_10bp | lightgbm | expanding | tuned | 53.4% | 44.1% | 0.193 | 0.191 | 0.017 | 0.168 | 0.209 | 0.168 | 5/5 |

## Feature selection (y_5m_10bp, decided on fold F4)

| Feature set | Features | MCC (selection fold) |
|---|---|---|
| top30_permutation | 30 | 0.1697 |
| without_market | 66 | 0.1697 |
| without_volume | 79 | 0.1696 |
| top20_permutation | 20 | 0.1693 |
| all | 84 | 0.1693 |
| without_ohlcv | 69 | 0.1691 |
| top50_permutation | 50 | 0.1690 |
| corr_filtered | 71 | 0.1688 |
| without_relative | 78 | 0.1682 |
| without_intraday | 72 | 0.1675 |
| only_technical | 28 | 0.1670 |
| top10_permutation | 10 | 0.1663 |
| without_technical | 56 | 0.1616 |
| only_ohlcv | 15 | 0.1563 |
| only_intraday | 12 | 0.1527 |
| only_relative | 6 | 0.1425 |
| only_market | 18 | 0.0979 |
| only_volume | 5 | 0.0671 |

Chosen: **top20_permutation** (20 features; smallest set within 0.002 MCC of the best on the selection fold).

| Validation | Accuracy | Balanced acc | MCC |
|---|---|---|---|
| all | 56.4% | 39.0% | 0.1551 |
| top20_permutation | 56.4% | 38.8% | 0.1538 |

## Ensembles and thresholds (y_1m_5bp)

| Model | Accuracy | Balanced acc | MCC | + class bias: MCC | Selective t (OOF) | Val coverage | Val selective acc | Val sign acc |
|---|---|---|---|---|---|---|---|---|
| lightgbm | 59.3% | 39.2% | 0.166 | 0.197 | 0.42 | 4.2% | 43.0% | 53.5% |
| xgboost | 59.3% | 39.3% | 0.168 | 0.197 | 0.43 | 4.1% | 42.6% | 53.2% |
| weighted_lgb_xgb | 59.3% | 39.3% | 0.168 | 0.197 | 0.43 | 4.1% | 42.6% | 53.2% |
| stacked_lgb_xgb | 59.3% | 39.0% | 0.164 | – | – | – | – | – |

LightGBM + transformer (weight 0.0 on LightGBM fit on validation dates 2024-11-05..2025-02-20, scored from 2025-02-20, 562,500 rows):

| Model | Accuracy | Balanced acc | MCC |
|---|---|---|---|
| lightgbm | 60.5% | 39.4% | 0.173 |
| transformer | 60.3% | 39.4% | 0.171 |
| weighted_lgb_transformer | 60.3% | 39.4% | 0.171 |


## Ensembles and thresholds (y_5m_10bp)

| Model | Accuracy | Balanced acc | MCC | + class bias: MCC | Selective t (OOF) | Val coverage | Val selective acc | Val sign acc |
|---|---|---|---|---|---|---|---|---|
| lightgbm | 56.4% | 39.0% | 0.155 | 0.177 | 0.42 | 4.8% | 39.8% | 51.2% |
| xgboost | 56.4% | 39.1% | 0.157 | 0.178 | 0.42 | 5.2% | 39.9% | 51.5% |
| weighted_lgb_xgb | 56.4% | 39.1% | 0.157 | 0.178 | 0.42 | 5.0% | 40.0% | 51.5% |
| stacked_lgb_xgb | 56.5% | 38.8% | 0.154 | – | – | – | – | – |

LightGBM + transformer (weight 0.0 on LightGBM fit on validation dates 2024-11-05..2025-02-20, scored from 2025-02-20, 555,000 rows):

| Model | Accuracy | Balanced acc | MCC |
|---|---|---|---|
| lightgbm | 57.5% | 39.1% | 0.161 |
| transformer | 57.4% | 39.5% | 0.165 |
| weighted_lgb_transformer | 57.4% | 39.5% | 0.165 |


## Success gate

No configuration reaches 70% accuracy together with balanced accuracy >= 60% and MCC >= 0.30 on validation. Status: **NOT VERIFIED** (spec section 39).
Test accuracy: not measured (test period unused).

## Findings

- Walk-forward results are stable. MCC changes by about 0.01 (std) across the five windows, and
  validation is the weakest window for every label. LightGBM beats the momentum rule in all 5 windows
  on 7 of the 10 labels (exceptions: y_1m_20bp 1/5, y_5m_20bp 0/5, y_30m_30bp 4/5).
- Label thresholds chosen by walk-forward MCC are 1m 5bp, 5m 10bp, 15m 20bp, 30m 20bp and 60m 20bp
  (60m 30bp is a near tie: 0.118 vs 0.119).
- Optuna gives the largest gain of the phase. It mostly comes from balanced class weights plus a lower
  learning rate.
  - Validation MCC: y_1m_5bp 0.166 to 0.194, and y_5m_10bp 0.155 to 0.168.
  - Validation balanced accuracy: about 39% to 45% (y_1m_5bp) and 43% (y_5m_10bp).
  - Raw accuracy falls (to about 50% and 48%) because the model stops defaulting to NEUTRAL.
  - The same trade-off comes from shifting class weights after training ("class bias": validation
    MCC 0.197 and 0.177).
- Feature selection does not help. Twenty features score about the same as all 84 (validation MCC
  0.154 vs 0.155). Removing the technical group hurts most; market context or volume alone are weak.
- Ensembles do not help. The LightGBM + XGBoost average, the stacked meta-model and LightGBM +
  transformer are all within ±0.004 MCC of the best single model.
- Selective UP/DOWN with a threshold chosen on out-of-fold data covers about 4–5% of validation rows,
  with sign accuracy 51–54%. There is no high-confidence regime.
- Best measured validation result: tuned LightGBM, y_1m_5bp, accuracy 50.1%, balanced accuracy
  45.2%, MCC 0.194, coverage 100%. The 70–80% target is not reached.
