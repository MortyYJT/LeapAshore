import { test } from "node:test";
import assert from "node:assert/strict";
import {
  attentionRecords,
  deadlineLabel,
  writeApplicationRecord,
  type ApplicationRecord,
} from "./application-records.ts";
import { StaleVersionError } from "./sync-conflict.ts";
const base: ApplicationRecord = {
  id: "a",
  programId: null,
  school: "Example",
  name: "MSc",
  round: null,
  status: "applying",
  deadline: null,
  sourceUrl: null,
  checkedAt: null,
  deadlineOrigin: null,
  materialsReady: false,
  materialNotes: "",
  version: "v1",
};

interface Call {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: Record<string, unknown> | null;
}

/** Run `run` with `fetch` answering from `replies` in order, and return the calls it made. */
async function withReplies<T>(replies: [number, unknown][], run: () => Promise<T>) {
  const original = globalThis.fetch;
  const calls: Call[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const [status, body] = replies[calls.length];
    calls.push({
      url: String(input),
      method: init?.method ?? "GET",
      headers: (init?.headers ?? {}) as Record<string, string>,
      body: init?.body ? JSON.parse(String(init.body)) : null,
    });
    return new Response(status === 204 ? null : JSON.stringify(body), { status });
  }) as typeof fetch;
  try {
    return { result: await run().then((value) => ({ value }), (error: unknown) => ({ error })), calls };
  } finally {
    globalThis.fetch = original;
  }
}
test("attention separates unknown dates and excludes submitted applications", () => {
  const view = attentionRecords([
    { ...base, id: "late", deadline: "2027-02-01" },
    { ...base, id: "unknown" },
    { ...base, id: "earlier", deadline: "2027-01-01" },
    { ...base, id: "submitted", status: "submitted", deadline: "2026-01-01" },
  ]);
  assert.deepEqual(
    view.dated.map((r) => r.id),
    ["earlier", "late"],
  );
  assert.deepEqual(
    view.undated.map((r) => r.id),
    ["unknown"],
  );
});
test("deadline labels preserve unknown and use calendar-day comparisons", () => {
  assert.equal(deadlineLabel(base, "2027-01-01"), "截止日期待确认");
  assert.equal(
    deadlineLabel({ ...base, deadline: "2027-01-01" }, "2027-01-01"),
    "2027-01-01 · 今天截止",
  );
  assert.equal(
    deadlineLabel({ ...base, deadline: "2027-01-02" }, "2027-01-01"),
    "2027-01-02 · 还有 1 天",
  );
  assert.equal(
    deadlineLabel({ ...base, deadline: "2026-12-31" }, "2027-01-01"),
    "2026-12-31 · 已截止",
  );
});

test("a create carries its idempotency key, and a retry sends the same one", async () => {
  const created = { ...base, id: "new" };
  const { result, calls } = await withReplies([[201, created]], () =>
    writeApplicationRecord(null, { school: "Example", name: "MSc" }, { idempotencyKey: "key-12345678" }),
  );
  assert.deepEqual(result, { value: created });
  assert.equal(calls[0].method, "POST");
  assert.equal(calls[0].headers["Idempotency-Key"], "key-12345678");
});

test("a replayed create restates the form on the record the first attempt made", async () => {
  // The first attempt landed but its answer was lost; the applicant changed the round and saved again.
  const first = { ...base, id: "new", round: "R1", version: "v1" };
  const updated = { ...first, round: "R2", version: "v2" };
  const { result, calls } = await withReplies([[200, first], [200, updated]], () =>
    writeApplicationRecord(null, { school: "Example", name: "MSc", round: "R2" }, { idempotencyKey: "key-12345678" }),
  );
  assert.deepEqual(result, { value: updated });
  assert.equal(calls.length, 2, "no second record is created; the first is updated");
  assert.equal(calls[1].method, "PATCH");
  assert.equal(calls[1].url, "/api/application-records/new");
  assert.deepEqual(calls[1].body, { school: "Example", name: "MSc", round: "R2", baseVersion: "v1" });
});

test("a stale update raises with the record the server holds", async () => {
  const current = { ...base, round: "R9", version: "v9" };
  const { result, calls } = await withReplies(
    [[409, { detail: "这条记录已在其他设备上更新", code: "stale_version", current }]],
    () => writeApplicationRecord("a", { round: "R2", baseVersion: "v1" }),
  );
  assert.equal(calls[0].method, "PATCH");
  assert.ok("error" in result && result.error instanceof StaleVersionError);
  assert.deepEqual((result.error as StaleVersionError<ApplicationRecord>).current, current);
});

test("a removal states the version it saw", async () => {
  const { calls } = await withReplies([[204, null]], () =>
    writeApplicationRecord("catalog:p 1", undefined, { baseVersion: "v1" }),
  );
  assert.equal(calls[0].method, "DELETE");
  assert.equal(calls[0].url, "/api/application-records/catalog%3Ap%201?baseVersion=v1");
});
