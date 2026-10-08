// Tests for the profile API layer: the merge rule that decides which copy of a field wins, and the
// rollback rule that decides what a failed save restores.
//
// `fetch` is stubbed here, so these run without the backend. The request path itself is covered end
// to end by scripts/e2e-walkthrough.cjs, which drives the real server through the real cookie.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  addMaterialVersion,
  archiveMaterial,
  fetchApplications,
  fetchMaterial,
  fetchMaterials,
  fetchProfile,
  fetchPrograms,
  fetchRoadmapDefinition,
  mergeServerProfile,
  patchProfile,
  patchRoadmapTask,
  replaceApplications,
  replaceRoadmapTasks,
  submitMaterial,
  uploadMaterial,
} from "./api.ts";
import type { TaskReplacePayload } from "./roadmap-sync.ts";
import { EMPTY_PROFILE } from "./store.ts";
import type { Profile } from "./types.ts";

function withFetch<T>(handler: (url: string, init?: RequestInit) => Response, run: () => Promise<T>) {
  const original = globalThis.fetch;
  const calls: { url: string; init?: RequestInit }[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return handler(String(input), init);
  }) as typeof fetch;
  return run()
    .then((value) => ({ value, calls }))
    .finally(() => {
      globalThis.fetch = original;
    });
}

test("a field the server holds wins over the local copy", () => {
  const merged = mergeServerProfile({ schoolName: "北京邮电大学", major: "软件工程" }, EMPTY_PROFILE);
  assert.equal(merged.schoolName, "北京邮电大学");
  assert.equal(merged.major, "软件工程");
});

test("a field the server has never been told does not erase the local answer", () => {
  // A `null` is "this account never told us", and the row a subject starts on is all nulls. Taking
  // those at face value would wipe the answers the applicant just gave on this device, which is the
  // whole reason the merge is not a spread. Null is the only value that means absent; an empty
  // string is an answer, which the next test pins.
  const local: Profile = { ...EMPTY_PROFILE, schoolName: "北京邮电大学", gpaScore: 82, intake: "2027 S1" };
  // The nulls are the wire value the server actually sends, and `Profile` declares these three fields
  // as non-nullable, so the cast is the test saying "this is what a raw response body looks like"
  // rather than a type-correct Partial<Profile>. Building the object as a Partial<Profile> would not
  // type-check at all, which is why the earlier version of this test only passed while nothing
  // type-checked test files.
  const fromServer = {
    schoolName: null,
    gpaScore: null,
    intake: null,
    major: null,
  } as unknown as Partial<Profile>;
  const merged = mergeServerProfile(fromServer, local);
  assert.deepEqual(merged, local);
});

test("an empty string on the server is an answer: it is how a cleared field comes back", () => {
  // The applicant cleared a saved field, `ProfileView` sent `""`, and the server stored it. Reading
  // that as "no answer" let the locally remembered value win, so the old value reappeared on screen
  // while the server held the cleared one — the silent divergence this layer exists to prevent.
  // This test used to name the opposite rule as intended; the rule was decided again deliberately:
  // the server is authoritative, and an explicit empty is an answer.
  const local: Profile = { ...EMPTY_PROFILE, schoolName: "北京邮电大学", englishScore: "IELTS 6.5" };
  assert.equal(mergeServerProfile({ schoolName: "" }, local).schoolName, "");
  assert.equal(mergeServerProfile({ englishScore: "" }, local).englishScore, "");
});

test("a whitespace-only string on the server is an answer too", () => {
  // Nothing in the UI produces one, so the tempting special case is "trim, then compare". It is not
  // taken: if the server holds "  " then that is what the applicant's saved answer is, and treating
  // it as absent would restore exactly the resurrection the test above pins — for the one value that
  // most looks like a deliberate blank.
  const local: Profile = { ...EMPTY_PROFILE, schoolName: "北京邮电大学" };
  assert.equal(mergeServerProfile({ schoolName: "  " }, local).schoolName, "  ");
});

test("clearing a saved field survives the next load", async () => {
  // The whole path in one test: the save of an empty value is accepted by the write-path check, and
  // the value that comes back merges as the answer rather than falling back to the local copy.
  const local: Profile = { ...EMPTY_PROFILE, schoolName: "北京邮电大学" };
  const { value } = await withFetch(
    () => new Response(JSON.stringify({ schoolName: "" }), { status: 200 }),
    () => patchProfile({ schoolName: "" }),
  );
  assert.equal(value.schoolName, "");
  assert.equal(mergeServerProfile(value, local).schoolName, "");
});

test("a numeric zero from the server is a real answer and wins over the local value", () => {
  // 0 is a value, not an absent one: the applicant who reports a zero must not be silently reverted
  // to whatever this device still held.
  const local: Profile = { ...EMPTY_PROFILE, gpaScore: 82 };
  assert.equal(mergeServerProfile({ gpaScore: 0 }, local).gpaScore, 0);
});

test("fetchProfile returns the body the server sent", async () => {
  const { value, calls } = await withFetch(
    () => new Response(JSON.stringify({ schoolName: "北京邮电大学" }), { status: 200 }),
    () => fetchProfile(),
  );
  assert.deepEqual(value, { schoolName: "北京邮电大学" });
  assert.equal(calls[0].url, "/api/profile");
  assert.equal(calls[0].init?.credentials, "same-origin");
});

test("fetchProfile refuses to treat an error page as a profile", async () => {
  await assert.rejects(
    () => withFetch(() => new Response("nope", { status: 502 }), () => fetchProfile()),
    /读取档案失败：502/,
  );
});

test("patchProfile sends only the fields it was given, as PATCH", async () => {
  const { value, calls } = await withFetch(
    () => new Response(JSON.stringify({ major: "软件工程" }), { status: 200 }),
    () => patchProfile({ major: "软件工程" }),
  );
  assert.deepEqual(value, { major: "软件工程" });
  assert.equal(calls[0].init?.method, "PATCH");
  assert.equal(calls[0].init?.body, JSON.stringify({ major: "软件工程" }));
  assert.deepEqual(calls[0].init?.headers, { "Content-Type": "application/json" });
});

test("patchProfile raises on a rejected save so the caller can roll the edit back", async () => {
  await assert.rejects(
    () => withFetch(() => new Response("", { status: 422 }), () => patchProfile({ major: "x" })),
    /保存档案失败：422/,
  );
});

test("patchProfile raises when the server did not store the value it was sent", async () => {
  // A reply is the server's account of what it now holds. If the field that was just sent comes back
  // as something else, the save did not land and the caller has to hear about it: this is the silent
  // divergence where the screen shows the new value and the server keeps the old one.
  await assert.rejects(
    () =>
      withFetch(
        () =>
          new Response(JSON.stringify({ major: "计算机科学与技术", schoolName: "北京邮电大学" }), {
            status: 200,
          }),
        () => patchProfile({ major: "软件工程" }),
      ),
    /保存档案失败：服务器没有按提交的值保存（major）/,
  );
});

test("a reply the column rounded is the same answer, not a divergence", async () => {
  // The regression this pins: `gpaScore` and `annualBudgetCny` are `Numeric(5, 2)` and
  // `Numeric(12, 2)`, so the database rounds anything finer, and comparing the raw numbers with
  // `!==` called that rounding a failed save. Both values below were measured through the running
  // server, and `api/tests/test_profile_api.py` pins the same ones against the real column, so this
  // test fails if the stub ever stops matching what the backend does. On the failure itself: the
  // onboarding caller refuses to advance on a divergence, so a three-decimal GPA on the 4.0/4.3/5.0/
  // 7.0 scales (`3.756`) left a healthy backend blocking the flow at `onboarding`.
  const { value } = await withFetch(
    () =>
      new Response(JSON.stringify({ gpaScore: 85.38, annualBudgetCny: 250000.51 }), { status: 200 }),
    () => patchProfile({ gpaScore: 85.375, annualBudgetCny: 250000.505 }),
  );
  assert.equal(value.gpaScore, 85.38);
  assert.equal(value.annualBudgetCny, 250000.51);
});

test("the rounding matches the column's ties, not binary scaling", async () => {
  // 4.675 * 100 is 467.49999999999994, so a comparison written as `Math.round(value * 100)` would
  // call this stored reply (4.68, measured through the server) a divergence. Same tie class as
  // 85.375, opposite float luck, which is why the digits are rounded as digits.
  const { value } = await withFetch(
    () => new Response(JSON.stringify({ gpaScore: 4.68 }), { status: 200 }),
    () => patchProfile({ gpaScore: 4.675 }),
  );
  assert.equal(value.gpaScore, 4.68);
});

test("a stored value the column cannot explain still raises", async () => {
  // The comparison is narrowed by the column's precision, not by a loose tolerance. Two shapes of a
  // save that did not land: the reply still holds the old value, or it holds something that two
  // decimal places of the sent value could not have produced.
  const replyWith = (body: unknown) => () =>
    new Response(JSON.stringify(body), { status: 200 });
  await assert.rejects(
    () => withFetch(replyWith({ gpaScore: 82 }), () => patchProfile({ gpaScore: 85.375 })),
    /保存档案失败：服务器没有按提交的值保存（gpaScore）/,
  );
  await assert.rejects(
    () => withFetch(replyWith({ gpaScore: 85.4 }), () => patchProfile({ gpaScore: 85.375 })),
    /保存档案失败：服务器没有按提交的值保存（gpaScore）/,
  );
});

test("patchProfile ignores the rest of the profile the server echoes back", async () => {
  // The response carries every field, so only the sent ones are compared. Treating the extra keys as
  // a divergence would fail on every real save, which is what the first version of this check did.
  const body = { major: "软件工程", schoolName: "北京邮电大学", gpaScore: 82 };
  const { value } = await withFetch(
    () => new Response(JSON.stringify(body), { status: 200 }),
    () => patchProfile({ major: "软件工程" }),
  );
  assert.deepEqual(value, body);
});

test("patchProfile does not compare a key the request never sent", async () => {
  // `JSON.stringify` drops a key whose value is `undefined`, so that key was never in the body the
  // server saw and the reply cannot be held to it. Comparing it anyway would report a divergence on
  // a save that landed, and the onboarding caller treats that as "do not advance".
  const { value, calls } = await withFetch(
    () => new Response(JSON.stringify({ major: "软件工程", schoolName: null }), { status: 200 }),
    () => patchProfile({ major: "软件工程", schoolName: undefined }),
  );
  assert.equal(calls[0].init?.body, JSON.stringify({ major: "软件工程" }));
  assert.deepEqual(value, { major: "软件工程", schoolName: null });
});

test("fetchRoadmapDefinition reads the served definition from the shared route", async () => {
  // The route is shared configuration rather than applicant data, so this request differs from the
  // profile calls in nothing but its path. The body is handed back unmapped: turning it into what
  // `buildRoadmap` takes is `roadmap-source.ts`'s job, and doing it here as well would give the same
  // mapping two homes.
  //
  // It is spelled the way the route serves it — `key` and `title`, not `id` and `label` — so this is
  // a check on the contract rather than a restatement of the call.
  const body = {
    phases: [{ key: "selection", title: "锁定申请组合", subtitle: null, offsetDays: 330, sortOrder: 0 }],
    materials: [
      {
        key: "sel-goal",
        phase: "selection",
        title: "明确目标国家与方向",
        detail: "结合预算、就业方向和家庭意见，先锁定国家与专业大类。",
        appliesTo: "all",
        sortOrder: 0,
        source: null,
      },
    ],
  };
  const { value, calls } = await withFetch(
    () => new Response(JSON.stringify(body), { status: 200 }),
    () => fetchRoadmapDefinition(),
  );
  assert.deepEqual(value, body);
  assert.equal(calls[0].url, "/api/roadmap");
  assert.equal(calls[0].init?.credentials, "same-origin");
});

test("fetchRoadmapDefinition rejects an error page so the caller can fall back visibly", async () => {
  // The failure this pins is the one the page has to report: an unreachable definition must not be
  // read as an empty one, or the roadmap would render with no phases and no explanation. The caller
  // catches this, builds from the built-in copy, and says so on screen.
  await assert.rejects(
    () => withFetch(() => new Response("nope", { status: 502 }), () => fetchRoadmapDefinition()),
    /读取路线图定义失败：502/,
  );
});

test("fetchRoadmapDefinition rejects a well-formed 200 that carries no phases", async () => {
  // The blank screen this pins: a route that answers `{"phases":[],"materials":[]}` is well formed and
  // used to be accepted as a definition, so the page replaced the built-in copy with nothing and drew
  // zero phases without a word. An empty phase list is the same claim as an unreachable route — there
  // is nothing to build a roadmap from — so it has to fail the read and reach the caller's catch,
  // which renders the built-in copy and the notice saying so.
  await assert.rejects(
    () =>
      withFetch(
        () => new Response(JSON.stringify({ phases: [], materials: [] }), { status: 200 }),
        () => fetchRoadmapDefinition(),
      ),
    /读取路线图定义失败：响应里没有任何阶段/,
  );
});

test("fetchRoadmapDefinition rejects a 200 whose lists are missing or not lists", async () => {
  // A malformed body is a failure for the same reason, and it is the case a caller cannot recover from
  // on its own: without `phases` the mapping throws inside the caller's `then`, and without
  // `materials` it throws inside the builder's own lookup. Both were reaching the notice by accident.
  // Failing at the read says which list was absent instead.
  await assert.rejects(
    () =>
      withFetch(
        () => new Response(JSON.stringify({ materials: [] }), { status: 200 }),
        () => fetchRoadmapDefinition(),
      ),
    /读取路线图定义失败：响应缺少阶段列表/,
  );
  await assert.rejects(
    () =>
      withFetch(
        () =>
          new Response(JSON.stringify({ phases: [{ key: "visa", title: "签证与行前" }] }), {
            status: 200,
          }),
        () => fetchRoadmapDefinition(),
      ),
    /读取路线图定义失败：响应缺少材料列表/,
  );
});

test("a definition with phases and no materials is still walkable", async () => {
  // The other side of the check: emptiness is judged on the phase list, because that is what produces
  // the timeline. An authored phase whose materials have not been written yet is a thin roadmap, not a
  // broken definition, and refusing it would send the page to the built-in copy for no reason.
  const body = {
    phases: [{ key: "visa", title: "签证与行前", subtitle: null, offsetDays: 30, sortOrder: 6 }],
    materials: [],
  };
  const { value } = await withFetch(
    () => new Response(JSON.stringify(body), { status: 200 }),
    () => fetchRoadmapDefinition(),
  );
  assert.deepEqual(value, body);
});

test("fetchRoadmapDefinition rejects a phase the date arithmetic cannot reach", async () => {
  // The reviewer's stub verbatim: a well-formed 200 whose only phase has no `offsetDays`. It used to
  // be installed as it arrived, and the failure surfaced during render — `addDays(anchor, -undefined)`
  // yields `Invalid Date`, and `toISOString` then throws `RangeError: Invalid time value` from inside
  // `buildRoadmap`'s `.map`, outside the promise chain and therefore outside the caller's `catch`.
  // Measured in a browser before this check: the Next Runtime RangeError overlay, zero phases, and no
  // notice. `phases: [null]` was already caught, because that throws inside the mapping; a phase
  // missing one field was not, which is the asymmetry this closes.
  await assert.rejects(
    () =>
      withFetch(
        () =>
          new Response(
            JSON.stringify({ phases: [{ key: "selection", title: "锁定申请组合" }], materials: [] }),
            { status: 200 },
          ),
        () => fetchRoadmapDefinition(),
      ),
    /读取路线图定义失败：阶段 0（selection）的 offsetDays 不是可用的天数/,
  );
});

test("fetchRoadmapDefinition caps the offset at the range of the date arithmetic", async () => {
  // `Number.isFinite` alone is not the check, and this case is why: 1e9 is finite, fits a Postgres
  // `INTEGER`, and still leaves the `Date` range once multiplied by 86_400_000 against ±8.64e15 ms —
  // the same crash in the same browser, measured. The column has no CHECK and the design intends
  // humans to edit these rows, so the read is the place that has to refuse a value like this.
  await assert.rejects(
    () =>
      withFetch(
        () =>
          new Response(
            JSON.stringify({
              phases: [
                {
                  key: "selection",
                  title: "锁定申请组合",
                  subtitle: null,
                  offsetDays: 1_000_000_000,
                  sortOrder: 0,
                },
              ],
              materials: [],
            }),
            { status: 200 },
          ),
        () => fetchRoadmapDefinition(),
      ),
    /阶段 0（selection）的 offsetDays 不是可用的天数/,
  );

  // The other side of the line: 1e8 days is the range itself and is still inside it for any anchor
  // this app can hold, so a phase carrying it is walkable rather than refused.
  const body = {
    phases: [
      { key: "selection", title: "锁定申请组合", subtitle: null, offsetDays: 100_000_000, sortOrder: 0 },
    ],
    materials: [],
  };
  const { value } = await withFetch(
    () => new Response(JSON.stringify(body), { status: 200 }),
    () => fetchRoadmapDefinition(),
  );
  assert.deepEqual(value, body);
});

test("fetchRoadmapDefinition rejects a phase with no key or no title", async () => {
  const rejects = (phases: unknown, message: RegExp) =>
    assert.rejects(
      () =>
        withFetch(
          () => new Response(JSON.stringify({ phases, materials: [] }), { status: 200 }),
          () => fetchRoadmapDefinition(),
        ),
      message,
    );
  // `null` reached the catch before, but by accident and with the mapper's own message; it is named
  // here rather than left to whatever the mapping happens to throw.
  await rejects([null], /读取路线图定义失败：阶段 0 缺少 key/);
  await rejects([{ title: "锁定申请组合", offsetDays: 330 }], /阶段 0 缺少 key/);
  await rejects([{ key: "selection", title: "", offsetDays: 330 }], /阶段 0（selection）缺少 title/);
});

test("fetchRoadmapDefinition rejects a material with no key, phase or title", async () => {
  // A material's own fields fail differently from a phase's: a missing `key` is the React
  // duplicate-key warning the browser walkthrough treats as a failure, and a missing `phase` groups
  // the requirement under no phase, so it silently never renders — a dropped requirement, which is
  // the failure this product exists to avoid. Neither is a crash, so neither was reachable from the
  // page's `catch` before this check.
  const phase = { key: "selection", title: "锁定申请组合", subtitle: null, offsetDays: 330, sortOrder: 0 };
  const material = {
    key: "sel-goal",
    phase: "selection",
    title: "明确目标国家与方向",
    detail: "结合预算、就业方向和家庭意见，先锁定国家与专业大类。",
    appliesTo: "all",
    sortOrder: 0,
  };
  const rejects = (materials: unknown, message: RegExp) =>
    assert.rejects(
      () =>
        withFetch(
          () => new Response(JSON.stringify({ phases: [phase], materials }), { status: 200 }),
          () => fetchRoadmapDefinition(),
        ),
      message,
    );
  await rejects([{ ...material, key: undefined }], /读取路线图定义失败：材料 0 缺少 key/);
  await rejects([{ ...material, phase: "" }], /材料 0（sel-goal）缺少 phase/);
  await rejects([{ ...material, title: undefined }], /材料 0（sel-goal）缺少 title/);
});

test("fetchRoadmapDefinition refuses a tasks list the mapper cannot walk", async () => {
  // The whole-branch reviewer's four shapes, verbatim, and they all share one property: the checks
  // above accept the body and the mapping does not. `tasks: [null]` throws inside `toTaskRows`
  // (`Cannot read properties of null (reading 'id')`); the other three make `(served ?? []).map` a
  // non-function. None of them used to be the transport's answer, so whether the page showed its
  // fallback depended on the caller having wrapped the mapping step rather than on the read failing.
  // The row below is the ordinary one, embedded in the invalid payloads, so each refusal is about the
  // entry rather than about the body being empty.
  const phase = { key: "selection", title: "锁定申请组合", subtitle: null, offsetDays: 330, sortOrder: 0 };
  const task = {
    id: "0f0f0f0f-0000-0000-0000-000000000000",
    materialKey: "sel-goal",
    programId: "",
    phase: "selection",
    status: "pending",
    suggestedAt: null,
    dueAt: "2026-06-09",
    scheduleOrigin: "suggested",
    origin: "system",
    documentId: null,
    completedAt: null,
    createdAt: "2026-10-07T12:41:51.352633Z",
    updatedAt: "2026-10-07T12:41:51.352633Z",
  };
  const rejects = (tasks: unknown, message: RegExp) =>
    assert.rejects(
      () =>
        withFetch(
          () => new Response(JSON.stringify({ phases: [phase], materials: [], tasks }), { status: 200 }),
          () => fetchRoadmapDefinition(),
        ),
      message,
    );
  await rejects([null], /读取路线图定义失败：任务 0 缺少 id/);
  await rejects([{ ...task, id: undefined }], /任务 0 缺少 id/);
  await rejects([{ ...task, materialKey: "" }], /任务 0（0f0f0f0f-0000-0000-0000-000000000000）缺少 materialKey/);
  await rejects({}, /读取路线图定义失败：响应的任务列表不是列表/);
  await rejects(5, /响应的任务列表不是列表/);
  await rejects("pending", /响应的任务列表不是列表/);

  // The other side of the check, and the reason the array test is written as "present and not a
  // list": `tasks` is absent for a subject who has never stored anything, and that is a walkable
  // definition rather than a broken one.
  const { value } = await withFetch(
    () => new Response(JSON.stringify({ phases: [phase], materials: [] }), { status: 200 }),
    () => fetchRoadmapDefinition(),
  );
  assert.deepEqual(value.tasks, undefined);
});

// The write path. The rule for what may be written is `roadmap-sync.test.ts`'s; these tests are the
// transport: the request the caller's payload turns into, and what counts as "the save did not land".

/** One computed row, as `toReplacePayload` emits it and as the route reads it. */
const PAYLOAD: TaskReplacePayload = {
  applicableKeys: ["spe-cv", "visa-gs"],
  rows: [
    { materialKey: "spe-cv", programId: "", phase: "specialized", dueAt: "2026-06-09", scheduleOrigin: "suggested" },
    { materialKey: "visa-gs", programId: "", phase: "visa", dueAt: "2027-01-15", scheduleOrigin: "suggested" },
  ],
};
const REPLACE_RESULT = { created: 1, updated: 1, removed: 0, kept: 0 };

test("replaceRoadmapTasks sends the applicable keys and the rows as a PUT", async () => {
  // The two lists travel as the route reads them: `applicableKeys` is the caller's statement of what
  // applies this round, and it is deliberately not derived from the rows by the server, so the whole
  // payload has to reach the wire as written. The counts come back and are returned to the caller.
  const { value, calls } = await withFetch(
    () => new Response(JSON.stringify(REPLACE_RESULT), { status: 200 }),
    () => replaceRoadmapTasks(PAYLOAD),
  );
  assert.deepEqual(value, REPLACE_RESULT);
  assert.equal(calls[0].url, "/api/roadmap/tasks");
  assert.equal(calls[0].init?.method, "PUT");
  assert.equal(calls[0].init?.credentials, "same-origin");
  assert.equal(calls[0].init?.body, JSON.stringify(PAYLOAD));
});

test("replaceRoadmapTasks raises on a rejected write so the caller can report it", async () => {
  // A rejected replacement is a roadmap the server did not store. The caller shows a notice; silently
  // resolving would leave the applicant looking at a roadmap that only exists in this tab.
  await assert.rejects(
    () =>
      withFetch(() => new Response("", { status: 422 }), () => replaceRoadmapTasks(PAYLOAD)),
    /保存路线图失败：422/,
  );
});

test("replaceRoadmapTasks raises when the reply says part of the roadmap was not written", async () => {
  // The regression this pins is a save that answered 200 and stored less than it was sent. The counts
  // are the server's own account of what it did, and two rows went out: a reply accounting for one of
  // them is the silent half-save this check exists to turn into an error the page can show. `kept` is
  // not part of it — that counts rows the caller does not own and cannot predict.
  await assert.rejects(
    () =>
      withFetch(
        () => new Response(JSON.stringify({ created: 1, updated: 0, removed: 0, kept: 5 }), { status: 200 }),
        () => replaceRoadmapTasks(PAYLOAD),
      ),
    /保存路线图失败：服务器只写入了 1 行，提交的是 2 行/,
  );
});

test("replaceRoadmapTasks accepts a write that landed as an update rather than a create", async () => {
  // Both counts are the same claim from this side's point of view — "this row is now stored" — so the
  // check is their sum. A recomputation over rows that already exist is all updates, which is the
  // normal case after the first one, and reading it as a failure would block every later recompute.
  const { value } = await withFetch(
    () => new Response(JSON.stringify({ created: 0, updated: 2, removed: 0, kept: 0 }), { status: 200 }),
    () => replaceRoadmapTasks(PAYLOAD),
  );
  assert.equal(value.updated, 2);
});

test("patchRoadmapTask edits one row by id, and returns the row the server stored", async () => {
  // The per-row door, and the reason it is not the replacement: this call is how a tick claims a row
  // for the applicant, which is what takes it out of the recomputation's reach. The reply is the
  // stored row, so it is returned rather than discarded — it carries the server's own `status` and
  // `completedAt`, which is what the caller's optimistic update has to agree with.
  const stored = {
    id: "task-9",
    materialKey: "spe-cv",
    programId: "",
    phase: "specialized",
    status: "completed",
    suggestedAt: null,
    dueAt: "2026-06-09",
    scheduleOrigin: "suggested",
    origin: "user",
    documentId: null,
    completedAt: "2026-10-06T00:00:00Z",
    createdAt: "2026-10-06T00:00:00Z",
    updatedAt: "2026-10-06T00:00:00Z",
  };
  const { value, calls } = await withFetch(
    () => new Response(JSON.stringify(stored), { status: 200 }),
    () => patchRoadmapTask("task-9", { status: "completed" }),
  );
  assert.equal(value.status, "completed");
  assert.equal(value.origin, "user");
  assert.equal(calls[0].url, "/api/roadmap/tasks/task-9");
  assert.equal(calls[0].init?.method, "PATCH");
  assert.equal(calls[0].init?.body, JSON.stringify({ status: "completed" }));
});

test("patchRoadmapTask raises when the tick was not stored", async () => {
  await assert.rejects(
    () =>
      withFetch(() => new Response("", { status: 404 }), () => patchRoadmapTask("task-9", { status: "completed" })),
    /保存材料状态失败：404/,
  );
});

// The catalogue and the portfolio. The mapping those bodies pass through is `programs-source.ts`'s and
// is bound to a captured response there; these are the transport's own claims: the path, the method,
// the payload as `ApplicationIn` reads it, and what counts as a read that failed.

test("fetchPrograms reads the catalogue from its own public route", async () => {
  // Public data: no cookie to ride along, so the request differs from the profile calls in nothing but
  // its path. The body is handed back unmapped — the `name ← nameEn` mapping is `programs-source.ts`'s
  // job, and doing it here too would give that rule two homes.
  const body = [
    {
      slug: "unsw-master-it",
      name: "信息技术硕士",
      nameEn: "Master of Information Technology",
      university: "新南威尔士大学",
      city: "悉尼",
      degreeLevel: "授课型硕士",
      field: "计算机与数据",
      duration: "2 年",
      minimumMark: 65,
      non211MinimumMark: 70,
      requiresCognate: false,
      prerequisites: [],
      englishRequirement: "按 UNSW 英语语言要求核验",
      dataStatus: "待核验",
      source: { url: "https://example.test/x", title: "UNSW", status: "待核验" },
    },
  ];
  const { value, calls } = await withFetch(
    () => new Response(JSON.stringify(body), { status: 200 }),
    () => fetchPrograms(),
  );
  assert.deepEqual(value, body);
  assert.equal(calls[0].url, "/api/programs");
  assert.equal(calls[0].init?.credentials, "same-origin");
});

test("fetchPrograms rejects a body that is not a list of programs", async () => {
  // The catalogue comes from the server now, so "the read failed" is the only lever the page has. A
  // body that is an object — a proxy's error page parsed as JSON, for instance — would otherwise reach
  // `.map` in the caller and throw there, where whether it is reported depends on who wrapped what.
  await assert.rejects(
    () => withFetch(() => new Response(JSON.stringify({ programs: [] }), { status: 200 }), () => fetchPrograms()),
    /读取项目目录失败：响应不是项目列表/,
  );
  await assert.rejects(
    () => withFetch(() => new Response("nope", { status: 502 }), () => fetchPrograms()),
    /读取项目目录失败：502/,
  );
});

test("fetchApplications reads the caller's own portfolio, and refuses a body it cannot walk", async () => {
  const body = [
    {
      id: "row-1",
      programId: "unsw-master-it",
      tier: "冲",
      status: "considering",
      isPrimary: false,
      officialDeadline: null,
      deadlineSourceUrl: null,
      needsReview: false,
      origin: "user",
      program: null,
      createdAt: "2026-10-07T12:41:51.352633Z",
      updatedAt: "2026-10-07T12:41:51.352633Z",
    },
  ];
  const { value, calls } = await withFetch(
    () => new Response(JSON.stringify(body), { status: 200 }),
    () => fetchApplications(),
  );
  assert.deepEqual(value, body);
  assert.equal(calls[0].url, "/api/applications");
  assert.equal(calls[0].init?.credentials, "same-origin");

  await assert.rejects(
    () => withFetch(() => new Response(JSON.stringify({ rows: [] }), { status: 200 }), () => fetchApplications()),
    /读取申请组合失败：响应不是组合列表/,
  );
  await assert.rejects(
    () => withFetch(() => new Response("", { status: 500 }), () => fetchApplications()),
    /读取申请组合失败：500/,
  );
});

test("replaceApplications sends the rows as a PUT and returns the server's counts", async () => {
  // The payload is the whole portfolio, so an empty list is a real statement rather than "nothing to
  // do" — the opposite of the roadmap replacement, whose empty `applicableKeys` is destructive and is
  // skipped by the caller instead. `origin` and `status` are absent by design: the schema forbids
  // unknown keys and the server writes `origin` itself.
  const rows = [
    { programId: "unsw-master-it", tier: "冲" as const, isPrimary: true, needsReview: false },
    { programId: "usyd-master-cs", tier: "保" as const, isPrimary: false, needsReview: true },
  ];
  const counts = { created: 1, updated: 1, kept: 0, removed: 0 };
  const { value, calls } = await withFetch(
    () => new Response(JSON.stringify(counts), { status: 200 }),
    () => replaceApplications(rows),
  );
  assert.deepEqual(value, counts);
  assert.equal(calls[0].url, "/api/applications");
  assert.equal(calls[0].init?.method, "PUT");
  assert.equal(calls[0].init?.credentials, "same-origin");
  assert.equal(calls[0].init?.body, JSON.stringify({ rows }));
});

test("replaceApplications raises on a refused portfolio so the picker can show it", async () => {
  // The route's two refusals (a program named twice, two first choices) are 422s with a message, and a
  // 500 is a server that never took the write. Either way the confirmation did not land, and the
  // caller must not advance: silently resolving would leave the applicant on an application flow built
  // from a portfolio the database does not hold.
  await assert.rejects(
    () =>
      withFetch(
        () => new Response(JSON.stringify({ detail: "..." }), { status: 422 }),
        () =>
          replaceApplications([
            { programId: "unsw-master-it", tier: "冲", isPrimary: true, needsReview: false },
          ]),
      ),
    /保存申请组合失败：422/,
  );
});


// --- the material library -------------------------------------------------------------------------
//
// The rule these pin is the one a refusal has to obey: the server writes its refusals in Chinese for
// the applicant, and a transport that replaced them with "上传失败" would throw away the only part of
// the answer that says what to do about it.

function aJsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

test("an upload sends the file as multipart, with the task when it was given one", async () => {
  const { calls } = await withFetch(
    () => aJsonResponse({ id: "d1", title: "陈述.png" }, 201),
    () => uploadMaterial(new File([new Uint8Array([1, 2, 3])], "陈述.png"), { taskId: "t1" }),
  );

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/documents");
  assert.equal(calls[0].init?.method, "POST");
  const form = calls[0].init?.body as FormData;
  assert.ok(form instanceof FormData, "the body has to be a form; JSON cannot carry a file");
  assert.equal((form.get("file") as File).name, "陈述.png");
  assert.equal(form.get("task_id"), "t1");
  assert.equal(
    (calls[0].init?.headers as Record<string, string> | undefined)?.["Content-Type"],
    undefined,
    "setting the content type by hand removes the multipart boundary the parser needs",
  );
});

test("an upload with no task sends no task field", async () => {
  const { calls } = await withFetch(
    () => aJsonResponse({ id: "d1", title: "陈述.png" }, 201),
    () => uploadMaterial(new File([new Uint8Array([1])], "陈述.png")),
  );

  assert.equal((calls[0].init?.body as FormData).get("task_id"), null);
});

test("a refused upload carries the server's own message", async () => {
  await assert.rejects(
    () =>
      withFetch(
        () => aJsonResponse({ detail: "单个材料不能超过 20 MB。" }, 413),
        () => uploadMaterial(new File([new Uint8Array([1])], "big.pdf")),
      ),
    (error: Error) => error.message === "单个材料不能超过 20 MB。",
  );
});

test("a refusal with no readable detail reports the status instead of an empty message", async () => {
  await assert.rejects(
    () =>
      withFetch(
        () => new Response("<html>gateway</html>", { status: 502 }),
        () => uploadMaterial(new File([new Uint8Array([1])], "a.pdf")),
      ),
    (error: Error) => error.message === "上传材料失败：502",
  );
});

test("archiving sends the kind the applicant chose", async () => {
  const { calls } = await withFetch(
    () => aJsonResponse({ id: "d1", kind: "transcript" }, 200),
    () => archiveMaterial("d1", "transcript"),
  );

  assert.equal(calls[0].url, "/api/documents/d1/archive");
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { kind: "transcript" });
});

test("submitting a material is a POST with no body", async () => {
  const { calls } = await withFetch(
    () => aJsonResponse({ id: "d1", status: "under_review" }, 200),
    () => submitMaterial("d1"),
  );

  assert.equal(calls[0].url, "/api/documents/d1/submit");
  assert.equal(calls[0].init?.method, "POST");
  assert.equal(calls[0].init?.body, undefined);
});

test("a refused submission says which rule refused it", async () => {
  await assert.rejects(
    () =>
      withFetch(
        () => aJsonResponse({ detail: "先给材料归档分类，才能送审。" }, 409),
        () => submitMaterial("d1"),
      ),
    (error: Error) => error.message === "先给材料归档分类，才能送审。",
  );
});

test("adding a version posts the file to the material's versions route", async () => {
  const { calls } = await withFetch(
    () => aJsonResponse({ id: "d1", currentVersion: { versionNo: 2 } }, 201),
    () => addMaterialVersion("d1", new File([new Uint8Array([9])], "成绩单.pdf")),
  );

  assert.equal(calls[0].url, "/api/documents/d1/versions");
  assert.equal((calls[0].init?.body as FormData).get("file") instanceof File, true);
});

test("a material list that is not a list is a failed read", async () => {
  await assert.rejects(
    () => withFetch(() => aJsonResponse({ materials: [] }, 200), () => fetchMaterials()),
    (error: Error) => error.message === "读取材料库失败：响应不是材料列表",
  );
});

test("a material the route cannot serve raises with the status", async () => {
  await assert.rejects(
    () => withFetch(() => aJsonResponse({ detail: "找不到这份材料。" }, 404), () => fetchMaterial("d1")),
    (error: Error) => error.message === "读取材料失败：404",
  );
});
