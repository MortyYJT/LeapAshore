"use client";

import { useState } from "react";
import {
  KIND_OPTIONS,
  byteSizeLabel,
  kindLabel,
  materialFileUrl,
  overallLabel,
  severityLabel,
  statusLabel,
} from "@/lib/materials-source";
import { UNKNOWN } from "@/lib/programs-source";
import type { Material, MaterialKind } from "@/lib/types";

/**
 * The applicant's material library: what they have uploaded, what state each one is in, and what a
 * review said about it.
 *
 * Every state on this screen is the server's own. A material's classification, its review status and
 * its versions all come from `GET /api/documents`, and nothing here keeps a local opinion about them —
 * a status this page remembered would be indistinguishable on screen from one the server holds, which
 * is the divergence the file's writes exist to report instead.
 *
 * A value the build cannot interpret renders as 未知 rather than as a guess: a `kind` outside the eight
 * this build knows is not "其他材料", a status outside the five is not "待归档", and a citation whose
 * page could not be read shows no link rather than an empty one.
 */

export interface MaterialsViewProps {
  materials: Material[];
  /** The material whose versions and reviews are open, or null when none is. */
  detail: Material | null;
  /** Why the last read or write failed, or null. */
  error: string | null;
  /** True while a write is in flight, so the controls that would race it are disabled. */
  busy: boolean;
  onOpen: (documentId: string | null) => void;
  onArchive: (documentId: string, kind: MaterialKind) => void;
  onSubmit: (documentId: string) => void;
  onAddVersion: (documentId: string, file: File) => void;
}

const ACCEPTED = ".pdf,.png,.jpg,.jpeg,.docx";

const STATUS_STYLE: Record<string, { color: string; background: string }> = {
  uploaded: { color: "var(--color-ink-soft)", background: "var(--color-line)" },
  archived: { color: "var(--color-brand-dark)", background: "var(--color-brand-soft)" },
  under_review: { color: "#9a6700", background: "var(--color-warn-soft)" },
  needs_revision: { color: "var(--color-danger)", background: "var(--color-danger-soft)" },
  accepted: { color: "var(--color-brand-dark)", background: "var(--color-brand-soft)" },
};

const SEVERITY_STYLE: Record<string, string> = {
  info: "var(--color-ink-soft)",
  warning: "#9a6700",
  blocker: "var(--color-danger)",
};

function Badge({ label, color, background }: { label: string; color: string; background: string }) {
  return (
    <span
      className="rounded-lg px-2 py-0.5 text-xs font-bold"
      style={{ color, background }}
      data-testid="material-badge"
    >
      {label}
    </span>
  );
}

export default function MaterialsView({
  materials,
  detail,
  error,
  busy,
  onOpen,
  onArchive,
  onSubmit,
  onAddVersion,
}: MaterialsViewProps) {
  // The kind each material is about to be classified as, while the applicant has not pressed 归档 yet.
  // Keyed by material: one picker per row, and a row's pending choice is not another row's.
  //
  // There is deliberately no default. The picker used to fall back to 成绩单 so that the select always
  // had a value, which meant one click on 归档 filed an unclassified file as a transcript — a
  // classification the applicant never made, and the exact fabricated value the rest of this codebase
  // refuses to produce. `null` here means "no choice yet", the placeholder option is what the select
  // shows, and 归档 stays disabled until a real choice arrives.
  const [pendingKind, setPendingKind] = useState<Record<string, MaterialKind | null>>({});

  const total = materials.length;
  const reviewed = materials.filter((material) => material.reviews.length > 0).length;

  return (
    <div className="grid gap-6">
      <section>
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-extrabold">材料库</h2>
          <span className="text-sm font-bold text-[var(--color-brand-dark)]">
            {total} 份材料
          </span>
        </div>

        {error && (
          <div className="mb-4 rounded-xl border-2 border-[var(--color-danger)] bg-[var(--color-danger-soft)] p-3">
            <p className="text-sm leading-relaxed text-[var(--color-danger)]">{error}</p>
          </div>
        )}

        {total === 0 && (
          <p className="rounded-xl border-2 border-dashed border-[var(--color-line)] p-6 text-sm leading-relaxed text-[var(--color-ink-soft)]">
            还没有上传任何材料。在「流程进度」里点开一个阶段，用每条材料右边的「上传材料」把文件存进来；
            文件只保存在本机服务端，库里记的是它的类型、大小和校验值。
          </p>
        )}

        <ul className="grid gap-3">
          {materials.map((material) => {
            const current = material.currentVersion;
            const meta = STATUS_STYLE[material.status ?? ""] ?? {
              color: "var(--color-ink-soft)",
              background: "var(--color-line)",
            };
            // Only a classification this build can offer may be pre-selected. A stored kind it cannot
            // name leaves the picker on the placeholder rather than posting that value back on a click:
            // the route would refuse it, and a picker showing a choice the applicant did not make is
            // worse than one showing none.
            const storedChoice = KIND_OPTIONS.find((option) => option.value === material.kind);
            const chosen = pendingKind[material.id] ?? storedChoice?.value ?? "";
            const chosenOption = KIND_OPTIONS.find((option) => option.value === chosen);
            const maySubmit =
              material.status === "archived" || material.status === "needs_revision";
            const open = detail?.id === material.id;
            return (
              <li
                key={material.id}
                className="rounded-xl border-2 border-[var(--color-line)] p-3"
                data-testid="material-row"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-[12rem] flex-1">
                    <p className="text-sm font-bold">{material.title}</p>
                    <p className="mt-0.5 text-xs text-[var(--color-ink-soft)]">
                      {current
                        ? `${current.filename} · ${byteSizeLabel(current.byteSize)} · 第 ${current.versionNo} 版 · ${current.createdAt.slice(0, 10)}`
                        : "还没有上传文件"}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge label={kindLabel(material.kind)} color="var(--color-ink-soft)" background="var(--color-surface)" />
                    <Badge label={statusLabel(material.status)} color={meta.color} background={meta.background} />
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {current && (
                    <a
                      className="rounded-lg border-2 border-[var(--color-line)] px-3 py-1 text-xs font-bold"
                      href={materialFileUrl(material.id, current.versionNo)}
                      download
                    >
                      下载
                    </a>
                  )}

                  <label className="text-xs text-[var(--color-ink-soft)]">
                    <span className="mr-1">分类</span>
                    <select
                      className="rounded-lg border-2 border-[var(--color-line)] bg-[var(--color-canvas)] px-2 py-1 text-xs font-bold"
                      value={chosen}
                      disabled={busy}
                      onChange={(event) =>
                        setPendingKind((prev) => ({
                          ...prev,
                          [material.id]: (event.target.value || null) as MaterialKind | null,
                        }))
                      }
                    >
                      {/* The empty value is the absence of a choice, and it is the only thing that may
                          sit there before the applicant picks one. */}
                      <option value="">请选择分类</option>
                      {KIND_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    className="rounded-lg border-2 border-[var(--color-brand)] px-3 py-1 text-xs font-bold text-[var(--color-brand-dark)] disabled:opacity-50"
                    disabled={busy || chosenOption === undefined}
                    title={chosenOption === undefined ? "先选择一个分类，再归档" : undefined}
                    onClick={() => {
                      if (chosenOption) onArchive(material.id, chosenOption.value);
                    }}
                  >
                    {material.kind === null ? "归档" : "改分类"}
                  </button>

                  <button
                    className="rounded-lg border-2 border-[var(--color-line)] px-3 py-1 text-xs font-bold disabled:opacity-50"
                    disabled={busy || !maySubmit}
                    title={maySubmit ? undefined : "先归档分类，才能送审"}
                    onClick={() => onSubmit(material.id)}
                  >
                    送审
                  </button>

                  <label className="rounded-lg border-2 border-[var(--color-line)] px-3 py-1 text-xs font-bold">
                    上传新版本
                    <input
                      className="hidden"
                      type="file"
                      accept={ACCEPTED}
                      disabled={busy}
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) onAddVersion(material.id, file);
                        // Cleared so choosing the same file twice still fires a change event.
                        event.target.value = "";
                      }}
                    />
                  </label>

                  <button
                    className="rounded-lg border-2 border-[var(--color-line)] px-3 py-1 text-xs font-bold"
                    onClick={() => onOpen(open ? null : material.id)}
                  >
                    {open ? "收起审核" : `查看审核${material.reviews.length > 0 ? `（${material.reviews.length}）` : ""}`}
                  </button>
                </div>

                {open && (
                  <div className="mt-3 rounded-xl bg-[var(--color-surface)] p-3" data-testid="material-detail">
                    <p className="text-xs font-bold text-[var(--color-ink-soft)]">
                      版本（{detail.versions.length}）
                    </p>
                    <ul className="mt-1 grid gap-1">
                      {detail.versions.map((version) => (
                        <li key={version.id} className="text-xs text-[var(--color-ink)]">
                          第 {version.versionNo} 版 · {version.filename} · {byteSizeLabel(version.byteSize)} ·{" "}
                          {version.createdAt.slice(0, 10)}
                        </li>
                      ))}
                    </ul>

                    <p className="mt-3 text-xs font-bold text-[var(--color-ink-soft)]">
                      审核结论（{detail.reviews.length}）
                    </p>
                    {detail.reviews.length === 0 ? (
                      <p className="mt-1 text-xs leading-relaxed text-[var(--color-ink-soft)]">
                        还没有审核结论。送审后由人工写入，每条建议都会写明它引用的审核要点与官方页面。
                      </p>
                    ) : (
                      <ul className="mt-1 grid gap-3">
                        {detail.reviews.map((review) => (
                          <li key={review.id} className="rounded-lg border-2 border-[var(--color-line)] p-2">
                            <p className="text-xs font-bold">
                              {overallLabel(review.overall)} · {review.reviewedBy} ·{" "}
                              {review.createdAt.slice(0, 10)}
                            </p>
                            {review.summary && (
                              <p className="mt-1 text-xs leading-relaxed text-[var(--color-ink)]">
                                {review.summary}
                              </p>
                            )}
                            <ul className="mt-2 grid gap-2">
                              {review.findings.map((finding) => (
                                <li key={finding.id} className="text-xs leading-relaxed">
                                  <span
                                    className="font-bold"
                                    style={{ color: SEVERITY_STYLE[finding.severity ?? ""] ?? "var(--color-ink-soft)" }}
                                  >
                                    [{severityLabel(finding.severity)}]
                                  </span>{" "}
                                  {finding.finding}
                                  <span className="mt-0.5 block text-[var(--color-ink-soft)]">
                                    依据：{finding.criterion.title}（{finding.criterion.code}）——{" "}
                                    {finding.criterion.description}
                                  </span>
                                  <span className="mt-0.5 block text-[var(--color-ink-soft)]">
                                    {finding.criterion.source.url ? (
                                      <>
                                        来源：
                                        <a
                                          className="underline"
                                          href={finding.criterion.source.url}
                                          target="_blank"
                                          rel="noreferrer"
                                        >
                                          {finding.criterion.source.title ?? finding.criterion.source.url}
                                        </a>
                                        （{finding.criterion.source.status}）
                                      </>
                                    ) : (
                                      <>来源：{UNKNOWN}</>
                                    )}
                                  </span>
                                </li>
                              ))}
                            </ul>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>

        {reviewed > 0 && (
          <p className="mt-3 text-xs leading-relaxed text-[var(--color-ink-soft)]">
            已有 {reviewed} 份材料带审核结论。每条建议都指向一条审核要点，要点再指向它出自的官方页面；
            要点本身是否已被人工核验，会在来源后面标出来。
          </p>
        )}
      </section>
    </div>
  );
}
