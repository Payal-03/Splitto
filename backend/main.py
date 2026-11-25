from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictInt

from backend.domain import calculate_balances, calculate_settlements
from backend.storage import add_expense, trips

app = FastAPI(title="Splitto API")


class ExpenseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    amount_paise: StrictInt
    payer_id: str
    category: str
    participant_ids: list[str]
    split_type: str
    shares: dict[str, StrictInt] | None = None


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request, exc: RequestValidationError):
    messages = [
        f"{'.'.join(str(loc) for loc in err['loc'] if loc != 'body')}: {err['msg']}"
        for err in exc.errors()
    ]
    return JSONResponse(status_code=400, content={"detail": "; ".join(messages)})


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


@app.post("/api/trips/{trip_id}/expenses", status_code=201)
def create_expense(trip_id: str, payload: ExpenseCreate):
    _get_trip_or_404(trip_id)
    try:
        return add_expense(trip_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
