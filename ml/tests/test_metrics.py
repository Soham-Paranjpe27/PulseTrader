import numpy as np

from pulsetrader.eval.metrics import binary_report, ece, selective_table


def test_majority_classifier_flagged():
    y = np.array([1] * 80 + [0] * 20)
    p = np.full(100, 0.9)
    r = binary_report(y, p)
    assert r["accuracy"] == 0.8
    assert r["balanced_accuracy"] == 0.5
    assert r["mcc"] == 0.0
    assert r["verdict"] == "FAILED — MAJORITY/IMBALANCE BEHAVIOR"


def test_selective_coverage():
    y = np.array([1, 0, 1, 0])
    p = np.array([0.95, 0.05, 0.55, 0.6])
    t = {r["threshold"]: r for r in selective_table(y, p)}
    assert t[0.9]["coverage"] == 0.5 and t[0.9]["accuracy"] == 1.0
    assert t[0.5]["coverage"] == 1.0 and t[0.5]["n_predictions"] == 4


def test_ece_perfect():
    y = np.array([0, 1] * 50)
    assert ece(y, np.full(100, 0.5)) == 0.0
