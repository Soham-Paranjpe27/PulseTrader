# Model evaluation

Code: `ml/src/pulsetrader/eval/multiclass.py` (3-class task), `ml/src/pulsetrader/eval/metrics.py` (binary).

## Task
Labels are DOWN / NEUTRAL / UP for a horizon h and threshold t (`y_{h}m_{bp}`, see labels.md).
Models output P(DOWN), P(NEUTRAL), P(UP).

## Full-coverage metrics (every experiment)
Accuracy, balanced accuracy, macro precision / recall / F1, MCC, one-vs-rest ROC-AUC, macro PR-AUC,
multiclass Brier, log loss, top-class ECE, confusion matrix, class and prediction distributions.
`updown_auc` is a diagnostic: ROC-AUC of P(UP) - P(DOWN) on rows whose label moved. The subset is
chosen by the outcome, so it measures pure direction skill and is never quoted as an accuracy.

Verdict: accuracy >= 70% with balanced accuracy < 55% or MCC < 0.10 is
`FAILED — MAJORITY/IMBALANCE BEHAVIOR`. Everything else is `NOT VERIFIED` until the full success gate
(walk-forward, calibration, regimes, symbols, reproducibility) passes in later phases.

## Selective prediction (PREDICT UP / PREDICT DOWN / NO PREDICTION)
Direction = UP if P(UP) >= P(DOWN) else DOWN. Predict only when that probability >= p and beats
P(NEUTRAL). For p in 0.40..0.90 report predictions, coverage (share of ALL rows), accuracy (an
actual NEUTRAL counts as wrong), sign accuracy (vs the realised return), balanced accuracy, MCC,
precision and recall per direction.

## Protocol (Phase 7)
- Fit on the training split only; validation scores every row; the test split is not read.
- Boosted trees early-stop on the last 10% of training dates, purged and embargoed (60 min).
- One `Preprocessor` (train-only medians, means, stds) per horizon, saved with the experiment.
- Each run writes a new folder in `data/experiments/` (never overwritten): experiment.json,
  config.json, metrics.json, feature_importance.json, report.md, predictions.parquet, preprocessor.json.
- Baselines: majority, stratified random, no-change (naive price), always-up (buy-and-hold view),
  momentum (class of the past return over the same horizon, same threshold).

## Calibration (Phase 10)
`eval/calibration.py`: one-vs-rest Platt (logistic on logit p) and isotonic, renormalised to sum to 1.
`experiments/calibrate.py` (`pulsetrader calibrate`) fits them on Phase 9 out-of-fold predictions:
- The method is chosen by Brier on the last pre-validation fold.
- The chosen method is then refit on all pre-validation folds and applied to validation.
- Reported: Brier, log loss, top-class ECE, classwise ECE, and reliability curves (top class and per class).
- Stored: raw_probability and <method>_probability. Calibration can change argmax decisions, so the
  class decision rule is kept separate from the reported probability.
