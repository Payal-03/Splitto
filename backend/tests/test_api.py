"""API endpoint smoke tests."""

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_trips_returns_five():
    response = client.get("/api/trips")
    assert response.status_code == 200
    assert len(response.json()) == 5
