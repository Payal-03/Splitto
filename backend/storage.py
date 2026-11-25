"""SQLite persistence layer for Splitto.

Seeds the five default trips once when the database is initialized for the
first time. Domain math and validation remain in backend/domain.py.
"""

import json
import os
import re
import sqlite3
from pathlib import Path

from backend.domain import validate_expense, validate_payment

_SEEDS_PATH = Path(__file__).resolve().parent / "seeds.json"
DEFAULT_DB_PATH = Path(os.environ.get("SPLITTO_DB_PATH", Path(__file__).resolve().parent / "splitto.db"))

_active_db_path: Path = DEFAULT_DB_PATH
# Kept for backwards compatibility with read-only inspection and test monkeypatching
trips: dict[str, dict] = {}


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or _active_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    """Create tables if missing and seed default trips only on first init."""
    global _active_db_path
    if db_path is not None:
        _active_db_path = Path(db_path)

    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trips (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS members (
                id TEXT PRIMARY KEY,
                trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                position INTEGER NOT NULL,
                UNIQUE(trip_id, name)
            );
            CREATE TABLE IF NOT EXISTS expenses (
                id TEXT PRIMARY KEY,
                trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
                description TEXT NOT NULL,
                amount_paise INTEGER NOT NULL,
                payer_id TEXT NOT NULL REFERENCES members(id),
                category TEXT NOT NULL,
                participant_ids TEXT NOT NULL,
                split_type TEXT NOT NULL,
                shares TEXT,
                position INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS payments (
                id TEXT PRIMARY KEY,
                trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
                from_member_id TEXT NOT NULL REFERENCES members(id),
                to_member_id TEXT NOT NULL REFERENCES members(id),
                amount_paise INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                position INTEGER NOT NULL
            );
            """
        )

        count = conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
        if count == 0:
            _seed_database(conn)

    refresh_trips_cache()


def _seed_database(conn: sqlite3.Connection) -> None:
    seed_trips = json.loads(_SEEDS_PATH.read_text(encoding="utf-8"))
    for trip in seed_trips:
        conn.execute("INSERT INTO trips (id, name) VALUES (?, ?)", (trip["id"], trip["name"]))
        for pos, member in enumerate(trip["members"]):
            conn.execute(
                "INSERT INTO members (id, trip_id, name, position) VALUES (?, ?, ?, ?)",
                (member["id"], trip["id"], member["name"], pos),
            )
        for pos, exp in enumerate(trip["expenses"]):
            conn.execute(
                """
                INSERT INTO expenses (
                    id, trip_id, description, amount_paise, payer_id,
                    category, participant_ids, split_type, shares, position
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exp["id"],
                    trip["id"],
                    exp["description"],
                    exp["amount_paise"],
                    exp["payer_id"],
                    exp["category"],
                    json.dumps(exp["participant_ids"]),
                    exp["split_type"],
                    json.dumps(exp["shares"]) if "shares" in exp else None,
                    pos,
                ),
            )


def _row_to_expense(row: sqlite3.Row) -> dict:
    expense = {
        "id": row["id"],
        "description": row["description"],
        "amount_paise": row["amount_paise"],
        "payer_id": row["payer_id"],
        "category": row["category"],
        "participant_ids": json.loads(row["participant_ids"]),
        "split_type": row["split_type"],
    }
    if row["shares"] is not None:
        expense["shares"] = json.loads(row["shares"])
    return expense


def _row_to_payment(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "trip_id": row["trip_id"],
        "from_member_id": row["from_member_id"],
        "to_member_id": row["to_member_id"],
        "amount_paise": row["amount_paise"],
        "created_at": row["created_at"],
    }


def _load_trip(conn: sqlite3.Connection, trip_row: sqlite3.Row) -> dict:
    trip_id = trip_row["id"]
    member_rows = conn.execute(
        "SELECT id, name FROM members WHERE trip_id = ? ORDER BY position ASC",
        (trip_id,),
    ).fetchall()
    expense_rows = conn.execute(
        "SELECT * FROM expenses WHERE trip_id = ? ORDER BY position ASC",
        (trip_id,),
    ).fetchall()
    payment_rows = conn.execute(
        "SELECT * FROM payments WHERE trip_id = ? ORDER BY position ASC",
        (trip_id,),
    ).fetchall()

    return {
        "id": trip_id,
        "name": trip_row["name"],
        "members": [{"id": r["id"], "name": r["name"]} for r in member_rows],
        "expenses": [_row_to_expense(r) for r in expense_rows],
        "payments": [_row_to_payment(r) for r in payment_rows],
    }


def refresh_trips_cache() -> None:
    trips.clear()
    for trip in list_trips():
        trips[trip["id"]] = trip


def list_trips() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT id, name FROM trips ORDER BY rowid ASC").fetchall()
        return [_load_trip(conn, row) for row in rows]


def get_trip(trip_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT id, name FROM trips WHERE id = ?", (trip_id,)).fetchone()
        if row is not None:
            return _load_trip(conn, row)
    return trips.get(trip_id)


def create_trip(name: str) -> dict:
    clean_name = name.strip() if isinstance(name, str) else ""
    if not clean_name:
        raise ValueError("Trip name must not be empty")

    base_slug = re.sub(r"[^a-z0-9]+", "-", clean_name.lower()).strip("-") or "trip"
    with _connect() as conn:
        existing_ids = {
            r[0] for r in conn.execute("SELECT id FROM trips").fetchall()
        }
        trip_id = base_slug
        suffix = 2
        while trip_id in existing_ids:
            trip_id = f"{base_slug}-{suffix}"
            suffix += 1

        conn.execute("INSERT INTO trips (id, name) VALUES (?, ?)", (trip_id, clean_name))

    refresh_trips_cache()
    return {"id": trip_id, "name": clean_name}


def add_member(trip_id: str, name: str) -> dict:
    clean_name = name.strip() if isinstance(name, str) else ""
    if not clean_name:
        raise ValueError("Member name must not be empty")

    with _connect() as conn:
        if conn.execute("SELECT 1 FROM trips WHERE id = ?", (trip_id,)).fetchone() is None:
            raise KeyError(trip_id)

        existing = conn.execute(
            "SELECT id, name FROM members WHERE trip_id = ? ORDER BY position ASC",
            (trip_id,),
        ).fetchall()
        if any(r["name"].strip().lower() == clean_name.lower() for r in existing):
            raise ValueError(f"Member '{clean_name}' already exists in trip '{trip_id}'")

        max_num = max(
            (int(r["id"].rsplit("-m", 1)[1]) for r in existing if "-m" in r["id"]),
            default=0,
        )
        member_id = f"{trip_id}-m{max_num + 1}"
        conn.execute(
            "INSERT INTO members (id, trip_id, name, position) VALUES (?, ?, ?, ?)",
            (member_id, trip_id, clean_name, len(existing)),
        )

    refresh_trips_cache()
    return {"id": member_id, "name": clean_name}


def _next_expense_id(trip_id: str, expenses: list[dict]) -> str:
    max_num = max(
        (int(exp["id"].rsplit("-e", 1)[1]) for exp in expenses if "-e" in exp["id"]),
        default=0,
    )
    return f"{trip_id}-e{max_num + 1:02d}"


def add_expense(trip_id: str, expense_data: dict) -> dict:
    """Validate and persist an expense to SQLite."""
    trip = get_trip(trip_id)
    if trip is None:
        raise KeyError(trip_id)

    expense = {"id": _next_expense_id(trip_id, trip["expenses"]), **expense_data}
    validate_expense(expense, {m["id"] for m in trip["members"]})

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO expenses (
                id, trip_id, description, amount_paise, payer_id,
                category, participant_ids, split_type, shares, position
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                expense["id"],
                trip_id,
                expense["description"],
                expense["amount_paise"],
                expense["payer_id"],
                expense["category"],
                json.dumps(expense["participant_ids"]),
                expense["split_type"],
                json.dumps(expense["shares"]) if "shares" in expense else None,
                len(trip["expenses"]),
            ),
        )

    refresh_trips_cache()
    return expense


def add_payment(trip_id: str, payment_data: dict) -> dict:
    """Validate against current debtor/creditor balances and persist a payment."""
    trip = get_trip(trip_id)
    if trip is None:
        raise KeyError(trip_id)

    validate_payment(trip, payment_data)

    payments = trip.get("payments", [])
    max_num = max(
        (int(p["id"].rsplit("-p", 1)[1]) for p in payments if "-p" in p["id"]),
        default=0,
    )
    payment_id = f"{trip_id}-p{max_num + 1:02d}"

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO payments (
                id, trip_id, from_member_id, to_member_id, amount_paise, position
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payment_id,
                trip_id,
                payment_data["from_member_id"],
                payment_data["to_member_id"],
                payment_data["amount_paise"],
                len(payments),
            ),
        )
        row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()

    refresh_trips_cache()
    names = {m["id"]: m["name"] for m in trip["members"]}
    saved = _row_to_payment(row)
    saved["from_member_name"] = names[saved["from_member_id"]]
    saved["to_member_name"] = names[saved["to_member_id"]]
    return saved


def list_payments(trip_id: str) -> list[dict]:
    trip = get_trip(trip_id)
    if trip is None:
        raise KeyError(trip_id)

    names = {m["id"]: m["name"] for m in trip["members"]}
    return [
        {
            **p,
            "from_member_name": names[p["from_member_id"]],
            "to_member_name": names[p["to_member_id"]],
        }
        for p in trip.get("payments", [])
    ]


init_db()
