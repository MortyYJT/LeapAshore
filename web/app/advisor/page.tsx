"use client";

import { useEffect } from "react";

import { Advisor } from "@/components/advisor/Advisor";
import { useAdvisorChat } from "@/components/advisor/AdvisorProvider";

/**
 * The advisor at full width: the phone's 顾问 tab, and the dock opened as a page. It is the same
 * conversation as the dock's, held in `AdvisorProvider`. `?q=` puts a question in the composer
 * without sending it.
 */
export default function AdvisorPage() {
  const { setDraft } = useAdvisorChat();
  useEffect(() => {
    const question = new URLSearchParams(window.location.search).get("q");
    if (question) setDraft(question);
  }, [setDraft]);
  return (
    <main className="advisor-route">
      <Advisor variant="page" />
    </main>
  );
}
