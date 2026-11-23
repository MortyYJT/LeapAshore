import assert from "node:assert/strict";
import { test } from "node:test";

import { IDLE, SKELETON_WAIT_MS, entersOnSwitch, nextPhase, revealIn, revealed, type LoadPhase } from "./motion.ts";

test("a placeholder holds its bars back first", () => {
  const { next, fade } = nextPhase(IDLE, true, 1000, false);
  assert.deepEqual(next, { phase: "wait", since: 1000 });
  assert.equal(fade, false);
});

test("data that lands before the bars were painted is drawn with no fade", () => {
  const waiting = nextPhase(IDLE, true, 1000, false).next;
  const at = 1000 + SKELETON_WAIT_MS - 1;
  const { next, fade } = nextPhase(revealed(waiting, at), false, at, false);
  assert.deepEqual(next, IDLE);
  assert.equal(fade, false);
});

test("content that replaces painted bars fades in", () => {
  const waiting = nextPhase(IDLE, true, 1000, false).next;
  const shown = revealed(waiting, 1000 + SKELETON_WAIT_MS);
  assert.equal(shown.phase, "shown");
  const { next, fade } = nextPhase(shown, false, 1400, false);
  assert.deepEqual(next, IDLE);
  assert.equal(fade, true);
});

test("content already in memory never had a placeholder and never fades", () => {
  assert.deepEqual(nextPhase(IDLE, false, 1000, false), { next: IDLE, fade: false });
});

test("a placeholder handing over to another keeps the phase and its start", () => {
  const shown: LoadPhase = { phase: "shown", since: 500 };
  assert.deepEqual(nextPhase(shown, true, 900, false).next, shown);
  const waiting: LoadPhase = { phase: "wait", since: 500 };
  assert.deepEqual(nextPhase(waiting, true, 540, false), { next: waiting, fade: false });
  // The second placeholder is revealed on the first one's clock, not its own.
  assert.equal(revealIn(waiting, 540), SKELETON_WAIT_MS - 40);
});

test("one block arriving while another is still loading fades in once the bars were painted", () => {
  const shown: LoadPhase = { phase: "shown", since: 500 };
  assert.equal(nextPhase(shown, true, 900, false).fade, true);
  assert.equal(nextPhase({ phase: "wait", since: 500 }, true, 550, false).fade, false);
});

test("reduced motion still holds the bars back for a fast load, and never fades", () => {
  const { next } = nextPhase(IDLE, true, 1000, true);
  assert.deepEqual(next, { phase: "wait", since: 1000 });
  const shown = revealed(next, 1000 + SKELETON_WAIT_MS);
  assert.equal(shown.phase, "shown");
  assert.equal(nextPhase(shown, false, 3000, true).fade, false);
});

test("the wait is counted from the placeholder's start", () => {
  const waiting: LoadPhase = { phase: "wait", since: 0 };
  assert.equal(revealIn(waiting, 0), SKELETON_WAIT_MS);
  assert.equal(revealIn(waiting, SKELETON_WAIT_MS + 50), 0);
  assert.equal(revealIn(IDLE, 0), null);
});

test("a page switch eases in only when the path changed and motion is allowed", () => {
  assert.equal(entersOnSwitch("/", "/roadmap", false), true);
  assert.equal(entersOnSwitch("/roadmap", "/roadmap", false), false);
  assert.equal(entersOnSwitch(null, "/roadmap", false), false);
  assert.equal(entersOnSwitch("/", "/roadmap", true), false);
});
