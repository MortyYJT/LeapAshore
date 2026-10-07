"use client";

import { useEffect, useRef, useState } from "react";
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

function AvatarGlyph() {
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
  avatar: string | null;
  /**
   * Tick or untick one material. `checked` is the state the control is moving to, so the caller does
   * not have to re-derive it from a roadmap that may already have been recomputed.
   */
  onToggleMaterial: (materialId: string, checked: boolean) => void;
  onUpdateProfile: (patch: Partial<Profile>) => void;
  onAvatarChange: (dataUrl: string | null) => void;
  onClear: () => void;
  /** Why the last profile save failed, or null, so the profile view can report the rollback. */
  profileError: string | null;
  /**
   * Set when the roadmap on screen was built from the built-in definition instead of the served one.
   *
   * It is a claim about the data, not a save error: the timeline still works, but it is missing
   * whatever the server holds that this build does not — the authored visa phase among it. Rendered
   * under the header on every tab rather than inside one view, because every view renders the roadmap.
   */
  roadmapNotice: string | null;
  /**
   * Set when a roadmap write did not land, or null.
   *
   * Deliberately a separate notice from the one above: that one says the page is rendering a copy of
   * the definition, this one says a change to the applicant's own rows was not stored. Both mean the
   * screen is not the server, but only this one means work is at risk, so it is rendered as an error
   * rather than as a warning.
   */
  taskSyncError: string | null;
}

export default function AppShell({
  profile,
  roadmap,
  portfolio,
  avatar,
  onToggleMaterial,
  onUpdateProfile,
  onAvatarChange,
  onClear,
  profileError,
  roadmapNotice,
  taskSyncError,
}: Props) {
  const [tab, setTab] = useState<Tab>("flow");
  const [panel, setPanel] = useState<Panel>(null);
  const [selectedPhase, setSelectedPhase] = useState<string>("selection");
  const [menuOpen, setMenuOpen] = useState(false);
  const accountRef = useRef<HTMLDivElement>(null);

  // Leaving a view returns to the top, otherwise the previous scroll position leaves content hidden
  // under the sticky header.
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [tab, panel]);

  // A hover menu also needs to close on an outside click and on Escape, otherwise it stays open over
  // the page after the pointer has moved on.
  useEffect(() => {
    if (!menuOpen) return;
    function onPointerDown(event: MouseEvent) {
      if (accountRef.current && !accountRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen]);

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
            ref={accountRef}
            className="relative justify-self-end"
            onMouseEnter={() => setMenuOpen(true)}
            onMouseLeave={() => setMenuOpen(false)}
          >
            <button
              aria-label="账户"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((v) => !v)}
              className="flex h-9 w-9 items-center justify-center overflow-hidden rounded-full border-2 transition-colors"
              style={{
                borderColor: showingPanel ? "var(--color-brand)" : "var(--color-line)",
                background: showingPanel ? "var(--color-brand-soft)" : "var(--color-surface)",
                color: showingPanel ? "var(--color-brand-dark)" : "var(--color-ink-soft)",
              }}
            >
              {avatar ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={avatar} alt="账户头像" className="h-full w-full object-cover" />
              ) : (
                <AvatarGlyph />
              )}
            </button>

            {/*
              The drop shadow gap is padding on this wrapper rather than a top offset. An offset would
              leave a strip that belongs to neither the button nor the menu, so crossing it fired
              mouseleave and the menu vanished before the pointer reached it.
            */}
            {menuOpen && (
              <div className="absolute right-0 top-full pt-2">
                <div className="w-40 overflow-hidden rounded-xl border-2 border-[var(--color-line)] bg-[var(--color-canvas)] py-1 shadow-lg">
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
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl px-4 py-6">
        {/*
          A stale local definition is a different claim from a fresh server one, so it is said out
          loud instead of falling back quietly. Warning-coloured rather than danger-coloured: the page
          works, it is the definition that is older than the server's.
        */}
        {roadmapNotice && (
          <div className="mb-4 rounded-xl border-2 border-[var(--color-warn)] bg-[var(--color-warn-soft)] p-3">
            <p className="text-sm leading-relaxed text-[#9a6700]">{roadmapNotice}</p>
          </div>
        )}
        {/*
          A write that did not land is reported on every tab, for the same reason the notice above is:
          the roadmap renders everywhere, so a failure to save it is not one view's news. Danger-
          coloured rather than warning-coloured, because this one means the server does not hold what
          the screen shows.
        */}
        {taskSyncError && (
          <div className="mb-4 rounded-xl border-2 border-[var(--color-danger)] bg-[var(--color-danger-soft)] p-3">
            <p className="text-sm leading-relaxed text-[var(--color-danger)]">{taskSyncError}</p>
          </div>
        )}
        {panel === "profile" && (
          <ProfileView
            profile={profile}
            avatar={avatar}
            onChange={onUpdateProfile}
            onAvatarChange={onAvatarChange}
            onOpenSettings={() => setPanel("settings")}
            saveError={profileError}
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
