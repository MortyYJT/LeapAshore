"use client";

import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { programQueryString } from "@/lib/api";
import { loadApplicationRecords, type ApplicationRecord } from "@/lib/application-records";
import { beijingToday } from "@/lib/deadlines";
import { demoRecords, loadDemoPrograms, type DemoProgram, type DemoQuery } from "@/lib/demo";
import { useResource } from "@/lib/hooks/useResource";
import { demoMaterialRecords } from "@/lib/materials-map";

/**
 * The applicant's application records, read once for the whole shell.
 *
 * The rail lists the applications on every route and the overview and 我的申请 show the same
 * records, so they share one read: a change saved on one of them is what the rail shows next.
 * Nothing of an account's is read for a visitor who is not signed in. In login mode that visitor gets
 * `demo` instead: a few catalogue programs drawn as applications (lib/demo.ts), read from the public
 * catalogue and kept apart from `data`, so nothing that works on real records ever sees them.
 *
 * The provider outlives every page, so it reads again whenever the records may have changed without
 * it: on each route change (the portfolio and the advisor write the same rows), and when the tab is
 * shown again (another device may have). A page that writes those rows itself calls `reload`.
 */
export interface ApplicationRecordsState {
  /** Null until the first read lands, and for a visitor who is not signed in. */
  data: ApplicationRecord[] | null;
  error: string | null;
  loading: boolean;
  /** When the records on screen were last read from or written to the server. */
  syncedAt: Date | null;
  reload: () => void;
  /** Replace the records with what a write just returned, without a second read. */
  set: (data: ApplicationRecord[]) => void;
  /**
   * Change the records on screen from what they are now (a record being added, or the server's answer
   * for it). Does nothing, and returns false, while nothing has been read yet. Like `set`, it drops a
   * read already on its way, which may have started before the write.
   */
  change: (edit: (records: ApplicationRecord[]) => ApplicationRecord[]) => boolean;
  /**
   * For a signed-out visitor in login mode: catalogue programs as sample records, or null when the
   * catalogue gave too few or could not be read. Always null for anyone else.
   */
  demo: ApplicationRecord[] | null;
  /** The visitor will get a demo or its absence in a moment; nothing is known yet. */
  demoPending: boolean;
  /**
   * For the same visitor, the materials map's sample records: the listed programs whose page has been
   * read for materials, with what the catalogue serves and nothing ticked. Null when too few have been.
   */
  demoMaterials: ApplicationRecord[] | null;
  /** The application picked in the rail; the other lines step back while one is picked. */
  selected: string | null;
  select: (id: string | null) => void;
  /** The application the advisor just wrote to, by record id or catalogue program; the overview flashes its row once. */
  changedProgram: string | null;
  markChanged: (key: string | null) => void;
}

const Ctx = createContext<ApplicationRecordsState | null>(null);

/** A catalogue read that has not answered by now counts as failed, so the page is never left waiting on it. */
const DEMO_READ_TIMEOUT = 20000;

/** One read of the public catalogue, which answers without a session. */
async function readPrograms(query: DemoQuery): Promise<DemoProgram[]> {
  const response = await fetch(`/api/programs${programQueryString(query)}`, {
    credentials: "same-origin",
    signal: AbortSignal.timeout(DEMO_READ_TIMEOUT),
  });
  if (!response.ok) throw new Error(`读取项目目录失败：${response.status}`);
  const programs = (await response.json()) as DemoProgram[];
  if (!Array.isArray(programs)) throw new Error("读取项目目录失败：响应不是项目列表");
  return programs;
}

export function ApplicationRecordsProvider({ children }: { children: ReactNode }) {
  const { ready, gated } = useAuth();
  const pathname = usePathname();
  const signedIn = ready && !gated;
  const signedOut = ready && gated;
  const signedInRef = useRef(signedIn);
  signedInRef.current = signedIn;
  const resource = useResource<ApplicationRecord[] | null>(
    useCallback(async () => (signedInRef.current ? loadApplicationRecords() : null), []),
  );
  const { reload, set } = resource;
  const latest = useRef(resource.data);
  latest.current = resource.data;
  const change = useCallback(
    (edit: (records: ApplicationRecord[]) => ApplicationRecord[]) => {
      if (!signedInRef.current || !latest.current) return false;
      const next = edit(latest.current);
      latest.current = next;
      set(next);
      return true;
    },
    [set],
  );
  const [syncedAt, setSyncedAt] = useState<Date | null>(null);
  const [selected, select] = useState<string | null>(null);
  const [changedProgram, markChanged] = useState<string | null>(null);

  // The first read runs before the session is known and reads nothing; read again once it is, and
  // on every route change after that.
  useEffect(() => {
    reload();
  }, [signedIn, pathname, reload]);

  useEffect(() => {
    const shown = () => {
      if (document.visibilityState === "visible") reload();
    };
    document.addEventListener("visibilitychange", shown);
    return () => document.removeEventListener("visibilitychange", shown);
  }, [reload]);

  useEffect(() => {
    if (resource.data && !resource.loading && !resource.error) setSyncedAt(new Date());
  }, [resource.data, resource.loading, resource.error]);

  // The demo's programs are read once per visit; which of them are drawn is decided against today.
  const [demoPrograms, setDemoPrograms] = useState<DemoProgram[] | "failed" | null>(null);
  useEffect(() => {
    if (!signedOut) return setDemoPrograms(null);
    let current = true;
    loadDemoPrograms(beijingToday(), readPrograms).then(
      (programs) => current && setDemoPrograms(programs),
      () => current && setDemoPrograms("failed"),
    );
    return () => {
      current = false;
    };
  }, [signedOut]);
  const today = beijingToday();
  const demo = useMemo(
    () => (signedOut && Array.isArray(demoPrograms) ? demoRecords(demoPrograms, today) : null),
    [signedOut, demoPrograms, today],
  );
  const demoPending = signedOut && demoPrograms === null;
  // Drawn from the overview's demo programs when enough of those have collected materials, so the
  // rail's list and the map show the same lines; otherwise from any of the listed programs.
  const demoMaterials = useMemo(() => {
    if (!signedOut || !Array.isArray(demoPrograms)) return null;
    const drawn = new Set((demo ?? []).map((record) => record.programId));
    return demoMaterialRecords(demoPrograms.filter((program) => drawn.has(program.slug))) ?? demoMaterialRecords(demoPrograms);
  }, [signedOut, demoPrograms, demo]);

  // A picked application that is gone (removed, or another account) is no longer picked.
  const shown = signedIn ? resource.data : [...(demo ?? []), ...(demoMaterials ?? [])];
  const picked = selected && shown?.some((record) => record.id === selected) ? selected : null;

  const value = useMemo<ApplicationRecordsState>(
    () => ({
      data: signedIn ? resource.data : null,
      error: signedIn ? resource.error : null,
      // Signed in with nothing read yet is still loading, whatever the first empty read said.
      loading: signedIn && (resource.loading || (resource.data === null && !resource.error)),
      syncedAt: signedIn ? syncedAt : null,
      reload,
      set,
      change,
      demo,
      demoPending,
      demoMaterials,
      selected: picked,
      select,
      changedProgram,
      markChanged,
    }),
    [signedIn, resource.data, resource.error, resource.loading, syncedAt, reload, set, change, demo, demoPending, demoMaterials, picked, changedProgram],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApplicationRecords(): ApplicationRecordsState {
  const value = useContext(Ctx);
  if (!value) throw new Error("useApplicationRecords needs ApplicationRecordsProvider above it");
  return value;
}
