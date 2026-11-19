"use client";

import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { loadApplicationRecords, type ApplicationRecord } from "@/lib/application-records";
import { useResource } from "@/lib/hooks/useResource";

/**
 * The applicant's application records, read once for the whole shell.
 *
 * The rail lists the applications on every route and the overview and 我的申请 show the same
 * records, so they share one read: a change saved on one of them is what the rail shows next.
 * Nothing is read for a visitor who is not signed in.
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
  /** The application picked in the rail; the other lines step back while one is picked. */
  selected: string | null;
  select: (id: string | null) => void;
  /** The catalogue program the advisor just wrote to; the overview flashes its row once. */
  changedProgram: string | null;
  markChanged: (programId: string | null) => void;
}

const Ctx = createContext<ApplicationRecordsState | null>(null);

export function ApplicationRecordsProvider({ children }: { children: ReactNode }) {
  const { ready, gated } = useAuth();
  const pathname = usePathname();
  const signedIn = ready && !gated;
  const signedInRef = useRef(signedIn);
  signedInRef.current = signedIn;
  const resource = useResource<ApplicationRecord[] | null>(
    useCallback(async () => (signedInRef.current ? loadApplicationRecords() : null), []),
  );
  const { reload, set } = resource;
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

  // A picked application that is gone (removed, or another account) is no longer picked.
  const picked = selected && resource.data?.some((record) => record.id === selected) ? selected : null;

  const value = useMemo<ApplicationRecordsState>(
    () => ({
      data: signedIn ? resource.data : null,
      error: signedIn ? resource.error : null,
      // Signed in with nothing read yet is still loading, whatever the first empty read said.
      loading: signedIn && (resource.loading || (resource.data === null && !resource.error)),
      syncedAt: signedIn ? syncedAt : null,
      reload,
      set,
      selected: picked,
      select,
      changedProgram,
      markChanged,
    }),
    [signedIn, resource.data, resource.error, resource.loading, syncedAt, reload, set, picked, changedProgram],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApplicationRecords(): ApplicationRecordsState {
  const value = useContext(Ctx);
  if (!value) throw new Error("useApplicationRecords needs ApplicationRecordsProvider above it");
  return value;
}
