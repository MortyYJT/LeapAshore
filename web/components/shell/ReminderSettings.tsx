"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import {
  LEAD_LIMITS,
  type ReminderChange,
  type ReminderSettings,
  StaleVersionError,
  addLead,
  leadProblem,
  loadReminderSettings,
  removeLead,
  resolveStaleSettings,
  saveReminderSettings,
  unsubscribedDay,
} from "@/lib/reminders";

import { Icon } from "./Icon";

type Conflict = { change: ReminderChange; theirs: ReminderSettings };

const days = (list: number[]) => `${list.join("、")} 天`;

function describe(theirs: ReminderSettings, change: ReminderChange) {
  if ("enabled" in change) return `别的设备刚把邮件提醒${theirs.enabled ? "开启" : "关闭"}了。`;
  return `别的设备刚把提前天数改成了 ${days(theirs.leadDays)}。`;
}

/**
 * The 「提醒」 panel of the settings dialog: deadline reminders by email, on or off, and how many days
 * ahead. Every control saves itself, like the appearance panel. `active` is whether the panel is
 * showing; settings are read the first time it is, and again whenever it is reopened.
 */
export function ReminderSettingsPanel({ active, report }: { active: boolean; report: (message: string) => void }) {
  const { state, ready, gated, requireLogin } = useAuth();
  const email = state?.account?.email ?? null;
  const [settings, setSettings] = useState<ReminderSettings | null>(null);
  const [failed, setFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [entry, setEntry] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [conflict, setConflict] = useState<Conflict | null>(null);

  const load = useCallback(async () => {
    setFailed(false);
    try {
      setSettings(await loadReminderSettings());
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    if (!active || !email) return;
    setConflict(null);
    void load();
  }, [active, email, load]);

  useEffect(() => {
    if (!email) setSettings(null);
  }, [email]);

  async function apply(change: ReminderChange, base: ReminderSettings) {
    setSaving(true);
    setConflict(null);
    report("");
    try {
      let stored: ReminderSettings;
      try {
        stored = await saveReminderSettings(change, base.version);
      } catch (error) {
        if (!(error instanceof StaleVersionError)) throw error;
        const theirs = error.current as ReminderSettings;
        const verdict = resolveStaleSettings(base, change, theirs);
        if (verdict === "ask") {
          setSettings(theirs);
          setConflict({ change, theirs });
          return;
        }
        // The other device changed a different setting (or made this same change): nothing of
        // theirs is overwritten by sending this one again on their version.
        stored = verdict === "adopt" ? theirs : await saveReminderSettings(change, theirs.version);
      }
      setSettings(stored);
      report("提醒设置已保存。");
    } catch (error) {
      if (error instanceof StaleVersionError) setSettings(error.current as ReminderSettings);
      report("提醒设置没有保存成功，请再试一次。");
    } finally {
      setSaving(false);
    }
  }

  function add(event: FormEvent) {
    event.preventDefault();
    if (!settings) return;
    const found = leadProblem(entry, settings.leadDays);
    setProblem(found);
    if (found) return;
    setEntry("");
    void apply({ leadDays: addLead(settings.leadDays, Number(entry.trim())) }, settings);
  }

  if (!ready) return <p className="uc-description">正在读取…</p>;
  if (!email) {
    return (
      <>
        <p className="uc-description">
          {gated ? "提醒邮件发到登录邮箱，登录后可以在这里设置。" : "提醒邮件发到登录邮箱。这个站点没有开启登录，所以用不了。"}
        </p>
        {gated && (
          <button className="btn btn-secondary" onClick={() => void requireLogin()}>
            登录
          </button>
        )}
      </>
    );
  }

  const day = settings && !settings.enabled ? unsubscribedDay(settings.unsubscribedAt) : null;
  const only = settings?.leadDays.length === 1;
  return (
    <>
      <p className="uc-description">截止日期临近时，发一封邮件到 {email}。</p>
      {failed && (
        <p className="notice notice-error" role="alert">
          没有读到提醒设置。
          <button className="btn btn-text" onClick={() => void load()}>
            重试
          </button>
        </p>
      )}
      {!settings && !failed && <p className="uc-hint">正在读取提醒设置…</p>}
      {settings && (
        <>
          {conflict && (
            <div className="notice notice-conflict" role="alert">
              <p>{describe(conflict.theirs, conflict.change)}下面显示的是那边改完的样子。</p>
              <div className="toolbar">
                <button
                  className="btn btn-secondary btn-small"
                  disabled={saving}
                  onClick={() => void apply(conflict.change, conflict.theirs)}
                >
                  按我刚才改的保存
                </button>
                <button className="btn btn-text" onClick={() => setConflict(null)}>
                  保持现在这样
                </button>
              </div>
            </div>
          )}
          <div className="uc-row">
            <div>
              <h3>邮件提醒</h3>
              <p className="uc-hint">
                {day
                  ? `你在 ${day} 通过邮件里的链接退订了。选「开启」就恢复。`
                  : "一天最多一封，同一天要提醒的项目写在一起。"}
              </p>
            </div>
            <div className="uc-modes" role="group" aria-label="邮件提醒">
              {[
                { on: true, label: "开启" },
                { on: false, label: "关闭" },
              ].map((choice) => (
                <button
                  key={choice.label}
                  type="button"
                  aria-pressed={settings.enabled === choice.on}
                  disabled={saving}
                  onClick={() => {
                    if (settings.enabled !== choice.on) void apply({ enabled: choice.on }, settings);
                  }}
                >
                  {choice.label}
                </button>
              ))}
            </div>
          </div>
          <div className="uc-row uc-row-leads">
            <div>
              <h3 id="uc-leads-title">提前几天</h3>
              <p className="uc-hint">
                {settings.enabled ? `截止前 ${days(settings.leadDays)}各发一次。` : "提醒关着，开启后按这些天数发。"}
              </p>
            </div>
            <div className="uc-leads">
              <ul aria-labelledby="uc-leads-title">
                {settings.leadDays.map((value) => (
                  <li key={value}>
                    <span className="num">{value}</span> 天
                    <button
                      type="button"
                      className="uc-lead-remove"
                      aria-label={`删掉提前 ${value} 天的提醒`}
                      title={only ? "至少留一个。不想收邮件就把提醒关掉。" : undefined}
                      disabled={saving || only}
                      onClick={() => void apply({ leadDays: removeLead(settings.leadDays, value) }, settings)}
                    >
                      <Icon name="close" />
                    </button>
                  </li>
                ))}
              </ul>
              <form className="uc-lead-add" onSubmit={add} noValidate>
                <input
                  className="input num"
                  inputMode="numeric"
                  value={entry}
                  maxLength={2}
                  placeholder="天数"
                  aria-label="要加的提前天数"
                  aria-invalid={problem ? true : undefined}
                  aria-describedby="uc-leads-problem"
                  onChange={(event) => {
                    setEntry(event.target.value);
                    setProblem(null);
                  }}
                />
                <button className="btn btn-secondary" disabled={saving}>
                  添加
                </button>
              </form>
              <p className="uc-hint uc-leads-problem" id="uc-leads-problem" role={problem ? "alert" : undefined}>
                {problem ?? `${LEAD_LIMITS.min} 到 ${LEAD_LIMITS.max} 天，最多 ${LEAD_LIMITS.count} 个。`}
              </p>
            </div>
          </div>
          <p className="uc-hint">
            只提醒状态是「考虑中」和「准备中」的申请，没填截止日期的不提醒。天数按北京时间的日期算；具体几点截止、按哪个时区，以学校官网为准。
          </p>
        </>
      )}
    </>
  );
}
