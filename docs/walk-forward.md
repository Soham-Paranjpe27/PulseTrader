# Walk-forward evaluation (Phase 9)

Code: `ml/src/pulsetrader/experiments/optimize.py`. CLI: `pulsetrader optimize --steps W|T|F|E`.
Results: `reports/phase9_optimization.md`; experiment folders `data/experiments/*-p9-*`.

## Folds
Only the development period (train + validation) is used. The test period is filtered out in the scan.

- The first 40% of training dates are always training data.
- The remaining training dates are cut into 4 equal chronological windows (F1..F4).
- The validation period is the last window (F5).

For every window, a model is trained only on rows before it:
- **expanding**: all earlier training rows; **rolling**: the last 365 days before the window.
- **purge**: a training row is used only if its label ends at or before the window's first bar.
- **embargo**: the first 60 minutes of each pre-validation window are not scored. The validation
  window uses the dataset's own purged and embargoed validation split.
- Early stopping uses the last 10% of the training dates of that window (purged and embargoed again),
  never the scored window.
- The preprocessor (median imputation and scaling) is fit on the training rows of each window only.

Every window is reported separately, plus mean, median, standard deviation, minimum and maximum.
Baselines on the same rows: majority class of the window's training labels and the momentum rule.

## What is chosen where
| Decision | Data used |
|---|---|
| Label threshold per horizon | mean walk-forward MCC over F1..F5 (LightGBM defaults) |
| Optuna hyperparameters | mean MCC on F3 and F4 only (validation unused) |
| Feature set | F4 only (model fit on rows before F4), then validation once |
| Ensemble weights, stacked meta-model, class-bias weights, selective probability threshold | out-of-fold predictions of F1..F4, applied unchanged to validation |
| LightGBM + transformer weight | first half of validation dates, scored on the second half (the transformer has no out-of-fold predictions) |

Nothing is chosen on the test period, which stays unused until model development is finished.
