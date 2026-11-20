/**
 * The applicant's own model key (docs/product/PRD-multi-device.md, 3.5).
 *
 * The key is kept in this browser's localStorage and nowhere else on this side. Each advisor request
 * carries it in a header (never in the URL or the body); the server uses it for that request and
 * stores nothing (`api/app/agent/model_key.py`). Signing out removes it.
 */

export const MODEL_KEY_STORAGE = "leapashore:model-key";
/** Fired on `window` when the stored key is saved or removed. */
export const MODEL_KEY_CHANGED = "leapashore:model-key-changed";
export const KEY_HEADER = "X-Model-Key";
export const PROVIDER_HEADER = "X-Model-Provider";

/** The providers the server accepts, by the ids it knows. The server holds each one's address. */
export const PROVIDERS = [
  { id: "deepseek", label: "DeepSeek", model: "deepseek-flash" },
  { id: "siliconflow", label: "硅基流动", model: "deepseek-ai/DeepSeek-V4-Flash" },
] as const;

export type ProviderId = (typeof PROVIDERS)[number]["id"];

export interface StoredModelKey {
  provider: ProviderId;
  key: string;
}

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function providerOf(id: string) {
  return PROVIDERS.find((provider) => provider.id === id) ?? null;
}

// The same shape the server accepts: 8 to 256 letters, digits and . _ ~ + / = -
const KEY_SHAPE = /^[A-Za-z0-9._~+/=-]{8,256}$/;

/** Why `raw` cannot be a key, or null when it can. Says nothing about whether the provider accepts it. */
export function keyProblem(raw: string): string | null {
  const key = raw.trim();
  if (!key) return "先粘贴密钥。";
  if (/\s/.test(key)) return "密钥中间不应该有空格或换行，请重新粘贴。";
  if (key.length < 8) return "这串字符太短，不像一把密钥。";
  if (!KEY_SHAPE.test(key)) return "密钥里有不认识的字符，请从服务商页面重新复制。";
  return null;
}

export function readModelKey(store: Store): StoredModelKey | null {
  try {
    const stored = JSON.parse(store.getItem(MODEL_KEY_STORAGE) ?? "null") as Partial<StoredModelKey> | null;
    if (!stored || typeof stored.key !== "string" || typeof stored.provider !== "string") return null;
    if (!providerOf(stored.provider) || keyProblem(stored.key)) return null;
    return { provider: stored.provider, key: stored.key };
  } catch {
    return null;
  }
}

export function saveModelKey(store: Store, provider: ProviderId, raw: string): StoredModelKey {
  const stored = { provider, key: raw.trim() };
  store.setItem(MODEL_KEY_STORAGE, JSON.stringify(stored));
  return stored;
}

export function removeModelKey(store: Store): void {
  store.removeItem(MODEL_KEY_STORAGE);
}

/** The headers that carry a key to the advisor; none when there is no key. */
export function modelKeyHeaders(stored: StoredModelKey | null): Record<string, string> {
  return stored ? { [KEY_HEADER]: stored.key, [PROVIDER_HEADER]: stored.provider } : {};
}

/** A key as the page shows it once saved: its first three and last four characters. */
export function maskKey(key: string): string {
  return key.length >= 12 ? `${key.slice(0, 3)}…${key.slice(-4)}` : `…${key.slice(-2)}`;
}

function browserStore(): Store | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null; // storage is blocked in this browser
  }
}

function announce() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(MODEL_KEY_CHANGED));
}

/** The key stored in this browser, if any. */
export function storedModelKey(): StoredModelKey | null {
  const store = browserStore();
  return store ? readModelKey(store) : null;
}

export function storeModelKey(provider: ProviderId, raw: string): StoredModelKey | null {
  const store = browserStore();
  if (!store) return null;
  try {
    const stored = saveModelKey(store, provider, raw);
    announce();
    return stored;
  } catch {
    return null;
  }
}

/** Remove the stored key: asked for in settings, and done on sign-out. */
export function forgetModelKey(): void {
  const store = browserStore();
  if (!store) return;
  try {
    const had = store.getItem(MODEL_KEY_STORAGE) !== null;
    removeModelKey(store);
    if (had) announce();
  } catch {
    // nothing stored can be reached, so nothing is left to remove
  }
}

export interface KeyCheck {
  ok: boolean;
  message: string;
}

/** What the server said about a key it tried, or about why it did not try. */
export function keyCheckResult(status: number, body: unknown, label: string): KeyCheck {
  const data = (body ?? {}) as { ok?: unknown; message?: unknown; detail?: unknown };
  if (status === 200 && data.ok === true) {
    return { ok: true, message: `${label} 接受了这把密钥。测试只查了模型列表，没有产生费用。` };
  }
  if (status === 200 && typeof data.message === "string") return { ok: false, message: data.message };
  if (status === 401) return { ok: false, message: "登录已失效，请重新登录后再测试。" };
  const detail = data.detail as { message?: unknown } | undefined;
  if (detail && typeof detail.message === "string") return { ok: false, message: detail.message };
  return { ok: false, message: `没能测试（HTTP ${status}），请稍后再试。` };
}

/** Ask the server to try the key against its provider's model list, which costs nothing. */
export async function checkModelKey(stored: StoredModelKey): Promise<KeyCheck> {
  const label = providerOf(stored.provider)?.label ?? stored.provider;
  try {
    const response = await fetch("/api/advisor/key/check", {
      method: "POST",
      credentials: "same-origin",
      headers: modelKeyHeaders(stored),
    });
    return keyCheckResult(response.status, await response.json().catch(() => null), label);
  } catch {
    return { ok: false, message: "连不上服务器，没能测试。" };
  }
}
