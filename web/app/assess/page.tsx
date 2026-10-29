"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Field, Loading, Notice, Pill, SourceNote } from "@/components/ui";
import { patchProfile } from "@/lib/api";
import {
  ENGLISH_TESTS,
  EMPTY_PROFILE,
  englishScoreOf,
  missingRequired,
  parseEnglishScore,
  type EnglishTest,
  type RequiredField,
} from "@/lib/assess";
import { useProfile } from "@/lib/hooks/useProfile";
import { BUDGET_OPTIONS, DEGREE_OPTIONS, EDUCATION_OPTIONS, GPA_SCALE_OPTIONS, INTAKE_OPTIONS, STUDY_AREAS } from "@/lib/taxonomy";
import type { Profile } from "@/lib/types";

import { exactInstitution, findInstitutions, type InstitutionHit } from "./institution-search";

const ORIGINS: { value: NonNullable<Profile["schoolOrigin"]>; label: string }[] = [
  { value: "国内", label: "中国大陆" },
  { value: "海外", label: "海外或港澳台" },
];

/** Where each required field's error is shown and which control takes focus. */
const FIELD_IDS: Record<RequiredField, string> = {
  educationLevel: "education",
  schoolOrigin: "origin",
  major: "major",
  gpaScore: "gpa",
  targetDegree: "degree",
  targetField: "field",
  englishScore: "english-test",
  intake: "intake",
};

/**
 * The background assessment (spec background-assessment): one page, filled from the server profile and
 * saved with PATCH before moving on. Nothing is kept in browser storage.
 */
export default function AssessPage() {
  const router = useRouter();
  const { data: saved, error: loadError, loading } = useProfile();
  const [profile, setProfile] = useState<Profile>(EMPTY_PROFILE);
  const [english, setEnglish] = useState<{ test: EnglishTest; score: string }>({ test: "", score: "" });
  const [errors, setErrors] = useState<Partial<Record<RequiredField, string>>>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [hits, setHits] = useState<InstitutionHit[]>([]);
  const [listed, setListed] = useState<InstitutionHit | null>(null);
  const filled = useRef(false);

  useEffect(() => {
    if (!saved || filled.current) return;
    filled.current = true;
    setProfile(saved);
    setEnglish(parseEnglishScore(saved.englishScore));
    if (saved.schoolOrigin === "国内" && saved.schoolName) void exactInstitution(saved.schoolName).then(setListed);
  }, [saved]);

  const set = <K extends keyof Profile>(key: K, value: Profile[K]) => {
    setProfile((p) => ({ ...p, [key]: value }));
    setErrors((e) => ({ ...e, [key]: undefined }));
  };

  async function onSchoolInput(name: string) {
    set("schoolName", name);
    if (profile.schoolOrigin !== "国内") return;
    const found = await findInstitutions(name);
    setHits(found);
    const exact = found.find((hit) => hit.name === name.trim()) ?? null;
    setListed(exact);
  }

  function pickSchool(hit: InstitutionHit) {
    set("schoolName", hit.name);
    setListed(hit);
    setHits([]);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const englishScore = englishScoreOf(english.test, english.score);
    // A school the Ministry list does not hold keeps its name and has no tier (spec scenario).
    const domesticTier = profile.schoolOrigin === "国内" && profile.schoolName.trim() ? listed?.tier ?? null : null;
    const next: Profile = { ...profile, englishScore, domesticTier, schoolName: profile.schoolName.trim() };
    const missing = missingRequired(next);
    if (english.test && english.test !== "NONE" && !english.score.trim()) {
      missing.push({ field: "englishScore", label: "英语成绩", reason: "选了考试就请填总分；还没考请选“还没考”" });
    }
    if (missing.length) {
      setErrors(Object.fromEntries(missing.map((m) => [m.field, m.reason])));
      document.getElementById(FIELD_IDS[missing[0].field])?.focus();
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await patchProfile({
        educationLevel: next.educationLevel,
        schoolOrigin: next.schoolOrigin,
        schoolName: next.schoolName,
        domesticTier: next.domesticTier,
        overseasBand: null,
        major: next.major.trim(),
        gpaScore: next.gpaScore,
        gpaScale: next.gpaScale,
        targetDegree: next.targetDegree,
        targetField: next.targetField,
        englishScore: next.englishScore,
        annualBudgetCny: next.annualBudgetCny,
        intake: next.intake,
      });
      router.push("/assess/result");
    } catch {
      // Every value stays where it was; the applicant can try again.
      setSaveError("背景没有保存，请稍后再试。");
      setSaving(false);
    }
  }

  const invalid = (field: RequiredField) => (errors[field] ? { "aria-invalid": true as const, "aria-describedby": `${FIELD_IDS[field]}-error` } : {});

  return (
    <>
      <main className="page">
        <div className="title-row">
          <div>
            <h1>背景测评</h1>
            <p className="lede">填一次，测评结果、选校和路线图都用这份背景。标「必填」的决定能否分档和排日期。</p>
          </div>
        </div>
        {loading && !saved && <div className="section"><Loading what="你的背景" /></div>}
        {loadError && !saved && (
          <div className="section">
            <Notice error>没有读到已保存的背景（{loadError}）。可以直接填写，保存时会再试一次。</Notice>
          </div>
        )}
        <form className="section stagger" noValidate onSubmit={onSubmit}>
          <section className="form-section" aria-labelledby="s1">
            <div className="about">
              <h2 id="s1">你的本科</h2>
              <p>院校层次决定用哪一条均分门槛。院校名单来自教育部，985 / 211 / 双一流按名单自动标注。</p>
            </div>
            <div className="panel fields">
              <Field label="现在的学历" required error={errors.educationLevel} errorId="education">
                <div className="choices" role="radiogroup" aria-label="现在的学历" id="education" tabIndex={-1} {...invalid("educationLevel")}>
                  {EDUCATION_OPTIONS.map((o) => (
                    <label className="choice" key={o.value}>
                      <input type="radio" name="education" checked={profile.educationLevel === o.value} onChange={() => set("educationLevel", o.value)} />
                      {o.value}
                    </label>
                  ))}
                </div>
              </Field>
              <Field label="学校在哪里" required error={errors.schoolOrigin} errorId="origin">
                <div className="choices" role="radiogroup" aria-label="学校在哪里" id="origin" tabIndex={-1} {...invalid("schoolOrigin")}>
                  {ORIGINS.map((o) => (
                    <label className="choice" key={o.value}>
                      <input
                        type="radio"
                        name="origin"
                        checked={profile.schoolOrigin === o.value}
                        onChange={() => {
                          set("schoolOrigin", o.value);
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
                htmlFor="school"
                wide
                hint={<SchoolHint origin={profile.schoolOrigin} name={profile.schoolName} listed={listed} />}
              >
                <input
                  className="input"
                  id="school"
                  autoComplete="off"
                  placeholder={profile.schoolOrigin === "海外" ? "输入校名" : "输入校名，例如 北京邮电大学"}
                  value={profile.schoolName}
                  onChange={(e) => void onSchoolInput(e.target.value)}
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
              <Field label="专业" htmlFor="major" required error={errors.major}>
                <input className="input" id="major" value={profile.major} onChange={(e) => set("major", e.target.value)} {...invalid("major")} />
              </Field>
              <Field label="加权均分" htmlFor="gpa" required error={errors.gpaScore} hint="按成绩单上的加权均分填">
                <div className="toolbar" style={{ flexWrap: "nowrap" }}>
                  <input
                    className="input num"
                    id="gpa"
                    inputMode="decimal"
                    style={{ flex: 1 }}
                    value={profile.gpaScore ?? ""}
                    onChange={(e) => set("gpaScore", e.target.value.trim() === "" || !Number.isFinite(Number(e.target.value)) ? null : Number(e.target.value))}
                    {...invalid("gpaScore")}
                  />
                  <select
                    className="select"
                    aria-label="分制"
                    style={{ width: 120 }}
                    value={profile.gpaScale ?? ""}
                    onChange={(e) => set("gpaScale", e.target.value === "" ? null : Number(e.target.value))}
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
            </div>
          </section>

          <section className="form-section" aria-labelledby="s2">
            <div className="about">
              <h2 id="s2">申请目标</h2>
              <p>入学时间决定路线图从哪天往前倒推；不填就不排日期。</p>
            </div>
            <div className="panel fields">
              <Field label="申请学位" htmlFor="degree" required error={errors.targetDegree}>
                <select className="select" id="degree" value={profile.targetDegree ?? ""} onChange={(e) => set("targetDegree", (e.target.value || null) as Profile["targetDegree"])} {...invalid("targetDegree")}>
                  <option value="">请选择</option>
                  {DEGREE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.value}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="方向" htmlFor="field" required error={errors.targetField}>
                <select className="select" id="field" value={profile.targetField ?? ""} onChange={(e) => set("targetField", (e.target.value || null) as Profile["targetField"])} {...invalid("targetField")}>
                  <option value="">请选择</option>
                  {STUDY_AREAS.map((a) => (
                    <option key={a}>{a}</option>
                  ))}
                </select>
              </Field>
              <Field label="入学时间" htmlFor="intake" required error={errors.intake} hint="S1 约 2 月，S2 约 7 月">
                <select className="select" id="intake" value={profile.intake} onChange={(e) => set("intake", e.target.value)} {...invalid("intake")}>
                  <option value="">请选择</option>
                  {INTAKE_OPTIONS.map((o) => (
                    <option key={o}>{o}</option>
                  ))}
                </select>
              </Field>
              <Field label="每年预算" htmlFor="budget" hint="可以不填，不填就显示为未知">
                <select className="select" id="budget" value={profile.annualBudgetCny ?? ""} onChange={(e) => set("annualBudgetCny", e.target.value === "" ? null : Number(e.target.value))}>
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

          <section className="form-section" aria-labelledby="s3">
            <div className="about">
              <h2 id="s3">语言</h2>
              <p>按雅思总分比较；其他考试和单项要求逐校标出“去官网确认”。</p>
            </div>
            <div className="panel fields">
              <Field label="考试" htmlFor="english-test" required error={errors.englishScore}>
                <select
                  className="select"
                  id="english-test"
                  value={english.test}
                  onChange={(e) => {
                    setEnglish({ test: e.target.value as EnglishTest, score: e.target.value === "NONE" ? "" : english.score });
                    setErrors((x) => ({ ...x, englishScore: undefined }));
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
              <Field label="总分" htmlFor="score">
                <input
                  className="input num"
                  id="score"
                  inputMode="decimal"
                  disabled={english.test === "NONE" || english.test === ""}
                  value={english.score}
                  onChange={(e) => setEnglish({ ...english, score: e.target.value })}
                />
              </Field>
            </div>
          </section>

          <div className="actions">
            <span className={saveError ? "negative" : "muted"} role="status" style={{ marginRight: "auto", alignSelf: "center" }}>
              {saveError ??
                (Object.values(errors).some(Boolean) ? `还差 ${Object.values(errors).filter(Boolean).length} 项必填，见标红的字段。` : "")}
            </span>
            <Link className="btn btn-secondary" href={saved && missingRequired(saved).length === 0 ? "/roadmap" : "/"}>
              取消
            </Link>
            <button className="btn btn-primary" type="submit" disabled={saving}>
              {saving ? "正在保存…" : "保存并查看结果"}
            </button>
          </div>
        </form>
      </main>
      <SourceNote>
        院校数据来源：教育部《全国高等学校名单》（截至 2025 年 6 月 20 日），985 / 211 / 双一流标签按名单自动标注。背景保存在服务器上，清空浏览器缓存不会丢。
      </SourceNote>
    </>
  );
}

function SchoolHint({ origin, name, listed }: { origin: Profile["schoolOrigin"]; name: string; listed: InstitutionHit | null }) {
  if (origin !== "国内") return <>海外或港澳台院校没有统一的均分门槛，测评会请你对照官网。可以不填。</>;
  if (!name.trim()) return <>可以不填；不填时院校层次记为未知。</>;
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
