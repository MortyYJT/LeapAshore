"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fetchRoadmapDefinition, patchRoadmapTask, replaceRoadmapTasks } from "../api";
import { buildRoadmap } from "../roadmap";
import { NO_DEFINITION_READ, readRoadmapDefinition, type DefinitionRead } from "../roadmap-definition";
import { toTaskRows } from "../roadmap-source";
import { alreadyStored, toReplacePayload, type TaskRow } from "../roadmap-sync";
import type { Profile, Roadmap } from "../types";

interface TickWrite {
  desired: string;
  confirmed: TaskRow;
}

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
  const [read, setRead] = useState<DefinitionRead>(NO_DEFINITION_READ);
  const [loading, setLoading] = useState(true);
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [failedTicks, setFailedTicks] = useState<Set<string>>(new Set());
  const lastWritten = useRef<string | null>(null);
  const mounted = useRef(true);
  const writes = useRef(new Map<string, TickWrite>());
  const taskRevision = useRef(0);
  const updatedAt = useRef(new Map<string, number>());
  const latestRead = useRef(0);

  const applySnapshot = useCallback((snapshot: TaskRow[], revision: number) => {
    const protectedIds = new Set(writes.current.keys());
    for (const [id, updated] of updatedAt.current) {
      if (updated > revision) protectedIds.add(id);
    }
    setTasks((previous) => {
      const protectedRows = new Map(previous.filter((row) => protectedIds.has(row.id)).map((row) => [row.id, row]));
      const next = snapshot.map((row) => {
        const current = protectedRows.get(row.id);
        protectedRows.delete(row.id);
        return current ?? row;
      });
      return [...next, ...protectedRows.values()];
    });
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(() => {
    const readId = ++latestRead.current;
    const revision = taskRevision.current;
    setLoading(true);
    void readRoadmapDefinition(fetchRoadmapDefinition).then((next) => {
      if (!mounted.current || readId !== latestRead.current) return;
      setRead(next);
      if (next.tasks !== null) applySnapshot(next.tasks, revision);
      setLoading(false);
    });
  }, [applySnapshot]);

  useEffect(load, [load]);

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
    // Claimed before the request: the write re-renders this effect, and a second identical write would
    // add a second round of audit events for one change.
    if (lastWritten.current === key) return;
    lastWritten.current = key;
    // The answer is applied even if this effect has re-run meanwhile: the rows it brings back are the
    // server's, and without their ids no box can be ticked. Only an unmounted page ignores it.
    replaceRoadmapTasks(payload)
      .then(async () => {
        const revision = taskRevision.current;
        const served = await fetchRoadmapDefinition();
        if (!mounted.current) return;
        setSyncError(null);
        applySnapshot(toTaskRows(served.tasks), revision);
      })
      .catch((error: unknown) => {
        lastWritten.current = null;
        if (!mounted.current) return;
        setSyncError(
          `路线图没有保存到服务器，勾选可能不会生效（${error instanceof Error ? error.message : "未知错误"}）。`,
        );
      });
  }, [profile, roadmap, read.definition, tasks, applySnapshot]);

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
      setTasks((prev) => prev.map((t) => (t.id === row.id ? { ...t, status } : t)));

      const pending = writes.current.get(row.id);
      if (pending) {
        pending.desired = status;
        return;
      }

      // One write per task at a time. While it runs, the checkbox keeps the latest user choice.
      const write: TickWrite = { desired: status, confirmed: row };
      writes.current.set(row.id, write);
      let attempted: string;
      let failed: boolean;
      do {
        attempted = write.desired;
        failed = false;
        try {
          const served = await patchRoadmapTask(row.id, { status: attempted });
          [write.confirmed] = toTaskRows([served]);
        } catch {
          failed = true;
        }
        // If another choice arrived, persist it before publishing a response or a rollback.
      } while (write.desired !== attempted);

      updatedAt.current.set(row.id, ++taskRevision.current);
      writes.current.delete(row.id);
      if (!mounted.current) return;
      setTasks((prev) => prev.map((t) => (t.id === row.id ? write.confirmed : t)));
      if (failed && write.confirmed.status !== attempted) fail();
    },
    [tasks],
  );

  return {
    roadmap,
    loading,
    notice: read.notice,
    syncError,
    failedTicks,
    taskIdFor,
    tick,
    reload: load,
  };
}
