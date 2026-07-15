"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  AdvisorThread,
  AdminStats,
  ApiActionItem,
  ApplicationChoice,
  ApplicationRoadmap,
  ApiHistoryItem,
  ApiUser,
  FeedbackItem,
  ProgramSourceStatus,
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
  fetchCurrentUser,
  fetchHistory,
  fetchPortfolio,
  fetchRoadmap,
  fetchMyFeedback,
  loginWithAccount,
  logoutAccount,
  registerAccount,
  requestPasswordReset,
  resendVerification,
  resetPassword,
  saveProfile,
  sendAdvisorMessage,
  updateTaskDetails,
  updatePortfolioChoice,
  updateAdminFeedback,
  updateAdminUser,
  verifyEmail,
} from "./api-client";
import { PortfolioControls } from "./portfolio-controls";
import { RoadmapView } from "./roadmap-view";

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

type Source = {
  id: string;
  title: string;
  url: string;
  excerpt: string;
};

type Program = {
  slug: string;
  short: string;
  university: string;
  name: string;
  city: string;
  accent: string;
  minimumMark: number;
  non211MinimumMark?: number;
  requiresCognate: boolean;
  prerequisites: string[];
  english: string;
  duration: string;
  source: Source;
};

const programs: Program[] = [
  {
    slug: "unsw-master-it", short: "UNSW", university: "新南威尔士大学", name: "Master of Information Technology", city: "悉尼", accent: "#D7A900", minimumMark: 65, non211MinimumMark: 70, requiresCognate: false, prerequisites: [], english: "按 UNSW 英语要求核验", duration: "2 年",
    source: { id: "UNSW-MIT-2026", title: "UNSW Master of Information Technology", url: "https://www.unsw.edu.au/study/postgraduate/master-of-information-technology?studentType=International", excerpt: "相关背景通常要求 65% 均分；非 211 中国院校通常要求 70%，非相关背景可走衔接路径。" },
  },
  {
    slug: "usyd-master-cs", short: "USYD", university: "悉尼大学", name: "Master of Computer Science", city: "悉尼", accent: "#C73B2C", minimumMark: 65, requiresCognate: false, prerequisites: [], english: "按悉尼大学英语要求核验", duration: "2 年",
    source: { id: "USYD-MCS-2026", title: "University of Sydney Master of Computer Science", url: "https://www.sydney.edu.au/content/courses/courses/pc/master-of-computer-science.html", excerpt: "申请人需具有任意学科本科学位并达到 credit average（65%）或同等水平。" },
  },
  {
    slug: "monash-master-ai", short: "MON", university: "蒙纳士大学", name: "Master of Artificial Intelligence", city: "墨尔本", accent: "#1769AA", minimumMark: 60, requiresCognate: false, prerequisites: [], english: "需满足 Monash 英语要求", duration: "1.5–2 年",
    source: { id: "MONASH-MAI-2026", title: "Monash Master of Artificial Intelligence", url: "https://www.monash.edu/study/courses/find-a-course/artificial-intelligence-c6007", excerpt: "2 年路径接受非 IT 本科，通常要求 60% 均分；相关背景可能满足 1.5 年路径。" },
  },
  {
    slug: "monash-master-cs", short: "MON", university: "蒙纳士大学", name: "Master of Computer Science", city: "墨尔本", accent: "#1769AA", minimumMark: 60, requiresCognate: true, prerequisites: ["编程", "算法或数据结构"], english: "需满足 Monash 英语要求", duration: "1.5–2 年",
    source: { id: "MONASH-MCS-2026", title: "Monash Master of Computer Science", url: "https://www.monash.edu/study/courses/find-a-course/computer-science-c6008", excerpt: "不同入学路径取决于既往计算机学习背景，课程页列出对应资格要求。" },
  },
  {
    slug: "uq-master-data-science", short: "UQ", university: "昆士兰大学", name: "Master of Data Science", city: "布里斯班", accent: "#51247A", minimumMark: 71.4, requiresCognate: true, prerequisites: ["微积分或高等数学", "线性代数与统计，或编程与数据库"], english: "IELTS 6.5，单项不低于 6.0", duration: "1.5–2 年",
    source: { id: "UQ-MDS-2027", title: "UQ Master of Data Science", url: "https://study.uq.edu.au/study-options/programs/master-data-science-5660", excerpt: "通常要求 UQ 7 分制 GPA 5.0，并满足相关学科或指定数学、统计及计算机课程要求。" },
  },
  {
    slug: "uwa-master-it", short: "UWA", university: "西澳大学", name: "Master of Information Technology", city: "珀斯", accent: "#12355B", minimumMark: 65, requiresCognate: false, prerequisites: ["Mathematics Methods ATAR 或同等数学基础"], english: "IELTS 6.5，单项不低于 6.0", duration: "1.5–2 年",
    source: { id: "UWA-MIT-2026", title: "UWA Master of Information Technology", url: "https://www.uwa.edu.au/study/courses/master-of-information-technology", excerpt: "通常要求受认可本科学位、至少 65% UWA 等值均分，并具备规定的数学基础。" },
  },
];

const agentSteps = [
  { tool: "normalize_gpa", label: "换算学术成绩", detail: "统一不同学校和满分制的成绩口径" },
  { tool: "retrieve_programs", label: "匹配目标项目", detail: "结合学位、方向与入学时间筛选已核验项目" },
  { tool: "check_hard_constraints", label: "评估申请要求", detail: "对照均分、专业背景、先修课程和语言要求" },
  { tool: "rank_portfolio", label: "规划申请组合", detail: "平衡冲刺、匹配和稳妥项目" },
  { tool: "validate_citations", label: "整理风险与材料", detail: "生成待确认事项和申请准备顺序" },
];

const initialProfile: Profile = {
  currentEducation: "本科",
  school: "广东工业大学",
  schoolTier: "双非",
  major: "软件工程",
  gpa: "82",
  gpaScale: "100",
  targetDegree: "授课型硕士",
  target: "计算机与数据",
  intake: "2027 S1",
  english: "IELTS 6.5",
  coursework: "高等数学、线性代数、概率统计、数据结构、算法、数据库、Python",
  experience: "一段后端开发实习，两个 AI 应用项目",
  careerGoal: "毕业后从事 AI 应用工程或数据工程",
  cityPreference: "悉尼、墨尔本优先，也接受布里斯班和珀斯",
  annualBudget: "45",
};

function profileToApi(profile: Profile): Record<string, unknown> {
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
    annual_budget_aud: profile.annualBudget ? Number(profile.annualBudget) * 10000 : null,
  };
}

function normalizeGpa(profile: Profile): number {
  return Math.min(100, Math.round(((Number(profile.gpa) || 0) / (Number(profile.gpaScale) || 100)) * 100));
}

function isCognate(major: string): boolean {
  return ["计算机", "软件", "信息", "数据", "人工智能", "网络", "电子", "自动化"].some((keyword) => major.includes(keyword));
}

function getProgramRecommendation(program: Program, profile: Profile) {
  // Hard admission constraints remain deterministic even though the UI is user-facing.
  const gpa = normalizeGpa(profile);
  const threshold = profile.schoolTier === "双非" && program.non211MinimumMark ? program.non211MinimumMark : program.minimumMark;
  const cognate = isCognate(profile.major);
  const blocked = program.requiresCognate && !cognate;
  const gap = gpa - threshold;
  const tier: Tier = blocked ? "暂不推荐" : gap >= 12 ? "稳妥" : gap >= 4 ? "匹配" : gap >= -3 ? "冲刺" : "暂不推荐";
  const score = blocked ? Math.max(45, Math.min(72, Math.round(62 + gap / 2))) : Math.max(50, Math.min(96, Math.round(78 + gap)));
  const eligibility = blocked ? "存在门槛缺口" : gap >= 0 ? "满足基础门槛" : "需要人工核验";
  const risks = [
    ...(program.prerequisites.length ? [`需结合成绩单确认：${program.prerequisites.join("、")}`] : []),
    ...(!profile.english ? ["尚未填写语言成绩"] : []),
  ];
  return { tier, score, threshold, cognate, eligibility, risks };
}

const tierOrder: Record<Tier, number> = { 匹配: 0, 稳妥: 1, 冲刺: 2, 暂不推荐: 3 };

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
  const [selected, setSelected] = useState<Program | null>(null);
  const [tierFilter, setTierFilter] = useState<"全部" | Tier>("全部");
  const [completedSteps, setCompletedSteps] = useState(0);
  const [token, setToken] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [runSummary, setRunSummary] = useState("已完成项目要求对照，并根据你的背景生成申请组合。");
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [portfolio, setPortfolio] = useState<ApplicationChoice[]>([]);
  const [roadmap, setRoadmap] = useState<ApplicationRoadmap | null>(null);
  const [history, setHistory] = useState<ApiHistoryItem[]>([]);
  const [advisorThread, setAdvisorThread] = useState<AdvisorThread | null>(null);
  const [advisorInput, setAdvisorInput] = useState("");
  const [advisorBusy, setAdvisorBusy] = useState(false);
  const [advisorProvider, setAdvisorProvider] = useState("正在连接顾问");
  const [transcriptText, setTranscriptText] = useState("");
  const [transcriptResult, setTranscriptResult] = useState<TranscriptAnalysis | null>(null);
  const [feedbackCategory, setFeedbackCategory] = useState<FeedbackItem["category"]>("建议");
  const [feedbackMessage, setFeedbackMessage] = useState("");
  const [myFeedback, setMyFeedback] = useState<FeedbackItem[]>([]);
  const [adminStats, setAdminStats] = useState<AdminStats | null>(null);
  const [adminUsers, setAdminUsers] = useState<ApiUser[]>([]);
  const [adminFeedback, setAdminFeedback] = useState<FeedbackItem[]>([]);
  const [adminSources, setAdminSources] = useState<ProgramSourceStatus[]>([]);
  const [deletePassword, setDeletePassword] = useState("");

  const results = useMemo(
    () => profile.targetDegree === "授课型硕士" && profile.target === "计算机与数据"
      ? programs.map((program) => ({ program, ...getProgramRecommendation(program, profile) })).sort((a, b) => tierOrder[a.tier] - tierOrder[b.tier] || b.score - a.score)
      : [],
    [profile],
  );
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
    fetchCurrentUser()
      .then((user) => {
        setCurrentUser(user);
        setToken("cookie");
        setIsAuthenticated(true);
        setView((current) => current === "login" ? "profile" : current);
      })
      .catch(() => undefined);
  }, []);

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
    if (view !== "agent") return;
    let current = 0;
    const interval = window.setInterval(() => {
      current += 1;
      setCompletedSteps(current);
      if (current === agentSteps.length) {
        window.clearInterval(interval);
        window.setTimeout(() => setView("results"), 700);
      }
    }, 520);
    return () => window.clearInterval(interval);
  }, [view]);

  useEffect(() => {
    if (view !== "advisor" || !token || advisorThread) return;
    let cancelled = false;
    saveProfile(token, profileToApi(profile))
      .then(() => createAdvisorThread(token))
      .then((thread) => { if (!cancelled) setAdvisorThread(thread); })
      .catch(() => { if (!cancelled) setAdvisorProvider("演示模式"); });
    return () => { cancelled = true; };
  }, [view, token, advisorThread, profile]);

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
    setToken(null);
    setCurrentUser(null);
    setIsAuthenticated(false);
    setView("login");
    setAuthMode("login");
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
    setCompletedSteps(0);
    setView("agent");
    void executeAgentRun();
  }

  async function executeAgentRun() {
    const backendProfile = profileToApi(profile);
    if (token) {
      try {
        await saveProfile(token, backendProfile);
        const run = await createAgentRun(token);
        setActiveRunId(run.run_id);
        setRunSummary(run.summary);
        const [nextPortfolio, nextRoadmap] = await Promise.all([
          fetchPortfolio(token, run.run_id), fetchRoadmap(token, run.run_id),
        ]);
        setPortfolio(nextPortfolio);
        setRoadmap(nextRoadmap);
        setHistory(await fetchHistory(token));
        return;
      } catch {
      }
    }
    const localRunId = `run_demo_${normalizeGpa(profile)}_${history.length + 1}`;
    setActiveRunId(localRunId);
    const localSummary = results.length
      ? `已完成 ${results.length} 个${profile.targetDegree}项目的申请要求对照，并生成建议组合。`
      : `已接入${profile.targetDegree} · ${profile.target}的官方目录入口；课程级要求仍在核验中，暂不生成录取分档。`;
    setRunSummary(localSummary);
    setHistory((items) => [{
      run_id: localRunId,
      created_at: new Date().toISOString(),
      workflow_version: "agent-0.4.0",
      target_field: profile.target,
      intake: profile.intake,
      recommendation_count: results.length,
      summary: localSummary,
    }, ...items]);
  }

  function openProgram(program: Program) {
    setSelected(program);
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
      const [choices, nextRoadmap] = await Promise.all([fetchPortfolio(token, item.run_id), fetchRoadmap(token, item.run_id)]);
      setPortfolio(choices);
      setRoadmap(nextRoadmap);
    }
    setView("results");
  }

  async function handleAdvisorMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = advisorInput.trim();
    if (!content || advisorBusy) return;
    setAdvisorInput("");
    setAdvisorBusy(true);
    if (token && advisorThread) {
      try {
        const reply = await sendAdvisorMessage(token, advisorThread.id, content);
        setAdvisorThread(reply.thread);
        setAdvisorProvider(reply.provider === "ollama" ? "Qwen · 服务端" : reply.provider === "openai" ? "OpenAI · 在线" : "安全降级模式");
      } catch {
        setAdvisorProvider("暂时无法连接，请稍后重试");
      }
    }
    setAdvisorBusy(false);
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
          <div className="go8-strip"><span>首批已核验项目</span>{programs.map((program) => <b key={program.slug}>{program.short}</b>)}</div>
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

      {view === "privacy" && <section className="legal-page"><button className="back-button" onClick={() => setView("login")}>← 返回登录</button><p className="eyebrow"><span /> 隐私说明</p><h1>OfferPilot Beta 隐私说明</h1><p>生效日期：2026 年 7 月 15 日</p><h2>收集的信息</h2><p>我们处理账户邮箱、申请背景、成绩与课程描述、目标偏好、顾问对话、任务进度、反馈和必要的安全日志。</p><h2>使用目的</h2><p>这些信息用于身份验证、生成申请规划、保存进度、改进产品、排查故障和防止滥用，不用于出售个人资料。</p><h2>存储与安全</h2><p>密码使用加盐哈希保存；验证、重置和会话令牌以哈希形式保存；生产数据存储在受控 PostgreSQL 中并执行备份。</p><h2>数据权利</h2><p>用户可以在“账户设置”中导出个人数据，或输入当前密码永久删除账户与关联资料；需要更正或帮助时可通过产品内反馈联系运营人员。</p><h2>第三方处理</h2><p>邮件服务商负责投递验证与重置邮件；自托管模型仅在服务端处理必要上下文。上线前会在此处公布实际服务商。</p></section>}

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
          <div className="agent-console" aria-live="polite"><div className="console-top"><span>申请方案进度</span><em>{completedSteps === agentSteps.length ? "已完成" : `${completedSteps} / ${agentSteps.length}`}</em></div>{agentSteps.map((step, index) => { const done = index < completedSteps; const active = index === completedSteps; return <div className={`agent-step ${done ? "done" : ""} ${active ? "active" : ""}`} key={step.tool}><span className="step-status">{done ? "✓" : active ? "…" : index + 1}</span><div><strong>{step.label}</strong><p>{step.detail}</p></div><small>{done ? "完成" : active ? "进行中" : "等待"}</small></div>; })}</div>
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
                  {message.actions.length > 0 && <div className="tool-actions">{message.actions.map((action, index) => <span key={`${action.tool}-${index}`}><b>✓</b>{action.summary}</span>)}</div>}
                </div>)}
                {!advisorThread && <div className="chat-loading">正在读取你的申请档案并建立顾问会话…</div>}
                {advisorBusy && advisorThread && <div className="chat-loading">顾问正在分析，并调用申请工具…</div>}
              </div>
              <div className="quick-prompts">{["帮我重新评估选校组合", "我更想去悉尼，预算每年 50 万", "提醒我准备英文成绩单"].map((prompt) => <button key={prompt} onClick={() => setAdvisorInput(prompt)}>{prompt}</button>)}</div>
              <form className="advisor-composer" onSubmit={handleAdvisorMessage}>
                <textarea value={advisorInput} onChange={(event) => setAdvisorInput(event.target.value)} placeholder="例如：我想把入学时间改到 2027 S2，哪些项目需要重新考虑？" />
                <button className="primary-button" disabled={!advisorThread || advisorBusy || !advisorInput.trim()}>发送 <span>→</span></button>
              </form>
            </article>
            <aside className="advisor-tools">
              <div className="profile-snapshot"><p className="step-kicker">当前申请画像</p><h3>{profile.school}</h3><dl><div><dt>专业</dt><dd>{profile.major}</dd></div><div><dt>语言</dt><dd>{profile.english || "待补充"}</dd></div><div><dt>城市</dt><dd>{profile.cityPreference || "不限"}</dd></div><div><dt>资料完整度</dt><dd>{Math.round(readiness)}%</dd></div></dl><button className="text-button" onClick={() => { setProfileStep(1); setView("profile"); }}>修改档案 →</button></div>
              <div className="transcript-tool"><p className="step-kicker">成绩单课程核验</p><h3>粘贴成绩单文本</h3><p>识别数学、编程、算法与数据库课程，并逐项目检查先修要求。</p><textarea value={transcriptText} onChange={(event) => setTranscriptText(event.target.value)} placeholder={"高等数学 88\n数据结构 90\n数据库系统 87"} /><button className="outline-button" disabled={!transcriptText.trim() || advisorBusy} onClick={handleTranscriptAnalysis}>分析课程匹配</button>{transcriptResult && <div className="transcript-result"><strong>{transcriptResult.academic_summary}</strong><span>{transcriptResult.program_matches.filter((item) => item.status === "满足").length} 个项目的已列先修课可初步满足</span>{transcriptResult.warnings.map((warning) => <small key={warning}>! {warning}</small>)}</div>}</div>
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
            <div><span>当前申请组合</span><strong>{applyingChoices.length} 个确定申请</strong><small>{primaryChoice ? `首选：${programs.find((item) => item.slug === primaryChoice.program_slug)?.university ?? primaryChoice.program_slug}` : "还没有设置首选项目"}</small></div>
            <p>先把项目放入“确定申请”，再选一个首选。它们会自动生成到行动路线图的学校分支中。</p>
            <button className="outline-button" onClick={() => setView("plan")}>打开路线图 →</button>
          </div>
          <div className="result-toolbar"><div>{(["全部", "匹配", "冲刺", "稳妥", "暂不推荐"] as const).map((tier) => <button key={tier} className={tierFilter === tier ? "active" : ""} onClick={() => setTierFilter(tier)}>{tier}</button>)}</div><span>点击项目查看具体要求和下一步准备</span></div>
          <div className="result-list">{filteredResults.map(({ program, tier, score, eligibility, risks }) => (
            <article className="result-card program-result-card" key={program.slug} role="button" tabIndex={0} onClick={() => openProgram(program)} onKeyDown={(event) => { if (event.key === "Enter") openProgram(program); }}>
              <div className="uni-monogram" style={{ background: program.accent }}>{program.short.slice(0, 2)}</div>
              <div className="uni-main"><div className="uni-title"><div><h3>{program.name}</h3><p>{program.university} · {program.city} · {program.duration}</p></div><span className={`tier tier-${tier}`}>{tier}</span></div><p className="uni-note">{program.source.excerpt}</p><div className="reason-row"><span>✓ {eligibility}</span><span>{profile.cityPreference.includes(program.city) ? "✓ 符合城市偏好" : "○ 城市偏好待权衡"}</span><span className={risks.length ? "warning" : ""}>{risks.length ? `! ${risks[0]}` : "✓ 暂无明显材料缺口"}</span></div><a className="citation-chip" href={program.source.url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>查看项目官方要求 ↗</a><PortfolioControls choice={choiceFor(program.slug)} onChange={(payload) => changePortfolioChoice(program.slug, payload)} /></div>
              <div className="match-score"><strong>{score}</strong><span>综合匹配度</span><button aria-label={`查看 ${program.name} 详情`}>→</button></div>
            </article>
          ))}{filteredResults.length === 0 && <div className="empty-state"><strong>这个方向已接入官方课程目录</strong><p>目前还没有完成课程级要求核验，因此不会生成可能误导你的录取分档。你可以先浏览八大官方目录，或让 AI 顾问帮你整理需要核验的学校与材料。</p><div className="reason-row">{officialCatalogs.map(([name, url]) => <a className="citation-chip" href={url} target="_blank" rel="noreferrer" key={name}>{name}课程目录 ↗</a>)}</div><button className="primary-button" onClick={() => setView("advisor")}>咨询 AI 申请顾问</button></div>}</div>
          <p className="data-disclaimer">匹配分不是录取概率；最低门槛、名额和课程信息可能变化，最终以项目官网及学校正式审核为准。</p>
        </section>
      )}

      {view === "program" && selected && (() => {
        const recommendation = getProgramRecommendation(selected, profile);
        return <section className="school-page"><button className="back-button" onClick={() => setView("results")}>← 返回选校方案</button><div className="school-hero"><div className="uni-monogram large" style={{ background: selected.accent }}>{selected.short.slice(0, 2)}</div><div><p>{selected.university} · {selected.city}</p><h1>{selected.name}</h1><span className={`tier tier-${recommendation.tier}`}>{recommendation.tier}</span></div><a href={selected.source.url} target="_blank" rel="noreferrer" className="outline-button">查看项目官网 ↗</a></div><div className="school-grid"><article className="analysis-card primary-analysis"><p className="step-kicker">申请要求对照</p><h2>为什么归入“{recommendation.tier}”？</h2><div className="big-score"><strong>{recommendation.score}</strong><span>/ 100 综合匹配度</span></div><ul><li><span>01</span><div><strong>学术成绩</strong><p>你的成绩换算为 {normalizeGpa(profile)}/100；当前项目公开成绩基线按 {recommendation.threshold}% 评估。</p></div></li><li><span>02</span><div><strong>专业背景</strong><p>你的“{profile.major}”背景初步判断为{recommendation.cognate ? "相关" : "非相关或需要进一步确认"}；正式结果需要结合完整成绩单。</p></div></li><li><span>03</span><div><strong>核心课程</strong><p>{selected.prerequisites.length ? `重点确认：${selected.prerequisites.join("、")}。你填写的课程包括：${profile.coursework || "尚未填写"}。` : "项目页面暂未列出明确的专业先修课程限制。"}</p></div></li><li><span>04</span><div><strong>英语要求</strong><p>{selected.english}；你的当前情况：{profile.english || "尚未填写语言成绩"}。</p></div></li></ul></article><aside><article className="analysis-card application-choice-card"><p className="step-kicker">申请决策</p><h3>把项目放进申请组合</h3><PortfolioControls choice={choiceFor(selected.slug)} showDeadline onChange={(payload) => changePortfolioChoice(selected.slug, payload)} /></article><article className="analysis-card"><p className="step-kicker">申请前确认</p><h3>这个项目还需要</h3><ol className="checklist"><li><span>1</span>确认成绩换算口径</li><li><span>2</span>逐项核对成绩单课程</li><li><span>3</span>确认语言总分与单项</li><li><span>4</span>查看当前开放轮次与截止日期</li></ol></article><article className="source-card"><span>项目要求来源</span><p>{selected.source.excerpt}</p><a href={selected.source.url} target="_blank" rel="noreferrer">{selected.source.title} ↗</a><small>信息更新：2026-07-14 · 请以官网最新说明为准</small></article></aside></div></section>;
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
          {adminStats ? <div className="admin-metrics"><div><span>注册用户</span><strong>{adminStats.users}</strong><small>{adminStats.verified_users} 已验证</small></div><div><span>活跃会话</span><strong>{adminStats.active_sessions}</strong><small>当前有效</small></div><div><span>选校方案</span><strong>{adminStats.recommendation_runs}</strong><small>{adminStats.advisor_threads} 个顾问会话</small></div><div><span>待处理反馈</span><strong>{adminStats.open_feedback}</strong><small>需要运营跟进</small></div><div><span>目录覆盖</span><strong>{adminStats.catalog_coverage_cells}</strong><small>{adminStats.verified_programs} 个已核验项目</small></div></div> : <div className="empty-state">正在加载运营数据…</div>}
          <div className="admin-sections">
            <article className="operations-card"><p className="step-kicker">用户管理</p><h3>Beta 用户</h3><div className="admin-table">{adminUsers.map((user) => <div className="admin-row" key={user.id}><div><strong>{user.display_name}</strong><span>{user.email}</span></div><span>{user.email_verified ? "邮箱已验证" : "待验证"}</span><span>{user.terms_version ? `条款 ${user.terms_version}` : "条款待补录"}</span><span>{user.role === "admin" ? "管理员" : "用户"}</span><button className="text-button" disabled={user.id === currentUser.id} onClick={() => void changeUserStatus(user.id, user.status === "active" ? "suspended" : "active")}>{user.status === "active" ? "停用" : "恢复"}</button></div>)}</div></article>
            <article className="operations-card"><p className="step-kicker">反馈队列</p><h3>用户反馈</h3><div className="compact-list">{adminFeedback.map((item) => <div key={item.id}><span className={`status-chip status-${item.status}`}>{item.status}</span><strong>{item.category} · {item.user_email}</strong><p>{item.message}</p><select value={item.status} onChange={(event) => void changeFeedbackStatus(item.id, event.target.value as FeedbackItem["status"])}><option value="new">待处理</option><option value="reviewing">处理中</option><option value="resolved">已解决</option></select></div>)}{adminFeedback.length === 0 && <p className="muted-copy">暂无用户反馈。</p>}</div></article>
            <article className="operations-card admin-sources"><p className="step-kicker">数据治理</p><h3>项目来源复核</h3><div className="admin-table">{adminSources.map((source) => <div className="admin-row source-row" key={source.source_id}><div><strong>{source.title}</strong><span>{source.source_id} · 上次核验 {source.verified_at}</span></div><span className={`status-chip ${source.status === "已核验" ? "status-resolved" : "status-new"}`}>{source.status}</span><span>{source.reason}</span><a className="text-button" href={source.url} target="_blank" rel="noreferrer">官网 ↗</a></div>)}</div></article>
          </div>
        </section>
      )}

      {view === "history" && (
        <section className="product-page"><div className="product-page-header"><div><p className="eyebrow"><span /> 我的方案</p><h1>历史选校方案</h1><p>对比不同背景和目标下生成的申请组合</p></div><button className="primary-button" onClick={() => { setProfileStep(1); setView("profile"); }}>新建方案 <span>→</span></button></div>{history.length ? <div className="history-list">{history.map((item) => <button key={item.run_id} onClick={() => void openHistoryRun(item)}><span className="history-date">{new Date(item.created_at).toLocaleDateString("zh-CN")}</span><div><strong>{item.target_field} · {item.intake}</strong><span>{item.summary.replace("Agent ", "")}</span></div><small>{item.recommendation_count} 个项目<br />查看方案 →</small></button>)}</div> : <div className="empty-state"><strong>还没有选校方案</strong><p>完成申请档案后，你的项目组合、风险提示和行动计划会保存在这里。</p><button className="primary-button" onClick={() => { setProfileStep(1); setView("profile"); }}>建立申请档案</button></div>}</section>
      )}
    </main>
  );
}
