"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { fetchRoadmapDefinition, patchRoadmapTask, replaceRoadmapTasks } from "../api";
import { buildRoadmap } from "../roadmap";
import { NO_DEFINITION_READ, readRoadmapDefinition, type DefinitionRead } from "../roadmap-definition";
import { toTaskRows, type ServedTask } from "../roadmap-source";
import { alreadyStored, mergeTaskSnapshot, toReplacePayload, type TaskRow } from "../roadmap-sync";
import { beginRead, peekResource, putResource, readStillCurrent, sameAccount, subscribeResource, type ReadTicket } from "../resource-cache";
import { ROADMAP_KEY } from "../resource-keys";
import { StaleVersionError, resolveStaleField } from "../sync-conflict";
import type { Profile, Roadmap } from "../types";

interface TickWrite {
  desired: string;
  confirmed: TaskRow;
}

/** A tick the server refused because another device set this task to a different status. */
export interface TickConflict {
  /** The status this device tried to save. */
  mine: string;
  /** The status the server holds, which is what the checkbox shows until the applicant chooses. */
  theirs: string;
}

/** What is kept of the roadmap for the visit: one read's definition, and the rows as they stand now. */
interface HeldRoadmap {
  read: DefinitionRead;
  tasks: TaskRow[];
}

const NO_TASKS: TaskRow[] = [];
const peekRoadmap = () => peekResource<HeldRoadmap>(ROADMAP_KEY);
const subscribeRoadmap = (listener: () => void) => subscribeResource(ROADMAP_KEY, listener);
const storeRoadmap = (next: HeldRoadmap) => putResource(ROADMAP_KEY, next);
/** Change the kept rows. Nothing is kept before the first read, and then there is nothing to change. */
function changeTasks(change: (previous: TaskRow[]) => TaskRow[]) {
  const shown = peekRoadmap();
  if (shown) storeRoadmap({ read: shown.read, tasks: change(shown.tasks) });
}

/**
 * The saves in flight and the order in which rows were last confirmed. It sits beside the kept rows,
 * above the pages, because a tick outlives the page it was made on: the overview's tick may still be
 * saving when the roadmap page mounts and reads, and that read must not undo it.
 */
interface Ledger {
  account: ReadTicket;
  /** One save per task at a time, by task id. */
  writes: Map<string, TickWrite>;
  /** Raised each time a save is confirmed. A read remembers the value it left at. */
  revision: number;
  /** The revision at which each task's row was last confirmed. */
  confirmedAt: Map<string, number>;
  /** The last recomputed rows sent to `PUT /api/roadmap/tasks`, so the same change is sent once. */
  lastWritten: string | null;
}

let book: Ledger | null = null;
/** The current account's ledger; a new one after the account changed. */
function ledger(): Ledger {
  if (!book || !sameAccount(book.account)) {
    book = { account: beginRead(ROADMAP_KEY), writes: new Map(), revision: 0, confirmedAt: new Map(), lastWritten: null };
  }
  return book;
}
/** The rows a read that left at `revision` may not replace. */
function heldRows(of: Ledger, revision: number): Set<string> {
  const ids = new Set(of.writes.keys());
  for (const [id, confirmed] of of.confirmedAt) if (confirmed > revision) ids.add(id);
  return ids;
}

/** How many times one tick is restated on a newer version before it is reported as not saved. */
const STALE_RETRIES = 3;

export interface RoadmapState {
  roadmap: Roadmap | null;
  /** True while the definition is being read. */
  loading: boolean;
  /** Set when the built-in copy is on screen because the server's definition could not be read. */
  notice: string | null;
  /** Set when the computed rows could not be stored, so ticks may not save. */
  syncError: string | null;
  /** Material keys whose last tick failed and was undone. */
  failedTicks: Set<string>;
  /** Material keys whose last tick met a different status set on another device, and was not saved. */
  tickConflicts: Map<string, TickConflict>;
  /** Answer a conflict: keep this device's tick (saved over the server's) or take the server's. */
  settleTick: (materialKey: string, keepMine: boolean) => void;
  /** The server's id for a material's row, needed to attach an upload to it. */
  taskIdFor: (materialKey: string) => string | null;
  tick: (materialKey: string, done: boolean) => Promise<void>;
  reload: () => void;
}

/**
 * The applicant's roadmap: the served definition dated from the profile's intake, with the ticks the
 * server holds (spec application-roadmap; design D1).
 *
 * The write rules are the old page's, moved here unchanged in substance:
 * - the computed rows are stored only when the definition came from the server and the profile is the
 *   server's (`profile` is null until it is), because a roadmap built from the built-in copy omits the
 *   visa phase and storing it would delete those rows;
 * - nothing is written when the server already holds exactly these rows (`alreadyStored`);
 * - after a write the rows are read again, because a tick needs the ids only the server knows.
 */
export function useRoadmap(profile: Profile | null): RoadmapState {
  // The definition and the rows are kept for the visit (lib/resource-cache.ts), so every page that
  // shows the roadmap draws the same rows and a return visit needs no read before it can draw.
  const held = useSyncExternalStore(subscribeRoadmap, peekRoadmap, () => undefined);
  const read = held?.read ?? NO_DEFINITION_READ;
  const tasks = held?.tasks ?? NO_TASKS;
  const [loading, setLoading] = useState(() => peekRoadmap() === undefined);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [failedTicks, setFailedTicks] = useState<Set<string>>(new Set());
  const [tickConflicts, setTickConflicts] = useState<Map<string, TickConflict>>(new Map());
  const mounted = useRef(true);
  const latestRead = useRef(0);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(() => {
    const readId = ++latestRead.current;
    const ticket = beginRead(ROADMAP_KEY);
    const book = ledger();
    const revision = book.revision;
    if (peekRoadmap() === undefined) setLoading(true);
    void readRoadmapDefinition(fetchRoadmapDefinition).then((next) => {
      // An answer for an account that has since signed out is nobody's.
      if (!sameAccount(ticket)) return;
      const shown = peekRoadmap();
      // A read that left before something newer was stored (a tick, another page's read, the rows a
      // write brought back) is dropped: its rows may predate rows the server has since created.
      // A background read that failed keeps the definition and the rows already on screen; only a
      // first read that failed falls back to the built-in copy and says so.
      const outdated = shown !== undefined && !readStillCurrent(ticket);
      if (!outdated && !(shown && shown.read.definition !== null && next.definition === null)) {
        storeRoadmap({
          read: next,
          tasks: next.tasks !== null ? mergeTaskSnapshot(shown?.tasks ?? NO_TASKS, next.tasks, heldRows(book, revision)) : shown?.tasks ?? NO_TASKS,
        });
      }
      if (mounted.current && readId === latestRead.current) setLoading(false);
    });
  }, []);

  useEffect(load, [load]);

  // The account changed: the kept rows are gone, and the page reads for the new one.
  useEffect(
    () =>
      subscribeResource(ROADMAP_KEY, (event) => {
        if (event !== "cleared") return;
        setSyncError(null);
        setFailedTicks(new Set());
        setTickConflicts(new Map());
        load();
      }),
    [load],
  );

  const roadmap = useMemo(() => {
    if (!profile || read === NO_DEFINITION_READ) return null;
    const done = tasks.filter((t) => t.status === "completed").map((t) => t.material_key);
    return buildRoadmap(profile, done, undefined, read.definition ?? undefined);
  }, [profile, tasks, read]);

  useEffect(() => {
    if (!profile || !roadmap || read.definition === null) return;
    const payload = toReplacePayload(read.definition, roadmap, tasks);
    if (payload === null || alreadyStored(payload, tasks)) return;
    const key = JSON.stringify(payload);
    // Claimed before the request, for the account rather than the page: the write re-renders this
    // effect, and the overview and the roadmap both run it, so a second identical write would add a
    // second round of audit events for one change.
    const claims = ledger();
    if (claims.lastWritten === key) return;
    claims.lastWritten = key;
    // The answer is applied even if this effect has re-run meanwhile: the rows it brings back are the
    // server's, and without their ids no box can be ticked. Only an unmounted page ignores it.
    const ticket = beginRead(ROADMAP_KEY);
    replaceRoadmapTasks(payload)
      .then(async () => {
        const book = ledger();
        const revision = book.revision;
        const served = await fetchRoadmapDefinition();
        if (!sameAccount(ticket)) return;
        const shown = peekRoadmap();
        if (shown) storeRoadmap({ read: shown.read, tasks: mergeTaskSnapshot(shown.tasks, toTaskRows(served.tasks), heldRows(book, revision)) });
        if (mounted.current) setSyncError(null);
      })
      .catch((error: unknown) => {
        if (claims.lastWritten === key) claims.lastWritten = null;
        if (!mounted.current) return;
        setSyncError(
          `路线图没有保存到服务器，勾选可能不会生效（${error instanceof Error ? error.message : "未知错误"}）。`,
        );
      });
  }, [profile, roadmap, read.definition, tasks]);

  const taskIdFor = useCallback(
    (materialKey: string) => tasks.find((t) => t.material_key === materialKey && t.program_id === "")?.id ?? null,
    [tasks],
  );

  const tick = useCallback(
    async (materialKey: string, done: boolean) => {
      const row = tasks.find((t) => t.material_key === materialKey && t.program_id === "");
      const fail = () =>
        setFailedTicks((prev) => new Set(prev).add(materialKey));
      if (!row) {
        fail();
        return;
      }
      const status = done ? "completed" : "pending";
      setFailedTicks((prev) => {
        if (!prev.has(materialKey)) return prev;
        const next = new Set(prev);
        next.delete(materialKey);
        return next;
      });
      setTickConflicts((prev) => {
        if (!prev.has(materialKey)) return prev;
        const next = new Map(prev);
        next.delete(materialKey);
        return next;
      });
      const book = ledger();
      changeTasks((prev) => prev.map((t) => (t.id === row.id ? { ...t, status } : t)));

      const pending = book.writes.get(row.id);
      if (pending) {
        pending.desired = status;
        return;
      }

      // One write per task at a time. While it runs, the checkbox keeps the latest user choice.
      const write: TickWrite = { desired: status, confirmed: row };
      book.writes.set(row.id, write);
      let attempted: string;
      let failed: boolean;
      let restate: boolean;
      let staleRounds = 0;
      let conflict: TickConflict | null;
      do {
        attempted = write.desired;
        failed = false;
        restate = false;
        conflict = null;
        try {
          // Each edit states the version of the last confirmed row, so a row another device changed
          // in the meantime is refused instead of overwritten.
          const served = await patchRoadmapTask(row.id, {
            status: attempted,
            baseVersion: write.confirmed.version,
          });
          [write.confirmed] = toTaskRows([served]);
        } catch (error) {
          if (error instanceof StaleVersionError) {
            // The server's row is the confirmed state from here on, whatever happens to this tick.
            const base = write.confirmed.status;
            [write.confirmed] = toTaskRows([error.current as ServedTask]);
            const action = resolveStaleField(base, attempted, write.confirmed.status);
            if (action === "retry") {
              if (++staleRounds <= STALE_RETRIES) restate = true;
              else failed = true;
            } else if (action === "ask") {
              conflict = { mine: attempted, theirs: write.confirmed.status };
            }
          } else {
            failed = true;
          }
        }
        // If another choice arrived, persist it before publishing a response or a rollback.
      } while (write.desired !== attempted || restate);

      book.confirmedAt.set(row.id, ++book.revision);
      book.writes.delete(row.id);
      // The account changed while the save was in flight: its rows are not this account's.
      if (book !== ledger()) return;
      // The confirmed row goes into the kept rows even when the page that ticked it is gone, so the
      // page the applicant went to shows what the server holds.
      changeTasks((prev) => prev.map((t) => (t.id === row.id ? write.confirmed : t)));
      if (!mounted.current) return;
      if (conflict) {
        const found = conflict;
        setTickConflicts((prev) => new Map(prev).set(materialKey, found));
      } else if (failed && write.confirmed.status !== attempted) fail();
    },
    [tasks],
  );

  const settleTick = useCallback(
    (materialKey: string, keepMine: boolean) => {
      const conflict = tickConflicts.get(materialKey);
      if (!conflict) return;
      // Keeping mine is the same tick again, now based on the row the refusal returned; taking the
      // server's needs no write, because the checkbox already shows it. Both clear the notice.
      if (keepMine) void tick(materialKey, conflict.mine === "completed");
      else {
        setTickConflicts((prev) => {
          const next = new Map(prev);
          next.delete(materialKey);
          return next;
        });
      }
    },
    [tick, tickConflicts],
  );

  return {
    roadmap,
    loading,
    notice: read.notice,
    syncError,
    failedTicks,
    tickConflicts,
    settleTick,
    taskIdFor,
    tick,
    reload: load,
  };
}
