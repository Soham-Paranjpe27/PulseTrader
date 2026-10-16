from fastapi.testclient import TestClient

from pulsetrader.serve.app import app


def test_health_and_not_ready_without_model():
    c = TestClient(app)
    assert c.get("/health").json()["status"] == "ok"
    r = c.get("/ready").json()
    assert r["ready"] is False and r["reason"] == "NO_ACTIVE_MODEL"
