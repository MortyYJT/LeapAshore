// Tests for what the browser is allowed to remember.
//
// The profile is server state, so these pin the split: `localStorage` keeps the stage, the portfolio,
// the ticked materials and the avatar, and never a copy of the profile. `window` is faked here, so
// these run in plain Node like the rest of the frontend suite.

import { test } from "node:test";
import assert from "node:assert/strict";

import { EMPTY_PROFILE, clearState, initialState, loadState, saveState } from "./store.ts";

const STORAGE_KEY = "offerpilot.state.v1";

/** Run `body` with a `window.localStorage` backed by a Map, and hand it that Map. */
function withLocalStorage<T>(body: (stored: Map<string, string>) => T): T {
  const stored = new Map<string, string>();
  const hadWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    writable: true,
    value: {
      localStorage: {
        getItem: (key: string) => stored.get(key) ?? null,
        setItem: (key: string, value: string) => void stored.set(key, value),
        removeItem: (key: string) => void stored.delete(key),
      },
    },
  });
  try {
    return body(stored);
  } finally {
    if (hadWindow) Object.defineProperty(globalThis, "window", hadWindow);
    else delete (globalThis as { window?: unknown }).window;
  }
}

test("the profile is not written to localStorage", () => {
  // The regression this pins: a persisted profile is merged back over the server's answer wherever
  // the server has none, so a cleared field or a save the server never took could return as if it
  // had been stored. The server owns the profile; the other four keys are this device's own progress.
  withLocalStorage((stored) => {
    saveState({
      ...initialState,
      profile: { ...EMPTY_PROFILE, schoolName: "北京邮电大学", gpaScore: 82 },
      stage: "app",
    });

    const raw = stored.get(STORAGE_KEY);
    assert.ok(raw, "the other state still has to be persisted");
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    assert.equal("profile" in parsed, false);
    assert.deepEqual(Object.keys(parsed).sort(), [
      "avatar",
      "completedMaterials",
      "portfolio",
      "stage",
    ]);
    assert.equal(parsed.stage, "app");
  });
});

test("the state the device owns survives a reload", () => {
  withLocalStorage((stored) => {
    saveState({
      ...initialState,
      stage: "app",
      portfolio: [],
      completedMaterials: ["transcript"],
      avatar: "data:image/png;base64,AAAA",
    });
    const loaded = loadState();
    assert.equal(loaded.stage, "app");
    assert.deepEqual(loaded.completedMaterials, ["transcript"]);
    assert.equal(loaded.avatar, "data:image/png;base64,AAAA");
    assert.ok(stored.size > 0);
  });
});

test("a profile left behind by an older build is ignored, not merged back", () => {
  // The copy an earlier version wrote is a second opinion about the profile. Reading it back would
  // reintroduce the divergence for anyone whose browser still holds one, so it is dropped instead.
  withLocalStorage((stored) => {
    stored.set(
      STORAGE_KEY,
      JSON.stringify({
        stage: "app",
        profile: { ...EMPTY_PROFILE, schoolName: "北京邮电大学" },
        portfolio: [],
        completedMaterials: [],
        avatar: null,
      }),
    );
    const loaded = loadState();
    assert.equal(loaded.stage, "app");
    assert.equal(loaded.profile.schoolName, "");
    assert.notEqual(loaded.profile, EMPTY_PROFILE, "the shared constant must not be handed out");
  });
});

test("clearing removes the stored state", () => {
  withLocalStorage((stored) => {
    saveState({ ...initialState, stage: "app" });
    assert.ok(stored.has(STORAGE_KEY));
    clearState();
    assert.equal(stored.has(STORAGE_KEY), false);
  });
});
