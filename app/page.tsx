"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  ApiActionItem,
  ApiHistoryItem,
  ApiMode,
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
  experience: string;
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
  { tool: "normalize_gpa", label: "标准化学术成绩", detail: "统一换算至 100 分制" },
  { tool: "retrieve_programs", label: "检索具体项目", detail: "命中 6 个官方项目页面" },
  { tool: "check_hard_constraints", label: "检查硬性门槛", detail: "核验均分、背景、先修课与语言" },
  { tool: "rank_portfolio", label: "生成申请组合", detail: "输出冲刺、匹配、稳妥分层" },
  { tool: "validate_citations", label: "验证来源引用", detail: "6 / 6 条结果绑定官方证据" },
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
  experience: "一段后端开发实习，两个 AI 应用项目",
};

const fallbackActionPlan: ApiActionItem[] = [
  { id: "verify-transcript", title: "核验成绩单先修课程", detail: "补充课程列表，让 Agent 检查数学、算法、编程与数据库先修要求。", priority: "P0", status: "待开始" },
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
  // Agent 只负责组织步骤与解释；硬门槛由透明、可测试的工具函数判断。
  const gpa = normalizeGpa(profile);
  const threshold = profile.schoolTier === "双非" && program.non211MinimumMark ? program.non211MinimumMark : program.minimumMark;
  const cognate = isCognate(profile.major);
  const blocked = program.requiresCognate && !cognate;
  const gap = gpa - threshold;
  const tier: Tier = blocked ? "暂不推荐" : gap >= 12 ? "稳妥" : gap >= 4 ? "匹配" : gap >= -3 ? "冲刺" : "暂不推荐";
  const score = blocked ? Math.max(45, Math.min(72, Math.round(62 + gap / 2))) : Math.max(50, Math.min(96, Math.round(78 + gap)));
  const eligibility = blocked ? "存在门槛缺口" : gap >= 0 ? "满足基础门槛" : "需要人工核验";
  const risks = [
    ...(program.prerequisites.length ? [`需用成绩单核验：${program.prerequisites.join("、")}`] : []),
    ...(!profile.english ? ["语言成绩尚未验证"] : []),
  ];
  return { tier, score, threshold, cognate, eligibility, risks };
}

const tierOrder: Record<Tier, number> = { 匹配: 0, 稳妥: 1, 冲刺: 2, 暂不推荐: 3 };

const navItems: { section: NavSection; label: string }[] = [
  { section: "landing", label: "主界面" },
  { section: "profile", label: "我的背景" },
  { section: "results", label: "Agent 报告" },
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
  const [profile, setProfile] = useState<Profile>(initialProfile);
  const [email, setEmail] = useState("demo@offerpilot.cn");
  const [password, setPassword] = useState("demo1234");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Program | null>(null);
  const [tierFilter, setTierFilter] = useState<"全部" | Tier>("全部");
  const [completedSteps, setCompletedSteps] = useState(0);
  const [token, setToken] = useState<string | null>(null);
  const [apiMode, setApiMode] = useState<ApiMode>("demo-fallback");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [runId, setRunId] = useState("run_demo_82_n211");
  const [runSummary, setRunSummary] = useState("Agent 已完成 6 个项目核验，并为每条推荐绑定官方项目来源。");
  const [actionPlan, setActionPlan] = useState<ApiActionItem[]>(fallbackActionPlan);
  const [history, setHistory] = useState<ApiHistoryItem[]>([]);

  const results = useMemo(
    () => programs.map((program) => ({ program, ...getProgramRecommendation(program, profile) })).sort((a, b) => tierOrder[a.tier] - tierOrder[b.tier] || b.score - a.score),
    [profile],
  );
  const filteredResults = results.filter((item) => tierFilter === "全部" || item.tier === tierFilter);
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
      setApiMode("fastapi");
    } catch {
      setToken(null);
      setApiMode("demo-fallback");
    } finally {
      setIsSubmitting(false);
      setIsAuthenticated(true);
      setView("profile");
    }
  }

  function navigateTo(section: NavSection) {
    setError("");
    setView(isAuthenticated ? section : "login");
  }

  function handleBrandClick() {
    navigateTo("landing");
  }

  function handleProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!profile.school.trim() || !profile.major.trim() || !profile.gpa.trim()) {
      setError("请先补全本科院校、专业和 GPA。");
      return;
    }
    setError("");
    setCompletedSteps(0);
    setRunId(`run_demo_${normalizeGpa(profile)}_${history.length + 1}`);
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
    };
    if (token) {
      try {
        await saveProfile(token, backendProfile);
        const run = await createAgentRun(token);
        setRunId(run.run_id);
        setRunSummary(run.summary);
        setActionPlan(await fetchActionPlan(token, run.run_id));
        setHistory(await fetchHistory(token));
        setApiMode("fastapi");
        return;
      } catch {
        setApiMode("demo-fallback");
      }
    }
    const localRunId = `run_demo_${normalizeGpa(profile)}_${history.length + 1}`;
    setRunId(localRunId);
    setActionPlan(fallbackActionPlan);
    setHistory((items) => [{
      run_id: localRunId,
      created_at: new Date().toISOString(),
      workflow_version: "agent-0.2.0",
      target_field: profile.target,
      intake: profile.intake,
      recommendation_count: programs.length,
      summary: "Demo fallback 完成 6 个项目的确定性工具核验。",
    }, ...items]);
  }

  function openProgram(program: Program) {
    setSelected(program);
    setView("program");
  }

  return (
    <main className="app-shell">
      <header className="site-header">
        <button className="brand" onClick={handleBrandClick} aria-label={isAuthenticated ? "返回主界面" : "返回登录页"}>
          <span className="brand-mark">O</span><span>OfferPilot</span><small>申请规划 Agent</small>
        </button>
        {isAuthenticated && <nav aria-label="主要导航">
          {navItems.map((item) => {
            const active = activeNavSection(view) === item.section;
            return <button key={item.section} className={active ? "active" : ""} aria-current={active ? "page" : undefined} onClick={() => navigateTo(item.section)}>
              <span>{item.label}</span>{active && <small>当前页面</small>}
            </button>;
          })}
        </nav>}
        {isAuthenticated
          ? <button className="account-pill" onClick={() => setView("login")}><span>D</span>体验账户</button>
          : <span className="login-required">请先登录</span>}
      </header>

      {view === "landing" && (
        <section className="landing">
          <div className="hero-copy">
            <p className="eyebrow"><span /> 可验证 RAG · 工具调用 · 官方引用</p>
            <h1>不只推荐学校，<br />还告诉你依据。</h1>
            <p className="hero-subtitle">OfferPilot 会检索具体项目、调用确定性工具检查 GPA 与先修课，再生成带官方来源的申请组合。Agent 负责规划，规则负责守住事实。</p>
            <div className="hero-actions">
              <button className="primary-button" onClick={() => setView("profile")}>运行申请 Agent <span>→</span></button>
              <button className="text-button" onClick={() => setView("results")}>查看完整示例</button>
            </div>
            <div className="trust-row"><div><strong>6</strong><span>个具体项目</span></div><div><strong>5</strong><span>个 Agent 工具</span></div><div><strong>100%</strong><span>官方来源引用</span></div></div>
          </div>
          <div className="hero-visual" aria-label="Agent 运行结果预览">
            <div className="orbit orbit-one" /><div className="orbit orbit-two" />
            <div className="compass-card agent-preview-card">
              <div className="card-top"><span>Agent Run</span><small>已完成</small></div>
              <div className="run-code">{runId}</div>
              {agentSteps.slice(0, 4).map((step, index) => <div className="mini-tool" key={step.tool}><span>0{index + 1}</span><div><strong>{step.label}</strong><small>{step.tool}</small></div><em>✓</em></div>)}
              <div className="next-step"><span>grounded output</span><strong>6 / 6 条推荐已绑定官方项目页</strong></div>
            </div>
            <div className="floating-note note-one"><span>✓</span> 门槛工具已执行</div><div className="floating-note note-two"><span>6</span> 条来源已验证</div>
          </div>
          <div className="go8-strip"><span>当前可核验项目</span>{programs.map((program) => <b key={program.slug}>{program.short}</b>)}</div>
        </section>
      )}

      {view === "login" && (
        <section className="center-stage"><div className="auth-panel">
          <div className="auth-intro"><p className="eyebrow"><span /> Agent Workspace</p><h2>从背景到<br />行动方案</h2><p>体验账户已填好。下一步 Agent 会展示每一个工具调用，而不是只返回一个黑盒答案。</p><blockquote>“LLM 负责理解与解释，确定性工具负责硬门槛。”</blockquote></div>
          <form className="auth-form" onSubmit={handleLogin}><div className="step-kicker">体验登录</div><h3>进入申请工作台</h3><label>邮箱<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label><label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>{error && <p className="form-error">{error}</p>}<button className="primary-button wide" type="submit" disabled={isSubmitting}>{isSubmitting ? "正在连接…" : "登录并填写背景"} <span>→</span></button><p className="fine-print">FastAPI 可用时保存本次会话；在线预览不可用时自动进入明确标注的 Demo fallback。</p></form>
        </div></section>
      )}

      {view === "profile" && (
        <section className="workspace">
          <aside className="side-rail"><p className="step-kicker">Agent 输入</p><h2>建立申请上下文</h2><p>Agent 会把结构化背景传给门槛检查工具。</p><ol><li className="active"><span>1</span><div><strong>学术背景</strong><small>学校、专业与成绩</small></div></li><li className="active"><span>2</span><div><strong>申请目标</strong><small>方向与入学时间</small></div></li><li><span>3</span><div><strong>Agent 执行</strong><small>检索、核验与排序</small></div></li></ol><div className="privacy-note"><span>◇</span><p><strong>可解释决策</strong><br />硬门槛不会交给模型猜测。</p></div></aside>
          <form className="profile-form" onSubmit={handleProfile}><div className="form-heading"><div><p>结构化输入</p><h2>你的学术与申请背景</h2></div><span>已填入示例数据</span></div><div className="progress"><i /></div><div className="form-grid">
            <label className="full">本科院校名称 *<input value={profile.school} onChange={(event) => setProfile({ ...profile, school: event.target.value })} /></label>
            <label>院校背景<select value={profile.schoolTier} onChange={(event) => setProfile({ ...profile, schoolTier: event.target.value })}><option>985</option><option>211/双一流</option><option>双非</option><option>海外重点</option><option>其他</option></select></label>
            <label>本科专业 *<input value={profile.major} onChange={(event) => setProfile({ ...profile, major: event.target.value })} /></label>
            <label>GPA *<div className="joined-input"><input value={profile.gpa} onChange={(event) => setProfile({ ...profile, gpa: event.target.value })} /><select value={profile.gpaScale} onChange={(event) => setProfile({ ...profile, gpaScale: event.target.value })}><option value="100">/ 100</option><option value="4">/ 4.0</option><option value="5">/ 5.0</option></select></div></label>
            <label>目标方向<select value={profile.target} onChange={(event) => setProfile({ ...profile, target: event.target.value })}><option>计算机与数据</option></select></label>
            <label>计划入学<select value={profile.intake} onChange={(event) => setProfile({ ...profile, intake: event.target.value })}><option>2027 S1</option><option>2027 S2</option></select></label>
            <label>语言成绩<input value={profile.english} onChange={(event) => setProfile({ ...profile, english: event.target.value })} placeholder="例如 IELTS 6.5" /></label>
            <label className="full">相关经历<textarea value={profile.experience} onChange={(event) => setProfile({ ...profile, experience: event.target.value })} /></label>
          </div>{error && <p className="form-error">{error}</p>}<div className="form-footer"><button type="button" className="text-button" onClick={() => setView("landing")}>返回首页</button><button className="primary-button" type="submit">启动 Agent <span>→</span></button></div></form>
        </section>
      )}

      {view === "agent" && (
        <section className="agent-run-page">
          <div className="agent-run-heading"><p className="eyebrow"><span /> live agent trace</p><h1>正在生成可验证的申请方案</h1><p>{profile.school} · {profile.major} · GPA {profile.gpa}/{profile.gpaScale}</p></div>
          <div className="agent-console" aria-live="polite"><div className="console-top"><span>{runId}</span><em>{completedSteps === agentSteps.length ? "completed" : "running"}</em></div>{agentSteps.map((step, index) => { const done = index < completedSteps; const active = index === completedSteps; return <div className={`agent-step ${done ? "done" : ""} ${active ? "active" : ""}`} key={step.tool}><span className="step-status">{done ? "✓" : active ? "…" : index + 1}</span><div><strong>{step.label}</strong><code>{step.tool}</code><p>{step.detail}</p></div><small>{done ? "COMPLETED" : active ? "RUNNING" : "QUEUED"}</small></div>; })}</div>
          <p className="agent-footnote">推荐结论不会使用模型生成的“录取概率”；每条硬门槛都由可测试工具判断。</p>
        </section>
      )}

      {view === "results" && (
        <section className="results-page">
          <div className="results-header"><div><p className="eyebrow"><span /> grounded agent report</p><h1>{profile.target} · {profile.intake}</h1><p>{profile.school} · {profile.major} · GPA {profile.gpa}/{profile.gpaScale} · {runId}</p></div><div className="header-actions"><button className="outline-button" onClick={() => setView("plan")}>行动计划</button><button className="outline-button" onClick={() => setView("profile")}>重新运行</button></div></div>
          <div className="mode-banner"><strong>{apiMode === "fastapi" ? "FastAPI connected" : "Demo fallback"}</strong><span>{apiMode === "fastapi" ? "本次资料与 Run 已通过后端接口保存。" : "当前在线演示使用同规则本地计算；刷新页面会清空记录。"}</span></div>
          <div className="insight-banner"><div className="insight-score"><strong>{results.filter((item) => item.eligibility === "满足基础门槛").length}</strong><span>满足基础门槛</span></div><div><p className="step-kicker">Agent 总结</p><h3>{runSummary}</h3><p>优先查看匹配项目；含先修课的项目仍需上传成绩单进行二次验证。</p></div><div className="legend"><span><i className="match" />匹配</span><span><i className="reach" />冲刺</span><span><i className="safe" />稳妥</span></div></div>
          <div className="evidence-overview"><div><span>工具调用</span><strong>5 / 5</strong><small>全部成功</small></div><div><span>来源覆盖</span><strong>6 / 6</strong><small>官方项目页</small></div><div><span>决策策略</span><strong>Hybrid</strong><small>Agent + Rules</small></div><div><span>待补信息</span><strong>1</strong><small>成绩单课程列表</small></div></div>
          <div className="result-toolbar"><div>{(["全部", "匹配", "冲刺", "稳妥", "暂不推荐"] as const).map((tier) => <button key={tier} className={tierFilter === tier ? "active" : ""} onClick={() => setTierFilter(tier)}>{tier}</button>)}</div><span>项目级推荐 · Agent workflow v0.2</span></div>
          <div className="result-list">{filteredResults.map(({ program, tier, score, eligibility, risks }) => <article className="result-card program-result-card" key={program.slug} role="button" tabIndex={0} onClick={() => openProgram(program)} onKeyDown={(event) => { if (event.key === "Enter") openProgram(program); }}><div className="uni-monogram" style={{ background: program.accent }}>{program.short.slice(0, 2)}</div><div className="uni-main"><div className="uni-title"><div><h3>{program.name}</h3><p>{program.university} · {program.city} · {program.duration}</p></div><span className={`tier tier-${tier}`}>{tier}</span></div><p className="uni-note">{program.source.excerpt}</p><div className="reason-row"><span>✓ {eligibility}</span><span>✓ GPA 工具已核验</span><span className={risks.length ? "warning" : ""}>{risks.length ? `! ${risks[0]}` : "✓ 未发现显式缺口"}</span></div><a className="citation-chip" href={program.source.url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>[{program.source.id}] 官方来源 ↗</a></div><div className="match-score"><strong>{score}</strong><span>匹配分</span><button aria-label={`查看 ${program.name} 详情`}>→</button></div></article>)}</div>
          <p className="data-disclaimer">匹配分不是录取概率；最低门槛、名额和课程信息可能变化，最终以项目官网及学校正式审核为准。</p>
        </section>
      )}

      {view === "program" && selected && (() => {
        const recommendation = getProgramRecommendation(selected, profile);
        return <section className="school-page"><button className="back-button" onClick={() => setView("results")}>← 返回 Agent 报告</button><div className="school-hero"><div className="uni-monogram large" style={{ background: selected.accent }}>{selected.short.slice(0, 2)}</div><div><p>{selected.university} · {selected.city}</p><h1>{selected.name}</h1><span className={`tier tier-${recommendation.tier}`}>{recommendation.tier}</span></div><a href={selected.source.url} target="_blank" rel="noreferrer" className="outline-button">打开官方项目页 ↗</a></div><div className="school-grid"><article className="analysis-card primary-analysis"><p className="step-kicker">工具核验结果</p><h2>为什么 Agent 给出“{recommendation.tier}”？</h2><div className="big-score"><strong>{recommendation.score}</strong><span>/ 100 匹配分</span></div><ul><li><span>01</span><div><strong>学术成绩</strong><p>标准化 GPA {normalizeGpa(profile)}/100；当前使用的公开基线为 {recommendation.threshold}% 。</p></div></li><li><span>02</span><div><strong>专业背景</strong><p>“{profile.major}”被工具识别为{recommendation.cognate ? "相关" : "非相关或待核验"}背景。</p></div></li><li><span>03</span><div><strong>先修课与语言</strong><p>{selected.prerequisites.length ? selected.prerequisites.join("、") : "未发现课程页中的显式专业先修限制"}；{selected.english}。</p></div></li></ul></article><aside><article className="analysis-card"><p className="step-kicker">下一步行动</p><h3>补全证据链</h3><ol className="checklist"><li><span>1</span>上传成绩单课程列表</li><li><span>2</span>核验国际学历换算</li><li><span>3</span>确认语言小分</li><li><span>4</span>检查当前申请轮次</li></ol></article><article className="source-card"><span>引用证据 · {selected.source.id}</span><p>{selected.source.excerpt}</p><a href={selected.source.url} target="_blank" rel="noreferrer">{selected.source.title} ↗</a><small>最近核验：2026-07-14</small></article></aside></div></section>;
      })()}

      {view === "plan" && (
        <section className="product-page"><div className="product-page-header"><div><p className="eyebrow"><span /> application roadmap</p><h1>你的申请行动计划</h1><p>基于 {runId} · 按影响与依赖关系排序</p></div><button className="outline-button" onClick={() => setView("results")}>返回报告</button></div><div className="plan-list">{actionPlan.map((item) => <article className="plan-item" key={item.id}><span className={`priority priority-${item.priority}`}>{item.priority}</span><div><h3>{item.title}</h3><p>{item.detail}</p></div><em>{item.status}</em></article>)}</div><div className="mode-banner"><strong>下一步</strong><span>先完成两个 P0 任务，再确认最终申请组合。</span></div></section>
      )}

      {view === "history" && (
        <section className="product-page"><div className="product-page-header"><div><p className="eyebrow"><span /> recommendation history</p><h1>历史 Agent Runs</h1><p>{apiMode === "fastapi" ? "来自当前 FastAPI Demo 会话" : "来自当前浏览器 Demo 会话"}</p></div><button className="primary-button" onClick={() => setView("profile")}>新建方案 <span>→</span></button></div>{history.length ? <div className="history-list">{history.map((item) => <button key={item.run_id} onClick={() => { setRunId(item.run_id); setRunSummary(item.summary); setView("results"); }}><code>{item.run_id}</code><div><strong>{item.target_field} · {item.intake}</strong><span>{item.summary}</span></div><small>{item.recommendation_count} 个项目<br />{new Date(item.created_at).toLocaleString("zh-CN")}</small></button>)}</div> : <div className="empty-state"><strong>还没有历史记录</strong><p>运行第一份申请方案后，这里会展示可重新打开的 Agent Run。</p><button className="primary-button" onClick={() => setView("profile")}>填写申请背景</button></div>}</section>
      )}
    </main>
  );
}
