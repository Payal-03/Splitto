"""API endpoint tests."""

from fastapi.testclient import TestClient
from backend.main import app
from backend.storage import trips as seeded_trips

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_trips_returns_five():
    response = client.get("/api/trips")
    assert response.status_code == 200
    assert len(response.json()) == 5


def test_balances_for_all_seeded_trips():
    for trip_id, trip in seeded_trips.items():
        response = client.get(f"/api/trips/{trip_id}/balances")
        assert response.status_code == 200
        data = response.json()
        assert data["trip_id"] == trip_id
        assert len(data["balances"]) == len(trip["members"])
        assert sum(b["net_balance_paise"] for b in data["balances"]) == 0


def test_settlements_for_all_seeded_trips():
    for trip_id in seeded_trips:
        response = client.get(f"/api/trips/{trip_id}/settlements")
        assert response.status_code == 200
        data = response.json()
        assert data["trip_id"] == trip_id
        assert data["payment_count"] == len(data["transfers"])
        assert data["is_exact_minimal"] is True


def test_unknown_trip_returns_404():
    assert client.get("/api/trips/nonexistent/balances").status_code == 404
    assert client.get("/api/trips/nonexistent/settlements").status_code == 404


def test_empty_trip_endpoints(monkeypatch):
    empty_trip = {
        "id": "empty-test",
        "name": "Empty Trip",
        "members": [{"id": "m1", "name": "Aarav"}, {"id": "m2", "name": "Diya"}],
        "expenses": [],
    }
    monkeypatch.setitem(seeded_trips, "empty-test", empty_trip)

    bal_resp = client.get("/api/trips/empty-test/balances")
    assert bal_resp.status_code == 200
    bal_data = bal_resp.json()
    assert bal_data["total_spend_paise"] == 0
    assert all(b["net_balance_paise"] == 0 for b in bal_data["balances"])

    settle_resp = client.get("/api/trips/empty-test/settlements")
    assert settle_resp.status_code == 200
    settle_data = settle_resp.json()
    assert settle_data["transfers"] == []
    assert settle_data["payment_count"] == 0
    assert settle_data["is_exact_minimal"] is True
