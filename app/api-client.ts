export type ApiMode = "fastapi" | "demo-fallback";

export type ApiUser = {
  id: string;
  email: string;
  display_name: string;
  role: "user" | "admin";
  email_verified: boolean;
  status: "active" | "suspended";
  created_at?: string | null;
  last_login_at?: string | null;
  terms_accepted_at?: string | null;
  terms_version?: string | null;
};

export type AuthSession = { access_token: string; user: ApiUser };

export type ApiApplicantProfile = {
  current_education_level: string;
  undergraduate_school: string;
  school_tier: string;
  undergraduate_major: string;
  gpa: number;
  gpa_scale: number;
  target_degree_level: string;
  target_field: string;
  intake: string;
  english_score?: string | null;
  coursework_summary?: string | null;
  experience_summary?: string | null;
  career_goal?: string | null;
  location_preferences?: string | null;
  annual_budget_cny?: number | null;
};

export type RegistrationResult = {
  message: string;
  user: ApiUser;
  delivery: "smtp" | "console" | "disabled";
  debug_token?: string | null;
};

export type FeedbackItem = {
  id: string;
  user_id: string;
  user_email: string;
  category: "问题" | "建议" | "数据错误" | "其他";
  message: string;
  page?: string | null;
  status: "new" | "reviewing" | "resolved";
  created_at: string;
  updated_at: string;
};

export type AdminStats = {
  users: number;
  verified_users: number;
  active_sessions: number;
  recommendation_runs: number;
  advisor_threads: number;
  open_feedback: number;
  verified_programs: number;
  catalog_coverage_cells: number;
  llm_calls_today: number;
  llm_average_latency_ms: number;
  llm_fallback_rate: number;
  llm_input_tokens_today: number;
  llm_output_tokens_today: number;
};

export type ProgramSourceStatus = {
  source_id: string;
  program_slug: string;
  title: string;
  url: string;
  verified_at: string;
  published_version_id: string;
  content_hash: string;
  pending_versions: number;
  status: "已核验" | "需要复核";
  reason: string;
};

export type ApiHistoryItem = {
  run_id: string;
  created_at: string;
  workflow_version: string;
  target_field: string;
  intake: string;
  recommendation_count: number;
  summary: string;
};

export type ApiActionItem = {
  id: string;
  title: string;
  detail: string;
  priority: "P0" | "P1" | "P2";
  status: "待开始" | "进行中" | "已完成";
  category?: string;
  due_at?: string | null;
  reminder_at?: string | null;
  source_run_id?: string | null;
  phase?: "selection" | "academic" | "language" | "specialized" | "submission" | "decision";
  program_slug?: string | null;
  dependencies?: string[];
  schedule_origin?: "system_suggestion" | "official" | "user";
};

export type ApplicationChoice = {
  run_id: string;
  program_slug: string;
  status: "considering" | "applying" | "excluded";
  is_primary: boolean;
  official_deadline?: string | null;
  deadline_source_url?: string | null;
  updated_at: string;
};

export type RoadmapPhase = {
  id: "selection" | "academic" | "language" | "specialized" | "submission" | "decision";
  title: string;
  detail: string;
  suggested_at: string;
  status: "pending" | "in_progress" | "completed" | "overdue";
  tasks: ApiActionItem[];
};

export type ApplicationRoadmap = {
  run_id: string;
  intake: string;
  anchor_at: string;
  generated_at: string;
  phases: RoadmapPhase[];
  program_branches: Array<{
    program_slug: string;
    program_name: string;
    university: string;
    is_primary: boolean;
    official_deadline?: string | null;
    deadline_source_url?: string | null;
    tasks: ApiActionItem[];
  }>;
  completed_tasks: number;
  total_tasks: number;
};

export type AdvisorAction = {
  tool: "update_profile" | "run_recommendation" | "create_task" | "set_application_choice" | "update_task" | "answer";
  summary: string;
  status: "completed" | "needs_confirmation" | "skipped";
};

export type AdvisorMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  actions: AdvisorAction[];
};

export type AdvisorThread = {
  id: string;
  title: string;
  messages: AdvisorMessage[];
  created_at: string;
  updated_at: string;
};

export type AIConsent = {
  accepted: boolean;
  provider: "deepseek";
  version: string;
  updated_at: string;
};

export type AdvisorStreamEvent =
  | { event: "status"; data: { message: string; provider: string } }
  | { event: "delta"; data: { content: string } }
  | { event: "actions"; data: AdvisorAction[] }
  | {
      event: "state";
      data: {
        thread: AdvisorThread;
        profile: ApiApplicantProfile;
        recommendation_run: ApiAgentRun | null;
        portfolio: ApplicationChoice[];
        roadmap: ApplicationRoadmap | null;
      };
    }
  | { event: "done"; data: { provider: string; model: string; latency_ms: number } }
  | { event: "error"; data: { message: string; fallback: boolean } };

export type TranscriptAnalysis = {
  academic_summary: string;
  warnings: string[];
  courses: { name: string; category: string }[];
  program_matches: { program_slug: string; program_name: string; matched: string[]; missing: string[]; status: string }[];
};

export type ApiProgramSource = {
  id: string;
  title: string;
  url: string;
  excerpt: string;
  verified_at: string;
  version_id: string | null;
  content_hash: string | null;
};

export type ApiProgram = {
  slug: string;
  university: string;
  name: string;
  city: string;
  degree_level: string;
  field: string;
  minimum_mark?: number | null;
  non_211_minimum_mark?: number | null;
  requires_cognate: boolean;
  prerequisites: string[];
  english_requirement: string;
  duration: string;
  requires_supervisor: boolean;
  research_proposal_required: boolean;
  verification_status: "已核验" | "待复核";
  source: ApiProgramSource;
};

export type ProgramSourceChange = {
  field: string;
  before: unknown;
  after: unknown;
};

export type ProgramSourceVersion = {
  version_id: string;
  program_slug: string;
  source_id: string;
  content_hash: string;
  base_hash?: string | null;
  status: "pending_review" | "published" | "superseded" | "rejected";
  program: ApiProgram;
  changes: ProgramSourceChange[];
  submitted_by: string;
  submitted_at: string;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  review_note?: string | null;
  rollback_of?: string | null;
};

export type ApiProgramRecommendation = {
  program: ApiProgram;
  tier: "冲刺" | "匹配" | "稳妥" | "暂不推荐";
  eligibility: "满足基础门槛" | "需要人工核验" | "存在门槛缺口";
  match_score: number;
  reasons: string[];
  risks: string[];
  next_action: string;
  citations: ApiProgramSource[];
};

export type ApiAgentRun = {
  run_id: string;
  workflow_version: string;
  agent_mode: "deterministic-demo" | "llm-assisted";
  profile_snapshot?: ApiApplicantProfile | null;
  summary: string;
  missing_information: string[];
  tool_trace: Array<{
    step: number;
    tool: string;
    status: "completed" | "needs_input" | "failed" | "skipped";
    summary: string;
    evidence_ids: string[];
  }>;
  catalog_options: Array<{
    university_slug: string;
    university: string;
    city: string;
    degree_level: string;
    field: string;
    catalog_url: string;
    source_title: string;
    status: string;
  }>;
  recommendations: ApiProgramRecommendation[];
};

export type KnowledgeEvidence = {
  chunk_id: string;
  program_slug: string;
  university: string;
  program_name: string;
  section: "项目概览" | "学术与背景" | "先修课与语言";
  content: string;
  relevance_score: number;
  source: ApiProgramSource;
};

export type KnowledgeSearchResponse = {
  query: string;
  retrieval_version: string;
  generated_at: string;
  hits: KnowledgeEvidence[];
  coverage_notice: string;
};

// Same-origin is the production default; Sites gracefully falls back when /api is absent.
const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "/api").replace(/\/$/, "");
export const SESSION_EXPIRED_EVENT = "offerpilot:session-expired";

export class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

export function isSessionExpiredError(error: unknown): error is ApiRequestError {
  return error instanceof ApiRequestError
    && error.status === 401
    && (error.message === "登录已失效" || error.message === "缺少 Bearer token");
}

function scheduleSessionExpired(error: ApiRequestError) {
  if (typeof window === "undefined" || !isSessionExpiredError(error)) return;
  window.setTimeout(() => window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT)), 0);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers({ "Content-Type": "application/json", ...init?.headers });
  const authenticatedRequest = headers.has("Authorization");
  if (headers.get("Authorization") === "Bearer cookie") headers.delete("Authorization");
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as {
      detail?: string | Array<{ msg?: string }>;
    } | null;
    const detail = Array.isArray(body?.detail)
      ? body.detail.map((item) => item.msg).filter(Boolean).join("；")
      : body?.detail;
    const error = new ApiRequestError(detail || `请求失败（${response.status}）`, response.status);
    if (authenticatedRequest) scheduleSessionExpired(error);
    throw error;
  }
  return response.json() as Promise<T>;
}

export async function fetchCurrentUser(): Promise<ApiUser> {
  return request<ApiUser>("/me");
}

export async function loginWithAccount(email: string, password: string): Promise<AuthSession> {
  return request<AuthSession>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function registerAccount(
  email: string,
  password: string,
  displayName: string,
  acceptedTerms: boolean,
): Promise<RegistrationResult> {
  return request<RegistrationResult>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, display_name: displayName, accepted_terms: acceptedTerms }),
  });
}

export async function verifyEmail(token: string): Promise<string> {
  const response = await request<{ message: string }>("/auth/verify-email", {
    method: "POST", body: JSON.stringify({ token }),
  });
  return response.message;
}

export async function resendVerification(email: string): Promise<string> {
  const response = await request<{ message: string }>("/auth/resend-verification", {
    method: "POST", body: JSON.stringify({ email }),
  });
  return response.message;
}

export async function requestPasswordReset(email: string): Promise<string> {
  const response = await request<{ message: string }>("/auth/forgot-password", {
    method: "POST", body: JSON.stringify({ email }),
  });
  return response.message;
}

export async function resetPassword(token: string, password: string): Promise<string> {
  const response = await request<{ message: string }>("/auth/reset-password", {
    method: "POST", body: JSON.stringify({ token, password }),
  });
  return response.message;
}

export async function logoutAccount(token: string): Promise<void> {
  await request("/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

export async function exportAccountData(token: string): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>("/me/export", { headers: { Authorization: `Bearer ${token}` } });
}

export async function deleteAccount(token: string, password: string): Promise<void> {
  await request("/me", {
    method: "DELETE", headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ password, confirmation: "DELETE" }),
  });
}

export async function saveProfile(token: string, profile: ApiApplicantProfile): Promise<void> {
  await request("/me/profile", {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(profile),
  });
}

export async function fetchProfile(token: string): Promise<ApiApplicantProfile> {
  return request<ApiApplicantProfile>("/me/profile", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function createAgentRun(token: string): Promise<ApiAgentRun> {
  return request<ApiAgentRun>("/me/recommendation-runs", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function fetchAgentRun(token: string, runId: string): Promise<ApiAgentRun> {
  return request<ApiAgentRun>(`/me/recommendation-runs/${runId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function searchOfficialKnowledge(
  token: string,
  query: string,
  filters?: { target_degree_level?: string; target_field?: string; program_slugs?: string[]; top_k?: number },
): Promise<KnowledgeSearchResponse> {
  return request<KnowledgeSearchResponse>("/me/knowledge/search", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ query, top_k: 5, ...filters }),
  });
}

export async function fetchHistory(token: string): Promise<ApiHistoryItem[]> {
  return request<ApiHistoryItem[]>("/me/recommendation-runs", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function fetchActionPlan(token: string, runId: string): Promise<ApiActionItem[]> {
  const response = await request<{ items: ApiActionItem[] }>(`/me/recommendation-runs/${runId}/action-plan`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return response.items;
}

export async function fetchPortfolio(token: string, runId: string): Promise<ApplicationChoice[]> {
  return request<ApplicationChoice[]>(`/me/recommendation-runs/${runId}/portfolio`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function updatePortfolioChoice(
  token: string,
  runId: string,
  programSlug: string,
  payload: Pick<ApplicationChoice, "status" | "is_primary"> & {
    official_deadline?: string | null;
    deadline_source_url?: string | null;
  },
): Promise<ApplicationChoice> {
  return request<ApplicationChoice>(`/me/recommendation-runs/${runId}/portfolio/${programSlug}`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  });
}

export async function fetchRoadmap(token: string, runId: string): Promise<ApplicationRoadmap> {
  return request<ApplicationRoadmap>(`/me/recommendation-runs/${runId}/roadmap`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function createAdvisorThread(token: string): Promise<AdvisorThread> {
  return request<AdvisorThread>("/me/advisor/threads", { method: "POST", headers: { Authorization: `Bearer ${token}` } });
}

export async function fetchAdvisorThreads(token: string): Promise<AdvisorThread[]> {
  return request<AdvisorThread[]>("/me/advisor/threads", { headers: { Authorization: `Bearer ${token}` } });
}

export async function sendAdvisorMessage(token: string, threadId: string, content: string): Promise<{ thread: AdvisorThread; provider: string }> {
  return request(`/me/advisor/threads/${threadId}/messages`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ content }),
  });
}

export async function fetchAIConsent(token: string): Promise<AIConsent | null> {
  return request<AIConsent | null>("/me/advisor/consent", { headers: { Authorization: `Bearer ${token}` } });
}

export async function saveAIConsent(token: string, accepted: boolean): Promise<AIConsent> {
  return request<AIConsent>("/me/advisor/consent", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ accepted }),
  });
}

export async function streamAdvisorMessage(
  token: string,
  threadId: string,
  content: string,
  onEvent: (event: AdvisorStreamEvent) => void,
): Promise<void> {
  const headers = new Headers({ "Content-Type": "application/json" });
  // The authenticated browser keeps the real credential in an HttpOnly
  // cookie. "cookie" is only a React presence marker and must never shadow
  // that cookie as a fake Bearer token.
  if (token && token !== "cookie") headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_URL}/me/advisor/threads/${threadId}/messages/stream`, {
    method: "POST",
    credentials: "include",
    headers,
    body: JSON.stringify({ content }),
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    const error = new ApiRequestError(body?.detail || `顾问请求失败（${response.status}）`, response.status);
    scheduleSessionExpired(error);
    throw error;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let committedStateReceived = false;
  const dispatchBlock = (block: string) => {
    const event = block.split("\n").find((line) => line.startsWith("event:"))?.slice(6).trim();
    const data = block.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
    if (!event || !data) return;
    if (event === "state") committedStateReceived = true;
    onEvent({ event, data: JSON.parse(data) } as AdvisorStreamEvent);
  };
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    blocks.forEach(dispatchBlock);
    if (done) {
      if (buffer.trim()) dispatchBlock(buffer);
      break;
    }
  }
  if (!committedStateReceived) throw new Error("顾问连接在收到保存确认前中断");
}

export async function analyzeTranscript(token: string, transcriptText: string): Promise<TranscriptAnalysis> {
  return request<TranscriptAnalysis>("/me/transcript/analyze", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ transcript_text: transcriptText, save_to_profile: true }),
  });
}

export async function fetchTasks(token: string): Promise<ApiActionItem[]> {
  return request<ApiActionItem[]>("/me/tasks", { headers: { Authorization: `Bearer ${token}` } });
}

export async function updateTask(token: string, taskId: string, status: ApiActionItem["status"]): Promise<ApiActionItem> {
  return request<ApiActionItem>(`/me/tasks/${taskId}`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ status }),
  });
}

export async function updateTaskDetails(
  token: string,
  taskId: string,
  payload: { status?: ApiActionItem["status"]; due_at?: string | null; reminder_at?: string | null },
): Promise<ApiActionItem> {
  return request<ApiActionItem>(`/me/tasks/${taskId}`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  });
}

export async function createFeedback(
  token: string,
  payload: { category: FeedbackItem["category"]; message: string; page?: string },
): Promise<FeedbackItem> {
  return request<FeedbackItem>("/me/feedback", {
    method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload),
  });
}

export async function fetchMyFeedback(token: string): Promise<FeedbackItem[]> {
  return request<FeedbackItem[]>("/me/feedback", { headers: { Authorization: `Bearer ${token}` } });
}

export async function fetchAdminStats(token: string): Promise<AdminStats> {
  return request<AdminStats>("/admin/stats", { headers: { Authorization: `Bearer ${token}` } });
}

export async function fetchAdminUsers(token: string): Promise<ApiUser[]> {
  return request<ApiUser[]>("/admin/users", { headers: { Authorization: `Bearer ${token}` } });
}

export async function updateAdminUser(token: string, userId: string, status: ApiUser["status"]): Promise<ApiUser> {
  return request<ApiUser>(`/admin/users/${userId}`, {
    method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ status }),
  });
}

export async function fetchAdminFeedback(token: string): Promise<FeedbackItem[]> {
  return request<FeedbackItem[]>("/admin/feedback", { headers: { Authorization: `Bearer ${token}` } });
}

export async function fetchAdminProgramSources(token: string): Promise<ProgramSourceStatus[]> {
  return request<ProgramSourceStatus[]>("/admin/program-sources", { headers: { Authorization: `Bearer ${token}` } });
}

export async function fetchProgram(programSlug: string): Promise<ApiProgram> {
  return request<ApiProgram>(`/programs/${programSlug}`);
}

export async function fetchAdminProgramSourceVersions(
  token: string,
  programSlug: string,
): Promise<ProgramSourceVersion[]> {
  return request<ProgramSourceVersion[]>(`/admin/program-sources/${programSlug}/versions`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function createAdminProgramSourceVersion(
  token: string,
  programSlug: string,
  baseHash: string,
  program: ApiProgram,
): Promise<ProgramSourceVersion> {
  return request<ProgramSourceVersion>(`/admin/program-sources/${programSlug}/versions`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ base_hash: baseHash, program }),
  });
}

export async function reviewAdminProgramSourceVersion(
  token: string,
  programSlug: string,
  versionId: string,
  decision: "approve" | "reject",
  note: string,
): Promise<ProgramSourceVersion> {
  return request<ProgramSourceVersion>(`/admin/program-sources/${programSlug}/versions/${versionId}`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ decision, note }),
  });
}

export async function rollbackAdminProgramSourceVersion(
  token: string,
  programSlug: string,
  targetVersionId: string,
  note: string,
): Promise<ProgramSourceVersion> {
  return request<ProgramSourceVersion>(`/admin/program-sources/${programSlug}/rollback`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ target_version_id: targetVersionId, note }),
  });
}

export async function updateAdminFeedback(token: string, feedbackId: string, status: FeedbackItem["status"]): Promise<FeedbackItem> {
  return request<FeedbackItem>(`/admin/feedback/${feedbackId}`, {
    method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ status }),
  });
}
