import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OfferPilot · 留学申请规划",
  description: "把留学申请流程画成一张可推进的图：每个阶段要准备什么、什么时候该做、依据来自哪里。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
