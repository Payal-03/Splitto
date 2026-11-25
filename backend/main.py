from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictInt

from backend.domain import calculate_balances, calculate_settlements, calculate_summary
from backend.storage import (
    add_expense,
    add_member,
    add_payment,
    create_trip,
    get_trip,
    list_payments,
    list_trips as load_all_trips,
)

app = FastAPI(title="Splitto API")


class TripCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


class MemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


class ExpenseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    amount_paise: StrictInt
    payer_id: str
    category: str
    participant_ids: list[str]
    split_type: str
    shares: dict[str, StrictInt] | None = None


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_member_id: str
    to_member_id: str
    amount_paise: StrictInt


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request, exc: RequestValidationError):
    messages = [
        f"{'.'.join(str(loc) for loc in err['loc'] if loc != 'body')}: {err['msg']}"
        for err in exc.errors()
    ]
    return JSONResponse(status_code=400, content={"detail": "; ".join(messages)})


def _get_trip_or_404(trip_id: str) -> dict:
    trip = get_trip(trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail=f"Trip '{trip_id}' not found")
    return trip


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/trips")
def list_trips():
    return load_all_trips()


@app.post("/api/trips", status_code=201)
def create_new_trip(payload: TripCreate):
    try:
        return create_trip(payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/trips/{trip_id}/members", status_code=201)
def create_member(trip_id: str, payload: MemberCreate):
    _get_trip_or_404(trip_id)
    try:
        return add_member(trip_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@app.post("/api/trips/{trip_id}/payments", status_code=201)
def create_payment(trip_id: str, payload: PaymentCreate):
    _get_trip_or_404(trip_id)
    try:
        return add_payment(trip_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/trips/{trip_id}/payments")
def get_trip_payments(trip_id: str):
    _get_trip_or_404(trip_id)
    payments = list_payments(trip_id)
    return {
        "trip_id": trip_id,
        "payments": payments,
        "total_settled_paise": sum(p["amount_paise"] for p in payments),
    }


@app.get("/api/trips/{trip_id}/summary")
def get_trip_summary(trip_id: str):
    return calculate_summary(_get_trip_or_404(trip_id))
