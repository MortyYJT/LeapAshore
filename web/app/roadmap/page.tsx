"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { RequireAccount, useAuth } from "@/components/auth/AuthProvider";
import { editHref } from "@/components/home/DeadlineTable";
import { RoadmapMap } from "@/components/roadmap/RoadmapMap";
import { useApplicationRecords } from "@/components/shell/ApplicationRecords";
import { Bar, DemoNotePlaceholder, RoadmapBody } from "@/components/shell/RouteSkeleton";
import { ConflictNotice, Loading, Notice } from "@/components/ui";
import { uploadMaterial } from "@/lib/api";
import { EMPTY_PROFILE } from "@/lib/assess";
import { beijingToday } from "@/lib/deadlines";
import { demoProgramHref } from "@/lib/demo";
import { useMaterials } from "@/lib/hooks/useMaterials";
import { useProfile } from "@/lib/hooks/useProfile";
import { useRoadmap } from "@/lib/hooks/useRoadmap";
import { toMaterial } from "@/lib/materials-source";
import { dateLabel, overviewOf, type Overview, type OverviewRow } from "@/lib/overview";
import { buildRoadmap, DEFAULT_DEFINITION, intakeAnchor } from "@/lib/roadmap";
import { stepFiles } from "@/lib/roadmap-files";
import { headline, roadmapMap, tightWords, windowWords, type RoadmapMap as MapModel } from "@/lib/roadmap-map";
import { scheduleBound } from "@/lib/roadmap-schedule";
import { taskStatusLabel } from "@/lib/roadmap-sync";
import { timelineOf, type Timeline, type TimelinePhase } from "@/lib/roadmap-timeline";
import { verifiedMark } from "@/lib/taxonomy";

/**
 * The roadmap (spec application-roadmap): the preparation drawn as one line from today to the intake,
 * with every application's deadline on the same axis. In login mode a visitor who is not signed in
 * sees a labelled sample; the applicant's own needs an account (openspec account-login).
 */
export default function RoadmapPage() {
  return (
    <main className="page roadmap">
      <RequireAccount
        what="路线图"
        fallback={<Sample />}
        // Before the account is known the page may still turn out to be the demo, whose note under the
        // title would push a placeholder down: only the title is drawn, and the blocks arrive below it.
        pending={<Frame finding={<Bar width="16em" />}>{null}</Frame>}
      >
        <Roadmap />
      </RequireAccount>
    </main>
  );
}

/** The title, the sentence under it and any note under that, what sits to its right, and the blocks. */
function Frame({ finding, note, demo = false, aside, children }: { finding: ReactNode; note?: ReactNode; demo?: boolean; aside?: ReactNode; children: ReactNode }) {
  return (
    <>
      <header className={`page-head${demo ? " has-note" : ""}`}>
        <div>
          {demo ? (
            <div className="marked">
              <h1>申请路线图</h1>
              <span className="pill pill-sample">演示</span>
            </div>
          ) : (
            <h1>申请路线图</h1>
          )}
          <p className="finding">{finding}</p>
          {note}
        </div>
        {aside}
      </header>
      {children}
    </>
  );
}

/** Midnight UTC of a calendar day, which is what the timeline's rules compare dates against. */
function dayOf(today: string): Date {
  return new Date(`${today}T00:00:00Z`);
}

function intakeWords(anchor: Date): string {
  return `${anchor.getUTCFullYear()} 年 ${anchor.getUTCMonth() + 1} 月入学`;
}

/**
 * The chosen stretch. It starts as the current one and is then pinned: ticking the last open step of
 * the stretch on screen moves "current" on, and the list must not leave under the applicant's hands.
 * A choice that no longer exists falls back to the current stretch.
 */
function useStretch(timeline: Timeline | null): [TimelinePhase | null, (id: string) => void] {
  const [choice, setChoice] = useState<string | null>(null);
  const fallback = timeline?.current ?? timeline?.phases[0] ?? null;
  const chosen = timeline?.phases.find((phase) => phase.id === choice) ?? fallback;
  const chosenId = chosen?.id ?? null;
  useEffect(() => {
    if (chosenId !== null && chosenId !== choice) setChoice(chosenId);
  }, [chosenId, choice]);
  return [chosen, setChoice];
}

function Roadmap() {
  const profile = useProfile();
  const roadmap = useRoadmap(profile.data);
  const records = useApplicationRecords();
  const library = useMaterials();
  // One "today" for the whole page: the Beijing calendar date the deadlines are judged against (D4).
  const today = beijingToday();

  const overview = useMemo(() => overviewOf(records.data ?? [], today), [records.data, today]);
  // The map draws a line per application and the schedule is fitted to their deadlines, so it waits
  // for the applications too: drawn without them it would grow and push the page down when they land.
  // A failed read counts as known (the map is drawn without them, as before), so a retry does not take
  // the map down again.
  const recordsKnown = records.data !== null || records.error !== null || !records.loading;
  // The phases before applying are fitted to the earliest open deadline once they are laid out again.
  const bound = useMemo(() => scheduleBound(overview.rows), [overview]);
  const timeline = useMemo(
    () => (roadmap.roadmap && recordsKnown ? timelineOf(roadmap.roadmap, dayOf(today), bound) : null),
    [roadmap.roadmap, recordsKnown, today, bound],
  );
  const map = useMemo(() => (timeline ? roadmapMap(timeline, overview.rows, today) : null), [timeline, overview, today]);
  const [stretch, choose] = useStretch(timeline);
  const anchor = profile.data ? intakeAnchor(profile.data.intake) : null;

  return (
    <Frame
      finding={timeline ? headline(timeline) : profile.error && !profile.data ? "没能读取你的申请背景。" : <Bar width="16em" />}
      note={timeline && <TightNote timeline={timeline} today={today} />}
      aside={
        anchor && (
          <div className="toolbar rm-intake">
            <span className="muted">{intakeWords(anchor)}</span>
            <Link className="btn btn-secondary" href="/me">
              改入学时间
            </Link>
          </div>
        )
      }
    >
      {profile.error && !profile.data && <Notice error>没有读到你的背景（{profile.error}）。</Notice>}
      {roadmap.notice && <Notice>{roadmap.notice}</Notice>}
      {roadmap.syncError && <Notice error>{roadmap.syncError}</Notice>}
      {!map && !profile.error && <RoadmapBody lines={recordsKnown ? overview.rows.length : null} />}
      {map && timeline && (
        <>
          {!map.dated && (
            <div className="rm-undated" role="note">
              <p>
                <b>还没有入学时间。</b>下面只按先后顺序排，没有日期。填上以后，每一段会按入学时间倒推出建议的时间，各项目的截止日期也会画上来。
              </p>
              <Link className="btn btn-primary" href="/me">
                填入学时间
              </Link>
            </div>
          )}
          <MapBlock map={map} today={today} intake={anchor ? intakeWords(anchor) : null} selected={stretch?.id ?? null} onSelect={choose} picked={records.selected} />
          {stretch && <Stations phase={stretch} roadmap={roadmap} library={library} />}
          <Dates
            overview={overview}
            today={today}
            picked={records.selected}
            loading={records.loading && !records.data}
            error={records.error}
            href={editHref}
            empty={
              <div className="lt-empty">
                <p>
                  <b>还没有申请</b>
                  添加以后，每个申请的截止日期会画在上面的时间轴上。日期还不知道也可以先加。
                </p>
                <Link className="btn btn-secondary" href="/applications?add=1">
                  添加申请项目
                </Link>
                <Link className="btn btn-secondary" href="/schools">
                  浏览学校库
                </Link>
              </div>
            }
          />
        </>
      )}
    </Frame>
  );
}

/**
 * 「时间很紧」 under the sentence below the title, once for each group of phases with too little time
 * left (lib/roadmap-schedule.ts): a calm line with the numbers, the same tag the stretches carry.
 */
function TightNote({ timeline, today }: { timeline: Timeline; today: string }) {
  if (!timeline.tight.length) return null;
  return (
    <>
      {timeline.tight.map((tight) => (
        <p className="rm-tight" key={tight.group}>
          <span className="rm-flag">时间很紧</span>
          <span>{tightWords(tight, timeline, today)}</span>
        </p>
      ))}
    </>
  );
}

/** The map with its heading, its legend and the sentence that says what the dates on it are. */
function MapBlock({
  map,
  today,
  intake,
  selected,
  onSelect,
  picked,
  demo = false,
}: {
  map: MapModel;
  today: string;
  intake: string | null;
  selected: string | null;
  onSelect: (id: string) => void;
  picked: string | null;
  demo?: boolean;
}) {
  const lead = map.stretches.some((stretch) => stretch.lead !== null);
  const moved = map.stretches.some((stretch) => stretch.phase.moved);
  return (
    <section className="block block-map" aria-labelledby="h-route">
      <div className="block-head">
        {demo ? (
          <div className="marked">
            <h2 id="h-route">准备路线</h2>
            <span className="pill pill-sample">示例</span>
          </div>
        ) : (
          <h2 id="h-route">准备路线</h2>
        )}
        <ul className="keys rm-keys" aria-label="图例">
          <li>
            <svg viewBox="0 0 14 14" aria-hidden="true">
              <circle className="k-j on" cx="7" cy="7" r="5" />
            </svg>
            做完
          </li>
          <li>
            <svg viewBox="0 0 14 14" aria-hidden="true">
              <circle className="k-j" cx="7" cy="7" r="5" />
            </svg>
            没做
          </li>
          {lead && (
            <li>
              <svg className="k-line" viewBox="0 0 22 14" aria-hidden="true">
                <path className="k-lead" d="M3 7H19" />
              </svg>
              原来的建议时间
            </li>
          )}
        </ul>
      </div>
      <RoadmapMap map={map} today={today} intake={intake} selected={selected} onSelect={onSelect} picked={picked} />
      {map.dated && (
        <p className="map-note">
          每一段的时间是按入学时间倒推的系统建议，不是官方日期。
          {moved && "过了原来的建议时间还没做完的段，系统从今天起重新排了。"}
          站只表示先后，没有各自的日期。
        </p>
      )}
    </section>
  );
}

/**
 * One stretch's stations as a list: where they are ticked. A station that ends in a document also
 * takes the file (lib/roadmap-files.ts says which); every other station is only ticked. The files
 * themselves live in the library on 材料, which is where a row sends the applicant to open one.
 */
function Stations({
  phase,
  roadmap,
  library,
  onDemoTick,
}: {
  phase: TimelinePhase;
  roadmap?: ReturnType<typeof useRoadmap>;
  /** The applicant's uploaded files; absent in the sample, which has none. */
  library?: ReturnType<typeof useMaterials>;
  /** In the sample nothing is saved: a tick asks the visitor to sign in instead. */
  onDemoTick?: () => void;
}) {
  // Keyed by task and kept across stretches: an upload started in one stretch still reports its
  // result, and stays guarded against a second send, after the applicant looks at another.
  const [uploads, setUploads] = useState<Record<string, { busy: boolean; failed?: boolean; stored?: string; message: string }>>({});
  // Two rows can upload at once, so the answer is added to the library as it is when it arrives.
  const libraryRef = useRef(library);
  libraryRef.current = library;

  async function upload(materialKey: string, file: File | undefined) {
    if (!file || !roadmap) return;
    const taskId = roadmap.taskIdFor(materialKey);
    if (!taskId || uploads[materialKey]?.busy) return;
    setUploads((u) => ({ ...u, [materialKey]: { busy: true, message: `正在上传 ${file.name}…` } }));
    try {
      const stored = toMaterial(await uploadMaterial(file, { title: file.name, taskId }));
      // The row lists the file from the library, so the answer goes straight into it; a library that
      // was never read is read now instead.
      const held = libraryRef.current;
      if (held?.data) held.set([...held.data, stored]);
      else held?.reload();
      setUploads((u) => ({ ...u, [materialKey]: { busy: false, stored: stored.id, message: `已上传 ${file.name}，在「材料」页的材料库里。` } }));
    } catch (error: unknown) {
      setUploads((u) => ({ ...u, [materialKey]: { busy: false, failed: true, message: `上传失败：${error instanceof Error ? error.message : "未知错误"}` } }));
    }
  }

  const suggested = windowWords(phase);
  return (
    <section className="block" aria-labelledby="h-stretch">
      <div className="block-head rm-stretch-head">
        <h2 id="h-stretch">
          {phase.title}
          {phase.current && <span className="pill pill-neutral">当前</span>}
        </h2>
        {phase.total > 0 && (
          <p className="block-note">
            <span className="block-count" aria-live="polite">
              {phase.done}/{phase.total} 项做完
            </span>
          </p>
        )}
      </div>
      <p className="rm-stretch-note">
        {phase.detail} {suggested}
        {phase.tight && <span className="rm-flag">时间很紧</span>}
        清单是系统建议的步骤，标了「依据」的才对应官方要求。
      </p>
      <ul className="rm-list" key={phase.id}>
        {phase.phase.tasks.length === 0 && <li className="is-plain">这一段对你的背景没有要做的步骤。</li>}
        {phase.phase.tasks.map((task) => {
          const id = `t-${task.materialId}`;
          const failed = roadmap?.failedTicks.has(task.materialId);
          const conflict = roadmap?.tickConflicts.get(task.materialId);
          // A tick needs the server's row for this step. On a first visit the rows are written and read
          // back first, so the box waits rather than taking a click that could not be saved.
          const ready = roadmap ? roadmap.taskIdFor(task.materialId) !== null : true;
          const uploadState = uploads[task.materialId];
          const files = roadmap ? stepFiles(task.materialId, roadmap.taskIdFor(task.materialId), library?.data ?? []) : null;
          // Once the file is named on the row, the row is the confirmation and the sentence is left to
          // a screen reader. A library that could not be read names nothing, so the sentence stays.
          const quiet = uploadState?.stored !== undefined && (library?.data ?? []).some((material) => material.id === uploadState.stored);
          return (
            <li className={task.done ? "is-done" : undefined} key={task.materialId}>
              <input
                type="checkbox"
                className="rm-tick"
                id={id}
                checked={task.done}
                disabled={!ready}
                title={onDemoTick ? "演示里不会保存，登录后可用" : ready ? undefined : "正在准备，稍等一下就能勾选"}
                aria-describedby={onDemoTick ? "demo-note" : undefined}
                onChange={(event) => (onDemoTick ? onDemoTick() : void roadmap?.tick(task.materialId, event.target.checked))}
              />
              <div className="what">
                <label htmlFor={id}>{task.label}</label>
                {task.detail && <p className="d">{task.detail}</p>}
                {task.source && (
                  <p className="d">
                    依据：
                    <a className="link" href={task.source.url} target="_blank" rel="noreferrer">
                      {task.source.title}
                    </a>
                    {verifiedMark(task.source.status) && <> · {verifiedMark(task.source.status)}</>}
                  </p>
                )}
                {failed && (
                  <p className="d negative" role="alert">
                    这次勾选没有保存，已恢复原状。
                  </p>
                )}
                {conflict && roadmap && (
                  <ConflictNotice onKeepMine={() => roadmap.settleTick(task.materialId, true)} onTakeTheirs={() => roadmap.settleTick(task.materialId, false)}>
                    这一步已在其他设备上改为「{taskStatusLabel(conflict.theirs)}」，这次勾选没有保存。
                  </ConflictNotice>
                )}
                {files && files.attached.length > 0 && (
                  <p className="d rm-files">
                    已上传 {files.attached.join("、")}。
                    <Link className="link" href="/materials#materials">
                      去材料库
                    </Link>
                  </p>
                )}
                {uploadState && (
                  <p className={quiet ? "sr-only" : `d${uploadState.failed ? " negative" : ""}`} role="status">
                    {uploadState.message}
                  </p>
                )}
              </div>
              {files?.upload && (
                <label className="btn btn-text btn-small" aria-disabled={!ready || uploadState?.busy} aria-busy={uploadState?.busy}>
                  上传
                  <input
                    type="file"
                    className="sr-only"
                    disabled={!ready || uploadState?.busy}
                    aria-label={`上传「${task.label}」的文件`}
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      event.target.value = "";
                      void upload(task.materialId, file);
                    }}
                  />
                </label>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Every application's deadline as the record states it: the date, whether it was checked, its source. */
function Dates({
  overview,
  today,
  picked,
  href,
  hrefTitle = "在「我的申请」里查看和修改",
  loading = false,
  error = null,
  demo = false,
  empty,
}: {
  overview: Overview;
  today: string;
  picked: string | null;
  href: (row: OverviewRow) => string;
  hrefTitle?: string;
  loading?: boolean;
  error?: string | null;
  demo?: boolean;
  empty?: ReactNode;
}) {
  const { rows, closed } = overview;
  const hasPicked = picked !== null && rows.some((row) => row.record.id === picked);
  return (
    <section className="block" aria-labelledby="h-dates">
      <div className="block-head">
        {demo ? (
          <div className="marked">
            <h2 id="h-dates">各项目的截止日期</h2>
            <span className="pill pill-sample">演示</span>
          </div>
        ) : (
          <h2 id="h-dates">各项目的截止日期</h2>
        )}
        {rows.length > 0 && !demo && (
          <p className="block-note">
            <Link href="/applications">全部申请</Link>
          </p>
        )}
      </div>
      {error && <Notice error>没能读取你的申请：{error}</Notice>}
      {loading && <Loading what="你的申请" lines={2} />}
      {!loading && !error && rows.length === 0 && empty}
      {rows.length > 0 && (
        <ul className={`rm-dates${hasPicked ? " has-sel" : ""}`}>
          {rows.map((row) => {
            const { record } = row;
            return (
              <li
                className={`line-${row.line}${row.soon ? " is-soon" : ""}${record.id === picked ? " is-sel" : ""}`}
                data-record={record.id}
                data-state={row.sent ? "sent" : row.days === null ? "unknown" : row.days < 0 ? "closed" : "upcoming"}
                key={record.id}
              >
                <div className="who">
                  <span className="bullet">{row.code}</span>
                  <div className="txt">
                    <div className="school">
                      <Link href={href(row)} title={hrefTitle}>
                        {record.school}
                      </Link>
                      {record.round && <span className="round">{record.round}</span>}
                    </div>
                    <div className="program">{record.name}</div>
                  </div>
                </div>
                <div className="date">
                  {record.deadline ? (
                    <>
                      <time className="num" dateTime={record.deadline.slice(0, 10)}>
                        {dateLabel(record.deadline, today)}
                      </time>
                      <span className="sub">
                        {/* Where the date came from, then whether the applicant has checked it against the official page. */}
                        {record.deadlineOrigin === "collected" ? "学校库采集 · " : record.deadlineOrigin === "entered" ? "自己填的 · " : ""}
                        {record.checkedAt ? "已核对" : "待核对"}
                        {record.sourceUrl && (
                          <>
                            {" · "}
                            <a href={record.sourceUrl} target="_blank" rel="noreferrer">
                              来源
                            </a>
                          </>
                        )}
                      </span>
                    </>
                  ) : (
                    <span className="none">待确认</span>
                  )}
                </div>
                <div className="left">
                  {row.sent ? (
                    <span className="word">已提交</span>
                  ) : row.days === null ? (
                    <span className="none" aria-label="待确认">
                      —
                    </span>
                  ) : row.days < 0 ? (
                    <span className="word">已截止</span>
                  ) : row.days === 0 ? (
                    <span className="word">今天截止</span>
                  ) : (
                    <>
                      <span className="n">{row.days}</span>
                      <span className="u">天</span>
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {closed > 0 && <p className="map-note">另有 {closed} 个已有结果或已放弃的申请，没有列出。</p>}
    </section>
  );
}

/**
 * For a visitor: a sample roadmap in the same drawing, labelled as one. The phases and their steps are
 * the built-in definition, dated from next July; which of them are ticked is made up, the same way
 * every time. The applications are the overview demo's (lib/demo.ts): real catalogue programs with
 * the dates the catalogue collected, and none when the catalogue could not be read. Nothing here
 * writes: a tick opens the sign-in dialog.
 */
function Sample() {
  const { requireLogin } = useAuth();
  const { demo, demoPending, selected } = useApplicationRecords();
  const today = beijingToday();
  const year = Number(today.slice(0, 4)) + 1;
  const timeline = useMemo(() => {
    const profile = { ...EMPTY_PROFILE, intake: `${year} S2`, targetField: "计算机与数据" as const };
    const now = dayOf(today);
    // Ticked in the sample: every step of a phase whose planned window has ended, and the first of the
    // next. So the sample is always on time: nothing in it is laid out again from today.
    const plan = timelineOf(buildRoadmap(profile, [], now, DEFAULT_DEFINITION), now);
    const done = plan.phases.flatMap((phase, index) => {
      const ids = phase.phase.tasks.map((task) => task.materialId);
      if (phase.planned && phase.planned.end <= today) return ids;
      const previous = plan.phases[index - 1];
      return !previous || (previous.planned && previous.planned.end <= today) ? ids.slice(0, 1) : [];
    });
    return timelineOf(buildRoadmap(profile, done, now, DEFAULT_DEFINITION), now);
  }, [today, year]);
  const overview = useMemo(() => overviewOf(demo ?? [], today), [demo, today]);
  const map = useMemo(() => roadmapMap(timeline, overview.rows, today), [timeline, overview, today]);
  const [stretch, choose] = useStretch(timeline);
  const signIn = () => void requireLogin();
  const finding = <>一位示例申请人的路线图：{year} 年 7 月入学，计算机方向。</>;

  // The demo's programs add a clause to the note and a line per program to the map. Drawn before they
  // arrive, both would grow under the visitor's eyes and push the page down; the placeholder holds
  // their final shape instead.
  if (demoPending) {
    return (
      <Frame demo finding={finding}>
        <DemoNotePlaceholder text="这是演示：阶段的时间和勾选是示例，项目和截止日期来自学校库。登录后，这里按你的入学时间和申请排出你自己的。" />
        <RoadmapBody lines={null} />
      </Frame>
    );
  }

  return (
    <Frame demo finding={finding}>
      <div className="demo-note" role="note">
        <p id="demo-note">
          这是演示：阶段的时间和勾选是示例{demo ? "，项目和截止日期来自学校库" : ""}。登录后，这里按你的入学时间和申请排出你自己的。
        </p>
        <button type="button" className="btn btn-primary" onClick={signIn}>
          登录
        </button>
      </div>
      <MapBlock map={map} today={today} intake={`${year} 年 7 月入学`} selected={stretch?.id ?? null} onSelect={choose} picked={selected} demo />
      {stretch && <Stations phase={stretch} onDemoTick={signIn} />}
      {overview.rows.length > 0 && (
        <Dates overview={overview} today={today} picked={selected} href={(row) => demoProgramHref(row.record)} hrefTitle="在学校库里看这个项目和日期的来源" demo />
      )}
    </Frame>
  );
}
