// Page-shaped placeholders. Each is the route's real frame (its title, the labels that never change,
// its panels and table headers) with a flat grey bar where a value will be, at the value's own size and
// row pitch, so the content that replaces it lands in the same place.
//
// They are drawn in two situations that must look the same:
// - by the shell, from the click until the route itself is on screen (`RouteSkeleton`);
// - by the route, while its first read is on its way (the `…Body` exports, and `Bar` for one value).
// Keep a title here in step with the page it stands for; the walkthrough compares them.

import { useMemo, type CSSProperties, type ReactNode } from "react";

import { beijingToday } from "@/lib/deadlines";
import { overviewOf } from "@/lib/overview";

import { useApplicationRecords } from "./ApplicationRecords";

import type { RouteShape } from "@/lib/navigation";

/** One value that has not arrived: a bar on the text's own line, `width` wide (any CSS length). */
export function Bar({ width, className = "" }: { width: string; className?: string }) {
  return <span className={`sk ${className}`.trim()} style={{ "--sk-w": width } as CSSProperties} aria-hidden="true" />;
}

/** A filled shape of a fixed size: a logo, a button, a field. */
function Box({ width, height, round = false }: { width: number | string; height: number; round?: boolean }) {
  return <span className={`sk sk-box${round ? " sk-round" : ""}`} style={{ "--sk-w": typeof width === "number" ? `${width}px` : width, "--sk-h": `${height}px` } as CSSProperties} aria-hidden="true" />;
}

/** What a screen reader hears instead of the bars. */
function Status({ what }: { what: string }) {
  return (
    <p className="sr-only" role="status">
      正在读取{what}…
    </p>
  );
}

/** `count` rows of one pitch, divided like the lists they stand for; `widths` are the bars in a row. */
function Rows({ count, pitch, widths, lead }: { count: number; pitch: number; widths: string[]; lead?: ReactNode }) {
  return (
    <div className="sk-rows sk-late" aria-hidden="true">
      {Array.from({ length: count }, (_, row) => (
        <div className="sk-row" key={row} style={{ "--sk-h": `${pitch}px` } as CSSProperties}>
          {lead}
          {widths.map((width, i) => (
            // Rows differ a little in length, as real names do; the first bar carries the variation.
            <Bar key={i} width={i === 0 ? `calc(${width} * ${1 - (row % 3) * 0.16})` : width} className={i > 0 ? "sk-end" : ""} />
          ))}
        </div>
      ))}
    </div>
  );
}

function Finding({ width = "16em" }: { width?: string }) {
  return (
    <p className="finding">
      <Bar width={width} className="sk-late" />
    </p>
  );
}

/* ---------- bodies, shared with the routes' own loading states ---------- */

/** 总览: the deadline lines, then what to do next. */
export function OverviewBody() {
  return (
    <>
      <Status what="你的申请" />
      <section className="block" aria-hidden="true">
        <div className="block-head">
          <h2>截止日期</h2>
        </div>
        <div className="sk-rows sk-late">
          {/* The table's own head row plus the frame's padding below the lines. */}
          <div className="sk-row" style={{ "--sk-h": "48px" } as CSSProperties}>
            <Bar width="3em" />
          </div>
        </div>
        <Rows count={3} pitch={64} widths={["34%", "9%", "14%"]} />
      </section>
      <section className="block" aria-hidden="true">
        <div className="block-head">
          <h2>接下来</h2>
        </div>
        <Rows count={3} pitch={52} widths={["28%", "34%"]} />
      </section>
    </>
  );
}

/**
 * 申请路线图: the map's frame, then the stretch's steps. `lines` is how many applications the map
 * will draw under the preparation line, when the shell already knows: each takes a row of the map,
 * so the steps below start where they will.
 */
export function RoadmapBody({ lines = 0 }: { lines?: number }) {
  return (
    <>
      <Status what="路线图" />
      <section className="block block-map" aria-hidden="true">
        <div className="block-head">
          <h2>准备路线</h2>
        </div>
        <div className="sk-map sk-late" style={lines ? ({ "--sk-lines": lines } as CSSProperties) : undefined}>
          {Array.from({ length: 7 }, (_, step) => (
            <span key={step} className="sk sk-step" style={{ "--sk-step": step } as CSSProperties} />
          ))}
        </div>
        <p className="map-note">
          <Bar width="28em" className="sk-late" />
        </p>
      </section>
      <section className="block" aria-hidden="true">
        <div className="block-head">
          <h2>
            <Bar width="7em" className="sk-late" />
          </h2>
        </div>
        <Rows count={5} pitch={70} widths={["38%"]} lead={<Box width={22} height={22} round />} />
      </section>
    </>
  );
}

/** One application card on 我的申请. */
function ApplicationCard() {
  return (
    <div className="panel application-card sk-card">
      <div className="application-card-heading">
        <div>
          <div className="small">
            <Bar width="6em" />
          </div>
          <h2>
            <Bar width="13em" />
          </h2>
        </div>
        <Box width={52} height={20} />
      </div>
      <div className="application-card-details">
        <div>
          <div>
            <Bar width="9em" />
          </div>
          <div className="small">
            <Bar width="7em" />
          </div>
        </div>
        <Bar width="6em" />
      </div>
      <div className="application-card-actions">
        <Box width={74} height={28} />
      </div>
    </div>
  );
}

/** The cards of 我的申请, under the page's own toolbar. */
export function ApplicationCards() {
  return (
    <div className="application-list section sk-late" aria-hidden="true">
      <ApplicationCard />
      <ApplicationCard />
      <ApplicationCard />
    </div>
  );
}

/** 我的申请 before the account is known: the toolbar's places, then the cards. */
export function ApplicationsBody() {
  return (
    <>
      <Status what="你的申请" />
      <div className="application-toolbar section sk-late" aria-hidden="true">
        <div className="toolbar">
          <Box width={104} height={32} />
          <Box width={104} height={32} />
        </div>
        <Box width={140} height={36} />
      </div>
      <ApplicationCards />
    </>
  );
}

/** A table inside a panel: the head's own labels, then rows of bars. */
function TablePanel({ title, head, rows, pitch, lead }: { title?: ReactNode; head: string[]; rows: number; pitch: number; lead?: boolean }) {
  return (
    <section className="panel section" aria-hidden="true">
      {title && <div className="panel-head">{title}</div>}
      <table className="stack sk-table">
        <thead>
          <tr>
            {head.map((label, i) => (
              <th key={label} className={i === head.length - 1 && head.length > 2 ? "num" : undefined}>
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="sk-late">
          {Array.from({ length: rows }, (_, row) => (
            <tr key={row} style={{ "--sk-h": `${pitch}px` } as CSSProperties}>
              {head.map((label, i) => (
                <td key={label} className={i === 0 ? "wide" : i === head.length - 1 && head.length > 2 ? "num" : undefined}>
                  {i === 0 && lead ? (
                    <span className="ident">
                      <Box width={28} height={28} round />
                      <Bar width={`${11 - (row % 3) * 2}em`} />
                    </span>
                  ) : (
                    <Bar width={i === 0 ? `${62 - (row % 4) * 9}%` : "4em"} />
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/** 材料: the map of what each program asks for, then the uploaded files. */
export function MaterialsBody() {
  return (
    <>
      <Status what="你的材料" />
      <section className="block" aria-hidden="true">
        <div className="block-head">
          <h2>
            <Bar width="6em" className="sk-late" />
          </h2>
        </div>
        <Rows count={3} pitch={68} widths={["30%", "44%"]} />
      </section>
      <section className="block block-files" aria-hidden="true">
        <TablePanel title={<h2>材料库</h2>} head={["材料", "分类", "状态", "版本"]} rows={3} pitch={89} />
      </section>
    </>
  );
}

/** 学校库: the filter bar's places and the list under its real column heads. */
function SchoolsBody() {
  return (
    <>
      <Status what="学校库" />
      <section className="panel section" aria-hidden="true">
        <div className="panel-head sk-filters">
          <div className="toolbar sk-late" style={{ flex: 1 }}>
            <Box width="min(280px, 100%)" height={36} />
            <Box width={140} height={36} />
            <Box width={150} height={36} />
            <Box width={92} height={32} />
          </div>
          <Bar width="3em" className="sk-late" />
        </div>
        <table className="stack sk-table">
          <thead>
            <tr>
              <th className="num" style={{ width: 72 }}>QS</th>
              <th>学校</th>
              <th className="hide-phone">地区 · 城市</th>
              <th className="num">已收录项目</th>
            </tr>
          </thead>
          <tbody className="sk-late">
            {Array.from({ length: 12 }, (_, row) => (
              <tr key={row} style={{ "--sk-h": "67px" } as CSSProperties}>
                <td className="num">
                  <Bar width="1.4em" />
                </td>
                <td className="wide">
                  <div className="ident">
                    <Box width={28} height={28} round />
                    <div className="two-line">
                      <div className="l1">
                        <Bar width={`${8 - (row % 3)}em`} />
                      </div>
                      <div className="l2">
                        <Bar width={`${15 - (row % 4) * 2}em`} />
                      </div>
                    </div>
                  </div>
                </td>
                <td className="hide-phone">
                  <Bar width="8em" />
                </td>
                <td className="num">
                  <Bar width="5em" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

/** A strip of facts: the labels are known, the values are not. */
function Strip({ labels }: { labels: (string | null)[] }) {
  return (
    <section className="panel section" aria-hidden="true">
      <div className="strip">
        {labels.map((label, i) => (
          <div key={i}>
            <div className="label">{label ?? <Bar width="4em" className="sk-late" />}</div>
            <div className="value">
              <Bar width="3.2em" className="sk-late" />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

/** Lines of running text inside a padded panel. */
function TextPanel({ lines, heading }: { lines: string[]; heading?: ReactNode }) {
  return (
    <section className="panel panel-pad section" aria-hidden="true">
      {heading ?? (
        <h2>
          <Bar width="7em" className="sk-late" />
        </h2>
      )}
      <div className="sk-text sk-late">
        {lines.map((width, i) => (
          <Bar key={i} width={width} />
        ))}
      </div>
    </section>
  );
}

/** 分档结果: the background strip, then the tiers. Also the page's own first-read state. */
export function TiersBody() {
  return (
    <>
      <Status what="你的背景" />
      <Strip labels={["本科院校", "专业", "均分", "英语", "方向"]} />
      <TextPanel lines={["92%", "78%", "85%", "60%", "88%", "70%"]} />
    </>
  );
}

export function PortfolioBody() {
  return (
    <>
      <Status what="选校组合" />
      <div className="stagger">
        <Strip labels={[null, null, null, null]} />
        <TablePanel head={["项目", "分档", "截止"]} rows={4} pitch={54} />
      </div>
    </>
  );
}

export function MeBody() {
  return (
    <>
      <Status what="你的背景和材料" />
      <div className="stagger">
        <section className="panel section" aria-hidden="true">
          <div className="panel-head">
            <h2>申请背景</h2>
          </div>
          <Rows count={5} pitch={46} widths={["16%", "22%"]} />
        </section>
        <TablePanel title={<h2>材料库</h2>} head={["材料", "分类", "状态", "版本"]} rows={3} pitch={89} />
      </div>
    </>
  );
}

function SchoolBody() {
  return (
    <>
      <Status what="学校" />
      <div className="stagger">
        <Strip labels={["QS 2027", "地区", "城市", "已收录项目"]} />
        <TablePanel title={<h2>授课型硕士项目</h2>} head={["项目", "方向", "录取要求"]} rows={12} pitch={46} />
      </div>
    </>
  );
}

function ProgramBody() {
  return (
    <>
      <Status what="项目" />
      <div className="stagger">
        <Strip labels={[null, "方向", null, "学制"]} />
        <div className="grid grid-8-4 section" aria-hidden="true">
          <section className="panel">
            <div className="panel-head">
              <h2>录取要求</h2>
            </div>
            <Rows count={5} pitch={49} widths={["22%", "46%"]} />
          </section>
          <section className="panel panel-pad">
            <div className="sk-text sk-late">
              <Bar width="70%" />
              <Bar width="90%" />
              <Box width={132} height={32} />
            </div>
          </section>
        </div>
      </div>
    </>
  );
}

/* ---------- whole pages, for the shell ---------- */

function TitleRow({ title, lede, aside }: { title: ReactNode; lede?: ReactNode; aside?: ReactNode }) {
  return (
    <div className="title-row">
      <div>
        <h1>{title}</h1>
        {lede && <p className="lede">{lede}</p>}
      </div>
      {aside}
    </div>
  );
}

/**
 * `demo`: the note of the signed-out visitor's page, which marks its title and explains itself under
 * it. The sentence is the page's own (keep the two in step), so it wraps to the same height.
 */
function PageHead({ title, demo }: { title: string; demo?: string | null }) {
  return (
    <>
      <header className={`page-head${demo ? " has-note" : ""}`}>
        <div>
          {demo ? (
            <div className="marked">
              <h1>{title}</h1>
              <span className="pill pill-sample">演示</span>
            </div>
          ) : (
            <h1>{title}</h1>
          )}
          <Finding />
        </div>
      </header>
      {demo && (
        <div className="demo-note sk-late" aria-hidden="true">
          <p>{demo}</p>
          <Box width={52} height={32} />
        </div>
      )}
    </>
  );
}

/** What the shell already knows about the page it is about to show. */
interface Known {
  /** The visitor is signed out and the demo's programs are in hand: the page will be the demo. */
  demo: boolean;
  /** The same for 材料, whose demo needs programs whose materials have been collected. */
  demoMaterials: boolean;
  /** How many applications the roadmap will draw. */
  lines: number;
}

const PAGES: Record<RouteShape, (known: Known) => ReactNode> = {
  overview: ({ demo }) => (
    <main className="page overview">
      <PageHead title="总览" demo={demo ? "这是演示：项目和截止日期来自学校库，状态和材料是示例。登录后这里是你自己的申请。" : null} />
      <OverviewBody />
    </main>
  ),
  roadmap: ({ demo, lines }) => (
    <main className="page roadmap">
      <PageHead title="申请路线图" demo={demo ? "这是演示：阶段的时间和勾选是示例，项目和截止日期来自学校库。登录后，这里按你的入学时间和申请排出你自己的。" : null} />
      <RoadmapBody lines={lines} />
    </main>
  ),
  applications: () => (
    <main className="page personal-applications">
      <h1>我的申请</h1>
      <p className="lede">集中管理每个项目的截止日期、材料和申请进度。</p>
      <ApplicationsBody />
    </main>
  ),
  materials: ({ demoMaterials }) => (
    <main className="page materials">
      <PageHead title="材料" demo={demoMaterials ? "这是演示：项目和材料要求来自学校库，都没有勾选。登录后这里是你自己的申请。" : null} />
      <MaterialsBody />
    </main>
  ),
  schools: () => (
    <main className="page">
      <TitleRow
        title="学校库"
        lede={
          <>
            29 个国家和地区里的 QS 2027 前 300，加上澳洲、香港、澳门的其他大学，共 <Bar width="1.7em" className="sk-late" /> 所，按 QS 名次排列。
          </>
        }
      />
      <SchoolsBody />
    </main>
  ),
  school: () => (
    <main className="page">
      <span className="crumb">学校库</span>
      <div className="title-row">
        <div className="ident" style={{ gap: 16 }}>
          <Box width={28} height={28} round />
          <div className="two-line">
            <h1>
              <Bar width="7em" className="sk-late" />
            </h1>
            <p className="lede" style={{ marginTop: 2 }}>
              <Bar width="11em" className="sk-late" />
            </p>
          </div>
        </div>
      </div>
      <SchoolBody />
    </main>
  ),
  program: () => (
    <main className="page">
      <span className="crumb">学校库</span>
      <TitleRow title={<Bar width="14em" className="sk-late" />} lede={<Bar width="9em" className="sk-late" />} />
      <ProgramBody />
    </main>
  ),
  tiers: () => (
    <main className="page">
      <TitleRow
        title="分档结果"
        lede={
          <>
            按已收录的官方要求比较你的背景。分档说明满足了几项要求，<strong>不是录取概率</strong>。
          </>
        }
        aside={
          <div className="toolbar sk-late" aria-hidden="true">
            <Box width={78} height={32} />
            <Box width={65} height={32} />
          </div>
        }
      />
      <TiersBody />
    </main>
  ),
  portfolio: () => (
    <main className="page">
      <TitleRow title="选校组合" lede={<Bar width="11em" className="sk-late" />} />
      <PortfolioBody />
    </main>
  ),
  advisor: () => (
    <main className="advisor-route sk-advisor">
      <h1 className="sr-only">AI 顾问</h1>
      <Status what="顾问" />
      <div className="sk-text sk-late" aria-hidden="true">
        <Bar width="46%" />
        <Bar width="72%" />
        <Bar width="58%" />
      </div>
      <span className="sk-field" aria-hidden="true" />
    </main>
  ),
  me: () => (
    <main className="page">
      <TitleRow title="我的" lede="分档、选校和路线图都用这一份背景。改了背景，分档会按新背景重算。" />
      <MeBody />
    </main>
  ),
  privacy: () => (
    <main className="page privacy">
      <TitleRow title="隐私政策" />
      <Status what="隐私政策" />
      <TextPanel heading={<h2>收集哪些信息</h2>} lines={["96%", "88%", "92%", "64%", "90%", "84%", "95%", "72%"]} />
      <TextPanel heading={<h2>交给谁处理</h2>} lines={["70%", "94%", "86%", "90%"]} />
    </main>
  ),
  unsubscribe: () => (
    <main className="page unsubscribe">
      <h1>退订截止提醒</h1>
      <p className="lede">
        <Bar width="26em" className="sk-late" />
      </p>
      <Status what="退订页" />
    </main>
  ),
  // No title: this page is the ordinary 404 to anyone who is not an admin, and says nothing before that is known.
  admin: () => (
    <main className="page">
      <TitleRow title={<Bar width="5em" className="sk-late" />} lede={<Bar width="24em" className="sk-late" />} />
      <Status what="页面" />
      <TextPanel lines={["90%", "76%", "84%"]} />
      <TextPanel lines={["82%", "68%"]} />
    </main>
  ),
};

/**
 * The destination's placeholder, drawn by the shell while the route is on its way. It takes no room
 * of its own and is moved down by `offset`, the distance the page under it is scrolled, so it starts
 * at the top of the window without the window being scrolled.
 */
export function RouteSkeleton({ shape, offset }: { shape: RouteShape; offset: number }) {
  const records = useApplicationRecords();
  const today = beijingToday();
  const source = records.data ?? records.demo;
  // The applications the map draws as lines: the overview's rows (lib/overview.ts), which the rail lists too.
  const lines = useMemo(() => (source ? overviewOf(source, today).rows.length : 0), [source, today]);
  const known: Known = { demo: !records.data && records.demo !== null, demoMaterials: !records.data && records.demoMaterials !== null, lines };
  return (
    <div className="route-skeleton" data-route-skeleton={shape} style={{ translate: `0 ${offset}px` }}>
      {PAGES[shape](known)}
    </div>
  );
}
