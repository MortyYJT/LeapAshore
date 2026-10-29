"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import { Field, Pill } from "@/components/ui";
import { patchProfile } from "@/lib/api";
import {
  ENGLISH_TESTS,
  EMPTY_PROFILE,
  englishScoreOf,
  missingBasics,
  parseEnglishScore,
  type BasicField,
  type EnglishTest,
} from "@/lib/assess";
import { exactInstitution, findInstitutions, type InstitutionHit } from "@/lib/institution-search";
import { BUDGET_OPTIONS, DEGREE_OPTIONS, EDUCATION_OPTIONS, GPA_SCALE_OPTIONS, INTAKE_OPTIONS, STUDY_AREAS } from "@/lib/taxonomy";
import type { Profile } from "@/lib/types";

const ORIGINS: { value: NonNullable<Profile["schoolOrigin"]>; label: string }[] = [
  { value: "国内", label: "中国大陆" },
  { value: "海外", label: "海外或港澳台" },
];

/** Which control takes focus when a basic is missing. */
const FOCUS: Record<BasicField, string> = { school: "school", gpa: "gpa", targetField: "field", englishScore: "english-test" };

/**
 * The applicant's profile as a form (openspec account-login, spec profile-basics).
 *
 * `basics` shows the four facts the tiers compare and requires all four: it is the step after the first
 * registration and the 先补信息 panel on the tiers page, and it may offer 跳过. `full` shows every field on
 * 我的 and requires none, so a partial edit can be saved. Both save with `PATCH /api/profile` and never keep
 * the background in browser storage.
 */
export function ProfileForm({
  initial,
  mode,
  idPrefix = "pf",
  onSaved,
  onSkip,
  onCancel,
  submitLabel = "保存",
}: {
  initial: Profile | null;
  mode: "basics" | "full";
  idPrefix?: string;
  onSaved: (profile: Profile) => void;
  onSkip?: () => void;
  onCancel?: () => void;
  submitLabel?: string;
}) {
  const [profile, setProfile] = useState<Profile>(initial ?? EMPTY_PROFILE);
  const [english, setEnglish] = useState(() => parseEnglishScore((initial ?? EMPTY_PROFILE).englishScore));
  const [errors, setErrors] = useState<Partial<Record<BasicField, string>>>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [hits, setHits] = useState<InstitutionHit[]>([]);
  const [listed, setListed] = useState<InstitutionHit | null>(null);
  const looked = useRef(false);
  const id = (name: string) => `${idPrefix}-${name}`;

  useEffect(() => {
    if (looked.current || !initial) return;
    looked.current = true;
    if (initial.schoolOrigin === "国内" && initial.schoolName) void exactInstitution(initial.schoolName).then(setListed);
  }, [initial]);

  const set = <K extends keyof Profile>(key: K, value: Profile[K]) => setProfile((p) => ({ ...p, [key]: value }));
  const clear = (field: BasicField) => setErrors((e) => ({ ...e, [field]: undefined }));

  async function onSchoolInput(name: string) {
    set("schoolName", name);
    clear("school");
    if (profile.schoolOrigin !== "国内") return;
    const found = await findInstitutions(name);
    setHits(found);
    setListed(found.find((hit) => hit.name === name.trim()) ?? null);
  }

  function pickSchool(hit: InstitutionHit) {
    set("schoolName", hit.name);
    setListed(hit);
    setHits([]);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const englishScore = englishScoreOf(english.test, english.score);
    const schoolName = profile.schoolName.trim();
    // A school the Ministry list does not hold keeps its name and has no tier.
    const domesticTier = profile.schoolOrigin === "国内" && schoolName ? listed?.tier ?? null : null;
    const next: Profile = { ...profile, englishScore, domesticTier, schoolName, major: profile.major.trim() };
    const found: Partial<Record<BasicField, string>> = {};
    if (mode === "basics") for (const m of missingBasics(next)) found[m.field] = `请填写${m.label}`;
    if (english.test && english.test !== "NONE" && !english.score.trim()) found.englishScore = "选了考试就请填总分；还没考请选“还没考”";
    if ((next.gpaScore === null) !== (next.gpaScale === null)) found.gpa = "均分和分制要一起填";
    const first = (Object.keys(FOCUS) as BasicField[]).find((f) => found[f]);
    if (first) {
      setErrors(found);
      document.getElementById(id(FOCUS[first]))?.focus();
      return;
    }
    setSaving(true);
    setSaveError(null);
    const patch: Partial<Profile> =
      mode === "basics"
        ? { schoolOrigin: next.schoolOrigin, schoolName, domesticTier, overseasBand: null, gpaScore: next.gpaScore, gpaScale: next.gpaScale, targetField: next.targetField, englishScore }
        : { ...next, overseasBand: null };
    try {
      await patchProfile(patch);
      onSaved(next);
    } catch {
      setSaveError("没有保存，请稍后再试。");
    } finally {
      setSaving(false);
    }
  }

  const invalid = (field: BasicField) => (errors[field] ? { "aria-invalid": true as const, "aria-describedby": `${id(FOCUS[field])}-error` } : {});
  const required = mode === "basics";

  const school = (
    <>
      <Field label="学校在哪里" required={required} error={errors.school && !profile.schoolOrigin ? errors.school : null} errorId={id("origin")}>
        <div className="choices" role="radiogroup" aria-label="学校在哪里" id={id("origin")} tabIndex={-1}>
          {ORIGINS.map((o) => (
            <label className="choice" key={o.value}>
              <input
                type="radio"
                name={id("origin")}
                checked={profile.schoolOrigin === o.value}
                onChange={() => {
                  set("schoolOrigin", o.value);
                  clear("school");
                  setHits([]);
                  if (o.value !== "国内") setListed(null);
                }}
              />
              {o.label}
            </label>
          ))}
        </div>
      </Field>
      <Field
        label="本科院校"
        htmlFor={id("school")}
        required={required}
        error={errors.school && profile.schoolOrigin ? errors.school : null}
        hint={<SchoolHint origin={profile.schoolOrigin} name={profile.schoolName} listed={listed} />}
      >
        <input
          className="input"
          id={id("school")}
          autoComplete="off"
          placeholder={profile.schoolOrigin === "海外" ? "输入校名" : "输入校名，例如 北京邮电大学"}
          value={profile.schoolName}
          onChange={(e) => void onSchoolInput(e.target.value)}
          {...invalid("school")}
        />
        {hits.length > 0 && (
          <div className="suggest" role="listbox" aria-label="教育部名单里的院校">
            {hits.map((hit) => (
              <button type="button" role="option" aria-selected={listed?.code === hit.code} key={hit.code} onClick={() => pickSchool(hit)}>
                <span>{hit.name}</span>
                <span className="toolbar">
                  {hit.tags.map((t) => (
                    <Pill key={t}>{t}</Pill>
                  ))}
                </span>
              </button>
            ))}
          </div>
        )}
      </Field>
    </>
  );

  const gpa = (
    <Field label="加权均分" htmlFor={id("gpa")} required={required} error={errors.gpa} hint="按成绩单上的加权均分填">
      <div className="toolbar" style={{ flexWrap: "nowrap" }}>
        <input
          className="input num"
          id={id("gpa")}
          inputMode="decimal"
          style={{ flex: 1, minWidth: 0 }}
          value={profile.gpaScore ?? ""}
          onChange={(e) => {
            set("gpaScore", e.target.value.trim() === "" || !Number.isFinite(Number(e.target.value)) ? null : Number(e.target.value));
            clear("gpa");
          }}
          {...invalid("gpa")}
        />
        <select
          className="select"
          aria-label="分制"
          style={{ width: 120 }}
          value={profile.gpaScale ?? ""}
          onChange={(e) => {
            set("gpaScale", e.target.value === "" ? null : Number(e.target.value));
            clear("gpa");
          }}
        >
          <option value="">分制</option>
          {GPA_SCALE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
    </Field>
  );

  const field = (
    <Field label="申请方向" htmlFor={id("field")} required={required} error={errors.targetField}>
      <select
        className="select"
        id={id("field")}
        value={profile.targetField ?? ""}
        onChange={(e) => {
          set("targetField", (e.target.value || null) as Profile["targetField"]);
          clear("targetField");
        }}
        {...invalid("targetField")}
      >
        <option value="">请选择</option>
        {STUDY_AREAS.map((a) => (
          <option key={a}>{a}</option>
        ))}
      </select>
    </Field>
  );

  const englishFields = (
    <>
      <Field label="英语考试" htmlFor={id("english-test")} required={required} error={errors.englishScore}>
        <select
          className="select"
          id={id("english-test")}
          value={english.test}
          onChange={(e) => {
            setEnglish({ test: e.target.value as EnglishTest, score: e.target.value === "NONE" ? "" : english.score });
            clear("englishScore");
          }}
          {...invalid("englishScore")}
        >
          <option value="">请选择</option>
          {ENGLISH_TESTS.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="总分" htmlFor={id("score")}>
        <input
          className="input num"
          id={id("score")}
          inputMode="decimal"
          disabled={english.test === "NONE" || english.test === ""}
          value={english.score}
          onChange={(e) => {
            setEnglish({ ...english, score: e.target.value });
            clear("englishScore");
          }}
        />
      </Field>
    </>
  );

  const actions = (
    <div className="actions">
      <span className={saveError ? "negative" : "muted"} role="status" style={{ marginRight: "auto", alignSelf: "center" }}>
        {saveError ?? (Object.values(errors).some(Boolean) ? `还差 ${Object.values(errors).filter(Boolean).length} 项，见标红的字段。` : "")}
      </span>
      {onSkip && (
        <button className="btn btn-text" type="button" onClick={onSkip}>
          跳过，以后再填
        </button>
      )}
      {onCancel && (
        <button className="btn btn-secondary" type="button" onClick={onCancel}>
          取消
        </button>
      )}
      <button className="btn btn-primary" type="submit" disabled={saving}>
        {saving ? "正在保存…" : submitLabel}
      </button>
    </div>
  );

  if (mode === "basics") {
    return (
      <form noValidate onSubmit={onSubmit} aria-label="分档需要的四项信息">
        <div className="fields" style={{ padding: 0, marginBottom: 20 }}>
          {school}
          {gpa}
          {field}
          {englishFields}
        </div>
        {actions}
      </form>
    );
  }

  return (
    <form className="stagger" noValidate onSubmit={onSubmit} aria-label="编辑背景">
      <section className="form-section" aria-labelledby={id("s1")}>
        <div className="about">
          <h2 id={id("s1")}>你的本科</h2>
          <p>院校层次决定用哪一条均分门槛。院校名单来自教育部，985 / 211 / 双一流按名单自动标注。</p>
        </div>
        <div className="panel fields">
          <Field label="现在的学历">
            <div className="choices" role="radiogroup" aria-label="现在的学历">
              {EDUCATION_OPTIONS.map((o) => (
                <label className="choice" key={o.value}>
                  <input type="radio" name={id("education")} checked={profile.educationLevel === o.value} onChange={() => set("educationLevel", o.value)} />
                  {o.value}
                </label>
              ))}
            </div>
          </Field>
          {school}
          <Field label="专业" htmlFor={id("major")}>
            <input className="input" id={id("major")} value={profile.major} onChange={(e) => set("major", e.target.value)} />
          </Field>
          {gpa}
        </div>
      </section>
      <section className="form-section" aria-labelledby={id("s2")}>
        <div className="about">
          <h2 id={id("s2")}>申请目标</h2>
          <p>入学时间决定路线图从哪天往前倒推；不填就不排日期。</p>
        </div>
        <div className="panel fields">
          <Field label="申请学位" htmlFor={id("degree")}>
            <select className="select" id={id("degree")} value={profile.targetDegree ?? ""} onChange={(e) => set("targetDegree", (e.target.value || null) as Profile["targetDegree"])}>
              <option value="">请选择</option>
              {DEGREE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.value}
                </option>
              ))}
            </select>
          </Field>
          {field}
          <Field label="入学时间" htmlFor={id("intake")} hint="S1 约 2 月，S2 约 7 月">
            <select className="select" id={id("intake")} value={profile.intake} onChange={(e) => set("intake", e.target.value)}>
              <option value="">请选择</option>
              {INTAKE_OPTIONS.map((o) => (
                <option key={o}>{o}</option>
              ))}
            </select>
          </Field>
          <Field label="每年预算" htmlFor={id("budget")} hint="可以不填，不填就显示为未知">
            <select className="select" id={id("budget")} value={profile.annualBudgetCny ?? ""} onChange={(e) => set("annualBudgetCny", e.target.value === "" ? null : Number(e.target.value))}>
              <option value="">不填</option>
              {BUDGET_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </section>
      <section className="form-section" aria-labelledby={id("s3")}>
        <div className="about">
          <h2 id={id("s3")}>语言</h2>
          <p>按雅思总分比较；其他考试和单项要求逐校标出“去官网确认”。</p>
        </div>
        <div className="panel fields">{englishFields}</div>
      </section>
      {actions}
    </form>
  );
}

function SchoolHint({ origin, name, listed }: { origin: Profile["schoolOrigin"]; name: string; listed: InstitutionHit | null }) {
  if (origin !== "国内") return <>海外或港澳台院校没有统一的均分门槛，分档会请你对照官网。</>;
  if (!name.trim()) return <>输入校名，从教育部名单里选。</>;
  if (!listed) return <>名单里没有这所学校：会按你填的名字保存，院校层次记为未知。</>;
  return (
    <>
      {listed.province} · {listed.level} ·{" "}
      {listed.tags.length ? (
        <>
          {listed.tags.map((t) => (
            <span key={t} className="pill pill-neutral" style={{ marginRight: 4 }}>
              {t}
            </span>
          ))}
          自动标注（教育部名单）
        </>
      ) : (
        "不在 985 / 211 名单（教育部名单）"
      )}
    </>
  );
}
