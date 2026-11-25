from fastapi import FastAPI
from backend.storage import trips

app = FastAPI(title="Splitto API")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/trips")
def list_trips():
    return list(trips.values())
