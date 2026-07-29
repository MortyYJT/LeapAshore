import asyncio
from hashlib import sha256
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .data import UNIVERSITIES
from .catalog_data import CATALOG_COVERAGE
from .models import (
    ActionPlanResponse,
    ActionPlanItem,
    AgentRunAudit,
    AIConsent,
    AIConsentRequest,
    ApplicationChoice,
    ApplicationChoiceUpdate,
    ApplicationRoadmap,
    ApplicationTask,
    AdvisorAction,
    AdvisorMessage,
    AdvisorMessageRequest,
    AdvisorReply,
    AdvisorStreamState,
    AdvisorThread,
    AdvisorTurnRecord,
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
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    Program,
    ProgramSourceCandidateRequest,
    ProgramSourceReviewRequest,
    ProgramSourceRollbackRequest,
    ProgramSourceStatus,
    ProgramSourceVersion,
    RecommendationResponse,
    RecommendationRunSummary,
    TranscriptAnalysisRequest,
    TranscriptAnalysisResponse,
    TaskCreateRequest,
    TaskUpdateRequest,
    University,
    advisor_turn_status_rank,
)
from .mailer import EmailDeliveryError, send_password_reset_email, send_verification_email
from .middleware import OriginGuardMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware
from .observability import configure_error_reporting
from .program_data import PROGRAMS, replace_published_program
from .taxonomy import DEGREE_LEVELS, STUDY_AREAS, DegreeLevel, StudyArea
from .services.advisor import plan_turn
from .services.advisor import fallback_plan
from .services.deepseek_advisor import (
    DeepSeekStreamError,
    build_redacted_context,
    safe_tool_actions,
    stream_deepseek,
)
from .services.agent import run_recommendation_agent
from .services.model_provider import configured_model, configured_provider, llm_is_configured
from .services.knowledge_rag import grounded_fallback_answer, retrieve_official_knowledge
from .services.roadmap import build_roadmap, merge_tasks, task_templates
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
from .source_errors import (
    SourceVersionConflictError,
    SourceVersionNotFoundError,
    SourceVersionStateError,
)
from .source_governance import (
    current_program,
    initialize_source_registry,
    new_candidate,
    refresh_source_registry,
    validate_official_source,
)

configure_error_reporting()
logger = logging.getLogger("offerpilot.mail")
deepseek_slots = asyncio.Semaphore(4)
SOURCE_BACKED_PATHS = (
    "/programs",
    "/program-sources",
    "/catalog",
    "/recommendations",
    "/agent",
    "/me/recommendation-runs",
    "/me/knowledge",
    "/me/transcript",
    "/me/advisor",
)
initialize_source_registry(store)


def portfolio_for_run(user_id: str, result: AgentRecommendationResponse) -> list[ApplicationChoice]:
    persisted = {choice.program_slug: choice for choice in store.list_choices(user_id, result.run_id)}
    now = datetime.now(UTC)
    return [
        persisted.get(item.program.slug) or ApplicationChoice(
            run_id=result.run_id, program_slug=item.program.slug, updated_at=now,
        )
        for item in result.recommendations
    ]


def sync_roadmap(
    user_id: str,
    profile: ApplicantProfile,
    result: AgentRecommendationResponse,
    choices: list[ApplicationChoice] | None = None,
    generated_at: datetime | None = None,
) -> ApplicationRoadmap:
    roadmap = roadmap_for_run(user_id, profile, result, choices, generated_at)
    tasks = (
        [task for phase in roadmap.phases for task in phase.tasks]
        + [task for branch in roadmap.program_branches for task in branch.tasks]
    )
    for task in tasks:
        store.save_task(user_id, task)
    return roadmap


def roadmap_for_run(
    user_id: str,
    profile: ApplicantProfile,
    result: AgentRecommendationResponse,
    choices: list[ApplicationChoice] | None = None,
    generated_at: datetime | None = None,
) -> ApplicationRoadmap:
    """Build a roadmap view without mutating persistence from a GET request."""
    portfolio = choices if choices is not None else portfolio_for_run(user_id, result)
    templates = task_templates(profile, result, portfolio, generated_at)
    merged = merge_tasks(templates, store.list_tasks(user_id))
    return build_roadmap(profile, result, portfolio, merged, generated_at)


def load_stream_prerequisites(user_id: str, thread_id: str) -> tuple[AdvisorThread | None, ApplicantProfile | None, int]:
    thread = store.get_thread(user_id, thread_id)
    profile = store.get_profile(user_id)
    today = datetime.now(UTC).date()
    daily_calls = sum(audit.created_at.date() == today for audit in store.list_audits(user_id))
    return thread, profile, daily_calls


def advisor_turn_at_least(turn: AdvisorTurnRecord, status: str) -> bool:
    return advisor_turn_status_rank(turn.status) >= advisor_turn_status_rank(status)


def advisor_turn_effect_id(user_id: str, thread_id: str, request_id: str) -> str:
    raw = f"{user_id}\0{thread_id}\0{request_id}".encode()
    return sha256(raw).hexdigest()[:20]


def advisor_effect_entity_id(effect_id: str, kind: str, action_index: int | None = None) -> str:
    action = "" if action_index is None else f":{action_index}"
    suffix = sha256(f"{effect_id}:{kind}{action}".encode()).hexdigest()[:16]
    return f"{kind}_{suffix}"


def reserve_advisor_turn(
    user_id: str,
    thread_id: str,
    message: str,
    request_id: str,
    mode: str,
) -> tuple[AdvisorTurnRecord, str]:
    now = datetime.now(UTC)
    content_hash = sha256(message.encode()).hexdigest()
    candidate = AdvisorTurnRecord(
        request_id=request_id,
        thread_id=thread_id,
        mode=mode,
        content_hash=content_hash,
        created_at=now,
        updated_at=now,
    )
    turn = store.reserve_advisor_turn(user_id, candidate)
    if turn.thread_id != thread_id or turn.mode != mode or turn.content_hash != content_hash:
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key 已用于不同的顾问请求，请生成新 Key",
        )
    return turn, advisor_turn_effect_id(user_id, thread_id, request_id)


def latest_recommendation(user_id: str, preferred_run_id: str | None = None) -> AgentRecommendationResponse | None:
    if preferred_run_id:
        preferred = store.get_run(user_id, preferred_run_id)
        if preferred:
            return preferred
    run_summaries = store.list_runs(user_id)
    return store.get_run(user_id, run_summaries[0].run_id) if run_summaries else None


def plan_stream_actions(
    user_id: str,
    message: str,
    profile: ApplicantProfile,
) -> list[AdvisorAction]:
    return safe_tool_actions(
        message,
        profile,
        latest_recommendation(user_id),
        store.list_tasks(user_id),
    )


def prepare_stream_turn(
    user: DemoUser,
    thread: AdvisorThread,
    profile: ApplicantProfile,
    message: str,
    actions: list[AdvisorAction],
    *,
    apply_actions: bool,
    effect_id: str,
    occurred_at: datetime,
    preferred_run_id: str | None = None,
) -> tuple[
    ApplicantProfile,
    AgentRecommendationResponse | None,
    list[ApplicationChoice],
    ApplicationRoadmap | None,
    KnowledgeSearchResponse,
    dict[str, Any],
    AIConsent | None,
]:
    action_run = None
    if apply_actions:
        updated_profile, action_run = execute_advisor_actions(
            user.id,
            profile,
            actions,
            effect_id=effect_id,
            occurred_at=occurred_at,
        )
    else:
        updated_profile = store.get_profile(user.id) or profile
    latest_result = action_run or latest_recommendation(user.id, preferred_run_id)
    choices = portfolio_for_run(user.id, latest_result) if latest_result else []
    current_roadmap = (
        roadmap_for_run(user.id, updated_profile, latest_result, choices, occurred_at)
        if latest_result else None
    )
    knowledge = retrieve_official_knowledge(KnowledgeSearchRequest(
        query=message,
        target_degree_level=updated_profile.target_degree_level,
        target_field=updated_profile.target_field,
        program_slugs=[item.program.slug for item in latest_result.recommendations] if latest_result else [],
        top_k=4,
    ))
    history = [{"role": item.role, "content": item.content} for item in thread.messages]
    context = build_redacted_context(
        updated_profile, latest_result, choices, current_roadmap, history, message,
        [user.email, user.display_name, user.id, profile.undergraduate_school],
        knowledge.hits,
    )
    return (
        updated_profile,
        latest_result,
        choices,
        current_roadmap,
        knowledge,
        context,
        store.get_ai_consent(user.id),
    )


def execute_advisor_actions(
    user_id: str,
    profile: ApplicantProfile,
    actions: list[AdvisorAction],
    *,
    effect_id: str | None = None,
    occurred_at: datetime | None = None,
) -> tuple[ApplicantProfile, AgentRecommendationResponse | None]:
    """Execute only the server whitelist; model text never mutates product state directly."""
    recommendation_run = None
    action_time = occurred_at or datetime.now(UTC)
    for action_index, action in enumerate(actions):
        if action.tool == "update_profile" and action.arguments:
            try:
                profile = ApplicantProfile.model_validate({**profile.model_dump(), **action.arguments})
                store.save_profile(user_id, profile)
            except ValueError:
                action.status = "skipped"
                action.summary = "档案更新值未通过格式检查，已保留原数据"
        elif action.tool == "run_recommendation":
            run_id = (
                advisor_effect_entity_id(effect_id, "run_adv", action_index)
                if effect_id else None
            )
            recommendation_run = run_recommendation_agent(profile, run_id=run_id)
            store.save_run(user_id, profile, recommendation_run)
            sync_roadmap(user_id, profile, recommendation_run, generated_at=action_time)
        elif action.tool == "create_task":
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
                task_id = (
                    advisor_effect_entity_id(effect_id, "task_adv", action_index)
                    if effect_id else f"task_{uuid4().hex[:10]}"
                )
                store.save_task(user_id, ApplicationTask(
                    id=task_id,
                    created_at=action_time,
                    updated_at=action_time,
                    **request.model_dump(),
                ))
            except ValueError:
                action.status = "skipped"
                action.summary = "待办信息格式不完整，暂未创建"
        elif action.tool == "set_application_choice":
            arguments = action.arguments
            result = store.get_run(user_id, str(arguments.get("run_id", "")))
            slug = str(arguments.get("program_slug", ""))
            if not result or slug not in {item.program.slug for item in result.recommendations}:
                action.status = "skipped"
                action.summary = "项目不在当前选校方案中，未修改申请组合"
                continue
            is_primary = bool(arguments.get("is_primary"))
            status = str(arguments.get("status", "considering"))
            if status not in {"considering", "applying", "excluded"}:
                action.status = "skipped"
                continue
            if is_primary:
                status = "applying"
            existing = store.get_choice(user_id, result.run_id, slug)
            store.save_choice(user_id, ApplicationChoice(
                run_id=result.run_id,
                program_slug=slug,
                status=status,
                is_primary=is_primary and status == "applying",
                official_deadline=existing.official_deadline if existing else None,
                deadline_source_url=existing.deadline_source_url if existing else None,
                updated_at=action_time,
            ))
            sync_roadmap(user_id, profile, result, generated_at=action_time)
        elif action.tool == "update_task":
            task = store.get_task(user_id, str(action.arguments.get("task_id", "")))
            status = action.arguments.get("status")
            if not task or status not in {"待开始", "进行中", "已完成"}:
                action.status = "skipped"
                action.summary = "没有找到可修改的路线图任务"
                continue
            store.save_task(user_id, task.model_copy(update={"status": status, "updated_at": action_time}))
    return profile, recommendation_run


def advisor_stream_state(
    user_id: str,
    thread: AdvisorThread,
    preferred_run_id: str | None = None,
    generated_at: datetime | None = None,
) -> AdvisorStreamState:
    profile = store.get_profile(user_id)
    if not profile:
        raise RuntimeError("顾问回合完成时申请背景丢失")
    latest_result = latest_recommendation(user_id, preferred_run_id)
    choices = portfolio_for_run(user_id, latest_result) if latest_result else []
    roadmap = (
        roadmap_for_run(user_id, profile, latest_result, choices, generated_at)
        if latest_result else None
    )
    return AdvisorStreamState(
        thread=thread,
        profile=profile,
        recommendation_run=latest_result,
        portfolio=choices,
        roadmap=roadmap,
    )


def commit_advisor_turn(
    user_id: str,
    thread: AdvisorThread,
    message: str,
    turn: AdvisorTurnRecord,
    effect_id: str,
) -> tuple[AdvisorThread, AdvisorTurnRecord]:
    if not turn.reply_text or not turn.provider or not turn.model or not turn.reply_ready_at:
        raise RuntimeError("顾问回合尚未生成可持久化回复")
    user_message_id = advisor_effect_entity_id(effect_id, "msg_user")
    assistant_message_id = advisor_effect_entity_id(effect_id, "msg_assistant")
    audit_id = advisor_effect_entity_id(effect_id, "audit_adv")
    committed_thread = thread.model_copy(deep=True)
    if not any(item.id == assistant_message_id for item in committed_thread.messages):
        committed_thread.messages = [
            item for item in committed_thread.messages
            if item.id not in {user_message_id, assistant_message_id}
        ]
        committed_thread.messages.extend([
            AdvisorMessage(
                id=user_message_id,
                role="user",
                content=message,
                created_at=turn.created_at,
            ),
            AdvisorMessage(
                id=assistant_message_id,
                role="assistant",
                content=turn.reply_text,
                actions=turn.actions,
                created_at=turn.reply_ready_at,
            ),
        ])
        committed_thread.updated_at = turn.reply_ready_at
    store.save_thread(user_id, committed_thread)
    store.save_audit(user_id, AgentRunAudit(
        id=audit_id,
        thread_id=committed_thread.id,
        message_id=assistant_message_id,
        provider=turn.provider,
        model=turn.model,
        prompt_version=turn.prompt_version or "advisor-2.0.0-redacted",
        workflow_version=turn.workflow_version or "advisor-tools-2.0.0",
        latency_ms=turn.latency_ms or 0,
        input_tokens=turn.input_tokens,
        output_tokens=turn.output_tokens,
        tools=turn.tools,
        created_at=turn.reply_ready_at,
    ))
    completed_at = datetime.now(UTC)
    completed_turn = store.save_advisor_turn(user_id, turn.model_copy(update={
        "status": "completed",
        "updated_at": completed_at,
        "completed_at": completed_at,
    }))
    return committed_thread, completed_turn


def sse_event(event: str, payload: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


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
app.add_middleware(OriginGuardMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


@app.middleware("http")
async def refresh_published_programs(request: Request, call_next):
    if request.url.path.startswith(SOURCE_BACKED_PATHS):
        await asyncio.to_thread(refresh_source_registry, store)
    return await call_next(request)


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
        api="ollama-chat" if provider == "ollama" else "chat-completions" if provider == "deepseek" else "responses",
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
        debug_token=token if os.getenv("EXPOSE_DEBUG_TOKENS", "false").lower() in {"1", "true", "yes", "on"} else None,
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
        "application_choices": [item.model_dump(mode="json") for item in store.list_choices(user.id)],
        "ai_advisor_consent": store.get_ai_consent(user.id).model_dump(mode="json") if store.get_ai_consent(user.id) else None,
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
    updates = payload.model_dump(exclude_unset=True)
    if "due_at" in updates:
        updates["schedule_origin"] = "user"
    task = task.model_copy(update={**updates, "updated_at": datetime.now(UTC)})
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
        **counts, **store.admin_model_metrics(),
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
    sync_roadmap(user.id, profile, result, [])
    return result


@app.get("/program-sources/status", response_model=list[ProgramSourceStatus])
def program_source_status() -> list[ProgramSourceStatus]:
    today = datetime.now(UTC).date()
    statuses = []
    all_versions = store.list_program_source_versions()
    by_program = {
        program.slug: [item for item in all_versions if item.program_slug == program.slug]
        for program in PROGRAMS
    }
    for program_slug, versions in by_program.items():
        published = next((item for item in versions if item.status == "published"), None)
        if not published:
            raise HTTPException(status_code=503, detail=f"项目 {program_slug} 缺少发布来源版本")
        program = published.program
        age = (today - datetime.fromisoformat(program.source.verified_at).date()).days
        needs_review = age > 30
        statuses.append(ProgramSourceStatus(
            source_id=program.source.id, program_slug=program.slug, title=program.source.title,
            url=program.source.url, verified_at=program.source.verified_at,
            published_version_id=published.version_id, content_hash=published.content_hash,
            pending_versions=sum(item.status == "pending_review" for item in versions),
            status="需要复核" if needs_review else "已核验",
            reason=f"距上次人工核验已 {age} 天" if needs_review else "仍在 30 天复核周期内",
        ))
    return statuses


@app.post("/me/knowledge/search", response_model=KnowledgeSearchResponse)
def search_official_knowledge(
    payload: KnowledgeSearchRequest,
    user: Annotated[DemoUser, Depends(current_user)],
) -> KnowledgeSearchResponse:
    profile = store.get_profile(user.id)
    if profile:
        payload = payload.model_copy(update={
            "target_degree_level": payload.target_degree_level or profile.target_degree_level,
            "target_field": payload.target_field or profile.target_field,
        })
    return retrieve_official_knowledge(payload)


@app.get("/admin/program-sources", response_model=list[ProgramSourceStatus])
def admin_program_source_status(_: Annotated[DemoUser, Depends(current_admin)]) -> list[ProgramSourceStatus]:
    return program_source_status()


def _published_source_version(program_slug: str) -> ProgramSourceVersion:
    published = next((
        item for item in store.list_program_source_versions(program_slug)
        if item.status == "published"
    ), None)
    if not published:
        raise HTTPException(status_code=404, detail="项目或发布来源版本不存在")
    return published


@app.get(
    "/admin/program-sources/{program_slug}/versions",
    response_model=list[ProgramSourceVersion],
)
def admin_program_source_versions(
    program_slug: str,
    _: Annotated[DemoUser, Depends(current_admin)],
) -> list[ProgramSourceVersion]:
    if not current_program(program_slug):
        raise HTTPException(status_code=404, detail="项目不存在")
    return store.list_program_source_versions(program_slug)


@app.post(
    "/admin/program-sources/{program_slug}/versions",
    response_model=ProgramSourceVersion,
    status_code=201,
)
def admin_create_program_source_version(
    program_slug: str,
    payload: ProgramSourceCandidateRequest,
    admin: Annotated[DemoUser, Depends(current_admin)],
) -> ProgramSourceVersion:
    if payload.program.slug != program_slug or not current_program(program_slug):
        raise HTTPException(status_code=422, detail="候选版本的项目标识与路径不一致")
    published = _published_source_version(program_slug)
    if payload.base_hash != published.content_hash:
        raise HTTPException(status_code=409, detail="当前发布版本已变化，请基于最新 hash 重新生成差异")
    try:
        candidate = new_candidate(
            current=published,
            proposed=payload.program,
            submitted_by=admin.id,
        )
        return store.save_program_source_version(candidate)
    except ValueError as error:
        status_code = 409 if "完全一致" in str(error) else 422
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    except SourceVersionStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.put(
    "/admin/program-sources/{program_slug}/versions/{version_id}",
    response_model=ProgramSourceVersion,
)
def admin_review_program_source_version(
    program_slug: str,
    version_id: str,
    payload: ProgramSourceReviewRequest,
    admin: Annotated[DemoUser, Depends(current_admin)],
) -> ProgramSourceVersion:
    candidate = store.get_program_source_version(version_id)
    if not candidate or candidate.program_slug != program_slug:
        raise HTTPException(status_code=404, detail="来源版本不存在")
    if payload.decision == "approve":
        try:
            validate_official_source(candidate.program)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        reviewed = store.review_program_source_version(
            version_id,
            payload.decision,
            admin.id,
            datetime.now(UTC),
            payload.note,
        )
    except SourceVersionNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (SourceVersionConflictError, SourceVersionStateError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if reviewed.status == "published":
        replace_published_program(reviewed.program)
    return reviewed


@app.post(
    "/admin/program-sources/{program_slug}/rollback",
    response_model=ProgramSourceVersion,
    status_code=201,
)
def admin_rollback_program_source_version(
    program_slug: str,
    payload: ProgramSourceRollbackRequest,
    admin: Annotated[DemoUser, Depends(current_admin)],
) -> ProgramSourceVersion:
    target = store.get_program_source_version(payload.target_version_id)
    if not target or target.program_slug != program_slug:
        raise HTTPException(status_code=404, detail="回滚目标版本不存在")
    if target.status != "superseded":
        raise HTTPException(status_code=409, detail="只能回滚到曾经发布且已被替代的历史版本")
    published = _published_source_version(program_slug)
    if target.content_hash == published.content_hash:
        raise HTTPException(status_code=409, detail="目标版本内容已经是当前发布内容")
    try:
        rollback = new_candidate(
            current=published,
            proposed=target.program,
            submitted_by=admin.id,
            rollback_of=target.version_id,
        )
        store.save_program_source_version(rollback)
        reviewed = store.review_program_source_version(
            rollback.version_id,
            "approve",
            admin.id,
            datetime.now(UTC),
            payload.note or f"回滚到历史版本 {target.version_id}",
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SourceVersionNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (SourceVersionConflictError, SourceVersionStateError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    replace_published_program(reviewed.program)
    return reviewed


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
    profile = store.get_profile(user.id)
    if not profile:
        raise HTTPException(status_code=409, detail="请先保存申请背景")
    roadmap = roadmap_for_run(user.id, profile, result)
    return ActionPlanResponse(
        run_id=run_id,
        items=[
            ActionPlanItem.model_validate(task.model_dump())
            for task in (
                [item for phase in roadmap.phases for item in phase.tasks]
                + [item for branch in roadmap.program_branches for item in branch.tasks]
            )
        ],
    )


@app.get("/me/recommendation-runs/{run_id}/portfolio", response_model=list[ApplicationChoice])
def get_portfolio(run_id: str, user: Annotated[DemoUser, Depends(current_user)]) -> list[ApplicationChoice]:
    result = store.get_run(user.id, run_id)
    if not result:
        raise HTTPException(status_code=404, detail="推荐记录不存在")
    return portfolio_for_run(user.id, result)


@app.put("/me/recommendation-runs/{run_id}/portfolio/{program_slug}", response_model=ApplicationChoice)
def update_portfolio_choice(
    run_id: str,
    program_slug: str,
    payload: ApplicationChoiceUpdate,
    user: Annotated[DemoUser, Depends(current_user)],
) -> ApplicationChoice:
    result = store.get_run(user.id, run_id)
    if not result:
        raise HTTPException(status_code=404, detail="推荐记录不存在")
    if program_slug not in {item.program.slug for item in result.recommendations}:
        raise HTTPException(status_code=404, detail="该项目不在当前选校方案中")
    if payload.deadline_source_url and not payload.deadline_source_url.startswith(("https://", "http://")):
        raise HTTPException(status_code=422, detail="截止日期来源必须是有效网页地址")
    status = "applying" if payload.is_primary else payload.status
    now = datetime.now(UTC)
    choice = ApplicationChoice(
        run_id=run_id, program_slug=program_slug, status=status,
        is_primary=payload.is_primary and status == "applying",
        official_deadline=payload.official_deadline,
        deadline_source_url=payload.deadline_source_url,
        updated_at=now,
    )
    store.save_choice(user.id, choice)
    profile = store.get_profile(user.id)
    if profile:
        sync_roadmap(user.id, profile, result)
    return choice


@app.get("/me/recommendation-runs/{run_id}/roadmap", response_model=ApplicationRoadmap)
def get_roadmap(run_id: str, user: Annotated[DemoUser, Depends(current_user)]) -> ApplicationRoadmap:
    result = store.get_run(user.id, run_id)
    if not result:
        raise HTTPException(status_code=404, detail="推荐记录不存在")
    profile = store.get_profile(user.id)
    if not profile:
        raise HTTPException(status_code=409, detail="请先保存申请背景")
    return roadmap_for_run(user.id, profile, result)


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


@app.get("/me/advisor/consent", response_model=AIConsent | None)
def get_advisor_consent(user: Annotated[DemoUser, Depends(current_user)]) -> AIConsent | None:
    return store.get_ai_consent(user.id)


@app.post("/me/advisor/consent", response_model=AIConsent)
def save_advisor_consent(
    payload: AIConsentRequest,
    user: Annotated[DemoUser, Depends(current_user)],
) -> AIConsent:
    return store.save_ai_consent(user.id, AIConsent(accepted=payload.accepted, updated_at=datetime.now(UTC)))


@app.post("/me/advisor/threads/{thread_id}/messages", response_model=AdvisorReply)
def send_advisor_message(
    thread_id: str,
    payload: AdvisorMessageRequest,
    user: Annotated[DemoUser, Depends(current_user)],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=128,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ],
) -> AdvisorReply:
    thread = store.get_thread(user.id, thread_id)
    profile = store.get_profile(user.id)
    if not thread:
        raise HTTPException(status_code=404, detail="顾问会话不存在")
    if not profile:
        raise HTTPException(status_code=409, detail="请先保存申请背景")

    turn, effect_id = reserve_advisor_turn(
        user.id,
        thread_id,
        payload.content,
        idempotency_key,
        "sync",
    )
    if turn.status == "completed":
        recommendation_run = (
            store.get_run(user.id, turn.recommendation_run_id)
            if turn.recommendation_run_id else None
        )
        return AdvisorReply(
            thread=thread,
            profile=profile,
            recommendation_run=recommendation_run,
            provider=turn.provider or "deterministic-fallback",
            model=turn.model or configured_model(),
            latency_ms=turn.latency_ms or 0,
            input_tokens=turn.input_tokens,
            output_tokens=turn.output_tokens,
            prompt_version=turn.prompt_version or "advisor-1.0.0",
        )

    if turn.status == "reserved":
        history = [{"role": item.role, "content": item.content} for item in thread.messages]
        reply_text, planned_actions, metadata = plan_turn(payload.content, profile, history)
        turn = store.save_advisor_turn(user.id, turn.model_copy(update={
            "status": "planned",
            "actions": planned_actions,
            "reply_text": reply_text,
            "provider": metadata["provider"],
            "model": metadata["model"],
            "latency_ms": metadata["latency_ms"],
            "input_tokens": metadata["input_tokens"],
            "output_tokens": metadata["output_tokens"],
            "prompt_version": "advisor-1.0.0",
            "updated_at": datetime.now(UTC),
        }))

    actions = [action.model_copy(deep=True) for action in turn.actions]
    recommendation_run = (
        store.get_run(user.id, turn.recommendation_run_id)
        if turn.recommendation_run_id else None
    )
    if not advisor_turn_at_least(turn, "actions_applied"):
        profile, recommendation_run = execute_advisor_actions(
            user.id,
            profile,
            actions,
            effect_id=effect_id,
            occurred_at=turn.created_at,
        )
        turn = store.save_advisor_turn(user.id, turn.model_copy(update={
            "status": "actions_applied",
            "actions": actions,
            "recommendation_run_id": recommendation_run.run_id if recommendation_run else None,
            "updated_at": datetime.now(UTC),
        }))
    else:
        profile = store.get_profile(user.id) or profile

    if not advisor_turn_at_least(turn, "reply_ready"):
        ready_at = datetime.now(UTC)
        turn = store.save_advisor_turn(user.id, turn.model_copy(update={
            "status": "reply_ready",
            "workflow_version": (
                recommendation_run.workflow_version
                if recommendation_run else "advisor-tools-1.0.0"
            ),
            "tools": [action.tool for action in turn.actions],
            "reply_ready_at": ready_at,
            "updated_at": ready_at,
        }))

    committed_thread, turn = commit_advisor_turn(
        user.id,
        thread,
        payload.content,
        turn,
        effect_id,
    )
    return AdvisorReply(
        thread=committed_thread,
        profile=store.get_profile(user.id) or profile,
        recommendation_run=(
            store.get_run(user.id, turn.recommendation_run_id)
            if turn.recommendation_run_id else None
        ),
        provider=turn.provider or "deterministic-fallback",
        model=turn.model or configured_model(),
        latency_ms=turn.latency_ms or 0,
        input_tokens=turn.input_tokens,
        output_tokens=turn.output_tokens,
        prompt_version=turn.prompt_version or "advisor-1.0.0",
    )


@app.post("/me/advisor/threads/{thread_id}/messages/stream")
async def stream_advisor_message(
    thread_id: str,
    payload: AdvisorMessageRequest,
    user: Annotated[DemoUser, Depends(current_user)],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=128,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ],
) -> StreamingResponse:
    thread, profile, daily_calls = await asyncio.to_thread(load_stream_prerequisites, user.id, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="顾问会话不存在")
    if not profile:
        raise HTTPException(status_code=409, detail="请先保存申请背景")

    turn, effect_id = await asyncio.to_thread(
        reserve_advisor_turn,
        user.id,
        thread_id,
        payload.content,
        idempotency_key,
        "stream",
    )
    if turn.status != "completed" and daily_calls >= int(os.getenv("ADVISOR_DAILY_LIMIT", "30")):
        raise HTTPException(status_code=429, detail="今日 AI 顾问请求次数已用完，请明天继续")

    async def events():
        nonlocal turn
        if turn.status == "completed":
            assistant_message_id = advisor_effect_entity_id(effect_id, "msg_assistant")
            assistant_message = next(
                (item for item in thread.messages if item.id == assistant_message_id),
                None,
            )
            if not assistant_message:
                raise RuntimeError("幂等顾问回合已完成，但会话消息不存在")
            yield sse_event("status", {
                "message": "该请求已完成，正在恢复保存结果",
                "provider": turn.provider or "deterministic-fallback",
            })
            yield sse_event("actions", [
                action.model_dump(mode="json") for action in assistant_message.actions
            ])
            yield sse_event("delta", {"content": assistant_message.content})
            state = await asyncio.to_thread(
                advisor_stream_state,
                user.id,
                thread,
                turn.recommendation_run_id,
                turn.created_at,
            )
            yield sse_event("state", state.model_dump(mode="json"))
            yield sse_event("done", {
                "provider": turn.provider or "deterministic-fallback",
                "model": turn.model or configured_model(),
                "latency_ms": turn.latency_ms or 0,
                "input_tokens": turn.input_tokens,
                "output_tokens": turn.output_tokens,
                "replayed": True,
            })
            return

        started = asyncio.get_running_loop().time()
        yield sse_event("status", {"message": "正在读取你的申请组合与路线图", "provider": "deepseek"})
        if turn.status == "reserved":
            planned_actions = await asyncio.to_thread(
                plan_stream_actions,
                user.id,
                payload.content,
                profile,
            )
            turn = await asyncio.to_thread(
                store.save_advisor_turn,
                user.id,
                turn.model_copy(update={
                    "status": "planned",
                    "actions": planned_actions,
                    "updated_at": datetime.now(UTC),
                }),
            )
        actions = [action.model_copy(deep=True) for action in turn.actions]
        apply_actions = not advisor_turn_at_least(turn, "actions_applied")
        (
            updated_profile,
            latest_result,
            choices,
            current_roadmap,
            knowledge,
            context,
            consent,
        ) = await asyncio.to_thread(
            prepare_stream_turn,
            user,
            thread,
            profile,
            payload.content,
            actions,
            apply_actions=apply_actions,
            effect_id=effect_id,
            occurred_at=turn.created_at,
            preferred_run_id=turn.recommendation_run_id,
        )
        if apply_actions:
            turn = await asyncio.to_thread(
                store.save_advisor_turn,
                user.id,
                turn.model_copy(update={
                    "status": "actions_applied",
                    "actions": actions,
                    "recommendation_run_id": latest_result.run_id if latest_result else None,
                    "updated_at": datetime.now(UTC),
                }),
            )
        yield sse_event("actions", [action.model_dump(mode="json") for action in actions])

        yield sse_event("status", {
            "message": f"已检索 {len(knowledge.hits)} 条可引用的官方项目证据" if knowledge.hits else "当前问题没有命中已核验项目证据",
            "provider": "official-knowledge-rag",
        })

        if advisor_turn_at_least(turn, "reply_ready"):
            assistant_text = turn.reply_text or ""
            provider = turn.provider or "deterministic-fallback"
            model = turn.model or configured_model()
            input_tokens = turn.input_tokens
            output_tokens = turn.output_tokens
            latency_ms = turn.latency_ms or 0
            yield sse_event("status", {
                "message": "动作已保存，正在恢复同一请求的回答",
                "provider": provider,
            })
            yield sse_event("delta", {"content": assistant_text})
        else:
            cloud_allowed = bool(consent and consent.accepted and configured_provider() == "deepseek")
            provider = "deepseek" if cloud_allowed else "deterministic-fallback"
            model = configured_model()
            input_tokens = None
            output_tokens = None
            reply_parts: list[str] = []

            if cloud_allowed:
                try:
                    async with asyncio.timeout(25):
                        async with deepseek_slots:
                            iterator = stream_deepseek(context).__aiter__()
                            first_delta = False
                            while not first_delta:
                                kind, value = await asyncio.wait_for(anext(iterator), timeout=8)
                                if kind == "usage":
                                    input_tokens = value.get("prompt_tokens")
                                    output_tokens = value.get("completion_tokens")
                                elif kind == "delta":
                                    first_delta = True
                                    reply_parts.append(str(value))
                                    yield sse_event("delta", {"content": value})
                            async for kind, value in iterator:
                                if kind == "usage":
                                    input_tokens = value.get("prompt_tokens")
                                    output_tokens = value.get("completion_tokens")
                                elif kind == "delta":
                                    reply_parts.append(str(value))
                                    yield sse_event("delta", {"content": value})
                    if not reply_parts:
                        raise DeepSeekStreamError("DeepSeek 返回了空内容")
                except (DeepSeekStreamError, TimeoutError, StopAsyncIteration, asyncio.TimeoutError):
                    provider = "deterministic-fallback"
                    yield sse_event("error", {"message": "DeepSeek 暂时不可用、限流或余额不足，已切换到规则顾问", "fallback": True})
            else:
                reason = "你尚未同意云端 AI 数据处理，当前使用规则顾问" if not consent or not consent.accepted else "DeepSeek 尚未配置，当前使用规则顾问"
                yield sse_event("status", {"message": reason, "provider": "deterministic-fallback"})

            if provider == "deterministic-fallback":
                fallback = grounded_fallback_answer(payload.content, knowledge.hits) or fallback_plan(payload.content, updated_profile)["reply"]
                reply_parts = [fallback]
                yield sse_event("delta", {"content": fallback})

            assistant_text = "".join(reply_parts)
            latency_ms = round((asyncio.get_running_loop().time() - started) * 1000)
            ready_at = datetime.now(UTC)
            turn = await asyncio.to_thread(
                store.save_advisor_turn,
                user.id,
                turn.model_copy(update={
                    "status": "reply_ready",
                    "actions": actions,
                    "reply_text": assistant_text,
                    "provider": provider,
                    "model": model,
                    "latency_ms": latency_ms,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "prompt_version": "advisor-2.0.0-redacted",
                    "workflow_version": (
                        latest_result.workflow_version
                        if latest_result else "advisor-tools-2.0.0"
                    ),
                    "tools": (
                        (["retrieve_official_knowledge"] if knowledge.hits else [])
                        + [action.tool for action in actions]
                    ),
                    "reply_ready_at": ready_at,
                    "updated_at": ready_at,
                }),
            )

        committed_thread, turn = await asyncio.to_thread(
            commit_advisor_turn,
            user.id,
            thread,
            payload.content,
            turn,
            effect_id,
        )
        state = AdvisorStreamState(
            thread=committed_thread,
            profile=updated_profile,
            recommendation_run=latest_result,
            portfolio=choices,
            roadmap=current_roadmap,
        )
        yield sse_event("state", state.model_dump(mode="json"))
        yield sse_event("done", {
            "provider": provider, "model": model, "latency_ms": latency_ms,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
        })

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
