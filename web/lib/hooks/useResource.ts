"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { INITIAL, settle, type LoadState, type Resource } from "./resource";

/** Read `load` on mount and on `reload()`. A read that lands after a newer one started is dropped. */
export function useResource<T>(load: () => Promise<T>): Resource<T> & { set: (data: T) => void } {
  const [state, setState] = useState<LoadState<T>>(INITIAL);
  const stateRef = useRef(state);
  stateRef.current = state;
  const loadRef = useRef(load);
  loadRef.current = load;
  const latest = useRef(0);

  const reload = useCallback(() => {
    const run = ++latest.current;
    setState((prev) => ({ ...prev, loading: true }));
    void settle(() => loadRef.current(), stateRef.current).then((next) => {
      if (run === latest.current) setState(next);
    });
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  // A write whose answer the page already holds replaces the data without a second read.
  const set = useCallback((data: T) => {
    latest.current++;
    setState({ data, error: null, loading: false });
  }, []);

  return { ...state, reload, set };
}
