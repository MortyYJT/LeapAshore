import type { MetadataRoute } from "next";

import { THEME_COLOR } from "../lib/pwa.ts";

const ICON = { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" } as const;

/**
 * The web app manifest, served at /manifest.webmanifest: what a browser needs to install the site as
 * an app in its own window (docs/product/PRD-multi-device.md, 3.2). Icons come from
 * scripts/make-icons.cjs.
 *
 * The `any` icons are transparent and drawn in one mid-tone ink, because the taskbar, dock or page
 * behind them may be light or dark. The `maskable` ones keep a full-bleed ground: a launcher cuts
 * them to its own shape.
 *
 * A manifest has one colour per role, not one per theme. Both take the rail's light-theme colour (the
 * sidebar grey): it is the maskable icon's own ground, so the launch screen shows the mark on one flat
 * field. Once a page is up, its theme-color meta takes over.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "鱼跃彼岸 LeapAshore",
    short_name: "鱼跃彼岸",
    description: "把每个硕士项目的轮次、截止日期、材料和申请进度放在一处，登录后在各台设备上同步。",
    lang: "zh-CN",
    dir: "ltr",
    start_url: "/",
    scope: "/",
    display: "standalone",
    theme_color: THEME_COLOR.light,
    background_color: THEME_COLOR.light,
    icons: [
      { ...ICON, purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/maskable-192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
    shortcuts: [
      { name: "总览", url: "/", icons: [ICON] },
      { name: "我的申请", url: "/applications", icons: [ICON] },
      { name: "AI 顾问", short_name: "顾问", url: "/advisor", icons: [ICON] },
    ],
  };
}
