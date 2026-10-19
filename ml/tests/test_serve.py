import json

import numpy as np
import polars as pl
import pytest
from fastapi.testclient import TestClient

from pulsetrader.registry.registry import PASSED, Gate, ModelRecord, Registry, Status, gate
from pulsetrader.serve import app as service


@pytest.fixture
def empty_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PULSETRADER_DATA_DIR", str(tmp_path))
    service.reset()
    yield TestClient(service.app)
    service.reset()


def test_health_and_not_ready_without_model(empty_env):
    c = empty_env
    assert c.get("/health").json()["status"] == "ok"
    r = c.get("/ready").json()
    assert r["ready"] is False and r["reason"] == "NO_MODEL_LOADED"
    assert c.get("/models/active").json()["active"] == []


@pytest.fixture(scope="module")
def served(golden_dataset, tmp_path_factory):
    """Golden walk-forward model exported into a registry as CANDIDATE."""
    from pulsetrader.experiments import optimize as opt
    from pulsetrader.experiments.register import export_artifact, write_serving_files

    tmp = tmp_path_factory.mktemp("serve")
    dev = opt.load_dev(golden_dataset, 5, (0.001,), dataset="ds", n_pre=1, min_train_frac=0.67,
                       embargo_minutes=15, train_every=5)  # fmt: skip
    r = opt.walk_forward(dev, tmp / "exp", "y_5m_10bp")
    wf = tmp / "exp" / r["experiment"]["experiment_id"]
    cal, bt = tmp / "cal", tmp / "bt"
    cal.mkdir()
    bt.mkdir()
    (cal / "calibrators.json").write_text(json.dumps({"platt": {"method": "platt", "coef": [[1, 0]] * 3}}))
    (cal / "metrics.json").write_text(json.dumps({"chosen": "platt"}))
    (bt / "config.json").write_text(json.dumps({"gate": {"chosen": {"gate": 0.0}}}))
    reg = Registry(golden_dataset / "registry")
    art = reg.artifact_dir("lgb-golden", 1)
    export_artifact(wf, cal, golden_dataset, art, "ds", min_train_frac=0.67)
    write_serving_files(art, golden_dataset / "datasets" / "ds", bt)
    exp = r["experiment"]
    rec = ModelRecord(
        model_id="lgb-golden", version=1, task="y_5m_10bp", model_type="lightgbm",
        dataset_version=exp["dataset_id"], feature_version="features-v2", label_version="labels-v1",
        training_period=exp["train_period"], validation_period=exp["validation_period"],
        test_period=exp["test_period"], hyperparameters={}, metrics={"validation": {"mcc": 0.1}},
        backtest_metrics={}, calibration_version="platt", artifact_path=str(art.relative_to(reg.root)),
        source_experiments={"walk_forward": wf.name},
    )  # fmt: skip
    reg.register(rec)
    reg.update_gates("lgb-golden", 1, {g.value: gate(PASSED, "golden") for g in Gate})
    reg.transition("lgb-golden", 1, Status.CANDIDATE, "golden")
    preds = pl.read_parquet(wf / "predictions.parquet").filter(pl.col("fold") == "F2")
    return {"root": golden_dataset, "reg": reg, "preds": preds}


@pytest.fixture
def client(served, monkeypatch):
    monkeypatch.setenv("PULSETRADER_DATA_DIR", str(served["root"]))
    monkeypatch.setenv("PULSETRADER_DATASET", "ds")
    monkeypatch.delenv("PULSETRADER_ALLOW_TEST_PERIOD", raising=False)
    service.reset()
    yield TestClient(service.app)
    service.reset()


def _req(sym, ts, **kw):
    return {"symbol": sym, "timestamp": ts.isoformat(), "model_id": "lgb-golden", **kw}


def test_ready_models_features(client):
    r = client.get("/ready").json()
    assert r["ready"] is True and r["reason"] == "NO_PRODUCTION_MODEL"
    assert r["loaded_models"] == ["lgb-golden@v1"]
    m = client.get("/models").json()["models"][0]
    assert m["status"] == "CANDIDATE" and m["serving"]["research_only"] is True
    f = client.get("/features").json()["models"][0]
    assert f["count"] == len(f["features"]) and f["features"][0]["order"] == 0


def test_no_production_model_refuses_unnamed_request(client, served):
    sym, ts = served["preds"].row(0)[:2]
    r = client.post("/predict", json={"symbol": sym, "timestamp": ts.isoformat()})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NO_PRODUCTION_MODEL"


def test_historical_predictions_match_walk_forward(client, served):
    rows = served["preds"].head(40)
    items = [_req(s, t) for s, t in rows.select("symbol", "ts").iter_rows()]
    out = client.post("/predict/batch", json={"items": items}).json()
    got = np.array([[p["raw_probability"][c] for c in ("down", "neutral", "up")] for p in out["predictions"]])
    assert np.allclose(got, rows.select("p_down", "p_neutral", "p_up").to_numpy(), atol=1e-5)
    p = out["predictions"][0]
    assert p["research_only"] is True and p["model_status"] == "CANDIDATE"
    assert p["prediction_timestamp"] > p["market_data_timestamp"]
    assert abs(sum(p["calibrated_probability"].values()) - 1) < 1e-6
    assert p["direction"] in ("UP", "DOWN", "NO_PREDICTION")
    m = client.get("/metrics").json()
    assert m["predictions"] == 40 and m["requests"]["predict_batch"] == 1


def test_test_period_is_locked(client, served):
    ds = served["root"] / "datasets" / "ds"
    test_row = (
        pl.scan_parquet(ds / "part-*.parquet")
        .filter(pl.col("split") == "test")
        .select("symbol", "ts")
        .head(1)
    ).collect()
    sym, ts = test_row.row(0)
    r = client.post("/predict", json=_req(sym, ts))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "TEST_PERIOD_LOCKED"


def test_abstention_rules(client, served):
    sym, ts = served["preds"].row(0)[:2]
    feats = service.store().lookup(sym, ts)["features"]
    ok = client.post("/predict", json=_req(sym, ts, features=feats)).json()
    assert ok["abstain_reason"] in (None, "LOW_CONFIDENCE") and ok["data_quality"] == "CLIENT_SUPPLIED"
    few = dict(list(feats.items())[:3])
    assert (
        client.post("/predict", json=_req(sym, ts, features=few)).json()["abstain_reason"]
        == "FEATURES_INVALID"
    )
    wild = {k: (1e9 if v is not None else None) for k, v in feats.items()}
    r = client.post("/predict", json=_req(sym, ts, features=wild)).json()
    assert r["abstain_reason"] == "MODEL_OUT_OF_DISTRIBUTION"
    r = client.post("/predict", json=_req("NOT_A_STOCK", ts, features=feats)).json()
    assert r["abstain_reason"] == "MODEL_OUT_OF_DISTRIBUTION"
    r = client.post("/predict", json=_req(sym, ts, features=feats, max_staleness_seconds=60)).json()
    assert r["abstain_reason"] == "STALE_DATA"
    bad = client.post("/predict", json=_req(sym, ts, features={"ret_1": "x"}))
    assert bad.status_code == 422
    naive = client.post("/predict", json={"symbol": sym, "timestamp": "2024-01-02T10:00:00", "model_id": "x"})
    assert naive.status_code == 422
    unknown = client.post("/predict", json={**_req(sym, ts), "model_id": "nope"})
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "MODEL_UNAVAILABLE"


def test_production_model_answers_unnamed_requests(served, monkeypatch):
    import shutil

    root = served["root"].parent / "prod_root"
    if not root.exists():
        shutil.copytree(served["root"] / "registry", root / "registry")
        shutil.copytree(served["root"] / "datasets", root / "datasets")
    reg = Registry(root / "registry")
    for s in (Status.SHADOW, Status.PRODUCTION):
        reg.transition("lgb-golden", 1, s, "golden test promotion")
    monkeypatch.setenv("PULSETRADER_DATA_DIR", str(root))
    monkeypatch.setenv("PULSETRADER_DATASET", "ds")
    service.reset()
    c = TestClient(service.app)
    assert [m["model_id"] for m in c.get("/models/active").json()["active"]] == ["lgb-golden"]
    sym, ts = served["preds"].row(0)[:2]
    p = c.post("/predict", json={"symbol": sym, "timestamp": ts.isoformat()}).json()
    assert p["model_status"] == "PRODUCTION" and p["research_only"] is False
    service.reset()


def test_bars_endpoint(client, served):
    sym, ts = served["preds"].row(0)[:2]
    d = ts.date().isoformat()
    r = client.get(f"/bars/{sym}?date={d}")
    assert r.status_code == 200 and r.json()["count"] > 0
    assert set(r.json()["bars"][0]) == {"ts", "open", "high", "low", "close", "volume"}
    assert client.get(f"/bars/{sym}?date=bad").status_code == 422
    assert client.get("/bars/NOPE?date=2024-01-02").json()["detail"]["code"] == "DATA_UNAVAILABLE"
