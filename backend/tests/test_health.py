"""Smoke test: the app boots and /health returns 200."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert set(body["models"]) == {"embed", "rerank"}


def test_auth_required() -> None:
    resp = client.get("/tech/ping")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "unauthorized"
