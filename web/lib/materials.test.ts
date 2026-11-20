import { test } from "node:test";
import assert from "node:assert/strict";
import {
  MATERIAL_TYPES,
  countLabel,
  materialName,
  materialsSummary,
  newCustomId,
  overviewMaterials,
  progressLabel,
  sameCustom,
  tickChanges,
  typeLabel,
  type RecordMaterial,
} from "./materials.ts";
import { differsFromForm, type ApplicationRecord } from "./application-records.ts";

// Made up for these tests: no page says this.
function material(fields: Partial<RecordMaterial> = {}): RecordMaterial {
  return {
    key: "recommendation",
    type: "recommendation",
    count: 2,
    note: null,
    quote: "FIXTURE: Two letters of recommendation.",
    sourceUrl: "https://example.test/apply",
    digest: "d-" + (fields.key ?? "recommendation"),
    ready: false,
    changed: false,
    ...fields,
  };
}

const record: ApplicationRecord = {
  id: "catalog:p1",
  programId: "p1",
  school: "Example",
  name: "MSc",
  round: null,
  status: "applying",
  deadline: null,
  sourceUrl: null,
  checkedAt: null,
  deadlineOrigin: null,
  materials: [material({ ready: true }), material({ key: "cv", type: "cv", count: null })],
  materialsExtracted: true,
  customMaterials: [{ id: "c-1", label: "在读证明", done: false }],
  materialsDone: 1,
  materialsTotal: 3,
  materialsReady: false,
  materialNotes: "",
  version: "v1",
};

test("every type of the fixed list has its own Chinese name", () => {
  const names = MATERIAL_TYPES.map(typeLabel);
  assert.equal(new Set(names).size, MATERIAL_TYPES.length);
  assert.ok(names.every((name) => /[一-鿿]/.test(name)));
});

test("a requirement is named with its count only when the page states one", () => {
  assert.equal(materialName(material()), "推荐信 2 封");
  assert.equal(materialName(material({ type: "cv", count: null })), "简历");
  assert.equal(materialName(material({ type: "personal_statement", count: 1 })), "个人陈述 1 篇");
  assert.equal(countLabel("transcript", 2), "2 份");
  assert.equal(countLabel("transcript", null), "");
});

test("an other entry is named by what the collector called it", () => {
  assert.equal(materialName(material({ type: "other", count: null, note: "course descriptions" })), "course descriptions");
  assert.equal(materialName(material({ type: "other", count: null, note: null })), "其他材料");
});

test("the summary says how far along the list is, or why there is no count", () => {
  assert.equal(materialsSummary(record), "材料 1/3");
  assert.equal(materialsSummary({ ...record, materialsDone: 3 }), "材料 3/3，都勾了");
  // Not read yet is said as such; it is not "0 of 0" and not "nothing needed".
  assert.equal(materialsSummary({ programId: "p1", materialsExtracted: false, materialsDone: 0, materialsTotal: 0 }), "材料要求还没提取");
  assert.equal(materialsSummary({ programId: null, materialsExtracted: false, materialsDone: 0, materialsTotal: 0 }), "还没列材料清单");
  assert.equal(progressLabel({ materialsDone: 0, materialsTotal: 0 }), null);
});

test("own lines all ticked on a program nobody read is not said to be complete", () => {
  const unread = { programId: "p1", materialsExtracted: false, materialsDone: 1, materialsTotal: 1, materialsReady: true };
  assert.equal(materialsSummary(unread), "材料 1/1，都勾了（自己列的，官网要求还没提取）");
  assert.equal(overviewMaterials(unread), "自列材料已勾完");
  // A manual application has no page in the catalogue to wait for; an extracted program has its list.
  assert.equal(overviewMaterials({ ...unread, programId: null }), "材料已就绪");
  assert.equal(overviewMaterials({ ...unread, materialsExtracted: true }), "材料已就绪");
  assert.equal(overviewMaterials({ ...unread, materialsReady: false, materialsDone: 0 }), "材料 0/1");
  assert.equal(overviewMaterials({ ...unread, materialsReady: false, materialsDone: 0, materialsTotal: 0 }), "材料准备中");
  // The signed-out demo's example rows carry the flag and no list.
  assert.equal(overviewMaterials({ ...unread, materialsDone: 0, materialsTotal: 0 }), "材料已就绪");
});

test("only the ticks that changed are sent, each new tick with the wording it was given for", () => {
  assert.equal(tickChanges(record.materials, {}), null);
  assert.equal(tickChanges(record.materials, { recommendation: true, cv: false }), null);
  assert.deepEqual(tickChanges(record.materials, { recommendation: false, cv: true }), {
    materialTicks: { recommendation: false, cv: true },
    // Clearing a tick needs no basis; setting one says which requirement the applicant read.
    materialBasis: { cv: "d-cv" },
  });
  // A key the record does not list is never sent: the server would refuse the whole save.
  assert.equal(tickChanges(record.materials, { portfolio: true }), null);
});

test("a new line of the own checklist gets an id the server accepts", () => {
  const ids = new Set(Array.from({ length: 50 }, newCustomId));
  assert.equal(ids.size, 50);
  for (const id of ids) assert.match(id, /^c-[A-Za-z0-9_-]{1,36}$/);
});

test("two checklists are the same only line for line", () => {
  const lines = [{ id: "c-1", label: "A", done: false }, { id: "c-2", label: "B", done: true }];
  assert.ok(sameCustom(lines, lines.map((line) => ({ ...line }))));
  assert.ok(!sameCustom(lines, [lines[1], lines[0]]));
  assert.ok(!sameCustom(lines, [{ ...lines[0], done: true }, lines[1]]));
  assert.ok(!sameCustom(lines, [lines[0]]));
});

test("a stored record that already holds the form's ticks and lines does not differ from it", () => {
  // What the conflict handling asks after a refused save: is there still anything to choose?
  assert.ok(!differsFromForm(record, { materialTicks: { recommendation: true }, materialBasis: { recommendation: "d-recommendation" } }));
  assert.ok(differsFromForm(record, { materialTicks: { cv: true } }));
  assert.ok(!differsFromForm(record, { customMaterials: [{ id: "c-1", label: "在读证明", done: false }] }));
  assert.ok(differsFromForm(record, { customMaterials: [{ id: "c-1", label: "在读证明", done: true }] }));
  assert.ok(differsFromForm(record, { materialTicks: { portfolio: true } }), "a tick the record does not list is a difference");
});
