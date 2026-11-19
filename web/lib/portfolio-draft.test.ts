import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DRAFT_KEY,
  addToDraft,
  clearDraft,
  draftChanged,
  draftDifferences,
  readDraft,
  readDraftBase,
  removeFromDraft,
  setPrimary,
  setStatus,
  writeDraft,
} from "./portfolio-draft.ts";
import type { PortfolioItem } from "./types.ts";

const item = (slug: string, overrides: Partial<PortfolioItem> = {}): PortfolioItem => ({
  programSlug: slug,
  program: { university: "悉尼大学", nameEn: slug },
  tier: "稳",
  confirmed: true,
  needsReview: false,
  isPrimary: false,
  status: "considering",
  ...overrides,
});

/** A stand-in for `sessionStorage`. */
function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() { return data.size; },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => void data.set(key, value),
  };
}

test("a tiered program is added with its band and starts as considering", () => {
  const draft = addToDraft([], { programSlug: "a", program: null, tier: "冲", needsReview: false });
  assert.equal(draft.length, 1);
  assert.equal(draft[0].tier, "冲");
  assert.equal(draft[0].status, "considering");
  assert.equal(draft[0].isPrimary, false);
});

test("an untiered program keeps the band the applicant picked and is flagged for review", () => {
  const [row] = addToDraft([], { programSlug: "b", program: null, tier: "保", needsReview: true });
  assert.equal(row.tier, "保");
  assert.equal(row.needsReview, true);
});

test("adding a program already in the draft changes its band, not the row count", () => {
  const draft = addToDraft([item("a", { status: "applying" })], { programSlug: "a", program: null, tier: "冲", needsReview: false });
  assert.equal(draft.length, 1);
  assert.equal(draft[0].tier, "冲");
  assert.equal(draft[0].status, "applying");
});

test("marking another program moves the first choice", () => {
  const draft = setPrimary([item("a", { isPrimary: true }), item("b")], "b");
  assert.deepEqual(draft.map((r) => r.isPrimary), [false, true]);
  assert.deepEqual(setPrimary(draft, null).map((r) => r.isPrimary), [false, false]);
});

test("a status change touches one row", () => {
  const draft = setStatus([item("a"), item("b")], "b", "offered");
  assert.deepEqual(draft.map((r) => r.status), ["considering", "offered"]);
});

test("removing the first choice leaves no first choice rather than promoting another", () => {
  const draft = removeFromDraft([item("a", { isPrimary: true }), item("b")], "a");
  assert.deepEqual(draft.map((r) => [r.programSlug, r.isPrimary]), [["b", false]]);
});

test("a draft that restates the saved portfolio is not a change", () => {
  const saved = [item("a"), item("b", { isPrimary: true })];
  assert.equal(draftChanged([...saved].reverse(), saved), false);
  assert.equal(draftChanged(setStatus(saved, "a", "submitted"), saved), true);
  assert.equal(draftChanged(saved.slice(1), saved), true);
});

test("the draft survives in session storage and a damaged copy is ignored", () => {
  const storage = memoryStorage();
  assert.equal(readDraft(storage), null);
  writeDraft(storage, [item("a")]);
  assert.deepEqual(readDraft(storage)?.map((r) => r.programSlug), ["a"]);
  storage.setItem(DRAFT_KEY, "{not json");
  assert.equal(readDraft(storage), null);
  storage.setItem(DRAFT_KEY, JSON.stringify([{ programSlug: "a", tier: "大" }]));
  assert.equal(readDraft(storage), null);
  writeDraft(storage, [item("a")]);
  clearDraft(storage);
  assert.equal(readDraft(storage), null);
});

test("the draft remembers the saved rows it was first made from", () => {
  const storage = memoryStorage();
  const saved = [item("a", { rowId: "row-a", version: 2 }), item("b", { rowId: "row-b", version: 1 })];
  assert.equal(readDraftBase(storage), null);
  writeDraft(storage, removeFromDraft(saved, "b"), saved);
  assert.deepEqual(readDraftBase(storage), [{ id: "row-a", version: 2 }, { id: "row-b", version: 1 }]);

  // A later edit, after another device changed the portfolio and this page read it again, must not
  // move the base: the draft is still the one made from the older rows.
  const newer = [item("a", { rowId: "row-a", version: 5 })];
  writeDraft(storage, [item("a"), item("c")], newer);
  assert.deepEqual(readDraftBase(storage), [{ id: "row-a", version: 2 }, { id: "row-b", version: 1 }]);

  clearDraft(storage);
  assert.equal(readDraftBase(storage), null);
  writeDraft(storage, [item("c")], newer);
  assert.deepEqual(readDraftBase(storage), [{ id: "row-a", version: 5 }]);
});

test("a draft made without a readable portfolio claims an empty one; an older build's draft has no base", () => {
  const storage = memoryStorage();
  writeDraft(storage, [item("a")], []);
  assert.deepEqual(readDraftBase(storage), []);
  clearDraft(storage);
  // The portfolio could not be read, so the draft started from nothing. Stating an empty base makes
  // the server refuse the confirm if a portfolio does exist, instead of replacing it unseen.
  writeDraft(storage, [item("a")], null);
  assert.deepEqual(readDraftBase(storage), []);
  clearDraft(storage);
  storage.setItem(DRAFT_KEY, JSON.stringify([item("a")]));
  assert.equal(readDraftBase(storage), null);
});

test("the differences between a draft and the server's portfolio name every program that would change", () => {
  const mine = [item("a"), item("b", { status: "considering" }), item("mine-only")];
  const theirs = [item("a"), item("b", { status: "submitted" }), item("theirs-only")];
  assert.deepEqual(draftDifferences(mine, theirs), {
    onlyMine: ["mine-only"],
    onlyTheirs: ["theirs-only"],
    // In both, but confirming the draft would put this row back to what the draft says.
    changed: ["b"],
  });
  assert.deepEqual(draftDifferences(mine, mine), { onlyMine: [], onlyTheirs: [], changed: [] });
});
