"use client";

import { FormEvent, useMemo, useState } from "react";

type View = "landing" | "login" | "profile" | "results" | "school";
type Tier = "冲刺" | "匹配" | "稳妥";

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
  city: string;
};

type University = {
  slug: string;
  short: string;
  name: string;
  city: string;
  accent: string;
  fields: string[];
  threshold: number;
  note: string;
  official: string;
};

const universities: University[] = [
  { slug: "unimelb", short: "Melb", name: "墨尔本大学", city: "墨尔本", accent: "#D94C36", fields: ["计算机与数据", "商科与金融", "教育与社会科学"], threshold: 88, note: "研究导向强，热门课程竞争激烈。", official: "https://www.unimelb.edu.au/" },
  { slug: "anu", short: "ANU", name: "澳大利亚国立大学", city: "堪培拉", accent: "#9C6A43", fields: ["计算机与数据", "商科与金融", "工程", "教育与社会科学"], threshold: 87, note: "学术与研究资源突出，适合目标清晰的申请者。", official: "https://www.anu.edu.au/" },
  { slug: "unsw", short: "UNSW", name: "新南威尔士大学", city: "悉尼", accent: "#D7A900", fields: ["计算机与数据", "商科与金融", "工程"], threshold: 85, note: "工程、技术与就业连接紧密。", official: "https://www.unsw.edu.au/" },
  { slug: "usyd", short: "USYD", name: "悉尼大学", city: "悉尼", accent: "#C73B2C", fields: ["计算机与数据", "商科与金融", "工程", "教育与社会科学"], threshold: 85, note: "学科覆盖广，热门方向需要更强的综合背景。", official: "https://www.sydney.edu.au/" },
  { slug: "monash", short: "Monash", name: "蒙纳士大学", city: "墨尔本", accent: "#1769AA", fields: ["计算机与数据", "商科与金融", "工程", "教育与社会科学"], threshold: 82, note: "课程选择丰富，产业合作与实践机会较多。", official: "https://www.monash.edu/" },
  { slug: "uq", short: "UQ", name: "昆士兰大学", city: "布里斯班", accent: "#51247A", fields: ["计算机与数据", "商科与金融", "工程", "生命科学"], threshold: 82, note: "科研实力与校园体验兼具。", official: "https://www.uq.edu.au/" },
  { slug: "uwa", short: "UWA", name: "西澳大学", city: "珀斯", accent: "#12355B", fields: ["计算机与数据", "商科与金融", "工程", "生命科学"], threshold: 78, note: "工程与资源相关方向具有地域优势。", official: "https://www.uwa.edu.au/" },
  { slug: "adelaide", short: "AU", name: "阿德莱德大学", city: "阿德莱德", accent: "#E3552F", fields: ["计算机与数据", "商科与金融", "工程", "教育与社会科学"], threshold: 78, note: "2026 年正式启用的新大学，由原阿德莱德大学与南澳大学整合而成。", official: "https://adelaideuni.edu.au/" },
];

const initialProfile: Profile = {
  school: "",
  schoolTier: "双非",
  major: "",
  gpa: "82",
  gpaScale: "100",
  target: "计算机与数据",
  intake: "2027 S1",
  english: "",
  experience: "",
  city: "不限",
};

function normalizeGpa(profile: Profile) {
  const value = Number(profile.gpa) || 0;
  const scale = Number(profile.gpaScale) || 100;
  return Math.min(100, Math.round((value / scale) * 100));
}

function getRecommendation(university: University, profile: Profile) {
  // Demo 规则刻意保持透明：每个加减分都能在产品说明中解释。
  // 这里输出的是规划用匹配分，不应被理解为录取概率。
  const gpa = normalizeGpa(profile);
  const schoolBonus = ["985", "海外重点"].includes(profile.schoolTier) ? 3 : profile.schoolTier === "211/双一流" ? 2 : 0;
  const fieldBonus = university.fields.includes(profile.target) ? 2 : -4;
  const englishBonus = profile.english.trim() ? 1 : 0;
  const gap = gpa + schoolBonus + fieldBonus + englishBonus - university.threshold;
  const tier: Tier = gap >= 5 ? "稳妥" : gap >= -2 ? "匹配" : "冲刺";
  const score = Math.max(55, Math.min(96, 76 + gap));
  return { tier, score, gap };
}

const tierOrder: Record<Tier, number> = { "匹配": 0, "冲刺": 1, "稳妥": 2 };

export default function Home() {
  const [view, setView] = useState<View>("landing");
  const [profile, setProfile] = useState<Profile>(initialProfile);
  const [email, setEmail] = useState("demo@offerpilot.cn");
  const [password, setPassword] = useState("demo1234");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<University | null>(null);
  const [tierFilter, setTierFilter] = useState<"全部" | Tier>("全部");

  const results = useMemo(() => universities.map((university) => ({ university, ...getRecommendation(university, profile) })), [profile]);
  const filteredResults = results
    .filter((item) => tierFilter === "全部" || item.tier === tierFilter)
    .sort((a, b) => tierOrder[a.tier] - tierOrder[b.tier] || b.score - a.score);

  function handleLogin(event: FormEvent) {
    event.preventDefault();
    if (!email.includes("@") || password.length < 6) {
      setError("请输入有效邮箱，密码至少 6 位。");
      return;
    }
    setError("");
    setView("profile");
  }

  function handleProfile(event: FormEvent) {
    event.preventDefault();
    if (!profile.school.trim() || !profile.major.trim() || !profile.gpa.trim()) {
      setError("请先补全本科院校、专业和 GPA。");
      return;
    }
    setError("");
    setView("results");
  }

  function openSchool(university: University) {
    setSelected(university);
    setView("school");
  }

  return (
    <main className="app-shell">
      <header className="site-header">
        <button className="brand" onClick={() => setView("landing")} aria-label="返回首页">
          <span className="brand-mark">O</span>
          <span>OfferPilot</span>
          <small>留学罗盘</small>
        </button>
        <nav aria-label="主要导航">
          <button onClick={() => setView("landing")}>首页</button>
          <button onClick={() => setView(email ? "profile" : "login")}>我的背景</button>
          <button onClick={() => setView("results")}>选校方案</button>
        </nav>
        <button className="account-pill" onClick={() => setView("login")}>
          <span>{email ? email.slice(0, 1).toUpperCase() : "?"}</span>
          {email ? "体验账户" : "登录"}
        </button>
      </header>

      {view === "landing" && (
        <section className="landing">
          <div className="hero-copy">
            <p className="eyebrow"><span /> 澳洲八大 · 2027 申请规划</p>
            <h1>选校不靠猜，<br />每一步都有依据。</h1>
            <p className="hero-subtitle">输入你的学术背景与目标，获得一份可解释的澳洲八大选校方案——知道哪里值得冲，也知道差距在哪里。</p>
            <div className="hero-actions">
              <button className="primary-button" onClick={() => setView("login")}>免费生成方案 <span>→</span></button>
              <button className="text-button" onClick={() => setView("results")}>先看示例结果</button>
            </div>
            <div className="trust-row">
              <div><strong>8</strong><span>所 Go8 院校</span></div>
              <div><strong>5</strong><span>个匹配维度</span></div>
              <div><strong>100%</strong><span>解释推荐理由</span></div>
            </div>
          </div>
          <div className="hero-visual" aria-label="选校方案预览">
            <div className="orbit orbit-one" />
            <div className="orbit orbit-two" />
            <div className="compass-card">
              <div className="card-top"><span>你的选校罗盘</span><small>已生成</small></div>
              <div className="score-ring"><strong>84</strong><span>综合准备度</span></div>
              <div className="mini-result"><span className="uni-dot gold">U</span><div><strong>昆士兰大学</strong><small>计算机科学硕士</small></div><em>匹配</em></div>
              <div className="mini-result"><span className="uni-dot blue">M</span><div><strong>蒙纳士大学</strong><small>信息技术硕士</small></div><em>匹配</em></div>
              <div className="next-step"><span>下一步</span><strong>补充语言成绩，让推荐更准确</strong></div>
            </div>
            <div className="floating-note note-one"><span>✓</span> 背景已完成 80%</div>
            <div className="floating-note note-two"><span>3</span> 所匹配院校</div>
          </div>
          <div className="go8-strip">
            <span>覆盖澳洲 Group of Eight</span>
            {universities.map((university) => <b key={university.slug}>{university.short}</b>)}
          </div>
        </section>
      )}

      {view === "login" && (
        <section className="center-stage">
          <div className="auth-panel">
            <div className="auth-intro">
              <p className="eyebrow"><span /> 开始你的申请规划</p>
              <h2>欢迎来到<br />OfferPilot</h2>
              <p>Demo 已为你填好体验账户。登录后，用两分钟完成背景信息。</p>
              <blockquote>“推荐不是一个黑盒分数，而是一组你能理解、能行动的判断。”</blockquote>
            </div>
            <form className="auth-form" onSubmit={handleLogin}>
              <div className="step-kicker">体验登录</div>
              <h3>继续你的选校方案</h3>
              <label>邮箱<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
              <label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
              {error && <p className="form-error">{error}</p>}
              <button className="primary-button wide" type="submit">登录并填写背景 <span>→</span></button>
              <p className="fine-print">当前为开源 Demo 登录；正式版本将接入 Supabase Auth。</p>
            </form>
          </div>
        </section>
      )}

      {view === "profile" && (
        <section className="workspace">
          <aside className="side-rail">
            <p className="step-kicker">申请档案</p>
            <h2>让我们认识你</h2>
            <p>信息越完整，推荐越接近你的真实情况。</p>
            <ol>
              <li className="active"><span>1</span><div><strong>学术背景</strong><small>学校、专业与成绩</small></div></li>
              <li><span>2</span><div><strong>申请目标</strong><small>方向与入学时间</small></div></li>
              <li><span>3</span><div><strong>补充经历</strong><small>语言与实践经验</small></div></li>
            </ol>
            <div className="privacy-note"><span>◇</span><p><strong>你的数据属于你</strong><br />Demo 不会上传或保存个人信息。</p></div>
          </aside>
          <form className="profile-form" onSubmit={handleProfile}>
            <div className="form-heading"><div><p>第 1 步，共 3 步</p><h2>你的学术与申请背景</h2></div><span>预计 2 分钟</span></div>
            <div className="progress"><i /></div>
            <div className="form-grid">
              <label className="full">本科院校名称 *<input value={profile.school} onChange={(event) => setProfile({ ...profile, school: event.target.value })} placeholder="例如：广东工业大学" /></label>
              <label>院校背景<select value={profile.schoolTier} onChange={(event) => setProfile({ ...profile, schoolTier: event.target.value })}><option>985</option><option>211/双一流</option><option>双非</option><option>海外重点</option><option>其他</option></select></label>
              <label>本科专业 *<input value={profile.major} onChange={(event) => setProfile({ ...profile, major: event.target.value })} placeholder="例如：软件工程" /></label>
              <label>GPA *<div className="joined-input"><input value={profile.gpa} onChange={(event) => setProfile({ ...profile, gpa: event.target.value })} /><select value={profile.gpaScale} onChange={(event) => setProfile({ ...profile, gpaScale: event.target.value })}><option value="100">/ 100</option><option value="4">/ 4.0</option><option value="5">/ 5.0</option></select></div></label>
              <label>目标方向<select value={profile.target} onChange={(event) => setProfile({ ...profile, target: event.target.value })}><option>计算机与数据</option><option>商科与金融</option><option>工程</option><option>教育与社会科学</option><option>生命科学</option></select></label>
              <label>计划入学<select value={profile.intake} onChange={(event) => setProfile({ ...profile, intake: event.target.value })}><option>2027 S1</option><option>2027 S2</option><option>2028 S1</option></select></label>
              <label>语言成绩（选填）<input value={profile.english} onChange={(event) => setProfile({ ...profile, english: event.target.value })} placeholder="例如：IELTS 6.5" /></label>
              <label className="full">相关经历（选填）<textarea value={profile.experience} onChange={(event) => setProfile({ ...profile, experience: event.target.value })} placeholder="简单描述实习、科研或项目经历" /></label>
            </div>
            {error && <p className="form-error">{error}</p>}
            <div className="form-footer"><button type="button" className="text-button" onClick={() => setView("landing")}>暂时返回</button><button className="primary-button" type="submit">生成选校方案 <span>→</span></button></div>
          </form>
        </section>
      )}

      {view === "results" && (
        <section className="results-page">
          <div className="results-header">
            <div><p className="eyebrow"><span /> 你的选校方案</p><h1>{profile.target} · {profile.intake}</h1><p>{profile.school || "示例大学"} · {profile.major || "软件工程"} · GPA {profile.gpa}/{profile.gpaScale}</p></div>
            <button className="outline-button" onClick={() => setView("profile")}>编辑背景</button>
          </div>
          <div className="insight-banner">
            <div className="insight-score"><strong>{Math.round(results.reduce((sum, item) => sum + item.score, 0) / results.length)}</strong><span>综合准备度</span></div>
            <div><p className="step-kicker">本次分析</p><h3>你的学术基础具备竞争力，建议采用“2 冲刺 + 4 匹配 + 2 稳妥”的组合。</h3><p>当前最大的不确定项是语言成绩与具体课程先修要求。选择项目后需要回到官网逐项核验。</p></div>
            <div className="legend"><span><i className="match" />匹配</span><span><i className="reach" />冲刺</span><span><i className="safe" />稳妥</span></div>
          </div>
          <div className="result-toolbar">
            <div>{(["全部", "匹配", "冲刺", "稳妥"] as const).map((tier) => <button key={tier} className={tierFilter === tier ? "active" : ""} onClick={() => setTierFilter(tier)}>{tier}</button>)}</div>
            <span>共 {filteredResults.length} 所院校 · 基于 Demo 规则 v0.1</span>
          </div>
          <div className="result-list">
            {filteredResults.map(({ university, tier, score }) => (
              <article className="result-card" key={university.slug} onClick={() => openSchool(university)}>
                <div className="uni-monogram" style={{ background: university.accent }}>{university.short.slice(0, 2)}</div>
                <div className="uni-main"><div className="uni-title"><div><h3>{university.name}</h3><p>{university.city} · {profile.target}</p></div><span className={`tier tier-${tier}`}>{tier}</span></div><p className="uni-note">{university.note}</p><div className="reason-row"><span>✓ 目标方向匹配</span><span>✓ GPA 已纳入评估</span><span className={!profile.english ? "warning" : ""}>{profile.english ? "✓ 已提供语言成绩" : "! 待补充语言成绩"}</span></div></div>
                <div className="match-score"><strong>{score}</strong><span>匹配分</span><button aria-label={`查看${university.name}详情`}>→</button></div>
              </article>
            ))}
          </div>
          <p className="data-disclaimer">推荐结果仅用于早期规划，不构成录取承诺。具体门槛、截止日期和材料要求请以各项目官网为准。</p>
        </section>
      )}

      {view === "school" && selected && (() => {
        const recommendation = getRecommendation(selected, profile);
        return (
          <section className="school-page">
            <button className="back-button" onClick={() => setView("results")}>← 返回选校方案</button>
            <div className="school-hero">
              <div className="uni-monogram large" style={{ background: selected.accent }}>{selected.short.slice(0, 2)}</div>
              <div><p>{selected.city} · Group of Eight</p><h1>{selected.name}</h1><span className={`tier tier-${recommendation.tier}`}>{recommendation.tier}选择</span></div>
              <a href={selected.official} target="_blank" rel="noreferrer" className="outline-button">访问学校官网 ↗</a>
            </div>
            <div className="school-grid">
              <article className="analysis-card primary-analysis"><p className="step-kicker">个性化判断</p><h2>为什么它是你的“{recommendation.tier}”选择？</h2><div className="big-score"><strong>{recommendation.score}</strong><span>/ 100 匹配分</span></div><ul><li><span>01</span><div><strong>学术成绩</strong><p>你的标准化 GPA 为 {normalizeGpa(profile)}，已与本校 Demo 基线进行比较。</p></div></li><li><span>02</span><div><strong>专业相关性</strong><p>{selected.fields.includes(profile.target) ? `学校覆盖${profile.target}方向，具备进一步筛选项目的基础。` : "当前方向不是本 Demo 的重点标签，需要逐项核验课程。"}</p></div></li><li><span>03</span><div><strong>准备完整度</strong><p>{profile.english ? `已记录语言成绩：${profile.english}。` : "尚未填写语言成绩，这是下一步最值得补充的信息。"}</p></div></li></ul></article>
              <aside>
                <article className="analysis-card"><p className="step-kicker">下一步行动</p><h3>申请前请完成</h3><ol className="checklist"><li><span>1</span>确定具体课程名称与 intake</li><li><span>2</span>核验本科院校对应成绩门槛</li><li><span>3</span>核验先修课程与语言小分</li><li><span>4</span>记录官方截止日期</li></ol></article>
                <article className="source-card"><span>数据说明</span><p>本页使用学校级公开信息与演示规则，不替代具体项目招生页面。</p><a href="https://go8.edu.au/about/the-go8" target="_blank" rel="noreferrer">查看 Go8 官方成员名单 ↗</a><small>最近核验：2026-07-14</small></article>
              </aside>
            </div>
          </section>
        );
      })()}
    </main>
  );
}
