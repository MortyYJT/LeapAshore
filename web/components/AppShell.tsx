"use client";

import { useEffect, useState } from "react";
import AdvisorView from "./AdvisorView";
import FlowView from "./FlowView";
import HomeView from "./HomeView";
import ProfileView from "./ProfileView";
import SettingsView from "./SettingsView";
import type { PortfolioItem, Profile, Roadmap } from "@/lib/types";

type Tab = "home" | "flow" | "advisor";
type Panel = "profile" | "settings" | null;

const TABS: { key: Tab; label: string }[] = [
  { key: "home", label: "首页" },
  { key: "flow", label: "流程进度" },
  { key: "advisor", label: "留学顾问" },
];

function AvatarIcon() {
  return (
    <svg viewBox="0 0 24 24" width="19" height="19" fill="none" aria-hidden>
      <circle cx="12" cy="8.5" r="3.6" fill="currentColor" />
      <path
        d="M4.8 20c0-3.6 3.2-6 7.2-6s7.2 2.4 7.2 6"
        stroke="currentColor"
        strokeWidth="1.9"
        strokeLinecap="round"
      />
    </svg>
  );
}

interface Props {
  profile: Profile;
  roadmap: Roadmap;
  portfolio: PortfolioItem[];
  completedMaterials: string[];
  onToggleMaterial: (materialId: string) => void;
  onUpdateProfile: (patch: Partial<Profile>) => void;
  onClear: () => void;
}

export default function AppShell({
  profile,
  roadmap,
  portfolio,
  onToggleMaterial,
  onUpdateProfile,
  onClear,
}: Props) {
  const [tab, setTab] = useState<Tab>("flow");
  const [panel, setPanel] = useState<Panel>(null);
  const [selectedPhase, setSelectedPhase] = useState<string>("selection");
  const [menuOpen, setMenuOpen] = useState(false);

  // Leaving a view returns to the top, otherwise the previous scroll position leaves content hidden
  // under the sticky header.
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [tab, panel]);

  const showingPanel = panel !== null;

  return (
    <div className="min-h-screen">
      {/*
        Equal 1fr columns keep the tab row centred on the page. The account control occupies the right
        column so it stays anchored to the edge instead of pulling the tabs off centre.
      */}
      <header className="sticky top-0 z-20 border-b-2 border-[var(--color-line)] bg-[var(--color-canvas)]">
        <div className="mx-auto grid w-full max-w-5xl grid-cols-[1fr_auto_1fr] items-center px-4">
          <button
            className="flex items-center gap-2 justify-self-start py-3"
            onClick={() => {
              setPanel(null);
              setTab("home");
            }}
          >
            <span className="text-xl">🧭</span>
            <strong className="hidden text-[15px] lg:inline">OfferPilot</strong>
          </button>

          <nav className="flex justify-self-center gap-1 overflow-x-auto py-2">
            {TABS.map((t) => {
              const active = !showingPanel && tab === t.key;
              return (
                <button
                  key={t.key}
                  onClick={() => {
                    setPanel(null);
                    setTab(t.key);
                  }}
                  className="whitespace-nowrap rounded-xl px-4 py-2 text-sm font-bold transition-colors"
                  style={
                    active
                      ? {
                          background: "var(--color-brand-soft)",
                          color: "var(--color-brand-dark)",
                          boxShadow: "0 2px 0 var(--color-brand)",
                        }
                      : { color: "var(--color-ink-soft)" }
                  }
                >
                  {t.label}
                </button>
              );
            })}
          </nav>

          <div
            className="relative justify-self-end"
            onMouseEnter={() => setMenuOpen(true)}
            onMouseLeave={() => setMenuOpen(false)}
          >
            <button
              aria-label="账户"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((v) => !v)}
              className="flex h-9 w-9 items-center justify-center rounded-full border-2 transition-colors"
              style={{
                borderColor: showingPanel ? "var(--color-brand)" : "var(--color-line)",
                background: showingPanel ? "var(--color-brand-soft)" : "var(--color-surface)",
                color: showingPanel ? "var(--color-brand-dark)" : "var(--color-ink-soft)",
              }}
            >
              <AvatarIcon />
            </button>

            {menuOpen && (
              <div className="absolute right-0 top-[calc(100%+6px)] w-40 overflow-hidden rounded-xl border-2 border-[var(--color-line)] bg-[var(--color-canvas)] py-1 shadow-lg">
                {(
                  [
                    { key: "profile", label: "个人信息" },
                    { key: "settings", label: "设置" },
                  ] as const
                ).map((item) => (
                  <button
                    key={item.key}
                    onClick={() => {
                      setPanel(item.key);
                      setMenuOpen(false);
                    }}
                    className="block w-full px-4 py-2 text-left text-sm font-semibold transition-colors hover:bg-[var(--color-surface)]"
                    style={
                      panel === item.key
                        ? { color: "var(--color-brand-dark)" }
                        : { color: "var(--color-ink)" }
                    }
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl px-4 py-6">
        {panel === "profile" && (
          <ProfileView
            profile={profile}
            onChange={onUpdateProfile}
            onOpenSettings={() => setPanel("settings")}
          />
        )}
        {panel === "settings" && <SettingsView onClear={onClear} />}
        {!showingPanel && tab === "home" && (
          <HomeView
            profile={profile}
            roadmap={roadmap}
            portfolio={portfolio}
            onGoFlow={() => setTab("flow")}
          />
        )}
        {!showingPanel && tab === "flow" && (
          <FlowView
            roadmap={roadmap}
            portfolio={portfolio}
            selectedPhase={selectedPhase}
            onSelectPhase={setSelectedPhase}
            onToggleMaterial={onToggleMaterial}
          />
        )}
        {!showingPanel && tab === "advisor" && <AdvisorView />}
      </main>
    </div>
  );
}
