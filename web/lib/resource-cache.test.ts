import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import {
  beginRead,
  clearResourceCache,
  finishRead,
  invalidateResource,
  invalidateResources,
  peekResource,
  putResource,
  readStillCurrent,
  sameAccount,
  subscribeResource,
  updateResource,
  type CacheEvent,
} from "./resource-cache.ts";

beforeEach(() => clearResourceCache());

test("nothing read yet: a page has to read first", () => {
  assert.equal(peekResource("profile"), undefined);
});

test("hit: a value read earlier in the visit is there for the next mount", () => {
  assert.equal(finishRead(beginRead("profile"), { intake: "2027 S2", version: 3 }), true);
  assert.deepEqual(peekResource("profile"), { intake: "2027 S2", version: 3 });
});

test("revalidate: a fresh answer that differs replaces the value and tells the pages showing it", () => {
  putResource("documents", [{ id: "a" }]);
  const events: CacheEvent[] = [];
  const stop = subscribeResource("documents", (event) => events.push(event));
  assert.equal(finishRead(beginRead("documents"), [{ id: "a" }, { id: "b" }]), true);
  assert.deepEqual(peekResource("documents"), [{ id: "a" }, { id: "b" }]);
  assert.deepEqual(events, ["changed"]);
  stop();
});

test("revalidate: an equal answer keeps the stored object and tells nobody", () => {
  const stored = [{ id: "a", version: 1 }];
  putResource("documents", stored);
  const events: CacheEvent[] = [];
  subscribeResource("documents", (event) => events.push(event));
  assert.equal(finishRead(beginRead("documents"), [{ id: "a", version: 1 }]), true);
  assert.equal(peekResource("documents"), stored);
  assert.deepEqual(events, []);
});

test("a write wins: a read that left before a save cannot put the old value back", () => {
  putResource("profile", { intake: "2027 S1", version: 1 });
  const background = beginRead("profile");
  // The applicant saves while the background read is in flight; the save's answer is stored.
  putResource("profile", { intake: "2027 S2", version: 2 });
  assert.equal(readStillCurrent(background), false);
  assert.equal(finishRead(background, { intake: "2027 S1", version: 1 }), false);
  assert.deepEqual(peekResource("profile"), { intake: "2027 S2", version: 2 });
});

test("an optimistic edit stored while a read is in flight outdates that read", () => {
  // The roadmap's tick: the kept rows are replaced with the ticked ones (useRoadmap's changeTasks).
  putResource("roadmap", { tasks: [{ id: "t1", status: "pending", version: 1 }] });
  const background = beginRead("roadmap");
  putResource("roadmap", { tasks: [{ id: "t1", status: "completed", version: 1 }] });
  assert.equal(readStillCurrent(background), false);
  assert.equal(finishRead(background, { tasks: [{ id: "t1", status: "pending", version: 1 }] }), false);
  assert.equal(peekResource<{ tasks: { status: string }[] }>("roadmap")!.tasks[0].status, "completed");
  assert.equal(sameAccount(background), true);
});

test("updateResource changes the value in place and outdates reads in flight", () => {
  putResource("documents", [{ id: "a" }]);
  const background = beginRead("documents");
  updateResource<{ id: string }[]>("documents", (previous) => [...(previous ?? []), { id: "b" }]);
  assert.deepEqual(peekResource("documents"), [{ id: "a" }, { id: "b" }]);
  assert.equal(finishRead(background, [{ id: "a" }]), false);
});

test("invalidateResources outdates every key with the prefix and nothing else", () => {
  putResource("tier-programs:计算机", [1]);
  putResource("tier-programs:商科", [2]);
  putResource("programs-by-slug", [3]);
  invalidateResources("tier-programs:");
  assert.equal(peekResource("tier-programs:计算机"), undefined);
  assert.equal(peekResource("tier-programs:商科"), undefined);
  assert.deepEqual(peekResource("programs-by-slug"), [3]);
});

test("invalidate on write: the next mount does not get the pre-write value", () => {
  putResource("portfolio", [{ programSlug: "a" }]);
  const events: CacheEvent[] = [];
  subscribeResource("portfolio", (event) => events.push(event));
  const background = beginRead("portfolio");
  invalidateResource("portfolio");
  assert.equal(peekResource("portfolio"), undefined);
  assert.deepEqual(events, ["invalidated"]);
  // The read that left before the write is dropped; one that leaves after it is stored.
  assert.equal(finishRead(background, [{ programSlug: "a" }]), false);
  assert.equal(peekResource("portfolio"), undefined);
  assert.equal(finishRead(beginRead("portfolio"), [{ programSlug: "a" }, { programSlug: "b" }]), true);
  assert.deepEqual(peekResource("portfolio"), [{ programSlug: "a" }, { programSlug: "b" }]);
});

test("invalidating a key nobody has read is harmless and still outdates reads in flight", () => {
  const background = beginRead("profile");
  invalidateResource("profile");
  assert.equal(finishRead(background, { version: 1 }), false);
  assert.equal(peekResource("profile"), undefined);
});

test("account change: everything is forgotten and pages are told", () => {
  putResource("profile", { email: "a@example.test" });
  putResource("documents", [{ id: "a" }]);
  const events: CacheEvent[] = [];
  subscribeResource("profile", (event) => events.push(event));
  clearResourceCache();
  assert.equal(peekResource("profile"), undefined);
  assert.equal(peekResource("documents"), undefined);
  assert.deepEqual(events, ["cleared"]);
});

test("account change: a read in flight for the previous account is never stored", () => {
  const forPrevious = beginRead("profile");
  clearResourceCache();
  assert.equal(sameAccount(forPrevious), false);
  assert.equal(finishRead(forPrevious, { email: "a@example.test" }), false);
  assert.equal(peekResource("profile"), undefined);
  // Not even for a key that nobody was subscribed to when the account changed.
  const other = beginRead("documents");
  clearResourceCache();
  assert.equal(finishRead(other, [{ id: "a" }]), false);
});

test("an unsubscribed page hears nothing more", () => {
  const events: CacheEvent[] = [];
  const stop = subscribeResource("profile", (event) => events.push(event));
  stop();
  putResource("profile", { version: 1 });
  assert.deepEqual(events, []);
});
