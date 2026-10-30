import type { Metadata } from "next";

import { SourceNote } from "@/components/ui";
import { requireAdminPage } from "@/lib/admin-server";

import { GapQueue } from "./GapQueue";
import { VerificationList } from "./VerificationList";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "核验 · 鱼跃彼岸", robots: { index: false, follow: false } };

/** The admin's desk (openspec source-verification): pages waiting for a person, and the knowledge-gap queue. */
export default async function AdminPage() {
  const admin = await requireAdminPage();
  return (
    <>
      <main className="page">
        <div className="title-row">
          <div>
            <h1>人工核验</h1>
            <p className="lede">
              逐页对照引文和快照，确认后这一页的要求在全站显示为「已核验」。当前账号 <span className="num">{admin.email}</span>。
            </p>
          </div>
        </div>
        <VerificationList />
        <GapQueue />
      </main>
      <SourceNote>只有管理员账号能打开这个页面。核验记录写明是谁、在什么时候、对照的是哪一版快照；页面内容变了，导入时会自动撤回核验。</SourceNote>
    </>
  );
}
