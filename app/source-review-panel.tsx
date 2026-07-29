"use client";

import { useEffect, useState } from "react";

import {
  ApiProgram,
  ProgramSourceStatus,
  ProgramSourceVersion,
  createAdminProgramSourceVersion,
  fetchAdminProgramSources,
  fetchAdminProgramSourceVersions,
  fetchProgram,
  reviewAdminProgramSourceVersion,
  rollbackAdminProgramSourceVersion,
} from "./api-client";

type SourceReviewPanelProps = {
  token: string;
  sources: ProgramSourceStatus[];
  onSourcesChange: (sources: ProgramSourceStatus[]) => void;
};

const versionStatusLabels: Record<ProgramSourceVersion["status"], string> = {
  pending_review: "待审核",
  published: "当前发布",
  superseded: "已替代",
  rejected: "已拒绝",
};

function formatChangeValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "string" ? value : JSON.stringify(value);
}

function formatTimestamp(value?: string | null): string {
  return value ? new Date(value).toLocaleString("zh-CN") : "—";
}

function formatBytes(value: number): string {
  return value < 1024 ? `${value} B` : `${(value / 1024).toFixed(1)} KiB`;
}

export function SourceReviewPanel({ token, sources, onSourcesChange }: SourceReviewPanelProps) {
  const [requestedSlug, setRequestedSlug] = useState("");
  const [versions, setVersions] = useState<ProgramSourceVersion[]>([]);
  const [loadedSlug, setLoadedSlug] = useState("");
  const [candidateJson, setCandidateJson] = useState("");
  const [candidateOpen, setCandidateOpen] = useState(false);
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedSlug = sources.some((source) => source.program_slug === requestedSlug)
    ? requestedSlug
    : sources[0]?.program_slug ?? "";
  const loading = Boolean(selectedSlug) && loadedSlug !== selectedSlug;

  useEffect(() => {
    if (!selectedSlug) return;
    let active = true;
    void fetchAdminProgramSourceVersions(token, selectedSlug)
      .then((items) => {
        if (!active) return;
        setVersions(items);
        setLoadedSlug(selectedSlug);
      })
      .catch((reason: Error) => {
        if (!active) return;
        setError(reason.message);
        setLoadedSlug(selectedSlug);
      });
    return () => { active = false; };
  }, [selectedSlug, token]);

  const currentVersion = loading ? null : versions.find((version) => version.status === "published") ?? null;

  async function refreshSourceData() {
    const [nextVersions, nextSources] = await Promise.all([
      fetchAdminProgramSourceVersions(token, selectedSlug),
      fetchAdminProgramSources(token),
    ]);
    setVersions(nextVersions);
    onSourcesChange(nextSources);
  }

  async function openCandidateEditor() {
    if (!selectedSlug) return;
    setBusyAction("prepare");
    setError("");
    setNotice("");
    try {
      const program = await fetchProgram(selectedSlug);
      setCandidateJson(JSON.stringify(program, null, 2));
      setCandidateOpen(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "暂时无法读取当前发布事实");
    } finally {
      setBusyAction(null);
    }
  }

  async function submitCandidate(captureSnapshot: boolean) {
    if (!currentVersion) return;
    let proposed: ApiProgram;
    try {
      proposed = JSON.parse(candidateJson) as ApiProgram;
    } catch {
      setError("候选 JSON 格式无效，请修正后重试");
      return;
    }
    if (proposed.slug !== selectedSlug) {
      setError("候选项目 slug 必须与当前所选项目一致");
      return;
    }
    setBusyAction(captureSnapshot ? "candidate-snapshot" : "candidate");
    setError("");
    setNotice("");
    try {
      await createAdminProgramSourceVersion(
        token,
        selectedSlug,
        currentVersion.content_hash,
        proposed,
        captureSnapshot,
      );
      await refreshSourceData();
      setCandidateOpen(false);
      setNotice(captureSnapshot
        ? "官网正文已受限抓取并随候选留存，请核对快照与字段差异后再决定是否发布。"
        : "候选已生成，请核对字段差异后再决定是否发布。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "候选创建失败");
    } finally {
      setBusyAction(null);
    }
  }

  async function reviewVersion(version: ProgramSourceVersion, decision: "approve" | "reject") {
    const note = reviewNotes[version.version_id]?.trim() ?? "";
    if (!note) return;
    setBusyAction(`${decision}:${version.version_id}`);
    setError("");
    setNotice("");
    try {
      await reviewAdminProgramSourceVersion(token, selectedSlug, version.version_id, decision, note);
      await refreshSourceData();
      setNotice(decision === "approve" ? "候选已批准并成为当前发布版本。" : "候选已拒绝，发布事实未变化。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "审核操作失败");
    } finally {
      setBusyAction(null);
    }
  }

  async function rollbackVersion(version: ProgramSourceVersion) {
    const note = reviewNotes[version.version_id]?.trim() ?? "";
    if (!note) return;
    setBusyAction(`rollback:${version.version_id}`);
    setError("");
    setNotice("");
    try {
      await rollbackAdminProgramSourceVersion(token, selectedSlug, version.version_id, note);
      await refreshSourceData();
      setNotice("已回滚到所选历史内容，并创建新的发布审计版本。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "回滚操作失败");
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <section className="source-governance-panel" aria-labelledby="source-review-title">
      <div className="source-review-toolbar">
        <label>
          选择项目
          <select value={selectedSlug} onChange={(event) => {
            const nextSlug = event.target.value;
            if (nextSlug === selectedSlug) return;
            setRequestedSlug(nextSlug);
            setVersions([]);
            setCandidateOpen(false);
            setNotice("");
            setError("");
          }}>
            {sources.map((source) => <option key={source.program_slug} value={source.program_slug}>{source.title}</option>)}
          </select>
        </label>
        <div>
          <h4 id="source-review-title">版本审核工作台</h4>
          <small>{currentVersion ? `当前 SHA-256 ${currentVersion.content_hash.slice(0, 16)}` : "正在读取发布版本"}</small>
        </div>
        <button className="outline-button" type="button" disabled={!currentVersion || busyAction !== null} onClick={() => void openCandidateEditor()}>
          {busyAction === "prepare" ? "正在准备…" : "基于当前版本创建候选"}
        </button>
      </div>

      {candidateOpen && (
        <div className="source-candidate-editor">
          <label>
            候选 Program JSON
            <textarea value={candidateJson} onChange={(event) => setCandidateJson(event.target.value)} spellCheck={false} />
          </label>
          <p>只提交可由官网证据复核的事实，并同步更新 source.excerpt 与 source.verified_at。“抓取官网”会校验官方域名、DNS、重定向、类型和大小，再把正文快照与 hash 留在待审核版本；两种方式都不会自动发布。</p>
          <div className="source-action-row">
            <button className="text-button" type="button" onClick={() => setCandidateOpen(false)}>取消</button>
            <button className="outline-button" type="button" disabled={busyAction !== null || !candidateJson.trim()} onClick={() => void submitCandidate(false)}>
              {busyAction === "candidate" ? "正在生成…" : "生成字段差异"}
            </button>
            <button className="primary-button" type="button" disabled={busyAction !== null || !candidateJson.trim()} onClick={() => void submitCandidate(true)}>
              {busyAction === "candidate-snapshot" ? "正在安全抓取…" : "抓取官网并生成候选"}
            </button>
          </div>
        </div>
      )}

      {notice && <p className="form-success" aria-live="polite">{notice}</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
      {loading && <p className="muted-copy">正在读取版本历史…</p>}

      {!loading && (
        <div className="source-version-list">
          {versions.map((version) => {
            const note = reviewNotes[version.version_id] ?? "";
            const actionBusy = busyAction !== null;
            return (
              <article className={`source-version-card source-version-${version.status}`} key={version.version_id}>
                <div className="source-version-heading">
                  <div>
                    <span className={`status-chip source-status-${version.status}`}>{versionStatusLabels[version.status]}</span>
                    <strong>{version.version_id}</strong>
                    <small>SHA-256 {version.content_hash} · 提交 {formatTimestamp(version.submitted_at)}</small>
                  </div>
                  {version.rollback_of && <em>回滚自 {version.rollback_of}</em>}
                </div>

                {version.changes.length > 0 ? (
                  <div className="source-diff-list" aria-label={`${version.version_id} 字段差异`}>
                    {version.changes.map((change) => (
                      <div key={change.field}>
                        <code>{change.field}</code>
                        <span><small>发布前</small>{formatChangeValue(change.before)}</span>
                        <span><small>候选值</small>{formatChangeValue(change.after)}</span>
                      </div>
                    ))}
                  </div>
                ) : <p className="muted-copy">种子或审计发布版本，没有独立字段差异记录。</p>}

                {version.source_snapshot && (
                  <details className="source-snapshot">
                    <summary>官网正文快照 · SHA-256 {version.source_snapshot.content_sha256.slice(0, 16)}</summary>
                    <dl>
                      <div><dt>抓取时间</dt><dd>{formatTimestamp(version.source_snapshot.fetched_at)}</dd></div>
                      <div><dt>最终 URL</dt><dd>{version.source_snapshot.final_url}</dd></div>
                      <div><dt>响应</dt><dd>{version.source_snapshot.content_type} · {formatBytes(version.source_snapshot.content_bytes)} · {version.source_snapshot.redirect_chain.length} 次跳转</dd></div>
                    </dl>
                    <pre>{version.source_snapshot.body_text.slice(0, 12000)}</pre>
                    {version.source_snapshot.body_text.length > 12000 && <small>界面只预览前 12,000 字符；完整正文仍保存在版本记录中。</small>}
                  </details>
                )}

                {version.reviewed_at && <p className="source-review-meta">审核 {formatTimestamp(version.reviewed_at)} · {version.review_note || "未填写备注"}</p>}

                {(version.status === "pending_review" || version.status === "superseded") && (
                  <div className="source-review-actions">
                    <label>
                      {version.status === "pending_review" ? "审核备注" : "回滚备注"}
                      <input value={note} onChange={(event) => setReviewNotes((items) => ({ ...items, [version.version_id]: event.target.value }))} placeholder="记录证据、判断或回滚原因" />
                    </label>
                    {version.status === "pending_review" ? (
                      <div>
                        <button className="outline-button" type="button" disabled={!note.trim() || actionBusy} onClick={() => void reviewVersion(version, "reject")}>拒绝候选</button>
                        <button className="primary-button" type="button" disabled={!note.trim() || actionBusy} onClick={() => void reviewVersion(version, "approve")}>批准发布</button>
                      </div>
                    ) : (
                      <button className="outline-button" type="button" disabled={!note.trim() || actionBusy} onClick={() => void rollbackVersion(version)}>回滚到此版本</button>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
