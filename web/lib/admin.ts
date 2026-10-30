// The admin pages (openspec source-verification): reading a page's fields, quotes and snapshot before
// confirming it, and the knowledge-gap queue. Every request goes to `/api/admin/...`, which answers 401
// without a session and 403 to anyone but an admin; the pages themselves are 404 to them (D6).

export type VerificationStatus = "unverified" | "verified" | "all";

export interface PageListItem {
  sourceId: string;
  url: string;
  title: string;
  school: string | null;
  status: string;
  verifiedAt: string | null;
  inPortfolios: number;
  fetchedAt: string | null;
  programs: { id: string; name: string; nameEn: string | null; dataStatus: string }[];
  snapshotReady: boolean;
}

export interface Quote {
  text: string;
  sourceUrl: string | null;
}

export interface FieldView {
  key: string;
  label: string;
  values: string[];
  quotes: Quote[];
}

export interface SnapshotView {
  url: string;
  own: boolean;
  title: string | null;
  snapshotSha256: string | null;
  fetchedAt: string | null;
  matchesVersion: boolean | null;
  text: string | null;
}

export interface PageDetail {
  source: { id: string; url: string; title: string; status: string; verifiedAt: string | null };
  version: { versionNo: number; contentSha256: string; fetchedAt: string | null };
  programs: { id: string; name: string; nameEn: string | null; school: string | null; dataStatus: string; fields: FieldView[] }[];
  pages: SnapshotView[];
  canVerify: boolean;
  history: { action: "verify" | "revoke"; at: string; by: string | null; contentSha256: string }[];
}

export interface Gap {
  id: string;
  route: string;
  reason: string;
  schools: { id: string; name: string | null }[];
  fields: string[];
  subjectWords: string[];
  topics: string[];
  reports: number;
  askers: number | null;
  lastSeenAt: string | null;
  status: string;
  reviewNote: string | null;
  reportsSinceReview: number;
  questions?: { question: string; at: string }[];
}

export class AdminApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const FALLBACK: Record<number, string> = {
  401: "需要先登录。",
  403: "只有管理员账号能用这个页面。",
  404: "没有找到。",
};

/** The server's own sentence when it sent one (`detail` as a string), otherwise a plain one by status. */
export function adminErrorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  return FALLBACK[status] ?? `请求失败（HTTP ${status}）。`;
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    headers: init.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new AdminApiError(response.status, adminErrorMessage(response.status, body));
  return body as T;
}

export interface VerificationQuery {
  status?: VerificationStatus;
  q?: string;
  offset?: number;
}

/** The list's query string, leaving the defaults out (unverified, no search, first page). */
export function verificationQuery({ status, q, offset }: VerificationQuery): string {
  const params = new URLSearchParams();
  if (status && status !== "unverified") params.set("status", status);
  if (q && q.trim()) params.set("q", q.trim());
  if (offset) params.set("offset", String(offset));
  const text = params.toString();
  return text ? `?${text}` : "";
}

export const PAGE_SIZE = 50;

export function fetchVerificationPages(query: VerificationQuery) {
  return call<{ items: PageListItem[]; total: number }>(`/api/admin/verification${verificationQuery(query)}`);
}

export function fetchVerificationPage(sourceId: string) {
  return call<PageDetail>(`/api/admin/verification/${encodeURIComponent(sourceId)}`);
}

export function verifyPage(sourceId: string, contentSha256: string) {
  return call<PageDetail>(`/api/admin/verification/${encodeURIComponent(sourceId)}/verify`, {
    method: "POST",
    body: JSON.stringify({ contentSha256 }),
  });
}

export function revokePage(sourceId: string) {
  return call<PageDetail>(`/api/admin/verification/${encodeURIComponent(sourceId)}/revoke`, { method: "POST" });
}

export function fetchGaps(status: "open" | "recollect_queued" | "dismissed" | "all" = "open") {
  return call<{ gaps: Gap[] }>(`/api/admin/knowledge-gaps?status=${status}`);
}

export function fetchGap(id: string) {
  return call<Gap>(`/api/admin/knowledge-gaps/${encodeURIComponent(id)}`);
}

export function reviewGap(id: string, decision: "recollect" | "dismiss", note: string) {
  return call<Gap>(`/api/admin/knowledge-gaps/${encodeURIComponent(id)}/review`, {
    method: "POST",
    body: JSON.stringify({ decision, note: note.trim() || null }),
  });
}

/**
 * Whether the confirm button is offered, and if not, why. The server's `canVerify` decides; the reason
 * is read from the page data so the admin knows what is missing.
 */
export function confirmGate(detail: PageDetail): { enabled: boolean; reason: string | null } {
  if (detail.source.verifiedAt) return { enabled: false, reason: "已核验；要重新核验先撤销。" };
  const own = detail.pages.find((p) => p.own);
  if (!own || !own.text) return { enabled: false, reason: "没有这一页的快照正文，不能确认。" };
  if (!own.matchesVersion) return { enabled: false, reason: "快照库里的这一页不是入库引文那一版，不能确认。" };
  if (!detail.canVerify) return { enabled: false, reason: "服务器不接受确认，请刷新后再看。" };
  return { enabled: true, reason: null };
}

export interface Segment {
  text: string;
  mark: boolean;
}

/**
 * Split `text` into marked and unmarked runs, marking every occurrence of each quote. Runs of whitespace
 * match any other run (the snapshot keeps the page's line breaks, a quote usually does not); the marked
 * runs are the page's own characters. Quotes that occur nowhere are returned in `missing`.
 */
export function highlightQuotes(text: string, quotes: string[]): { segments: Segment[]; missing: string[] } {
  // The text with each whitespace run folded to one space, and where each folded character came from.
  let folded = "";
  const origin: number[] = [];
  for (let i = 0; i < text.length; i++) {
    if (/\s/.test(text[i])) {
      if (folded.endsWith(" ")) continue;
      folded += " ";
    } else {
      folded += text[i];
    }
    origin.push(i);
  }
  const ranges: [number, number][] = [];
  const missing: string[] = [];
  for (const quote of quotes) {
    const needle = quote.replace(/\s+/g, " ").trim();
    if (!needle) continue;
    let from = folded.indexOf(needle);
    if (from === -1) {
      missing.push(quote);
      continue;
    }
    while (from !== -1) {
      const last = from + needle.length - 1;
      ranges.push([origin[from], origin[last] + 1]);
      from = folded.indexOf(needle, from + 1);
    }
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const range of ranges) {
    const top = merged[merged.length - 1];
    if (top && range[0] <= top[1]) top[1] = Math.max(top[1], range[1]);
    else merged.push([...range]);
  }
  const segments: Segment[] = [];
  let at = 0;
  for (const [start, end] of merged) {
    if (start > at) segments.push({ text: text.slice(at, start), mark: false });
    segments.push({ text: text.slice(start, end), mark: true });
    at = end;
  }
  if (at < text.length || segments.length === 0) segments.push({ text: text.slice(at), mark: false });
  return { segments, missing };
}

export const ACTION_LABEL: Record<string, string> = { verify: "确认核验", revoke: "撤销核验" };

export const GAP_REASON_LABEL: Record<string, string> = {
  no_school: "没认出学校",
  school_not_collected: "学校还没有采到数据",
  no_program_in_field: "该方向没有项目数据",
  no_citable_source: "没有可引用的来源",
  no_passage: "页面里没有这个主题的段落",
  nothing_checkable: "回答一句都没过核对",
  school_missing: "多校问题里缺这所",
};
