import type { Metadata } from "next";
import Link from "next/link";

import { requireAdminPage } from "@/lib/admin-server";

import { SourceReview } from "./SourceReview";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "核验页面 · 鱼跃彼岸", robots: { index: false, follow: false } };

/** One official page: each program's fields, the quotes behind them, the snapshot, and the confirm button. */
export default async function AdminSourcePage({ params }: { params: Promise<{ id: string }> }) {
  await requireAdminPage();
  const id = decodeURIComponent((await params).id);
  return (
    <main className="page">
      <Link className="crumb" href="/admin">← 人工核验</Link>
      <SourceReview id={id} />
    </main>
  );
}
