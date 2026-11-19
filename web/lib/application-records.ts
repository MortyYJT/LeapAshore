import { beijingToday } from "./deadlines.ts";
import { staleOf } from "./sync-conflict.ts";
export interface ApplicationRecord {
  id: string;
  programId: string | null;
  school: string;
  name: string;
  round: string | null;
  status: string;
  deadline: string | null;
  sourceUrl: string | null;
  checkedAt: string | null;
  deadlineOrigin: string | null;
  materialsReady: boolean;
  materialNotes: string;
  /** Opaque; changes whenever the record does. Sent back as `baseVersion` with an update or removal. */
  version: string;
}
export const RECORD_STATUSES = [
  ["considering", "考虑中"],
  ["applying", "准备中"],
  ["submitted", "已提交"],
  ["offered", "收到录取"],
  ["rejected", "未录取"],
  ["excluded", "已放弃"],
] as const;
export function activeRecord(record: ApplicationRecord) {
  return ["considering", "applying"].includes(record.status);
}
export function attentionRecords(records: ApplicationRecord[]) {
  const active = records.filter(activeRecord);
  return {
    dated: active
      .filter((r) => r.deadline)
      .sort((a, b) => a.deadline!.localeCompare(b.deadline!)),
    undated: active.filter((r) => !r.deadline),
  };
}
export function deadlineLabel(
  record: ApplicationRecord,
  today = beijingToday(),
) {
  if (!record.deadline) return "截止日期待确认";
  const days = Math.round(
    (Date.parse(record.deadline) - Date.parse(today)) / 86400000,
  );
  return `${record.deadline} · ${days < 0 ? "已截止" : days === 0 ? "今天截止" : `还有 ${days} 天`}`;
}
export async function loadApplicationRecords(): Promise<ApplicationRecord[]> {
  const response = await fetch("/api/application-records", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) throw Error(`读取申请失败：${response.status}`);
  return response.json();
}
/**
 * Create (`id` null), update or remove (`payload` absent) one record.
 *
 * - A create sends `options.idempotencyKey`, made once per form with `newIdempotencyKey` and reused
 *   when the applicant saves again. If an earlier attempt already created the record, the server
 *   answers 200 with it instead of creating a second one, and the form is then restated on that
 *   record as an ordinary update, so an edit made between the two attempts is saved.
 * - An update carries `baseVersion` in the payload, and a removal in `options.baseVersion`.
 * - A stale update or removal throws `StaleVersionError` with the record as the server holds it.
 */
export async function writeApplicationRecord(
  id: string | null,
  payload?: object,
  options: { idempotencyKey?: string; baseVersion?: string } = {},
): Promise<ApplicationRecord | null> {
  const path = `/api/application-records${id ? `/${encodeURIComponent(id)}` : ""}`;
  const remove = payload === undefined;
  const response = await fetch(
    remove ? `${path}?baseVersion=${encodeURIComponent(options.baseVersion ?? "")}` : path,
    {
      method: payload ? (id ? "PATCH" : "POST") : "DELETE",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        ...(!id && options.idempotencyKey ? { "Idempotency-Key": options.idempotencyKey } : {}),
      },
      body: payload ? JSON.stringify(payload) : undefined,
    },
  );
  const stale = await staleOf<ApplicationRecord>(response);
  if (stale) throw stale;
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw Error(
      typeof body?.detail === "string"
        ? body.detail
        : "无法保存，请检查填写内容后重试。",
    );
  }
  if (response.status === 204) return null;
  const record = (await response.json()) as ApplicationRecord;
  if (!id && response.status === 200) {
    return writeApplicationRecord(record.id, { ...payload, baseVersion: record.version });
  }
  return record;
}
