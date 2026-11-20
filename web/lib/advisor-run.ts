/**
 * The advisor's transcript: what the stream's events add up to on screen.
 *
 * A turn is the applicant's message and the run that answers it. The run is a list of blocks in the
 * order they happened: the steps the agent took, the sources it was given, a change waiting for an
 * answer, the reply, an error. A confirm continues the turn it belongs to, so the proposal, the answer
 * and the write stay together. Everything here is pure, so the rules can be tested without a browser.
 */

import type { AdvisorEvent, Change, ChangeTarget, Citation, Detail, StepStatus } from "./advisor.ts";
import type { Overview } from "./overview.ts";

export interface StepBlock {
  type: "step";
  id: string;
  kind: string;
  name: string;
  title?: string;
  args?: Detail[];
  status: StepStatus;
  ms?: number;
  result?: string;
  items?: string[];
  write?: boolean;
}

export interface CitationsBlock {
  type: "citations";
  gate: "pass" | "refuse";
  citations: Citation[];
}

/**
 * `pending` waits for the applicant. `void` was never answered and was not made. `gone` is one the
 * server no longer holds: it was answered somewhere else or has expired, and this page cannot tell which.
 */
export type ConfirmState = "pending" | "approved" | "declined" | "void" | "gone";

export interface ConfirmBlock {
  type: "confirm";
  id?: string;
  stepId?: string;
  summary: string;
  target?: ChangeTarget;
  changes?: Change[];
  state: ConfirmState;
  /** The answer on its way to the server: the buttons are held until the outcome is known. */
  answer?: boolean;
}

export interface TextBlock {
  type: "text";
  text: string;
}

export interface ErrorBlock {
  type: "error";
  code?: string;
  message: string;
}

export type Block = StepBlock | CitationsBlock | ConfirmBlock | TextBlock | ErrorBlock;

/**
 * `waiting`: a change is waiting for the applicant. `lost`: the page was reloaded while the turn ran,
 * so its end was never shown.
 */
export type TurnState = "running" | "waiting" | "done" | "stopped" | "failed" | "lost";

export interface Turn {
  id: string;
  question: string;
  blocks: Block[];
  state: TurnState;
  /** The evidence gate refused: what follows is a refusal, and is drawn as one. */
  refused: boolean;
  /** One line under a run that did not end by itself. */
  note?: string;
}

export function newTurn(id: string, question: string): Turn {
  return { id, question, blocks: [], state: "running", refused: false };
}

const isStep = (block: Block): block is StepBlock => block.type === "step";
const isConfirm = (block: Block): block is ConfirmBlock => block.type === "confirm";

/** Names for the steps this page knows, used when an event carries no title of its own. */
const STEP_TITLES: Record<string, string> = {
  classify_intent: "判断问题类型",
  retrieve_requirements: "检索学校库",
  retrieve_passages: "检索官方页面",
  answer_passages: "核对引文",
  search_programs: "搜索项目",
  get_my_profile: "读取背景",
  update_my_profile: "更新背景",
  get_my_portfolio: "读取选校组合",
  get_my_applications: "读取申请",
  propose_portfolio_change: "提议修改",
};

/** What a step is called: the server's title, a name this page knows, or the raw name of a new tool. */
export function stepTitle(step: Pick<StepBlock, "title" | "name">): string {
  return step.title || STEP_TITLES[step.name] || step.name;
}

/** "0.7s", "12s", "1m 05s". */
export function formatDuration(ms: number): string {
  const seconds = ms / 1000;
  if (seconds < 10) return `${seconds.toFixed(1)}s`;
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}m ${String(whole % 60).padStart(2, "0")}s`;
}

function settleConfirm(blocks: Block[], stepId: string, status: StepStatus): Block[] {
  if (status !== "done" && status !== "declined") return blocks;
  return blocks.map((block) =>
    isConfirm(block) && block.stepId === stepId && block.state === "pending"
      ? { ...block, state: status === "done" ? "approved" : "declined", answer: undefined }
      : block,
  );
}

/** Fold one stream event into the turn. Events this page does not draw (`intent`, `tool`) change nothing. */
export function applyEvent(turn: Turn, event: AdvisorEvent): Turn {
  switch (event.type) {
    case "step": {
      const at = turn.blocks.findIndex((block) => isStep(block) && block.id === event.id);
      const { type: _type, ...fields } = event;
      if (at === -1) {
        // A closing event for a step this page never saw opened is not drawn: there is nothing to say about it.
        if (!event.name) return turn;
        const step: StepBlock = { ...fields, type: "step", kind: event.kind ?? "tool", name: event.name };
        return { ...turn, blocks: [...turn.blocks, step] };
      }
      const blocks = turn.blocks.map((block, index) => (index === at ? { ...(block as StepBlock), ...fields } : block));
      return { ...turn, blocks: settleConfirm(blocks, event.id, event.status) };
    }
    case "citations": {
      const refused = turn.refused || event.gate === "refuse";
      // A refusal has no sources to show; the flag alone changes how the reply is drawn.
      if (!event.citations.length) return { ...turn, refused };
      return { ...turn, refused, blocks: [...turn.blocks, { type: "citations", gate: event.gate, citations: event.citations }] };
    }
    case "token": {
      const last = turn.blocks.at(-1);
      if (last?.type === "text") {
        return { ...turn, blocks: [...turn.blocks.slice(0, -1), { ...last, text: last.text + event.text }] };
      }
      return { ...turn, blocks: [...turn.blocks, { type: "text", text: event.text }] };
    }
    case "confirm": {
      const { type: _type, ...fields } = event;
      return { ...turn, blocks: [...turn.blocks, { type: "confirm", state: "pending", ...fields }] };
    }
    case "error": {
      let blocks: Block[] = [...turn.blocks, { type: "error", code: event.code, message: event.message }];
      // The server found nothing to confirm: the change was answered elsewhere, or it has expired.
      if (event.code === "nothing_pending") {
        blocks = blocks.map((block) =>
          isConfirm(block) && block.answer !== undefined ? { ...block, state: "gone", answer: undefined } : block,
        );
      }
      return { ...turn, blocks };
    }
    case "stopped":
      // Stopped from somewhere else: a stop this page asked for is no longer listened to. Another tab
      // sent a message in this conversation, or stopped it.
      return { ...turn, state: "stopped", note: "这一轮在别处被停下了，没有写完。" };
    default:
      return turn;
  }
}

/** The stream has ended by itself: settle whatever is still open and name the turn's state. */
export function finishTurn(turn: Turn): Turn {
  const failed = turn.blocks.some((block) => block.type === "error");
  const blocks = turn.blocks.map((block): Block => {
    if (isConfirm(block) && block.answer !== undefined && block.state === "pending") {
      // No step told how it ended (an older thread without step ids): the answer stands unless the
      // turn failed, in which case the change is still waiting and can be answered again.
      return failed ? { ...block, answer: undefined } : { ...block, state: block.answer ? "approved" : "declined", answer: undefined };
    }
    // The server closes every step it opens; one still running here lost its closing event.
    if (isStep(block) && block.status === "running") return { ...block, status: failed ? "failed" : "stopped" };
    return block;
  });
  const waiting = blocks.some((block) => isConfirm(block) && block.state === "pending");
  return { ...turn, blocks, state: waiting ? "waiting" : failed ? "failed" : turn.state === "stopped" ? "stopped" : "done" };
}

/**
 * What can be said for certain about a turn the applicant stopped. The page stops listening at once,
 * so a tool that was still running may have finished unseen; the note says so instead of guessing.
 */
export function stopNote(turn: Turn): string {
  const steps = turn.blocks.filter(isStep);
  const midway = steps.find((step) => step.status === "running" && step.kind === "tool");
  if (midway) return `已停止。「${stepTitle(midway)}」当时还没返回，结果没有显示出来。`;
  if (steps.some((step) => step.write && step.status === "done")) return "已停止。停下之前保存的改动还在。";
  return "已停止。停下之前没有写入任何改动。";
}

/** The applicant stopped the turn. */
export function stopTurn(turn: Turn): Turn {
  const note = stopNote(turn);
  const blocks = turn.blocks.map((block): Block => {
    if (isStep(block) && block.status === "running") return { ...block, status: "stopped", result: "已停止" };
    if (isConfirm(block) && block.answer !== undefined) return { ...block, answer: undefined };
    return block;
  });
  return { ...turn, blocks, state: "stopped", note };
}

/** The request itself failed (the network, a dropped connection). */
export function failTurn(turn: Turn, message: string): Turn {
  const blocks = turn.blocks.map((block): Block => {
    if (isStep(block) && block.status === "running") return { ...block, status: "failed", result: "连接断了，这一步的结果没有收到" };
    if (isConfirm(block) && block.answer !== undefined) return { ...block, answer: undefined };
    return block;
  });
  const waiting = blocks.some((block) => isConfirm(block) && block.state === "pending");
  return { ...turn, blocks: [...blocks, { type: "error", code: "network", message }], state: waiting ? "waiting" : "failed" };
}

/** The applicant pressed a confirm card's button: hold the card while the answer is on its way. */
export function beginAnswer(turn: Turn, confirmId: string | undefined, approved: boolean): Turn {
  const blocks = turn.blocks
    // An error from an earlier try at answering is no longer the latest word.
    .filter((block) => block.type !== "error")
    .map((block): Block => (isConfirm(block) && block.id === confirmId && block.state === "pending" ? { ...block, answer: approved } : block));
  return { ...turn, blocks, state: "running", note: undefined };
}

/**
 * The applicant wrote a new message instead of answering: the change was not made and cannot be
 * confirmed any more (the server closes the call the same way, `with_unanswered_calls_closed`).
 */
export function voidPending(turn: Turn): Turn {
  if (!turn.blocks.some((block) => isConfirm(block) && block.state === "pending")) return turn;
  const blocks = turn.blocks.map((block): Block => {
    if (isConfirm(block) && block.state === "pending") return { ...block, state: "void", answer: undefined };
    if (isStep(block) && block.status === "waiting") return { ...block, status: "stopped", result: "没有等到确认，没有执行" };
    return block;
  });
  return { ...turn, blocks, state: turn.state === "waiting" ? "done" : turn.state };
}

/** The reply as plain text, for the copy button. */
export function answerText(turn: Turn): string {
  return turn.blocks
    .filter((block): block is TextBlock => block.type === "text")
    .map((block) => block.text.trim())
    .filter(Boolean)
    .join("\n\n");
}

/** Whether the turn has a change still waiting for the applicant. */
export function hasPending(turn: Turn): boolean {
  return turn.blocks.some((block) => isConfirm(block) && block.state === "pending");
}

/**
 * Questions to start from, written from the applicant's own applications: the names are theirs and
 * nothing else is stated. Without applications the questions name none.
 */
export function starterQuestions(overview: Pick<Overview, "rows" | "unknown" | "nearest"> | null): string[] {
  const rows = overview?.rows.filter((row) => !row.sent) ?? [];
  if (!rows.length) return ["我该从哪一步开始准备申请？", "帮我看看我的背景还缺哪几项没填"];
  const name = (row: (typeof rows)[number]) => `${row.record.school} ${row.record.name}`;
  const questions: string[] = [];
  const undated = overview?.unknown[0];
  if (undated) questions.push(`${name(undated)} 的申请截止日期是哪天？`);
  const asked = overview?.nearest ?? rows.find((row) => row !== undated) ?? rows[0];
  questions.push(`${name(asked)} 的语言和均分要求是什么？`);
  questions.push(rows.length > 1 ? "按截止日期排一下我的申请，接下来先做哪个？" : "我这个申请接下来该准备什么？");
  return questions;
}

// ---------- keeping the conversation across a reload ----------

export const STORAGE_KEY = "leapashore:advisor:v1";
/** Turns kept in the browser. The server keeps the whole thread; this is only what is drawn again. */
const KEPT_TURNS = 30;

export interface Stored {
  v: 1;
  /** Whose conversation this is: the account's email, or "" without login mode. */
  owner: string;
  conversationId: string;
  turns: Turn[];
}

export function serialize(owner: string, conversationId: string, turns: Turn[]): string {
  const stored: Stored = { v: 1, owner, conversationId, turns: turns.slice(-KEPT_TURNS) };
  return JSON.stringify(stored);
}

/**
 * A turn as it comes back after a reload. One that was still running was cut off by the reload: the
 * server finished it, but this page never saw how.
 */
export function restoreTurn(turn: Turn): Turn {
  if (turn.state !== "running") return turn;
  const blocks = turn.blocks.map((block): Block => {
    if (isStep(block) && block.status === "running") return { ...block, status: "stopped", result: "页面刷新了，结果没有显示出来" };
    if (isConfirm(block) && block.answer !== undefined) return { ...block, answer: undefined };
    return block;
  });
  if (blocks.some((block) => isConfirm(block) && block.state === "pending")) return { ...turn, blocks, state: "waiting" };
  return { ...turn, blocks, state: "lost", note: "页面刷新时这一轮还没结束，后面的内容没有显示出来。可以再问一次。" };
}

/** The stored conversation, when it is well-formed and belongs to `owner`; otherwise null. */
export function restore(raw: string | null, owner: string): { conversationId: string; turns: Turn[] } | null {
  if (!raw) return null;
  try {
    const stored = JSON.parse(raw) as Partial<Stored>;
    if (stored.v !== 1 || stored.owner !== owner) return null;
    if (typeof stored.conversationId !== "string" || !/^[A-Za-z0-9_-]{1,40}$/.test(stored.conversationId)) return null;
    if (!Array.isArray(stored.turns)) return null;
    const turns = stored.turns.filter(
      (turn): turn is Turn =>
        !!turn && typeof turn.id === "string" && typeof turn.question === "string" && Array.isArray(turn.blocks),
    );
    return { conversationId: stored.conversationId, turns: turns.map(restoreTurn) };
  } catch {
    return null;
  }
}
