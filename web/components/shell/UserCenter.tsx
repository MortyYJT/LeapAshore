"use client";

import Link from "next/link";
import { useEffect, useLayoutEffect, useRef, useState, type ChangeEvent } from "react";
import { useAuth } from "@/components/auth/AuthProvider";

import { Icon } from "./Icon";
import { ReminderSettingsPanel } from "./ReminderSettings";

const COLORS = [{ id: "graphite", name: "默认" }] as const;
const TABS = [
  { id: "profile", label: "个人资料" },
  { id: "appearance", label: "外观" },
  { id: "reminders", label: "提醒" },
  { id: "account", label: "账号" },
] as const;
/** Another part of the page asks for the settings dialog on one tab: `detail` is the tab's id. */
export const SETTINGS_EVENT = "leapashore-settings";
/** The mode last applied, under a key that does not depend on the account: app/layout.tsx reads it before first paint. */
export const APPEARANCE_KEY = "leapashore:appearance";
type Preferences = {
  name: string;
  avatar: string;
  mode: string;
  color: string;
};
const DEFAULTS: Preferences = {
  name: "",
  avatar: "",
  mode: "system",
  color: "graphite",
};

export function UserCenter() {
  const { state, ready, signOut, gated, openLogin } = useAuth();
  const [prefs, setPrefs] = useState(DEFAULTS);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("profile");
  const [message, setMessage] = useState("");
  const [uploading, setUploading] = useState(false);
  const [shown, setShown] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const tabs = useRef<HTMLDivElement>(null);
  const indicator = useRef<HTMLSpanElement>(null);
  const key = `leapashore:preferences:${state?.account?.email ?? "browser"}`;
  const name = state?.account ? prefs.name || "申请者" : "未登录";

  useLayoutEffect(() => {
    const list = tabs.current;
    const highlight = indicator.current;
    const selected = list?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (!list || !highlight || !selected) return;

    const position = () => {
      if (!selected.offsetWidth) return;
      highlight.style.width = `${selected.offsetWidth}px`;
      highlight.style.height = `${selected.offsetHeight}px`;
      highlight.style.translate = `${selected.offsetLeft}px ${selected.offsetTop}px`;
      list.dataset.positioned = "true";
    };
    position();
    const observer = new ResizeObserver(position);
    observer.observe(list);
    return () => observer.disconnect();
  }, [tab]);

  useEffect(() => {
    setLoadedKey(null);
    // Preferences are kept per account, so nothing is read (or applied) until the session is known:
    // reading the signed-out copy first would flash its theme before the account's.
    if (!ready) return;
    try {
      const raw = JSON.parse(localStorage.getItem(key) || "null");
      setPrefs({
        name: typeof raw?.name === "string" ? raw.name.slice(0, 30) : "",
        avatar:
          typeof raw?.avatar === "string" &&
          raw.avatar.startsWith("data:image/webp;base64,")
            ? raw.avatar
            : "",
        mode: ["system", "light", "dark"].includes(raw?.mode)
          ? raw.mode
          : "system",
        color: COLORS.some((c) => c.id === raw?.color) ? raw.color : "graphite",
      });
    } catch {
      setPrefs(DEFAULTS);
    }
    setLoadedKey(key);
  }, [key, ready]);

  useEffect(() => {
    if (loadedKey !== key) return;
    try {
      localStorage.setItem(key, JSON.stringify(prefs));
      localStorage.setItem(APPEARANCE_KEY, prefs.mode);
    } catch {
      setMessage("浏览器存储空间不足，偏好暂未保存。请移除头像后重试。");
    }
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.appearance =
        prefs.mode === "system"
          ? media.matches
            ? "dark"
            : "light"
          : prefs.mode;
      document.documentElement.dataset.accent = prefs.color;
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [prefs, loadedKey, key]);

  useEffect(() => {
    const update = (event: Event) =>
      setPrefs((p) => ({ ...p, mode: (event as CustomEvent<string>).detail }));
    window.addEventListener("leapashore-theme", update);
    return () => window.removeEventListener("leapashore-theme", update);
  }, []);

  useEffect(() => {
    if (!open) return;
    const pointer = (e: PointerEvent) => {
      if (!menu.current?.contains(e.target as Node)) setOpen(false);
    };
    const keyboard = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", pointer);
    document.addEventListener("keydown", keyboard);
    return () => {
      document.removeEventListener("pointerdown", pointer);
      document.removeEventListener("keydown", keyboard);
    };
  }, [open]);

  function settings(next = "profile") {
    trigger.current?.focus();
    setOpen(false);
    setTab(next);
    setMessage("");
    if (!dialog.current?.open) dialog.current?.showModal();
    setShown(true);
  }
  const openSettings = useRef(settings);
  openSettings.current = settings;
  useEffect(() => {
    const show = (event: Event) => {
      const wanted = (event as CustomEvent<string>).detail;
      openSettings.current(TABS.some((item) => item.id === wanted) ? wanted : "profile");
    };
    window.addEventListener(SETTINGS_EVENT, show);
    return () => window.removeEventListener(SETTINGS_EVENT, show);
  }, []);
  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0];
    e.target.value = "";
    if (!selected) return;
    if (
      !["image/jpeg", "image/png", "image/webp"].includes(selected.type) ||
      selected.size > 5 * 1024 * 1024
    ) {
      setMessage("请选择 5 MB 以内的 JPG、PNG 或 WebP 图片。");
      return;
    }
    setUploading(true);
    const url = URL.createObjectURL(selected);
    try {
      const image = new Image();
      image.src = url;
      await image.decode();
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 256;
      const context = canvas.getContext("2d");
      if (!context) throw new Error();
      const size = Math.min(image.width, image.height);
      context.drawImage(
        image,
        (image.width - size) / 2,
        (image.height - size) / 2,
        size,
        size,
        0,
        0,
        256,
        256,
      );
      setPrefs((p) => ({ ...p, avatar: canvas.toDataURL("image/webp", 0.85) }));
      setMessage("头像已更新。");
    } catch {
      setMessage("无法读取图片，请换一张重试。");
    } finally {
      URL.revokeObjectURL(url);
      setUploading(false);
    }
  }
  function avatar(large = false) {
    return (
      <span className={`uc-avatar${large ? " uc-avatar-large" : ""}`}>
        {prefs.avatar ? (
          <img src={prefs.avatar} alt="用户头像" />
        ) : (
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            aria-hidden="true"
          >
            <circle cx="12" cy="8" r="4" />
            <path d="M4 21v-2a8 8 0 0 1 16 0v2" />
          </svg>
        )}
      </span>
    );
  }

  return (
    <div className="user-center" ref={menu}>
      <button
        className="uc-trigger"
        ref={trigger}
        aria-label="我的，打开用户菜单"
        aria-expanded={open}
        aria-controls="user-menu"
        onClick={() => setOpen((v) => !v)}
      >
        {avatar()}
        <span className="uc-name">{name}</span>
      </button>
      <div className="uc-menu" id="user-menu" aria-label="用户菜单" data-open={open} inert={!open}>
        <div className="uc-identity">
          {avatar()}
          <div>
            <strong>{name}</strong>
            {state?.account?.email && <p>{state.account.email}</p>}
          </div>
        </div>
        <div className="uc-menu-group">
          <Link href="/me#background" onClick={() => setOpen(false)}>
            申请背景
          </Link>
          <Link href="/materials" onClick={() => setOpen(false)}>
            我的材料
          </Link>
        </div>
        <div className="uc-menu-group">
          <button onClick={() => settings()}>设置</button>
        </div>
        {gated && (
          <div className="uc-menu-group">
            <button
              onClick={() => {
                setOpen(false);
                openLogin(window.location.pathname);
              }}
            >
              登录
            </button>
          </div>
        )}
        {state?.account && (
          <div className="uc-menu-group">
            <button
              onClick={() => {
                setOpen(false);
                void signOut().catch(() =>
                  setMessage("退出失败，请稍后重试。"),
                );
              }}
            >
              退出登录
            </button>
          </div>
        )}
      </div>
      <dialog
        className="uc-dialog"
        ref={dialog}
        aria-labelledby="uc-title"
        onClose={() => setShown(false)}
        onClick={(e) => {
          if (e.target === dialog.current) {
            const r = dialog.current.getBoundingClientRect();
            if (
              e.clientX < r.left ||
              e.clientX > r.right ||
              e.clientY < r.top ||
              e.clientY > r.bottom
            )
              dialog.current.close();
          }
        }}
      >
        <div className="uc-settings">
          <aside className="uc-sidebar">
            <h2 id="uc-title">设置</h2>
            <div role="tablist" aria-label="设置分类" ref={tabs}>
              <span className="uc-tab-indicator" aria-hidden="true" ref={indicator} />
              {TABS.map((item) => (
                <button
                  key={item.id}
                  role="tab"
                  id={`uc-tab-${item.id}`}
                  aria-controls={`uc-panel-${item.id}`}
                  aria-selected={tab === item.id}
                  tabIndex={tab === item.id ? 0 : -1}
                  onClick={() => {
                    setTab(item.id);
                    setMessage("");
                  }}
                  onKeyDown={(e) => {
                    const ids = TABS.map((each) => each.id);
                    if (
                      [
                        "ArrowDown",
                        "ArrowRight",
                        "ArrowLeft",
                        "ArrowUp",
                        "Home",
                        "End",
                      ].includes(e.key)
                    ) {
                      e.preventDefault();
                      const i =
                        e.key === "Home"
                          ? 0
                          : e.key === "End"
                            ? ids.length - 1
                            : (ids.indexOf(tab as (typeof ids)[number]) +
                                (["ArrowDown", "ArrowRight"].includes(e.key)
                                  ? 1
                                  : ids.length - 1)) %
                              ids.length;
                      setTab(ids[i]);
                      document.getElementById(`uc-tab-${ids[i]}`)?.focus();
                    }
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </aside>
          <div className="uc-content">
            <button
              className="icon-button uc-close"
              aria-label="关闭设置"
              onClick={() => dialog.current?.close()}
            >
              <Icon name="close" />
            </button>
            <section
              id="uc-panel-profile"
              role="tabpanel"
              aria-labelledby="uc-tab-profile"
              hidden={tab !== "profile"}
            >
              <h2>个人资料</h2>
              <p className="uc-description">让这个申请空间更像你。</p>
              <div className="uc-photo">
                {avatar(true)}
                <div>
                  <button
                    className="btn btn-secondary"
                    disabled={uploading}
                    onClick={() => file.current?.click()}
                  >
                    {uploading ? "正在处理…" : "上传头像"}
                  </button>
                  <button
                    className="btn btn-text"
                    disabled={!prefs.avatar || uploading}
                    onClick={() => {
                      setPrefs((p) => ({ ...p, avatar: "" }));
                      setMessage("已恢复默认头像。");
                    }}
                  >
                    移除
                  </button>
                  <p className="uc-hint">JPG、PNG 或 WebP，最大 5 MB</p>
                  <input
                    ref={file}
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    hidden
                    onChange={upload}
                  />
                </div>
              </div>
              <label className="uc-field">
                显示名称
                <input
                  className="input"
                  value={prefs.name}
                  placeholder="输入显示名称"
                  maxLength={30}
                  autoComplete="nickname"
                  onChange={(e) =>
                    setPrefs((p) => ({ ...p, name: e.target.value }))
                  }
                />
              </label>
              <p className="uc-hint">
                头像和个人偏好保存在此浏览器，不上传服务器。
              </p>
            </section>
            <section
              id="uc-panel-appearance"
              role="tabpanel"
              aria-labelledby="uc-tab-appearance"
              hidden={tab !== "appearance"}
            >
              <h2>外观</h2>
              <p className="uc-description">选择适合你的工作空间。</p>
              <div className="uc-row">
                <div>
                  <h3>显示模式</h3>
                  <p className="uc-hint">应用到整个网站。</p>
                </div>
                <div className="uc-modes" role="group" aria-label="显示模式">
                  {[
                    { id: "system", label: "跟随系统" },
                    { id: "light", label: "浅色" },
                    { id: "dark", label: "深色" },
                  ].map((mode) => (
                    <button
                      key={mode.id}
                      type="button"
                      aria-pressed={prefs.mode === mode.id}
                      onClick={() => setPrefs((p) => ({ ...p, mode: mode.id }))}
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>
              </div>
              <p className="uc-hint">修改即时生效，自动保存。</p>
              <button
                className="btn btn-text"
                onClick={() =>
                  setPrefs((p) => ({ ...p, mode: "system", color: "graphite" }))
                }
              >
                恢复默认外观
              </button>
            </section>
            <section
              id="uc-panel-reminders"
              role="tabpanel"
              aria-labelledby="uc-tab-reminders"
              hidden={tab !== "reminders"}
            >
              <h2>截止提醒</h2>
              <ReminderSettingsPanel active={shown && tab === "reminders"} report={setMessage} />
            </section>
            <section
              id="uc-panel-account"
              role="tabpanel"
              aria-labelledby="uc-tab-account"
              hidden={tab !== "account"}
            >
              <h2>账号</h2>
              <p className="uc-description">管理登录信息和数据。</p>
              <div className="uc-row">
                <div>
                  <h3>{state?.account ? "登录邮箱" : "未登录"}</h3>
                  <p className="uc-hint">
                    {state?.account?.email ?? "尚未登录账号。"}
                  </p>
                </div>
              </div>
              <div className="uc-row">
                <div>
                  <h3>隐私政策</h3>
                  <p className="uc-hint">了解个人资料和材料如何使用。</p>
                </div>
                <Link
                  href="/privacy"
                  className="btn btn-secondary"
                  onClick={() => dialog.current?.close()}
                >
                  查看
                </Link>
              </div>
              {state?.account && (
                <details className="uc-advanced">
                  <summary>账号高级操作</summary>
                  <p className="uc-hint">
                    注销会永久删除账号的背景、材料和规划。
                  </p>
                  <Link
                    className="btn btn-text negative"
                    href="/me#account"
                    onClick={() => dialog.current?.close()}
                  >
                    管理和注销账号
                  </Link>
                </details>
              )}
            </section>
            <p className="uc-status" role="status">
              {message}
            </p>
          </div>
        </div>
      </dialog>
    </div>
  );
}
