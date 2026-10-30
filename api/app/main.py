from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import check_settings, settings
from app.middleware import BodySizeLimitMiddleware
from app.routers import (
    admin,
    advisor,
    applications,
    auth,
    documents,
    profile,
    programs,
    review_criteria,
    roadmap,
    universities,
)
from app.services.documents import MAX_UPLOAD_BYTES, TOO_LARGE

# Refuse to start with login mode on in production and no real mail backend (account-login D2).
check_settings(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # The advisor's checkpoint pool opens on its first use; give its connections back on shutdown.
    from app.agent.checkpoint import checkpointer

    checkpointer.close()


app = FastAPI(title="LeapAshore API", lifespan=lifespan)

# Registered before the routes so an oversize upload is refused before the multipart parser spools
# it to a temporary file; the upload service counts the bytes as a second line of defence.
app.add_middleware(
    BodySizeLimitMiddleware,
    max_bytes=MAX_UPLOAD_BYTES,
    paths=("/api/documents",),
    detail=TOO_LARGE,
)

app.include_router(admin.router)
app.include_router(advisor.router)
app.include_router(applications.router)
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(profile.router)
app.include_router(programs.router)
app.include_router(review_criteria.router)
app.include_router(roadmap.router)
app.include_router(universities.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness probe. Kept dependency-free so it works before the database exists."""
    return {"status": "ok"}
