"use client";

import { useRouter } from "next/navigation";

import { Timeline } from "@/components/roadmap/Timeline";
import { EMPTY_PROFILE } from "@/lib/assess";
import { buildRoadmap, DEFAULT_DEFINITION } from "@/lib/roadmap";
import { timelineOf } from "@/lib/roadmap-timeline";

/** The introduction's picture: a sample applicant's roadmap, labelled as a sample wherever it shows. */
export function SampleTimeline() {
  const router = useRouter();
  // The start of today's UTC day, so the server's drawing and the browser's agree to the pixel.
  const now = new Date();
  const today = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const year = today.getUTCFullYear() + 1;
  const profile = { ...EMPTY_PROFILE, intake: `${year} S2`, targetField: "计算机与数据" as const };
  const done = (DEFAULT_DEFINITION.materials.selection ?? []).map((m) => m.id);
  const model = timelineOf(buildRoadmap(profile, done, today), today);
  return (
    <figure className="panel" style={{ margin: 0, padding: "16px 16px 8px" }}>
      <Timeline model={model} today={today} deadlines={[]} showDeadlines={false} selected={null} onSelect={() => router.push("/tiers")} animate />
      <figcaption className="muted small" style={{ padding: "4px 8px" }}>
        <span className="pill pill-sample" style={{ marginRight: 6 }}>示例</span>
        {year} 年 7 月入学、计算机方向的路线图
      </figcaption>
    </figure>
  );
}
