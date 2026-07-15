"use client";

import { useState } from "react";

import type { ApplicationChoice } from "./api-client";


type ChoicePayload = Pick<ApplicationChoice, "status" | "is_primary"> & {
  official_deadline?: string | null;
  deadline_source_url?: string | null;
};

export function PortfolioControls({
  choice,
  onChange,
  showDeadline = false,
}: {
  choice: ApplicationChoice;
  onChange: (payload: ChoicePayload) => Promise<void>;
  showDeadline?: boolean;
}) {
  return (
    <PortfolioControlsEditor
      key={`${choice.updated_at}-${choice.official_deadline ?? ""}-${choice.deadline_source_url ?? ""}`}
      choice={choice}
      onChange={onChange}
      showDeadline={showDeadline}
    />
  );
}

function PortfolioControlsEditor({
  choice,
  onChange,
  showDeadline,
}: {
  choice: ApplicationChoice;
  onChange: (payload: ChoicePayload) => Promise<void>;
  showDeadline: boolean;
}) {
  const [deadline, setDeadline] = useState(choice.official_deadline?.slice(0, 16) ?? "");
  const [sourceUrl, setSourceUrl] = useState(choice.deadline_source_url ?? "");
  const [busy, setBusy] = useState(false);

  async function apply(payload: ChoicePayload) {
    setBusy(true);
    try {
      await onChange(payload);
    } finally {
      setBusy(false);
    }
  }

  const preserved = {
    official_deadline: choice.official_deadline ?? null,
    deadline_source_url: choice.deadline_source_url ?? null,
  };

  return (
    <div className="portfolio-controls" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
      <div className="choice-buttons" aria-label="申请项目状态">
        {([
          ["considering", "待定"],
          ["applying", "确定申请"],
          ["excluded", "不考虑"],
        ] as const).map(([status, label]) => (
          <button
            type="button"
            key={status}
            className={choice.status === status ? "active" : ""}
            disabled={busy}
            onClick={() => apply({ status, is_primary: status === "applying" && choice.is_primary, ...preserved })}
          >
            {label}
          </button>
        ))}
        {choice.status === "applying" && (
          <button
            type="button"
            className={`primary-choice ${choice.is_primary ? "active" : ""}`}
            disabled={busy}
            onClick={() => apply({ status: "applying", is_primary: !choice.is_primary, ...preserved })}
          >
            {choice.is_primary ? "★ 首选项目" : "☆ 设为首选"}
          </button>
        )}
      </div>
      {showDeadline && choice.status === "applying" && (
        <div className="deadline-editor">
          <label>学校官方截止日期<input type="datetime-local" value={deadline} onChange={(event) => setDeadline(event.target.value)} /></label>
          <label>官方来源链接<input type="url" value={sourceUrl} placeholder="https://…" onChange={(event) => setSourceUrl(event.target.value)} /></label>
          <button
            type="button"
            className="outline-button"
            disabled={busy || (!!sourceUrl && !sourceUrl.startsWith("http"))}
            onClick={() => apply({
              status: "applying",
              is_primary: choice.is_primary,
              official_deadline: deadline ? new Date(deadline).toISOString() : null,
              deadline_source_url: sourceUrl || null,
            })}
          >
            保存截止日期
          </button>
          <small>未填写时使用系统倒推的建议时间；最终期限始终以学校官网为准。</small>
        </div>
      )}
    </div>
  );
}
