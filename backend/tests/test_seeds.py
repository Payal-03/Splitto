"""Validate seed data integrity."""

import json
from pathlib import Path

SEEDS_PATH = Path(__file__).resolve().parent.parent / "seeds.json"
VALID_CATEGORIES = {"Accommodation", "Food", "Transport", "Fuel", "Activities", "Shopping", "Other"}

EXPECTED_TRIPS = {
    "Goa Getaway": {"members": 6, "expenses": 30},
    "Manali Escape": {"members": 5, "expenses": 25},
    "Jaipur Heritage Tour": {"members": 4, "expenses": 22},
    "Rishikesh Adventure": {"members": 7, "expenses": 35},
    "Mumbai Weekend": {"members": 4, "expenses": 20},
}


def load_seeds():
    return json.loads(SEEDS_PATH.read_text(encoding="utf-8"))


def test_trip_count():
    assert len(load_seeds()) == 5


def test_trip_names_and_counts():
    for trip in load_seeds():
        expected = EXPECTED_TRIPS[trip["name"]]
        assert len(trip["members"]) == expected["members"]
        assert len(trip["expenses"]) == expected["expenses"]


def test_unique_member_ids():
    all_ids = []
    for trip in load_seeds():
        all_ids.extend(m["id"] for m in trip["members"])
    assert len(all_ids) == len(set(all_ids))


def test_unique_expense_ids():
    all_ids = []
    for trip in load_seeds():
        all_ids.extend(e["id"] for e in trip["expenses"])
    assert len(all_ids) == len(set(all_ids))


def test_amounts_are_positive_integers():
    for trip in load_seeds():
        for exp in trip["expenses"]:
            assert isinstance(exp["amount_paise"], int)
            assert exp["amount_paise"] > 0


def test_payer_is_trip_member():
    for trip in load_seeds():
        member_ids = {m["id"] for m in trip["members"]}
        for exp in trip["expenses"]:
            assert exp["payer_id"] in member_ids


def test_participants_are_trip_members():
    for trip in load_seeds():
        member_ids = {m["id"] for m in trip["members"]}
        for exp in trip["expenses"]:
            assert len(exp["participant_ids"]) > 0
            for pid in exp["participant_ids"]:
                assert pid in member_ids


def test_categories_valid():
    for trip in load_seeds():
        for exp in trip["expenses"]:
            assert exp["category"] in VALID_CATEGORIES


def test_shares_only_for_unequal():
    for trip in load_seeds():
        for exp in trip["expenses"]:
            if exp["split_type"] == "equal":
                assert "shares" not in exp
            elif exp["split_type"] == "unequal":
                assert "shares" in exp


def test_unequal_shares_sum_to_amount():
    for trip in load_seeds():
        for exp in trip["expenses"]:
            if exp["split_type"] == "unequal":
                assert sum(exp["shares"].values()) == exp["amount_paise"]


def test_unequal_shares_keys_match_participants():
    for trip in load_seeds():
        for exp in trip["expenses"]:
            if exp["split_type"] == "unequal":
                assert set(exp["shares"].keys()) == set(exp["participant_ids"])
