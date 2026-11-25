"""In-memory store loaded from seeds.json at import time."""

import json
from pathlib import Path
from backend.domain import validate_expense

_seeds_path = Path(__file__).resolve().parent / "seeds.json"
_data: list[dict] = json.loads(_seeds_path.read_text(encoding="utf-8"))

# Keyed by trip id for O(1) lookup
trips: dict[str, dict] = {trip["id"]: trip for trip in _data}


def _next_expense_id(trip_id: str, expenses: list[dict]) -> str:
    max_num = max(
        (int(exp["id"].rsplit("-e", 1)[1]) for exp in expenses if "-e" in exp["id"]),
        default=0,
    )
    return f"{trip_id}-e{max_num + 1:02d}"


def add_expense(trip_id: str, expense_data: dict) -> dict:
    """Validate and append an expense to the trip's in-memory list."""
    trip = trips[trip_id]
    expense = {"id": _next_expense_id(trip_id, trip["expenses"]), **expense_data}
    validate_expense(expense, {m["id"] for m in trip["members"]})
    trip["expenses"].append(expense)
    return expense
