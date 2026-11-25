"""In-memory store loaded from seeds.json at import time."""

import json
from pathlib import Path

_seeds_path = Path(__file__).resolve().parent / "seeds.json"
_data: list[dict] = json.loads(_seeds_path.read_text(encoding="utf-8"))

# Keyed by trip id for O(1) lookup
trips: dict[str, dict] = {trip["id"]: trip for trip in _data}
