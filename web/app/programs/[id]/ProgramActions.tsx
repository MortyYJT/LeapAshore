"use client";

import Link from "next/link";

import { useAuth } from "@/components/auth/AuthProvider";
import { Loading } from "@/components/ui";
import { hasBasics, toApplicant } from "@/lib/assess";
import { useProfile } from "@/lib/hooks/useProfile";
import { tierProgram } from "@/lib/tiers";
import type { Program } from "@/lib/types";

/**
 * How the program compares with the applicant's background. Adding it is the page's main action, in
 * the title row (components/shell/AddProgram.tsx), which stores the band shown here when there is one
 * (`bandFor` in lib/add-program.ts).
 */
export function ProgramActions({ program }: { program: Program }) {
  const { ready, gated } = useAuth();
  if (!ready) return null;
  if (gated) {
    return (
      <section className="panel panel-pad" aria-labelledby="fit-h">
        <h2 id="fit-h" style={{ marginBottom: 8 }}>和你的背景比</h2>
        <p className="muted" style={{ margin: 0 }}>登录后，这里会按收录的要求和你的背景比较。</p>
      </section>
    );
  }
  return <Fit program={program} />;
}

function Fit({ program }: { program: Program }) {
  const profile = useProfile();
  const complete = profile.data ? hasBasics(profile.data) : false;
  const result = profile.data && complete ? tierProgram(toApplicant(profile.data), program) : null;

  return (
    <section className="panel panel-pad" aria-labelledby="fit-h">
      <h2 id="fit-h" style={{ marginBottom: 8 }}>和你的背景比</h2>
      {!profile.data && profile.loading && <Loading what="你的背景" />}
      {profile.data && !complete && (
        <p className="muted" style={{ margin: 0 }}>
          分档要的四项信息还没填全。<Link href="/tiers">先补信息</Link>后，这里会按收录的要求比较。
        </p>
      )}
      {result && (
        <>
          <p style={{ margin: "0 0 4px", fontSize: 30, lineHeight: "36px", fontWeight: 600 }}>{result.tier ?? "未分档"}</p>
          <p className="muted" style={{ margin: "0 0 12px" }}>
            {result.tier ? "按已收录的要求比较，不是录取概率。" : "没有能和你的背景比较的要求，所以不分档。"}
          </p>
          {result.confirm.map((c) => (
            <p className="small" key={c.kind} style={{ margin: "6px 0 0" }}>
              <span className="pill pill-neutral">去官网确认</span> {c.label}
            </p>
          ))}
        </>
      )}
    </section>
  );
}
