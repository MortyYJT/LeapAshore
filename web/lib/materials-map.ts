// The materials line map's model (docs/product/PRD-multi-device.md, 3.7): for one applicant, which
// materials every program asks for in the same form and which differ, built from the records alone.
//
// Each application is a line. A material that every extracted program asks for, once, with the same
// count and nothing particular noted, is shared: an interchange all the lines pass through. Any other
// material is a column where a line stops only if its program's page asks for it. A program whose page
// has not been read for materials has no stops at all and is drawn apart from the others, because
// nothing is known about it; it is never treated as asking for nothing.
//
// Pure functions, so the rules are tested without a browser. Nothing here fills a gap: a count the
// page does not state stays unstated, and a note is the collector's own summary, shown as such.

import { activeRecord, type ApplicationRecord } from "./application-records.ts";
import { MATERIAL_TYPES, countLabel, typeLabel, type RecordMaterial } from "./materials.ts";
import { assignLines, lineCode, type LineColour } from "./overview.ts";

/** One application as the map draws it. */
export interface MapLine {
  record: ApplicationRecord;
  code: string;
  line: LineColour;
}

/** What one program asks for under one material type. */
export interface Requirement {
  line: MapLine;
  /** One entry as a rule; a page that sets two essays has two. */
  entries: RecordMaterial[];
  /** The few characters under the station: the count where the page states one. */
  caption: string;
  /** Departs from what most programs ask: another count, something particular noted, or several entries. */
  differs: boolean;
  /** Every entry is ticked. */
  ready: boolean;
}

export interface MaterialColumn {
  type: string;
  name: string;
  /** In the same form for every extracted program: prepared once. */
  shared: boolean;
  /** What most of the programs that ask for it ask, as a count label; "" when they state no count; null when no two agree. */
  common: string | null;
  requirements: Requirement[];
  /** Extracted programs whose page lists no such material. */
  absent: MapLine[];
}

export interface MaterialsModel {
  /** Programs whose page has been read, in the overview's order: the lines of the map. */
  lines: MapLine[];
  /** Catalogue programs whose page has not been read for materials. */
  unread: MapLine[];
  /** Applications added by hand: no page in the catalogue to read. */
  manual: MapLine[];
  shared: MaterialColumn[];
  differing: MaterialColumn[];
  /** Collected requirements across the lines, counted per program, and how many are ticked. */
  total: number;
  done: number;
  /** Applications left out because they are submitted, decided or dropped. */
  closed: number;
}

/** The shorter names the map's column heads use; the lists below it use the full ones. */
const SHORT_NAMES: Record<string, string> = { test_score: "标化成绩", other: "其他" };

export function columnName(type: string): string {
  return SHORT_NAMES[type] ?? typeLabel(type);
}

function byDeadline(a: ApplicationRecord, b: ApplicationRecord): number {
  // Dated applications first, nearest first, then the undated; ids break ties so the order is stable.
  const left = a.deadline ?? "9999-99-99";
  const right = b.deadline ?? "9999-99-99";
  return left < right ? -1 : left > right ? 1 : a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

/**
 * The most frequent value among `values` when at least two share it and no other value is as frequent;
 * null otherwise. Two programs asking for 2 and two asking for 3 have no common form to depart from.
 */
function mode<T>(values: readonly T[]): T | null {
  const counts = new Map<T, number>();
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1);
  const top = Math.max(1, ...counts.values());
  const leaders = [...counts].filter(([, count]) => count === top);
  return top > 1 && leaders.length === 1 ? leaders[0][0] : null;
}

/** The words for a requirement the page states no number for: asked plainly, or asked with something noted. */
export const ASKED = "要交";
export const NOTED = "另有说明";

function captionOf(type: string, entries: readonly RecordMaterial[]): string {
  if (entries.length > 1) return `${entries.length} 项`;
  // An `other` entry's note is its name, not a remark on it.
  return countLabel(type, entries[0].count) || (entries[0].note && type !== "other" ? NOTED : ASKED);
}

/**
 * The model for the applications that are still being prepared. Colours and codes are the overview's,
 * so an application is the same line on every screen. `rail` is the ids the rail's list is drawn from
 * when that is not `records` itself (the signed-out demo): a record in it takes the rail's colour, and
 * the others are coloured among themselves.
 */
export function materialsModel(records: readonly ApplicationRecord[], rail?: readonly string[]): MaterialsModel {
  const railColours = rail ? assignLines(rail) : new Map<string, LineColour>();
  const ownColours = assignLines(records.map((record) => record.id).filter((id) => !railColours.has(id)));
  const colours = new Map([...ownColours, ...railColours]);
  const open = records.filter(activeRecord).sort(byDeadline);
  const asLine = (record: ApplicationRecord): MapLine => ({
    record,
    code: lineCode(record.school),
    line: colours.get(record.id) ?? "green",
  });
  const lines = open.filter((record) => record.programId && record.materialsExtracted).map(asLine);
  const unread = open.filter((record) => record.programId && !record.materialsExtracted).map(asLine);
  const manual = open.filter((record) => !record.programId).map(asLine);

  const shared: MaterialColumn[] = [];
  const differing: MaterialColumn[] = [];
  for (const type of MATERIAL_TYPES) {
    const asking = lines
      .map((line) => ({ line, entries: line.record.materials.filter((material) => material.type === type) }))
      .filter(({ entries }) => entries.length > 0);
    if (!asking.length) continue;
    const plain = asking.filter(({ entries }) => entries.length === 1 && !entries[0].note);
    // "Shared" is a claim about every program the map knows: it needs at least two of them, each
    // asking once, with one count between them and nothing particular noted. `other` entries are
    // different documents under one heading, so they are never merged.
    const isShared =
      type !== "other" &&
      lines.length >= 2 &&
      asking.length === lines.length &&
      plain.length === asking.length &&
      new Set(plain.map(({ entries }) => entries[0].count)).size === 1;
    const commonCount = type === "other" ? null : mode(plain.map(({ entries }) => (entries[0].count === null ? "" : countLabel(type, entries[0].count))));
    const requirements: Requirement[] = asking.map(({ line, entries }) => {
      const single = entries.length === 1 && !entries[0].note;
      const own = single ? (entries[0].count === null ? "" : countLabel(type, entries[0].count)) : null;
      return {
        line,
        entries,
        caption: captionOf(type, entries),
        // With no common form to depart from (one program, or no two alike), nothing "differs".
        differs: !isShared && commonCount !== null && own !== commonCount,
        ready: entries.every((entry) => entry.ready),
      };
    });
    const column: MaterialColumn = {
      type,
      name: columnName(type),
      shared: isShared,
      common: commonCount,
      requirements,
      absent: lines.filter((line) => !asking.some((asked) => asked.line === line)),
    };
    (isShared ? shared : differing).push(column);
  }

  const collected = lines.flatMap((line) => line.record.materials);
  return {
    lines,
    unread,
    manual,
    shared,
    differing,
    total: collected.length,
    done: collected.filter((material) => material.ready).length,
    closed: records.length - open.length,
  };
}

// ---------------------------------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------------------------------

export interface MapLabel {
  kind: "group" | "hub-name" | "hub-state" | "column" | "caption" | "end";
  text: string;
  x: number;
  y: number;
  /** Which line the label belongs to, for the captions and the line ends. */
  line?: MapLine;
  differs?: boolean;
  /** How the label sits on its point. */
  align: "centre" | "left" | "right" | "middle";
}

export interface MapGeometry {
  vertical: boolean;
  width: number;
  height: number;
  /** One path per extracted program: along the trunk, out at 45 degrees, then along its own run. */
  paths: { line: MapLine; d: string }[];
  /** One dotted run per program that has not been read: it joins nothing. */
  dotted: { line: MapLine; d: string }[];
  hubs: { column: MaterialColumn; x: number; y: number; width: number; height: number; ready: boolean }[];
  stations: { requirement: Requirement; x: number; y: number }[];
  guides: { x1: number; y1: number; x2: number; y2: number }[];
  labels: MapLabel[];
}

/** Below this frame width the map is drawn top to bottom. */
export const VERTICAL_BELOW = 640;
/** A column narrower than this cannot hold its head and captions side by side. */
const MIN_COLUMN = 64;
/** In the vertical map, lines closer than this drop their plain captions and keep only the marked ones. */
export const DENSE_PITCH = 44;

const TRUNK_PITCH = 7;

/**
 * Whether a frame this wide draws the map left to right: wide enough, and every capsule and column gets
 * at least `MIN_COLUMN`. `layoutMap` shares the width evenly between them, so the two agree.
 */
export function drawsHorizontally(model: MaterialsModel, width: number): boolean {
  if (width < VERTICAL_BELOW) return false;
  const slots = model.shared.length + model.differing.length;
  const fan = model.shared.length ? (46 - TRUNK_PITCH) * ((model.lines.length - 1) / 2) : 0;
  return slots === 0 || (width - 3 - 54 - fan) / slots >= MIN_COLUMN;
}

function hubState(column: MaterialColumn): { ready: boolean; text: string } {
  const done = column.requirements.filter((requirement) => requirement.ready).length;
  const all = column.requirements.length;
  if (done === all) return { ready: true, text: "已备好" };
  return { ready: false, text: done ? `备好 ${done}/${all}` : "还没备好" };
}

/**
 * Where everything on the map goes, for a frame `width` pixels wide. The lines keep the model's order;
 * on the trunk they run `TRUNK_PITCH` apart, and each has its own run once they fan out.
 */
export function layoutMap(model: MaterialsModel, width: number): MapGeometry {
  const n = model.lines.length;
  const mid = (n - 1) / 2;
  const hubs: MapGeometry["hubs"] = [];
  const stations: MapGeometry["stations"] = [];
  const guides: MapGeometry["guides"] = [];
  const labels: MapLabel[] = [];
  const paths: MapGeometry["paths"] = [];
  const dotted: MapGeometry["dotted"] = [];
  const hasTrunk = model.shared.length > 0;
  const columns = model.differing;

  if (drawsHorizontally(model, width)) {
    const pitch = 46;
    // A run nobody has read carries no caption, so it needs less room than a line with stops.
    const unreadPitch = 30;
    const head = n ? 30 : 8;
    const height = head + n * pitch + model.unread.length * unreadPitch + (n || model.unread.length ? 4 : pitch);
    const left = 3;
    const endRoom = 54;
    const fan = hasTrunk ? (pitch - TRUNK_PITCH) * mid : 0;
    const usable = width - left - endRoom - fan;
    // The trunk and the branches share the width by how many stops each has to hold: every capsule
    // and every column gets the same room.
    const slots = model.shared.length + columns.length;
    const trunk = hasTrunk ? (columns.length ? (usable * model.shared.length) / slots : usable - 24) : 0;
    const branch = usable - trunk;
    const trunkEnd = left + trunk;
    const branchStart = trunkEnd + fan;
    const end = branchStart + branch - 4;
    const centre = head + (pitch * n) / 2;
    const runY = (i: number) => head + pitch * (i + 0.5);
    const trunkY = (i: number) => centre + (i - mid) * TRUNK_PITCH;
    const columnX = (j: number) => branchStart + (branch / Math.max(columns.length, 1)) * (j + 0.5);

    columns.forEach((_, j) => guides.push({ x1: columnX(j), x2: columnX(j), y1: head - 6, y2: head + n * pitch }));
    model.lines.forEach((line, i) => {
      const d = hasTrunk
        ? `M${left} ${trunkY(i)}H${trunkEnd}L${trunkEnd + Math.abs(runY(i) - trunkY(i))} ${runY(i)}H${end}`
        : `M${left} ${runY(i)}H${end}`;
      paths.push({ line, d });
      labels.push({ kind: "end", text: line.code, x: end + 8, y: runY(i), line, align: "middle" });
    });
    model.shared.forEach((column, k) => {
      const x = left + (trunk / model.shared.length) * (k + 0.5);
      const state = hubState(column);
      hubs.push({ column, x: x - 8, y: trunkY(0) - 10, width: 16, height: (n - 1) * TRUNK_PITCH + 20, ready: state.ready });
      labels.push({ kind: "hub-name", text: column.name, x, y: trunkY(0) - 34, align: "centre" });
      labels.push({ kind: "hub-state", text: state.text, x, y: trunkY(n - 1) + 15, align: "centre" });
    });
    columns.forEach((column, j) => {
      labels.push({ kind: "column", text: column.name, x: columnX(j), y: 0, align: "centre" });
      column.requirements.forEach((requirement) => {
        const y = runY(model.lines.indexOf(requirement.line));
        stations.push({ requirement, x: columnX(j), y });
        labels.push({ kind: "caption", text: requirement.caption, x: columnX(j), y: y + 9, line: requirement.line, differs: requirement.differs, align: "centre" });
      });
    });
    model.unread.forEach((line, k) => {
      const y = head + n * pitch + unreadPitch * (k + 0.5);
      dotted.push({ line, d: `M${left} ${y}H${end}` });
      labels.push({ kind: "end", text: line.code, x: end + 8, y, line, align: "middle" });
    });
    if (hasTrunk) labels.push({ kind: "group", text: "通用，准备一份", x: 0, y: 0, align: "left" });
    return { vertical: false, width, height, paths, dotted, hubs, stations, guides, labels };
  }

  // Top to bottom: the hubs stack on the trunk, the lines fan out to one column each, and every
  // differing material is a row.
  const frame = Math.min(width, 420);
  const hubPitch = 34;
  const rowPitch = 50;
  const top = hasTrunk ? 28 : 8;
  const labelWidth = 62;
  const all = n + model.unread.length;
  const lane = (frame - labelWidth - 4) / Math.max(all, 1);
  const laneX = (i: number) => labelWidth + lane * (i + 0.5);
  const centre = labelWidth + (lane * n) / 2;
  const trunkX = (i: number) => centre + (i - mid) * TRUNK_PITCH;
  const trunkEnd = top + hubPitch * model.shared.length;
  const fan = hasTrunk ? (lane - TRUNK_PITCH) * mid : 0;
  const rowsStart = trunkEnd + fan + 8;
  const rowY = (j: number) => rowsStart + rowPitch * j + 14;
  const end = rowsStart + rowPitch * Math.max(columns.length, hasTrunk ? 0 : 1);
  const height = end + 32;
  const dense = lane < DENSE_PITCH;

  columns.forEach((_, j) => guides.push({ x1: 0, x2: frame, y1: rowY(j), y2: rowY(j) }));
  model.lines.forEach((line, i) => {
    const d = hasTrunk
      ? `M${trunkX(i)} ${top - 6}V${trunkEnd}L${laneX(i)} ${trunkEnd + Math.abs(laneX(i) - trunkX(i))}V${end}`
      : `M${laneX(i)} ${top - 6}V${end}`;
    paths.push({ line, d });
    labels.push({ kind: "end", text: line.code, x: laneX(i), y: end + 8, line, align: "centre" });
  });
  model.shared.forEach((column, k) => {
    const y = top + hubPitch * (k + 0.5);
    const state = hubState(column);
    hubs.push({ column, x: trunkX(0) - 10, y: y - 8, width: (n - 1) * TRUNK_PITCH + 20, height: 16, ready: state.ready });
    labels.push({ kind: "hub-name", text: column.name, x: trunkX(0) - 18, y: y - 9, align: "right" });
    labels.push({ kind: "hub-state", text: state.text, x: trunkX(n - 1) + 18, y: y - 9, align: "left" });
  });
  columns.forEach((column, j) => {
    labels.push({ kind: "column", text: column.name, x: 0, y: rowY(j) - 9, align: "left" });
    column.requirements.forEach((requirement) => {
      const x = laneX(model.lines.indexOf(requirement.line));
      stations.push({ requirement, x, y: rowY(j) });
      if (!dense || requirement.differs) {
        labels.push({ kind: "caption", text: requirement.caption, x, y: rowY(j) + 9, line: requirement.line, differs: requirement.differs, align: "centre" });
      }
    });
  });
  model.unread.forEach((line, k) => {
    const x = laneX(n + k);
    dotted.push({ line, d: `M${x} ${rowsStart - 4}V${end}` });
    labels.push({ kind: "end", text: line.code, x, y: end + 8, line, align: "centre" });
  });
  if (hasTrunk) labels.push({ kind: "group", text: "通用，准备一份", x: 0, y: 0, align: "left" });
  return { vertical: true, width: frame, height, paths, dotted, hubs, stations, guides, labels };
}

// ---------------------------------------------------------------------------------------------------
// The signed-out demo
// ---------------------------------------------------------------------------------------------------

/** A served program as the demo reads it: its identity and what the catalogue collected for it. */
export interface DemoMaterialsProgram {
  slug: string;
  name: string;
  nameEn: string | null;
  university: string;
  materials?: { items?: readonly Omit<RecordMaterial, "ready" | "changed" | "digest">[] | null } | null;
}

/** How many programs with collected materials make a map worth showing. */
export const DEMO_MIN_PROGRAMS = 2;
export const DEMO_MAX_PROGRAMS = 5;

/**
 * Records for the signed-out map: the first few listed programs whose page has been read for
 * materials, each with exactly what the catalogue serves and nothing ticked. Null when the catalogue
 * has fewer than `DEMO_MIN_PROGRAMS` of them, so the page falls back to its sign-in block; a program
 * that was not read is never drawn with made-up requirements.
 */
export function demoMaterialRecords(programs: readonly DemoMaterialsProgram[]): ApplicationRecord[] | null {
  const seen = new Set<string>();
  const read = programs.filter((program) => {
    if (!program.materials || !Array.isArray(program.materials.items) || !program.materials.items.length) return false;
    if (seen.has(program.university)) return false;
    seen.add(program.university);
    return true;
  });
  if (read.length < DEMO_MIN_PROGRAMS) return null;
  return read.slice(0, DEMO_MAX_PROGRAMS).map((program) => {
    const materials = (program.materials!.items ?? []).map((item) => ({ ...item, digest: "", ready: false, changed: false }));
    return {
      id: `demo:${program.slug}`,
      programId: program.slug,
      school: program.university,
      name: program.nameEn || program.name,
      round: null,
      status: "applying",
      deadline: null,
      sourceUrl: null,
      checkedAt: null,
      deadlineOrigin: null,
      materials,
      materialsExtracted: true,
      customMaterials: [],
      materialsDone: 0,
      materialsTotal: materials.length,
      materialsReady: false,
      materialNotes: "",
      version: "demo",
    };
  });
}
