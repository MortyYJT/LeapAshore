// The material library adapter, bound to two captured response bodies.
//
// The fixtures are real bodies — `materials-list.fixture.json` is `GET /api/documents` and
// `materials-detail.fixture.json` is `GET /api/documents/{id}` for the same subject — captured from the
// running server while the Genuine Student statement had a review with a finding. They are what makes
// these tests able to fail: an adapter tested against a body typed out from its own declarations
// agrees with itself, which is how `roadmap-source.ts` read `id`/`label` while the wire said
// `key`/`title` and every test still passed.
//
// The fixture carries the two cases the mapping exists for: one material with `kind: null` and one
// classified `gs`, and a finding whose criterion cites the official page with `status: 待核验`.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  KIND_OPTIONS,
  byteSizeLabel,
  kindLabel,
  materialFileUrl,
  overallLabel,
  severityLabel,
  statusLabel,
  toMaterial,
  toMaterials,
  type ServedDocument,
} from "./materials-source.ts";
import type { Material, SourceStatus } from "./types.ts";

const LIST = JSON.parse(
  readFileSync(new URL("./materials-list.fixture.json", import.meta.url), "utf8"),
) as ServedDocument[];

const DETAIL = JSON.parse(
  readFileSync(new URL("./materials-detail.fixture.json", import.meta.url), "utf8"),
) as ServedDocument;

const UNCLASSIFIED = LIST.find((row) => row.kind === null)!;
const CLASSIFIED = LIST.find((row) => row.kind === "gs")!;

test("maps the list without inventing versions or reviews it was not given", () => {
  const materials = toMaterials(LIST);

  assert.equal(materials.length, 2);
  assert.equal(materials[0].versions.length, 0, "the list route does not carry versions");
  assert.equal(materials[0].reviews.length, 0, "the list route does not carry reviews");
  assert.notEqual(materials[0].currentVersion, null, "the list route does carry the current version");
  assert.equal(materials[0].currentVersion!.versionNo, 1);
});

test("an unclassified material reports no kind", () => {
  const material = toMaterial(UNCLASSIFIED);

  assert.equal(material.kind, null);
  assert.equal(kindLabel(material.kind), "未分类", "no kind must not read as 其他");
});

test("a kind this build does not know is unknown, not unclassified and not other", () => {
  const material = toMaterial({ ...UNCLASSIFIED, kind: "diploma" });

  assert.equal(material.kind, "diploma", "the value the server stated has to survive the mapping");
  assert.equal(kindLabel(material.kind), "未知");
  assert.notEqual(kindLabel(material.kind), "未分类");
  assert.notEqual(kindLabel(material.kind), "其他材料");
});

test("the status mapping is exercised through the adapter, not only through the labels", () => {
  // Each case runs the served value through `toMaterial`, which is what the screens read. Calling
  // `statusLabel` alone left the mapping's own normalisation untested: inverting it, or relabelling one
  // state, kept every test green before this one existed.
  const expected: [string, string][] = [
    ["uploaded", "待归档"],
    ["archived", "已归档"],
    ["under_review", "审核中"],
    ["needs_revision", "需要修改"],
    ["accepted", "已通过"],
  ];
  for (const [status, label] of expected) {
    const material = toMaterial({ ...UNCLASSIFIED, status });
    assert.equal(material.status, status);
    assert.equal(statusLabel(material.status), label);
  }

  const unknown = toMaterial({ ...UNCLASSIFIED, status: "restored" });
  assert.equal(unknown.status, null);
  assert.equal(statusLabel(unknown.status), "未知");
});

test("a classification the mapper carries through stays out of the picker's vocabulary", () => {
  // The picker offers only the values in `KIND_OPTIONS`, and that is what keeps an unrecognised
  // classification from being posted back to the route on a click.
  const material = toMaterial({ ...UNCLASSIFIED, kind: "diploma" });
  assert.equal(
    KIND_OPTIONS.some((option) => option.value === material.kind),
    false,
  );
});

test("the download URL is built from the id and the version, and a hostile id cannot escape", () => {
  assert.equal(materialFileUrl("d1", 2), "/api/documents/d1/versions/2/file");
  assert.equal(
    materialFileUrl("../../etc/passwd", 1),
    "/api/documents/..%2F..%2Fetc%2Fpasswd/versions/1/file",
    "the id is server-provided today, and this is the one place it turns into a path",
  );
  assert.equal(materialFileUrl("a b", 1), "/api/documents/a%20b/versions/1/file");
});

test("a classification this build knows is labelled in Chinese", () => {
  assert.equal(kindLabel("transcript"), "成绩单");
  assert.equal(kindLabel("gs"), "Genuine Student 陈述");
  assert.equal(kindLabel("other"), "其他材料");
});

test("the review lifecycle labels every state the server can send", () => {
  assert.equal(statusLabel("uploaded"), "待归档");
  assert.equal(statusLabel("archived"), "已归档");
  assert.equal(statusLabel("under_review"), "审核中");
  assert.equal(statusLabel("needs_revision"), "需要修改");
  assert.equal(statusLabel("accepted"), "已通过");
  assert.equal(statusLabel(null), "未知", "a status this build does not know is not a made-up label");
});

test("the detail carries the versions and the review with its citation", () => {
  const material = toMaterial(DETAIL);

  assert.equal(material.versions.length, 1);
  assert.equal(material.reviews.length, 1);
  const review = material.reviews[0];
  assert.equal(overallLabel(review.overall), "需要修改");
  assert.equal(review.reviewedBy, "审查者");
  assert.equal(review.findings.length, 1);

  const finding = review.findings[0];
  assert.equal(severityLabel(finding.severity), "注意");
  assert.equal(finding.evidenceQuote, null, "a finding that quoted nothing must not read as an empty quote");
  assert.match(finding.criterion.code, /^gs-/);
  assert.equal(finding.criterion.title, "回答长度");
  assert.equal(
    finding.criterion.source.url,
    "https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/student-500/genuine-student-requirement",
    "the citation has to be the official page, or the finding cannot be checked",
  );
  assert.equal(finding.criterion.source.status, "待核验");
});

test("an unverified citation stays unverified and an unknown one does not become verified", () => {
  const unverified: SourceStatus = toMaterial(DETAIL).reviews[0].findings[0].criterion.source.status;
  assert.equal(unverified, "待核验");

  const served = structuredClone(DETAIL);
  served.reviews![0].findings[0].criterion.source.status = "失效";
  const mapped = toMaterial(served);
  assert.equal(
    mapped.reviews[0].findings[0].criterion.source.status,
    "待核验",
    "a status this build has never heard of must not read as 已核验",
  );
});

test("a citation whose page could not be read is null rather than empty", () => {
  const served = structuredClone(DETAIL);
  served.reviews![0].findings[0].criterion.source = { url: null, title: null, status: null };
  const citation = toMaterial(served).reviews[0].findings[0].criterion.source;

  assert.equal(citation.url, null);
  assert.equal(citation.title, null);
  assert.equal(citation.status, "待核验");
});

test("a verdict or severity this build does not know is unknown, not pass and not a blocker", () => {
  const served = structuredClone(DETAIL);
  served.reviews![0].overall = "probably_fine";
  served.reviews![0].findings[0].severity = "catastrophic";
  const review = toMaterial(served).reviews[0];

  assert.equal(review.overall, null);
  assert.equal(overallLabel(review.overall), "未知");
  assert.equal(review.findings[0].severity, null);
  assert.equal(severityLabel(review.findings[0].severity), "未知");
});

test("a material the interface cannot name is a failed read, not a blank row", () => {
  assert.throws(
    () => toMaterial({ ...UNCLASSIFIED, title: "" }),
    /读取材料失败：条目缺少 title/,
  );
});

test("a size nobody recorded stays unknown rather than zero", () => {
  assert.equal(byteSizeLabel(null), "未知");
  // An absent field is not a number at all, and it used to reach the arithmetic and print
  // "undefined B" — which is not a claim about the file's size in either direction.
  assert.equal(byteSizeLabel(undefined as unknown as number), "未知");
  assert.equal(byteSizeLabel(0), "0 B");
  assert.equal(byteSizeLabel(70), "70 B");
  assert.equal(byteSizeLabel(2048), "2 KB");
  assert.equal(byteSizeLabel(3 * 1024 * 1024), "3.0 MB");
});

test("every mapped material keeps the fields the render sites read", () => {
  const materials: Material[] = toMaterials(LIST);

  for (const material of materials) {
    assert.equal(typeof material.id, "string");
    assert.ok(material.id.length > 0);
    assert.equal(typeof material.title, "string");
    assert.equal(typeof material.createdAt, "string");
    assert.equal(typeof kindLabel(material.kind), "string");
    assert.equal(typeof statusLabel(material.status), "string");
  }
});
