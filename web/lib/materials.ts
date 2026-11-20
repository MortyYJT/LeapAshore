// Application materials on the client (docs/product/PRD-multi-device.md, 3.7).
//
// A record carries two lists. `materials` is what the catalogue collected from the program's official
// page, each entry with the sentence it was read from, the page that sentence is on and the
// applicant's own tick. `customMaterials` is the applicant's own checklist. `materialsExtracted` false
// means nobody has read the program's page for materials yet, which is a different statement from a
// page that asks for nothing. A page that was read and lists no documents is not "asks for nothing"
// either: the list is usually on another page, so the screens say what was read and send the
// applicant to the official page.
//
// A tick is the applicant saying "I have this ready". Nothing here, and nothing on the server, reviews
// a document.

/** The fixed list of material types, in the order the screens list them. Mirrors `app.collect.materials`. */
export const MATERIAL_TYPES = [
  "transcript",
  "language_score",
  "cv",
  "recommendation",
  "personal_statement",
  "test_score",
  "writing_sample",
  "portfolio",
  "other",
] as const;
export type MaterialType = (typeof MATERIAL_TYPES)[number];

const TYPE_LABELS: Record<string, string> = {
  cv: "简历",
  personal_statement: "个人陈述",
  recommendation: "推荐信",
  transcript: "成绩单",
  language_score: "语言成绩",
  test_score: "标化考试成绩",
  portfolio: "作品集",
  writing_sample: "写作样本",
  other: "其他材料",
};
const COUNT_UNITS: Record<string, string> = { recommendation: "封", personal_statement: "篇", writing_sample: "篇" };

/** One material the catalogue collected for a program, as a record serves it. */
export interface RecordMaterial {
  /** The name a tick is sent under. */
  key: string;
  type: string;
  /** How many the page asks for; null when it states no number. */
  count: number | null;
  /** The collector's summary of what is particular about the requirement; not a quotation. */
  note: string | null;
  /** The sentence the entry was read from, verbatim. */
  quote: string;
  sourceUrl: string;
  /** The requirement as it reads now. A tick is sent back with it, so the server knows which wording was ticked. */
  digest: string;
  ready: boolean;
  /** Ticked for an earlier wording of this requirement: it no longer counts, and is worth a second look. */
  changed: boolean;
}

/** One line of the applicant's own checklist. */
export interface CustomMaterial {
  id: string;
  label: string;
  done: boolean;
}

export const CUSTOM_LIMIT = 40;
export const CUSTOM_LABEL_LIMIT = 200;

export function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type;
}

/** `2 封`, `1 份`; empty when the page states no number. */
export function countLabel(type: string, count: number | null): string {
  return count === null ? "" : `${count} ${COUNT_UNITS[type] ?? "份"}`;
}

/** `推荐信 2 封`, `简历`: a requirement in a few words. An `other` entry is named by its note. */
export function materialName(material: Pick<RecordMaterial, "type" | "count" | "note">): string {
  const name = material.type === "other" && material.note ? material.note : typeLabel(material.type);
  const count = countLabel(material.type, material.count);
  return count ? `${name} ${count}` : name;
}

/** An id for a new line of the applicant's own checklist; the `c-` prefix is the server's rule. */
export function newCustomId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(6));
  return `c-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

/** `2/5`, or null for a record that lists nothing to tick. */
export function progressLabel(record: { materialsDone: number; materialsTotal: number }): string | null {
  return record.materialsTotal > 0 ? `${record.materialsDone}/${record.materialsTotal}` : null;
}

/**
 * Whether the record is a catalogue program whose page was read and lists no documents. A record
 * served without its `materials` list (the helpers below take partial records) is never one.
 */
export function listsNone(record: { programId: string | null; materialsExtracted: boolean; materials?: readonly unknown[] }): boolean {
  return Boolean(record.programId) && record.materialsExtracted && record.materials !== undefined && record.materials.length === 0;
}

/**
 * Whether the catalogue holds no requirement for this catalogue program (its page was not read, or
 * lists no documents), so that any count shown for it is of the applicant's own lines only.
 */
export function ownLinesOnly(record: { programId: string | null; materialsExtracted: boolean; materials?: readonly unknown[] }): boolean {
  return Boolean(record.programId) && (!record.materialsExtracted || listsNone(record));
}

/**
 * The words for a record's materials in one short phrase: how many lines are ticked, or why there is
 * no count. `programId` tells a catalogue program whose page has not been read from a manual record.
 */
export function materialsSummary(record: {
  programId: string | null;
  materialsExtracted: boolean;
  materials?: readonly unknown[];
  materialsDone: number;
  materialsTotal: number;
}): string {
  const progress = progressLabel(record);
  const unread = Boolean(record.programId) && !record.materialsExtracted;
  const silent = listsNone(record);
  if (!progress) return unread ? "材料要求还没提取" : silent ? "项目页没列材料" : "还没列材料清单";
  const counted = record.materialsDone === record.materialsTotal ? `材料 ${progress}，都勾了` : `材料 ${progress}`;
  // The count is of the applicant's own lines only: say so, or "all ticked" reads as "nothing else is asked".
  return unread ? `${counted}（自己列的，官网要求还没提取）` : silent ? `${counted}（自己列的，项目页没列材料）` : counted;
}

/**
 * The overview's few words for a record's materials. "就绪" is only said of a list that could be
 * complete: for a program whose page has not been read, or lists no documents, every line ticked
 * means the applicant's own lines are ticked, and that is what it says.
 */
export function overviewMaterials(record: {
  programId: string | null;
  materialsExtracted: boolean;
  materials?: readonly unknown[];
  materialsReady: boolean;
  materialsDone: number;
  materialsTotal: number;
}): string {
  const progress = progressLabel(record);
  if (record.materialsReady) {
    // A record with nothing listed (the signed-out demo's examples) has no count to qualify.
    return progress && ownLinesOnly(record) ? "自列材料已勾完" : "材料已就绪";
  }
  return progress ? `材料 ${progress}` : "材料准备中";
}

/**
 * The ticks to send: only the materials whose state differs from the record's, and for each one being
 * ticked the requirement's digest as this page showed it (`materialBasis`).
 */
export function tickChanges(
  materials: readonly RecordMaterial[],
  ticked: Readonly<Record<string, boolean>>,
): { materialTicks: Record<string, boolean>; materialBasis: Record<string, string> } | null {
  const changed = materials.filter((material) => (ticked[material.key] ?? material.ready) !== material.ready);
  if (!changed.length) return null;
  return {
    materialTicks: Object.fromEntries(changed.map((material) => [material.key, !material.ready])),
    materialBasis: Object.fromEntries(changed.filter((material) => !material.ready).map((material) => [material.key, material.digest])),
  };
}

export function sameCustom(a: readonly CustomMaterial[], b: readonly CustomMaterial[]): boolean {
  return a.length === b.length && a.every((item, index) => item.id === b[index].id && item.label === b[index].label && item.done === b[index].done);
}
