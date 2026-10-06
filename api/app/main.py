from fastapi import FastAPI

from app.routers import profile, programs, roadmap

app = FastAPI(title="OfferPilot API")

app.include_router(profile.router)
app.include_router(programs.router)
app.include_router(roadmap.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness probe. Kept dependency-free so it works before the database exists."""
    return {"status": "ok"}
