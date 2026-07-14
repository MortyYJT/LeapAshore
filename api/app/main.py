import os
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .data import UNIVERSITIES
from .models import (
    ActionPlanResponse,
    AgentRecommendationResponse,
    ApplicantProfile,
    AuthResponse,
    DemoUser,
    LoginRequest,
    Program,
    RecommendationResponse,
    RecommendationRunSummary,
    University,
)
from .program_data import PROGRAMS
from .services.action_plan import build_action_plan
from .services.agent import run_recommendation_agent
from .services.recommender import generate_recommendations
from .store import store

app = FastAPI(
    title="OfferPilot API",
    description="澳洲八大留学申请规划 Demo API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)


def current_user(authorization: Annotated[str | None, Header()] = None) -> DemoUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer token")
    user = store.user_for_token(authorization.split(" ", 1)[1])
    if not user:
        raise HTTPException(status_code=401, detail="登录已失效")
    return user


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest) -> AuthResponse:
    token, user = store.login(payload.email)
    return AuthResponse(access_token=token, user=user)


@app.get("/universities", response_model=list[University])
def list_universities() -> list[University]:
    return UNIVERSITIES


@app.get("/programs", response_model=list[Program])
def list_programs() -> list[Program]:
    return PROGRAMS


@app.get("/programs/{slug}", response_model=Program)
def get_program(slug: str) -> Program:
    program = next((item for item in PROGRAMS if item.slug == slug), None)
    if not program:
        raise HTTPException(status_code=404, detail="项目不存在")
    return program


@app.get("/me/profile", response_model=ApplicantProfile)
def get_my_profile(user: Annotated[DemoUser, Depends(current_user)]) -> ApplicantProfile:
    profile = store.get_profile(user.id)
    if not profile:
        raise HTTPException(status_code=404, detail="尚未创建申请背景")
    return profile


@app.put("/me/profile", response_model=ApplicantProfile)
def save_my_profile(profile: ApplicantProfile, user: Annotated[DemoUser, Depends(current_user)]) -> ApplicantProfile:
    return store.save_profile(user.id, profile)


@app.post("/recommendations", response_model=RecommendationResponse)
def recommendations(profile: ApplicantProfile) -> RecommendationResponse:
    return generate_recommendations(profile)


@app.post("/agent/recommendations", response_model=AgentRecommendationResponse)
def agent_recommendations(profile: ApplicantProfile) -> AgentRecommendationResponse:
    return run_recommendation_agent(profile)


@app.post("/me/recommendation-runs", response_model=AgentRecommendationResponse)
def create_recommendation_run(user: Annotated[DemoUser, Depends(current_user)]) -> AgentRecommendationResponse:
    profile = store.get_profile(user.id)
    if not profile:
        raise HTTPException(status_code=409, detail="请先保存申请背景")
    result = run_recommendation_agent(profile)
    store.save_run(user.id, profile, result)
    return result


@app.get("/me/recommendation-runs", response_model=list[RecommendationRunSummary])
def list_recommendation_runs(user: Annotated[DemoUser, Depends(current_user)]) -> list[RecommendationRunSummary]:
    return store.list_runs(user.id)


@app.get("/me/recommendation-runs/{run_id}", response_model=AgentRecommendationResponse)
def get_recommendation_run(run_id: str, user: Annotated[DemoUser, Depends(current_user)]) -> AgentRecommendationResponse:
    result = store.get_run(user.id, run_id)
    if not result:
        raise HTTPException(status_code=404, detail="推荐记录不存在")
    return result


@app.get("/me/recommendation-runs/{run_id}/action-plan", response_model=ActionPlanResponse)
def get_action_plan(run_id: str, user: Annotated[DemoUser, Depends(current_user)]) -> ActionPlanResponse:
    result = store.get_run(user.id, run_id)
    if not result:
        raise HTTPException(status_code=404, detail="推荐记录不存在")
    return build_action_plan(result)
