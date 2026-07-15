from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

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
    annual_budget_aud: float | None = Field(default=None, gt=0)


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
    summary: str
    missing_information: list[str]
    tool_trace: list[ToolTrace]
    recommendations: list[ProgramRecommendation]


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=6, max_length=128)


class DemoUser(BaseModel):
    id: str
    email: str
    display_name: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: DemoUser


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
    tool: Literal["update_profile", "run_recommendation", "create_task", "answer"]
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
    title: str
    messages: list[AdvisorMessage]
    created_at: datetime
    updated_at: datetime


class AdvisorMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class AdvisorReply(BaseModel):
    thread: AdvisorThread
    profile: ApplicantProfile
    recommendation_run: AgentRecommendationResponse | None = None
    model: str
    provider: Literal["openai", "ollama", "deterministic-fallback"]
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    prompt_version: str = "advisor-1.0.0"


class LLMStatus(BaseModel):
    configured: bool
    provider: str = "openai"
    model: str
    api: str = "responses"


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


class ProgramSourceStatus(BaseModel):
    source_id: str
    program_slug: str
    title: str
    url: str
    verified_at: str
    status: Literal["已核验", "需要复核"]
    reason: str


class AgentRunAudit(BaseModel):
    id: str
    thread_id: str
    message_id: str
    provider: Literal["openai", "ollama", "deterministic-fallback"]
    model: str
    prompt_version: str
    workflow_version: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    tools: list[str]
    created_at: datetime
