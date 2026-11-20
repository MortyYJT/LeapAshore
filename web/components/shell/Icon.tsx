import type { ReactNode } from "react";

// One icon set for the whole interface: 16px grid, 1.5px round strokes, drawn in the current colour
// (the `.icon` class in app/globals.css holds the stroke). Icons are authored here, not loaded.
const ICONS = {
  // Two lines, each ending in a station.
  overview: (
    <>
      <path d="M1.5 5h4M1.5 11h8" />
      <circle cx="7.5" cy="5" r="2" />
      <circle cx="11.5" cy="11" r="2" />
    </>
  ),
  // A route between two stops.
  roadmap: (
    <>
      <path d="M5.7 12.5h3.8a2.25 2.25 0 0 0 0-4.5h-3a2.25 2.25 0 0 1 0-4.5h3.8" />
      <circle cx="4" cy="12.5" r="1.7" />
      <circle cx="12" cy="3.5" r="1.7" />
    </>
  ),
  applications: <path d="M4 2.5h5.5l3 3v8H4zM9.5 2.5v3h3M6.2 8.5h4.1M6.2 11h4.1" />,
  schools: <path d="M2 6.5 8 3l6 3.5M3.5 6.5v6.5M8 6.5v6.5M12.5 6.5v6.5M2 13.5h12" />,
  advisor: (
    <>
      <path d="M2.5 3h11v8H7.6l-3.1 2.5V11h-2z" />
      <path d="M5.5 5.8l1.4 1.2-1.4 1.2M8.6 8.4h2" />
    </>
  ),
  profile: (
    <>
      <circle cx="8" cy="5.5" r="2.5" />
      <path d="M3 13.5a5 5 0 0 1 10 0" />
    </>
  ),
  materials: <path d="M2 4.6l1.3 1.3L5.6 3.4M2 10.6l1.3 1.3 2.3-2.5M8.5 4.5h5.5M8.5 10.5h5.5" />,
  search: (
    <>
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.4 10.4 14 14" />
    </>
  ),
  sidebar: <path d="M2.5 3h11v10h-11zM6.2 3v10" />,
  theme: (
    <>
      <circle cx="8" cy="8" r="5.5" />
      <path d="M8 2.5a5.5 5.5 0 0 1 0 11z" fill="currentColor" stroke="none" />
    </>
  ),
  synced: (
    <>
      <circle cx="8" cy="8" r="5.5" />
      <path d="M5.6 8.2l1.7 1.7 3.2-3.6" />
    </>
  ),
  // Not synced: the same ring, empty.
  unsynced: (
    <>
      <circle cx="8" cy="8" r="5.5" />
      <path d="M5.5 8h5" />
    </>
  ),
  check: <path d="M3.2 8.6l3 3 6.4-7.2" />,
  close: <path d="M4 4l8 8M12 4l-8 8" />,
  arrow: <path d="M3 8h9.5M8.8 4.2 12.6 8l-3.8 3.8" />,
  chevron: <path d="M6 3.5 10.5 8 6 12.5" />,
  send: <path d="M8 13V3.5M4 7.2l4-3.9 4 3.9" />,
  stop: <rect x="4.5" y="4.5" width="7" height="7" rx="1.2" fill="currentColor" stroke="none" />,
  // A page leaving its frame: opens the official source in a new tab.
  external: <path d="M6.5 3.5h-3v9h9v-3M9 3h4v4M13 3 7.5 8.5" />,
  // The dock as its own page, and back beside the workspace.
  expand: <path d="M9.5 2.5h4v4M13.5 2.5 9 7M6.5 13.5h-4v-4M2.5 13.5 7 9" />,
  dock: <path d="M2.5 3h11v10h-11zM9.8 3v10" />,
  dockOpen: (
    <>
      <path d="M2.5 3h11v10h-11z" />
      <path d="M9.8 3h3.7v10H9.8z" fill="currentColor" />
    </>
  ),
  copy: <path d="M5.5 5.5v-3h8v8h-3M2.5 5.5h8v8h-8z" />,
  retry: <path d="M13 8a5 5 0 1 1-1.6-3.7M13 2.5v2.4h-2.4" />,
  plus: <path d="M8 3.5v9M3.5 8h9" />,
  // The share button as iOS draws it: an arrow leaving a tray.
  share: <path d="M8 9.8V2.3M5.4 4.8 8 2.2l2.6 2.6M5.3 7H3.5v6.5h9V7h-1.8" />,
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof ICONS;

export function Icon({ name, className = "" }: { name: IconName; className?: string }) {
  return (
    <svg className={`icon ${className}`.trim()} viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      {ICONS[name]}
    </svg>
  );
}
