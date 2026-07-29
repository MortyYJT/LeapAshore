"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  AdvisorAction,
  AdvisorThread,
  AIConsent,
  AdminStats,
  ApiApplicantProfile,
  ApiAgentRun,
  ApiActionItem,
  ApplicationChoice,
  ApplicationRoadmap,
  ApiHistoryItem,
  ApiProgram,
  ApiProgramRecommendation,
  KnowledgeEvidence,
  ApiUser,
  FeedbackItem,
  ProgramSourceStatus,
  SESSION_EXPIRED_EVENT,
  TranscriptAnalysis,
  analyzeTranscript,
  createAdvisorThread,
  createAgentRun,
  createFeedback,
  deleteAccount,
  exportAccountData,
  fetchAdminFeedback,
  fetchAdminStats,
  fetchAdminUsers,
  fetchAdminProgramSources,
  fetchAgentRun,
  fetchAIConsent,
  fetchAdvisorThreads,
  fetchCurrentUser,
  fetchHistory,
  fetchPortfolio,
  fetchProfile,
  fetchRoadmap,
  fetchMyFeedback,
  loginWithAccount,
  logoutAccount,
  isSessionExpiredError,
  registerAccount,
  requestPasswordReset,
  resendVerification,
  resetPassword,
  saveProfile,
  saveAIConsent,
  searchOfficialKnowledge,
  streamAdvisorMessage,
  updateTaskDetails,
  updatePortfolioChoice,
  updateAdminFeedback,
  updateAdminUser,
  verifyEmail,
} from "./api-client";
import { PortfolioControls } from "./portfolio-controls";
import { RoadmapView } from "./roadmap-view";
import { SourceReviewPanel } from "./source-review-panel";

type View = "landing" | "login" | "profile" | "agent" | "advisor" | "results" | "program" | "plan" | "history" | "feedback" | "admin" | "account" | "terms" | "privacy";
type Tier = "冲刺" | "匹配" | "稳妥" | "暂不推荐";
type NavSection = "landing" | "profile" | "advisor" | "results" | "plan" | "history" | "feedback" | "admin" | "account";
type AuthMode = "login" | "register" | "forgot" | "reset";

type Profile = {
  currentEducation: string;
  school: string;
  schoolTier: string;
  major: string;
  gpa: string;
  gpaScale: string;
  targetDegree: string;
  target: string;
  intake: string;
  english: string;
  coursework: string;
  experience: string;
  careerGoal: string;
  cityPreference: string;
  annualBudget: string;
};

const degreeLevels = ["本科", "授课型硕士", "研究型硕士", "博士"] as const;
const studyAreas = [
  "计算机与数据", "商科与金融", "工程", "教育与社会科学", "生命科学", "医学与健康",
  "法律与犯罪学", "自然科学与数学", "人文与语言", "建筑规划与设计", "传媒艺术与音乐", "环境与农业",
] as const;
const officialCatalogs = [
  ["ANU", "https://programsandcourses.anu.edu.au/Search"],
  ["墨尔本大学", "https://study.unimelb.edu.au/"],
  ["UNSW", "https://www.unsw.edu.au/study/find-a-degree-or-course"],
  ["悉尼大学", "https://www.sydney.edu.au/courses/search.html"],
  ["蒙纳士大学", "https://www.monash.edu/study/courses/find-a-course"],
  ["昆士兰大学", "https://study.uq.edu.au/study-options/programs?type=program"],
  ["西澳大学", "https://www.uwa.edu.au/study/courses"],
  ["阿德莱德大学", "https://adelaideuni.edu.au/study/degrees"],
] as const;
const verifiedProgramUniversities = ["UNSW", "USYD", "MON", "UQ", "UWA"] as const;

const agentSteps = [
  { tool: "normalize_gpa", label: "换算学术成绩", detail: "统一不同学校和满分制的成绩口径" },
  { tool: "retrieve_official_catalogs", label: "读取官方目录", detail: "读取本地登记的澳洲八大官方课程目录入口" },
  { tool: "retrieve_programs", label: "匹配目标项目", detail: "结合学位、方向与入学时间筛选已核验项目" },
  { tool: "check_hard_constraints", label: "评估申请要求", detail: "对照均分、专业背景、先修课程和语言要求" },
  { tool: "rank_portfolio", label: "规划申请组合", detail: "平衡冲刺、匹配和稳妥项目" },
  { tool: "validate_citations", label: "整理风险与材料", detail: "生成待确认事项和申请准备顺序" },
];

const initialProfile: Profile = {
  currentEducation: "本科",
  school: "",
  schoolTier: "双非",
  major: "",
  gpa: "",
  gpaScale: "100",
  targetDegree: "授课型硕士",
  target: "计算机与数据",
  intake: "2027 S1",
  english: "",
  coursework: "",
  experience: "",
  careerGoal: "",
  cityPreference: "",
  annualBudget: "",
};
const initialRunSummary = "已完成项目要求对照，并根据你的背景生成申请组合。";

const advisorActionStatusMeta: Record<AdvisorAction["status"], { icon: string; label: string }> = {
  completed: { icon: "✓", label: "已完成" },
  needs_confirmation: { icon: "?", label: "待确认" },
  skipped: { icon: "–", label: "已跳过" },
};

function profileToApi(profile: Profile): ApiApplicantProfile {
  return {
    current_education_level: profile.currentEducation,
    undergraduate_school: profile.school,
    school_tier: profile.schoolTier,
    undergraduate_major: profile.major,
    gpa: Number(profile.gpa),
    gpa_scale: Number(profile.gpaScale),
    target_degree_level: profile.targetDegree,
    target_field: profile.target,
    intake: profile.intake,
    english_score: profile.english || null,
    experience_summary: profile.experience || null,
    coursework_summary: profile.coursework || null,
    career_goal: profile.careerGoal || null,
    location_preferences: profile.cityPreference || null,
    annual_budget_cny: profile.annualBudget ? Number(profile.annualBudget) * 10000 : null,
  };
}

function profileFromApi(profile: ApiApplicantProfile): Profile {
  return {
    currentEducation: profile.current_education_level,
    school: profile.undergraduate_school,
    schoolTier: profile.school_tier,
    major: profile.undergraduate_major,
    gpa: String(profile.gpa),
    gpaScale: String(profile.gpa_scale),
    targetDegree: profile.target_degree_level,
    target: profile.target_field,
    intake: profile.intake,
    english: profile.english_score ?? "",
    coursework: profile.coursework_summary ?? "",
    experience: profile.experience_summary ?? "",
    careerGoal: profile.career_goal ?? "",
    cityPreference: profile.location_preferences ?? "",
    annualBudget: profile.annual_budget_cny ? String(profile.annual_budget_cny / 10000) : "",
  };
}

const universityPresentation: Record<string, { short: string; accent: string }> = {
  "新南威尔士大学": { short: "UNSW", accent: "#D7A900" },
  "悉尼大学": { short: "USYD", accent: "#C73B2C" },
  "蒙纳士大学": { short: "MON", accent: "#1769AA" },
  "昆士兰大学": { short: "UQ", accent: "#51247A" },
  "西澳大学": { short: "UWA", accent: "#12355B" },
};

function presentationFor(program: ApiProgram) {
  return universityPresentation[program.university] ?? {
    short: program.university.slice(0, 2),
    accent: "#315E52",
  };
}

const navItems: { section: NavSection; label: string }[] = [
  { section: "landing", label: "主界面" },
  { section: "profile", label: "我的背景" },
  { section: "advisor", label: "AI 申请顾问" },
  { section: "results", label: "选校方案" },
  { section: "plan", label: "行动计划" },
  { section: "history", label: "历史记录" },
  { section: "feedback", label: "产品反馈" },
  { section: "account", label: "账户设置" },
];

function activeNavSection(view: View): NavSection | null {
  if (view === "agent" || view === "program") return "results";
  if (view === "login" || view === "terms" || view === "privacy") return null;
  return view;
}

export default function Home() {
  const [view, setView] = useState<View>("login");
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [profileStep, setProfileStep] = useState<1 | 2>(1);
  const [profile, setProfile] = useState<Profile>(initialProfile);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [authNotice, setAuthNotice] = useState("");
  const [debugVerificationToken, setDebugVerificationToken] = useState<string | null>(null);
  const [resetToken, setResetToken] = useState("");
  const [currentUser, setCurrentUser] = useState<ApiUser | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<ApiProgramRecommendation | null>(null);
  const [tierFilter, setTierFilter] = useState<"全部" | Tier>("全部");
  const [token, setToken] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [runSummary, setRunSummary] = useState(initialRunSummary);
  const [agentRun, setAgentRun] = useState<ApiAgentRun | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [portfolio, setPortfolio] = useState<ApplicationChoice[]>([]);
  const [roadmap, setRoadmap] = useState<ApplicationRoadmap | null>(null);
  const [history, setHistory] = useState<ApiHistoryItem[]>([]);
  const [advisorThread, setAdvisorThread] = useState<AdvisorThread | null>(null);
  const [advisorInput, setAdvisorInput] = useState("");
  const [advisorBusy, setAdvisorBusy] = useState(false);
  const [advisorProvider, setAdvisorProvider] = useState("正在连接顾问");
  const [cloudConsent, setCloudConsent] = useState<AIConsent | null | undefined>(undefined);
  const [showCloudConsent, setShowCloudConsent] = useState(false);
  const [pendingAdvisorMessage, setPendingAdvisorMessage] = useState("");
  const advisorRetryRef = useRef<{ content: string; requestId: string } | null>(null);
  const [transcriptText, setTranscriptText] = useState("");
  const [transcriptResult, setTranscriptResult] = useState<TranscriptAnalysis | null>(null);
  const [knowledgeQuery, setKnowledgeQuery] = useState("UQ 数据科学的雅思和数学先修要求");
  const [knowledgeHits, setKnowledgeHits] = useState<KnowledgeEvidence[]>([]);
  const [knowledgeBusy, setKnowledgeBusy] = useState(false);
  const [feedbackCategory, setFeedbackCategory] = useState<FeedbackItem["category"]>("建议");
  const [feedbackMessage, setFeedbackMessage] = useState("");
  const [myFeedback, setMyFeedback] = useState<FeedbackItem[]>([]);
  const [adminStats, setAdminStats] = useState<AdminStats | null>(null);
  const [adminUsers, setAdminUsers] = useState<ApiUser[]>([]);
  const [adminFeedback, setAdminFeedback] = useState<FeedbackItem[]>([]);
  const [adminSources, setAdminSources] = useState<ProgramSourceStatus[]>([]);
  const [deletePassword, setDeletePassword] = useState("");

  const resetAuthenticatedSession = useCallback((message = "") => {
    setToken(null);
    setCurrentUser(null);
    setIsAuthenticated(false);
    setProfile(initialProfile);
    setProfileStep(1);
    setPassword("");
    setHistory([]);
    setAgentRun(null);
    setActiveRunId(null);
    setRunSummary(initialRunSummary);
    setPortfolio([]);
    setRoadmap(null);
    setSelected(null);
    setTierFilter("全部");
    setAdvisorThread(null);
    setAdvisorInput("");
    setAdvisorBusy(false);
    setAdvisorProvider("正在连接顾问");
    setCloudConsent(undefined);
    setShowCloudConsent(false);
    setPendingAdvisorMessage("");
    advisorRetryRef.current = null;
    setTranscriptText("");
    setTranscriptResult(null);
    setKnowledgeHits([]);
    setKnowledgeBusy(false);
    setMyFeedback([]);
    setAdminStats(null);
    setAdminUsers([]);
    setAdminFeedback([]);
    setAdminSources([]);
    setDeletePassword("");
    setIsSubmitting(false);
    setAuthNotice("");
    setError(message);
    setView("login");
    setAuthMode("login");
  }, []);

  const results = agentRun?.recommendations ?? [];
  const filteredResults = results.filter((item) => tierFilter === "全部" || item.tier === tierFilter);
  const portfolioBySlug = useMemo(() => new Map(portfolio.map((choice) => [choice.program_slug, choice])), [portfolio]);
  const applyingChoices = portfolio.filter((choice) => choice.status === "applying");
  const primaryChoice = applyingChoices.find((choice) => choice.is_primary) ?? null;
  const readiness = [profile.school, profile.major, profile.gpa, profile.english, profile.coursework, profile.experience, profile.careerGoal, profile.annualBudget]
    .filter((value) => value.trim()).length * 12.5;

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const verification = params.get("verify_token");
    const passwordReset = params.get("reset_token");
    if (verification) {
      verifyEmail(verification)
        .then((message) => { setAuthNotice(message); setAuthMode("login"); })
        .catch((reason: Error) => setError(reason.message));
      window.history.replaceState({}, "", window.location.pathname);
    } else if (passwordReset) {
      Promise.resolve().then(() => { setResetToken(passwordReset); setAuthMode("reset"); });
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  useEffect(() => {
    const handleSessionExpired = () => {
      void logoutAccount("cookie").catch(() => undefined);
      resetAuthenticatedSession("登录状态已失效，请重新登录。");
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
  }, [resetAuthenticatedSession]);

  useEffect(() => {
    fetchCurrentUser()
      .then((user) => {
        setCurrentUser(user);
        setToken("cookie");
        setIsAuthenticated(true);
        setView((current) => current === "login" ? "profile" : current);
        void hydrateWorkspace("cookie");
      })
      .catch((reason) => {
        if (!isSessionExpiredError(reason) || reason.message !== "登录已失效") return;
        void logoutAccount("cookie").catch(() => undefined);
        resetAuthenticatedSession("登录状态已失效，请重新登录。");
      });
  }, [resetAuthenticatedSession]);

  useEffect(() => {
    if (view === "feedback" && token) {
      void fetchMyFeedback(token).then(setMyFeedback).catch(() => setError("暂时无法读取反馈记录"));
    }
    if (view === "admin" && token && currentUser?.role === "admin") {
      void Promise.all([fetchAdminStats(token), fetchAdminUsers(token), fetchAdminFeedback(token), fetchAdminProgramSources(token)])
        .then(([stats, users, feedback, sources]) => { setAdminStats(stats); setAdminUsers(users); setAdminFeedback(feedback); setAdminSources(sources); })
        .catch(() => setError("暂时无法读取运营后台数据"));
    }
  }, [view, token, currentUser]);
  useEffect(() => {
    if (!token || !activeRunId || !["results", "program", "plan"].includes(view)) return;
    void Promise.all([fetchPortfolio(token, activeRunId), fetchRoadmap(token, activeRunId)])
      .then(([choices, nextRoadmap]) => { setPortfolio(choices); setRoadmap(nextRoadmap); })
      .catch(() => setError("暂时无法读取申请组合"));
  }, [view, token, activeRunId]);
  useEffect(() => {
    if (view !== "agent" || !agentRun) return;
    const timeout = window.setTimeout(() => setView("results"), 900);
    return () => window.clearTimeout(timeout);
  }, [view, agentRun]);

  useEffect(() => {
    if (view !== "advisor" || !token || advisorThread) return;
    const sessionToken = token;
    let cancelled = false;
    async function restoreAdvisor() {
      try {
        const [consent, threads] = await Promise.all([
          fetchAIConsent(sessionToken).catch(() => null),
          fetchAdvisorThreads(sessionToken),
        ]);
        if (cancelled) return;
        setCloudConsent(consent);
        setAdvisorProvider(consent?.accepted ? "DeepSeek V4 Flash · 云端" : consent ? "规则顾问 · 云端处理已关闭" : "顾问已就绪");
        const thread = threads[0] ?? await createAdvisorThread(sessionToken);
        if (!cancelled) setAdvisorThread(thread);
      } catch {
        if (!cancelled) setAdvisorProvider("请先保存申请档案");
      }
    }
    void restoreAdvisor();
    return () => { cancelled = true; };
  }, [view, token, advisorThread]);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email.includes("@") || password.length < 8) {
      setError("请输入有效邮箱，密码至少 8 位。");
      return;
    }
    setError("");
    setIsSubmitting(true);
    try {
      const session = await loginWithAccount(email, password);
      // The browser session lives in an HttpOnly cookie. Keep only a presence
      // marker in React so the real credential is never retained by UI state.
      setToken("cookie");
      setCurrentUser(session.user);
      setIsAuthenticated(true);
      await hydrateWorkspace("cookie");
      setView("profile");
    } catch (reason) {
      setToken(null);
      setError(reason instanceof Error ? reason.message : "登录失败，请稍后重试。");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleRegister(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setAuthNotice("");
    setIsSubmitting(true);
    try {
      const result = await registerAccount(email, password, displayName, acceptedTerms);
      setAuthNotice(result.message);
      setDebugVerificationToken(result.debug_token ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "注册失败，请稍后重试。");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleForgotPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      setAuthNotice(await requestPasswordReset(email));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "暂时无法发送重置邮件");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleResendVerification() {
    setError("");
    try {
      setAuthNotice(await resendVerification(email));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "暂时无法发送验证邮件");
    }
  }

  async function handleResetPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      setAuthNotice(await resetPassword(resetToken, password));
      setAuthMode("login");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "密码重置失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function completeLocalVerification() {
    if (!debugVerificationToken) return;
    setIsSubmitting(true);
    try {
      setAuthNotice(await verifyEmail(debugVerificationToken));
      setDebugVerificationToken(null);
      setAuthMode("login");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "验证失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleLogout() {
    if (token) await logoutAccount(token).catch(() => undefined);
    resetAuthenticatedSession();
  }

  async function hydrateWorkspace(sessionToken: string) {
    const [savedProfile, savedHistory] = await Promise.all([
      fetchProfile(sessionToken).catch(() => null),
      fetchHistory(sessionToken).catch(() => []),
    ]);
    if (savedProfile) setProfile(profileFromApi(savedProfile));
    setHistory(savedHistory);
  }

  async function handleExportData() {
    if (!token) return;
    const data = await exportAccountData(token);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `offerpilot-data-${new Date().toISOString().slice(0, 10)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function handleDeleteAccount() {
    if (!token || deletePassword.length < 8 || !window.confirm("确定永久删除账户和全部申请数据吗？此操作无法撤销。")) return;
    try {
      await deleteAccount(token, deletePassword);
      await handleLogout();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "账户删除失败");
    }
  }

  async function handleFeedback(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || feedbackMessage.trim().length < 3) return;
    setIsSubmitting(true);
    try {
      const item = await createFeedback(token, { category: feedbackCategory, message: feedbackMessage.trim(), page: view });
      setMyFeedback((items) => [item, ...items]);
      setFeedbackMessage("");
      setAuthNotice("反馈已提交，我们会在后台跟进处理。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "反馈提交失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function changeUserStatus(userId: string, status: ApiUser["status"]) {
    if (!token) return;
    const updated = await updateAdminUser(token, userId, status);
    setAdminUsers((users) => users.map((user) => user.id === updated.id ? updated : user));
  }

  async function changeFeedbackStatus(feedbackId: string, status: FeedbackItem["status"]) {
    if (!token) return;
    const updated = await updateAdminFeedback(token, feedbackId, status);
    setAdminFeedback((items) => items.map((item) => item.id === updated.id ? updated : item));
    setAdminStats(await fetchAdminStats(token));
  }

  function navigateTo(section: NavSection) {
    setError("");
    if (section === "profile") setProfileStep(1);
    if (section === "results" && !agentRun && history[0]) {
      void openHistoryRun(history[0]);
      return;
    }
    setView(isAuthenticated ? section : "login");
  }

  function handleBrandClick() {
    navigateTo("landing");
  }

  function handleProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (profileStep === 1 && (!profile.school.trim() || !profile.major.trim() || !profile.gpa.trim())) {
      setError("请先补全当前或最高学历、专业（课程体系）和学术成绩。");
      return;
    }
    if (profileStep === 1) {
      setError("");
      setProfileStep(2);
      return;
    }
    setError("");
    setAgentRun(null);
    setView("agent");
    void executeAgentRun();
  }

  async function executeAgentRun() {
    const backendProfile = profileToApi(profile);
    if (token) {
      try {
        await saveProfile(token, backendProfile);
        const run = await createAgentRun(token);
        setAgentRun(run);
        setActiveRunId(run.run_id);
        setRunSummary(run.summary);
        const [nextPortfolio, nextRoadmap] = await Promise.all([
          fetchPortfolio(token, run.run_id), fetchRoadmap(token, run.run_id),
        ]);
        setPortfolio(nextPortfolio);
        setRoadmap(nextRoadmap);
        setHistory(await fetchHistory(token));
        return;
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "生成选校方案失败，请稍后重试");
        setView("profile");
        return;
      }
    }
    setError("登录状态已失效，请重新登录后生成方案");
    setView("login");
  }

  function openProgram(recommendation: ApiProgramRecommendation) {
    setSelected(recommendation);
    setView("program");
  }

  function choiceFor(programSlug: string): ApplicationChoice {
    return portfolioBySlug.get(programSlug) ?? {
      run_id: activeRunId ?? "demo",
      program_slug: programSlug,
      status: "considering",
      is_primary: false,
      updated_at: new Date().toISOString(),
    };
  }

  async function changePortfolioChoice(programSlug: string, payload: {
    status: ApplicationChoice["status"];
    is_primary: boolean;
    official_deadline?: string | null;
    deadline_source_url?: string | null;
  }) {
    if (!token || !activeRunId || activeRunId.startsWith("run_demo_")) {
      setPortfolio((choices) => {
        const next = choices.map((choice) => payload.is_primary ? { ...choice, is_primary: false } : choice)
          .filter((choice) => choice.program_slug !== programSlug);
        return [...next, { run_id: activeRunId ?? "demo", program_slug: programSlug, updated_at: new Date().toISOString(), ...payload }];
      });
      return;
    }
    setError("");
    try {
      await updatePortfolioChoice(token, activeRunId, programSlug, payload);
      const [choices, nextRoadmap] = await Promise.all([fetchPortfolio(token, activeRunId), fetchRoadmap(token, activeRunId)]);
      setPortfolio(choices);
      setRoadmap(nextRoadmap);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "申请组合更新失败");
    }
  }

  async function updateRoadmapTask(taskId: string, payload: {
    status?: ApiActionItem["status"];
    due_at?: string | null;
    reminder_at?: string | null;
  }) {
    if (!token || !activeRunId) return;
    await updateTaskDetails(token, taskId, payload);
    const nextRoadmap = await fetchRoadmap(token, activeRunId);
    setRoadmap(nextRoadmap);
  }

  async function openHistoryRun(item: ApiHistoryItem) {
    setRunSummary(item.summary);
    setActiveRunId(item.run_id);
    if (token) {
      const [run, choices, nextRoadmap] = await Promise.all([
        fetchAgentRun(token, item.run_id), fetchPortfolio(token, item.run_id), fetchRoadmap(token, item.run_id),
      ]);
      setAgentRun(run);
      if (run.profile_snapshot) setProfile(profileFromApi(run.profile_snapshot));
      setPortfolio(choices);
      setRoadmap(nextRoadmap);
    }
    setView("results");
  }

  async function handleAdvisorMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = advisorInput.trim();
    if (!content || advisorBusy) return;
    if (cloudConsent == null) {
      setPendingAdvisorMessage(content);
      setShowCloudConsent(true);
      return;
    }
    await submitAdvisorMessage(content);
  }

  async function submitAdvisorMessage(content: string) {
    if (!token || !advisorThread || advisorBusy) return;
    const pendingRetry = advisorRetryRef.current;
    const requestId = pendingRetry?.content === content
      ? pendingRetry.requestId
      : crypto.randomUUID();
    advisorRetryRef.current = { content, requestId };
    const persistedMessageCount = advisorThread.messages.length;
    const activeThreadId = advisorThread.id;
    setAdvisorInput("");
    setAdvisorBusy(true);
    const temporaryUserId = `temp-user-${Date.now()}`;
    const temporaryAssistantId = `temp-assistant-${Date.now()}`;
    setAdvisorThread((thread) => thread ? {
      ...thread,
      messages: [...thread.messages,
        { id: temporaryUserId, role: "user", content, created_at: new Date().toISOString(), actions: [] },
        { id: temporaryAssistantId, role: "assistant", content: "", created_at: new Date().toISOString(), actions: [] },
      ],
    } : thread);
    let committedStateReceived = false;
    try {
      await streamAdvisorMessage(token, advisorThread.id, content, requestId, ({ event, data }) => {
        if (event === "status") setAdvisorProvider(data.message);
        if (event === "error") setAdvisorProvider(data.message);
        if (event === "delta") setAdvisorThread((thread) => thread ? {
          ...thread,
          messages: thread.messages.map((message) => message.id === temporaryAssistantId ? { ...message, content: message.content + data.content } : message),
        } : thread);
        if (event === "actions") setAdvisorThread((thread) => thread ? {
          ...thread,
          messages: thread.messages.map((message) => message.id === temporaryAssistantId ? { ...message, actions: data } : message),
        } : thread);
        if (event === "state") {
          committedStateReceived = true;
          setAdvisorThread(data.thread);
          setProfile(profileFromApi(data.profile));
          setPortfolio(data.portfolio);
          setRoadmap(data.roadmap);
          if (data.recommendation_run) {
            setAgentRun(data.recommendation_run);
            setActiveRunId(data.recommendation_run.run_id);
            setRunSummary(data.recommendation_run.summary);
            setSelected(null);
            setTierFilter("全部");
          }
        }
        if (event === "done") setAdvisorProvider(data.provider === "deepseek" ? `DeepSeek V4 Flash · ${data.latency_ms}ms` : "规则顾问 · 快速降级");
      });
      advisorRetryRef.current = null;
      void fetchHistory(token).then(setHistory).catch(() => undefined);
    } catch (reason) {
      setAdvisorProvider(reason instanceof Error ? reason.message : "暂时无法连接，请稍后重试");
      if (committedStateReceived) advisorRetryRef.current = null;
      if (!committedStateReceived) {
        const persistedThread = await fetchAdvisorThreads(token)
          .then((threads) => threads.find((thread) => thread.id === activeThreadId) ?? null)
          .catch(() => null);
        const newMessages = persistedThread?.messages.slice(persistedMessageCount) ?? [];
        const persistedUserIndex = newMessages.findIndex((message) => message.role === "user" && message.content === content);
        const turnWasPersisted = persistedUserIndex >= 0
          && newMessages.slice(persistedUserIndex + 1).some((message) => message.role === "assistant");
        if (persistedThread && turnWasPersisted) {
          advisorRetryRef.current = null;
          setAdvisorThread(persistedThread);
          setAdvisorProvider("回答已保存，已恢复最新会话");
          await hydrateWorkspace(token);
        } else {
          setAdvisorThread((thread) => thread ? {
            ...thread,
            messages: thread.messages.filter((message) => message.id !== temporaryUserId && message.id !== temporaryAssistantId),
          } : thread);
          setAdvisorInput(content);
          setAdvisorProvider(reason instanceof Error ? `${reason.message}，请重试` : "暂时无法连接，请稍后重试");
        }
      }
    } finally {
      setAdvisorBusy(false);
    }
  }

  async function decideCloudConsent(accepted: boolean) {
    if (!token) return;
    try {
      const consent = await saveAIConsent(token, accepted);
      setCloudConsent(consent);
      setShowCloudConsent(false);
      const content = pendingAdvisorMessage;
      setPendingAdvisorMessage("");
      if (content) await submitAdvisorMessage(content);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "数据处理选择保存失败");
    }
  }

  async function handleTranscriptAnalysis() {
    if (!token || !transcriptText.trim() || advisorBusy) return;
    setAdvisorBusy(true);
    try {
      setTranscriptResult(await analyzeTranscript(token, transcriptText));
    } catch {
      setAdvisorProvider("成绩单分析暂时不可用");
    } finally {
      setAdvisorBusy(false);
    }
  }

  async function handleKnowledgeSearch() {
    if (!token || knowledgeQuery.trim().length < 2 || knowledgeBusy) return;
    setKnowledgeBusy(true);
    setError("");
    try {
      const response = await searchOfficialKnowledge(token, knowledgeQuery.trim(), {
        target_degree_level: profile.targetDegree,
        target_field: profile.target,
        program_slugs: results.map((item) => item.program.slug),
        top_k: 4,
      });
      setKnowledgeHits(response.hits);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "官方资料检索暂时不可用");
    } finally {
      setKnowledgeBusy(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="site-header">
        <button className="brand" onClick={handleBrandClick} aria-label={isAuthenticated ? "返回主界面" : "返回登录页"}>
          <span className="brand-mark">O</span><span>OfferPilot</span><small>智能申请规划</small>
        </button>
        {isAuthenticated && <nav aria-label="主要导航">
          {navItems.map((item) => {
            const active = activeNavSection(view) === item.section;
            return <button key={item.section} className={active ? "active" : ""} aria-current={active ? "page" : undefined} onClick={() => navigateTo(item.section)}>
              <span>{item.label}</span>
            </button>;
          })}
          {currentUser?.role === "admin" && <button className={activeNavSection(view) === "admin" ? "active" : ""} aria-current={activeNavSection(view) === "admin" ? "page" : undefined} onClick={() => navigateTo("admin")}><span>运营后台</span></button>}
        </nav>}
        {isAuthenticated
          ? <button className="account-pill" onClick={() => void handleLogout()}><span>{currentUser?.display_name.slice(0, 1).toUpperCase() || "U"}</span>退出登录</button>
          : <span className="login-required">请先登录</span>}
      </header>

      {view === "landing" && (
        <section className="landing">
          <div className="hero-copy">
            <p className="eyebrow"><span /> 澳洲八大 · 本硕博 · 个性化申请规划</p>
            <h1>从你的背景出发，<br />规划每一步申请。</h1>
            <p className="hero-subtitle">填写学术背景、目标方向和申请偏好，获得具体项目建议、要求对照、风险提示与按优先级整理的材料计划。</p>
            <div className="hero-actions">
              <button className="primary-button" onClick={() => { setProfileStep(1); setView("profile"); }}>开始申请规划 <span>→</span></button>
              <button className="text-button" onClick={() => setView("results")}>查看选校示例</button>
            </div>
            <div className="trust-row"><div><strong>384</strong><span>个目录覆盖组合</span></div><div><strong>12</strong><span>个专业大类</span></div><div><strong>4</strong><span>个学位层次</span></div></div>
          </div>
          <div className="hero-visual" aria-label="申请方案预览">
            <div className="orbit orbit-one" /><div className="orbit orbit-two" />
            <div className="compass-card agent-preview-card">
              <div className="card-top"><span>你的申请方案</span><small>已生成</small></div>
              {agentSteps.slice(0, 4).map((step, index) => <div className="mini-tool" key={step.tool}><span>0{index + 1}</span><div><strong>{step.label}</strong><small>{step.detail}</small></div><em>✓</em></div>)}
              <div className="next-step"><span>下一步</span><strong>确认先修课程并建立申请时间表</strong></div>
            </div>
            <div className="floating-note note-one"><span>✓</span> 学术背景已评估</div><div className="floating-note note-two"><span>8</span> 所学校目录已接入</div>
          </div>
          <div className="go8-strip"><span>首批已核验项目</span>{verifiedProgramUniversities.map((university) => <b key={university}>{university}</b>)}</div>
        </section>
      )}

      {view === "login" && (
        <section className="center-stage"><div className="auth-panel">
          <div className="auth-intro"><p className="eyebrow"><span /> OfferPilot</p><h2>把复杂申请，<br />拆成清晰步骤</h2><p>保存你的申请背景、选校方案和材料进度，随时回来继续推进。</p><blockquote>先确认要求，再确定组合；先补关键缺口，再投入申请材料。</blockquote></div>
          <form className="auth-form" onSubmit={authMode === "login" ? handleLogin : authMode === "register" ? handleRegister : authMode === "forgot" ? handleForgotPassword : handleResetPassword}>
            <div className="step-kicker">{authMode === "login" ? "账户登录" : authMode === "register" ? "创建账户" : authMode === "forgot" ? "找回密码" : "设置新密码"}</div>
            <h3>{authMode === "login" ? "继续你的申请规划" : authMode === "register" ? "开始建立申请档案" : authMode === "forgot" ? "接收密码重置邮件" : "为账户设置新密码"}</h3>
            {authMode === "register" && <label>你的称呼<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} autoComplete="name" /></label>}
            {authMode !== "reset" && <label>邮箱<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" /></label>}
            {authMode !== "forgot" && <label>{authMode === "login" ? "密码" : "密码（至少 8 位，包含字母和数字）"}<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={authMode === "login" ? "current-password" : "new-password"} /></label>}
            {authNotice && <p className="form-success">{authNotice}</p>}
            {error && <p className="form-error">{error}</p>}
            {authMode === "register" && <label className="consent-field"><input type="checkbox" checked={acceptedTerms} onChange={(event) => setAcceptedTerms(event.target.checked)} /><span>我已阅读并同意服务条款与隐私说明</span></label>}
            <button className="primary-button wide" type="submit" disabled={isSubmitting || (authMode === "register" && !acceptedTerms)}>{isSubmitting ? "正在处理…" : authMode === "login" ? "登录" : authMode === "register" ? "注册并验证邮箱" : authMode === "forgot" ? "发送重置邮件" : "更新密码"} <span>→</span></button>
            {debugVerificationToken && <button className="outline-button wide" type="button" onClick={() => void completeLocalVerification()}>本地环境：完成邮箱验证</button>}
            {authMode === "login" && <div className="auth-links"><button type="button" onClick={() => { setAuthMode("register"); setError(""); setAuthNotice(""); }}>注册账户</button><button type="button" onClick={() => { setAuthMode("forgot"); setError(""); setAuthNotice(""); }}>忘记密码</button></div>}
            {authMode === "register" && <div className="auth-links"><button type="button" onClick={() => void handleResendVerification()}>重新发送验证邮件</button><button type="button" onClick={() => setAuthMode("login")}>已有账户，去登录</button></div>}
            {(authMode === "forgot" || authMode === "reset") && <div className="auth-links"><button type="button" onClick={() => setAuthMode("login")}>返回登录</button></div>}
            <p className="fine-print">请在注册前阅读 <button type="button" onClick={() => setView("terms")}>服务条款</button> 与 <button type="button" onClick={() => setView("privacy")}>隐私说明</button>。你的资料仅用于生成和保存申请规划。</p>
          </form>
        </div></section>
      )}

      {view === "terms" && <section className="legal-page"><button className="back-button" onClick={() => setView("login")}>← 返回登录</button><p className="eyebrow"><span /> 服务条款</p><h1>OfferPilot Beta 服务条款</h1><p>生效日期：2026 年 7 月 15 日</p><h2>产品用途</h2><p>OfferPilot 用于辅助整理学校公开信息、申请偏好和准备任务，不是学校、招生代理或录取决定机构。</p><h2>结果边界</h2><p>匹配分不是录取概率。课程要求、名额、费用和截止日期可能变化，用户应在提交申请前通过学校官网或学校正式渠道复核。</p><h2>账户与使用</h2><p>用户应提供真实且有权处理的资料，妥善保管账户，不得滥用服务、干扰系统或上传侵犯他人权益的内容。</p><h2>Beta 阶段</h2><p>封闭测试期间功能可能调整。我们会尽力保持数据与服务可靠，但不承诺服务永不中断或建议适用于所有情况。</p><h2>联系我们</h2><p>账户、安全或数据问题请通过产品内“产品反馈”提交。</p></section>}

      {view === "privacy" && <section className="legal-page"><button className="back-button" onClick={() => setView("login")}>← 返回登录</button><p className="eyebrow"><span /> 隐私说明</p><h1>OfferPilot Beta 隐私说明</h1><p>生效日期：2026 年 7 月 15 日</p><h2>收集的信息</h2><p>我们处理账户邮箱、申请背景、成绩与课程描述、目标偏好、顾问对话、任务进度、反馈和必要的安全日志。</p><h2>使用目的</h2><p>这些信息用于身份验证、生成申请规划、保存进度、改进产品、排查故障和防止滥用，不用于出售个人资料。</p><h2>存储与安全</h2><p>密码使用加盐哈希保存；验证、重置和会话令牌以哈希形式保存；生产数据存储在受控 PostgreSQL 中并执行备份。</p><h2>数据权利</h2><p>用户可以在“账户设置”中导出个人数据，或输入当前密码永久删除账户与关联资料；需要更正或帮助时可通过产品内反馈联系运营人员。</p><h2>DeepSeek 云端顾问</h2><p>首次使用前会单独征求同意。经同意后，仅发送脱敏申请画像、已核验选校事实、申请组合、路线图任务和最近对话；不发送姓名、邮箱、账户 ID、本科学校名称、原始成绩单或认证信息。拒绝后仍可使用规则顾问。</p><h2>第三方处理</h2><p>邮件服务商负责投递验证与重置邮件；DeepSeek 开放平台在用户单独同意后处理最小化顾问上下文。服务端 API Key 不会发送到浏览器或写入用户数据。</p></section>}

      {view === "profile" && (
        <section className="workspace">
          <aside className="side-rail"><p className="step-kicker">申请档案</p><h2>建立你的申请画像</h2><p>信息越完整，项目要求对照和后续材料建议越准确。</p><ol><li className="active"><span>{profileStep > 1 ? "✓" : "1"}</span><div><strong>学术背景</strong><small>学校、专业与成绩</small></div></li><li className={profileStep === 2 ? "active" : ""}><span>2</span><div><strong>目标与偏好</strong><small>方向、课程、预算与职业目标</small></div></li><li><span>3</span><div><strong>生成选校方案</strong><small>要求对照、组合与行动计划</small></div></li></ol><div className="privacy-note"><span>{Math.round(readiness)}%</span><p><strong>资料完整度</strong><br />建议补全语言、课程和职业目标。</p></div></aside>
          <form className="profile-form" onSubmit={handleProfile}><div className="form-heading"><div><p>步骤 {profileStep} / 2</p><h2>{profileStep === 1 ? "学术背景" : "申请目标与个人偏好"}</h2></div><span>{Math.round(readiness)}% 已完成</span></div><div className="progress"><i style={{ width: profileStep === 1 ? "50%" : "100%" }} /></div><div className="form-grid">
            {profileStep === 1 ? <>
              <label>当前或最高学历<select value={profile.currentEducation} onChange={(event) => setProfile({ ...profile, currentEducation: event.target.value })}><option>高中</option><option>本科</option><option>硕士</option><option>其他</option></select></label>
              <label>院校或课程体系<select value={profile.schoolTier} onChange={(event) => setProfile({ ...profile, schoolTier: event.target.value })}><option>高中/国际课程</option><option>985</option><option>211/双一流</option><option>双非</option><option>海外重点</option><option>其他</option></select></label>
              <label className="full">当前或最高学历院校 *<input value={profile.school} onChange={(event) => setProfile({ ...profile, school: event.target.value })} /></label>
              <label>专业或课程体系 *<input value={profile.major} onChange={(event) => setProfile({ ...profile, major: event.target.value })} placeholder="例如软件工程、A-Level" /></label>
              <label>当前学术成绩 *<div className="joined-input"><input value={profile.gpa} onChange={(event) => setProfile({ ...profile, gpa: event.target.value })} /><select value={profile.gpaScale} onChange={(event) => setProfile({ ...profile, gpaScale: event.target.value })}><option value="100">/ 100</option><option value="4">/ 4.0</option><option value="5">/ 5.0</option></select></div></label>
            </> : <>
              <label>目标学位<select value={profile.targetDegree} onChange={(event) => setProfile({ ...profile, targetDegree: event.target.value })}>{degreeLevels.map((level) => <option key={level}>{level}</option>)}</select></label>
              <label>目标方向<select value={profile.target} onChange={(event) => setProfile({ ...profile, target: event.target.value })}>{studyAreas.map((area) => <option key={area}>{area}</option>)}</select></label>
              <label>计划入学<select value={profile.intake} onChange={(event) => setProfile({ ...profile, intake: event.target.value })}><option>2027 S1</option><option>2027 S2</option></select></label>
              <label>语言成绩<input value={profile.english} onChange={(event) => setProfile({ ...profile, english: event.target.value })} placeholder="例如 IELTS 6.5（单项 6.0）" /></label>
              <label>年度预算（万元人民币）<input inputMode="numeric" value={profile.annualBudget} onChange={(event) => setProfile({ ...profile, annualBudget: event.target.value })} placeholder="例如 45" /></label>
              <label className="full">核心课程与技能<textarea value={profile.coursework} onChange={(event) => setProfile({ ...profile, coursework: event.target.value })} placeholder="例如高等数学、线性代数、概率统计、数据结构、数据库、Python" /></label>
              <label className="full">实习、科研与项目经历<textarea value={profile.experience} onChange={(event) => setProfile({ ...profile, experience: event.target.value })} /></label>
              <label>职业目标<input value={profile.careerGoal} onChange={(event) => setProfile({ ...profile, careerGoal: event.target.value })} placeholder="例如 AI 应用工程师" /></label>
              <label>城市偏好<input value={profile.cityPreference} onChange={(event) => setProfile({ ...profile, cityPreference: event.target.value })} placeholder="例如悉尼、墨尔本优先" /></label>
            </>}
          </div>{error && <p className="form-error">{error}</p>}<div className="form-footer"><button type="button" className="text-button" onClick={() => profileStep === 1 ? setView("landing") : setProfileStep(1)}>{profileStep === 1 ? "返回主界面" : "上一步"}</button><button className="primary-button" type="submit">{profileStep === 1 ? "下一步" : "生成选校方案"} <span>→</span></button></div></form>
        </section>
      )}

      {view === "agent" && (
        <section className="agent-run-page">
          <div className="agent-run-heading"><p className="eyebrow"><span /> 正在规划</p><h1>正在生成你的申请方案</h1><p>{profile.school} · {profile.major} · GPA {profile.gpa}/{profile.gpaScale}</p></div>
          <div className="agent-console" aria-live="polite">
            <div className="console-top"><span>后端工具执行记录</span><em>{agentRun ? `${agentRun.tool_trace.length} 步已返回` : "正在请求"}</em></div>
            {!agentRun
              ? <div className="agent-step active"><span className="step-status">…</span><div><strong>运行确定性申请工具</strong><p>正在读取档案并等待后端返回真实执行状态。</p></div><small>进行中</small></div>
              : agentRun.tool_trace.map((trace) => {
                const meta = agentSteps.find((item) => item.tool === trace.tool);
                const label = meta?.label ?? trace.tool;
                const statusLabel = trace.status === "completed" ? "完成" : trace.status === "needs_input" ? "待补信息" : trace.status === "skipped" ? "已跳过" : "失败";
                const icon = trace.status === "completed" ? "✓" : trace.status === "needs_input" ? "!" : trace.status === "skipped" ? "–" : "×";
                return <div className={`agent-step ${trace.status === "completed" ? "done" : trace.status.replace("_", "-")}`} key={`${trace.step}-${trace.tool}`}><span className="step-status">{icon}</span><div><strong>{label}</strong><p>{trace.summary}</p></div><small>{statusLabel}</small></div>;
              })}
          </div>
          <p className="agent-footnote">结果会区分最低申请要求与竞争力建议；最终录取仍以学校正式审核为准。</p>
        </section>
      )}

      {view === "advisor" && (
        <section className="advisor-page">
          <div className="advisor-heading">
            <div><p className="eyebrow"><span /> AI 申请顾问</p><h1>把问题变成下一步行动</h1><p>顾问会读取你的档案、调用选校与任务工具，并保留每一步执行记录。</p></div>
            <span className="advisor-status"><i />{advisorProvider}</span>
          </div>
          <div className="advisor-layout">
            <article className="advisor-chat">
              <div className="chat-context"><span>{profile.targetDegree}</span><span>{profile.target}</span><span>{profile.intake}</span><span>成绩 {profile.gpa}/{profile.gpaScale}</span></div>
              <div className="message-list" aria-live="polite">
                {(advisorThread?.messages ?? []).map((message) => <div key={message.id} className={`chat-message ${message.role}`}>
                  <small>{message.role === "assistant" ? "OfferPilot 顾问" : "你"}</small>
                  <p>{message.content}</p>
                  {message.actions.length > 0 && <div className="tool-actions">{message.actions.map((action, index) => {
                    const status = advisorActionStatusMeta[action.status];
                    return <span className={`tool-action-${action.status.replace("_", "-")}`} key={`${action.tool}-${index}`}><b aria-hidden="true">{status.icon}</b><em>{status.label}</em>{action.summary}</span>;
                  })}</div>}
                </div>)}
                {!advisorThread && <div className="chat-loading">正在读取你的申请档案并建立顾问会话…</div>}
                {advisorBusy && advisorThread && <div className="chat-loading">顾问正在分析，并调用申请工具…</div>}
              </div>
              <div className="quick-prompts">{["UQ 数据科学的雅思和数学先修要求", "帮我重新评估选校组合", "我更想去悉尼，预算每年 50 万", "提醒我准备英文成绩单"].map((prompt) => <button key={prompt} onClick={() => setAdvisorInput(prompt)}>{prompt}</button>)}</div>
              <form className="advisor-composer" onSubmit={handleAdvisorMessage}>
                <textarea value={advisorInput} onChange={(event) => setAdvisorInput(event.target.value)} placeholder="例如：我想把入学时间改到 2027 S2，哪些项目需要重新考虑？" />
                <button className="primary-button" disabled={!advisorThread || advisorBusy || !advisorInput.trim()}>发送 <span>→</span></button>
              </form>
            </article>
            <aside className="advisor-tools">
              <div className="profile-snapshot"><p className="step-kicker">当前申请画像</p><h3>{profile.school}</h3><dl><div><dt>专业</dt><dd>{profile.major}</dd></div><div><dt>语言</dt><dd>{profile.english || "待补充"}</dd></div><div><dt>城市</dt><dd>{profile.cityPreference || "不限"}</dd></div><div><dt>资料完整度</dt><dd>{Math.round(readiness)}%</dd></div></dl><button className="text-button" onClick={() => { setProfileStep(1); setView("profile"); }}>修改档案 →</button></div>
              <div className="knowledge-tool"><p className="step-kicker">官方知识库 · RAG</p><h3>检索已核验要求</h3><p>只检索已人工核验的项目事实，每条结果都能回到学校官方页面。</p><textarea value={knowledgeQuery} onChange={(event) => setKnowledgeQuery(event.target.value)} placeholder="例如：UQ 数据科学需要哪些数学课程？" /><button className="outline-button" disabled={knowledgeQuery.trim().length < 2 || knowledgeBusy} onClick={handleKnowledgeSearch}>{knowledgeBusy ? "正在检索…" : "检索官方资料"}</button>{knowledgeHits.length > 0 && <div className="knowledge-results">{knowledgeHits.map((hit) => <article key={hit.chunk_id}><span>{hit.section} · 相关度 {hit.relevance_score.toFixed(1)}</span><strong>{hit.university} · {hit.program_name}</strong><p>{hit.content}</p><a href={hit.source.url} target="_blank" rel="noreferrer">{hit.source.title} ↗</a><small>核验日期 {hit.source.verified_at}{hit.source.version_id ? ` · 版本 ${hit.source.version_id.slice(0, 18)}` : ""}</small></article>)}</div>}</div>
              <div className="transcript-tool"><p className="step-kicker">成绩单课程核验</p><h3>粘贴成绩单文本</h3><p>识别数学、编程、算法与数据库课程，并逐项目检查先修要求。原始文本不会发送给 DeepSeek。</p><textarea value={transcriptText} onChange={(event) => setTranscriptText(event.target.value)} placeholder={"高等数学 88\n数据结构 90\n数据库系统 87"} /><button className="outline-button" disabled={!transcriptText.trim() || advisorBusy} onClick={handleTranscriptAnalysis}>分析课程匹配</button>{transcriptResult && <div className="transcript-result"><strong>{transcriptResult.academic_summary}</strong><span>{transcriptResult.program_matches.filter((item) => item.status === "满足").length} 个项目的已列先修课可初步满足</span>{transcriptResult.warnings.map((warning) => <small key={warning}>! {warning}</small>)}</div>}</div>
              {cloudConsent && <div className="ai-data-setting"><span>云端 AI 数据处理</span><strong>{cloudConsent.accepted ? "已同意 · 最小化脱敏" : "已拒绝 · 使用规则顾问"}</strong><button className="text-button" onClick={() => setShowCloudConsent(true)}>修改选择</button></div>}
            </aside>
          </div>
        </section>
      )}

      {view === "results" && (
        <section className="results-page">
          <div className="results-header"><div><p className="eyebrow"><span /> 个性化选校方案</p><h1>{profile.targetDegree} · {profile.target} · {profile.intake}</h1><p>{profile.school} · {profile.major} · 成绩 {profile.gpa}/{profile.gpaScale}</p><p className="preference-summary">职业目标：{profile.careerGoal || "待补充"} · 城市偏好：{profile.cityPreference || "不限"} · 年度预算：{profile.annualBudget ? `${profile.annualBudget} 万元` : "待补充"}</p></div><div className="header-actions"><button className="outline-button" onClick={() => setView("plan")}>查看行动计划</button><button className="outline-button" onClick={() => { setProfileStep(1); setView("profile"); }}>修改申请背景</button></div></div>
          <div className="insight-banner"><div className="insight-score"><strong>{results.filter((item) => item.eligibility === "满足基础门槛").length}</strong><span>达到公开基线</span></div><div><p className="step-kicker">方案摘要</p><h3>{runSummary.replace("Agent ", "")}</h3><p>优先确认匹配项目；涉及专业背景和先修课程的项目仍需结合正式成绩单判断。</p></div><div className="legend"><span><i className="match" />匹配</span><span><i className="reach" />冲刺</span><span><i className="safe" />稳妥</span></div></div>
          <div className="evidence-overview"><div><span>项目范围</span><strong>{results.length}</strong><small>已核验具体项目</small></div><div><span>推荐组合</span><strong>{results.filter((item) => item.tier !== "暂不推荐").length}</strong><small>值得继续评估</small></div><div><span>语言状态</span><strong>{profile.english ? "已填写" : "待补充"}</strong><small>{profile.english || "补充总分与单项"}</small></div><div><span>资料完整度</span><strong>{Math.round(readiness)}%</strong><small>{readiness >= 85 ? "可进入选校阶段" : "仍有信息需要补充"}</small></div></div>
          <div className="portfolio-summary">
            <div><span>当前申请组合</span><strong>{applyingChoices.length} 个确定申请</strong><small>{primaryChoice ? `首选：${results.find((item) => item.program.slug === primaryChoice.program_slug)?.program.university ?? primaryChoice.program_slug}` : "还没有设置首选项目"}</small></div>
            <p>先把项目放入“确定申请”，再选一个首选。它们会自动生成到行动路线图的学校分支中。</p>
            <button className="outline-button" onClick={() => setView("plan")}>打开路线图 →</button>
          </div>
          <div className="result-toolbar"><div>{(["全部", "匹配", "冲刺", "稳妥", "暂不推荐"] as const).map((tier) => <button key={tier} className={tierFilter === tier ? "active" : ""} onClick={() => setTierFilter(tier)}>{tier}</button>)}</div><span>点击项目查看具体要求和下一步准备</span></div>
          <div className="result-list">{filteredResults.map((recommendation) => {
            const { program, tier, eligibility, risks } = recommendation;
            const presentation = presentationFor(program);
            return (
            <article className="result-card program-result-card" key={program.slug} role="button" tabIndex={0} onClick={() => openProgram(recommendation)} onKeyDown={(event) => { if (event.key === "Enter") openProgram(recommendation); }}>
              <div className="uni-monogram" style={{ background: presentation.accent }}>{presentation.short.slice(0, 2)}</div>
              <div className="uni-main"><div className="uni-title"><div><h3>{program.name}</h3><p>{program.university} · {program.city} · {program.duration}</p></div><span className={`tier tier-${tier}`}>{tier}</span></div><p className="uni-note">{program.source.excerpt}</p><div className="reason-row"><span>✓ {eligibility}</span><span>{profile.cityPreference.includes(program.city) ? "✓ 符合城市偏好" : "○ 城市偏好待权衡"}</span><span className={risks.length ? "warning" : ""}>{risks.length ? `! ${risks[0]}` : "✓ 暂无明显材料缺口"}</span></div><a className="citation-chip" href={program.source.url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>查看项目官方要求 ↗</a><PortfolioControls choice={choiceFor(program.slug)} onChange={(payload) => changePortfolioChoice(program.slug, payload)} /></div>
              <div className="match-score"><strong>{recommendation.match_score}</strong><span>综合匹配度</span><button aria-label={`查看 ${program.name} 详情`}>→</button></div>
            </article>
          );})}{filteredResults.length === 0 && <div className="empty-state"><strong>这个方向已接入官方课程目录</strong><p>目前还没有完成课程级要求核验，因此不会生成可能误导你的录取分档。你可以先浏览八大官方目录，或让 AI 顾问帮你整理需要核验的学校与材料。</p><div className="reason-row">{officialCatalogs.map(([name, url]) => <a className="citation-chip" href={url} target="_blank" rel="noreferrer" key={name}>{name}课程目录 ↗</a>)}</div><button className="primary-button" onClick={() => setView("advisor")}>咨询 AI 申请顾问</button></div>}</div>
          <p className="data-disclaimer">匹配分不是录取概率；最低门槛、名额和课程信息可能变化，最终以项目官网及学校正式审核为准。</p>
        </section>
      )}

      {view === "program" && selected && (() => {
        const program = selected.program;
        const presentation = presentationFor(program);
        const evidencePoints = [
          ...selected.reasons.map((reason, index) => ({ title: index === 0 ? "成绩换算" : index === 1 ? "公开门槛" : "专业背景", detail: reason })),
          { title: "核心课程", detail: program.prerequisites.length ? `重点确认：${program.prerequisites.join("、")}。` : "项目页面暂未列出明确的专业先修课程限制。" },
          { title: "英语要求", detail: `${program.english_requirement}；你的当前情况：${profile.english || "尚未填写语言成绩"}。` },
        ];
        return <section className="school-page"><button className="back-button" onClick={() => setView("results")}>← 返回选校方案</button><div className="school-hero"><div className="uni-monogram large" style={{ background: presentation.accent }}>{presentation.short.slice(0, 2)}</div><div><p>{program.university} · {program.city}</p><h1>{program.name}</h1><span className={`tier tier-${selected.tier}`}>{selected.tier}</span></div><a href={program.source.url} target="_blank" rel="noreferrer" className="outline-button">查看项目官网 ↗</a></div><div className="school-grid"><article className="analysis-card primary-analysis"><p className="step-kicker">申请要求对照</p><h2>为什么归入“{selected.tier}”？</h2><div className="big-score"><strong>{selected.match_score}</strong><span>/ 100 综合匹配度</span></div><ul>{evidencePoints.map((point, index) => <li key={`${point.title}-${index}`}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{point.title}</strong><p>{point.detail}</p></div></li>)}</ul><div className="risk-panel"><strong>需要继续确认</strong>{selected.risks.map((risk) => <p key={risk}>! {risk}</p>)}</div></article><aside><article className="analysis-card application-choice-card"><p className="step-kicker">申请决策</p><h3>把项目放进申请组合</h3><PortfolioControls choice={choiceFor(program.slug)} showDeadline onChange={(payload) => changePortfolioChoice(program.slug, payload)} /></article><article className="analysis-card"><p className="step-kicker">申请前确认</p><h3>建议下一步</h3><p>{selected.next_action}</p><ol className="checklist"><li><span>1</span>确认成绩换算口径</li><li><span>2</span>逐项核对成绩单课程</li><li><span>3</span>确认语言总分与单项</li><li><span>4</span>查看当前开放轮次与截止日期</li></ol></article><article className="source-card"><span>项目要求来源</span><p>{program.source.excerpt}</p><a href={program.source.url} target="_blank" rel="noreferrer">{program.source.title} ↗</a><small>信息更新：{program.source.verified_at}{program.source.version_id ? ` · 版本 ${program.source.version_id.slice(0, 18)}` : ""} · 请以官网最新说明为准</small></article></aside></div></section>;
      })()}

      {view === "plan" && (
        roadmap
          ? <RoadmapView roadmap={roadmap} onBack={() => setView("results")} onUpdateTask={updateRoadmapTask} />
          : <section className="product-page"><div className="product-page-header"><div><p className="eyebrow"><span /> 申请路线图</p><h1>正在生成你的路线图</h1><p>读取申请组合、入学季与已有任务…</p></div><button className="outline-button" onClick={() => setView("results")}>返回选校方案</button></div></section>
      )}

      {view === "feedback" && (
        <section className="product-page">
          <div className="product-page-header"><div><p className="eyebrow"><span /> Beta 反馈</p><h1>帮助我们把产品做得更可靠</h1><p>问题、建议和课程数据错误都会进入运营后台处理。</p></div></div>
          <div className="operations-grid">
            <form className="operations-card" onSubmit={handleFeedback}><p className="step-kicker">提交反馈</p><h3>告诉我们哪里需要改进</h3><label>反馈类型<select value={feedbackCategory} onChange={(event) => setFeedbackCategory(event.target.value as FeedbackItem["category"])}><option>问题</option><option>建议</option><option>数据错误</option><option>其他</option></select></label><label>具体情况<textarea value={feedbackMessage} onChange={(event) => setFeedbackMessage(event.target.value)} placeholder="请描述你当时要完成什么、遇到了什么，以及你期待的结果。" /></label>{authNotice && <p className="form-success">{authNotice}</p>}{error && <p className="form-error">{error}</p>}<button className="primary-button" disabled={isSubmitting || feedbackMessage.trim().length < 3}>提交反馈</button></form>
            <div className="operations-card"><p className="step-kicker">处理记录</p><h3>我的反馈</h3>{myFeedback.length ? <div className="compact-list">{myFeedback.map((item) => <div key={item.id}><span className={`status-chip status-${item.status}`}>{item.status === "new" ? "待处理" : item.status === "reviewing" ? "处理中" : "已解决"}</span><strong>{item.category}</strong><p>{item.message}</p><small>{new Date(item.created_at).toLocaleString("zh-CN")}</small></div>)}</div> : <p className="muted-copy">还没有提交过反馈。</p>}</div>
          </div>
        </section>
      )}

      {view === "account" && currentUser && (
        <section className="product-page">
          <div className="product-page-header"><div><p className="eyebrow"><span /> Account</p><h1>账户与数据</h1><p>管理登录状态，并导出或删除与账户关联的个人数据。</p></div></div>
          <div className="operations-grid">
            <article className="operations-card"><p className="step-kicker">账户信息</p><h3>{currentUser.display_name}</h3><div className="account-details"><div><span>邮箱</span><strong>{currentUser.email}</strong></div><div><span>验证状态</span><strong>{currentUser.email_verified ? "已验证" : "待验证"}</strong></div><div><span>账户角色</span><strong>{currentUser.role === "admin" ? "管理员" : "Beta 用户"}</strong></div><div><span>条款同意记录</span><strong>{currentUser.terms_version ? `版本 ${currentUser.terms_version}` : "历史账户待补录"}</strong></div></div><button className="outline-button" onClick={() => void handleLogout()}>退出当前会话</button></article>
            <article className="operations-card"><p className="step-kicker">个人数据</p><h3>导出或删除</h3><p className="muted-copy">导出文件包括申请档案、方案、顾问会话、任务、反馈和 Agent 审计记录。</p><button className="outline-button" onClick={() => void handleExportData()}>下载我的数据</button><div className="danger-zone"><strong>永久删除账户</strong><p>删除后无法恢复。请输入当前密码确认。</p><input type="password" value={deletePassword} onChange={(event) => setDeletePassword(event.target.value)} placeholder="当前密码" /><button type="button" onClick={() => void handleDeleteAccount()}>永久删除账户</button>{error && <p className="form-error">{error}</p>}</div></article>
          </div>
        </section>
      )}

      {view === "admin" && currentUser?.role === "admin" && (
        <section className="product-page admin-page">
          <div className="product-page-header"><div><p className="eyebrow"><span /> OfferPilot Operations</p><h1>运营后台</h1><p>查看 Beta 用户、产品使用、反馈处理与数据覆盖情况。</p></div><button className="outline-button" onClick={() => { if (token) void Promise.all([fetchAdminStats(token), fetchAdminUsers(token), fetchAdminFeedback(token), fetchAdminProgramSources(token)]).then(([stats, users, feedback, sources]) => { setAdminStats(stats); setAdminUsers(users); setAdminFeedback(feedback); setAdminSources(sources); }); }}>刷新数据</button></div>
          {adminStats ? <div className="admin-metrics"><div><span>注册用户</span><strong>{adminStats.users}</strong><small>{adminStats.verified_users} 已验证</small></div><div><span>活跃会话</span><strong>{adminStats.active_sessions}</strong><small>当前有效</small></div><div><span>选校方案</span><strong>{adminStats.recommendation_runs}</strong><small>{adminStats.advisor_threads} 个顾问会话</small></div><div><span>待处理反馈</span><strong>{adminStats.open_feedback}</strong><small>需要运营跟进</small></div><div><span>目录覆盖</span><strong>{adminStats.catalog_coverage_cells}</strong><small>{adminStats.verified_programs} 个已核验项目</small></div><div><span>今日顾问调用</span><strong>{adminStats.llm_calls_today}</strong><small>平均 {adminStats.llm_average_latency_ms}ms</small></div><div><span>确定性降级率</span><strong>{Math.round(adminStats.llm_fallback_rate * 100)}%</strong><small>{adminStats.llm_input_tokens_today + adminStats.llm_output_tokens_today} tokens</small></div></div> : <div className="empty-state">正在加载运营数据…</div>}
          <div className="admin-sections">
            <article className="operations-card"><p className="step-kicker">用户管理</p><h3>Beta 用户</h3><div className="admin-table">{adminUsers.map((user) => <div className="admin-row" key={user.id}><div><strong>{user.display_name}</strong><span>{user.email}</span></div><span>{user.email_verified ? "邮箱已验证" : "待验证"}</span><span>{user.terms_version ? `条款 ${user.terms_version}` : "条款待补录"}</span><span>{user.role === "admin" ? "管理员" : "用户"}</span><button className="text-button" disabled={user.id === currentUser.id} onClick={() => void changeUserStatus(user.id, user.status === "active" ? "suspended" : "active")}>{user.status === "active" ? "停用" : "恢复"}</button></div>)}</div></article>
            <article className="operations-card"><p className="step-kicker">反馈队列</p><h3>用户反馈</h3><div className="compact-list">{adminFeedback.map((item) => <div key={item.id}><span className={`status-chip status-${item.status}`}>{item.status}</span><strong>{item.category} · {item.user_email}</strong><p>{item.message}</p><select value={item.status} onChange={(event) => void changeFeedbackStatus(item.id, event.target.value as FeedbackItem["status"])}><option value="new">待处理</option><option value="reviewing">处理中</option><option value="resolved">已解决</option></select></div>)}{adminFeedback.length === 0 && <p className="muted-copy">暂无用户反馈。</p>}</div></article>
            <article className="operations-card admin-sources">
              <p className="step-kicker">数据治理</p><h3>项目来源复核</h3>
              <div className="admin-table">{adminSources.map((source) => <div className="admin-row source-row" key={source.source_id}><div><strong>{source.title}</strong><span>{source.source_id} · 上次核验 {source.verified_at}</span><span>版本 {source.published_version_id.slice(0, 18)} · SHA-256 {source.content_hash.slice(0, 12)}{source.pending_versions ? ` · ${source.pending_versions} 个待审核` : ""}</span></div><span className={`status-chip ${source.status === "已核验" ? "status-resolved" : "status-new"}`}>{source.status}</span><span>{source.reason}</span><a className="text-button" href={source.url} target="_blank" rel="noreferrer">官网 ↗</a></div>)}</div>
              {token && <SourceReviewPanel token={token} sources={adminSources} onSourcesChange={setAdminSources} />}
            </article>
          </div>
        </section>
      )}

      {view === "history" && (
        <section className="product-page"><div className="product-page-header"><div><p className="eyebrow"><span /> 我的方案</p><h1>历史选校方案</h1><p>对比不同背景和目标下生成的申请组合</p></div><button className="primary-button" onClick={() => { setProfileStep(1); setView("profile"); }}>新建方案 <span>→</span></button></div>{history.length ? <div className="history-list">{history.map((item) => <button key={item.run_id} onClick={() => void openHistoryRun(item)}><span className="history-date">{new Date(item.created_at).toLocaleDateString("zh-CN")}</span><div><strong>{item.target_field} · {item.intake}</strong><span>{item.summary.replace("Agent ", "")}</span></div><small>{item.recommendation_count} 个项目<br />查看方案 →</small></button>)}</div> : <div className="empty-state"><strong>还没有选校方案</strong><p>完成申请档案后，你的项目组合、风险提示和行动计划会保存在这里。</p><button className="primary-button" onClick={() => { setProfileStep(1); setView("profile"); }}>建立申请档案</button></div>}</section>
      )}
      {showCloudConsent && (
        <div className="consent-overlay" role="presentation">
          <section className="cloud-consent-dialog" role="dialog" aria-modal="true" aria-labelledby="cloud-consent-title">
            <p className="eyebrow"><span /> 云端 AI 数据处理</p>
            <h2 id="cloud-consent-title">是否使用 DeepSeek 顾问？</h2>
            <p>同意后，OfferPilot 会把最少量的脱敏申请上下文发送到 DeepSeek 开放平台，以生成更自然、更专业的回答。</p>
            <ul><li>会发送：学校层级、专业、归一化成绩、目标、选校事实、申请组合、路线图与最近对话</li><li>不会发送：姓名、邮箱、账户 ID、本科学校名称、原始成绩单、密码或认证信息</li><li>所有申请组合和任务修改仍由服务端白名单工具校验</li></ul>
            <p className="consent-note">拒绝不影响其他功能，顾问会立即使用本地确定性规则回答。你之后可以随时修改选择。</p>
            <div className="consent-actions"><button className="outline-button" onClick={() => void decideCloudConsent(false)}>拒绝并使用规则顾问</button><button className="primary-button" onClick={() => void decideCloudConsent(true)}>同意使用 DeepSeek</button></div>
          </section>
        </div>
      )}
    </main>
  );
}
