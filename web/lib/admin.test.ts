import assert from "node:assert/strict";
import { test } from "node:test";

import { adminErrorMessage, confirmGate, highlightQuotes, verificationQuery, type PageDetail } from "./admin.ts";

test("a quote is marked in the snapshot even when the whitespace differs", () => {
  const text = "Entry requirements\nIELTS 7.0 with\n6.5 in each   component\nApply now";
  const { segments, missing } = highlightQuotes(text, ["IELTS 7.0 with 6.5 in each component"]);
  assert.deepEqual(missing, []);
  assert.equal(segments.map((s) => s.text).join(""), text, "segments must rebuild the text exactly");
  assert.deepEqual(segments.filter((s) => s.mark).map((s) => s.text), ["IELTS 7.0 with\n6.5 in each   component"]);
});

test("every occurrence is marked, overlapping quotes merge, and a quote not on the page is reported", () => {
  const text = "fee A$50,000 a year. fee A$50,000 a year.";
  const { segments, missing } = highlightQuotes(text, ["A$50,000", "fee A$50", "not on the page at all"]);
  assert.deepEqual(segments.filter((s) => s.mark).map((s) => s.text), ["fee A$50,000", "fee A$50,000"]);
  assert.deepEqual(missing, ["not on the page at all"]);
  assert.equal(segments.map((s) => s.text).join(""), text);
});

test("an empty quote marks nothing and is not reported missing", () => {
  const { segments, missing } = highlightQuotes("abc", ["", "   "]);
  assert.deepEqual(segments, [{ text: "abc", mark: false }]);
  assert.deepEqual(missing, []);
});

function detail(overrides: Partial<PageDetail> = {}): PageDetail {
  return {
    source: { id: "s", url: "https://x.edu/msc", title: "MSc", status: "待核验", verifiedAt: null },
    version: { versionNo: 1, contentSha256: "a".repeat(64), fetchedAt: null },
    programs: [],
    pages: [{ url: "https://x.edu/msc", own: true, title: null, snapshotSha256: "a".repeat(64), fetchedAt: null, matchesVersion: true, text: "x" }],
    canVerify: true,
    digest: "d".repeat(64),
    history: [],
    ...overrides,
  };
}

test("the confirm button says why it is off", () => {
  assert.deepEqual(confirmGate(detail()), { enabled: true, reason: null });
  assert.equal(confirmGate(detail({ source: { ...detail().source, status: "已核验", verifiedAt: "2026-10-30T00:00:00Z" }, canVerify: false })).reason, "已核验；要重新核验先撤销。");
  const stale = detail({ canVerify: false, pages: [{ ...detail().pages[0], matchesVersion: false }] });
  assert.equal(confirmGate(stale).reason, "快照库里的这一页不是入库引文那一版，不能确认。");
  const none = detail({ canVerify: false, pages: [{ ...detail().pages[0], text: null, snapshotSha256: null, matchesVersion: false }] });
  assert.equal(confirmGate(none).reason, "没有这一页的快照正文，不能确认。");
  // The server's answer wins: a page it will not confirm is never offered, whatever the page data says.
  assert.equal(confirmGate(detail({ canVerify: false })).enabled, false);
});

test("the list query leaves defaults out", () => {
  assert.equal(verificationQuery({}), "");
  assert.equal(verificationQuery({ status: "unverified", q: "  ", offset: 0 }), "");
  assert.equal(verificationQuery({ status: "verified", q: " 悉尼 ", offset: 50 }), "?status=verified&q=%E6%82%89%E5%B0%BC&offset=50");
});

test("a refusal reads as the server's sentence, or a plain one by status", () => {
  assert.equal(adminErrorMessage(409, { detail: "页面在你打开后有了新版本，请刷新后重新阅读。" }), "页面在你打开后有了新版本，请刷新后重新阅读。");
  assert.equal(adminErrorMessage(403, null), "只有管理员账号能用这个页面。");
  assert.equal(adminErrorMessage(401, {}), "需要先登录。");
  assert.equal(adminErrorMessage(500, { detail: [{ msg: "x" }] }), "请求失败（HTTP 500）。");
});
