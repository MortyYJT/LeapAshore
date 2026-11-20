"use client";

import { useState } from "react";
import { Icon } from "@/components/shell/Icon";
import {
  CUSTOM_LABEL_LIMIT,
  CUSTOM_LIMIT,
  materialName,
  newCustomId,
  typeLabel,
  type CustomMaterial,
  type RecordMaterial,
} from "@/lib/materials";

/**
 * One application's material checklist: what the catalogue collected from the program's page, each
 * with its source, then the applicant's own lines. Controlled: the parent holds the ticks and the
 * lines and decides when they are saved.
 *
 * `extracted` false with `catalog` true is a program whose page nobody has read for materials yet. It
 * is said in words, and never drawn as an empty list of requirements. A page that was read and lists
 * no documents is said in words too, with the page to check: it is not a program that asks for none.
 */
export function MaterialChecklist({
  materials,
  extracted,
  catalog,
  pageUrl = null,
  ticked,
  onTick,
  custom,
  onCustom,
  disabled = false,
  compact = false,
}: {
  materials: readonly RecordMaterial[];
  extracted: boolean;
  /** Whether the record is a catalogue program (a manual one has no page in the catalogue to read). */
  catalog: boolean;
  /** The page the materials were read from, linked where it lists nothing the catalogue could cite. */
  pageUrl?: string | null;
  ticked: Readonly<Record<string, boolean>>;
  onTick: (key: string, ready: boolean) => void;
  custom: readonly CustomMaterial[];
  onCustom: (next: CustomMaterial[]) => void;
  disabled?: boolean;
  /** Only the applicant's own lines and the field that adds one: the page around it says the rest. */
  compact?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const label = draft.trim();
  const full = custom.length >= CUSTOM_LIMIT;

  function add() {
    if (!label || full) return;
    onCustom([...custom, { id: newCustomId(), label: label.slice(0, CUSTOM_LABEL_LIMIT), done: false }]);
    setDraft("");
  }

  return (
    <div className="material-checklist">
      {catalog && extracted && materials.length > 0 && (
        <ul className="material-lines" aria-label="官网要求的材料">
          {materials.map((material) => {
            const ready = ticked[material.key] ?? material.ready;
            return (
              <li key={material.key}>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={ready}
                    disabled={disabled}
                    onChange={(event) => onTick(material.key, event.target.checked)}
                  />
                  <span className="material-name">{materialName(material)}</span>
                </label>
                <div className="material-detail">
                  {material.type !== "other" && material.note && <span>{material.note}</span>}
                  {material.type === "other" && <span>{typeLabel(material.type)}</span>}
                  {material.changed && !ready && <span className="material-changed">官网的要求改过，请重新核对</span>}
                  <a href={material.sourceUrl} target="_blank" rel="noreferrer" title={material.quote}>
                    出处
                  </a>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {!compact && catalog && extracted && materials.length === 0 && (
        <p className="small muted">
          读到的项目页没有列申请材料，这不等于不用交。请到
          {pageUrl ? (
            <a className="link" href={pageUrl} target="_blank" rel="noreferrer">
              官网页面
            </a>
          ) : (
            "官网"
          )}
          核对，再在下面列自己的清单。
        </p>
      )}
      {!compact && catalog && !extracted && (
        <p className="small muted">这个项目的材料要求还没提取。先在下面列自己的清单，以官网为准。</p>
      )}
      {custom.length > 0 && (
        <ul className="material-lines" aria-label="自己列的材料">
          {custom.map((item) => (
            <li key={item.id} className="material-own">
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={item.done}
                  disabled={disabled}
                  onChange={(event) => onCustom(custom.map((other) => (other.id === item.id ? { ...other, done: event.target.checked } : other)))}
                />
                <span className="material-name">{item.label}</span>
              </label>
              <button
                type="button"
                className="icon-button"
                aria-label={`删除「${item.label}」`}
                disabled={disabled}
                onClick={() => onCustom(custom.filter((other) => other.id !== item.id))}
              >
                <Icon name="close" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="material-add">
        <input
          className="input"
          value={draft}
          maxLength={CUSTOM_LABEL_LIMIT}
          placeholder={full ? `最多 ${CUSTOM_LIMIT} 项` : "加一项自己的材料，例如：在读证明"}
          aria-label="加一项自己的材料"
          disabled={disabled || full}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            // Enter that commits an input method's composition (拼音 → 汉字) is not "add this line".
            if (event.key === "Enter" && !event.nativeEvent.isComposing && event.keyCode !== 229) {
              event.preventDefault();
              add();
            }
          }}
        />
        <button type="button" className="btn btn-secondary" disabled={disabled || !label || full} onClick={add}>
          添加
        </button>
      </div>
      {!compact && (
        <p className="small muted">
          勾选是你自己的核对，不是审核。{catalog && extracted && materials.length > 0 ? "官网要求来自采集到的页面，可能不全，提交前以官网为准。" : ""}
        </p>
      )}
    </div>
  );
}
