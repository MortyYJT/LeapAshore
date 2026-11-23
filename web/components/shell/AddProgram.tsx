"use client";

import Link from "next/link";
import {
  type MouseEvent,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import {
  deadlineNote,
  addState,
  bandFor,
  catalogueRecordId,
  provisionalRecord,
  recordHref,
  withRecord,
  withoutRecord,
} from "@/lib/add-program";
import {
  addCatalogueProgram,
  loadApplicationRecords,
  writeApplicationRecord,
  type ApplicationRecord,
} from "@/lib/application-records";
import { beijingToday } from "@/lib/deadlines";
import { loadProfile } from "@/lib/hooks/useProfile";
import { ENTER_MS } from "@/lib/motion";
import { peekResource } from "@/lib/resource-cache";
import { PROFILE_KEY } from "@/lib/resource-keys";
import { StaleVersionError } from "@/lib/sync-conflict";
import type { Profile, Program } from "@/lib/types";

import { useApplicationRecords } from "./ApplicationRecords";
import { Icon } from "./Icon";

/**
 * Adding a school-library program to 我的申请 in one step, from the school page's program rows and
 * the program page.
 *
 * One press adds it. The control reads as added at once and the record is drawn in the rail, the
 * overview and the roadmap before the server answers (`provisionalRecord`); the answer replaces it,
 * and a refusal takes it back out and says why. The server is idempotent by program, so a double
 * press, a retry or a second tab adds one record. A visitor who is not signed in gets the sign-in
 * dialog, and the add runs once they are in.
 *
 * The toast says what was added and which deadline it took, leads to the record (去看看, which lands on
 * 我的申请 scrolled to it and marked) and, for a record this press created, offers 撤销: a removal
 * based on the version just answered, so an edit made in the meantime is never thrown away unseen.
 */

type Toast =
  | { kind: "added"; record: ApplicationRecord; created: boolean; confirmed: boolean }
  | { kind: "failed"; program: Program; message: string }
  | { kind: "note"; message: string };

interface AddProgramState {
  /** Programs whose add is on its way, by slug. */
  adding: ReadonlySet<string>;
  add: (program: Program) => void;
  toast: (Toast & { key: number }) | null;
  dismiss: () => void;
  undo: () => void;
  undoing: boolean;
  /** The record 我的申请 should scroll to and mark next, set by 去看看. */
  arrival: string | null;
  arrive: (id: string | null) => void;
}

const Ctx = createContext<AddProgramState | null>(null);

/**
 * How long the toast stays when nothing holds it (the pointer or focus inside it holds it). Nothing
 * is only in the toast: the row and the program page turn into the link to the record (去看看), and
 * 我的申请 removes it (撤销), so a toast that has gone takes no way of doing either with it.
 */
const TOAST_MS = 8000;

/**
 * The control stays a plain 已加入 mark at least this long after the press, before it becomes the
 * link to the record: the second press of a double click lands on the mark and does nothing, instead
 * of opening 我的申请.
 */
const SETTLE_MS = 600;

function reasonOf(error: unknown): string {
  // A fetch that never reached the server throws a TypeError whose message is the browser's, in English.
  if (error instanceof TypeError) return "网络没有连上，请稍后再试。";
  return error instanceof Error && error.message ? error.message : "没能加入，请稍后再试。";
}

export function AddProgramProvider({ children }: { children: ReactNode }) {
  const { requireLogin, state } = useAuth();
  const records = useApplicationRecords();
  const { change, reload } = records;
  const [adding, setAdding] = useState<ReadonlySet<string>>(new Set());
  const addingRef = useRef(new Set<string>());
  const [toast, setToast] = useState<(Toast & { key: number }) | null>(null);
  const toastKey = useRef(0);
  const [undoing, setUndoing] = useState(false);
  const [arrival, arrive] = useState<string | null>(null);

  // Another account signed in (or this one signed out) in this tab: nothing of the last one's adds
  // stays on screen. Signing in from none is the add's own continuation, and keeps its toast.
  const account = state?.account?.email ?? null;
  const lastAccount = useRef(account);
  useEffect(() => {
    if (lastAccount.current !== null && lastAccount.current !== account) {
      setToast(null);
      arrive(null);
    }
    lastAccount.current = account;
  }, [account]);

  const show = useCallback((next: Toast | null) => {
    setToast(next && { ...next, key: ++toastKey.current });
    return toastKey.current;
  }, []);

  const mark = useCallback((slug: string, on: boolean) => {
    if (on) addingRef.current.add(slug);
    else addingRef.current.delete(slug);
    setAdding(new Set(addingRef.current));
  }, []);

  const add = useCallback(
    async (program: Program) => {
      const slug = program.slug;
      if (addingRef.current.has(slug)) return;
      // Signed out: the dialog first, and the add once they are in. Closing it adds nothing.
      if (!(await requireLogin()) || addingRef.current.has(slug)) return;
      mark(slug, true);
      const pressed = Date.now();
      let added = false;
      try {
        const provisional = provisionalRecord(program, beijingToday());
        let drawn = false;
        change((list) => {
          if (list.some((record) => record.programId === slug)) return list;
          drawn = true;
          return withRecord(list, provisional);
        });
        const key = show({ kind: "added", record: provisional, created: true, confirmed: false });
        try {
          const profile = peekResource<Profile>(PROFILE_KEY) ?? (await loadProfile().catch(() => null));
          const { record, created } = await addCatalogueProgram(slug, bandFor(profile, program));
          added = true;
          if (!change((list) => withRecord(list, record))) reload();
          setToast((current) => (current?.key === key ? { ...current, kind: "added", record, created, confirmed: true } : current));
        } catch (error) {
          // The add may have landed with its answer lost: read the records once, and if it is there,
          // it is added (without 撤销, since this press may not have been the one that made it).
          const held = await loadApplicationRecords()
            .then((list) => list.find((record) => record.programId === slug) ?? null)
            .catch(() => null);
          if (held) {
            added = true;
            if (!change((list) => withRecord(list, held))) reload();
            setToast((current) => (current?.key === key ? { ...current, kind: "added", record: held, created: false, confirmed: true } : current));
            return;
          }
          if (drawn) change((list) => withoutRecord(list, provisional.id));
          reload();
          show({ kind: "failed", program, message: reasonOf(error) });
        }
      } finally {
        // A failure frees the control at once, so 重试 works; an add holds it (see SETTLE_MS).
        const left = added ? SETTLE_MS - (Date.now() - pressed) : 0;
        if (left > 0) await new Promise((resolve) => setTimeout(resolve, left));
        mark(slug, false);
      }
    },
    [requireLogin, change, reload, show, mark],
  );

  const undo = useCallback(async () => {
    if (toast?.kind !== "added" || !toast.confirmed || !toast.created || undoing) return;
    const { record } = toast;
    setUndoing(true);
    try {
      await writeApplicationRecord(record.id, undefined, { baseVersion: record.version });
      change((list) => withoutRecord(list, record.id));
      show({ kind: "note", message: `已撤销，「${record.name}」已从我的申请移除。` });
    } catch (error) {
      reload();
      show({
        kind: "note",
        message: error instanceof StaleVersionError ? "这条申请刚在别处改过，没有撤销。去我的申请里看过再移除。" : reasonOf(error),
      });
    } finally {
      setUndoing(false);
    }
  }, [toast, undoing, change, reload, show]);

  const value = useMemo<AddProgramState>(
    () => ({
      adding,
      add: (program) => void add(program),
      toast,
      dismiss: () => setToast(null),
      undo: () => void undo(),
      undoing,
      arrival,
      arrive,
    }),
    [adding, add, toast, undo, undoing, arrival],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAddProgram(): AddProgramState {
  const value = useContext(Ctx);
  if (!value) throw new Error("useAddProgram needs AddProgramProvider above it");
  return value;
}

/** A plain click, which this tab follows; one that opens a new tab or window is not. */
function plainClick(event: MouseEvent<HTMLElement>): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

/**
 * The control for one program. `row`: the compact one in a program table's last column. `primary`:
 * the program page's main action. Added, it is a link to the record instead.
 */
export function AddProgramButton({ program, variant }: { program: Program; variant: "row" | "primary" }) {
  const { adding, add, arrive } = useAddProgram();
  const { data } = useApplicationRecords();
  const state = addState(data, adding, program.slug);
  const name = program.name ?? "这个项目";
  const id = data?.find((record) => record.programId === program.slug)?.id ?? catalogueRecordId(program.slug);
  const row = variant === "row";
  const look = row ? "btn-small" : "btn-secondary";
  const label = row ? "已加入" : "已加入我的申请";

  // The control changes element (a button, then the link) as the add goes through. Whether it held
  // the focus is read while the old element is still in the document, and the new one takes it, so
  // a keyboard press does not drop the focus to the top of the page.
  const slot = useRef<HTMLSpanElement>(null);
  const hadFocus = useRef(false);
  if (slot.current && typeof document !== "undefined") hadFocus.current = slot.current.contains(document.activeElement);
  useLayoutEffect(() => {
    if (hadFocus.current && slot.current && !slot.current.contains(document.activeElement)) {
      slot.current.querySelector<HTMLElement>("a, button")?.focus();
    }
  }, [state]);

  return (
    <span ref={slot} className="add-program-slot">
      {state === "add" ? (
        <button
          type="button"
          className={`btn ${row ? "btn-secondary btn-small" : "btn-primary"} add-program`}
          aria-label={row ? `加入申请：${name}` : undefined}
          onClick={() => add(program)}
        >
          <Icon name="plus" />
          {row ? "加入申请" : "加入我的申请"}
        </button>
      ) : state === "adding" ? (
        <button type="button" className={`btn ${look} add-program is-added`} aria-disabled="true">
          <Icon name="check" />
          {label}
        </button>
      ) : (
        <Link
          className={`btn ${look} add-program is-added`}
          href={recordHref(id)}
          aria-label={`已加入我的申请，查看 ${name}`}
          onClick={(event) => plainClick(event) && arrive(id)}
        >
          <Icon name="check" />
          {label}
        </Link>
      )}
    </span>
  );
}

/** The toast, drawn inside the shell so its link switches pages like every other link there. */
export function AddProgramToast() {
  const { toast, dismiss, undo, undoing, add, arrive } = useAddProgram();
  const box = useRef<HTMLDivElement>(null);
  const [held, setHeld] = useState(false);
  // Closing the toast or following its link removes it under the pointer, with no leave or blur to
  // say so; each message starts unheld.
  useEffect(() => setHeld(false), [toast?.key]);

  // Each new message rises into place once; Reduced Motion draws it in place.
  useLayoutEffect(() => {
    if (!toast || !box.current || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    box.current.animate([{ opacity: 0, translate: "0 8px" }, { opacity: 1, translate: "none" }], {
      duration: ENTER_MS,
      easing: "cubic-bezier(.16, 1, .3, 1)",
    });
  }, [toast?.key]); // eslint-disable-line react-hooks/exhaustive-deps

  // A message that offers no repair goes by itself; a failure stays until it is closed or retried.
  const lasting = toast?.kind === "failed" || (toast?.kind === "added" && !toast.confirmed);
  useEffect(() => {
    if (!toast || lasting || held) return;
    const timer = setTimeout(dismiss, TOAST_MS);
    return () => clearTimeout(timer);
  }, [toast, lasting, held, dismiss]);

  return (
    <div className="add-toast-region" role="status" aria-live="polite">
      {toast && (
        <div
          ref={box}
          key={toast.key}
          className={`add-toast${toast.kind === "failed" ? " is-failed" : ""}`}
          onPointerEnter={() => setHeld(true)}
          onPointerLeave={() => setHeld(false)}
          onFocus={() => setHeld(true)}
          onBlur={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setHeld(false);
          }}
        >
          <div className="add-toast-text">
            {toast.kind === "added" && (
              <>
                <strong>{toast.created ? "已加入我的申请" : "已经在我的申请里"}</strong>
                <span className="small add-toast-name">{toast.record.name}</span>
                <span className="small muted">{deadlineNote(toast.record)}</span>
              </>
            )}
            {toast.kind === "failed" && (
              <>
                <strong>没能加入我的申请</strong>
                <span className="small">{toast.message}</span>
              </>
            )}
            {toast.kind === "note" && <strong>{toast.message}</strong>}
          </div>
          <div className="add-toast-actions">
            {toast.kind === "added" && (
              <>
                {toast.created && (
                  <button type="button" className="btn btn-text btn-small" onClick={undo} disabled={!toast.confirmed || undoing}>
                    {undoing ? "撤销中…" : "撤销"}
                  </button>
                )}
                {toast.confirmed ? (
                  <Link
                    className="btn btn-secondary btn-small"
                    href={recordHref(toast.record.id)}
                    onClick={(event) => {
                      if (!plainClick(event)) return;
                      arrive(toast.record.id);
                      dismiss();
                    }}
                  >
                    去看看
                    <Icon name="arrow" />
                  </Link>
                ) : (
                  // The record is not saved yet: 我的申请 would show a row nothing can be written to.
                  <button type="button" className="btn btn-secondary btn-small" disabled>
                    去看看
                    <Icon name="arrow" />
                  </button>
                )}
              </>
            )}
            {toast.kind === "failed" && (
              <button type="button" className="btn btn-secondary btn-small" onClick={() => add(toast.program)}>
                <Icon name="retry" />
                重试
              </button>
            )}
            <button type="button" className="btn btn-text btn-small add-toast-close" aria-label="关闭提示" onClick={dismiss}>
              <Icon name="close" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
