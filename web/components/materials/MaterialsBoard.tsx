"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";

import { MaterialChecklist } from "@/components/materials/MaterialChecklist";
import { MaterialsMap } from "@/components/materials/MaterialsMap";
import { Icon } from "@/components/shell/Icon";
import type { ApplicationRecord } from "@/lib/application-records";
import { countLabel, materialName, typeLabel, type CustomMaterial, type RecordMaterial } from "@/lib/materials";
import { ASKED, NOTED, type MapLine, type MaterialColumn, type MaterialsModel, type Requirement } from "@/lib/materials-map";

/** What the board asks its page to save. Each resolves when the server has answered. */
export interface MaterialsActions {
  /** Tick or clear collected materials of one application, by entry. */
  tick: (record: ApplicationRecord, entries: readonly RecordMaterial[], ready: boolean) => Promise<void>;
  /** Replace one application's own checklist. */
  custom: (record: ApplicationRecord, next: CustomMaterial[]) => Promise<void>;
}

/**
 * The materials screen under its title: the line map, the shared materials (ticked once for every
 * program), the materials that differ (each program's requirement with the sentence it was read from)
 * and every application's own checklist, which is all a program has until its page has been read.
 *
 * `actions` null draws the same blocks read-only (the signed-out demo); a control then calls
 * `onBlocked` instead of saving.
 */
export function MaterialsBoard({
  model,
  selected,
  actions,
  onBlocked,
  busy = false,
}: {
  model: MaterialsModel;
  selected: string | null;
  actions: MaterialsActions | null;
  onBlocked?: () => void;
  busy?: boolean;
}) {
  const own = [...model.unread, ...model.manual, ...model.lines];
  const picked = (line: MapLine) => (selected ? (line.record.id === selected ? " is-sel" : " is-dim") : "");
  const tick = (record: ApplicationRecord, entries: readonly RecordMaterial[], ready: boolean) =>
    actions ? void actions.tick(record, entries, ready) : onBlocked?.();
  const readyShared = model.shared.filter((column) => column.requirements.every((requirement) => requirement.ready)).length;

  return (
    <>
      <section className="block block-map" aria-labelledby="h-map">
        <div className="block-head">
          <h2 id="h-map">各项目要什么</h2>
          <ul className="keys" aria-label="图例">
            <li>
              <svg viewBox="0 0 14 14" aria-hidden="true">
                <circle className="k-stn is-ready" cx="7" cy="7" r="5" />
              </svg>
              已备好
            </li>
            <li>
              <svg viewBox="0 0 14 14" aria-hidden="true">
                <circle className="k-stn" cx="7" cy="7" r="5" />
              </svg>
              还没备好
            </li>
            {model.differing.some((column) => column.requirements.some((requirement) => requirement.differs)) && (
              <li>
                <span className="k-diff">3 封</span>和多数项目不一样
              </li>
            )}
            {model.unread.length > 0 && (
              <li>
                <svg className="k-line" viewBox="0 0 22 14" aria-hidden="true">
                  <path className="k-unread" d="M2 7H20" />
                </svg>
                还没提取
              </li>
            )}
          </ul>
        </div>
        <MaterialsMap model={model} selected={selected} />
        {model.lines.length > 0 && (
          <p className="map-note">要求提取自各项目的官网页面，可能不全，提交前以官网为准。勾选是你自己的核对，系统不审核材料。</p>
        )}
      </section>

      {model.shared.length > 0 && (
        <section className="block" aria-labelledby="h-shared">
          <div className="block-head">
            <h2 id="h-shared">通用材料</h2>
            <p className="block-note">
              {model.shared.length} 项里已备好 {readyShared} 项
            </p>
          </div>
          <ul className="shared">
            {model.shared.map((column) => (
              <SharedItem key={column.type} column={column} disabled={busy} onTick={tick} />
            ))}
          </ul>
        </section>
      )}

      {model.differing.length > 0 && (
        <section className="block" aria-labelledby="h-diff">
          <div className="block-head">
            <h2 id="h-diff">{model.shared.length > 0 || model.lines.length > 1 ? "各项目不同的材料" : "官网要求的材料"}</h2>
          </div>
          <div className="diffs">
            <div className="diff-head" aria-hidden="true">
              <span>材料</span>
              <span>要求</span>
              <span>要交的项目，勾选表示已备好</span>
            </div>
            {model.differing.map((column) => (
              <DifferingRow key={column.type} column={column} picked={picked} disabled={busy} onTick={tick} />
            ))}
          </div>
        </section>
      )}

      {/* A demo has no applicant, so it has no checklist of an applicant's own. */}
      {actions && own.length > 0 && (
        <section className="block" aria-labelledby="h-own">
          <div className="block-head">
            <h2 id="h-own">自己的清单</h2>
            <p className="block-note">官网没列到、你自己要备的材料记在这里</p>
          </div>
          <ul className="own">
            {own.map((line) => (
              <OwnList
                key={line.record.id}
                line={line}
                dim={picked(line)}
                disabled={busy || !actions}
                onCustom={(next) => (actions ? void actions.custom(line.record, next) : onBlocked?.())}
              />
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

type Tick = (record: ApplicationRecord, entries: readonly RecordMaterial[], ready: boolean) => void;

/** A shared material: one checkbox that ticks it for every program, and each program's own sentence. */
function SharedItem({ column, disabled, onTick }: { column: MaterialColumn; disabled: boolean; onTick: Tick }) {
  const [open, setOpen] = useState(false);
  const done = column.requirements.filter((requirement) => requirement.ready).length;
  const all = column.requirements.length;
  const count = countLabel(column.type, column.requirements[0].entries[0].count);
  return (
    <li>
      <label className="check">
        <input
          type="checkbox"
          checked={done === all}
          ref={(node) => {
            if (node) node.indeterminate = done > 0 && done < all;
          }}
          disabled={disabled}
          onChange={(event) => {
            for (const requirement of column.requirements) {
              if (requirement.ready !== event.target.checked) onTick(requirement.line.record, requirement.entries, event.target.checked);
            }
          }}
        />
        <span className="text">
          <b>{typeLabel(column.type)}</b>
          <span>
            {all} 个项目都要{count && `，各 ${count}`}
            {done > 0 && done < all && `，备好 ${done} 个`}
          </span>
        </span>
      </label>
      <SourceButton open={open} onToggle={() => setOpen(!open)} />
      {open && <Quotes requirements={column.requirements} />}
    </li>
  );
}

/** A material whose requirement is not the same everywhere: what most ask, who departs from it, who does not ask. */
function DifferingRow({
  column,
  picked,
  disabled,
  onTick,
}: {
  column: MaterialColumn;
  picked: (line: MapLine) => string;
  disabled: boolean;
  onTick: Tick;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const usual = column.requirements.filter((requirement) => !requirement.differs);
  const marked = column.requirements.filter((requirement) => requirement.differs);
  // With a common form, the programs that follow it share one line; without one, every program has its own.
  const grouped = column.common !== null && usual.length > 1;
  const separate = grouped ? marked : column.requirements;
  const toggle = (id: string) => setOpen(open === id ? null : id);
  return (
    <div className="diff">
      <h3>{typeLabel(column.type)}</h3>
      <div className="diff-req">
        {grouped && (
          <div className="exc is-common">
            <span className="who">
              {usual.map((requirement) => (
                <span key={requirement.line.record.id} className={`bullet line-${requirement.line.line}${picked(requirement.line)}`} title={requirement.line.record.school}>
                  {requirement.line.code}
                </span>
              ))}
            </span>
            <span className="what">{column.common ? `要 ${column.common}` : "要交，页面没写份数"}</span>
            <SourceButton open={open === "common"} onToggle={() => toggle("common")} />
            {open === "common" && <Quotes requirements={usual} />}
          </div>
        )}
        {separate.map((requirement) => (
          <div className={`exc${picked(requirement.line)}`} key={requirement.line.record.id}>
            <span className={`bullet line-${requirement.line.line}`} title={requirement.line.record.school}>
              {requirement.line.code}
            </span>
            <span className="what">
              {requirement.entries.map((entry, index) => (
                <span key={entry.key} className="entry">
                  {index > 0 && "；"}
                  {requirement.differs ? <mark>{entryCount(entry)}</mark> : entryCount(entry)}
                  {entry.note && column.type !== "other" && <span lang="en">，{entry.note}</span>}
                </span>
              ))}
            </span>
            <SourceButton open={open === requirement.line.record.id} onToggle={() => toggle(requirement.line.record.id)} />
            {open === requirement.line.record.id && <Quotes requirements={[requirement]} />}
          </div>
        ))}
        {column.absent.length > 0 && (
          <p className="absent">
            {column.absent.map((line) => line.record.school).join("、")}的页面没有列这一项。
          </p>
        )}
      </div>
      <div className="toggles">
        <span className="toggles-label">勾选已备好的项目</span>
        {column.requirements.map((requirement) => (
          <Toggle key={requirement.line.record.id} requirement={requirement} name={typeLabel(column.type)} dim={picked(requirement.line)} disabled={disabled} onTick={onTick} />
        ))}
      </div>
    </div>
  );
}

/** `2 封`; without a stated number, that it is asked or that something is noted. An `other` entry is named by its note. */
function entryCount(entry: RecordMaterial): string {
  if (entry.type === "other") return materialName(entry);
  return countLabel(entry.type, entry.count) || (entry.note ? NOTED : ASKED);
}

/** A line bullet as a checkbox: hollow until the applicant says this program's material is ready. */
function Toggle({ requirement, name, dim, disabled, onTick }: { requirement: Requirement; name: string; dim: string; disabled: boolean; onTick: Tick }) {
  const { line, entries, ready } = requirement;
  const changed = entries.some((entry) => entry.changed && !entry.ready);
  return (
    <label className={`bt line-${line.line}${dim}${changed ? " is-changed" : ""}`} title={changed ? `${line.record.school}：官网的要求改过，请重新核对` : line.record.school}>
      <input
        type="checkbox"
        checked={ready}
        disabled={disabled}
        aria-label={`${line.record.school}的${name}已备好${changed ? "（官网的要求改过，请重新核对）" : ""}`}
        onChange={(event) => onTick(line.record, entries, event.target.checked)}
      />
      <span className="bullet">
        <Icon name="check" />
        {line.code}
      </span>
    </label>
  );
}

function SourceButton({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button type="button" className="srcbtn" aria-expanded={open} onClick={onToggle}>
      出处
    </button>
  );
}

/** The sentences the requirements were read from, each with its program and the page it is on. */
function Quotes({ requirements }: { requirements: readonly Requirement[] }) {
  return (
    <div className="mat-cites">
      {requirements.flatMap((requirement) =>
        requirement.entries.map((entry) => (
          <figure className="mat-cite" key={`${requirement.line.record.id}:${entry.key}`}>
            <blockquote lang="en">{entry.quote}</blockquote>
            <figcaption>
              <span className={`bullet line-${requirement.line.line}`}>{requirement.line.code}</span>
              <a className="link" href={entry.sourceUrl} target="_blank" rel="noreferrer">
                {requirement.line.record.school}官网页面
              </a>
              <span className="pill pill-outline">官网原文，机器核对</span>
            </figcaption>
          </figure>
        )),
      )}
    </div>
  );
}

/** One application's own checklist, with what the map knows about the program beside its name. */
function OwnList({ line, dim, disabled, onCustom }: { line: MapLine; dim: string; disabled: boolean; onCustom: (next: CustomMaterial[]) => void }) {
  const { record } = line;
  // A program with its official list and no line of the applicant's own shows one quiet action, not an
  // empty field: most applicants add nothing here.
  const [adding, setAdding] = useState(false);
  const quiet = record.materialsExtracted && record.customMaterials.length === 0 && !adding;
  const state: ReactNode = !record.programId ? (
    <span className="st">手动添加</span>
  ) : record.materialsExtracted ? (
    <span className="st is-sent">官网要求 {record.materials.length} 项</span>
  ) : (
    <span className="st is-idea">还没提取</span>
  );
  return (
    <li className={`own-row line-${line.line}${dim}`}>
      <div className="own-id">
        <span className="bullet">{line.code}</span>
        <div className="txt">
          <div className="school">
            {record.programId ? <Link href={`/programs/${encodeURIComponent(record.programId)}`}>{record.school}</Link> : record.school}
            {state}
          </div>
          <div className="program">{record.name}</div>
        </div>
      </div>
      <div className="own-list">
        {record.programId && !record.materialsExtracted && (
          <p className="own-note">这个项目的官网要求还没提取，图上是一条虚线。先在这里列自己的清单，以官网为准。</p>
        )}
        {quiet ? (
          <button type="button" className="btn btn-text btn-small own-add" disabled={disabled} onClick={() => setAdding(true)}>
            <Icon name="plus" />
            加一项自己的材料
          </button>
        ) : (
        <MaterialChecklist
          compact
          materials={[]}
          extracted={record.materialsExtracted}
          catalog={Boolean(record.programId)}
          ticked={{}}
          onTick={() => undefined}
          custom={record.customMaterials}
          onCustom={onCustom}
          disabled={disabled}
        />
        )}
      </div>
    </li>
  );
}
