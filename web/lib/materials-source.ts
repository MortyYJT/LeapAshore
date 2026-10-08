// Maps the served material library onto the shape the interface renders.
//
// The field names this file reads are the ones the routes serve, copied from a live response and bound
// by `web/lib/materials-source.test.ts` against `web/lib/materials-list.fixture.json` and
// `web/lib/materials-detail.fixture.json`, both captured bodies. A fixture typed out against this
// module's own declarations would prove nothing: the same mistake has already happened once in this
// repository, when `roadmap-source.ts` read `id`/`label` while the wire said `key`/`title` and every
// test passed anyway.
//
// Two rules the mapping exists to keep, both of them the product's rather than TypeScript's:
//
// - **An unknown stays unknown.** A `kind` nobody has chosen is `null` and renders as 未分类, which is
//   a statement about the applicant's own file; a value this build has never heard of is also `null`
//   and renders as 未知, which is a statement about this build. Collapsing the two would tell an
//   applicant that nobody had classified a file the server says someone did, or worse, that it is
//   `other` — a decision no one took.
// - **A citation this build cannot read is not a citation.** `url` and `title` may be null, and the
//   render sites show 未知 rather than an empty link.

import { UNKNOWN } from "./programs-source.ts";
import { toSourceStatus } from "./source-status.ts";
import type {
  FindingSeverity,
  Material,
  MaterialCitation,
  MaterialCriterion,
  MaterialFinding,
  MaterialKind,
  MaterialReview,
  MaterialStatus,
  MaterialVersion,
  ReviewOverall,
} from "./types";

/** One version row as `GET /api/documents` serves it. */
export interface ServedVersion {
  id: string;
  versionNo: number;
  filename: string;
  mimeType: string;
  byteSize: number;
  sha256: string;
  createdAt: string;
}

export interface ServedCitation {
  url: string | null;
  title: string | null;
  status: string | null;
}

export interface ServedCriterion {
  code: string;
  scope: string;
  title: string;
  description: string;
  source: ServedCitation;
}

export interface ServedFinding {
  id: string;
  severity: string;
  finding: string;
  evidenceQuote: string | null;
  criterion: ServedCriterion;
}

export interface ServedReview {
  id: string;
  versionId: string;
  overall: string;
  summary: string | null;
  reviewedBy: string;
  createdAt: string;
  findings: ServedFinding[];
}

/**
 * One material as the route serves it.
 *
 * Named after the server's own noun, because the route is `/api/documents` and the row is a document:
 * the interface calls the same thing a material — what the applicant uploaded — while the roadmap
 * already uses `ServedMaterial` for the *requirement* to prepare one. The two are different rows in
 * different tables and the names now say so.
 *
 * `versions` and `reviews` are optional because only the detail route carries them; the list route
 * sends the current version alone, so a list body read as a detail would otherwise lose both.
 */
export interface ServedDocument {
  id: string;
  title: string;
  kind: string | null;
  status: string;
  taskId: string | null;
  archivedAt: string | null;
  createdAt: string;
  currentVersion: ServedVersion | null;
  versions?: ServedVersion[];
  reviews?: ServedReview[];
}

/** The kinds this build knows, with the wording the interface shows for each. */
const KIND_LABELS: Record<MaterialKind, string> = {
  transcript: "成绩单",
  cv: "简历",
  ps: "个人陈述",
  recommendation: "推荐信",
  language: "语言成绩",
  passport: "护照",
  gs: "Genuine Student 陈述",
  other: "其他材料",
};

const STATUS_LABELS: Record<MaterialStatus, string> = {
  uploaded: "待归档",
  archived: "已归档",
  under_review: "审核中",
  needs_revision: "需要修改",
  accepted: "已通过",
};

const OVERALL_LABELS: Record<ReviewOverall, string> = {
  pass: "通过",
  needs_revision: "需要修改",
  insufficient_evidence: "证据不足",
};

const SEVERITY_LABELS: Record<FindingSeverity, string> = {
  info: "提示",
  warning: "注意",
  blocker: "阻塞",
};

function isKnown<K extends string>(value: unknown, labels: Record<K, string>): value is K {
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(labels, value);
}

/**
 * The label for a material's classification.
 *
 * `null` is 未分类 — nobody has said what this file is — and a value outside the vocabulary this build
 * knows is 未知, because those are different facts and only one of them is about the applicant. The
 * default is never 其他材料: that is a classification, and the interface may not make one.
 */
export function kindLabel(kind: string | null): string {
  if (kind === null) return "未分类";
  return Object.prototype.hasOwnProperty.call(KIND_LABELS, kind)
    ? KIND_LABELS[kind as MaterialKind]
    : UNKNOWN;
}

export function statusLabel(status: MaterialStatus | null): string {
  return status === null ? UNKNOWN : STATUS_LABELS[status];
}

export function overallLabel(overall: ReviewOverall | null): string {
  return overall === null ? UNKNOWN : OVERALL_LABELS[overall];
}

export function severityLabel(severity: FindingSeverity | null): string {
  return severity === null ? UNKNOWN : SEVERITY_LABELS[severity];
}

/** The kinds the applicant may choose from, in the order the picker shows them. */
export const KIND_OPTIONS: { value: MaterialKind; label: string }[] = (
  Object.keys(KIND_LABELS) as MaterialKind[]
).map((value) => ({ value, label: KIND_LABELS[value] }));

/** Bytes as the interface states them. A size nobody recorded stays unknown rather than 0 B. */
export function byteSizeLabel(bytes: number | null): string {
  // A size that is absent, or not a number at all, is unknown rather than zero: `undefined` used to
  // reach the arithmetic and print "undefined B", which is not a claim about the file's size.
  if (typeof bytes !== "number" || Number.isNaN(bytes)) return UNKNOWN;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function toVersion(served: ServedVersion): MaterialVersion {
  return {
    id: served.id,
    versionNo: served.versionNo,
    filename: served.filename,
    mimeType: served.mimeType,
    byteSize: served.byteSize,
    sha256: served.sha256,
    createdAt: served.createdAt,
  };
}

function toCitation(served: ServedCitation | undefined): MaterialCitation {
  return {
    url: served?.url ?? null,
    title: served?.title ?? null,
    status: toSourceStatus(served?.status),
  };
}

function toCriterion(served: ServedCriterion): MaterialCriterion {
  return {
    code: served.code,
    scope: served.scope,
    title: served.title,
    description: served.description,
    source: toCitation(served.source),
  };
}

function toFinding(served: ServedFinding): MaterialFinding {
  return {
    id: served.id,
    severity: isKnown(served.severity, SEVERITY_LABELS) ? served.severity : null,
    finding: served.finding,
    evidenceQuote: served.evidenceQuote,
    criterion: toCriterion(served.criterion),
  };
}

function toReview(served: ServedReview): MaterialReview {
  return {
    id: served.id,
    versionId: served.versionId,
    overall: isKnown(served.overall, OVERALL_LABELS) ? served.overall : null,
    summary: served.summary,
    reviewedBy: served.reviewedBy,
    createdAt: served.createdAt,
    findings: (served.findings ?? []).map(toFinding),
  };
}

/**
 * One served material as the interface renders it.
 *
 * The title is required: it is what the applicant sees in their own list and what every file they
 * uploaded is identified by, and a material the interface cannot name is not one it can show. The
 * other fields are carried through as they arrive, including the ones this build cannot interpret,
 * which become `null` rather than a guess.
 */
export function toMaterial(served: ServedDocument): Material {
  if (typeof served.title !== "string" || served.title.length === 0) {
    throw new Error("读取材料失败：条目缺少 title");
  }
  return {
    id: served.id,
    title: served.title,
    // Carried through as the server states it, including a value this build cannot name; only a
    // non-string or an empty string is treated as "no classification stated".
    kind: typeof served.kind === "string" && served.kind.length > 0 ? served.kind : null,
    status: isKnown(served.status, STATUS_LABELS) ? served.status : null,
    taskId: served.taskId,
    archivedAt: served.archivedAt,
    createdAt: served.createdAt,
    currentVersion: served.currentVersion ? toVersion(served.currentVersion) : null,
    versions: (served.versions ?? []).map(toVersion),
    reviews: (served.reviews ?? []).map(toReview),
  };
}

export function toMaterials(served: ServedDocument[]): Material[] {
  return served.map(toMaterial);
}

/** The download URL for one stored version, which the browser navigates to rather than fetching. */
export function materialFileUrl(documentId: string, versionNo: number): string {
  return `/api/documents/${encodeURIComponent(documentId)}/versions/${versionNo}/file`;
}
