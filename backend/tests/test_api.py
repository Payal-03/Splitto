"""API endpoint tests."""

import hashlib
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.storage import trips as seeded_trips

client = TestClient(app)

SEEDS_PATH = Path(__file__).resolve().parent.parent / "seeds.json"


def _valid_payload(**overrides):
    base = {
        "description": "Beach snacks",
        "amount_paise": 6000,
        "payer_id": "goa-m1",
        "category": "Food",
        "participant_ids": ["goa-m1", "goa-m2", "goa-m3", "goa-m4", "goa-m5", "goa-m6"],
        "split_type": "equal",
    }
    base.update(overrides)
    return base


def _get_goa_trip():
    return next(t for t in client.get("/api/trips").json() if t["id"] == "goa")


def _balances_by_id(trip_id: str) -> dict[str, dict]:
    return {
        b["member_id"]: b
        for b in client.get(f"/api/trips/{trip_id}/balances").json()["balances"]
    }


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
    assert client.post("/api/trips/nonexistent/expenses", json=_valid_payload()).status_code == 404


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


# --- Milestone 3: POST /api/trips/{trip_id}/expenses ---


def test_create_equal_expense_all_members():
    before_trip = _get_goa_trip()
    resp = client.post("/api/trips/goa/expenses", json=_valid_payload())
    assert resp.status_code == 201
    created = resp.json()
    assert created["id"] == "goa-e31"
    assert "shares" not in created

    after_trip = _get_goa_trip()
    assert len(after_trip["expenses"]) == len(before_trip["expenses"]) + 1
    assert after_trip["expenses"][-1] == created


def test_create_expense_id_sequence():
    r1 = client.post("/api/trips/goa/expenses", json=_valid_payload())
    r2 = client.post("/api/trips/goa/expenses", json=_valid_payload(description="Coffee"))
    assert r1.status_code == 201 and r1.json()["id"] == "goa-e31"
    assert r2.status_code == 201 and r2.json()["id"] == "goa-e32"


def test_equal_split_with_remainder():
    before = _balances_by_id("goa")
    resp = client.post(
        "/api/trips/goa/expenses",
        json=_valid_payload(
            amount_paise=10000,
            payer_id="goa-m1",
            participant_ids=["goa-m3", "goa-m1", "goa-m2"],
        ),
    )
    assert resp.status_code == 201
    after = _balances_by_id("goa")
    # Sorted IDs: goa-m1, goa-m2, goa-m3 -> 3334, 3333, 3333
    assert after["goa-m1"]["total_owed_paise"] - before["goa-m1"]["total_owed_paise"] == 3334
    assert after["goa-m2"]["total_owed_paise"] - before["goa-m2"]["total_owed_paise"] == 3333
    assert after["goa-m3"]["total_owed_paise"] - before["goa-m3"]["total_owed_paise"] == 3333


def test_equal_split_selected_members_only():
    before = _balances_by_id("goa")
    resp = client.post(
        "/api/trips/goa/expenses",
        json=_valid_payload(amount_paise=2000, payer_id="goa-m1", participant_ids=["goa-m1", "goa-m2"]),
    )
    assert resp.status_code == 201
    after = _balances_by_id("goa")
    for non_part in ("goa-m3", "goa-m4", "goa-m5", "goa-m6"):
        assert after[non_part]["total_owed_paise"] == before[non_part]["total_owed_paise"]


def test_unequal_split():
    before = _balances_by_id("goa")
    shares = {"goa-m1": 1500, "goa-m2": 3500}
    resp = client.post(
        "/api/trips/goa/expenses",
        json=_valid_payload(
            amount_paise=5000,
            payer_id="goa-m1",
            participant_ids=["goa-m1", "goa-m2"],
            split_type="unequal",
            shares=shares,
        ),
    )
    assert resp.status_code == 201
    assert resp.json()["shares"] == shares
    after = _balances_by_id("goa")
    assert after["goa-m1"]["total_owed_paise"] - before["goa-m1"]["total_owed_paise"] == 1500
    assert after["goa-m2"]["total_owed_paise"] - before["goa-m2"]["total_owed_paise"] == 3500


def test_payer_not_among_participants():
    before = _balances_by_id("goa")
    resp = client.post(
        "/api/trips/goa/expenses",
        json=_valid_payload(amount_paise=4000, payer_id="goa-m6", participant_ids=["goa-m1", "goa-m2"]),
    )
    assert resp.status_code == 201
    after = _balances_by_id("goa")
    assert after["goa-m6"]["total_paid_paise"] - before["goa-m6"]["total_paid_paise"] == 4000
    assert after["goa-m6"]["total_owed_paise"] == before["goa-m6"]["total_owed_paise"]


def test_balance_and_settlement_integration():
    before_bal = client.get("/api/trips/goa/balances").json()
    before_settle = client.get("/api/trips/goa/settlements").json()

    resp = client.post(
        "/api/trips/goa/expenses",
        json=_valid_payload(amount_paise=1200000, payer_id="goa-m3", participant_ids=["goa-m1", "goa-m2"]),
    )
    assert resp.status_code == 201

    after_bal = client.get("/api/trips/goa/balances").json()
    after_settle = client.get("/api/trips/goa/settlements").json()

    assert after_bal["total_spend_paise"] == before_bal["total_spend_paise"] + 1200000
    assert sum(b["net_balance_paise"] for b in after_bal["balances"]) == 0

    before_map = {b["member_id"]: b for b in before_bal["balances"]}
    after_map = {b["member_id"]: b for b in after_bal["balances"]}
    assert after_map["goa-m3"]["total_paid_paise"] == before_map["goa-m3"]["total_paid_paise"] + 1200000
    assert after_map["goa-m1"]["total_owed_paise"] == before_map["goa-m1"]["total_owed_paise"] + 600000
    assert after_map["goa-m2"]["total_owed_paise"] == before_map["goa-m2"]["total_owed_paise"] + 600000

    assert after_settle["transfers"] != before_settle["transfers"]

    net = {b["member_id"]: b["net_balance_paise"] for b in after_bal["balances"]}
    for t in after_settle["transfers"]:
        net[t["from_member_id"]] += t["amount_paise"]
        net[t["to_member_id"]] -= t["amount_paise"]
    assert all(v == 0 for v in net.values())


def _invalid_cases():
    cases = []
    for missing_field in ("description", "amount_paise", "payer_id", "category", "participant_ids", "split_type"):
        p = _valid_payload()
        p.pop(missing_field)
        cases.append((f"missing-{missing_field}", p))

    cases.extend([
        ("blank-description", _valid_payload(description="")),
        ("whitespace-description", _valid_payload(description="   \t\n")),
        ("amount-zero", _valid_payload(amount_paise=0)),
        ("amount-negative", _valid_payload(amount_paise=-500)),
        ("amount-float-fraction", _valid_payload(amount_paise=100.5)),
        ("amount-float-whole", _valid_payload(amount_paise=100.0)),
        ("amount-bool", _valid_payload(amount_paise=True)),
        ("amount-string", _valid_payload(amount_paise="100")),
        ("payer-not-member", _valid_payload(payer_id="manali-m1")),
        ("participants-empty", _valid_payload(participant_ids=[])),
        ("participants-duplicate", _valid_payload(participant_ids=["goa-m1", "goa-m1"])),
        ("participants-non-member", _valid_payload(participant_ids=["goa-m1", "manali-m1"])),
        ("invalid-category", _valid_payload(category="Gambling")),
        ("invalid-split-type", _valid_payload(split_type="percent")),
        ("unequal-missing-shares", _valid_payload(split_type="unequal")),
        (
            "unequal-shares-keys-mismatch",
            _valid_payload(
                split_type="unequal",
                participant_ids=["goa-m1", "goa-m2"],
                shares={"goa-m1": 6000},
            ),
        ),
        (
            "unequal-shares-sum-mismatch",
            _valid_payload(
                amount_paise=6000,
                split_type="unequal",
                participant_ids=["goa-m1", "goa-m2"],
                shares={"goa-m1": 3000, "goa-m2": 2000},
            ),
        ),
        (
            "unequal-zero-share",
            _valid_payload(
                amount_paise=6000,
                split_type="unequal",
                participant_ids=["goa-m1", "goa-m2"],
                shares={"goa-m1": 0, "goa-m2": 6000},
            ),
        ),
        (
            "unequal-negative-share",
            _valid_payload(
                amount_paise=6000,
                split_type="unequal",
                participant_ids=["goa-m1", "goa-m2"],
                shares={"goa-m1": -100, "goa-m2": 6100},
            ),
        ),
        (
            "equal-with-shares-dict",
            _valid_payload(
                split_type="equal",
                participant_ids=["goa-m1", "goa-m2"],
                shares={"goa-m1": 3000, "goa-m2": 3000},
            ),
        ),
        (
            "equal-with-shares-null",
            _valid_payload(
                split_type="equal",
                participant_ids=["goa-m1", "goa-m2"],
                shares=None,
            ),
        ),
        ("extra-unknown-field", _valid_payload(unknown_field="nope")),
    ])
    return cases


@pytest.mark.parametrize("case_name,payload", _invalid_cases(), ids=lambda x: x if isinstance(x, str) else "")
def test_invalid_expense_returns_400_and_leaves_store_unchanged(case_name, payload):
    before_count = len(_get_goa_trip()["expenses"])
    before_balances = client.get("/api/trips/goa/balances").json()

    resp = client.post("/api/trips/goa/expenses", json=payload)
    assert resp.status_code == 400, f"{case_name} returned {resp.status_code}: {resp.text}"
    assert "detail" in resp.json()

    assert len(_get_goa_trip()["expenses"]) == before_count
    assert client.get("/api/trips/goa/balances").json() == before_balances


def test_seeds_json_untouched():
    before_hash = hashlib.sha256(SEEDS_PATH.read_bytes()).hexdigest()
    resp = client.post("/api/trips/goa/expenses", json=_valid_payload())
    assert resp.status_code == 201
    after_hash = hashlib.sha256(SEEDS_PATH.read_bytes()).hexdigest()
    assert before_hash == after_hash
