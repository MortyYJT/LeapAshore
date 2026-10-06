"use client";

import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import Generating from "@/components/Generating";
import Onboarding from "@/components/Onboarding";
import PortfolioPicker from "@/components/PortfolioPicker";
import { buildRoadmap } from "@/lib/roadmap";
import { clearState, initialState, loadState, saveState, type PersistedState } from "@/lib/store";
import type { PortfolioItem, Profile } from "@/lib/types";

export default function Page() {
  // Render the initial state first so the first paint shows onboarding, then hydrate from localStorage.
  const [state, setState] = useState<PersistedState>(initialState);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setState(loadState());
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (hydrated) saveState(state);
  }, [state, hydrated]);

  // Scroll to top when the stage changes.
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [state.stage]);

  const roadmap = buildRoadmap(state.profile, state.completedMaterials);

  function handleProfileComplete(profile: Profile) {
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
    setState((prev) => {
      const profile = { ...prev.profile, ...patch };
      // Clearing the tier is meaningful: the assessment then reports that it cannot decide.
      return { ...prev, profile };
    });
  }

  function setAvatar(dataUrl: string | null) {
    setState((prev) => ({ ...prev, avatar: dataUrl }));
  }

  function clearAll() {
    clearState();
    setState({ ...initialState });
  }

  if (state.stage === "onboarding") {
    return (
      <Onboarding
        initialProfile={state.profile}
        onComplete={handleProfileComplete}
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
    />
  );
}
