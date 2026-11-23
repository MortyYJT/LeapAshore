"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { beginRead, finishRead, peekResource, sameAccount, subscribeResource } from "../resource-cache";

interface ReadState<T> {
  key: string | null;
  data: T | null;
  error: string | null;
}

const starting = <T,>(key: string | null): ReadState<T> => ({ key, data: key === null ? null : peekResource<T>(key) ?? null, error: null });

/**
 * A read whose key changes while the page is mounted (a list by its filter, programs by field), kept
 * for the visit like `useResource`'s: a key read before is drawn at once and read again behind; a key
 * never read starts with no data. `key === null` means there is nothing to read yet. A failed read
 * keeps the data on screen and reports the error beside it.
 */
export function useCachedRead<T>(key: string | null, load: () => Promise<T>): { data: T | null; error: string | null; reload: () => void } {
  const [state, setState] = useState<ReadState<T>>(() => starting<T>(key));
  // A new key is answered from the cache during this render, not one render late.
  const shown = state.key === key ? state : starting<T>(key);
  if (shown !== state) setState(shown);
  const loadRef = useRef(load);
  loadRef.current = load;
  const latest = useRef(0);

  const reload = useCallback(() => {
    if (key === null) return;
    const run = ++latest.current;
    const ticket = beginRead(key);
    loadRef.current().then(
      (data) => {
        if (!sameAccount(ticket)) return;
        finishRead(ticket, data);
        if (run === latest.current) setState({ key, data: peekResource<T>(key) ?? data, error: null });
      },
      (error: unknown) => {
        if (run === latest.current && sameAccount(ticket)) {
          setState((previous) => ({ ...(previous.key === key ? previous : starting<T>(key)), error: error instanceof Error && error.message ? error.message : "读取失败，请稍后再试。" }));
        }
      },
    );
  }, [key]);

  useEffect(() => {
    reload();
    return () => {
      latest.current++;
    };
  }, [reload]);

  useEffect(() => {
    if (key === null) return;
    return subscribeResource(key, (event) => {
      if (event === "cleared") setState({ key, data: null, error: null });
      if (event !== "changed") reload();
    });
  }, [key, reload]);

  return { data: shown.data, error: shown.error, reload };
}
