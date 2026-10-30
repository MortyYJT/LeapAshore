"use client";

import { useEffect, useState } from "react";

import { Button, Loading, Notice, Panel, Pill } from "@/components/ui";
import {
  ACTION_LABEL,
  confirmGate,
  fetchVerificationPage,
  highlightQuotes,
  revokePage,
  verifyPage,
  type PageDetail,
  type Quote,
  type SnapshotView,
} from "@/lib/admin";

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }) : "未知";
}

/** The reading view: values and quotes first, then the snapshot with the quotes marked, then the decision. */
export function SourceReview({ id }: { id: string }) {
  const [detail, setDetail] = useState<PageDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [read, setRead] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchVerificationPage(id).then(setDetail).catch((e: Error) => setError(e.message));
  }, [id]);

  if (!detail) {
    return (
      <>
        <h1>核验页面</h1>
        {error ? <Notice error>{error}</Notice> : <Loading what="页面" />}
      </>
    );
  }

  const gate = confirmGate(detail);
  const act = (run: () => Promise<PageDetail>) => {
    setBusy(true);
    setError(null);
    run()
      .then((next) => (setDetail(next), setRead(false)))
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };
  const allQuotes = detail.programs.flatMap((p) => p.fields.flatMap((f) => f.quotes));

  return (
    <div className="stagger">
      <div className="title-row">
        <div>
          <h1>{detail.source.title}</h1>
          <p className="lede" style={{ overflowWrap: "anywhere" }}>
            <a href={detail.source.url} target="_blank" rel="noopener noreferrer">{detail.source.url}</a>
          </p>
        </div>
        {detail.source.verifiedAt ? <Pill kind="tier">已核验 {when(detail.source.verifiedAt)}</Pill> : <Pill>待核验</Pill>}
      </div>
      <p className="muted small">
        入库版本 <span className="num">{detail.version.versionNo}</span> · 抓取于 {when(detail.version.fetchedAt)} · 快照{" "}
        <span className="num">{detail.version.contentSha256.slice(0, 12)}</span>
      </p>

      {detail.programs.map((program) => (
        <section className="section" key={program.id} aria-label={program.nameEn ?? program.name}>
          <div className="section-head">
            <h2>{program.nameEn ?? program.name}</h2>
            <span className="muted">
              {program.school ?? ""} · {program.dataStatus}
            </span>
          </div>
          <Panel>
            <div className="rows">
              {program.fields.length === 0 && <div className="row muted">这个项目没有从这一页入库的要求。</div>}
              {program.fields.map((field) => (
                <div className="row" key={field.key} style={{ gridTemplateColumns: "120px minmax(0, 1fr)", alignItems: "start" }}>
                  <div className="muted">{field.label}</div>
                  <div>
                    <div className="field-values">
                      {field.values.length ? field.values.join("；") : <span className="muted">未入库（库里没有这一项的值）</span>}
                    </div>
                    {field.quotes.map((quote, i) => (
                      <QuoteLine key={i} quote={quote} />
                    ))}
                    {field.quotes.length === 0 && <div className="muted small">没有存引文</div>}
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </section>
      ))}

      <section className="section" aria-labelledby="snap-head">
        <div className="section-head">
          <h2 id="snap-head">快照正文</h2>
          <span className="muted">去掉了导航和页脚；引文已标出。</span>
        </div>
        {detail.pages.map((page) => (
          <Snapshot key={page.url} page={page} quotes={allQuotes.filter((q) => (page.own ? q.sourceUrl === null : q.sourceUrl === page.url))} />
        ))}
      </section>

      <section className="section" aria-labelledby="decide-head">
        <h2 id="decide-head">确认</h2>
        <Panel>
          <div className="panel-pad grid">
            {error && <Notice error>{error}</Notice>}
            {detail.source.verifiedAt ? (
              <div className="toolbar">
                <span>已核验。页面内容变了时，下次导入会自动撤回。</span>
                <Button disabled={busy} onClick={() => act(() => revokePage(detail.source.id))}>撤销核验</Button>
              </div>
            ) : (
              <>
                <label className="toolbar">
                  <input type="checkbox" checked={read} disabled={!gate.enabled} onChange={(e) => setRead(e.target.checked)} />
                  我已逐条对照上面的值、引文和快照，它们和官网这一版一致
                </label>
                <div className="toolbar">
                  <Button
                    variant="primary"
                    disabled={!gate.enabled || !read || busy}
                    onClick={() => act(() => verifyPage(detail))}
                  >
                    确认核验
                  </Button>
                  {gate.reason && <span className="muted">{gate.reason}</span>}
                </div>
              </>
            )}
            {detail.history.length > 0 && (
              <ul className="small muted" style={{ margin: 0, paddingLeft: 18 }} aria-label="核验记录">
                {detail.history.map((h, i) => (
                  <li key={i}>
                    {when(h.at)} {ACTION_LABEL[h.action] ?? h.action}，{h.by ?? "账号已注销"}，快照 <span className="num">{h.contentSha256.slice(0, 12)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Panel>
      </section>
    </div>
  );
}

function QuoteLine({ quote }: { quote: Quote }) {
  return (
    <blockquote className="quote">
      {quote.text}
      {quote.sourceUrl && (
        <span className="muted small">
          {" "}出处：
          {quote.sourceUrl.startsWith("http") ? (
            <a href={quote.sourceUrl} target="_blank" rel="noopener noreferrer">{quote.sourceUrl}</a>
          ) : (
            quote.sourceUrl
          )}
        </span>
      )}
    </blockquote>
  );
}

function Snapshot({ page, quotes }: { page: SnapshotView; quotes: Quote[] }) {
  const label = page.own ? "本页" : "引文出处页";
  if (!page.text) {
    return (
      <Notice>
        {label} {page.url}：没有快照正文。
      </Notice>
    );
  }
  const { segments, missing } = highlightQuotes(page.text, quotes.map((q) => q.text));
  return (
    <details className="panel snapshot-block" open={page.own}>
      <summary className="panel-head">
        <span style={{ overflowWrap: "anywhere" }}>
          {label}：{page.url}
        </span>
        <span className="muted small">
          抓取于 {when(page.fetchedAt)}
          {page.own && page.matchesVersion === false && <span className="negative">，不是入库那一版</span>}
        </span>
      </summary>
      {missing.length > 0 && (
        <div className="panel-pad">
          <Notice error>
            有 <span className="num">{missing.length}</span> 条引文没在这段正文里逐字找到（可能被当成导航去掉了，或跨了段），请打开官网核对：
            {missing.map((m, i) => (
              <div key={i}>「{m}」</div>
            ))}
          </Notice>
        </div>
      )}
      <pre className="snapshot">
        {segments.map((s, i) => (s.mark ? <mark key={i}>{s.text}</mark> : <span key={i}>{s.text}</span>))}
      </pre>
    </details>
  );
}
