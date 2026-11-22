"use client";

import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { useApplicationRecords } from "@/components/shell/ApplicationRecords";
import { confirmAdvisorAction, sendAdvisorMessage, stopAdvisorTurn, targetKey, type AdvisorEvent } from "@/lib/advisor";
import {
  applyEvent,
  beginAnswer,
  failTurn,
  finishTurn,
  newTurn,
  restore,
  serialize,
  stopTurn,
  STORAGE_KEY,
  voidPending,
  type Turn,
} from "@/lib/advisor-run";
import { useNavigation } from "@/components/shell/Navigation";

/**
 * The advisor's conversation and its dock, held above the pages.
 *
 * One conversation lives here for as long as the tab does, so it is the same in the dock on every
 * route and on the full page at /advisor, and moving between routes does not interrupt a turn. The
 * transcript is also kept in the browser, so a reload draws it again; the server keeps the thread
 * itself (`api/app/agent/checkpoint.py`) under the same conversation id, so the next message carries
 * on from it and a change that was waiting can still be answered.
 */

/** Where the dock's open state is kept. The script in `DockScript` reads the same key before first paint. */
export const DOCK_KEY = "leapashore:advisor-dock";
/** From this width the dock sits beside the workspace; below it the advisor is the 顾问 tab's own screen. */
export const DOCK_QUERY = "(min-width: 901px)";
const NETWORK_FAILED = "连接断了，这一轮的回答没有收完。";
const MAX_DRAFT = 2000;

interface DockState {
  open: boolean;
  setOpen: (open: boolean) => void;
  /** Put a question in the composer without sending it: in the dock where there is one, else on /advisor. */
  ask: (question: string) => void;
  /** Whether a turn is running, for the shell's toggle. */
  running: boolean;
  /** Changes each time the composer should take the focus. */
  focusRequest: number;
}

interface ChatState {
  turns: Turn[];
  draft: string;
  setDraft: (draft: string) => void;
  /** The id of the turn whose stream is open, or null. */
  runningTurn: string | null;
  send: (text: string) => Promise<void>;
  answer: (turnId: string, confirmId: string | undefined, approved: boolean) => Promise<void>;
  stop: () => void;
  /** Ask the last question again. */
  retry: () => void;
  /** Start a new conversation. A turn that is running is stopped first. */
  reset: () => void;
}

const DockCtx = createContext<DockState | null>(null);
const ChatCtx = createContext<ChatState | null>(null);

const uid = () => Math.random().toString(36).slice(2, 12);

function readDock(): boolean {
  return document.documentElement.dataset.dock === "open";
}

export function AdvisorProvider({ children }: { children: ReactNode }) {
  const { state, ready, gated, requireLogin, refresh } = useAuth();
  const { reload: reloadRecords, markChanged } = useApplicationRecords();
  const { push } = useNavigation();
  const pathname = usePathname() ?? "/";

  const [open, setOpenState] = useState(false);
  const [focusRequest, setFocusRequest] = useState(0);
  const [conversationId, setConversationId] = useState(uid);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraftState] = useState("");
  const [runningTurn, setRunningTurn] = useState<string | null>(null);

  const conversation = useRef(conversationId);
  conversation.current = conversationId;
  const turnsRef = useRef(turns);
  turnsRef.current = turns;
  /** True from the moment a send or an answer is accepted until its stream has ended. */
  const busy = useRef(false);
  const run = useRef<{ turnId: string; controller: AbortController; stopped: boolean } | null>(null);

  // ---------- the dock ----------

  useEffect(() => {
    // The script in the document head decided this before first paint; take its answer.
    setOpenState(readDock());
  }, []);

  const setOpen = useCallback((next: boolean) => {
    setOpenState(next);
    const root = document.documentElement;
    root.dataset.dock = next ? "open" : "closed";
    // Only a change the applicant made is animated; the first paint is not.
    root.dataset.dockMoved = "true";
    try {
      localStorage.setItem(DOCK_KEY, next ? "open" : "closed");
    } catch {}
    if (next) setFocusRequest((n) => n + 1);
  }, []);

  const setDraft = useCallback((next: string) => setDraftState(next.slice(0, MAX_DRAFT)), []);

  const ask = useCallback(
    (question: string) => {
      setDraft(question);
      if (window.matchMedia(DOCK_QUERY).matches && pathname !== "/advisor") setOpen(true);
      else if (pathname !== "/advisor") push("/advisor");
      setFocusRequest((n) => n + 1);
    },
    [pathname, push, setDraft, setOpen],
  );

  // ⌘/Ctrl J opens and closes the advisor; Esc stops a turn that is running.
  const stopRef = useRef<() => void>(() => undefined);
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && event.key.toLowerCase() === "j") {
        event.preventDefault();
        if (pathname === "/advisor") setFocusRequest((n) => n + 1);
        else if (window.matchMedia(DOCK_QUERY).matches) {
          const closing = readDock();
          // Focus inside a dock that is closing would be left on nothing: it goes back to the switch.
          if (closing && document.getElementById("advisor-dock")?.contains(document.activeElement)) {
            document.getElementById("advisor-toggle")?.focus();
          }
          setOpen(!closing);
        } else push("/advisor");
        return;
      }
      // Esc belongs to whatever is open on top first: an input method's candidates, a dialog, the account menu.
      if (event.key !== "Escape" || event.defaultPrevented || event.isComposing || event.keyCode === 229 || !run.current) return;
      if (document.querySelector('dialog[open], .uc-menu[data-open="true"]')) return;
      event.preventDefault();
      stopRef.current();
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [pathname, push, setOpen]);

  // ---------- keeping the conversation ----------

  const owner = state?.account?.email ?? "";
  /** The owner the stored conversation was last read for; null before the session is known. */
  const settledFor = useRef<string | null>(null);
  /** Whose conversation is on screen while nobody is signed in (a session that ran out). */
  const leftBy = useRef<string | null>(null);
  const GATED = "\u0000signed-out";

  useEffect(() => {
    // Without an answer from /api/auth/me nothing is known about whose browser this is: the stored
    // conversation is neither shown nor replaced.
    if (!ready || !state) return;
    const previous = settledFor.current;
    if (gated) {
      // Signed out: the transcript is the account's, so it leaves this browser with the session.
      try {
        localStorage.removeItem(STORAGE_KEY);
      } catch {}
      // A session that ran out mid-conversation keeps what is on screen, so the applicant can read why
      // the last message was refused; a sign-out, or any other way of ending up signed out, clears it.
      const last = turnsRef.current.at(-1)?.blocks.at(-1);
      const expired = last?.type === "error" && last.code === "unauthorized";
      if (previous !== null && previous !== GATED) {
        leftBy.current = expired ? previous : null;
        if (!busy.current && !expired) {
          setTurns([]);
          setConversationId(uid());
        }
      }
      settledFor.current = GATED;
      return;
    }
    if (previous === owner) return;
    settledFor.current = owner;
    if (previous === GATED && leftBy.current !== null && leftBy.current !== owner) {
      // Somebody else signed in after a session ran out: what the last account left on screen goes,
      // except a message this account is sending right now.
      setTurns((turns) => turns.filter((turn) => turn.state === "running"));
      if (!busy.current) setConversationId(uid());
    }
    leftBy.current = null;
    if (previous === null) {
      let raw: string | null = null;
      try {
        raw = localStorage.getItem(STORAGE_KEY);
      } catch {}
      const back = restore(raw, owner);
      if (back && !busy.current && !turnsRef.current.length) {
        setConversationId(back.conversationId);
        setTurns(back.turns);
      }
    } else if (previous !== GATED && !busy.current) {
      // Another account in the same tab: its conversation is not this one.
      setTurns([]);
      setConversationId(uid());
    }
  }, [ready, state, gated, owner]);

  // Written a moment after the last change rather than on every token of a streaming reply.
  useEffect(() => {
    if (settledFor.current === null || settledFor.current === GATED) return;
    const write = () => {
      try {
        if (turnsRef.current.length) localStorage.setItem(STORAGE_KEY, serialize(owner, conversation.current, turnsRef.current));
        // An empty conversation removes this account's stored one, never another account's.
        else if (restore(localStorage.getItem(STORAGE_KEY), owner)) localStorage.removeItem(STORAGE_KEY);
      } catch {}
    };
    const timer = window.setTimeout(write, 400);
    window.addEventListener("pagehide", write);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("pagehide", write);
    };
  }, [turns, conversationId, owner]);

  // ---------- turns ----------

  const patch = useCallback((turnId: string, change: (turn: Turn) => Turn) => {
    setTurns((previous) => previous.map((turn) => (turn.id === turnId ? change(turn) : turn)));
  }, []);

  /** Run one stream into a turn, from its first event to its end. */
  const follow = useCallback(
    async (
      turnId: string,
      start: (onEvent: (event: AdvisorEvent) => void, signal: AbortSignal) => Promise<string>,
      /** The application each waiting step would change, by step id, for a stream that answers one. */
      targets = new Map<string, string | undefined>(),
    ) => {
      const current = { turnId, controller: new AbortController(), stopped: false };
      run.current = current;
      setRunningTurn(turnId);
      // Undefined until a step of this stream has written; then the application it wrote to, if it named one.
      let wrote: string | null | undefined;
      let answered = false;
      try {
        const outcome = await start((event) => {
          if (current.stopped || event.type === "done") return;
          // A step that wrote: the records the rail and the overview show are stale now.
          if (event.type === "confirm" && event.stepId) targets.set(event.stepId, targetKey(event.target));
          if (event.type === "step" && event.write && event.status === "done") {
            wrote = targets.get(event.id.replace(/:write$/, "")) ?? wrote ?? null;
          }
          // A confirmed write that ended any other way (refused because the record moved elsewhere,
          // or found already stored): what is on screen may be old either way.
          if (event.type === "step" && event.status !== "running" && event.id.endsWith(":write")) answered = true;
          patch(turnId, (turn) => applyEvent(turn, event));
        }, current.controller.signal);
        if (outcome === "unauthorized") void refresh();
        if (!current.stopped) patch(turnId, finishTurn);
      } catch {
        if (!current.stopped) patch(turnId, (turn) => failTurn(turn, NETWORK_FAILED));
      } finally {
        if (run.current === current) run.current = null;
        busy.current = false;
        setRunningTurn((id) => (id === turnId ? null : id));
        if (wrote !== undefined || answered) reloadRecords();
        if (wrote) markChanged(wrote);
      }
    },
    [patch, refresh, reloadRecords, markChanged],
  );

  /**
   * Send `text`. In login mode a signed-out visitor gets the login dialog first; the sentence stays in
   * the composer while it is open and is sent as typed once the dialog finishes (openspec account-login D11).
   */
  const send = useCallback(
    async (text: string) => {
      const content = text.trim();
      if (!content || busy.current) return;
      busy.current = true;
      if (!(await requireLogin().catch(() => false))) {
        busy.current = false;
        return;
      }
      const turn = newTurn(uid(), content);
      // A change left unanswered is closed by the new message, here as on the server.
      setTurns((previous) => [...previous.map(voidPending), turn]);
      setDraftState("");
      const id = conversation.current;
      await follow(turn.id, (onEvent, signal) => sendAdvisorMessage(id, content, onEvent, signal));
    },
    [follow, requireLogin],
  );

  const answer = useCallback(
    async (turnId: string, confirmId: string | undefined, approved: boolean) => {
      if (busy.current) return;
      busy.current = true;
      if (!(await requireLogin().catch(() => false))) {
        busy.current = false;
        return;
      }
      const turn = turnsRef.current.find((item) => item.id === turnId);
      const card = turn?.blocks.find((block) => block.type === "confirm" && block.id === confirmId);
      patch(turnId, (item) => beginAnswer(item, confirmId, approved));
      const id = conversation.current;
      // The write of this stream belongs to the card that was just answered.
      const targets = new Map<string, string | undefined>();
      if (card?.type === "confirm" && card.stepId) targets.set(card.stepId, targetKey(card.target));
      await follow(turnId, (onEvent, signal) => confirmAdvisorAction(id, approved, onEvent, confirmId, signal), targets);
    },
    [follow, patch, requireLogin],
  );

  const stop = useCallback(() => {
    const current = run.current;
    if (!current || current.stopped) return;
    const turn = turnsRef.current.find((item) => item.id === current.turnId);
    // An answer on its way is a write in flight: it is over in a moment and is not cut off half-way.
    if (turn?.blocks.some((block) => block.type === "confirm" && block.answer !== undefined)) return;
    current.stopped = true;
    stopAdvisorTurn(conversation.current);
    current.controller.abort();
    patch(current.turnId, stopTurn);
  }, [patch]);

  stopRef.current = stop;

  const retry = useCallback(() => {
    const last = turnsRef.current.at(-1);
    if (last && !busy.current) void send(last.question);
  }, [send]);

  const reset = useCallback(() => {
    stop();
    setTurns([]);
    setConversationId(uid());
    setDraftState("");
    setFocusRequest((n) => n + 1);
  }, [stop]);

  const dock = useMemo<DockState>(
    () => ({ open, setOpen, ask, running: runningTurn !== null, focusRequest }),
    [open, setOpen, ask, runningTurn, focusRequest],
  );
  const chat = useMemo<ChatState>(
    () => ({ turns, draft, setDraft, runningTurn, send, answer, stop, retry, reset }),
    [turns, draft, setDraft, runningTurn, send, answer, stop, retry, reset],
  );

  return (
    <DockCtx.Provider value={dock}>
      <ChatCtx.Provider value={chat}>{children}</ChatCtx.Provider>
    </DockCtx.Provider>
  );
}

export function useAdvisorDock(): DockState {
  const value = useContext(DockCtx);
  if (!value) throw new Error("useAdvisorDock needs AdvisorProvider above it");
  return value;
}

export function useAdvisorChat(): ChatState {
  const value = useContext(ChatCtx);
  if (!value) throw new Error("useAdvisorChat needs AdvisorProvider above it");
  return value;
}

// Decides before first paint whether the dock is open, so the workspace does not jump once the app
// has loaded: the applicant's last choice, or open on a screen wide enough for three panes.
const DOCK_SOURCE = `(function(){try{var v=localStorage.getItem(${JSON.stringify(DOCK_KEY)});document.documentElement.dataset.dock=(v?v==="open":innerWidth>=1440)?"open":"closed"}catch(e){}})()`;

/** See `ThemeScript` for why the type differs between the server and the browser. */
export function DockScript() {
  return (
    <script
      suppressHydrationWarning
      type={typeof window === "undefined" ? undefined : "application/json"}
      dangerouslySetInnerHTML={{ __html: DOCK_SOURCE }}
    />
  );
}
