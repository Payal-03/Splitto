"""Deterministic seed data generator for Splitto.

Run: python -m backend.scripts.generate_seeds
Outputs: backend/seeds.json
"""

import json
import random
from pathlib import Path

SEED = 42

TRIPS = [
    {"slug": "goa", "name": "Goa Getaway", "member_count": 6, "expense_count": 30},
    {"slug": "manali", "name": "Manali Escape", "member_count": 5, "expense_count": 25},
    {"slug": "jaipur", "name": "Jaipur Heritage Tour", "member_count": 4, "expense_count": 22},
    {"slug": "rishikesh", "name": "Rishikesh Adventure", "member_count": 7, "expense_count": 35},
    {"slug": "mumbai", "name": "Mumbai Weekend", "member_count": 4, "expense_count": 20},
]

MEMBER_NAMES = [
    "Aarav", "Diya", "Kabir", "Meera", "Rohan", "Ananya", "Vihaan",
    "Ishita", "Arjun", "Priya", "Siddharth", "Nisha", "Karan", "Tanvi",
    "Aditya", "Riya", "Dhruv", "Kavya", "Nikhil", "Sneha", "Harsh",
    "Pooja", "Rahul", "Simran", "Yash", "Neha",
]

CATEGORIES = ["Accommodation", "Food", "Transport", "Fuel", "Activities", "Shopping", "Other"]

# Amount ranges in paise per category (min, max)
AMOUNT_RANGES = {
    "Accommodation": (800000, 3000000),
    "Food": (30000, 500000),
    "Transport": (50000, 800000),
    "Fuel": (150000, 400000),
    "Activities": (100000, 600000),
    "Shopping": (50000, 300000),
    "Other": (20000, 150000),
}

# Category weights: Accommodation and Food dominate
CATEGORY_WEIGHTS = [15, 30, 12, 8, 15, 12, 8]

EXPENSE_TEMPLATES = {
    "Accommodation": ["Hotel stay", "Resort booking", "Hostel room", "Airbnb rental", "Guest house"],
    "Food": [
        "Dinner at restaurant", "Street food lunch", "Breakfast cafe", "Chai and snacks",
        "Groceries for cooking", "Lunch thali", "Ice cream stop", "Dinner buffet",
    ],
    "Transport": ["Cab to station", "Auto rickshaw", "Bus tickets", "Train tickets", "Airport transfer"],
    "Fuel": ["Petrol fill-up", "Diesel refuel", "Highway toll", "Fuel for car"],
    "Activities": [
        "River rafting", "Paragliding", "Museum entry", "Fort tickets",
        "Boat ride", "Trekking guide", "Spa session", "Water sports",
    ],
    "Shopping": ["Souvenirs", "Local handicrafts", "Clothes shopping", "Spice market haul"],
    "Other": ["Parking fee", "Phone recharge", "Laundry", "Tips", "Medical supplies"],
}


def generate_members(slug, count, rng):
    names = rng.sample(MEMBER_NAMES, count)
    return [{"id": f"{slug}-m{i+1}", "name": name} for i, name in enumerate(names)]


def pick_category(rng):
    return rng.choices(CATEGORIES, weights=CATEGORY_WEIGHTS, k=1)[0]


def generate_expense(slug, index, members, rng, heavy_payer_ids):
    category = pick_category(rng)
    lo, hi = AMOUNT_RANGES[category]
    amount_paise = rng.randint(lo // 100, hi // 100) * 100  # round to whole rupees

    description = rng.choice(EXPENSE_TEMPLATES[category])

    # Heavy payers pay ~60% of the time
    if rng.random() < 0.6:
        payer = rng.choice(heavy_payer_ids)
    else:
        payer = rng.choice(members)["id"]

    # Decide split type: 60% equal-all, 25% equal-selected, 15% unequal
    roll = rng.random()
    member_ids = [m["id"] for m in members]

    if roll < 0.60:
        # Equal split among everyone
        participant_ids = member_ids[:]
        split_type = "equal"
        shares = None
    elif roll < 0.85:
        # Equal split among selected members (at least 2)
        subset_size = rng.randint(2, max(2, len(members) - 1))
        participant_ids = rng.sample(member_ids, subset_size)
        split_type = "equal"
        shares = None
        # Sometimes payer is not a participant
        if rng.random() < 0.2 and payer in participant_ids and len(participant_ids) > 2:
            participant_ids.remove(payer)
    else:
        # Unequal split
        subset_size = rng.randint(2, len(members))
        participant_ids = rng.sample(member_ids, subset_size)
        split_type = "unequal"
        shares = distribute_unequal(amount_paise, participant_ids, rng)
        # Sometimes payer doesn't participate
        if rng.random() < 0.25 and payer not in participant_ids:
            pass  # payer already not in participants
        elif rng.random() < 0.15 and payer in participant_ids and len(participant_ids) > 2:
            # Remove payer from participants, redistribute their share
            payer_share = shares.pop(payer)
            participant_ids.remove(payer)
            # Give removed share to first participant
            shares[participant_ids[0]] += payer_share

    return {
        "id": f"{slug}-e{index + 1:02d}",
        "description": description,
        "amount_paise": amount_paise,
        "payer_id": payer,
        "category": category,
        "participant_ids": participant_ids,
        "split_type": split_type,
        **({"shares": shares} if shares is not None else {}),
    }


def distribute_unequal(total, participant_ids, rng):
    """Distribute total paise unevenly across participants, summing exactly to total."""
    n = len(participant_ids)
    # Generate random weights and allocate proportionally
    weights = [rng.randint(1, 10) for _ in range(n)]
    weight_sum = sum(weights)

    allocated = [(total * w) // weight_sum for w in weights]
    remainder = total - sum(allocated)
    # Distribute remainder one paisa at a time
    for i in range(remainder):
        allocated[i % n] += 1

    return {pid: amt for pid, amt in zip(participant_ids, allocated)}


def generate_trip(trip_spec, rng):
    slug = trip_spec["slug"]
    members = generate_members(slug, trip_spec["member_count"], rng)

    # Pick 1-2 heavy payers for this trip
    heavy_count = 1 if len(members) <= 4 else 2
    heavy_payer_ids = [m["id"] for m in rng.sample(members, heavy_count)]

    expenses = [
        generate_expense(slug, i, members, rng, heavy_payer_ids)
        for i in range(trip_spec["expense_count"])
    ]

    return {
        "id": slug,
        "name": trip_spec["name"],
        "members": members,
        "expenses": expenses,
    }


def main():
    rng = random.Random(SEED)
    trips = [generate_trip(spec, rng) for spec in TRIPS]

    out_path = Path(__file__).resolve().parent.parent / "seeds.json"
    out_path.write_text(json.dumps(trips, indent=2), encoding="utf-8")
    print(f"Generated {len(trips)} trips -> {out_path}")


if __name__ == "__main__":
    main()
