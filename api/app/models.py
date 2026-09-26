from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field

from .taxonomy import DegreeLevel, EducationLevel, StudyArea


class ApplicantProfile(BaseModel):
    current_education_level: EducationLevel = "本科"
    undergraduate_school: str = Field(min_length=1, max_length=120)
    school_tier: Literal["高中/国际课程", "985", "211/双一流", "双非", "海外重点", "其他"]
    undergraduate_major: str = Field(min_length=1, max_length=120)
    gpa: float = Field(gt=0)
    gpa_scale: float = Field(gt=0)
    target_degree_level: DegreeLevel = "授课型硕士"
    target_field: StudyArea
    intake: str = "2027 S1"
    english_score: str | None = None
    coursework_summary: str | None = None
    experience_summary: str | None = None
    career_goal: str | None = None
    location_preferences: str | None = None
    annual_budget_cny: float | None = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("annual_budget_cny", "annual_budget_aud"),
    )


class University(BaseModel):
    slug: str
    name: str
    city: str
    fields: list[str]
    threshold: int
    official_url: str
    note: str


class SourceCitation(BaseModel):
    id: str
    title: str
    url: str
    excerpt: str
    verified_at: str = "2026-07-14"
    version_id: str | None = None
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class Program(BaseModel):
    slug: str
    university: str
    name: str
    city: str
    degree_level: DegreeLevel = "授课型硕士"
    field: StudyArea
    minimum_mark: float | None = None
    non_211_minimum_mark: float | None = None
    requires_cognate: bool = False
    prerequisites: list[str] = []
    english_requirement: str
    duration: str
    requires_supervisor: bool = False
    research_proposal_required: bool = False
    verification_status: Literal["已核验", "待复核"] = "已核验"
    source: SourceCitation


class CatalogCoverage(BaseModel):
    university_slug: str
    university: str
    city: str
    degree_level: DegreeLevel
    field: StudyArea
    catalog_url: str
    source_title: str
    status: Literal["目录已接入，待课程级核验"] = "目录已接入，待课程级核验"


class CatalogFacets(BaseModel):
    universities: list[str]
    degree_levels: list[DegreeLevel]
    study_areas: list[StudyArea]
    coverage_cells: int
    verified_programs: int


class ToolTrace(BaseModel):
    step: int
    tool: str
    status: Literal["completed", "needs_input", "failed", "skipped"]
    summary: str
    evidence_ids: list[str] = []


class ProgramRecommendation(BaseModel):
    program: Program
    tier: Literal["冲刺", "匹配", "稳妥", "暂不推荐"]
    eligibility: Literal["满足基础门槛", "需要人工核验", "存在门槛缺口"]
    match_score: int
    reasons: list[str]
    risks: list[str]
    next_action: str
    citations: list[SourceCitation]


class AgentRecommendationResponse(BaseModel):
    run_id: str
    workflow_version: str
    agent_mode: Literal["deterministic-demo", "llm-assisted"] = "deterministic-demo"
    profile_snapshot: ApplicantProfile | None = None
    summary: str
    missing_information: list[str]
    tool_trace: list[ToolTrace]
    catalog_options: list[CatalogCoverage] = Field(default_factory=list)
    recommendations: list[ProgramRecommendation]


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=8, max_length=128)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    accepted_terms: bool


class EmailTokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class EmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=160)


class PasswordResetRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    password: str = Field(min_length=8, max_length=128)


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=8, max_length=128)
    confirmation: Literal["DELETE"]


class DemoUser(BaseModel):
    id: str
    email: str
    display_name: str
    role: Literal["user", "admin"] = "user"
    email_verified: bool = False
    status: Literal["active", "suspended"] = "active"
    created_at: datetime | None = None
    last_login_at: datetime | None = None
    terms_accepted_at: datetime | None = None
    terms_version: str | None = None


class AuthResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: DemoUser


class RegistrationResponse(BaseModel):
    message: str
    user: DemoUser
    delivery: Literal["smtp", "console", "disabled"]
    debug_token: str | None = None


class MessageResponse(BaseModel):
    message: str


class FeedbackCreateRequest(BaseModel):
    category: Literal["问题", "建议", "数据错误", "其他"]
    message: str = Field(min_length=3, max_length=4000)
    page: str | None = Field(default=None, max_length=200)


class FeedbackItem(BaseModel):
    id: str
    user_id: str
    user_email: str
    category: Literal["问题", "建议", "数据错误", "其他"]
    message: str
    page: str | None = None
    status: Literal["new", "reviewing", "resolved"] = "new"
    created_at: datetime
    updated_at: datetime


class FeedbackUpdateRequest(BaseModel):
    status: Literal["new", "reviewing", "resolved"]


class KnowledgeGapCandidate(BaseModel):
    id: str
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    program_slug: str | None = None
    topic_class: Literal["academic", "prerequisite", "language", "tuition", "deadline", "policy", "general"]
    occurrence_count: int = Field(default=1, ge=1)
    status: Literal["new", "reviewing", "source_pending", "published", "eval_failed", "resolved", "rejected"] = "new"
    source_version_id: str | None = None
    eval_dataset_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    eval_passed: bool | None = None
    review_note: str | None = Field(default=None, max_length=1000)
    revision: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime


class KnowledgeGapUpdateRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    action: Literal["start_review", "attach_source", "reject"]
    source_version_id: str | None = Field(default=None, min_length=1, max_length=160)
    review_note: str | None = Field(default=None, max_length=1000)


class AdminStats(BaseModel):
    users: int
    verified_users: int
    active_sessions: int
    recommendation_runs: int
    advisor_threads: int
    open_feedback: int
    verified_programs: int
    catalog_coverage_cells: int
    llm_calls_today: int = 0
    llm_average_latency_ms: int = 0
    llm_fallback_rate: float = 0
    llm_input_tokens_today: int = 0
    llm_output_tokens_today: int = 0


class AdminUserUpdateRequest(BaseModel):
    status: Literal["active", "suspended"]


class RecommendationRunSummary(BaseModel):
    run_id: str
    created_at: datetime
    workflow_version: str
    target_field: str
    intake: str
    recommendation_count: int
    summary: str


class ActionPlanItem(BaseModel):
    id: str
    title: str
    detail: str
    priority: Literal["P0", "P1", "P2"]
    status: Literal["待开始", "进行中", "已完成"] = "待开始"


class ActionPlanResponse(BaseModel):
    run_id: str
    items: list[ActionPlanItem]


class ApplicationChoice(BaseModel):
    run_id: str
    program_slug: str
    status: Literal["considering", "applying", "excluded"] = "considering"
    is_primary: bool = False
    official_deadline: datetime | None = None
    deadline_source_url: str | None = Field(default=None, max_length=500)
    updated_at: datetime


class ApplicationChoiceUpdate(BaseModel):
    status: Literal["considering", "applying", "excluded"]
    is_primary: bool = False
    official_deadline: datetime | None = None
    deadline_source_url: str | None = Field(default=None, max_length=500)


class Recommendation(BaseModel):
    university: University
    tier: Literal["冲刺", "匹配", "稳妥"]
    match_score: int
    reasons: list[str]
    risks: list[str]
    next_action: str


class RecommendationResponse(BaseModel):
    algorithm_version: str
    disclaimer: str
    recommendations: list[Recommendation]


class AdvisorAction(BaseModel):
    tool: Literal["update_profile", "run_recommendation", "create_task", "set_application_choice", "update_task", "answer"]
    summary: str
    arguments: dict[str, Any] = {}
    status: Literal["completed", "needs_confirmation", "skipped"] = "completed"


class AdvisorMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    actions: list[AdvisorAction] = []


class AdvisorThread(BaseModel):
    id: str
    revision: int = Field(default=0, ge=0)
    title: str
    messages: list[AdvisorMessage]
    created_at: datetime
    updated_at: datetime


class AdvisorMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class AdvisorTurnRecord(BaseModel):
    """Durable checkpoint for one idempotent advisor request."""

    request_id: str = Field(min_length=8, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    mode: Literal["sync", "stream"]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["reserved", "planned", "actions_applied", "reply_ready", "completed"] = "reserved"
    actions: list[AdvisorAction] = Field(default_factory=list)
    reply_text: str | None = None
    provider: Literal["openai", "ollama", "deepseek", "deterministic-fallback"] | None = None
    model: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    recommendation_run_id: str | None = None
    prompt_version: str | None = None
    workflow_version: str | None = None
    tools: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    reply_ready_at: datetime | None = None
    completed_at: datetime | None = None


ADVISOR_TURN_STATUS_RANK = {
    "reserved": 0,
    "planned": 1,
    "actions_applied": 2,
    "reply_ready": 3,
    "completed": 4,
}


def advisor_turn_status_rank(status: str) -> int:
    return ADVISOR_TURN_STATUS_RANK[status]


class AdvisorReply(BaseModel):
    thread: AdvisorThread
    profile: ApplicantProfile
    recommendation_run: AgentRecommendationResponse | None = None
    model: str
    provider: Literal["openai", "ollama", "deepseek", "deterministic-fallback"]
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    prompt_version: str = "advisor-1.0.0"


class LLMStatus(BaseModel):
    configured: bool
    provider: str = "openai"
    model: str
    api: str = "responses"


class AIConsentRequest(BaseModel):
    accepted: bool


class AIConsent(BaseModel):
    accepted: bool
    provider: Literal["deepseek"] = "deepseek"
    version: str = "deepseek-data-1.0"
    updated_at: datetime


class TranscriptAnalysisRequest(BaseModel):
    transcript_text: str = Field(min_length=3, max_length=30000)
    save_to_profile: bool = True


class TranscriptCourse(BaseModel):
    name: str
    category: Literal["数学与统计", "编程", "算法与数据结构", "数据库", "计算机基础", "其他"]


class ProgramPrerequisiteMatch(BaseModel):
    program_slug: str
    program_name: str
    matched: list[str]
    missing: list[str]
    status: Literal["满足", "部分满足", "无需指定先修课"]


class TranscriptAnalysisResponse(BaseModel):
    courses: list[TranscriptCourse]
    program_matches: list[ProgramPrerequisiteMatch]
    academic_summary: str
    warnings: list[str]


class ApplicationTask(BaseModel):
    id: str
    title: str
    detail: str
    category: Literal["选校", "成绩单", "语言", "材料", "截止日期", "其他"]
    priority: Literal["P0", "P1", "P2"]
    status: Literal["待开始", "进行中", "已完成"] = "待开始"
    due_at: datetime | None = None
    reminder_at: datetime | None = None
    source_run_id: str | None = None
    phase: Literal["selection", "academic", "language", "specialized", "submission", "decision"] = "specialized"
    program_slug: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    schedule_origin: Literal["system_suggestion", "official", "user"] = "system_suggestion"
    created_at: datetime
    updated_at: datetime


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    detail: str = Field(default="", max_length=1000)
    category: Literal["选校", "成绩单", "语言", "材料", "截止日期", "其他"] = "其他"
    priority: Literal["P0", "P1", "P2"] = "P1"
    due_at: datetime | None = None
    reminder_at: datetime | None = None


class TaskUpdateRequest(BaseModel):
    status: Literal["待开始", "进行中", "已完成"] | None = None
    due_at: datetime | None = None
    reminder_at: datetime | None = None


class RoadmapPhase(BaseModel):
    id: Literal["selection", "academic", "language", "specialized", "submission", "decision"]
    title: str
    detail: str
    suggested_at: datetime
    status: Literal["pending", "in_progress", "completed", "overdue"]
    tasks: list[ApplicationTask] = Field(default_factory=list)


class ProgramRoadmapBranch(BaseModel):
    program_slug: str
    program_name: str
    university: str
    is_primary: bool
    official_deadline: datetime | None = None
    deadline_source_url: str | None = None
    tasks: list[ApplicationTask] = Field(default_factory=list)


class ApplicationRoadmap(BaseModel):
    run_id: str
    intake: str
    anchor_at: datetime
    generated_at: datetime
    phases: list[RoadmapPhase]
    program_branches: list[ProgramRoadmapBranch]
    completed_tasks: int
    total_tasks: int


class AdvisorStreamState(BaseModel):
    """Authoritative client state after an advisor turn finishes."""

    thread: AdvisorThread
    profile: ApplicantProfile
    recommendation_run: AgentRecommendationResponse | None = None
    portfolio: list[ApplicationChoice]
    roadmap: ApplicationRoadmap | None = None


class ProgramSourceChange(BaseModel):
    field: str
    before: Any = None
    after: Any = None


class ProgramSourceSnapshot(BaseModel):
    requested_url: str = Field(max_length=2048)
    final_url: str = Field(max_length=2048)
    fetched_at: datetime
    content_type: str = Field(max_length=100)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_bytes: int = Field(gt=0, le=512 * 1024)
    body_text: str = Field(min_length=1, max_length=512 * 1024)
    redirect_chain: list[str] = Field(default_factory=list, max_length=3)


class ProgramSourceVersion(BaseModel):
    version_id: str
    program_slug: str
    source_id: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: Literal["pending_review", "published", "superseded", "rejected"]
    program: Program
    changes: list[ProgramSourceChange] = Field(default_factory=list)
    submitted_by: str
    submitted_at: datetime
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    rollback_of: str | None = None
    source_snapshot: ProgramSourceSnapshot | None = None


class ProgramSourceCandidateRequest(BaseModel):
    base_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    program: Program
    capture_snapshot: bool = False


class ProgramSourceReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=1000)


class ProgramSourceRollbackRequest(BaseModel):
    target_version_id: str = Field(min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=1000)


class ProgramSourceStatus(BaseModel):
    source_id: str
    program_slug: str
    title: str
    url: str
    verified_at: str
    published_version_id: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    pending_versions: int = 0
    status: Literal["已核验", "需要复核"]
    reason: str


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    target_degree_level: DegreeLevel | None = None
    target_field: StudyArea | None = None
    program_slugs: list[str] = Field(default_factory=list, max_length=20)
    top_k: int = Field(default=5, ge=1, le=8)


class KnowledgeEvidence(BaseModel):
    chunk_id: str
    program_slug: str
    university: str
    program_name: str
    section: Literal["项目概览", "学术与背景", "先修课与语言"]
    content: str
    relevance_score: float = Field(ge=0)
    source: SourceCitation


class KnowledgeSearchResponse(BaseModel):
    query: str
    retrieval_version: str
    generated_at: datetime
    hits: list[KnowledgeEvidence]
    coverage_notice: str


class AgentRunAudit(BaseModel):
    id: str
    thread_id: str
    message_id: str
    provider: Literal["openai", "ollama", "deepseek", "deterministic-fallback"]
    model: str
    prompt_version: str
    workflow_version: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    tools: list[str]
    created_at: datetime
