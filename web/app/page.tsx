import type { Metadata } from "next";

import { SampleTimeline } from "@/components/home/SampleTimeline";
import { LinkButton, SourceNote } from "@/components/ui";
import { chineseInstitutions, overseasInstitutions } from "@/lib/catalog-server";
import { serverProgramPage } from "@/lib/server-api";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "鱼跃彼岸 · 把硕士申请排成一条时间线" };

async function programCount(): Promise<number | null> {
  try {
    return (await serverProgramPage({ limit: 1 })).total;
  } catch {
    return null; // unknown stays unknown
  }
}

/** The first visit (spec app-navigation). A returning applicant is redirected to /roadmap by proxy.ts. */
export default async function Home() {
  const programs = await programCount();
  const facts: [string, string][] = [
    [overseasInstitutions.length.toLocaleString("en"), "所海外大学：29 个国家和地区里的 QS 2027 前 300，加上澳洲、香港、澳门的其他大学"],
    [programs === null ? "未知" : programs.toLocaleString("en"), "个授课型硕士项目，事实来自 CRICOS 登记或学校官网"],
    [chineseInstitutions.length.toLocaleString("en"), "所国内院校，来自教育部名单，用来判断适用哪条均分门槛"],
  ];
  return (
    <>
      <main className="page">
        <section className="intro stagger">
          <div>
            <h1 className="intro-title">把硕士申请排成一条时间线</h1>
            <p className="lede intro-lede">
              填一次背景，看看哪些项目的官方要求你已经满足；选好学校后，从今天到入学，每个阶段要准备什么、建议什么时候做、依据来自哪个官方页面，都在一张图上。
            </p>
            <div className="toolbar" style={{ marginTop: 28 }}>
              <LinkButton href="/assess" variant="primary">
                开始测评
              </LinkButton>
              <LinkButton href="/schools">先看学校</LinkButton>
            </div>
          </div>
          <SampleTimeline />
        </section>
        <section className="facts stagger" aria-label="收录范围">
          {facts.map(([n, t]) => (
            <div key={t}>
              <div className="n num">{n}</div>
              <div className="t">{t}</div>
            </div>
          ))}
        </section>
      </main>
      <SourceNote>录取要求以学校官网为准；没有官方来源的要求显示为未收录，系统不会代填。</SourceNote>
    </>
  );
}
