"""Unit tests for balance calculation and minimum-payment settlement."""

import random
import pytest

from backend.domain import (
    EXACT_LIMIT,
    calculate_balances,
    calculate_settlements,
    optimize_settlements,
)
from backend.storage import trips as seeded_trips


def _make_trip(members, expenses, trip_id="t1"):
    return {
        "id": trip_id,
        "name": "Test Trip",
        "members": [{"id": m, "name": m.capitalize()} for m in members],
        "expenses": expenses,
    }


def _expense(
    exp_id,
    amount_paise,
    payer_id,
    participant_ids,
    split_type="equal",
    shares=None,
):
    data = {
        "id": exp_id,
        "description": f"Expense {exp_id}",
        "amount_paise": amount_paise,
        "payer_id": payer_id,
        "category": "Food",
        "participant_ids": participant_ids,
        "split_type": split_type,
    }
    if shares is not None:
        data["shares"] = shares
    return data


def _apply_transfers(balances: dict[str, int], transfers: list[dict]) -> dict[str, int]:
    result = dict(balances)
    for t in transfers:
        result[t["from_member_id"]] += t["amount_paise"]
        result[t["to_member_id"]] -= t["amount_paise"]
    return result


def _greedy_largest_pair(net_balances: dict[str, int]) -> list[dict]:
    """Simple test-only greedy: largest debtor pays largest creditor."""
    creditors = [[m, a] for m, a in net_balances.items() if a > 0]
    debtors = [[m, -a] for m, a in net_balances.items() if a < 0]
    transfers = []
    while creditors and debtors:
        c = max(creditors, key=lambda x: (x[1], -ord(x[0][0])))
        d = max(debtors, key=lambda x: (x[1], -ord(x[0][0])))
        amt = min(c[1], d[1])
        transfers.append({"from_member_id": d[0], "to_member_id": c[0], "amount_paise": amt})
        c[1] -= amt
        d[1] -= amt
        if c[1] == 0:
            creditors.remove(c)
        if d[1] == 0:
            debtors.remove(d)
    return transfers


def _oracle_min_transfers(net_balances: dict[str, int]) -> int:
    """Independent recursive zero-sum partition oracle for small n."""
    nonzero = [amt for amt in net_balances.values() if amt != 0]
    if not nonzero:
        return 0
    n = len(nonzero)

    def max_zero_groups(remaining: tuple[int, ...]) -> int:
        if not remaining:
            return 0
        first, *rest = remaining
        best = 0
        m = len(rest)
        # Find all subsets of `rest` that sum to `-first`
        for mask in range(1 << m):
            group_sum = first
            next_rem = []
            for idx in range(m):
                if mask & (1 << idx):
                    group_sum += rest[idx]
                else:
                    next_rem.append(rest[idx])
            if group_sum == 0:
                candidate = 1 + max_zero_groups(tuple(next_rem))
                if candidate > best:
                    best = candidate
        return best

    return n - max_zero_groups(tuple(nonzero))


# --- Balance Tests ---


def test_one_person_pays_for_everyone():
    trip = _make_trip(
        ["a", "b", "c"],
        [_expense("e1", 9000, "a", ["a", "b", "c"])],
    )
    res = calculate_balances(trip)
    assert res["total_spend_paise"] == 9000
    by_id = {b["member_id"]: b for b in res["balances"]}
    assert by_id["a"]["net_balance_paise"] == 6000
    assert by_id["b"]["net_balance_paise"] == -3000
    assert by_id["c"]["net_balance_paise"] == -3000
    assert sum(b["net_balance_paise"] for b in res["balances"]) == 0


def test_selected_members_only():
    trip = _make_trip(
        ["a", "b", "c"],
        [_expense("e1", 4000, "a", ["a", "b"])],
    )
    by_id = {b["member_id"]: b for b in calculate_balances(trip)["balances"]}
    assert by_id["a"]["net_balance_paise"] == 2000
    assert by_id["b"]["net_balance_paise"] == -2000
    assert by_id["c"]["net_balance_paise"] == 0


def test_unequal_exact_shares():
    trip = _make_trip(
        ["a", "b", "c"],
        [_expense("e1", 1000, "a", ["a", "b", "c"], "unequal", {"a": 500, "b": 300, "c": 200})],
    )
    by_id = {b["member_id"]: b for b in calculate_balances(trip)["balances"]}
    assert by_id["a"]["net_balance_paise"] == 500
    assert by_id["b"]["net_balance_paise"] == -300
    assert by_id["c"]["net_balance_paise"] == -200


def test_payer_not_a_participant():
    trip = _make_trip(
        ["a", "b", "c"],
        [_expense("e1", 6000, "a", ["b", "c"])],
    )
    by_id = {b["member_id"]: b for b in calculate_balances(trip)["balances"]}
    assert by_id["a"]["total_paid_paise"] == 6000
    assert by_id["a"]["total_owed_paise"] == 0
    assert by_id["a"]["net_balance_paise"] == 6000
    assert by_id["b"]["net_balance_paise"] == -3000
    assert by_id["c"]["net_balance_paise"] == -3000


def test_zero_balance_member_and_empty_trip():
    empty_trip = _make_trip(["a", "b"], [])
    res = calculate_balances(empty_trip)
    assert res["total_spend_paise"] == 0
    assert [b["net_balance_paise"] for b in res["balances"]] == [0, 0]


def test_remainder_distribution_deterministic():
    trip = _make_trip(
        ["c", "a", "b"],
        [_expense("e1", 100, "c", ["c", "a", "b"])],
    )
    by_id = {b["member_id"]: b for b in calculate_balances(trip)["balances"]}
    # Sorted participant IDs: a, b, c -> a gets 34, b gets 33, c gets 33
    assert by_id["a"]["total_owed_paise"] == 34
    assert by_id["b"]["total_owed_paise"] == 33
    assert by_id["c"]["total_owed_paise"] == 33
    assert sum(b["net_balance_paise"] for b in calculate_balances(trip)["balances"]) == 0


@pytest.mark.parametrize(
    "bad_expense",
    [
        _expense("bad-zero", 0, "a", ["a", "b"]),
        _expense("bad-neg", -100, "a", ["a", "b"]),
        _expense("bad-float", 100.5, "a", ["a", "b"]),
        _expense("bad-bool", True, "a", ["a", "b"]),
        _expense("bad-payer", 100, "z", ["a", "b"]),
        _expense("bad-empty-part", 100, "a", []),
        _expense("bad-dup-part", 100, "a", ["a", "a"]),
        _expense("bad-foreign-part", 100, "a", ["a", "z"]),
        _expense("bad-split-type", 100, "a", ["a", "b"], split_type="percent"),
        _expense("bad-shares-keys", 100, "a", ["a", "b"], "unequal", {"a": 100}),
        _expense("bad-shares-float", 100, "a", ["a", "b"], "unequal", {"a": 50.0, "b": 50}),
        _expense("bad-shares-bool", 100, "a", ["a", "b"], "unequal", {"a": True, "b": 99}),
        _expense("bad-shares-zero", 100, "a", ["a", "b"], "unequal", {"a": 0, "b": 100}),
        _expense("bad-shares-sum", 100, "a", ["a", "b"], "unequal", {"a": 40, "b": 40}),
    ],
)
def test_invalid_expense_rejected(bad_expense):
    trip = _make_trip(["a", "b"], [bad_expense])
    with pytest.raises(ValueError, match=bad_expense["id"]):
        calculate_balances(trip)


# --- Settlement Tests ---


def test_reference_scenario():
    trip = _make_trip(
        ["alice", "bob", "charlie", "david"],
        [
            _expense("e1", 120000, "alice", ["alice", "bob", "charlie", "david"]),
            _expense("e2", 60000, "bob", ["bob", "charlie"]),
            _expense("e3", 40000, "charlie", ["alice", "david"]),
        ],
    )
    balances = {b["member_id"]: b["net_balance_paise"] for b in calculate_balances(trip)["balances"]}
    assert balances == {"alice": 70000, "bob": 0, "charlie": -20000, "david": -50000}

    settlement = calculate_settlements(trip)
    assert settlement["payment_count"] == 2
    assert settlement["is_exact_minimal"] is True
    assert settlement["transfers"] == [
        {
            "from_member_id": "charlie",
            "from_member_name": "Charlie",
            "to_member_id": "alice",
            "to_member_name": "Alice",
            "amount_paise": 20000,
        },
        {
            "from_member_id": "david",
            "from_member_name": "David",
            "to_member_id": "alice",
            "to_member_name": "Alice",
            "amount_paise": 50000,
        },
    ]


def test_greedy_is_not_minimal():
    net = {"A": 1000, "B": 900, "C": -400, "D": -600, "E": -900}
    greedy_transfers = _greedy_largest_pair(net)
    assert len(greedy_transfers) == 4

    exact_transfers, is_exact = optimize_settlements(net)
    assert is_exact is True
    assert len(exact_transfers) == 3
    assert exact_transfers == [
        {"from_member_id": "C", "to_member_id": "A", "amount_paise": 400},
        {"from_member_id": "D", "to_member_id": "A", "amount_paise": 600},
        {"from_member_id": "E", "to_member_id": "B", "amount_paise": 900},
    ]


def test_randomized_against_oracle():
    rng = random.Random(12345)
    for _ in range(200):
        n = rng.randint(2, 8)
        members = [f"m{i}" for i in range(n)]
        vals = [rng.randint(-5000, 5000) for _ in range(n - 1)]
        vals.append(-sum(vals))
        net = dict(zip(members, vals))

        transfers, is_exact = optimize_settlements(net)
        assert is_exact is True
        assert len(transfers) == _oracle_min_transfers(net)
        assert len(transfers) <= max(0, sum(1 for v in vals if v != 0) - 1)
        assert all(v == 0 for v in _apply_transfers(net, transfers).values())
        for t in transfers:
            assert isinstance(t["amount_paise"], int) and t["amount_paise"] > 0
            assert t["from_member_id"] != t["to_member_id"]

        # Deterministic check
        transfers_again, _ = optimize_settlements(net)
        assert transfers == transfers_again


def test_exact_limit_boundary():
    exact_12 = {f"m{i:02d}": 100 for i in range(11)}
    exact_12["m11"] = -1100
    transfers_12, is_exact_12 = optimize_settlements(exact_12)
    assert len(exact_12) == EXACT_LIMIT
    assert is_exact_12 is True
    assert all(v == 0 for v in _apply_transfers(exact_12, transfers_12).values())

    fallback_13 = {f"m{i:02d}": 1 for i in range(12)}
    fallback_13["m12"] = -12
    transfers_13, is_exact_13 = optimize_settlements(fallback_13)
    assert is_exact_13 is False
    assert all(v == 0 for v in _apply_transfers(fallback_13, transfers_13).values())


def test_empty_settlement():
    transfers, is_exact = optimize_settlements({"a": 0, "b": 0})
    assert transfers == []
    assert is_exact is True


def test_all_seeded_trips():
    for trip_id, trip in seeded_trips.items():
        bal_res = calculate_balances(trip)
        assert len(bal_res["balances"]) == len(trip["members"])
        assert sum(b["net_balance_paise"] for b in bal_res["balances"]) == 0

        settle_res = calculate_settlements(trip)
        assert settle_res["payment_count"] == len(settle_res["transfers"])
        assert settle_res["is_exact_minimal"] is True
        net_map = {b["member_id"]: b["net_balance_paise"] for b in bal_res["balances"]}
        assert all(v == 0 for v in _apply_transfers(net_map, settle_res["transfers"]).values())
