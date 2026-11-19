"use client";
import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { RequireAccount } from "@/components/auth/AuthProvider";
import { ConflictNotice, LoadingPanel, Notice } from "@/components/ui";
import { useResource } from "@/lib/hooks/useResource";
import {
  loadApplicationRecords,
  writeApplicationRecord,
  RECORD_STATUSES,
  deadlineLabel,
  type ApplicationRecord,
} from "@/lib/application-records";
import { StaleVersionError, changedFields, newIdempotencyKey } from "@/lib/sync-conflict";
export default function ApplicationsPage() {
  return (
    <main className="page personal-applications">
      <div className="workspace-crumb">我的工作台 / 我的申请</div>
      <h1>我的申请</h1>
      <p className="lede">集中管理每个项目的截止日期、材料和申请进度。</p>
      <RequireAccount what="你的申请">
        <Applications />
      </RequireAccount>
    </main>
  );
}
function Applications() {
  const records = useResource(loadApplicationRecords);
  const [editor, setEditor] = useState<{ record: ApplicationRecord | null; key: number; open: boolean } | null>(null);
  const [filter, setFilter] = useState("all");
  const [deleting, setDeleting] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  function openEditor(record: ApplicationRecord | null) {
    setEditor((previous) => ({ record, key: (previous?.key ?? 0) + 1, open: true }));
  }

  function closeEditor(key: number) {
    setEditor((previous) => previous?.key === key ? { ...previous, open: false } : previous);
  }

  useEffect(() => {
    if (new URLSearchParams(location.search).has("add")) openEditor(null);
  }, []);

  useEffect(() => {
    if (editor?.open) dialog.current?.showModal();
    else dialog.current?.close();
  }, [editor?.open, editor?.key]);
  async function remove(record: ApplicationRecord) {
    setBusy(true);
    setError("");
    try {
      await writeApplicationRecord(record.id, undefined, { baseVersion: record.version });
      setDeleting(null);
      records.reload();
    } catch (e) {
      if (e instanceof StaleVersionError) {
        // The record was edited on another device after this list was read. Nothing was removed; the
        // list is read again so the applicant sees that edit before deciding to remove it.
        setDeleting(null);
        records.reload();
        setError("这条申请已在其他设备上修改，没有移除。列表已更新，确认后可以再次移除。");
      } else setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setBusy(false);
    }
  }
  const rows = (records.data ?? [])
    .filter((r) => filter === "all" || r.status === filter)
    .sort((a, b) => (a.deadline ?? "9999").localeCompare(b.deadline ?? "9999"));
  return (
    <>
      <div className="application-toolbar section">
        <div className="toolbar">
          <button className="btn btn-primary" onClick={() => openEditor(null)}>
            添加申请项目
          </button>
          <Link className="btn btn-secondary" href="/portfolio">
            管理选校组合
          </Link>
        </div>
        <select
          className="select"
          style={{ width: 140 }}
          aria-label="筛选申请状态"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="all">全部状态</option>
          {RECORD_STATUSES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      {error && <Notice error>{error}</Notice>}
      {records.error && <Notice error>{records.error}</Notice>}
      {records.loading && !records.data ? (
        <LoadingPanel what="我的申请" />
      ) : (
        <div className="application-list section">
          {rows.length === 0 ? (
            <section className="panel panel-pad">
              <h2>
                {records.data?.length
                  ? "当前筛选下没有申请"
                  : "从第一份申请开始"}
              </h2>
              <p className="muted">
                手动添加项目，或在学校库选好项目并保存组合。未知的截止日期会保留为待确认。
              </p>
              <Link href="/schools">浏览学校库 →</Link>
            </section>
          ) : (
            rows.map((record) => (
              <article className="panel application-card" key={record.id}>
                <div className="application-card-heading">
                  <div>
                    <div className="small muted">
                      {record.school}
                      {record.round ? ` · ${record.round}` : ""}
                    </div>
                    <h2>{record.name}</h2>
                  </div>
                  <span className="pill pill-neutral">
                    {RECORD_STATUSES.find(([v]) => v === record.status)?.[1] ??
                      record.status}
                  </span>
                </div>
                <div className="application-card-details">
                  <div>
                    <div>{deadlineLabel(record)}</div>
                    <div className="small muted">
                      {record.checkedAt
                        ? `已自行核对 · ${record.checkedAt.slice(0, 10)}`
                        : record.deadlineOrigin === "collected"
                          ? "学校库采集 · 请复核"
                          : "待自行核对"}
                      {record.sourceUrl && (
                        <>
                          {" "}
                          ·{" "}
                          <a
                            href={record.sourceUrl}
                            target="_blank"
                            rel="noreferrer"
                          >
                            查看来源
                          </a>
                        </>
                      )}
                    </div>
                  </div>
                  <span className="muted">
                    {record.materialsReady
                      ? "材料已就绪（自查）"
                      : "材料准备中"}
                  </span>
                </div>
                {record.materialNotes && (
                  <p className="application-notes muted">
                    {record.materialNotes}
                  </p>
                )}
                <div className="application-card-actions">
                  <button
                    className="btn btn-secondary btn-small"
                    onClick={() => openEditor(record)}
                  >
                    编辑申请
                  </button>
                  {record.programId && (
                    <Link
                      className="btn btn-text btn-small"
                      href={`/programs/${encodeURIComponent(record.programId)}`}
                    >
                      项目详情
                    </Link>
                  )}
                  <Link className="btn btn-text btn-small" href="/materials">
                    材料库
                  </Link>
                  {deleting === record.id ? (
                    <>
                      <button
                        disabled={busy}
                        className="btn btn-text btn-small negative"
                        onClick={() => void remove(record)}
                      >
                        确认移除
                      </button>
                      <button
                        className="btn btn-text btn-small"
                        onClick={() => setDeleting(null)}
                      >
                        取消
                      </button>
                    </>
                  ) : (
                    <button
                      className="btn btn-text btn-small muted"
                      onClick={() => setDeleting(record.id)}
                    >
                      移除
                    </button>
                  )}
                </div>
              </article>
            ))
          )}
        </div>
      )}
      <dialog
        ref={dialog}
        className="dialog application-dialog"
        aria-labelledby="application-dialog-title"
        onCancel={() => editor && closeEditor(editor.key)}
      >
        {editor && (
          <ApplicationForm
            key={editor.key}
            record={editor.record}
            onClose={() => closeEditor(editor.key)}
            onSaved={() => {
              closeEditor(editor.key);
              records.reload();
            }}
          />
        )}
      </dialog>
    </>
  );
}
function ApplicationForm({
  record,
  onClose,
  onSaved,
}: {
  record: ApplicationRecord | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // One key per form: saving a new application again after a failure must not create a second one.
  const createKey = useRef(newIdempotencyKey());
  // A save refused because the record changed on another device: this form's edit and the server's record.
  const [conflict, setConflict] = useState<{ payload: Record<string, unknown>; current: ApplicationRecord } | null>(null);
  async function save(payload: Record<string, unknown>, target: ApplicationRecord | null) {
    setBusy(true);
    setError("");
    try {
      await writeApplicationRecord(
        target?.id ?? null,
        target ? { ...payload, baseVersion: target.version } : payload,
        { idempotencyKey: createKey.current },
      );
      onSaved();
    } catch (e) {
      if (e instanceof StaleVersionError) setConflict({ payload, current: e.current as ApplicationRecord });
      else setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const payload = {
      ...(!record?.programId
        ? { school: data.get("school"), name: data.get("name") }
        : {}),
      round: data.get("round") || null,
      status: data.get("status"),
      deadline: data.get("deadline") || null,
      sourceUrl: data.get("sourceUrl") || null,
      confirmDeadline: data.has("confirmDeadline"),
      materialsReady: data.has("materialsReady"),
      materialNotes: data.get("materialNotes"),
    };
    // After a refused save, saving the form again is the applicant's answer to the server's record.
    const target = conflict?.current ?? record;
    setConflict(null);
    await save(conflict ? editOf(payload) : payload, target);
  }
  // What this form changed on the record it was opened on. A confirmed deadline is confirmed as this
  // form shows it, so the three fields it covers travel with the confirmation.
  function editOf(payload: Record<string, unknown>): Record<string, unknown> {
    const confirmed = payload.confirmDeadline
      ? { round: payload.round, deadline: payload.deadline, sourceUrl: payload.sourceUrl }
      : {};
    return { ...changedFields(payload, record), ...confirmed };
  }
  return (
    <form onSubmit={(event) => void submit(event)}>
      <div className="panel-head">
        <h2 id="application-dialog-title">
          {record ? "编辑申请" : "添加申请项目"}
        </h2>
        <button
          type="button"
          className="icon-button"
          aria-label="关闭申请表单"
          onClick={onClose}
        >
          ×
        </button>
      </div>
      <div className="application-form panel-pad">
        {!record?.programId ? (
          <>
            <label>
              学校名称
              <input
                className="input"
                name="school"
                required
                maxLength={200}
                defaultValue={record?.school}
              />
            </label>
            <label>
              项目名称
              <input
                className="input"
                name="name"
                required
                maxLength={300}
                defaultValue={record?.name}
              />
            </label>
          </>
        ) : (
          <p>
            {record.school} · {record.name}
          </p>
        )}
        <label>
          申请轮次
          <input
            className="input"
            name="round"
            maxLength={120}
            placeholder="例如：第一轮，或留空"
            defaultValue={record?.round ?? ""}
          />
        </label>
        <label>
          申请状态
          <select
            className="select"
            name="status"
            defaultValue={record?.status ?? "considering"}
          >
            {RECORD_STATUSES.map(([v, l]) => (
              <option value={v} key={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label>
          截止日期
          <input
            className="input"
            type="date"
            name="deadline"
            defaultValue={record?.deadline ?? ""}
          />
        </label>
        <label>
          日期来源链接
          <input
            className="input"
            name="sourceUrl"
            type="url"
            placeholder="https://…"
            maxLength={2000}
            defaultValue={record?.sourceUrl ?? ""}
          />
        </label>
        <label className="check-label">
          <input type="checkbox" name="confirmDeadline" />
          我已自行核对本轮截止日期与来源
        </label>
        <p className="small muted">
          日期或来源未知可以留空。修改日期、轮次或来源后，需要重新核对；这里的自查不会改变学校库的官方核验状态。
        </p>
        <label className="check-label">
          <input
            type="checkbox"
            name="materialsReady"
            defaultChecked={record?.materialsReady ?? false}
          />
          本项目所需材料已准备好（自查）
        </label>
        <label>
          材料与准备备注
          <textarea
            className="input"
            name="materialNotes"
            maxLength={10000}
            rows={3}
            defaultValue={record?.materialNotes ?? ""}
          />
        </label>
        {error && <Notice error>{error}</Notice>}
        {conflict && (
          <ConflictNotice
            busy={busy}
            onKeepMine={() => void save(editOf(conflict.payload), conflict.current)}
            onTakeTheirs={onSaved}
          >
            这条申请已在其他设备上修改，这次没有保存。保留我的修改只写入你在这里改过的内容。
            {serverDifferences(conflict.payload, conflict.current)}
          </ConflictNotice>
        )}
        <div className="toolbar">
          <button disabled={busy} className="btn btn-primary" type="submit">
            {busy ? "正在保存…" : "保存申请"}
          </button>
          <button
            disabled={busy}
            className="btn btn-secondary"
            type="button"
            onClick={onClose}
          >
            取消
          </button>
        </div>
      </div>
    </form>
  );
}

const FIELD_LABELS: [keyof ApplicationRecord, string][] = [
  ["school", "学校"],
  ["name", "项目"],
  ["round", "轮次"],
  ["status", "状态"],
  ["deadline", "截止日期"],
  ["sourceUrl", "来源链接"],
  ["materialsReady", "材料就绪"],
  ["materialNotes", "备注"],
];

/** The fields where the server's record differs from this form, with the server's value. */
function serverDifferences(payload: Record<string, unknown>, current: ApplicationRecord): string {
  const shown = (key: keyof ApplicationRecord, value: unknown) =>
    key === "status"
      ? (RECORD_STATUSES.find(([v]) => v === value)?.[1] ?? String(value))
      : typeof value === "boolean"
        ? value ? "是" : "否"
        : value ? String(value) : "空";
  const differing = FIELD_LABELS.filter(
    ([key]) => key in payload && (payload[key] ?? "") !== (current[key] ?? ""),
  ).map(([key, label]) => `${label}：${shown(key, current[key])}`);
  return differing.length ? `服务器上的内容：${differing.join("；")}。` : "";
}
