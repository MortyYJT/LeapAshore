import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from .data import UNIVERSITIES
from .catalog_data import CATALOG_COVERAGE
from .models import (
    ActionPlanResponse,
    AgentRunAudit,
    ApplicationTask,
    AdvisorMessage,
    AdvisorMessageRequest,
    AdvisorReply,
    AdvisorThread,
    AgentRecommendationResponse,
    ApplicantProfile,
    AuthResponse,
    AdminStats,
    AdminUserUpdateRequest,
    CatalogCoverage,
    CatalogFacets,
    DemoUser,
    DeleteAccountRequest,
    EmailRequest,
    EmailTokenRequest,
    FeedbackCreateRequest,
    FeedbackItem,
    FeedbackUpdateRequest,
    LoginRequest,
    MessageResponse,
    PasswordResetRequest,
    RegisterRequest,
    RegistrationResponse,
    LLMStatus,
    Program,
    ProgramSourceStatus,
    RecommendationResponse,
    RecommendationRunSummary,
    TranscriptAnalysisRequest,
    TranscriptAnalysisResponse,
    TaskCreateRequest,
    TaskUpdateRequest,
    University,
)
from .mailer import EmailDeliveryError, send_password_reset_email, send_verification_email
from .middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from .observability import configure_error_reporting
from .program_data import PROGRAMS
from .taxonomy import DEGREE_LEVELS, STUDY_AREAS, DegreeLevel, StudyArea
from .services.action_plan import build_action_plan
from .services.advisor import plan_turn
from .services.agent import run_recommendation_agent
from .services.model_provider import configured_model, configured_provider, llm_is_configured
from .services.recommender import generate_recommendations
from .services.transcript import analyze_transcript
from .settings import validate_runtime_configuration
from .store import (
    AccountExistsError,
    AccountSuspendedError,
    EmailNotVerifiedError,
    InvalidAuthTokenError,
    InvalidCredentialsError,
    store,
)

configure_error_reporting()
logger = logging.getLogger("offerpilot.mail")


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_runtime_configuration()
    yield

app = FastAPI(
    title="OfferPilot API",
    description="澳洲八大全层次课程探索与申请规划 API",
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


def current_user(
    authorization: Annotated[str | None, Header()] = None,
    session_cookie: Annotated[str | None, Cookie(alias="offerpilot_session")] = None,
) -> DemoUser:
    token = authorization.split(" ", 1)[1] if authorization and authorization.lower().startswith("bearer ") else session_cookie
    if not token:
        raise HTTPException(status_code=401, detail="缺少 Bearer token")
    user = store.user_for_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="登录已失效")
    return user


def current_admin(user: Annotated[DemoUser, Depends(current_user)]) -> DemoUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def validate_password_strength(password: str) -> None:
    if not any(character.isalpha() for character in password) or not any(character.isdigit() for character in password):
        raise HTTPException(status_code=422, detail="密码至少 8 位，并同时包含字母和数字")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/readiness")
def readiness() -> dict[str, str]:
    try:
        database = "connected" if store.healthcheck() else "unavailable"
    except Exception as error:
        raise HTTPException(status_code=503, detail="数据库暂不可用") from error
    return {
        "status": "ready",
        "llm": "configured" if llm_is_configured() else "fallback",
        "storage": store.__class__.__name__,
        "database": database,
        "email": "smtp" if os.getenv("SMTP_HOST") else "console",
    }


@app.get("/llm/status", response_model=LLMStatus)
def llm_status() -> LLMStatus:
    provider = configured_provider()
    return LLMStatus(
        configured=llm_is_configured(),
        provider=provider,
        model=configured_model(),
        api="ollama-chat" if provider == "ollama" else "responses",
    )


@app.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest, response: Response) -> AuthResponse:
    validate_password_strength(payload.password)
    try:
        token, user = store.login(payload.email, payload.password)
    except InvalidCredentialsError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except EmailNotVerifiedError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except AccountSuspendedError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    response.set_cookie(
        "offerpilot_session", token, max_age=60 * 60 * int(os.getenv("SESSION_TTL_HOURS", "168")),
        httponly=True, secure=os.getenv("APP_ENV", "development") == "production", samesite="lax", path="/",
    )
    return AuthResponse(access_token=token, user=user)


@app.post("/auth/register", response_model=RegistrationResponse, status_code=201)
def register(payload: RegisterRequest) -> RegistrationResponse:
    if not payload.accepted_terms:
        raise HTTPException(status_code=422, detail="请先同意服务条款与隐私说明")
    validate_password_strength(payload.password)
    try:
        user, token = store.register(payload.email, payload.password, payload.display_name)
    except AccountExistsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    try:
        delivery = send_verification_email(user.email, user.display_name, token)
    except EmailDeliveryError:
        logger.exception("verification_email_delivery_failed")
        delivery = "disabled"
    return RegistrationResponse(
        message=(
            "注册成功，请检查邮箱完成验证"
            if delivery != "disabled" else
            "账户已创建，但验证邮件暂未送达，请稍后点击重新发送"
        ),
        user=user,
        delivery=delivery,
        debug_token=token if os.getenv("APP_ENV", "development") != "production" else None,
    )


@app.post("/auth/verify-email", response_model=MessageResponse)
def verify_email(payload: EmailTokenRequest) -> MessageResponse:
    try:
        store.verify_email(payload.token)
    except InvalidAuthTokenError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return MessageResponse(message="邮箱验证成功，现在可以登录")


@app.post("/auth/resend-verification", response_model=MessageResponse)
def resend_verification(payload: EmailRequest) -> MessageResponse:
    result = store.create_email_verification(payload.email)
    if result:
        user, token = result
        try:
            send_verification_email(user.email, user.display_name, token)
        except EmailDeliveryError:
            logger.exception("verification_email_redelivery_failed")
    return MessageResponse(message="如果该邮箱已注册且尚未验证，我们已发送新的验证邮件")


@app.post("/auth/forgot-password", response_model=MessageResponse)
def forgot_password(payload: EmailRequest) -> MessageResponse:
    result = store.create_password_reset(payload.email)
    if result:
        user, token = result
        try:
            send_password_reset_email(user.email, user.display_name, token)
        except EmailDeliveryError:
            logger.exception("password_reset_email_delivery_failed")
    return MessageResponse(message="如果该邮箱已注册，我们已发送密码重置邮件")


@app.post("/auth/reset-password", response_model=MessageResponse)
def reset_password(payload: PasswordResetRequest) -> MessageResponse:
    validate_password_strength(payload.password)
    try:
        store.reset_password(payload.token, payload.password)
    except InvalidAuthTokenError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return MessageResponse(message="密码已更新，请重新登录")


@app.post("/auth/logout", response_model=MessageResponse)
def logout(
    _: Annotated[DemoUser, Depends(current_user)],
    response: Response,
    authorization: Annotated[str | None, Header()] = None,
    session_cookie: Annotated[str | None, Cookie(alias="offerpilot_session")] = None,
) -> MessageResponse:
    token = authorization.split(" ", 1)[1] if authorization and authorization.lower().startswith("bearer ") else session_cookie
    if token:
        store.logout(token)
    response.delete_cookie("offerpilot_session", path="/", secure=os.getenv("APP_ENV", "development") == "production", samesite="lax")
    return MessageResponse(message="已安全退出")


@app.get("/me", response_model=DemoUser)
def get_me(user: Annotated[DemoUser, Depends(current_user)]) -> DemoUser:
    return user


@app.get("/me/export")
def export_my_data(user: Annotated[DemoUser, Depends(current_user)]) -> dict[str, Any]:
    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "account": user.model_dump(mode="json"),
        "profile": profile.model_dump(mode="json") if (profile := store.get_profile(user.id)) else None,
        "recommendation_runs": [item.model_dump(mode="json") for item in store.list_runs(user.id)],
        "advisor_threads": [item.model_dump(mode="json") for item in store.list_threads(user.id)],
        "tasks": [item.model_dump(mode="json") for item in store.list_tasks(user.id)],
        "feedback": [item.model_dump(mode="json") for item in store.list_feedback(user.id)],
        "agent_audits": [item.model_dump(mode="json") for item in store.list_audits(user.id)],
    }


@app.delete("/me", response_model=MessageResponse)
def delete_my_account(
    payload: DeleteAccountRequest,
    user: Annotated[DemoUser, Depends(current_user)],
) -> MessageResponse:
    try:
        store.delete_account(user.id, payload.password)
    except InvalidCredentialsError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    return MessageResponse(message="账户和关联数据已删除")


@app.get("/universities", response_model=list[University])
def list_universities() -> list[University]:
    return UNIVERSITIES


@app.get("/catalog/facets", response_model=CatalogFacets)
def catalog_facets() -> CatalogFacets:
    return CatalogFacets(
        universities=[item.name for item in UNIVERSITIES],
        degree_levels=list(DEGREE_LEVELS),
        study_areas=list(STUDY_AREAS),
        coverage_cells=len(CATALOG_COVERAGE),
        verified_programs=sum(program.verification_status == "已核验" for program in PROGRAMS),
    )


@app.get("/catalog/coverage", response_model=list[CatalogCoverage])
def catalog_coverage(
    university: str | None = Query(default=None),
    degree_level: DegreeLevel | None = Query(default=None),
    field: StudyArea | None = Query(default=None),
) -> list[CatalogCoverage]:
    return [
        item for item in CATALOG_COVERAGE
        if (not university or item.university_slug == university or item.university == university)
        and (not degree_level or item.degree_level == degree_level)
        and (not field or item.field == field)
    ]


@app.get("/programs", response_model=list[Program])
def list_programs(
    university: str | None = Query(default=None),
    degree_level: DegreeLevel | None = Query(default=None),
    field: StudyArea | None = Query(default=None),
    q: str | None = Query(default=None, max_length=120),
) -> list[Program]:
    needle = q.casefold().strip() if q else None
    return [
        program for program in PROGRAMS
        if (not university or program.university == university)
        and (not degree_level or program.degree_level == degree_level)
        and (not field or program.field == field)
        and (not needle or needle in f"{program.university} {program.name} {program.field}".casefold())
    ]


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


@app.get("/me/tasks", response_model=list[ApplicationTask])
def list_my_tasks(user: Annotated[DemoUser, Depends(current_user)]) -> list[ApplicationTask]:
    return store.list_tasks(user.id)


@app.post("/me/tasks", response_model=ApplicationTask)
def create_my_task(payload: TaskCreateRequest, user: Annotated[DemoUser, Depends(current_user)]) -> ApplicationTask:
    now = datetime.now(UTC)
    task = ApplicationTask(id=f"task_{uuid4().hex[:10]}", created_at=now, updated_at=now, **payload.model_dump())
    return store.save_task(user.id, task)


@app.put("/me/tasks/{task_id}", response_model=ApplicationTask)
def update_my_task(
    task_id: str,
    payload: TaskUpdateRequest,
    user: Annotated[DemoUser, Depends(current_user)],
) -> ApplicationTask:
    task = store.get_task(user.id, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="申请任务不存在")
    task = task.model_copy(update={**payload.model_dump(exclude_unset=True), "updated_at": datetime.now(UTC)})
    return store.save_task(user.id, task)


@app.get("/me/feedback", response_model=list[FeedbackItem])
def list_my_feedback(user: Annotated[DemoUser, Depends(current_user)]) -> list[FeedbackItem]:
    return store.list_feedback(user.id)


@app.post("/me/feedback", response_model=FeedbackItem, status_code=201)
def create_feedback(
    payload: FeedbackCreateRequest,
    user: Annotated[DemoUser, Depends(current_user)],
) -> FeedbackItem:
    now = datetime.now(UTC)
    return store.save_feedback(FeedbackItem(
        id=f"feedback_{uuid4().hex[:12]}", user_id=user.id, user_email=user.email,
        created_at=now, updated_at=now, **payload.model_dump(),
    ))


@app.get("/admin/stats", response_model=AdminStats)
def admin_stats(_: Annotated[DemoUser, Depends(current_admin)]) -> AdminStats:
    counts = store.admin_counts()
    return AdminStats(
        **counts,
        verified_programs=sum(program.verification_status == "已核验" for program in PROGRAMS),
        catalog_coverage_cells=len(CATALOG_COVERAGE),
    )


@app.get("/admin/users", response_model=list[DemoUser])
def admin_users(_: Annotated[DemoUser, Depends(current_admin)]) -> list[DemoUser]:
    return store.list_users()


@app.put("/admin/users/{user_id}", response_model=DemoUser)
def admin_update_user(
    user_id: str,
    payload: AdminUserUpdateRequest,
    admin: Annotated[DemoUser, Depends(current_admin)],
) -> DemoUser:
    if user_id == admin.id and payload.status == "suspended":
        raise HTTPException(status_code=409, detail="不能停用当前管理员账户")
    user = store.update_user_status(user_id, payload.status)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@app.get("/admin/feedback", response_model=list[FeedbackItem])
def admin_feedback(_: Annotated[DemoUser, Depends(current_admin)]) -> list[FeedbackItem]:
    return store.list_feedback()


@app.put("/admin/feedback/{feedback_id}", response_model=FeedbackItem)
def admin_update_feedback(
    feedback_id: str,
    payload: FeedbackUpdateRequest,
    _: Annotated[DemoUser, Depends(current_admin)],
) -> FeedbackItem:
    item = store.get_feedback(feedback_id)
    if not item:
        raise HTTPException(status_code=404, detail="反馈不存在")
    return store.save_feedback(item.model_copy(update={"status": payload.status, "updated_at": datetime.now(UTC)}))


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
    now = datetime.now(UTC)
    categories = {"verify-transcript": "成绩单", "verify-language": "语言", "shortlist": "选校", "deadlines": "截止日期", "materials": "材料"}
    for item in build_action_plan(result).items:
        store.save_task(user.id, ApplicationTask(
            id=f"task_{result.run_id}_{item.id}", title=item.title, detail=item.detail,
            category=categories.get(item.id, "其他"), priority=item.priority, status=item.status,
            source_run_id=result.run_id, created_at=now, updated_at=now,
        ))
    return result


@app.get("/program-sources/status", response_model=list[ProgramSourceStatus])
def program_source_status() -> list[ProgramSourceStatus]:
    today = datetime.now(UTC).date()
    statuses = []
    for program in PROGRAMS:
        age = (today - datetime.fromisoformat(program.source.verified_at).date()).days
        needs_review = age > 30
        statuses.append(ProgramSourceStatus(
            source_id=program.source.id, program_slug=program.slug, title=program.source.title,
            url=program.source.url, verified_at=program.source.verified_at,
            status="需要复核" if needs_review else "已核验",
            reason=f"距上次人工核验已 {age} 天" if needs_review else "仍在 30 天复核周期内",
        ))
    return statuses


@app.get("/admin/program-sources", response_model=list[ProgramSourceStatus])
def admin_program_source_status(_: Annotated[DemoUser, Depends(current_admin)]) -> list[ProgramSourceStatus]:
    return program_source_status()


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


@app.get("/me/advisor/audits", response_model=list[AgentRunAudit])
def list_advisor_audits(user: Annotated[DemoUser, Depends(current_user)]) -> list[AgentRunAudit]:
    return store.list_audits(user.id)


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
        elif action.tool == "create_task":
            now = datetime.now(UTC)
            arguments = action.arguments
            try:
                request = TaskCreateRequest.model_validate({
                    "title": arguments.get("title", action.summary),
                    "detail": arguments.get("detail", "由 AI 申请顾问创建"),
                    "category": arguments.get("category", "其他"),
                    "priority": arguments.get("priority", "P1"),
                    "due_at": arguments.get("due_at"),
                    "reminder_at": arguments.get("reminder_at"),
                })
                store.save_task(user.id, ApplicationTask(
                    id=f"task_{uuid4().hex[:10]}", created_at=now, updated_at=now, **request.model_dump()
                ))
            except ValueError:
                action.status = "skipped"
                action.summary = "待办信息格式不完整，暂未创建"

    assistant_message = AdvisorMessage(
        id=f"msg_{uuid4().hex[:10]}", role="assistant", content=reply_text, created_at=datetime.now(UTC), actions=actions
    )
    thread.messages.extend([user_message, assistant_message])
    thread.updated_at = assistant_message.created_at
    store.save_thread(user.id, thread)
    store.save_audit(user.id, AgentRunAudit(
        id=f"audit_{uuid4().hex[:10]}", thread_id=thread.id, message_id=assistant_message.id,
        provider=metadata["provider"], model=metadata["model"], prompt_version="advisor-1.0.0",
        workflow_version=recommendation_run.workflow_version if recommendation_run else "advisor-tools-1.0.0",
        latency_ms=metadata["latency_ms"], input_tokens=metadata["input_tokens"],
        output_tokens=metadata["output_tokens"], tools=[action.tool for action in actions],
        created_at=assistant_message.created_at,
    ))
    return AdvisorReply(thread=thread, profile=profile, recommendation_run=recommendation_run, **metadata)
