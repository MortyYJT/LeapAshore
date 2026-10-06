"use client";

import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import Generating from "@/components/Generating";
import Onboarding from "@/components/Onboarding";
import PortfolioPicker from "@/components/PortfolioPicker";
import { fetchProfile, mergeServerProfile, patchProfile } from "@/lib/api";
import { buildRoadmap } from "@/lib/roadmap";
import { clearState, initialState, loadState, saveState, type PersistedState } from "@/lib/store";
import type { PortfolioItem, Profile } from "@/lib/types";

export default function Page() {
  // Render the initial state first so the first paint shows onboarding, then hydrate from localStorage.
  const [state, setState] = useState<PersistedState>(initialState);
  const [hydrated, setHydrated] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  useEffect(() => {
    setState(loadState());
    setHydrated(true);
  }, []);

  // The server owns the profile, so it is read once on mount and merged over the local copy. The
  // read is skipped when the database is unreachable, but a failed save has to be said out loud,
  // because the applicant would otherwise believe an edit was stored when it was not.
  useEffect(() => {
    let cancelled = false;
    fetchProfile()
      .then((remote) => {
        if (cancelled) return;
        setState((prev) => ({ ...prev, profile: mergeServerProfile(remote, prev.profile) }));
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setProfileError(error instanceof Error ? error.message : "读取档案失败");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (hydrated) saveState(state);
  }, [state, hydrated]);

  // Scroll to top when the stage changes.
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [state.stage]);

  const roadmap = buildRoadmap(state.profile, state.completedMaterials);

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

  function toggleMaterial(materialId: string) {
    setState((prev) => {
      const has = prev.completedMaterials.includes(materialId);
      return {
        ...prev,
        completedMaterials: has
          ? prev.completedMaterials.filter((m) => m !== materialId)
          : [...prev.completedMaterials, materialId],
      };
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
      completedMaterials={state.completedMaterials}
      onToggleMaterial={toggleMaterial}
      onUpdateProfile={updateProfile}
      avatar={state.avatar}
      onAvatarChange={setAvatar}
      onClear={clearAll}
      profileError={profileError}
    />
  );
}
