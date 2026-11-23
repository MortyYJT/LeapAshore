import { beijingToday } from "./deadlines.ts";
import { sameCustom, type CustomMaterial, type RecordMaterial } from "./materials.ts";
import { StaleVersionError, changedFields, staleOf } from "./sync-conflict.ts";
import { APPLICATION_STATUSES } from "./taxonomy.ts";
import { invalidateResource } from "./resource-cache.ts";
import { PORTFOLIO_KEY } from "./resource-keys.ts";
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
  /** What the catalogue collected from the program's official page, each with the applicant's tick. */
  materials: RecordMaterial[];
  /** False for a manual record, and for a program whose page has not been read for materials yet. */
  materialsExtracted: boolean;
  /** The page the materials were read from, when the catalogue holds that snapshot; null or absent otherwise. */
  materialsPageUrl?: string | null;
  /** The applicant's own checklist lines. */
  customMaterials: CustomMaterial[];
  materialsDone: number;
  materialsTotal: number;
  /** Every listed line is ticked (and there is at least one). The applicant's own check, not a review. */
  materialsReady: boolean;
  materialNotes: string;
  /** Opaque; changes whenever the record does. Sent back as `baseVersion` with an update or removal. */
  version: string;
}
/** The statuses as `[value, label]` pairs; the words are `APPLICATION_STATUSES`', so no screen has its own. */
export const RECORD_STATUSES: readonly (readonly [string, string])[] = APPLICATION_STATUSES.map(
  ({ value, label }) => [value, label] as const,
);
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
 *   answers 200 with it instead of creating a second one. When that record says what the form says,
 *   it is the result. When it does not, either the form was changed between the attempts or another
 *   device edited the record since; nothing is written and a `StaleVersionError` carries the stored
 *   record, so the applicant chooses as for any other conflict.
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
  // A record of a catalogue program is a row of the saved portfolio, so that kept value is out of date too.
  invalidateResource(PORTFOLIO_KEY);
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
  if (!id && response.status === 200 && differsFromForm(record, payload as Record<string, unknown>)) {
    throw new StaleVersionError(record, "这条申请已经保存过，服务器上的内容和这里填写的不同。");
  }
  return record;
}

/**
 * Add a school-library program to 我的申请 in one step (`POST /api/application-records/catalog`).
 *
 * `band` is the band it is stored with and whether that is flagged for review (`bandFor` in
 * `add-program.ts`). The server adds the program's portfolio row once: a program
 * already held is answered 200 with its record and nothing is written, so a double click or a retry
 * after a lost answer never makes two. `created` says which of the two happened.
 */
export async function addCatalogueProgram(
  programId: string,
  band: { tier: string; needsReview: boolean },
): Promise<{ record: ApplicationRecord; created: boolean }> {
  const response = await fetch("/api/application-records/catalog", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ programId, tier: band.tier, needsReview: band.needsReview }),
  });
  // The record is a row of the saved portfolio, so that kept value is out of date whatever the answer.
  invalidateResource(PORTFOLIO_KEY);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw Error(typeof body?.detail === "string" ? body.detail : `没能加入（${response.status}）`);
  }
  return { record: (await response.json()) as ApplicationRecord, created: response.status === 201 };
}

/** Whether a stored record says something else than the form that was submitted for it. */
export function differsFromForm(record: ApplicationRecord, form: Record<string, unknown>): boolean {
  const { confirmDeadline, materialTicks, materialBasis: _basis, customMaterials, ...fields } = form;
  // Ticks are sent as changes by key and the checklist as a whole list, so each is compared as such.
  const ticks = (materialTicks ?? {}) as Record<string, boolean>;
  const ticksDiffer = Object.entries(ticks).some(
    ([key, ready]) => (record.materials ?? []).find((material) => material.key === key)?.ready !== ready,
  );
  const customDiffers = Array.isArray(customMaterials) && !sameCustom(customMaterials as CustomMaterial[], record.customMaterials ?? []);
  return (
    Object.keys(changedFields(fields, record)).length > 0 ||
    ticksDiffer ||
    customDiffers ||
    (confirmDeadline === true && !record.checkedAt)
  );
}
