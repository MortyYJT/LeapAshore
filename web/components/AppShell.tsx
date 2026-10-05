"use client";

import { useEffect, useState } from "react";
import AdvisorView from "./AdvisorView";
import FlowView from "./FlowView";
import HomeView from "./HomeView";
import ProfileView from "./ProfileView";
import { PROGRAMS } from "@/lib/programs";
import type { PortfolioItem, Profile, Roadmap } from "@/lib/types";

type Tab = "home" | "flow" | "profile" | "advisor";

const TABS: { key: Tab; label: string }[] = [
  { key: "home", label: "首页" },
  { key: "flow", label: "流程进度" },
  { key: "profile", label: "个人中心" },
  { key: "advisor", label: "留学顾问" },
];

interface Props {
  profile: Profile;
  roadmap: Roadmap;
  portfolio: PortfolioItem[];
  completedMaterials: string[];
  onToggleMaterial: (materialId: string) => void;
  onRestart: () => void;
  onClear: () => void;
}

export default function AppShell({
  profile,
  roadmap,
  portfolio,
  onToggleMaterial,
  onRestart,
  onClear,
}: Props) {
  const [tab, setTab] = useState<Tab>("flow");
  const [selectedPhase, setSelectedPhase] = useState<string>("selection");

  // Scroll to top on tab change, or the previous scroll position hides content under the header.
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [tab]);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b-2 border-[var(--color-line)] bg-white">
        <div className="mx-auto flex w-full max-w-5xl items-center gap-1 px-4">
          <div className="mr-3 flex items-center gap-2 py-3">
            <span className="text-xl">🧭</span>
            <strong className="text-[15px]">OfferPilot</strong>
          </div>
          <nav className="flex flex-1 gap-1 overflow-x-auto">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className="whitespace-nowrap rounded-xl px-4 py-2 text-sm font-bold transition-colors"
                style={
                  tab === t.key
                    ? { background: "var(--color-brand-soft)", color: "var(--color-brand-dark)" }
                    : { color: "var(--color-ink-soft)" }
                }
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl px-4 py-6">
        {tab === "home" && (
          <HomeView
            profile={profile}
            roadmap={roadmap}
            portfolio={portfolio}
            onGoFlow={() => setTab("flow")}
          />
        )}
        {tab === "flow" && (
          <FlowView
            roadmap={roadmap}
            portfolio={portfolio}
            selectedPhase={selectedPhase}
            onSelectPhase={setSelectedPhase}
            onToggleMaterial={onToggleMaterial}
          />
        )}
        {tab === "profile" && (
          <ProfileView profile={profile} onRestart={onRestart} onClear={onClear} />
        )}
        {tab === "advisor" && <AdvisorView />}
      </main>
    </div>
  );
}
