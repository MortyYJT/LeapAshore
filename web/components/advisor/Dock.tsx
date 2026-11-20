"use client";

import { Advisor } from "./Advisor";
import { useAdvisorDock } from "./AdvisorProvider";

/**
 * The advisor beside the workspace. Whether it shows is decided in CSS from `data-dock` on <html>,
 * which the script in the document head sets before first paint (app/advisor.css); `inert` keeps a
 * closed dock out of the tab order and away from assistive technology.
 */
export function Dock() {
  const { open } = useAdvisorDock();
  return (
    <aside className="dock" id="advisor-dock" aria-label="顾问" inert={!open}>
      <Advisor variant="dock" />
    </aside>
  );
}
