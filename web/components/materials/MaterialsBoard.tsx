"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { MaterialChecklist } from "@/components/materials/MaterialChecklist";
import { MaterialsMap } from "@/components/materials/MaterialsMap";
import { Icon } from "@/components/shell/Icon";
import type { ApplicationRecord } from "@/lib/application-records";
import { countLabel, materialName, typeLabel, type CustomMaterial, type RecordMaterial } from "@/lib/materials";
import { ASKED, NOTED, unknownLines, type MapLine, type MaterialColumn, type MaterialsModel, type Requirement } from "@/lib/materials-map";

/** What the board asks its page to save. Each resolves when the server has answered. */
export interface MaterialsActions {
  /** Tick or clear collected materials of one application, by entry. */
  tick: (record: ApplicationRecord, entries: readonly RecordMaterial[], ready: boolean) => Promise<void>;
  /** Replace one application's own checklist. */
  custom: (record: ApplicationRecord, next: CustomMaterial[]) => Promise<void>;
}

/**
 * The materials screen under its title: the line map, the materials every program asks for, the
 * materials only some ask for (each program's requirement with the sentence it was read from) and
 * every application's own checklist, which is all a program has until its page has been read.
 *
 * A material every program asks for in one plain form is ticked once for all of them. One that some
 * program asks for in a form of its own is listed like the materials that differ: that program's
 * wording and source stay on the page, and each program has its own tick.
 *
 * A program whose page was read and lists no documents is drawn like one that was not read: a dotted
 * run with no stops, a note that names it and links its page, and its own checklist. It is never
 * counted among the programs that "do not ask" for a material.
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
  const own = [...unknownLines(model), ...model.manual, ...model.lines];
  const apart = unknownLines(model);
  const picked = (line: MapLine) => (selected ? (line.record.id === selected ? " is-sel" : " is-dim") : "");
  // A tick shows at once and is saved behind it; the controls stay enabled, so the keyboard's focus
  // stays where it was. Once nothing is being saved the page shows what the server holds again, which
  // is the same unless a save was refused.
  const [sent, setSent] = useState<Record<string, boolean>>({});
  useEffect(() => {
    if (!busy) setSent({});
  }, [busy]);
  const isReady: IsReady = (record, entry) => sent[`${record.id}\n${entry.key}`] ?? entry.ready;
  const tick: Tick = (record, entries, ready) => {
    if (!actions) return onBlocked?.();
    setSent((previous) => ({ ...previous, ...Object.fromEntries(entries.map((entry) => [`${record.id}\n${entry.key}`, ready])) }));
    void actions.tick(record, entries, ready);
  };
  const readyShared = model.shared.filter((column) => column.requirements.every((requirement) => requirement.ready)).length;
  const same = model.shared.filter((column) => column.uniform);
  const mixed = model.shared.filter((column) => !column.uniform);
  const markedAtHub = model.shared.some((column) => column.requirements.some((requirement) => requirement.differs));

  return (
    <>
      {/* Only manual applications: nothing the catalogue knows could be drawn, so no empty frame is. */}
      {model.lines.length + apart.length > 0 && (
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
            {markedAtHub && (
              <li>
                <svg viewBox="0 0 14 14" aria-hidden="true">
                  <rect className="k-hub" x="2" y="1" width="10" height="12" rx="5" />
                  <rect className="k-mark" x="3.5" y="4.5" width="7" height="5" rx="2.5" />
                </svg>
                这条线另有要求
              </li>
            )}
            {apart.length > 0 && (
              <li>
                <svg className="k-line" viewBox="0 0 22 14" aria-hidden="true">
                  <path className="k-unread" d="M2 7H20" />
                </svg>
                {[model.unread.length > 0 && "还没提取", model.silent.length > 0 && "页面没列材料"].filter(Boolean).join("，或")}
              </li>
            )}
          </ul>
        </div>
        <MaterialsMap model={model} selected={selected} />
        {model.lines.length > 0 && (
          <p className="map-note">要求提取自各项目的官网页面，可能不全，提交前以官网为准。勾选是你自己的核对，系统不审核材料。</p>
        )}
        {actions && model.unread.length > 0 && (
          <p className="map-note">虚线是官网要求还没提取的项目，它要什么材料现在不知道。先在下面列自己的清单，以官网为准。</p>
        )}
        {model.silent.length > 0 && (
          <p className="map-note">
            {model.silent.map((line, index) => (
              <span key={line.record.id}>
                {index > 0 && "、"}
                {line.record.materialsPageUrl ? (
                  <a className="link" href={line.record.materialsPageUrl} target="_blank" rel="noreferrer">
                    {line.record.school}
                  </a>
                ) : (
                  line.record.school
                )}
              </span>
            ))}
            的项目页读过了，上面没有列申请材料，{model.unread.length > 0 ? "也" : ""}画成虚线。这不等于不用交：清单可能在官网的其他页面，请到官网核对
            {actions ? "，再在下面列自己的清单。" : "。"}
          </p>
        )}
      </section>
      )}

      {model.shared.length > 0 && (
        <section className="block" aria-labelledby="h-shared">
          <div className="block-head">
            <h2 id="h-shared">{mixed.length > 0 ? "各项目都要的材料" : "通用材料"}</h2>
            <p className="block-note">
              {model.shared.length} 项里已备好 {readyShared} 项
            </p>
          </div>
          {same.length > 0 && (
            <ul className="shared">
              {same.map((column) => (
                <SharedItem key={column.type} column={column} isReady={isReady} onTick={tick} />
              ))}
            </ul>
          )}
          {mixed.length > 0 && (
            <>
              <p className="shared-note">
                {same.length > 0 ? `另外 ${mixed.length} 项` : `这 ${mixed.length} 项`}每个项目都要，要求不完全一样，按项目分别准备和勾选。
              </p>
              <div className="diffs">
                <div className="diff-head" aria-hidden="true">
                  <span>材料</span>
                  <span>要求</span>
                  <span>勾选表示已备好</span>
                </div>
                {mixed.map((column) => (
                  <DifferingRow key={column.type} column={column} picked={picked} isReady={isReady} onTick={tick} />
                ))}
              </div>
            </>
          )}
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
              <DifferingRow key={column.type} column={column} picked={picked} isReady={isReady} onTick={tick} />
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
                busy={busy}
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
/** Whether an entry reads as ticked: the tick just made on this page, else the record's. */
type IsReady = (record: ApplicationRecord, entry: RecordMaterial) => boolean;
/** Ticked for an earlier wording of the requirement, and not ticked again since. */
const moved = (entry: RecordMaterial) => entry.changed && !entry.ready;
const CHANGED = "官网的要求改过，请重新核对";

/** A material every program asks for in one plain form: one checkbox that ticks it for all of them, and each program's own sentence. */
function SharedItem({ column, isReady, onTick }: { column: MaterialColumn; isReady: IsReady; onTick: Tick }) {
  const [open, setOpen] = useState(false);
  const ready = (requirement: Requirement) => requirement.entries.every((entry) => isReady(requirement.line.record, entry));
  const done = column.requirements.filter(ready).length;
  const all = column.requirements.length;
  const count = countLabel(column.type, column.requirements[0].entries[0].count);
  const changed = column.requirements.some((requirement) => requirement.entries.some(moved) && !ready(requirement));
  return (
    <li className={open ? "is-open" : undefined}>
      <label className="check">
        <input
          type="checkbox"
          checked={done === all}
          ref={(node) => {
            if (node) node.indeterminate = done > 0 && done < all;
          }}
          onChange={(event) => {
            for (const requirement of column.requirements) {
              if (ready(requirement) !== event.target.checked) onTick(requirement.line.record, requirement.entries, event.target.checked);
            }
          }}
        />
        <span className="text">
          <b>{typeLabel(column.type)}</b>
          <span>
            {all} 个项目都要{count && `，各 ${count}`}
            {done > 0 && done < all && `，备好 ${done} 个`}
          </span>
          {changed && <span className="changed">{CHANGED}</span>}
        </span>
      </label>
      <SourceButton open={open} onToggle={() => setOpen(!open)} />
      {open && <Quotes requirements={column.requirements} />}
    </li>
  );
}

/**
 * A material whose requirement is not the same everywhere: what most ask, who departs from it, who
 * does not ask. Also the row of an interchange that is not uniform, where nobody is absent.
 */
function DifferingRow({
  column,
  picked,
  isReady,
  onTick,
}: {
  column: MaterialColumn;
  picked: (line: MapLine) => string;
  isReady: IsReady;
  onTick: Tick;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const usual = column.requirements.filter((requirement) => !requirement.differs);
  const marked = column.requirements.filter((requirement) => requirement.differs);
  // With a common form, the programs that follow it share one line; without one, every program has its own.
  const grouped = column.common !== null && usual.length > 1;
  const separate = grouped ? marked : column.requirements;
  const toggle = (id: string) => setOpen(open === id ? null : id);
  const changedLines = column.requirements.filter(
    (requirement) => requirement.entries.some(moved) && !requirement.entries.every((entry) => isReady(requirement.line.record, entry)),
  );
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
          <Toggle key={requirement.line.record.id} requirement={requirement} name={typeLabel(column.type)} dim={picked(requirement.line)} isReady={isReady} onTick={onTick} />
        ))}
        {changedLines.length > 0 && (
          <span className="changed">
            {changedLines.map((requirement) => requirement.line.record.school).join("、")}：{CHANGED}
          </span>
        )}
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
function Toggle({ requirement, name, dim, isReady, onTick }: { requirement: Requirement; name: string; dim: string; isReady: IsReady; onTick: Tick }) {
  const { line, entries } = requirement;
  const ready = entries.every((entry) => isReady(line.record, entry));
  const changed = entries.some(moved) && !ready;
  return (
    <label className={`bt line-${line.line}${dim}${changed ? " is-changed" : ""}`} title={changed ? `${line.record.school}：${CHANGED}` : line.record.school}>
      <input
        type="checkbox"
        checked={ready}
        aria-label={`${line.record.school}的${name}已备好${changed ? `（${CHANGED}）` : ""}`}
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
function OwnList({ line, dim, busy, onCustom }: { line: MapLine; dim: string; busy: boolean; onCustom: (next: CustomMaterial[]) => void }) {
  const { record } = line;
  // The list as the applicant last left it on this page, shown while it is being saved; afterwards the
  // record's own list again. Each save sends the whole list, so a second change made before the first
  // has been answered still carries the first.
  const [edited, setEdited] = useState<CustomMaterial[] | null>(null);
  useEffect(() => {
    if (!busy) setEdited(null);
  }, [busy, record.version]);
  const lines = edited ?? record.customMaterials;
  // A program with its official list and no line of the applicant's own shows one quiet action, not an
  // empty field: most applicants add nothing here.
  const [adding, setAdding] = useState(false);
  const quiet = record.materials.length > 0 && lines.length === 0 && !adding;
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (adding) list.current?.querySelector<HTMLInputElement>(".material-add input")?.focus();
  }, [adding]);
  const state: ReactNode = !record.programId ? (
    <span className="st">手动添加</span>
  ) : record.materials.length > 0 ? (
    <span className="st is-sent">官网要求 {record.materials.length} 项</span>
  ) : (
    // Read with nothing listed is said as that: "0 项" would read as "nothing is asked".
    <span className="st is-idea">{record.materialsExtracted ? "页面没列材料" : "还没提取"}</span>
  );
  // Read with nothing to cite: the page that was read is where the applicant checks.
  const page = record.materials.length === 0 ? record.materialsPageUrl : null;
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
          {page && (
            <a className="link own-page" href={page} target="_blank" rel="noreferrer">
              官网页面
            </a>
          )}
        </div>
      </div>
      <div className="own-list" ref={list}>
        {quiet ? (
          <button type="button" className="btn btn-text btn-small own-add" onClick={() => setAdding(true)}>
            <Icon name="plus" />
            加一项自己的材料
          </button>
        ) : (
          <MaterialChecklist
            compact
            materials={[]}
            extracted={record.materialsExtracted}
            catalog={Boolean(record.programId)}
            pageUrl={record.materialsPageUrl}
            ticked={{}}
            onTick={() => undefined}
            custom={lines}
            onCustom={(next) => {
              setEdited(next);
              onCustom(next);
            }}
          />
        )}
      </div>
    </li>
  );
}
