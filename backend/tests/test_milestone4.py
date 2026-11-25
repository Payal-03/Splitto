"""Milestone 4 tests: SQLite persistence, trips, members, payments, and summary."""

import pytest
from fastapi.testclient import TestClient

from backend import storage
from backend.main import app

client = TestClient(app)


# --- M4.1: SQLite Initialization & Persistence ---


def test_db_initialized_with_five_seeded_trips():
    trips = client.get("/api/trips").json()
    assert len(trips) == 5
    by_id = {t["id"]: t for t in trips}
    assert len(by_id["goa"]["expenses"]) == 30
    assert by_id["goa"]["expenses"][0]["id"] == "goa-e01"


def test_seed_data_not_duplicated_on_restart(tmp_path):
    db_file = tmp_path / "restart.db"
    storage.init_db(db_file)
    assert len(client.get("/api/trips").json()) == 5

    # Simulate app restart against the same SQLite file
    storage.init_db(db_file)
    trips = client.get("/api/trips").json()
    assert len(trips) == 5
    goa = next(t for t in trips if t["id"] == "goa")
    assert len(goa["members"]) == 6
    assert len(goa["expenses"]) == 30


def test_persistence_across_restart(tmp_path):
    db_file = tmp_path / "persist.db"
    storage.init_db(db_file)

    trip_resp = client.post("/api/trips", json={"name": "Ladakh Ride"})
    assert trip_resp.status_code == 201
    trip_id = trip_resp.json()["id"]

    m1 = client.post(f"/api/trips/{trip_id}/members", json={"name": "Asha"}).json()["id"]
    m2 = client.post(f"/api/trips/{trip_id}/members", json={"name": "Vikram"}).json()["id"]

    exp_resp = client.post(
        f"/api/trips/{trip_id}/expenses",
        json={
            "description": "Bike rental",
            "amount_paise": 100000,
            "payer_id": m1,
            "category": "Transport",
            "participant_ids": [m1, m2],
            "split_type": "equal",
        },
    )
    assert exp_resp.status_code == 201

    pay_resp = client.post(
        f"/api/trips/{trip_id}/payments",
        json={"from_member_id": m2, "to_member_id": m1, "amount_paise": 20000},
    )
    assert pay_resp.status_code == 201

    # Simulate restart by clearing in-memory cache and re-initializing from same DB
    storage.trips.clear()
    storage.init_db(db_file)

    bal = client.get(f"/api/trips/{trip_id}/balances").json()
    assert bal["total_spend_paise"] == 100000
    by_id = {b["member_id"]: b for b in bal["balances"]}
    assert by_id[m1]["net_balance_paise"] == 30000
    assert by_id[m2]["net_balance_paise"] == -30000

    payments = client.get(f"/api/trips/{trip_id}/payments").json()["payments"]
    assert len(payments) == 1
    assert payments[0]["amount_paise"] == 20000


# --- M4.2: Trip & Member APIs ---


def test_create_trip_and_duplicate_slug():
    r1 = client.post("/api/trips", json={"name": "Spiti Valley"})
    assert r1.status_code == 201
    assert r1.json()["id"] == "spiti-valley"

    r2 = client.post("/api/trips", json={"name": "Spiti Valley"})
    assert r2.status_code == 201
    assert r2.json()["id"] == "spiti-valley-2"


@pytest.mark.parametrize("bad_body", [{"name": ""}, {"name": "   "}, {}, {"name": "Ok", "extra": 1}])
def test_create_trip_invalid(bad_body):
    assert client.post("/api/trips", json=bad_body).status_code == 400


def test_create_member_and_duplicate_rejection():
    trip_id = client.post("/api/trips", json={"name": "Coorg"}).json()["id"]

    r1 = client.post(f"/api/trips/{trip_id}/members", json={"name": "Asha"})
    assert r1.status_code == 201
    assert r1.json() == {"id": f"{trip_id}-m1", "name": "Asha"}

    # Exact and case-insensitive duplicate rejected
    assert client.post(f"/api/trips/{trip_id}/members", json={"name": "Asha"}).status_code == 400
    assert client.post(f"/api/trips/{trip_id}/members", json={"name": " asha "}).status_code == 400
    assert client.post(f"/api/trips/{trip_id}/members", json={"name": "   "}).status_code == 400


def test_create_member_unknown_trip():
    assert client.post("/api/trips/does-not-exist/members", json={"name": "Asha"}).status_code == 404


# --- M4.3: Payment Recording & Summary ---


def _setup_two_member_debt():
    """Create a trip where B owes A exactly 100000 paise (Rs 1,000)."""
    trip_id = client.post("/api/trips", json={"name": "Payment Test"}).json()["id"]
    a_id = client.post(f"/api/trips/{trip_id}/members", json={"name": "Alice"}).json()["id"]
    b_id = client.post(f"/api/trips/{trip_id}/members", json={"name": "Bob"}).json()["id"]
    resp = client.post(
        f"/api/trips/{trip_id}/expenses",
        json={
            "description": "Hotel",
            "amount_paise": 200000,
            "payer_id": a_id,
            "category": "Accommodation",
            "participant_ids": [a_id, b_id],
            "split_type": "equal",
        },
    )
    assert resp.status_code == 201
    return trip_id, a_id, b_id


def test_partial_payments_and_full_settlement():
    trip_id, a_id, b_id = _setup_two_member_debt()

    # First partial payment: Bob pays Alice 50000 (Rs 500)
    p1 = client.post(
        f"/api/trips/{trip_id}/payments",
        json={"from_member_id": b_id, "to_member_id": a_id, "amount_paise": 50000},
    )
    assert p1.status_code == 201
    assert p1.json()["amount_paise"] == 50000

    bal1 = client.get(f"/api/trips/{trip_id}/balances").json()
    assert bal1["total_spend_paise"] == 200000
    b_map1 = {b["member_id"]: b for b in bal1["balances"]}
    # Expense-derived paid/owed are untouched
    assert b_map1[a_id]["total_paid_paise"] == 200000
    assert b_map1[a_id]["total_owed_paise"] == 100000
    assert b_map1[b_id]["total_paid_paise"] == 0
    assert b_map1[b_id]["total_owed_paise"] == 100000
    # Adjusted net balances reflect the Rs 500 payment
    assert b_map1[a_id]["net_balance_paise"] == 50000
    assert b_map1[b_id]["net_balance_paise"] == -50000

    settle1 = client.get(f"/api/trips/{trip_id}/settlements").json()
    assert settle1["payment_count"] == 1
    assert settle1["transfers"][0]["amount_paise"] == 50000

    # Second payment: Bob pays remaining 50000 -> fully settled
    p2 = client.post(
        f"/api/trips/{trip_id}/payments",
        json={"from_member_id": b_id, "to_member_id": a_id, "amount_paise": 50000},
    )
    assert p2.status_code == 201

    bal2 = client.get(f"/api/trips/{trip_id}/balances").json()
    assert all(b["net_balance_paise"] == 0 for b in bal2["balances"])

    settle2 = client.get(f"/api/trips/{trip_id}/settlements").json()
    assert settle2["transfers"] == []
    assert settle2["payment_count"] == 0

    history = client.get(f"/api/trips/{trip_id}/payments").json()
    assert len(history["payments"]) == 2
    assert history["total_settled_paise"] == 100000


def test_overpayment_rejected_and_store_unchanged():
    trip_id, a_id, b_id = _setup_two_member_debt()
    client.post(
        f"/api/trips/{trip_id}/payments",
        json={"from_member_id": b_id, "to_member_id": a_id, "amount_paise": 60000},
    )

    # Only 40000 remaining; 50000 must be rejected
    over = client.post(
        f"/api/trips/{trip_id}/payments",
        json={"from_member_id": b_id, "to_member_id": a_id, "amount_paise": 50000},
    )
    assert over.status_code == 400

    history = client.get(f"/api/trips/{trip_id}/payments").json()
    assert len(history["payments"]) == 1
    assert history["total_settled_paise"] == 60000


@pytest.mark.parametrize(
    "bad_payment_fn",
    [
        lambda a, b: {"from_member_id": b, "to_member_id": a, "amount_paise": 0},
        lambda a, b: {"from_member_id": b, "to_member_id": a, "amount_paise": -100},
        lambda a, b: {"from_member_id": b, "to_member_id": a, "amount_paise": 100.5},
        lambda a, b: {"from_member_id": b, "to_member_id": a, "amount_paise": True},
        lambda a, b: {"from_member_id": b, "to_member_id": b, "amount_paise": 100},
        lambda a, b: {"from_member_id": "unknown", "to_member_id": a, "amount_paise": 100},
        lambda a, b: {"from_member_id": b, "to_member_id": "unknown", "amount_paise": 100},
        lambda a, b: {"from_member_id": a, "to_member_id": b, "amount_paise": 100},  # creditor paying debtor
        lambda a, b: {"from_member_id": b, "to_member_id": a, "amount_paise": 100, "extra": 1},
    ],
)
def test_invalid_payments_rejected(bad_payment_fn):
    trip_id, a_id, b_id = _setup_two_member_debt()
    before_bal = client.get(f"/api/trips/{trip_id}/balances").json()

    resp = client.post(f"/api/trips/{trip_id}/payments", json=bad_payment_fn(a_id, b_id))
    assert resp.status_code == 400
    assert client.get(f"/api/trips/{trip_id}/payments").json()["payments"] == []
    assert client.get(f"/api/trips/{trip_id}/balances").json() == before_bal


def test_unknown_trip_for_payments_and_summary():
    assert client.get("/api/trips/missing/payments").status_code == 404
    assert client.get("/api/trips/missing/summary").status_code == 404
    assert (
        client.post(
            "/api/trips/missing/payments",
            json={"from_member_id": "m1", "to_member_id": "m2", "amount_paise": 100},
        ).status_code
        == 404
    )


def test_summary_endpoint():
    trip_id, a_id, b_id = _setup_two_member_debt()
    client.post(
        f"/api/trips/{trip_id}/payments",
        json={"from_member_id": b_id, "to_member_id": a_id, "amount_paise": 25000},
    )

    summary = client.get(f"/api/trips/{trip_id}/summary")
    assert summary.status_code == 200
    data = summary.json()
    assert data["trip_id"] == trip_id
    assert data["trip_name"] == "Payment Test"
    assert data["total_spend_paise"] == 200000
    assert data["total_settled_paise"] == 25000
    assert data["settlements"]["payment_count"] == 1
    assert data["settlements"]["transfers"][0]["amount_paise"] == 75000
    assert len(data["payments"]) == 1
