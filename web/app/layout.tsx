import type { Metadata, Viewport } from "next";

import { AdvisorProvider, DockScript } from "@/components/advisor/AdvisorProvider";
import { AuthProvider } from "@/components/auth/AuthProvider";
import { ApplicationRecordsProvider } from "@/components/shell/ApplicationRecords";
import { InstallScript } from "@/components/shell/Install";
import { Shell } from "@/components/shell/Shell";
import { ThemeScript } from "@/components/shell/ThemeScript";

import "./globals.css";
import "./shell.css";
import "./overview.css";
import "./advisor.css";
import "./motion.css";

export const metadata: Metadata = {
  title: "鱼跃彼岸 · 硕士申请规划",
  description: "填一次背景，看哪些项目的官方要求你已经满足；选好学校后，从今天到入学，每个阶段要准备什么、依据来自哪个官方页面，都在一张图上。",
  applicationName: "鱼跃彼岸",
  // Added to an iOS home screen, the site opens in its own window (app/manifest.ts does the same for
  // other systems). The page then runs under the status bar, whose text iOS draws light: the rail's
  // colour is kept behind it (shell.css, "installed").
  appleWebApp: { capable: true, title: "鱼跃彼岸", statusBarStyle: "black-translucent" },
  // Next writes `mobile-web-app-capable`; iOS before 17.4 reads only its own name for it.
  other: { "apple-mobile-web-app-capable": "yes" },
};

// `viewportFit: cover` lets the installed app paint to the screen's edges, with the safe-area insets
// kept clear in globals.css and shell.css.
//
// No `themeColor` here on purpose. The browser's bars take the rail's colour in the theme the app is
// showing, which the settings can set against the system, so the one theme-color meta is written by
// ThemeScript and kept in step by UserCenter (lib/pwa.ts, applyThemeColor). Metas rendered from here
// follow only the system, and React re-inserts them ahead of any other on a client-side navigation,
// where the browser would read them first.
export const viewport: Viewport = { viewportFit: "cover" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // ThemeScript sets `data-appearance` before React hydrates, which is the one mismatch allowed here.
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <ThemeScript />
        <InstallScript />
        <DockScript />
      </head>
      <body>
        <AuthProvider>
          <ApplicationRecordsProvider>
            <AdvisorProvider>
              <Shell>{children}</Shell>
            </AdvisorProvider>
          </ApplicationRecordsProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
