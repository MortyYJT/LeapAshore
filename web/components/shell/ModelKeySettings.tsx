"use client";

import Link from "next/link";
import { useEffect, useId, useState, type FormEvent } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import {
  MODEL_KEY_CHANGED,
  PROVIDERS,
  type ProviderId,
  type StoredModelKey,
  checkModelKey,
  forgetModelKey,
  keyProblem,
  maskKey,
  providerOf,
  storeModelKey,
  storedModelKey,
} from "@/lib/model-key";

/**
 * Settings → 模型密钥: the applicant's own key for the advisor's model
 * (docs/product/PRD-multi-device.md, 3.5). The key stays in this browser; the page shows only its
 * ends once it is saved. `report` writes the one status line under the settings panel.
 */
export function ModelKeySettingsPanel({ report, close }: { report: (message: string) => void; close: () => void }) {
  const { gated, requireLogin } = useAuth();
  const [stored, setStored] = useState<StoredModelKey | null>(null);
  const [provider, setProvider] = useState<ProviderId>("deepseek");
  const [draft, setDraft] = useState("");
  const [problem, setProblem] = useState("");
  const [checking, setChecking] = useState(false);
  const field = useId();

  useEffect(() => {
    const read = () => setStored(storedModelKey());
    read();
    window.addEventListener(MODEL_KEY_CHANGED, read);
    // Another tab of this browser saved or removed the key.
    window.addEventListener("storage", read);
    return () => {
      window.removeEventListener(MODEL_KEY_CHANGED, read);
      window.removeEventListener("storage", read);
    };
  }, []);

  function save(event: FormEvent) {
    event.preventDefault();
    const found = keyProblem(draft);
    if (found) {
      setProblem(found);
      return;
    }
    if (!storeModelKey(provider, draft)) {
      setProblem("这个浏览器不允许网页保存数据，密钥没有存下。");
      return;
    }
    setDraft("");
    setProblem("");
    report("已保存在这个浏览器里。顾问的下一条消息开始用它。");
  }

  function remove() {
    forgetModelKey();
    setProblem("");
    report("已从这个浏览器删除。顾问改用本站的密钥和每日额度。");
  }

  async function check() {
    if (!stored) return;
    setChecking(true);
    setProblem("");
    report("");
    const result = await checkModelKey(stored);
    setChecking(false);
    if (result.ok) report(result.message);
    else setProblem(result.message);
  }

  const saved = stored ? providerOf(stored.provider) : null;

  return (
    <>
      <p className="uc-description">
        顾问默认用本站的密钥，每人每天有额度。填上你自己的密钥后，对话改用它，不占本站额度，费用由你的服务商账户结算。
      </p>
      {gated ? (
        <div className="uc-row">
          <div>
            <h3>登录后填写</h3>
            <p className="uc-hint">顾问登录后才能用，密钥也在登录后填。退出登录时它会从浏览器里删除。</p>
          </div>
          <button className="btn btn-secondary" onClick={() => void requireLogin()}>
            登录
          </button>
        </div>
      ) : stored && saved ? (
        <div className="uc-row uc-key-saved">
          <div>
            <h3>{saved.label}</h3>
            <p className="uc-hint">
              <span className="uc-key-mask">{maskKey(stored.key)}</span>
              <span>模型 {saved.model}</span>
            </p>
          </div>
          <div className="toolbar">
            <button className="btn btn-secondary" onClick={() => void check()} disabled={checking}>
              {checking ? "正在测试" : "测试"}
            </button>
            <button className="btn btn-text negative" onClick={remove}>
              删除
            </button>
          </div>
        </div>
      ) : (
        <form className="uc-key-form" onSubmit={save} noValidate>
          <div className="uc-row">
            <div>
              <h3>服务商</h3>
              <p className="uc-hint">模型 {providerOf(provider)?.model}。接口地址由本站固定。</p>
            </div>
            <div className="uc-modes" role="group" aria-label="服务商">
              {PROVIDERS.map((item) => (
                <button key={item.id} type="button" aria-pressed={provider === item.id} onClick={() => setProvider(item.id)}>
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          <label className="uc-field" htmlFor={field}>
            密钥
          </label>
          <div className="uc-key-entry">
            <input
              id={field}
              className="input"
              type="password"
              value={draft}
              placeholder="粘贴在服务商后台创建的 API 密钥"
              autoComplete="off"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              aria-invalid={problem ? true : undefined}
              aria-describedby={problem ? `${field}-problem` : undefined}
              onChange={(event) => {
                setDraft(event.target.value);
                setProblem("");
              }}
            />
            <button className="btn btn-primary" type="submit">
              保存
            </button>
          </div>
        </form>
      )}
      {problem && (
        <p className="notice notice-error uc-key-problem" role="alert" id={`${field}-problem`}>
          {problem}
        </p>
      )}
      <h3 className="uc-key-heading">这把密钥会到哪里</h3>
      <ul className="uc-key-facts">
        <li>它只存在这台设备的这个浏览器里，不同步到你的其他设备。退出登录时会删除。</li>
        <li>
          每次给顾问发消息，它放在请求头里经 HTTPS 发到本站服务器。服务器处理这一次请求时在内存里用它，转给你选的服务商，不写进数据库、对话存档和日志。
        </li>
        <li>
          它要经过本站服务器，所以运营者在技术上读得到。建议单独建一把密钥，在服务商后台设好消费上限，或者只在账户里留少量余额。
        </li>
      </ul>
      <p className="uc-hint">
        <Link href="/privacy#model-key" onClick={close}>
          隐私政策里的完整说明
        </Link>
      </p>
    </>
  );
}
