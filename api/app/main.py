import os
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .data import UNIVERSITIES
from .models import (
    ActionPlanResponse,
    AdvisorMessage,
    AdvisorMessageRequest,
    AdvisorReply,
    AdvisorThread,
    AgentRecommendationResponse,
    ApplicantProfile,
    AuthResponse,
    DemoUser,
    LoginRequest,
    LLMStatus,
    Program,
    RecommendationResponse,
    RecommendationRunSummary,
    TranscriptAnalysisRequest,
    TranscriptAnalysisResponse,
    University,
)
from .program_data import PROGRAMS
from .services.action_plan import build_action_plan
from .services.advisor import plan_turn
from .services.agent import run_recommendation_agent
from .services.model_provider import configured_model, llm_is_configured
from .services.recommender import generate_recommendations
from .services.transcript import analyze_transcript
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


@app.get("/llm/status", response_model=LLMStatus)
def llm_status() -> LLMStatus:
    return LLMStatus(configured=llm_is_configured(), model=configured_model())


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


@app.post("/me/transcript/analyze", response_model=TranscriptAnalysisResponse)
def analyze_my_transcript(
    payload: TranscriptAnalysisRequest,
    user: Annotated[DemoUser, Depends(current_user)],
) -> TranscriptAnalysisResponse:
    profile = store.get_profile(user.id)
    if not profile:
        raise HTTPException(status_code=409, detail="请先保存申请背景")
    result = analyze_transcript(payload.transcript_text)
    if payload.save_to_profile and result.courses:
        profile.coursework_summary = "、".join(course.name for course in result.courses)
        store.save_profile(user.id, profile)
    return result


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


@app.post("/me/advisor/threads", response_model=AdvisorThread)
def create_advisor_thread(user: Annotated[DemoUser, Depends(current_user)]) -> AdvisorThread:
    profile = store.get_profile(user.id)
    if not profile:
        raise HTTPException(status_code=409, detail="请先保存申请背景")
    now = datetime.now(UTC)
    greeting = AdvisorMessage(
        id=f"msg_{uuid4().hex[:10]}",
        role="assistant",
        content=f"你好，我已经读取了你的申请档案。我们可以从 {profile.target_field} 的选校组合、背景补强或申请时间表开始。",
        created_at=now,
    )
    thread = AdvisorThread(
        id=f"thread_{uuid4().hex[:10]}",
        title=f"{profile.target_field} · {profile.intake}",
        messages=[greeting],
        created_at=now,
        updated_at=now,
    )
    return store.save_thread(user.id, thread)


@app.get("/me/advisor/threads", response_model=list[AdvisorThread])
def list_advisor_threads(user: Annotated[DemoUser, Depends(current_user)]) -> list[AdvisorThread]:
    return store.list_threads(user.id)


@app.get("/me/advisor/threads/{thread_id}", response_model=AdvisorThread)
def get_advisor_thread(thread_id: str, user: Annotated[DemoUser, Depends(current_user)]) -> AdvisorThread:
    thread = store.get_thread(user.id, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="顾问会话不存在")
    return thread


@app.post("/me/advisor/threads/{thread_id}/messages", response_model=AdvisorReply)
def send_advisor_message(
    thread_id: str,
    payload: AdvisorMessageRequest,
    user: Annotated[DemoUser, Depends(current_user)],
) -> AdvisorReply:
    thread = store.get_thread(user.id, thread_id)
    profile = store.get_profile(user.id)
    if not thread:
        raise HTTPException(status_code=404, detail="顾问会话不存在")
    if not profile:
        raise HTTPException(status_code=409, detail="请先保存申请背景")

    now = datetime.now(UTC)
    user_message = AdvisorMessage(id=f"msg_{uuid4().hex[:10]}", role="user", content=payload.content, created_at=now)
    history = [{"role": item.role, "content": item.content} for item in thread.messages]
    reply_text, actions, metadata = plan_turn(payload.content, profile, history)

    recommendation_run = None
    for action in actions:
        if action.tool == "update_profile" and action.arguments:
            try:
                profile = ApplicantProfile.model_validate({**profile.model_dump(), **action.arguments})
                store.save_profile(user.id, profile)
            except ValueError:
                action.status = "skipped"
                action.summary = "档案更新值未通过格式检查，已保留原数据"
        elif action.tool == "run_recommendation":
            recommendation_run = run_recommendation_agent(profile)
            store.save_run(user.id, profile, recommendation_run)

    assistant_message = AdvisorMessage(
        id=f"msg_{uuid4().hex[:10]}", role="assistant", content=reply_text, created_at=datetime.now(UTC), actions=actions
    )
    thread.messages.extend([user_message, assistant_message])
    thread.updated_at = assistant_message.created_at
    store.save_thread(user.id, thread)
    return AdvisorReply(thread=thread, profile=profile, recommendation_run=recommendation_run, **metadata)
