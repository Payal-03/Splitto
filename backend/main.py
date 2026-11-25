from fastapi import FastAPI, HTTPException
from backend.domain import calculate_balances, calculate_settlements
from backend.storage import trips

app = FastAPI(title="Splitto API")


def _get_trip_or_404(trip_id: str) -> dict:
    trip = trips.get(trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail=f"Trip '{trip_id}' not found")
    return trip


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/trips")
def list_trips():
    return list(trips.values())


@app.get("/api/trips/{trip_id}/balances")
def get_trip_balances(trip_id: str):
    return calculate_balances(_get_trip_or_404(trip_id))


@app.get("/api/trips/{trip_id}/settlements")
def get_trip_settlements(trip_id: str):
    return calculate_settlements(_get_trip_or_404(trip_id))
