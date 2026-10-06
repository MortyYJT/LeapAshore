from fastapi import FastAPI

from app.routers import profile

app = FastAPI(title="OfferPilot API")

app.include_router(profile.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness probe. Kept dependency-free so it works before the database exists."""
    return {"status": "ok"}
