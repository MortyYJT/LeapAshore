"use client";

import { useEffect, useRef, useState } from "react";
import AppShell from "@/components/AppShell";
import Generating from "@/components/Generating";
import Onboarding from "@/components/Onboarding";
import PortfolioPicker from "@/components/PortfolioPicker";
import {
  fetchProfile,
  fetchRoadmapDefinition,
  mergeServerProfile,
  patchProfile,
  patchRoadmapTask,
  replaceRoadmapTasks,
} from "@/lib/api";
import { buildRoadmap } from "@/lib/roadmap";
import { NO_DEFINITION_READ, readRoadmapDefinition } from "@/lib/roadmap-definition";
import { toTaskRows } from "@/lib/roadmap-source";
import { alreadyStored, toReplacePayload, type TaskRow } from "@/lib/roadmap-sync";
import { clearState, initialState, loadState, saveState, type PersistedState } from "@/lib/store";
import type { PortfolioItem, Profile, RoadmapDefinition } from "@/lib/types";

/**
 * Shown when a roadmap write did not land.
 *
 * A failed recomputation is otherwise invisible: the timeline on screen is the one this page just
 * computed, so a roadmap the server never stored looks exactly like one it did — until the next load
 * shows the applicant's ticks and dates from a stale version. The notice names the risk out loud, and
 * it is deliberately separate from the definition notice above: one says the page is rendering a
 * copy, the other says a change was not saved.
 */
const TASK_SYNC_ERROR_NOTICE =
  "路线图的保存没有成功，服务器上的任务没有更新。当前显示的是本机计算的结果，刷新页面可能会看到旧数据。";

/**
 * The parts of the profile that decide what the payload holds, as a comparable string.
 *
 * This is the page's record of *which* recomputation it is in the middle of: it is claimed for a
 * payload before the request goes out, so the effect cannot fire a second identical write while the
 * first is in flight, and the claim is what the effect compares against on later runs. Everything the
 * payload is built from therefore has to be in it: `targetDegree` and `targetField`, which decide
 * which materials apply, `intake`, which decides every date in it, and the definition's own phase and
 * material keys, because a definition that gained or lost one changes the payload too.
 *
 * `intake` was deliberately left out of an earlier version of this function, and that was wrong: it
 * is the one input that moves every `dueAt`, so a payload built after the intake changed was a
 * different payload under the same fingerprint — the trigger and the payload disagreed about what a
 * recomputation is for, and changing 2027 S1 to 2028 S1 on screen left the stored dates a year behind
 * with nothing said about it. It is in here now, and the dates it moves are also compared against the
 * server's rows by `alreadyStored`, so the two halves of the decision cannot drift apart again.
 */
function applicabilityFingerprint(definition: RoadmapDefinition, profile: Profile): string {
  return JSON.stringify({
    targetDegree: profile.targetDegree,
    targetField: profile.targetField,
    intake: profile.intake,
    phases: definition.phases.map((phase) => phase.id),
    materials: Object.entries(definition.materials)
      .flatMap(([phase, items]) => items.map((item) => `${phase}:${item.id}`))
      .sort(),
  });
}

/** The status a tick leaves behind. Only the two the checkbox means; `in_progress` is the server's. */
function statusForTick(checked: boolean): "completed" | "pending" {
  return checked ? "completed" : "pending";
}

export default function Page() {
  // Render the initial state first so the first paint shows onboarding, then hydrate from localStorage.
  const [state, setState] = useState<PersistedState>(initialState);
  const [hydrated, setHydrated] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  /**
   * Whether the profile on screen is the server's own copy rather than this device's memory of it.
   *
   * The profile is the third input a payload is built from, and like the definition it has to have
   * been read from the server before anything is written. On a cold start `localStorage` holds the
   * last copy this device saw, and that is the profile the page computes from until the read answers:
   * a payload built from it would carry the dates of an intake the server may not hold and would be
   * indistinguishable from a legitimate recomputation once stored. This is the same gate as
   * `definition === null` below, one input over — and it is the whole of "do not write on mount" —
   * so the two writes and the render all trace back to the server's own answers.
   */
  const [profileFromServer, setProfileFromServer] = useState(false);
  /**
   * What the read of the served definition left behind: the definition, the fallback notice, its rows.
   *
   * `definition` inside it is `null` while the read is in flight and `null` again after a failed one.
   * `null` is what `buildRoadmap` reads as "use the built-in copy", so a failure needs no second flag
   * to fall back correctly. The notice is the separate one: without it the fallback would be silent,
   * and a roadmap that quietly omits the phases this build does not carry looks exactly like a roadmap
   * built from the server's answer.
   *
   * It is also the write gate, which is the part that matters most here. A write is only ever built
   * from a definition this state actually holds, so the built-in copy — which has no visa phase — can
   * never drive one; see `note/superpowers/specs/2026-10-06-stage-2-m2-design.md` §3.8 and
   * `roadmap-sync.ts`. Keeping the fallback out of this state rather than out of the payload function
   * means there is exactly one way to have a definition and that is to have read it.
   *
   * The state is the read's own answer rather than three pieces the page assembles, and the read
   * itself is `roadmap-definition.ts`, where `npm test` can reach it: the decision that a failure
   * leaves `null` behind is the rule §3.8 turns on, and a component's `useEffect` is not testable in
   * this project. Nothing in this file names a definition for the failure case, so there is no line
   * here that could put the built-in copy into the value the gate reads.
   */
  const [definitionRead, setDefinitionRead] = useState(NO_DEFINITION_READ);
  const definition = definitionRead.definition;
  /**
   * The applicant's own rows, as the server holds them.
   *
   * These are the roadmap's ticks, not `localStorage`: a completion mark is per-applicant state that
   * has to survive a reload on another device, which is why M2b moved it behind the API. The saved
   * local copy in `store.ts` is no longer read here — it was the pre-M2b answer, and the server is
   * authoritative now.
   */
  const [taskRows, setTaskRows] = useState<TaskRow[]>([]);
  /** Set when a roadmap write did not land, so the failure is not silent. */
  const [taskSyncError, setTaskSyncError] = useState<string | null>(null);
  /**
   * The applicability fingerprint of the recomputation this session has already sent, or is sending.
   *
   * A ref rather than state because it is a record of what was *sent*, not something to render, and
   * because the recomputation effect must be able to read it without itself being re-run by the write
   * that sets it. `undefined` means no write has been claimed in this session, which is why it can
   * only ever answer "is this exact recomputation already on its way" — a fresh page has no memory of
   * an earlier session, and reading it as "the server's rows are current" is the defect this wave
   * fixes: a subject whose rows were stale reloaded into a page that compared nothing and wrote
   * nothing, forever. What survives a reload is the server's own data, and `alreadyStored` is where
   * that comparison happens.
   */
  const lastSyncedFingerprint = useRef<string | undefined>(undefined);
  /**
   * The rows the toggle handler's asynchronous write has to see.
   *
   * A ref rather than the state value read out of the closure, because a tick can land while an
   * earlier request is in flight and the second one must look at the rows as they are now, including
   * whatever the first one changed.
   */
  const rowsRef = useRef<TaskRow[]>([]);
  rowsRef.current = taskRows;

  /**
   * Re-read the roadmap so the local rows carry the ids the server gave them.
   *
   * A replacement is answered with counts, not with the rows themselves — the caller computed those —
   * so after a successful one the page holds no id for the rows it just caused to exist, and a tick
   * would have nothing to `PATCH`. That is not a detail: with no row, `toggleMaterial` has no id to
   * send, so it returns early and the checkbox on screen flips straight back while the server never
   * hears about it. Measured in a browser against the running server before this call existed: a click
   * on a material produced no request at all. Reading the definition again is the one call that
   * returns both halves, and it is the same read as the mount one, so there is no second source.
   *
   * It runs after *every* successful write rather than only after one that created rows, because the
   * case where this matters most is the opposite one: a subject whose read answered with no tasks while
   * the replacement reported the rows as updates. That subject has rows on the server and none in the
   * page, which is exactly what makes a tick silently do nothing.
   *
   * A failed re-read is announced rather than swallowed, for the same reason a tick that cannot be
   * sent is: the symptom it produces on screen — a click that does nothing, or a checkbox that flips
   * straight back — is exactly the defect this path was fixed for, and a page that says nothing about
   * it is indistinguishable from one that worked. The rows on screen stay as they are, because the
   * write this followed did land and the rows it created are still the server's truth; what is missing
   * is their ids, and only a reload can fetch those.
   */
  async function refreshTaskRows(): Promise<void> {
    try {
      const served = await fetchRoadmapDefinition();
      setTaskRows(toTaskRows(served.tasks));
    } catch (error: unknown) {
      setTaskSyncError(
        error instanceof Error
          ? `路线图已保存，但重新读取任务行失败（${error.message}），勾选暂时不会生效。`
          : "路线图已保存，但重新读取任务行失败，勾选暂时不会生效。",
      );
    }
  }

  useEffect(() => {
    setState(loadState());
    setHydrated(true);
  }, []);

  // The server owns the profile, so it is read once on mount and merged over the local copy. The
  // read is skipped when the database is unreachable, but a failed save has to be said out loud,
  // because the applicant would otherwise believe an edit was stored when it was not.
  //
  // A read that lands is also what makes the profile on screen the server's own copy rather than this
  // device's memory of it, which the recomputation below needs before it writes anything: see
  // `profileFromServer`. A read that fails leaves that false, exactly as a failed definition read
  // leaves the definition `null` — the page keeps rendering from what it has and writes nothing,
  // because a payload built from a copy the server never confirmed is the silent divergence the whole
  // layer refuses to make.
  useEffect(() => {
    let cancelled = false;
    fetchProfile()
      .then((remote) => {
        if (cancelled) return;
        setState((prev) => ({ ...prev, profile: mergeServerProfile(remote, prev.profile) }));
        setProfileFromServer(true);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setProfileError(error instanceof Error ? error.message : "读取档案失败");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /**
   * The definitions come from the server too, once, for the same reason the profile does.
   *
   * The failure is reported rather than thrown away. A roadmap built from the built-in copy is a
   * different claim from one built from the server's answer — the fallback does not carry the visa
   * phase, for instance — and reporting the phase count as if it came from the server would be the
   * silent divergence the profile layer already refuses to make. So the notice stays on screen while
   * the fallback is what is being rendered.
   *
   * What the read leaves behind, including "no definition at all" after a failure, is decided by
   * `readRoadmapDefinition`, and deliberately not here: that decision is the write gate above, and it
   * lives where the unit tests can drive its failure branch. This effect applies the answer and has no
   * `catch` of its own, so there is no line here that could put the built-in copy into the definition
   * the gate reads. The rows arrive with the definition, in one response, and they are what the
   * timeline's ticks are read from; `null` means the read failed, and the rows already on screen are
   * kept rather than replaced with none.
   */
  useEffect(() => {
    let cancelled = false;
    readRoadmapDefinition(fetchRoadmapDefinition).then((read) => {
      if (cancelled) return;
      setDefinitionRead(read);
      if (read.tasks !== null) setTaskRows(read.tasks);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (hydrated) saveState(state);
  }, [state, hydrated]);

  /**
   * Store the roadmap on the server, but only when the server's own rows give a reason to.
   *
   * The trigger is `alreadyStored`, which compares the payload this profile and definition imply
   * against the rows the server served in the same response. That comparison is the one piece of
   * evidence a reload cannot lose, and it is the fix for the defect an earlier version of this effect
   * had: the trigger was session memory — "the server has no rows, or the fingerprint moved since the
   * last write this session made" — and a fresh page has none, so a subject whose stored roadmap was
   * stale (a profile edited elsewhere, or a recomputation whose `PUT` failed and whose notice told the
   * applicant to reload) reloaded into a page that wrote nothing. Measured: 31 rows on the server with
   * no row for a material the profile had just made applicable; the material rendered, its checkbox
   * sent no `PATCH`, and no reload could ever repair it. Now the reload reconciles: the missing key is
   * a disagreement, the write runs, and the row exists to be ticked.
   *
   * Rounding that off, the two conditions around it:
   *
   * - nothing is computed or written until both the definition and the profile have been read from the
   *   server. The profile half is `profileFromServer`; `localStorage` holds a copy of the profile this
   *   device saw, and a payload built from it before the read answers would store dates for an intake
   *   the server may not hold. Until then the effect returns without claiming a fingerprint, so the
   *   decision is taken again — correctly — when the read lands;
   * - a fingerprint already claimed means this exact recomputation is in flight or has landed. That is
   *   what keeps a re-render during the request from sending the payload twice: the write records one
   *   round of audit events, not two. A failed write clears the claim, so the next run retries rather
   *   than believing a partial write landed; the failure itself is reported, never swallowed.
   *
   * `toReplacePayload` can still answer `null`, and that gate is untouched: a definition the page did
   * not read from the server produces no write at all, because the built-in copy omits the visa phase
   * and its applicable-key set would delete those rows and their completion state — §3.8, and never
   * an empty payload instead.
   */
  useEffect(() => {
    if (!hydrated || definition === null || !profileFromServer) return;
    const fingerprint = applicabilityFingerprint(definition, state.profile);
    if (lastSyncedFingerprint.current === fingerprint) return;
    const payload = toReplacePayload(definition, roadmap, taskRows);
    if (payload === null) return;
    if (alreadyStored(payload, taskRows)) {
      // The server already holds the rows this profile and definition imply, so there is nothing to
      // store this time round. The fingerprint is claimed anyway: it is the record that this exact
      // recomputation has been considered, which is what stops the comparison being redone on every
      // later render of the same inputs.
      lastSyncedFingerprint.current = fingerprint;
      return;
    }
    // Claimed before the request, not after it lands: this effect is re-run by the state it sets, and
    // a fingerprint written in `.then` leaves a window in which a second run cannot tell that a write
    // is already on its way. Two identical replacements would both succeed — the service is a
    // replacement, not an append — but they would also write two rounds of audit events for one
    // change. A failed write clears the claim again so the next run retries.
    lastSyncedFingerprint.current = fingerprint;
    let cancelled = false;
    replaceRoadmapTasks(payload)
      .then(async () => {
        if (cancelled) return;
        // The counts are not checked again here. `replaceRoadmapTasks` already raises when the reply's
        // `created + updated` disagrees with the rows sent, so a second copy of that rule in this file
        // could never run — it was dead code, and two implementations of one rule is one too many,
        // because only the live one is ever exercised. The transport owns it: that is where the reply
        // is read, and the raise reaches the `catch` below with the same notice and one more thing
        // done — the fingerprint claim is cleared, so the next run retries rather than believing a
        // partial write landed.
        setTaskSyncError(null);
        // The rows this call created, or confirmed, have ids only the server knows, and a tick needs
        // them; see `refreshTaskRows`. It runs after every successful write rather than only after one
        // that created rows, because a write this call could not see the rows for is exactly the case
        // where the page holds none — measured on a subject whose GET answered with no tasks while the
        // replacement reported the rows as updates.
        await refreshTaskRows();
      })
      .catch((error: unknown) => {
        lastSyncedFingerprint.current = undefined;
        if (cancelled) return;
        setTaskSyncError(
          error instanceof Error ? `${TASK_SYNC_ERROR_NOTICE}（${error.message}）` : TASK_SYNC_ERROR_NOTICE,
        );
      });
    return () => {
      cancelled = true;
    };
    // `roadmap` is deliberately absent: it is recomputed on every render, so it cannot be a trigger
    // without making this run on every render. Every input it is built from is covered instead — the
    // definition and the profile in the fingerprint, the rows in `alreadyStored` — and `taskRows` is
    // what the ownership rule reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hydrated, definition, profileFromServer, taskRows, state.profile]);

  // Scroll to top when the stage changes.
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [state.stage]);

  // An omitted definition is the built-in copy, so the failed-fetch path is the same line of code as
  // the first paint rather than a second branch that has to be kept in step with it. `now` is left at
  // its own default by passing `undefined` explicitly, which is the only reason it is named here.
  //
  // This call does run with the built-in copy when the read failed, and that is safe now because the
  // result is only ever rendered: the write is gated on `definition`, which is null in exactly that
  // case, and on `profileFromServer` for the other input, so §3.8's hazard is closed at the effect
  // above rather than by branching here. The applicant's own marks come from the server's rows, so a
  // tick cannot be lost by a recomputation that renders from a subset.
  const completedMaterialIds = taskRows
    .filter((row) => row.status === "completed")
    .map((row) => row.material_key);
  const roadmap = buildRoadmap(
    state.profile,
    completedMaterialIds,
    undefined,
    definition ?? undefined,
  );

  /**
   * Send one field edit to the server, keeping the local update optimistic.
   *
   * The edit has already been applied to local state by the caller, so the row feels immediate.
   * `rollbackTo` is the pre-edit value of each field this patch changed: a failure restores exactly
   * those fields and leaves any newer edit to another field alone. Pass null instead when there is
   * no earlier profile to fall back to, which is the first save: restoring `previousValues` there
   * would replace everything the applicant just typed with an empty profile while the error is
   * shown on a screen they have already left. A local value the server never accepted is the silent
   * divergence this keeps out.
   *
   * Returns whether the server took the edit, so the caller can decide what to do next instead of
   * advancing as if it had.
   */
  async function saveProfile(patch: Partial<Profile>, rollbackTo: Partial<Profile> | null): Promise<boolean> {
    setProfileError(null);
    try {
      await patchProfile(patch);
      return true;
    } catch (error: unknown) {
      if (rollbackTo !== null) {
        const rollback: Record<string, unknown> = {};
        for (const key of Object.keys(rollbackTo)) rollback[key] = rollbackTo[key as keyof Profile];
        setState((prev) => ({
          ...prev,
          profile: { ...prev.profile, ...rollback } as Profile,
        }));
      }
      setProfileError(error instanceof Error ? error.message : "保存档案失败");
      return false;
    }
  }

  /**
   * The values `patch` would replace, for the fields it actually changes.
   *
   * A patch only carries a value the applicant just sent, so a field that already held that value is
   * not part of the edit and must not be rolled back with it.
   */
  function previousValues(patch: Partial<Profile>, profile: Profile): Partial<Profile> {
    const before: Record<string, unknown> = {};
    const current = profile as unknown as Record<string, unknown>;
    for (const [key, value] of Object.entries(patch)) {
      if (current[key] !== value) before[key] = current[key];
    }
    return before as Partial<Profile>;
  }

  /**
   * Finish onboarding: store the whole profile, then move on only if the server took it.
   *
   * The stage change is what makes this different from an inline edit. Advancing first left the
   * applicant on a screen where the failure is invisible, holding a profile the rollback had just
   * emptied, and the flow went on to build a plan from no background at all. Staying on the last
   * onboarding step keeps the typed answers and the error message on the screen the applicant is
   * looking at, and it leaves the retry button under their cursor. The two exits the applicant
   * controls are deliberate: 返回 keeps the answers and lets them walk back through the steps, and
   * the copy says a reload does not have them, because the server is what makes them durable.
   */
  async function handleProfileComplete(profile: Profile) {
    const saved = await saveProfile(profile, null);
    if (!saved) return;
    setState((prev) => ({ ...prev, profile, stage: "generating" }));
  }

  function handlePortfolioConfirm(portfolio: PortfolioItem[]) {
    setState((prev) => ({ ...prev, portfolio, stage: "app" }));
  }

  /**
   * Tick or untick one material, through the per-row door rather than the replacement.
   *
   * `PATCH /api/roadmap/tasks/{id}` exists for exactly this: the applicant's own mark on one row, which
   * also claims the row for them so the next recomputation leaves it alone. A recomputation must never
   * be how a tick is stored — the replacement carries dates, not status, and routing a tick through it
   * would entangle the applicant's mark with a recompute that another change may trigger at the same
   * moment.
   *
   * The local update is optimistic and rolled back if the write fails, and the failure is said out
   * loud: a tick that the server never took is indistinguishable on screen from one it did, right up
   * until the next load shows it gone. `rowsRef` is read rather than `taskRows` from the closure
   * because the write is asynchronous and a second tick can land while the first is in flight.
   */
  function toggleMaterial(materialId: string, checked: boolean) {
    const row = rowsRef.current.find((candidate) => candidate.material_key === materialId);
    if (row === undefined) {
      // No row to edit: the roadmap is rendering a material the server has no row for yet, which can
      // only be the moment between a recomputation being computed and its rows arriving. It used to
      // return in silence, and silence is the wrong answer here: the applicant sees a click that did
      // nothing and a checkbox that flipped back, which is the same symptom as the defect this path
      // was fixed for, and the rest of it — a failed `PATCH`, a failed re-read — refuses to leave that
      // unsaid. The row the tick names is not in the server's answer, so there is nothing to write to
      // and nothing to roll back.
      setTaskSyncError("材料勾选没有保存到服务器：服务器上还没有这一条材料对应的任务行，请刷新页面后重试。");
      return;
    }
    const previous = { status: row.status, origin: row.origin };
    const status = statusForTick(checked);
    const apply = (fields: Partial<TaskRow>) =>
      setTaskRows((rows) =>
        rows.map((candidate) =>
          candidate.id === row.id ? { ...candidate, ...fields } : candidate,
        ),
      );
    apply({ status });
    setTaskSyncError(null);
    patchRoadmapTask(row.id, { status })
      .then((stored) => {
        // The reply is the row the server stored, so the local copy takes its status *and its origin*
        // back from it rather than keeping the guess. The origin is the half that is easy to forget and
        // the more expensive one to get wrong: the edit claims the row for the applicant, and a client
        // that kept it as `system` would offer the row in the next recomputation's payload — the one
        // thing the ownership rule forbids. Measured before this line existed: after a tick, the next
        // recompute's payload carried the row the applicant had just claimed.
        apply({ status: stored.status, origin: stored.origin as TaskRow["origin"] });
      })
      .catch((error: unknown) => {
        apply(previous);
        setTaskSyncError(
          error instanceof Error
            ? `材料勾选没有保存到服务器（${error.message}）`
            : "材料勾选没有保存到服务器",
        );
      });
  }

  function restart() {
    setState((prev) => ({ ...prev, stage: "onboarding" }));
  }

  // Editing a single field from the profile view. Used instead of sending the applicant back through
  // onboarding to correct one value.
  function updateProfile(patch: Partial<Profile>) {
    const before = previousValues(patch, state.profile);
    setState((prev) => {
      // Clearing the tier is meaningful: the assessment then reports that it cannot decide.
      return { ...prev, profile: { ...prev.profile, ...patch } };
    });
    void saveProfile(patch, before);
  }

  function setAvatar(dataUrl: string | null) {
    setState((prev) => ({ ...prev, avatar: dataUrl }));
  }

  function clearAll() {
    clearState();
    setState({ ...initialState, profile: state.profile });
  }

  if (state.stage === "onboarding") {
    return (
      <Onboarding
        initialProfile={state.profile}
        onComplete={handleProfileComplete}
        saveError={profileError}
      />
    );
  }

  if (state.stage === "generating") {
    return <Generating onDone={() => setState((prev) => ({ ...prev, stage: "portfolio" }))} />;
  }

  if (state.stage === "portfolio") {
    return (
      <PortfolioPicker
        profile={state.profile}
        onConfirm={handlePortfolioConfirm}
        onBack={restart}
      />
    );
  }

  return (
    <AppShell
      profile={state.profile}
      roadmap={roadmap}
      portfolio={state.portfolio}
      onToggleMaterial={toggleMaterial}
      onUpdateProfile={updateProfile}
      avatar={state.avatar}
      onAvatarChange={setAvatar}
      onClear={clearAll}
      profileError={profileError}
      roadmapNotice={definitionRead.notice}
      taskSyncError={taskSyncError}
    />
  );
}
