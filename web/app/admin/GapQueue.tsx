"use client";

import { useCallback, useEffect, useState } from "react";

import { Button, Empty, Loading, Notice, Panel } from "@/components/ui";
import { GAP_REASON_LABEL, fetchGap, fetchGaps, reviewGap, type Gap } from "@/lib/admin";

/** The knowledge-gap queue (P2 #1): open gaps, their questions, and the two review decisions. */
export function GapQueue() {
  const [gaps, setGaps] = useState<Gap[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    fetchGaps("open")
      .then((body) => (setGaps(body.gaps), setError(null)))
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  return (
    <section className="section" aria-labelledby="gap-head">
      <div className="section-head">
        <h2 id="gap-head">
          知识缺口<span className="count num">{gaps ? gaps.length : ""}</span>
        </h2>
        <span className="muted">顾问拒答时记下的问题。补采会把学校没采成功的页面重新排队。</span>
      </div>
      {error && <Notice error>{error}</Notice>}
      {!gaps && !error && <Loading what="知识缺口" />}
      {gaps && gaps.length === 0 && <Empty>没有待审的知识缺口。</Empty>}
      {gaps && gaps.length > 0 && (
        <Panel label="知识缺口">
          <div className="rows">
            {gaps.map((gap) => (
              <GapRow key={gap.id} gap={gap} onReviewed={load} />
            ))}
          </div>
        </Panel>
      )}
    </section>
  );
}

function GapRow({ gap, onReviewed }: { gap: Gap; onReviewed: () => void }) {
  const [open, setOpen] = useState<Gap | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const schools = gap.schools.map((s) => s.name ?? s.id).join("、") || "没认出学校";
  const about = [...gap.subjectWords, ...gap.fields, ...gap.topics].join("、");

  const decide = (decision: "recollect" | "dismiss") => {
    setBusy(true);
    reviewGap(gap.id, decision, note)
      .then(() => onReviewed())
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };

  return (
    <div className="row" style={{ gridTemplateColumns: "minmax(0, 1fr)" }}>
      <div className="two-line">
        <div className="l1">
          {schools}
          {about && <span className="muted">（{about}）</span>}
        </div>
        <div className="l2">
          {GAP_REASON_LABEL[gap.reason] ?? gap.reason} · 被问 <span className="num">{gap.reports}</span> 次
          {gap.askers !== null && <>，<span className="num">{gap.askers}</span> 人</>}
          {gap.lastSeenAt && <> · 最近 {gap.lastSeenAt.slice(0, 10)}</>}
        </div>
      </div>
      {open?.questions && (
        <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
          {open.questions.length === 0 && <li className="muted">提问原文没有保存或已过 90 天。</li>}
          {open.questions.map((q, i) => (
            <li key={i}>{q.question}</li>
          ))}
        </ul>
      )}
      {error && <Notice error>{error}</Notice>}
      <div className="toolbar">
        {!open && (
          <Button small variant="text" onClick={() => fetchGap(gap.id).then(setOpen).catch((e: Error) => setError(e.message))}>
            看提问
          </Button>
        )}
        <label htmlFor={`note-${gap.id}`} className="sr-only">审核备注</label>
        <input id={`note-${gap.id}`} className="input" style={{ width: 220, height: 30 }} placeholder="备注（可选）" value={note} onChange={(e) => setNote(e.target.value)} />
        <Button small variant="primary" disabled={busy} onClick={() => decide("recollect")}>补采</Button>
        <Button small disabled={busy} onClick={() => decide("dismiss")}>忽略</Button>
      </div>
    </div>
  );
}
