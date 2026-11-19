import type { Metadata, Viewport } from "next";

import { AuthProvider } from "@/components/auth/AuthProvider";
import { ApplicationRecordsProvider } from "@/components/shell/ApplicationRecords";
import { Shell } from "@/components/shell/Shell";
import { ThemeScript } from "@/components/shell/ThemeScript";

import "./globals.css";
import "./shell.css";
import "./overview.css";
import "./motion.css";

export const metadata: Metadata = {
  title: "鱼跃彼岸 · 硕士申请规划",
  description: "填一次背景，看哪些项目的官方要求你已经满足；选好学校后，从今天到入学，每个阶段要准备什么、依据来自哪个官方页面，都在一张图上。",
};

// The browser's own bars take the rail's colour in each theme.
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#121a28" },
    { media: "(prefers-color-scheme: dark)", color: "#090c12" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // ThemeScript sets `data-appearance` before React hydrates, which is the one mismatch allowed here.
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body>
        <AuthProvider>
          <ApplicationRecordsProvider>
            <Shell>{children}</Shell>
          </ApplicationRecordsProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
