"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fetchRoadmapDefinition, patchRoadmapTask, replaceRoadmapTasks } from "../api";
import { buildRoadmap } from "../roadmap";
import { NO_DEFINITION_READ, readRoadmapDefinition, type DefinitionRead } from "../roadmap-definition";
import { toTaskRows } from "../roadmap-source";
import { alreadyStored, toReplacePayload, type TaskRow } from "../roadmap-sync";
import type { Profile, Roadmap } from "../types";

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
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    void readRoadmapDefinition(fetchRoadmapDefinition).then((next) => {
      setRead(next);
      if (next.tasks !== null) setTasks(next.tasks);
      setLoading(false);
    });
  }, []);

  useEffect(load, [load]);

  const roadmap = useMemo(() => {
    if (!profile) return null;
    const done = tasks.filter((t) => t.status === "completed").map((t) => t.material_key);
    return buildRoadmap(profile, done, undefined, read.definition ?? undefined);
  }, [profile, tasks, read.definition]);

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
        const served = await fetchRoadmapDefinition();
        if (!mounted.current) return;
        setSyncError(null);
        setTasks(toTaskRows(served.tasks));
      })
      .catch((error: unknown) => {
        lastWritten.current = null;
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
      const before = row.status;
      const status = done ? "completed" : "pending";
      setFailedTicks((prev) => {
        const next = new Set(prev);
        next.delete(materialKey);
        return next;
      });
      setTasks((prev) => prev.map((t) => (t.id === row.id ? { ...t, status } : t)));
      try {
        const served = await patchRoadmapTask(row.id, { status });
        const [saved] = toTaskRows([served]);
        setTasks((prev) => prev.map((t) => (t.id === row.id ? saved : t)));
      } catch {
        // The box goes back to what the server holds, and the row says the change was not saved.
        setTasks((prev) => prev.map((t) => (t.id === row.id ? { ...t, status: before } : t)));
        fail();
      }
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
