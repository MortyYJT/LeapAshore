"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  ApiActionItem,
  ApiHistoryItem,
  createAgentRun,
  fetchActionPlan,
  fetchHistory,
  loginWithDemoAccount,
  saveProfile,
} from "./api-client";

type View = "landing" | "login" | "profile" | "agent" | "results" | "program" | "plan" | "history";
type Tier = "冲刺" | "匹配" | "稳妥" | "暂不推荐";
type NavSection = "landing" | "profile" | "results" | "plan" | "history";

type Profile = {
  school: string;
  schoolTier: string;
  major: string;
  gpa: string;
  gpaScale: string;
  target: string;
  intake: string;
  english: string;
  coursework: string;
  experience: string;
  careerGoal: string;
  cityPreference: string;
  annualBudget: string;
};

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
  { tool: "retrieve_programs", label: "匹配目标项目", detail: "结合方向与入学时间筛选具体硕士项目" },
  { tool: "check_hard_constraints", label: "评估申请要求", detail: "对照均分、专业背景、先修课程和语言要求" },
  { tool: "rank_portfolio", label: "规划申请组合", detail: "平衡冲刺、匹配和稳妥项目" },
  { tool: "validate_citations", label: "整理风险与材料", detail: "生成待确认事项和申请准备顺序" },
];

const initialProfile: Profile = {
  school: "广东工业大学",
  schoolTier: "双非",
  major: "软件工程",
  gpa: "82",
  gpaScale: "100",
  target: "计算机与数据",
  intake: "2027 S1",
  english: "IELTS 6.5",
  coursework: "高等数学、线性代数、概率统计、数据结构、算法、数据库、Python",
  experience: "一段后端开发实习，两个 AI 应用项目",
  careerGoal: "毕业后从事 AI 应用工程或数据工程",
  cityPreference: "悉尼、墨尔本优先，也接受布里斯班和珀斯",
  annualBudget: "45",
};

const fallbackActionPlan: ApiActionItem[] = [
  { id: "verify-transcript", title: "确认成绩单与先修课程", detail: "整理中英文成绩单，逐项确认数学、算法、编程与数据库课程。", priority: "P0", status: "待开始" },
  { id: "verify-language", title: "确认语言成绩与小分", detail: "对照每个项目的英语要求，记录总分、单项和考试日期。", priority: "P0", status: "进行中" },
  { id: "shortlist", title: "确认最终申请组合", detail: "选择 2 个冲刺、2–3 个匹配和 1 个稳妥项目。", priority: "P1", status: "待开始" },
  { id: "deadlines", title: "建立申请截止日期日历", detail: "记录开放时间、轮次和材料截止日期。", priority: "P1", status: "待开始" },
  { id: "materials", title: "准备申请材料", detail: "整理简历、个人陈述、推荐信和官方成绩单。", priority: "P2", status: "待开始" },
];

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
  { section: "results", label: "选校方案" },
  { section: "plan", label: "行动计划" },
  { section: "history", label: "历史记录" },
];

function activeNavSection(view: View): NavSection | null {
  if (view === "agent" || view === "program") return "results";
  if (view === "login") return null;
  return view;
}

export default function Home() {
  const [view, setView] = useState<View>("login");
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [profileStep, setProfileStep] = useState<1 | 2>(1);
  const [profile, setProfile] = useState<Profile>(initialProfile);
  const [email, setEmail] = useState("demo@offerpilot.cn");
  const [password, setPassword] = useState("demo1234");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Program | null>(null);
  const [tierFilter, setTierFilter] = useState<"全部" | Tier>("全部");
  const [completedSteps, setCompletedSteps] = useState(0);
  const [token, setToken] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [runSummary, setRunSummary] = useState("已完成项目要求对照，并根据你的背景生成申请组合。");
  const [actionPlan, setActionPlan] = useState<ApiActionItem[]>(fallbackActionPlan);
  const [history, setHistory] = useState<ApiHistoryItem[]>([]);

  const results = useMemo(
    () => programs.map((program) => ({ program, ...getProgramRecommendation(program, profile) })).sort((a, b) => tierOrder[a.tier] - tierOrder[b.tier] || b.score - a.score),
    [profile],
  );
  const filteredResults = results.filter((item) => tierFilter === "全部" || item.tier === tierFilter);
  const readiness = [profile.school, profile.major, profile.gpa, profile.english, profile.coursework, profile.experience, profile.careerGoal, profile.annualBudget]
    .filter((value) => value.trim()).length * 12.5;
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

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email.includes("@") || password.length < 6) {
      setError("请输入有效邮箱，密码至少 6 位。");
      return;
    }
    setError("");
    setIsSubmitting(true);
    try {
      const accessToken = await loginWithDemoAccount(email, password);
      setToken(accessToken);
    } catch {
      setToken(null);
    } finally {
      setIsSubmitting(false);
      setIsAuthenticated(true);
      setView("profile");
    }
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
      setError("请先补全本科院校、专业和 GPA。");
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
    const backendProfile = {
      undergraduate_school: profile.school,
      school_tier: profile.schoolTier,
      undergraduate_major: profile.major,
      gpa: Number(profile.gpa),
      gpa_scale: Number(profile.gpaScale),
      target_field: profile.target,
      intake: profile.intake,
      english_score: profile.english || null,
      experience_summary: profile.experience || null,
      coursework_summary: profile.coursework || null,
      career_goal: profile.careerGoal || null,
      location_preferences: profile.cityPreference || null,
      annual_budget_aud: profile.annualBudget ? Number(profile.annualBudget) * 10000 : null,
    };
    if (token) {
      try {
        await saveProfile(token, backendProfile);
        const run = await createAgentRun(token);
        setRunSummary(run.summary);
        setActionPlan(await fetchActionPlan(token, run.run_id));
        setHistory(await fetchHistory(token));
        return;
      } catch {
      }
    }
    const localRunId = `run_demo_${normalizeGpa(profile)}_${history.length + 1}`;
    setActionPlan(fallbackActionPlan);
    setHistory((items) => [{
      run_id: localRunId,
      created_at: new Date().toISOString(),
      workflow_version: "agent-0.2.0",
      target_field: profile.target,
      intake: profile.intake,
      recommendation_count: programs.length,
      summary: "已完成 6 个项目的申请要求对照，并生成建议组合。",
    }, ...items]);
  }

  function openProgram(program: Program) {
    setSelected(program);
    setView("program");
  }

  function togglePlanItem(itemId: string) {
    const nextStatus = { 待开始: "进行中", 进行中: "已完成", 已完成: "待开始" } as const;
    setActionPlan((items) => items.map((item) => item.id === itemId ? { ...item, status: nextStatus[item.status] } : item));
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
        </nav>}
        {isAuthenticated
          ? <button className="account-pill" onClick={() => setView("login")}><span>{email.slice(0, 1).toUpperCase()}</span>我的账户</button>
          : <span className="login-required">请先登录</span>}
      </header>

      {view === "landing" && (
        <section className="landing">
          <div className="hero-copy">
            <p className="eyebrow"><span /> 澳洲硕士 · 个性化选校 · 申请规划</p>
            <h1>从你的背景出发，<br />规划每一步申请。</h1>
            <p className="hero-subtitle">填写学术背景、目标方向和申请偏好，获得具体项目建议、要求对照、风险提示与按优先级整理的材料计划。</p>
            <div className="hero-actions">
              <button className="primary-button" onClick={() => { setProfileStep(1); setView("profile"); }}>开始申请规划 <span>→</span></button>
              <button className="text-button" onClick={() => setView("results")}>查看选校示例</button>
            </div>
            <div className="trust-row"><div><strong>6</strong><span>个首批硕士项目</span></div><div><strong>4</strong><span>类申请要求对照</span></div><div><strong>1</strong><span>份线性行动计划</span></div></div>
          </div>
          <div className="hero-visual" aria-label="申请方案预览">
            <div className="orbit orbit-one" /><div className="orbit orbit-two" />
            <div className="compass-card agent-preview-card">
              <div className="card-top"><span>你的申请方案</span><small>已生成</small></div>
              {agentSteps.slice(0, 4).map((step, index) => <div className="mini-tool" key={step.tool}><span>0{index + 1}</span><div><strong>{step.label}</strong><small>{step.detail}</small></div><em>✓</em></div>)}
              <div className="next-step"><span>下一步</span><strong>确认先修课程并建立申请时间表</strong></div>
            </div>
            <div className="floating-note note-one"><span>✓</span> 学术背景已评估</div><div className="floating-note note-two"><span>6</span> 个项目已对照</div>
          </div>
          <div className="go8-strip"><span>首批覆盖项目</span>{programs.map((program) => <b key={program.slug}>{program.short}</b>)}</div>
        </section>
      )}

      {view === "login" && (
        <section className="center-stage"><div className="auth-panel">
          <div className="auth-intro"><p className="eyebrow"><span /> OfferPilot</p><h2>把复杂申请，<br />拆成清晰步骤</h2><p>保存你的申请背景、选校方案和材料进度，随时回来继续推进。</p><blockquote>先确认要求，再确定组合；先补关键缺口，再投入申请材料。</blockquote></div>
          <form className="auth-form" onSubmit={handleLogin}><div className="step-kicker">账户登录</div><h3>继续你的申请规划</h3><label>邮箱<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label><label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>{error && <p className="form-error">{error}</p>}<button className="primary-button wide" type="submit" disabled={isSubmitting}>{isSubmitting ? "正在登录…" : "登录"} <span>→</span></button><p className="fine-print">你的资料仅用于生成和保存申请规划。</p></form>
        </div></section>
      )}

      {view === "profile" && (
        <section className="workspace">
          <aside className="side-rail"><p className="step-kicker">申请档案</p><h2>建立你的申请画像</h2><p>信息越完整，项目要求对照和后续材料建议越准确。</p><ol><li className="active"><span>{profileStep > 1 ? "✓" : "1"}</span><div><strong>学术背景</strong><small>学校、专业与成绩</small></div></li><li className={profileStep === 2 ? "active" : ""}><span>2</span><div><strong>目标与偏好</strong><small>方向、课程、预算与职业目标</small></div></li><li><span>3</span><div><strong>生成选校方案</strong><small>要求对照、组合与行动计划</small></div></li></ol><div className="privacy-note"><span>{Math.round(readiness)}%</span><p><strong>资料完整度</strong><br />建议补全语言、课程和职业目标。</p></div></aside>
          <form className="profile-form" onSubmit={handleProfile}><div className="form-heading"><div><p>步骤 {profileStep} / 2</p><h2>{profileStep === 1 ? "学术背景" : "申请目标与个人偏好"}</h2></div><span>{Math.round(readiness)}% 已完成</span></div><div className="progress"><i style={{ width: profileStep === 1 ? "50%" : "100%" }} /></div><div className="form-grid">
            {profileStep === 1 ? <>
              <label className="full">本科院校名称 *<input value={profile.school} onChange={(event) => setProfile({ ...profile, school: event.target.value })} /></label>
              <label>院校背景<select value={profile.schoolTier} onChange={(event) => setProfile({ ...profile, schoolTier: event.target.value })}><option>985</option><option>211/双一流</option><option>双非</option><option>海外重点</option><option>其他</option></select></label>
              <label>本科专业 *<input value={profile.major} onChange={(event) => setProfile({ ...profile, major: event.target.value })} /></label>
              <label>GPA *<div className="joined-input"><input value={profile.gpa} onChange={(event) => setProfile({ ...profile, gpa: event.target.value })} /><select value={profile.gpaScale} onChange={(event) => setProfile({ ...profile, gpaScale: event.target.value })}><option value="100">/ 100</option><option value="4">/ 4.0</option><option value="5">/ 5.0</option></select></div></label>
            </> : <>
              <label>目标方向<select value={profile.target} onChange={(event) => setProfile({ ...profile, target: event.target.value })}><option>计算机与数据</option></select></label>
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

      {view === "results" && (
        <section className="results-page">
          <div className="results-header"><div><p className="eyebrow"><span /> 个性化选校方案</p><h1>{profile.target} · {profile.intake}</h1><p>{profile.school} · {profile.major} · GPA {profile.gpa}/{profile.gpaScale}</p><p className="preference-summary">职业目标：{profile.careerGoal || "待补充"} · 城市偏好：{profile.cityPreference || "不限"} · 年度预算：{profile.annualBudget ? `${profile.annualBudget} 万元` : "待补充"}</p></div><div className="header-actions"><button className="outline-button" onClick={() => setView("plan")}>查看行动计划</button><button className="outline-button" onClick={() => { setProfileStep(1); setView("profile"); }}>修改申请背景</button></div></div>
          <div className="insight-banner"><div className="insight-score"><strong>{results.filter((item) => item.eligibility === "满足基础门槛").length}</strong><span>达到公开基线</span></div><div><p className="step-kicker">方案摘要</p><h3>{runSummary.replace("Agent ", "")}</h3><p>优先确认匹配项目；涉及专业背景和先修课程的项目仍需结合正式成绩单判断。</p></div><div className="legend"><span><i className="match" />匹配</span><span><i className="reach" />冲刺</span><span><i className="safe" />稳妥</span></div></div>
          <div className="evidence-overview"><div><span>项目范围</span><strong>{results.length}</strong><small>具体硕士项目</small></div><div><span>推荐组合</span><strong>{results.filter((item) => item.tier !== "暂不推荐").length}</strong><small>值得继续评估</small></div><div><span>语言状态</span><strong>{profile.english ? "已填写" : "待补充"}</strong><small>{profile.english || "补充总分与单项"}</small></div><div><span>资料完整度</span><strong>{Math.round(readiness)}%</strong><small>{readiness >= 85 ? "可进入选校阶段" : "仍有信息需要补充"}</small></div></div>
          <div className="result-toolbar"><div>{(["全部", "匹配", "冲刺", "稳妥", "暂不推荐"] as const).map((tier) => <button key={tier} className={tierFilter === tier ? "active" : ""} onClick={() => setTierFilter(tier)}>{tier}</button>)}</div><span>点击项目查看具体要求和下一步准备</span></div>
          <div className="result-list">{filteredResults.map(({ program, tier, score, eligibility, risks }) => <article className="result-card program-result-card" key={program.slug} role="button" tabIndex={0} onClick={() => openProgram(program)} onKeyDown={(event) => { if (event.key === "Enter") openProgram(program); }}><div className="uni-monogram" style={{ background: program.accent }}>{program.short.slice(0, 2)}</div><div className="uni-main"><div className="uni-title"><div><h3>{program.name}</h3><p>{program.university} · {program.city} · {program.duration}</p></div><span className={`tier tier-${tier}`}>{tier}</span></div><p className="uni-note">{program.source.excerpt}</p><div className="reason-row"><span>✓ {eligibility}</span><span>{profile.cityPreference.includes(program.city) ? "✓ 符合城市偏好" : "○ 城市偏好待权衡"}</span><span className={risks.length ? "warning" : ""}>{risks.length ? `! ${risks[0]}` : "✓ 暂无明显材料缺口"}</span></div><a className="citation-chip" href={program.source.url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>查看项目官方要求 ↗</a></div><div className="match-score"><strong>{score}</strong><span>综合匹配度</span><button aria-label={`查看 ${program.name} 详情`}>→</button></div></article>)}</div>
          <p className="data-disclaimer">匹配分不是录取概率；最低门槛、名额和课程信息可能变化，最终以项目官网及学校正式审核为准。</p>
        </section>
      )}

      {view === "program" && selected && (() => {
        const recommendation = getProgramRecommendation(selected, profile);
        return <section className="school-page"><button className="back-button" onClick={() => setView("results")}>← 返回选校方案</button><div className="school-hero"><div className="uni-monogram large" style={{ background: selected.accent }}>{selected.short.slice(0, 2)}</div><div><p>{selected.university} · {selected.city}</p><h1>{selected.name}</h1><span className={`tier tier-${recommendation.tier}`}>{recommendation.tier}</span></div><a href={selected.source.url} target="_blank" rel="noreferrer" className="outline-button">查看项目官网 ↗</a></div><div className="school-grid"><article className="analysis-card primary-analysis"><p className="step-kicker">申请要求对照</p><h2>为什么归入“{recommendation.tier}”？</h2><div className="big-score"><strong>{recommendation.score}</strong><span>/ 100 综合匹配度</span></div><ul><li><span>01</span><div><strong>学术成绩</strong><p>你的成绩换算为 {normalizeGpa(profile)}/100；当前项目公开成绩基线按 {recommendation.threshold}% 评估。</p></div></li><li><span>02</span><div><strong>专业背景</strong><p>你的“{profile.major}”背景初步判断为{recommendation.cognate ? "相关" : "非相关或需要进一步确认"}；正式结果需要结合完整成绩单。</p></div></li><li><span>03</span><div><strong>核心课程</strong><p>{selected.prerequisites.length ? `重点确认：${selected.prerequisites.join("、")}。你填写的课程包括：${profile.coursework || "尚未填写"}。` : "项目页面暂未列出明确的专业先修课程限制。"}</p></div></li><li><span>04</span><div><strong>英语要求</strong><p>{selected.english}；你的当前情况：{profile.english || "尚未填写语言成绩"}。</p></div></li></ul></article><aside><article className="analysis-card"><p className="step-kicker">申请前确认</p><h3>这个项目还需要</h3><ol className="checklist"><li><span>1</span>确认成绩换算口径</li><li><span>2</span>逐项核对成绩单课程</li><li><span>3</span>确认语言总分与单项</li><li><span>4</span>查看当前开放轮次与截止日期</li></ol></article><article className="source-card"><span>项目要求来源</span><p>{selected.source.excerpt}</p><a href={selected.source.url} target="_blank" rel="noreferrer">{selected.source.title} ↗</a><small>信息更新：2026-07-14 · 请以官网最新说明为准</small></article></aside></div></section>;
      })()}

      {view === "plan" && (
        <section className="product-page"><div className="product-page-header"><div><p className="eyebrow"><span /> 申请路线图</p><h1>你的申请行动计划</h1><p>按照申请依赖关系与重要程度排列</p></div><button className="outline-button" onClick={() => setView("results")}>返回选校方案</button></div><div className="plan-guidance"><strong>建议顺序</strong><span>先完成成绩单与语言确认，再锁定项目组合，最后集中准备文书和推荐信。点击任务可更新进度。</span></div><div className="plan-list">{actionPlan.map((item, index) => <button type="button" className="plan-item" key={item.id} onClick={() => togglePlanItem(item.id)}><span className={`priority priority-${item.priority}`}>{index + 1}</span><div><h3>{item.title}</h3><p>{item.detail}</p></div><em>{item.status}</em></button>)}</div></section>
      )}

      {view === "history" && (
        <section className="product-page"><div className="product-page-header"><div><p className="eyebrow"><span /> 我的方案</p><h1>历史选校方案</h1><p>对比不同背景和目标下生成的申请组合</p></div><button className="primary-button" onClick={() => { setProfileStep(1); setView("profile"); }}>新建方案 <span>→</span></button></div>{history.length ? <div className="history-list">{history.map((item) => <button key={item.run_id} onClick={() => { setRunSummary(item.summary); setView("results"); }}><span className="history-date">{new Date(item.created_at).toLocaleDateString("zh-CN")}</span><div><strong>{item.target_field} · {item.intake}</strong><span>{item.summary.replace("Agent ", "")}</span></div><small>{item.recommendation_count} 个项目<br />查看方案 →</small></button>)}</div> : <div className="empty-state"><strong>还没有选校方案</strong><p>完成申请档案后，你的项目组合、风险提示和行动计划会保存在这里。</p><button className="primary-button" onClick={() => { setProfileStep(1); setView("profile"); }}>建立申请档案</button></div>}</section>
      )}
    </main>
  );
}
