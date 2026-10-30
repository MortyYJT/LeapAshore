"use client";

import Link from "next/link";
import { useState } from "react";

import { RequireAccount, useAuth } from "@/components/auth/AuthProvider";
import { ProfileForm } from "@/components/profile/ProfileForm";
import { Button, Loading, Notice } from "@/components/ui";
import { deleteAccount, normalizeEmail } from "@/lib/auth";
import { addMaterialVersion, archiveMaterial, fetchMaterial, submitMaterial } from "@/lib/api";
import { useMaterials } from "@/lib/hooks/useMaterials";
import { useProfile } from "@/lib/hooks/useProfile";
import { KIND_OPTIONS, byteSizeLabel, kindLabel, materialFileUrl, overallLabel, severityLabel, statusLabel, toMaterial } from "@/lib/materials-source";
import { intakeAnchor } from "@/lib/roadmap";
import { labelOf, BUDGET_OPTIONS, GPA_SCALE_OPTIONS } from "@/lib/taxonomy";
import type { Material, MaterialKind, Profile } from "@/lib/types";

function rowsOf(p: Profile): [string, string][] {
  const anchor = intakeAnchor(p.intake);
  const tier = p.schoolOrigin === "国内" ? p.domesticTier ?? "层次未知" : "海外";
  return [
    ["学历", p.educationLevel ?? "未填"],
    ["院校所在地", p.schoolOrigin === "国内" ? "中国大陆" : p.schoolOrigin === "海外" ? "海外或港澳台" : "未填"],
    ["本科院校", p.schoolName ? `${p.schoolName} · ${tier}` : "未填"],
    ["专业", p.major || "未填"],
    ["加权均分", p.gpaScore !== null ? `${p.gpaScore}（${labelOf(GPA_SCALE_OPTIONS, p.gpaScale) || "分制未填"}）` : "未填"],
    ["英语", p.englishScore || "未填"],
    ["申请学位", p.targetDegree ?? "未填"],
    ["方向", p.targetField ?? "未填"],
    ["入学", anchor ? `${anchor.getUTCFullYear()} 年 ${anchor.getUTCMonth() + 1} 月（${p.intake}）` : "未填"],
    ["每年预算", p.annualBudgetCny !== null ? labelOf(BUDGET_OPTIONS, p.annualBudgetCny) : "未知"],
  ];
}

/** 我的: the profile every page uses, the materials library (spec document-library) and the account. */
export default function MePage() {
  return (
    <main className="page">
      <div className="title-row">
        <div>
          <h1>我的</h1>
          <p className="lede">分档、选校和路线图都用这一份背景。改了背景，分档会按新背景重算。</p>
        </div>
      </div>
      <RequireAccount what="你的背景和材料">
        <Mine />
      </RequireAccount>
    </main>
  );
}

function Mine() {
  const profile = useProfile();
  const materials = useMaterials();
  const [editing, setEditing] = useState(false);
  return (
    <div className="stagger">
      <section className={editing ? "section" : "panel section"} aria-labelledby="bg-h">
        <div className={editing ? "section-head" : "panel-head"}>
          <h2 id="bg-h">申请背景</h2>
          {!editing && profile.data && (
            <Button small onClick={() => setEditing(true)}>
              修改背景
            </Button>
          )}
        </div>
        {profile.loading && !profile.data && <div className="panel-pad"><Loading what="背景" /></div>}
        {profile.error && !profile.data && <div className="panel-pad"><Notice error>没有读到背景（{profile.error}）。</Notice></div>}
        {profile.data && editing && (
          <ProfileForm
            initial={profile.data}
            mode="full"
            idPrefix="me"
            onSaved={() => {
              setEditing(false);
              profile.reload();
            }}
            onCancel={() => setEditing(false)}
          />
        )}
        {profile.data && !editing && (
          <dl className="kv2">
            {rowsOf(profile.data).map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd className="num">{v}</dd>
              </div>
            ))}
          </dl>
        )}
      </section>
      <MaterialsLibrary materials={materials} />
      <AccountPanel />
    </div>
  );
}

/** The account: who is logged in, 退出登录, and 注销账号 with the email typed as confirmation. */
function AccountPanel() {
  const { state, signOut, refresh } = useAuth();
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const account = state?.account;
  if (!state?.authEnabled || !account) return null;

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await deleteAccount(typed);
      sessionStorage.clear();
      await refresh();
      window.location.assign("/");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "注销失败，请稍后再试。");
      setBusy(false);
    }
  }

  return (
    <section className="panel section" aria-labelledby="acct-h">
      <div className="panel-head">
        <h2 id="acct-h">账号</h2>
        <Button small onClick={() => void signOut()}>
          退出登录
        </Button>
      </div>
      <div className="panel-pad">
        <p style={{ marginTop: 0 }}>
          登录邮箱：<b>{account.email}</b>
        </p>
        <p className="muted small">
          数据怎么保存、给谁处理、怎么删除，见<Link href="/privacy">隐私政策</Link>。
        </p>
        {!confirming ? (
          <Button variant="text" className="negative" onClick={() => setConfirming(true)}>
            注销账号
          </Button>
        ) : (
          <div className="grid" style={{ gap: 8, maxWidth: 420 }}>
            <label htmlFor="del-email">
              注销会删除这个账号的背景、选校、路线图、上传的材料和登录记录，不能恢复。输入你的登录邮箱确认：
            </label>
            <input id="del-email" className="input" autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} />
            {error && <p className="negative small" role="alert">{error}</p>}
            <div className="toolbar">
              <Button variant="primary" disabled={busy || normalizeEmail(typed) !== account.email} onClick={() => void remove()}>
                {busy ? "正在注销…" : "永久注销"}
              </Button>
              <Button onClick={() => setConfirming(false)}>取消</Button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function MaterialsLibrary({ materials }: { materials: ReturnType<typeof useMaterials> }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Material | null>(null);
  const [kinds, setKinds] = useState<Record<string, MaterialKind>>({});
  const list = materials.data ?? [];

  async function run(id: string, action: () => Promise<unknown>) {
    setBusy(id);
    setError(null);
    try {
      await action();
      materials.reload();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "操作失败，请稍后再试。");
    } finally {
      setBusy(null);
    }
  }

  async function showReviews(id: string) {
    setError(null);
    try {
      setOpen(toMaterial(await fetchMaterial(id)));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "读取材料失败");
    }
  }

  return (
    <section className="panel section" aria-labelledby="mat-h">
      <div className="panel-head">
        <h2 id="mat-h">
          材料库<span className="count num muted" style={{ fontWeight: 400, marginLeft: 6 }}>{list.length}</span>
        </h2>
      </div>
      {error && <div className="panel-pad"><Notice error>{error}</Notice></div>}
      {materials.loading && !materials.data && <div className="panel-pad"><Loading what="材料" /></div>}
      {materials.error && !materials.data && <div className="panel-pad"><Notice error>没有读到材料库（{materials.error}）。</Notice></div>}
      {materials.data && (
        <table className="stack">
          <thead>
            <tr>
              <th>材料</th>
              <th>分类</th>
              <th>状态</th>
              <th className="num">版本</th>
              <th className="num"><span className="sr-only">操作</span></th>
            </tr>
          </thead>
          <tbody>
            {list.length === 0 && (
              <tr>
                <td colSpan={5} className="wide">
                  <div className="empty">
                    还没有上传材料。在<Link href="/roadmap">路线图</Link>的任务上上传，材料会按任务归档在这里，可以下载、送审和上传新版本。
                  </div>
                </td>
              </tr>
            )}
            {list.map((m) => {
              const maySubmit = m.status === "archived" || m.status === "needs_revision";
              return (
                <tr key={m.id}>
                  <td className="wide">
                    <div className="two-line">
                      <div className="l1">{m.title}</div>
                      <div className="l2">
                        {m.currentVersion ? `${m.currentVersion.filename} · ${byteSizeLabel(m.currentVersion.byteSize)}` : "没有文件"}
                      </div>
                    </div>
                  </td>
                  <td>
                    {m.kind ? (
                      kindLabel(m.kind)
                    ) : (
                      <span className="toolbar" style={{ flexWrap: "nowrap" }}>
                        <select
                          className="select"
                          style={{ height: 30, width: 128 }}
                          aria-label={`${m.title} 的分类`}
                          value={kinds[m.id] ?? ""}
                          onChange={(e) => setKinds((k) => ({ ...k, [m.id]: e.target.value as MaterialKind }))}
                        >
                          <option value="">选择分类</option>
                          {KIND_OPTIONS.map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                        <Button small disabled={!kinds[m.id] || busy === m.id} onClick={() => run(m.id, () => archiveMaterial(m.id, kinds[m.id]))}>
                          归档
                        </Button>
                      </span>
                    )}
                  </td>
                  <td>{statusLabel(m.status)}</td>
                  <td className="num">{m.currentVersion?.versionNo ?? "—"}</td>
                  <td className="num">
                    <span className="toolbar" style={{ justifyContent: "flex-end" }}>
                      {m.currentVersion && (
                        <a className="btn btn-text" href={materialFileUrl(m.id, m.currentVersion.versionNo)}>
                          下载
                        </a>
                      )}
                      <label className="btn btn-text">
                        新版本
                        <input
                          type="file"
                          className="sr-only"
                          disabled={busy === m.id}
                          onChange={(e) => {
                            const file = e.target.files?.[0];
                            if (file) void run(m.id, () => addMaterialVersion(m.id, file));
                          }}
                        />
                      </label>
                      <Button variant="text" disabled={!maySubmit || busy === m.id} title={maySubmit ? undefined : "先归档分类，才能送审"} onClick={() => run(m.id, () => submitMaterial(m.id))}>
                        送审
                      </Button>
                      <Button variant="text" onClick={() => void showReviews(m.id)}>
                        审核意见
                      </Button>
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {open && (
        <div className="panel-pad" style={{ borderTop: "1px solid var(--rule)" }} aria-live="polite">
          <div className="section-head">
            <h3>{open.title} 的审核意见</h3>
            <Button variant="text" onClick={() => setOpen(null)}>
              收起
            </Button>
          </div>
          {open.reviews.length === 0 && <p className="muted" style={{ margin: 0 }}>还没有审核意见。</p>}
          {open.reviews.map((r) => (
            <div key={r.id} style={{ marginTop: 12 }}>
              <div>
                <b>{overallLabel(r.overall)}</b> <span className="muted small">{r.createdAt.slice(0, 10)} · {r.reviewedBy}</span>
              </div>
              {r.summary && <p style={{ margin: "4px 0" }}>{r.summary}</p>}
              <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                {r.findings.map((f) => (
                  <li key={f.id}>
                    <span className="muted">{severityLabel(f.severity)}</span> {f.finding}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
