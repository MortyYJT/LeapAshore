import { beijingToday } from "./deadlines.ts";
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
export async function writeApplicationRecord(
  id: string | null,
  payload?: object,
) {
  const response = await fetch(
    `/api/application-records${id ? `/${encodeURIComponent(id)}` : ""}`,
    {
      method: payload ? (id ? "PATCH" : "POST") : "DELETE",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: payload ? JSON.stringify(payload) : undefined,
    },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw Error(
      typeof body?.detail === "string"
        ? body.detail
        : "无法保存，请检查填写内容后重试。",
    );
  }
  return response.status === 204 ? null : response.json();
}
