import type { Metadata } from "next";

import { AuthProvider } from "@/components/auth/AuthProvider";
import { Shell } from "@/components/shell/Shell";
import { SiteFooter } from "@/components/shell/SiteFooter";

import "./globals.css";

export const metadata: Metadata = {
  title: "鱼跃彼岸 · 硕士申请规划",
  description: "填一次背景，看哪些项目的官方要求你已经满足；选好学校后，从今天到入学，每个阶段要准备什么、依据来自哪个官方页面，都在一张图上。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <AuthProvider>
          <Shell footer={<SiteFooter />}>{children}</Shell>
        </AuthProvider>
      </body>
    </html>
  );
}
