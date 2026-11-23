import assert from "node:assert/strict";
import { test } from "node:test";

import {
  addState,
  deadlineNote,
  arrivalOf,
  bandFor,
  catalogueRecordId,
  provisionalRecord,
  recordHref,
  withRecord,
  withoutRecord,
} from "./add-program.ts";
import { addCatalogueProgram, type ApplicationRecord } from "./application-records.ts";
import { EMPTY_PROFILE } from "./assess.ts";
import { peekResource, putResource } from "./resource-cache.ts";
import { PORTFOLIO_KEY } from "./resource-keys.ts";
import type { Profile, Program } from "./types.ts";

function program(overrides: Partial<Program> = {}): Program {
  return {
    slug: "example-msc", university: "示例大学", name: "MSc Example", city: null, degreeLevel: "授课型硕士",
    field: "计算机与数据", duration: null, minimumMark: 75, non211MinimumMark: null, requiresCognate: false,
    prerequisites: [], englishRequirement: "IELTS 6.5，单项不低于 6.0", academicRequirement: null, academicSourceUrl: null, deadlines: [],
    source: { id: "s", title: "t", url: "https://example.edu/msc", excerpt: "", verifiedAt: null, status: "待核验" },
    dataStatus: "待核验",
    universityId: null,
    country: null,
    ...overrides,
  };
}

const complete: Profile = {
  ...EMPTY_PROFILE,
  educationLevel: "本科",
  schoolOrigin: "国内",
  schoolName: "北京邮电大学",
  domesticTier: "211",
  major: "软件工程",
  gpaScore: 85,
  gpaScale: 100,
  targetDegree: "授课型硕士",
  targetField: "计算机与数据",
  englishScore: "IELTS 7",
  intake: "2027 S2",
};

const TODAY = "2026-11-23";

test("a program's control reads from the records and the adds on their way", () => {
  const record = provisionalRecord(program(), TODAY);
  assert.equal(addState(null, new Set(), "example-msc"), "add");
  assert.equal(addState([], new Set(["example-msc"]), "example-msc"), "adding");
  assert.equal(addState([record], new Set(), "example-msc"), "added");
  assert.equal(addState([record], new Set(), "other"), "add");
});

test("去看看 leads to the record on 我的申请, and the page reads it back", () => {
  const href = recordHref(catalogueRecordId("cricos-0100139"));
  assert.equal(href, "/applications?record=catalog%3Acricos-0100139");
  assert.equal(arrivalOf(href.slice(href.indexOf("?"))), "catalog:cricos-0100139");
  assert.equal(arrivalOf(""), null);
});

test("the band is the tiers' own, and flagged for review when they give none", () => {
  const unchecked = { tier: "稳", needsReview: true };
  assert.deepEqual(bandFor(null, program()), unchecked);
  assert.deepEqual(bandFor(EMPTY_PROFILE, program()), unchecked);
  assert.deepEqual(bandFor(complete, program()), { tier: "保", needsReview: false });
  assert.deepEqual(bandFor(complete, program({ minimumMark: 84 })), { tier: "稳", needsReview: false });
  assert.deepEqual(bandFor(complete, program({ minimumMark: 88 })), { tier: "冲", needsReview: false });
  // Nothing to compare: no band is presented as the system's.
  assert.deepEqual(bandFor(complete, program({ minimumMark: null, englishRequirement: null })), unchecked);
  // Short of the stated requirement (不满足): a reach at best, and not the tiers' band.
  assert.deepEqual(bandFor(complete, program({ minimumMark: 95 })), { tier: "冲", needsReview: true });
});

test("the record drawn before the answer takes the catalogue's next date, never one of its own", () => {
  const deadlines = [
    { label: "Round 1", date: "2026-10-01", sourceUrl: "https://example.edu/r1" },
    { label: "Round 2", date: "2027-01-15", sourceUrl: "https://example.edu/r2" },
    { label: "Round 3", date: "2027-03-01", sourceUrl: "https://example.edu/r3" },
  ];
  const drawn = provisionalRecord(program({ deadlines }), TODAY);
  assert.equal(drawn.id, "catalog:example-msc");
  assert.equal(drawn.status, "considering");
  assert.deepEqual([drawn.deadline, drawn.sourceUrl, drawn.deadlineOrigin, drawn.checkedAt], ["2027-01-15", "https://example.edu/r2", "collected", null]);
  const none = provisionalRecord(program(), TODAY);
  assert.deepEqual([none.deadline, none.sourceUrl, none.deadlineOrigin], [null, null, null]);
});

test("the answer replaces the drawn record in place, and a removal takes it out", () => {
  const drawn = provisionalRecord(program(), TODAY);
  const other = { ...drawn, id: "manual-1", programId: null };
  const answered = { ...drawn, version: "v1" };
  assert.deepEqual(withRecord([other], drawn), [other, drawn]);
  assert.deepEqual(withRecord([drawn, other], answered), [answered, other]);
  assert.deepEqual(withoutRecord([drawn, other], drawn.id), [other]);
});

test("the toast says which date the record took and where it came from", () => {
  const base = provisionalRecord(program(), TODAY);
  assert.equal(deadlineNote(base), "截止日期待确认");
  assert.equal(deadlineNote({ ...base, deadline: "2027-01-15", deadlineOrigin: "collected" }), "截止 2027-01-15 · 学校库采集，请复核");
  assert.equal(deadlineNote({ ...base, deadline: "2027-01-15", deadlineOrigin: "entered" }), "截止 2027-01-15 · 待自行核对");
  assert.equal(deadlineNote({ ...base, deadline: "2027-01-15", checkedAt: "2026-11-01T00:00:00Z" }), "截止 2027-01-15");
});

async function answering(status: number, body: unknown, run: () => Promise<unknown>) {
  const original = globalThis.fetch;
  const calls: { url: string; init?: RequestInit }[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
  try {
    return { result: await run().catch((error: unknown) => error), calls };
  } finally {
    globalThis.fetch = original;
  }
}

test("an add sends the program and its band, and says whether it made the record", async () => {
  const record = { ...provisionalRecord(program(), TODAY), version: "v1" } as ApplicationRecord;
  putResource(PORTFOLIO_KEY, []);
  const made = await answering(201, record, () => addCatalogueProgram("example-msc", { tier: "稳", needsReview: false }));
  assert.deepEqual(made.result, { record, created: true });
  assert.equal(made.calls[0].url, "/api/application-records/catalog");
  assert.equal(made.calls[0].init?.method, "POST");
  assert.deepEqual(JSON.parse(String(made.calls[0].init?.body)), { programId: "example-msc", tier: "稳", needsReview: false });
  // The record is a portfolio row: the portfolio kept for the visit is out of date.
  assert.equal(peekResource(PORTFOLIO_KEY), undefined);
  const held = await answering(200, record, () => addCatalogueProgram("example-msc", { tier: "稳", needsReview: true }));
  assert.deepEqual(held.result, { record, created: false });
});

test("a refused add raises the server's reason", async () => {
  const refused = await answering(404, { detail: "学校库里没有这个项目" }, () => addCatalogueProgram("gone", { tier: "稳", needsReview: true }));
  assert.ok(refused.result instanceof Error && refused.result.message === "学校库里没有这个项目");
  const unexplained = await answering(500, null, () => addCatalogueProgram("x", { tier: "稳", needsReview: true }));
  assert.ok(unexplained.result instanceof Error && unexplained.result.message === "没能加入（500）");
});
