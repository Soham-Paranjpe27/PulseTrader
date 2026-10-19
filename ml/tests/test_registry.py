import json

import pytest

from pulsetrader.registry.registry import (
    FAILED,
    NOT_RUN,
    PASSED,
    REQUIRED_GATES,
    Gate,
    ModelRecord,
    Registry,
    RegistryError,
    Status,
    gate,
)


def _rec(model_id: str = "lgb-y_5m", version: int = 1, task: str = "y_5m_10bp") -> ModelRecord:
    return ModelRecord(
        model_id=model_id, version=version, task=task, model_type="lightgbm", dataset_version="ds",
        feature_version="features-v2", label_version="labels-v1", training_period={},
        validation_period={}, test_period={"used": False}, hyperparameters={}, metrics={"validation": {}},
        backtest_metrics={}, calibration_version=None, artifact_path="artifacts/x",
    )  # fmt: skip


def _all_gates(status: str = PASSED) -> dict:
    return {g.value: gate(status, "test") for g in Gate}


def test_register_and_reload(tmp_path):
    reg = Registry(tmp_path)
    reg.register(_rec())
    assert reg.next_version("lgb-y_5m") == 2
    r = reg.get("lgb-y_5m")
    assert r.status == Status.EXPERIMENT and r.history[0]["to"] == "EXPERIMENT"
    assert json.loads((tmp_path / "registry.json").read_text())["registry_version"] == "registry-v1"
    with pytest.raises(RegistryError):
        reg.register(_rec())  # duplicate version


def test_transition_needs_gates(tmp_path):
    reg = Registry(tmp_path)
    reg.register(_rec())
    with pytest.raises(RegistryError, match="gates not passed"):
        reg.transition("lgb-y_5m", 1, Status.CANDIDATE, "try")
    gates = _all_gates()
    gates[Gate.BACKTEST.value] = gate(FAILED, "loses after costs")
    gates[Gate.TEST.value] = gate(NOT_RUN, "untouched")
    reg.update_gates("lgb-y_5m", 1, gates)
    assert reg.transition("lgb-y_5m", 1, Status.CANDIDATE, "ok").status == "CANDIDATE"
    with pytest.raises(RegistryError, match="backtest_passed"):
        reg.transition("lgb-y_5m", 1, Status.SHADOW, "try")


def test_illegal_transitions(tmp_path):
    reg = Registry(tmp_path)
    reg.register(_rec())
    reg.update_gates("lgb-y_5m", 1, _all_gates())
    with pytest.raises(RegistryError, match="not allowed"):
        reg.transition("lgb-y_5m", 1, Status.PRODUCTION, "skip shadow")
    reg.transition("lgb-y_5m", 1, Status.REJECTED, "bad")
    with pytest.raises(RegistryError, match="not allowed"):
        reg.transition("lgb-y_5m", 1, Status.CANDIDATE, "revive")
    with pytest.raises(RegistryError):
        reg.transition("lgb-y_5m", 9, Status.CANDIDATE, "missing")


def test_promotion_retires_previous_production(tmp_path):
    reg = Registry(tmp_path)
    for v in (1, 2):
        reg.register(_rec(version=v))
        reg.update_gates("lgb-y_5m", v, _all_gates())
        for s in (Status.CANDIDATE, Status.SHADOW, Status.PRODUCTION):
            reg.transition("lgb-y_5m", v, s, "gates passed")
    assert [m.version for m in reg.active("y_5m_10bp")] == [2]
    old = reg.get("lgb-y_5m", 1)
    assert old.status == "RETIRED" and "replaced by lgb-y_5m@v2" in old.history[-1]["reason"]
    with pytest.raises(RegistryError, match="reason"):
        reg.transition("lgb-y_5m", 2, Status.RETIRED, " ")


def test_required_gates_grow_with_status():
    c, s, p = (set(REQUIRED_GATES[x]) for x in (Status.CANDIDATE, Status.SHADOW, Status.PRODUCTION))
    assert c < s < p and Gate.SHADOW in p and Gate.TEST in s


def test_gate_evaluators():
    from pulsetrader.experiments.register import backtest_gate, calibration_gate, validation_gate

    m = {"validation": {"mcc": 0.19, "balanced_accuracy": 0.45, "accuracy": 0.50,
                        "baselines": {"momentum_mcc": 0.09, "majority_accuracy": 0.58}}}  # fmt: skip
    assert validation_gate(m)["status"] == PASSED
    m["validation"]["mcc"] = 0.05 + 0.04  # equals momentum -> fail
    m["validation"]["baselines"]["momentum_mcc"] = 0.09
    assert validation_gate(m)["status"] == FAILED
    c = {
        "chosen": "isotonic",
        "validation": {"isotonic": {"ece_classwise": 0.02}, "raw": {"ece_classwise": 0.14}},
    }
    assert calibration_gate(c)["status"] == PASSED
    b = {
        "model_gated|costs": {"total_return": -0.09, "sharpe": -1.0, "max_drawdown": -0.1},
        "buy_and_hold|costs": {"total_return": 0.015},
    }
    assert backtest_gate(b)["status"] == FAILED


def test_export_artifact_on_golden(golden_dataset, tmp_path):
    from pulsetrader.experiments import optimize as opt
    from pulsetrader.experiments.register import export_artifact

    dev = opt.load_dev(golden_dataset, 5, (0.001,), dataset="ds", n_pre=1, min_train_frac=0.67,
                       embargo_minutes=15, train_every=5)  # fmt: skip
    r = opt.walk_forward(dev, tmp_path / "exp", "y_5m_10bp")
    wf = tmp_path / "exp" / r["experiment"]["experiment_id"]
    cal = tmp_path / "cal"
    cal.mkdir()
    (cal / "calibrators.json").write_text(json.dumps({"isotonic": {"method": "isotonic", "thresholds": []}}))
    (cal / "metrics.json").write_text(json.dumps({"chosen": "isotonic"}))
    out = export_artifact(wf, cal, golden_dataset, tmp_path / "art", "ds", min_train_frac=0.67)
    assert out["gate"]["status"] == PASSED, out["gate"]
    for f in ("model.txt", "preprocessor.json", "features.json", "calibrator.json", "model_meta.json"):
        assert (tmp_path / "art" / f).exists()
    feats = json.loads((tmp_path / "art" / "features.json").read_text())["features"]
    assert feats == r["experiment"]["config"]["features"] if "config" in r["experiment"] else feats
