from fastapi import FastAPI

app = FastAPI(title="OfferPilot API")


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness probe. Kept dependency-free so it works before the database exists."""
    return {"status": "ok"}
