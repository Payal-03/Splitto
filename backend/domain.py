"""Pure balance calculation and minimum-payment settlement optimization.

All monetary values are integer paise. No floats, true division, or I/O.
"""

EXACT_LIMIT = 12
CATEGORIES = ("Accommodation", "Food", "Transport", "Fuel", "Activities", "Shopping", "Other")


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_expense(expense: dict, member_ids: set[str]) -> None:
    exp_id = expense.get("id", "<unknown>")
    description = expense.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"Expense {exp_id}: description must be a non-empty string")

    if expense.get("category") not in CATEGORIES:
        raise ValueError(f"Expense {exp_id}: category must be one of {', '.join(CATEGORIES)}")

    amount = expense.get("amount_paise")
    if not _is_positive_int(amount):
        raise ValueError(f"Expense {exp_id}: amount_paise must be a positive integer")

    if expense.get("payer_id") not in member_ids:
        raise ValueError(f"Expense {exp_id}: payer_id is not a trip member")

    participants = expense.get("participant_ids")
    if not isinstance(participants, list) or not participants:
        raise ValueError(f"Expense {exp_id}: participant_ids must be a non-empty list")

    participant_set = set(participants)
    if len(participant_set) != len(participants):
        raise ValueError(f"Expense {exp_id}: participant_ids contains duplicates")

    if not participant_set.issubset(member_ids):
        raise ValueError(f"Expense {exp_id}: participant_ids contains non-members")

    split_type = expense.get("split_type")
    if split_type not in ("equal", "unequal"):
        raise ValueError(f"Expense {exp_id}: split_type must be 'equal' or 'unequal'")

    if split_type == "equal" and "shares" in expense:
        raise ValueError(f"Expense {exp_id}: shares must not be provided for equal split")

    if split_type == "unequal":
        shares = expense.get("shares")
        if not isinstance(shares, dict) or set(shares.keys()) != participant_set:
            raise ValueError(f"Expense {exp_id}: shares keys must match participant_ids")
        if not all(_is_positive_int(share) for share in shares.values()):
            raise ValueError(f"Expense {exp_id}: all shares must be positive integers")
        if sum(shares.values()) != amount:
            raise ValueError(f"Expense {exp_id}: shares must sum to amount_paise")


def _expense_shares(expense: dict) -> dict[str, int]:
    if expense["split_type"] == "unequal":
        return expense["shares"]
    participants = sorted(expense["participant_ids"])
    base, remainder = divmod(expense["amount_paise"], len(participants))
    return {
        pid: base + (1 if idx < remainder else 0)
        for idx, pid in enumerate(participants)
    }


def calculate_balances(trip: dict) -> dict:
    """Compute per-member paid, owed, and payment-adjusted net balance in integer paise."""
    members = trip["members"]
    member_ids = {m["id"] for m in members}
    paid = {m["id"]: 0 for m in members}
    owed = {m["id"]: 0 for m in members}
    total_spend_paise = 0

    for expense in trip["expenses"]:
        validate_expense(expense, member_ids)
        amount = expense["amount_paise"]
        total_spend_paise += amount
        paid[expense["payer_id"]] += amount
        for pid, share in _expense_shares(expense).items():
            owed[pid] += share

    # Actual payments adjust net balances without altering expense-derived paid/owed
    net = {mid: paid[mid] - owed[mid] for mid in member_ids}
    for payment in trip.get("payments", []):
        amt = payment["amount_paise"]
        net[payment["from_member_id"]] += amt
        net[payment["to_member_id"]] -= amt

    return {
        "trip_id": trip["id"],
        "total_spend_paise": total_spend_paise,
        "balances": [
            {
                "member_id": m["id"],
                "member_name": m["name"],
                "total_paid_paise": paid[m["id"]],
                "total_owed_paise": owed[m["id"]],
                "net_balance_paise": net[m["id"]],
            }
            for m in members
        ],
    }


def validate_payment(trip: dict, payment: dict) -> None:
    """Validate a settlement payment against current debtor/creditor positions."""
    member_ids = {m["id"] for m in trip["members"]}
    from_id = payment.get("from_member_id")
    to_id = payment.get("to_member_id")
    amount = payment.get("amount_paise")

    if not _is_positive_int(amount):
        raise ValueError("amount_paise must be a positive integer")
    if from_id not in member_ids:
        raise ValueError("from_member_id is not a trip member")
    if to_id not in member_ids:
        raise ValueError("to_member_id is not a trip member")
    if from_id == to_id:
        raise ValueError("from_member_id and to_member_id cannot be the same member")

    net_by_id = {
        b["member_id"]: b["net_balance_paise"]
        for b in calculate_balances(trip)["balances"]
    }
    sender_net = net_by_id[from_id]
    receiver_net = net_by_id[to_id]
    if sender_net >= 0:
        raise ValueError(f"Member '{from_id}' does not owe any money")
    if receiver_net <= 0:
        raise ValueError(f"Member '{to_id}' is not owed any money")

    max_payable = min(-sender_net, receiver_net)
    if amount > max_payable:
        raise ValueError(
            f"Payment of {amount} paise exceeds outstanding limit of {max_payable} paise"
        )


def _settle_group_two_pointer(group: list[tuple[str, int]]) -> list[dict]:
    creditors = sorted(
        [[mid, amt] for mid, amt in group if amt > 0],
        key=lambda item: (-item[1], item[0]),
    )
    debtors = sorted(
        [[mid, -amt] for mid, amt in group if amt < 0],
        key=lambda item: (-item[1], item[0]),
    )
    transfers = []
    ci = 0
    di = 0
    while ci < len(creditors) and di < len(debtors):
        transfer_amt = min(creditors[ci][1], debtors[di][1])
        transfers.append(
            {
                "from_member_id": debtors[di][0],
                "to_member_id": creditors[ci][0],
                "amount_paise": transfer_amt,
            }
        )
        creditors[ci][1] -= transfer_amt
        debtors[di][1] -= transfer_amt
        if creditors[ci][1] == 0:
            ci += 1
        if debtors[di][1] == 0:
            di += 1
    return transfers


def _settle_exact_dp(items: list[tuple[str, int]]) -> list[dict]:
    """Exact minimum-transfer settlement via bitmask DP.

    Complexity: O(2^n * n) time, O(2^n) memory (at most ~49k ops for n = 12).
    """
    n = len(items)
    full = (1 << n) - 1
    sum_of = [0] * (1 << n)
    for mask in range(1, 1 << n):
        lsb = mask & -mask
        sum_of[mask] = sum_of[mask ^ lsb] + items[lsb.bit_length() - 1][1]

    best = [0] * (1 << n)
    for mask in range(1, 1 << n):
        max_prev = 0
        for i in range(n):
            if mask & (1 << i):
                prev = best[mask ^ (1 << i)]
                if prev > max_prev:
                    max_prev = prev
        best[mask] = max_prev + (1 if sum_of[mask] == 0 else 0)

    groups: list[list[tuple[str, int]]] = []
    mask = full
    last_zero_mask = full
    while mask > 0:
        target = best[mask] - (1 if sum_of[mask] == 0 else 0)
        for i in range(n):
            if (mask & (1 << i)) and best[mask ^ (1 << i)] == target:
                mask ^= 1 << i
                break
        if sum_of[mask] == 0:
            group_mask = last_zero_mask ^ mask
            groups.append([items[i] for i in range(n) if group_mask & (1 << i)])
            last_zero_mask = mask

    transfers = []
    for group in groups:
        transfers.extend(_settle_group_two_pointer(group))
    return transfers


def _settle_greedy_fallback(items: list[tuple[str, int]]) -> list[dict]:
    """Deterministic greedy fallback for groups larger than EXACT_LIMIT."""
    creditors = [[mid, amt] for mid, amt in items if amt > 0]
    debtors = [[mid, -amt] for mid, amt in items if amt < 0]
    transfers = []
    while creditors and debtors:
        creditor = min(creditors, key=lambda c: (-c[1], c[0]))
        debtor = min(debtors, key=lambda d: (-d[1], d[0]))
        transfer_amt = min(creditor[1], debtor[1])
        transfers.append(
            {
                "from_member_id": debtor[0],
                "to_member_id": creditor[0],
                "amount_paise": transfer_amt,
            }
        )
        creditor[1] -= transfer_amt
        debtor[1] -= transfer_amt
        if creditor[1] == 0:
            creditors.remove(creditor)
        if debtor[1] == 0:
            debtors.remove(debtor)
    return transfers


def optimize_settlements(net_balances: dict[str, int]) -> tuple[list[dict], bool]:
    """Compute settlement transfers for {member_id: net_paise}.

    Uses exact bitmask DP (O(2^n * n) time, O(2^n) memory) when non-zero
    members <= EXACT_LIMIT (12), and deterministic greedy fallback otherwise.
    Returns (sorted_transfers, is_exact_minimal).
    """
    items = sorted(
        ((mid, amt) for mid, amt in net_balances.items() if amt != 0),
        key=lambda item: item[0],
    )
    if not items:
        return [], True

    if len(items) <= EXACT_LIMIT:
        transfers = _settle_exact_dp(items)
        is_exact_minimal = True
    else:
        transfers = _settle_greedy_fallback(items)
        is_exact_minimal = False

    transfers.sort(key=lambda t: (t["from_member_id"], t["to_member_id"]))
    return transfers, is_exact_minimal


def calculate_settlements(trip: dict) -> dict:
    """Compute named settlement transfers for a trip."""
    balance_report = calculate_balances(trip)
    net_map = {
        b["member_id"]: b["net_balance_paise"]
        for b in balance_report["balances"]
    }
    transfers, is_exact_minimal = optimize_settlements(net_map)
    names = {m["id"]: m["name"] for m in trip["members"]}

    return {
        "trip_id": trip["id"],
        "transfers": [
            {
                "from_member_id": t["from_member_id"],
                "from_member_name": names[t["from_member_id"]],
                "to_member_id": t["to_member_id"],
                "to_member_name": names[t["to_member_id"]],
                "amount_paise": t["amount_paise"],
            }
            for t in transfers
        ],
        "payment_count": len(transfers),
        "is_exact_minimal": is_exact_minimal,
    }


def calculate_summary(trip: dict) -> dict:
    """Return combined trip balances, settlement recommendations, and payment summary."""
    balance_report = calculate_balances(trip)
    settlement_report = calculate_settlements(trip)
    names = {m["id"]: m["name"] for m in trip["members"]}
    payments = [
        {
            **p,
            "from_member_name": names[p["from_member_id"]],
            "to_member_name": names[p["to_member_id"]],
        }
        for p in trip.get("payments", [])
    ]
    return {
        "trip_id": trip["id"],
        "trip_name": trip["name"],
        "total_spend_paise": balance_report["total_spend_paise"],
        "total_settled_paise": sum(p["amount_paise"] for p in payments),
        "balances": balance_report["balances"],
        "settlements": {
            "transfers": settlement_report["transfers"],
            "payment_count": settlement_report["payment_count"],
            "is_exact_minimal": settlement_report["is_exact_minimal"],
        },
        "payments": payments,
    }
