"use client";

import { useState } from "react";
import { DOMESTIC_TIER_OPTIONS, OVERSEAS_BAND_OPTIONS } from "@/lib/schools";
import {
  BUDGET_OPTIONS,
  DEGREE_OPTIONS,
  EDUCATION_OPTIONS,
  GPA_SCALE_OPTIONS,
  INTAKE_OPTIONS,
  STUDY_AREAS,
} from "@/lib/taxonomy";
import type {
  DegreeLevel,
  DomesticTier,
  EducationLevel,
  OverseasBand,
  Profile,
  StudyArea,
} from "@/lib/types";

const inputClass =
  "rounded-xl border-2 border-[var(--color-line)] px-3 py-2 outline-none focus:border-[var(--color-brand)]";

interface RowProps<T> {
  label: string;
  value: string;
  initialDraft: T;
  renderEditor: (draft: T, setDraft: (v: T) => void) => React.ReactNode;
  onSave: (draft: T) => void;
}

/**
 * One profile field. Editing swaps only this row, so the rest of the profile stays on screen and the
 * applicant never has to walk the onboarding steps again to correct a single value.
 */
function EditableRow<T>({ label, value, initialDraft, renderEditor, onSave }: RowProps<T>) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<T>(initialDraft);

  if (!editing) {
    return (
      <div className="group flex items-center justify-between gap-4 border-b border-[var(--color-line)] py-3 last:border-b-0">
        <span className="shrink-0 text-sm text-[var(--color-ink-soft)]">{label}</span>
        <span className="flex items-center gap-3">
          <span className="text-right text-sm font-semibold">{value || "—"}</span>
          <button
            aria-label={`编辑${label}`}
            onClick={() => {
              setDraft(initialDraft);
              setEditing(true);
            }}
            className="rounded-lg px-2 py-1 text-xs font-bold text-[var(--color-ink-soft)] opacity-0 transition-opacity hover:bg-[var(--color-surface)] focus:opacity-100 group-hover:opacity-100"
          >
            编辑
          </button>
        </span>
      </div>
    );
  }

  return (
    <div className="border-b border-[var(--color-line)] py-3 last:border-b-0">
      <div className="mb-2 text-sm text-[var(--color-ink-soft)]">{label}</div>
      <div className="flex flex-wrap items-center gap-2">
        {renderEditor(draft, setDraft)}
        <button
          className="btn btn-primary !px-4 !py-2 !text-sm"
          onClick={() => {
            onSave(draft);
            setEditing(false);
          }}
        >
          保存
        </button>
        <button className="btn btn-ghost !px-4 !py-2 !text-sm" onClick={() => setEditing(false)}>
          取消
        </button>
      </div>
    </div>
  );
}

function TextEditor({
  draft,
  setDraft,
  placeholder,
}: {
  draft: string;
  setDraft: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <input
      autoFocus
      className={`${inputClass} min-w-[200px] flex-1`}
      value={draft}
      placeholder={placeholder}
      onChange={(e) => setDraft(e.target.value)}
    />
  );
}

function SelectEditor<T extends string>({
  draft,
  setDraft,
  options,
  allowEmpty = true,
}: {
  draft: T;
  setDraft: (v: T) => void;
  options: { value: string; label?: string }[];
  allowEmpty?: boolean;
}) {
  return (
    <select
      autoFocus
      className={`${inputClass} min-w-[200px]`}
      value={draft}
      onChange={(e) => setDraft(e.target.value as T)}
    >
      {allowEmpty && <option value="">未选择</option>}
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label ?? o.value}
        </option>
      ))}
    </select>
  );
}

interface Props {
  profile: Profile;
  onChange: (patch: Partial<Profile>) => void;
  onOpenSettings: () => void;
}

export default function ProfileView({ profile, onChange, onOpenSettings }: Props) {
  const isOverseas = profile.schoolOrigin === "海外";

  return (
    <div className="grid gap-6">
      <header>
        <h1 className="text-xl font-extrabold">个人信息</h1>
        <p className="mt-1 text-sm text-[var(--color-ink-soft)]">
          每条都能单独改，改完立刻影响推荐和流程，不需要重填整份档案。
        </p>
      </header>

      <section className="card">
        <EditableRow<EducationLevel | "">
          label="当前学历"
          value={profile.educationLevel ?? ""}
          initialDraft={profile.educationLevel ?? ""}
          onSave={(v) => onChange({ educationLevel: (v || null) as EducationLevel | null })}
          renderEditor={(draft, setDraft) => (
            <SelectEditor
              draft={draft}
              setDraft={setDraft}
              options={EDUCATION_OPTIONS.map((o) => ({ value: o.value }))}
            />
          )}
        />

        <EditableRow<string>
          label="本科院校"
          value={profile.schoolName}
          initialDraft={profile.schoolName}
          onSave={(v) => onChange({ schoolName: v.trim() })}
          renderEditor={(draft, setDraft) => (
            <TextEditor draft={draft} setDraft={setDraft} placeholder="例如：北京邮电大学" />
          )}
        />

        <EditableRow<string>
          label={isOverseas ? "院校区间" : "院校层次"}
          value={(isOverseas ? profile.overseasBand : profile.domesticTier) ?? ""}
          initialDraft={(isOverseas ? profile.overseasBand : profile.domesticTier) ?? ""}
          onSave={(v) => {
            if (isOverseas) onChange({ overseasBand: (v || null) as OverseasBand | null });
            else onChange({ domesticTier: (v || null) as DomesticTier | null });
          }}
          renderEditor={(draft, setDraft) => (
            <SelectEditor
              draft={draft}
              setDraft={setDraft}
              options={
                isOverseas
                  ? OVERSEAS_BAND_OPTIONS.map((o) => ({ value: o.value, label: o.label }))
                  : DOMESTIC_TIER_OPTIONS.map((o) => ({ value: o.value, label: o.label }))
              }
            />
          )}
        />

        <EditableRow<string>
          label="本科专业"
          value={profile.major}
          initialDraft={profile.major}
          onSave={(v) => onChange({ major: v.trim() })}
          renderEditor={(draft, setDraft) => (
            <TextEditor draft={draft} setDraft={setDraft} placeholder="例如：软件工程" />
          )}
        />

        <EditableRow<{ score: string; scale: number }>
          label="均分"
          value={profile.gpaScore ? `${profile.gpaScore} / ${profile.gpaScale}` : ""}
          initialDraft={{ score: String(profile.gpaScore ?? ""), scale: profile.gpaScale ?? 100 }}
          onSave={(d) => onChange({ gpaScore: d.score === "" ? null : Number(d.score), gpaScale: d.scale })}
          renderEditor={(draft, setDraft) => (
            <>
              <input
                autoFocus
                type="number"
                className={`${inputClass} w-32`}
                value={draft.score}
                onChange={(e) => setDraft({ ...draft, score: e.target.value })}
              />
              <select
                className={inputClass}
                value={String(draft.scale)}
                onChange={(e) => setDraft({ ...draft, scale: Number(e.target.value) })}
              >
                {GPA_SCALE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </>
          )}
        />

        <EditableRow<DegreeLevel | "">
          label="目标学位"
          value={profile.targetDegree ?? ""}
          initialDraft={profile.targetDegree ?? ""}
          onSave={(v) => onChange({ targetDegree: (v || null) as DegreeLevel | null })}
          renderEditor={(draft, setDraft) => (
            <SelectEditor
              draft={draft}
              setDraft={setDraft}
              options={DEGREE_OPTIONS.map((o) => ({ value: o.value }))}
            />
          )}
        />

        <EditableRow<StudyArea | "">
          label="目标方向"
          value={profile.targetField ?? ""}
          initialDraft={profile.targetField ?? ""}
          onSave={(v) => onChange({ targetField: (v || null) as StudyArea | null })}
          renderEditor={(draft, setDraft) => (
            <SelectEditor
              draft={draft}
              setDraft={setDraft}
              options={STUDY_AREAS.map((v) => ({ value: v }))}
            />
          )}
        />

        <EditableRow<string>
          label="语言成绩"
          value={profile.englishScore || "未提供"}
          initialDraft={profile.englishScore}
          onSave={(v) => onChange({ englishScore: v.trim() })}
          renderEditor={(draft, setDraft) => (
            <TextEditor draft={draft} setDraft={setDraft} placeholder="例如：IELTS 6.5" />
          )}
        />

        <EditableRow<string>
          label="年度预算"
          value={profile.annualBudgetCny ? `${profile.annualBudgetCny / 10000} 万 / 年` : ""}
          initialDraft={String(profile.annualBudgetCny ?? "")}
          onSave={(v) => onChange({ annualBudgetCny: v === "" ? null : Number(v) })}
          renderEditor={(draft, setDraft) => (
            <SelectEditor
              draft={draft}
              setDraft={setDraft}
              options={BUDGET_OPTIONS.map((o) => ({ value: String(o.value), label: o.label }))}
            />
          )}
        />

        <EditableRow<string>
          label="入学时间"
          value={profile.intake}
          initialDraft={profile.intake}
          onSave={(v) => onChange({ intake: v || profile.intake })}
          renderEditor={(draft, setDraft) => (
            <SelectEditor
              draft={draft}
              setDraft={setDraft}
              options={INTAKE_OPTIONS.map((v) => ({ value: v }))}
              allowEmpty={false}
            />
          )}
        />
      </section>

      <section className="card">
        <h2 className="text-sm font-bold text-[var(--color-ink-soft)]">数据与隐私</h2>
        <p className="mt-2 text-sm leading-relaxed text-[var(--color-ink-soft)]">
          档案保存在这台设备的浏览器里，没有账号体系，也没有上传到服务器。清除数据与数据来源说明在设置里。
        </p>
        <button className="btn btn-ghost mt-4" onClick={onOpenSettings}>
          打开设置
        </button>
      </section>
    </div>
  );
}
