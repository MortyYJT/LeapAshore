from fastapi import FastAPI

from app.middleware import BodySizeLimitMiddleware
from app.routers import (
    applications,
    documents,
    profile,
    programs,
    review_criteria,
    roadmap,
)
from app.services.documents import MAX_UPLOAD_BYTES, TOO_LARGE

app = FastAPI(title="OfferPilot API")

# Registered before the routes so an oversize upload is refused before the multipart parser spools
# it to a temporary file; the upload service counts the bytes as a second line of defence.
app.add_middleware(
    BodySizeLimitMiddleware,
    max_bytes=MAX_UPLOAD_BYTES,
    paths=("/api/documents",),
    detail=TOO_LARGE,
)

app.include_router(applications.router)
app.include_router(documents.router)
app.include_router(profile.router)
app.include_router(programs.router)
app.include_router(review_criteria.router)
app.include_router(roadmap.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness probe. Kept dependency-free so it works before the database exists."""
    return {"status": "ok"}
