"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { AUTH_CHANGED } from "../auth";
import { beginRead, peekResource, putResource, subscribeResource } from "../resource-cache";
import { INITIAL, SESSION_ENDED, initialState, readThrough, saysSignedOut, settle, type LoadState, type Resource } from "./resource";

/**
 * Read `load` on mount and on `reload()`. A read that lands after a newer one started is dropped.
 *
 * With a `key` the resource is kept for the visit (lib/resource-cache.ts): a page that mounts after
 * the first read draws the kept value at once, with no placeholder, and reads again behind it. What a
 * write returns goes in through `set`; a write whose answer is not known here calls
 * `invalidateResource(key)`, and every page showing the resource reads it again. When the account
 * changes the kept value is dropped and the page goes back to its placeholder.
 */
export function useResource<T>(load: () => Promise<T>, key?: string): Resource<T> & { set: (data: T) => void } {
  const [state, setState] = useState<LoadState<T>>(() => initialState<T>(key));
  const stateRef = useRef(state);
  stateRef.current = state;
  const loadRef = useRef(load);
  loadRef.current = load;
  const latest = useRef(0);

  const reload = useCallback(() => {
    const run = ++latest.current;
    setState((prev) => ({ ...prev, loading: true }));
    const read =
      key === undefined
        ? settle(() => loadRef.current(), stateRef.current)
        : readThrough(key, () => loadRef.current(), stateRef.current, beginRead(key));
    void read.then((next) => {
      // Data this account read earlier is now answered 401: the session ended without this tab being told.
      if (key !== undefined && next && next.data !== null && saysSignedOut(next.error)) window.dispatchEvent(new Event(SESSION_ENDED));
      if (next && run === latest.current) setState(next);
    });
  }, [key]);

  useEffect(() => {
    reload();
  }, [reload]);

  // Logging in or out changes whose data every read returns. A kept resource hears of it from the
  // cache instead ("cleared"), after its value has been dropped.
  useEffect(() => {
    if (key !== undefined) return;
    window.addEventListener(AUTH_CHANGED, reload);
    return () => window.removeEventListener(AUTH_CHANGED, reload);
  }, [key, reload]);

  useEffect(() => {
    if (key === undefined) return;
    return subscribeResource(key, (event) => {
      if (event === "cleared") {
        // Another account's data must not stay on screen while the new read is on its way.
        latest.current++;
        // The read below starts from nothing: if it fails, it must not fall back to the previous
        // account's data, which `stateRef` still holds until this update renders.
        stateRef.current = INITIAL;
        setState(INITIAL);
        reload();
      } else if (event === "invalidated") {
        reload();
      } else {
        // Stored by a write or by a read on another page showing the same resource.
        const data = peekResource<T>(key);
        if (data !== undefined && data !== stateRef.current.data) setState((prev) => ({ ...prev, data, error: null }));
      }
    });
  }, [key, reload]);

  // A write whose answer the page already holds replaces the data without a second read.
  const set = useCallback(
    (data: T) => {
      latest.current++;
      if (key !== undefined) putResource(key, data);
      setState({ data, error: null, loading: false });
    },
    [key],
  );

  return { ...state, reload, set };
}
