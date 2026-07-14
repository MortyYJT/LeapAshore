from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .data import UNIVERSITIES
from .models import ApplicantProfile, RecommendationResponse, University
from .services.recommender import generate_recommendations

app = FastAPI(
    title="OfferPilot API",
    description="澳洲八大留学申请规划 Demo API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/universities", response_model=list[University])
def list_universities() -> list[University]:
    return UNIVERSITIES


@app.post("/recommendations", response_model=RecommendationResponse)
def recommendations(profile: ApplicantProfile) -> RecommendationResponse:
    return generate_recommendations(profile)
