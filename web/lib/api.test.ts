// Tests for the profile API layer: the merge rule that decides which copy of a field wins, and the
// rollback rule that decides what a failed save restores.
//
// `fetch` is stubbed here, so these run without the backend. The request path itself is covered end
// to end by scripts/e2e-walkthrough.cjs, which drives the real server through the real cookie.

import { test } from "node:test";
import assert from "node:assert/strict";

import { fetchProfile, fetchRoadmapDefinition, mergeServerProfile, patchProfile } from "./api.ts";
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
