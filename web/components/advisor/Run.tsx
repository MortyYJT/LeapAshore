"use client";

import { Fragment, memo, useId, useMemo, useState, type ReactNode } from "react";

import { Icon } from "@/components/shell/Icon";
import type { Citation } from "@/lib/advisor";
import {
  answerText,
  formatDuration,
  hasPending,
  stepTitle,
  type Block,
  type CitationsBlock,
  type ConfirmBlock,
  type ErrorBlock,
  type StepBlock,
  type Turn,
} from "@/lib/advisor-run";
import { parseAnswer, type Inline } from "@/lib/advisor-text";
import type { LineColour } from "@/lib/overview";
import { verifiedMark } from "@/lib/taxonomy";

/** The line colour and code of an application, when a step touches one the applicant already has. */
export interface Line {
  colour: LineColour;
  code: string;
}

interface TurnProps {
  turn: Turn;
  /** This turn's stream is open. */
  running: boolean;
  /** Something is running somewhere, so nothing else may start. */
  busy: boolean;
  last: boolean;
  /** The applicant's applications by catalogue program, for the line colour. */
  lines: ReadonlyMap<string, Line>;
  onAnswer: (turnId: string, confirmId: string | undefined, approved: boolean) => void;
  onRetry: () => void;
}

/**
 * One turn: the applicant's message, then the run that answers it. Steps, sources and confirm cards
 * sit on a line of stops in the order they happened; the reply is set below the line it follows.
 */
export const TurnView = memo(function TurnView({ turn, running, busy, last, lines, onAnswer, onRetry }: TurnProps) {
  const cited = useMemo(
    () => new Set(turn.blocks.flatMap((block) => (block.type === "citations" ? block.citations.map((c) => c.n) : []))),
    [turn.blocks],
  );
  // The application each step touches, read off the confirm card the step raised.
  const lineOf = (step: StepBlock): Line | undefined => {
    const base = step.id.replace(/:write$/, "");
    const card = turn.blocks.find((block): block is ConfirmBlock => block.type === "confirm" && block.stepId === base);
    return card?.target?.programId ? lines.get(card.target.programId) : undefined;
  };
  const segments = segment(turn.blocks);
  const lastBlock = turn.blocks.at(-1);
  const thinking = running && (!lastBlock || (lastBlock.type === "step" && lastBlock.status !== "running") || lastBlock.type === "citations");
  const text = answerText(turn);
  const canRetry = last && !busy && !hasPending(turn) && turn.state !== "running";

  return (
    <article className="turn" data-state={turn.state} aria-label={`提问：${turn.question}`}>
      <p className="msg-user">{turn.question}</p>
      {segments.map((part, index) =>
        part.kind === "rail" ? (
          <ol className="run" key={index}>
            {part.blocks.map((block, at) =>
              block.type === "step" ? (
                <Step key={block.id} step={block} line={lineOf(block)} />
              ) : block.type === "citations" ? (
                <li className="run-item" key={`c${at}`}>
                  <Sources block={block} turnId={turn.id} />
                </li>
              ) : block.type === "confirm" ? (
                <li className="run-item" key={block.id ?? `k${at}`}>
                  <Confirm
                    card={block}
                    line={block.target?.programId ? lines.get(block.target.programId) : undefined}
                    busy={busy}
                    onAnswer={(approved) => onAnswer(turn.id, block.id, approved)}
                  />
                </li>
              ) : null,
            )}
          </ol>
        ) : part.kind === "text" ? (
          <Answer
            key={index}
            text={part.text}
            refused={turn.refused}
            streaming={running && index === segments.length - 1}
            cited={cited}
            turnId={turn.id}
          />
        ) : (
          <Problem key={index} error={part.error} />
        ),
      )}
      {thinking && (
        <p className="run-thinking" role="status">
          <span className="spin" aria-hidden="true" />
          {lastBlock ? "正在思考" : "正在连接顾问"}
        </p>
      )}
      {turn.note && (
        <p className="run-note">
          <span className="dot" aria-hidden="true" />
          {turn.note}
        </p>
      )}
      {!running && (text || canRetry) && (
        <div className="turn-actions">
          {text && <CopyButton text={text} />}
          {canRetry && (
            <button type="button" className="btn-quiet" onClick={onRetry}>
              <Icon name="retry" />
              {turn.state === "done" ? "再问一次" : "重试"}
            </button>
          )}
        </div>
      )}
    </article>
  );
});

type Segment =
  | { kind: "rail"; blocks: Block[] }
  | { kind: "text"; text: string }
  | { kind: "error"; error: ErrorBlock };

/** Consecutive steps, sources and confirm cards share one line; a reply or an error breaks it. */
function segment(blocks: Block[]): Segment[] {
  const out: Segment[] = [];
  for (const block of blocks) {
    if (block.type === "text") out.push({ kind: "text", text: block.text });
    else if (block.type === "error") out.push({ kind: "error", error: block });
    else {
      const last = out.at(-1);
      if (last?.kind === "rail") last.blocks.push(block);
      else out.push({ kind: "rail", blocks: [block] });
    }
  }
  return out;
}

const STATUS_WORDS: Record<StepBlock["status"], string> = {
  running: "进行中",
  done: "完成",
  empty: "没有结果",
  failed: "失败",
  waiting: "等待确认",
  declined: "已取消",
  stopped: "已停止",
};

function Step({ step, line }: { step: StepBlock; line?: Line }) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  const title = stepTitle(step);
  const details = Boolean(step.args?.length || step.items?.length);
  const head = (
    <>
      <span className="label">{title}</span>
      {step.kind === "tool" && step.name !== title && <code>{step.name}</code>}
      <span className="meta">
        {/* A step over in an instant (a proposal that only asks) has no time worth printing. */}
        {step.ms !== undefined && step.ms >= 100 && step.status !== "running" && <span className="time num">{formatDuration(step.ms)}</span>}
        {/* The slot is kept without a chevron, so the times of a run line up. */}
        {details ? <Icon name="chevron" className="chev" /> : <span className="chev" />}
      </span>
    </>
  );
  return (
    <li className={`step is-${step.status}${line ? ` has-line line-${line.colour}` : ""}`}>
      <span className="dot" aria-hidden="true">
        {step.status === "failed" ? <Icon name="close" /> : <Icon name="check" />}
      </span>
      <span className="sr-only">{STATUS_WORDS[step.status]}：</span>
      {details ? (
        <button type="button" className="call" aria-expanded={open} aria-controls={panel} onClick={() => setOpen((value) => !value)}>
          {head}
        </button>
      ) : (
        <div className="call">{head}</div>
      )}
      <p className="out">{step.result ?? (step.status === "running" ? "进行中" : "")}</p>
      {details && (
        <dl className="detail" id={panel} hidden={!open}>
          {step.args?.map((row, index) => (
            <div key={`a${index}`}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
          {step.items && step.items.length > 0 && (
            <div>
              <dt>结果</dt>
              <dd>
                <ul>
                  {step.items.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              </dd>
            </div>
          )}
        </dl>
      )}
    </li>
  );
}

const sourceId = (turnId: string, n: number) => `source-${turnId}-${n}`;
const isWeb = (url: string | undefined) => !!url && /^https?:\/\//.test(url);

/** The official pages an answer rests on. Only what the server sent is shown: nothing is filled in here. */
function Sources({ block, turnId }: { block: CitationsBlock; turnId: string }) {
  return (
    <div className="sources">
      {block.citations.map((citation) => (
        <Source key={citation.n} citation={citation} id={sourceId(turnId, citation.n)} alone={block.citations.length === 1} />
      ))}
    </div>
  );
}

function Source({ citation: c, id, alone }: { citation: Citation; id: string; alone: boolean }) {
  const checked = verifiedMark(c.status);
  const fetched = c.fetchedAt?.slice(0, 10);
  return (
    <figure className="cite" id={id} tabIndex={-1}>
      <figcaption className="cite-head">
        <span className="cite-n num" aria-label={`来源 ${c.n}`}>
          {c.n}
        </span>
        <span className="cite-program">{c.program}</span>
        {checked && (
          <span className="st is-sent">
            <Icon name="check" />
            {checked}
          </span>
        )}
      </figcaption>
      {c.quotes?.map((quote, index) => (
        <blockquote key={index}>
          {index === 0 && c.field && <span className="cite-field">{c.field} · 官网原文</span>}
          <p lang="en">{quote}</p>
        </blockquote>
      ))}
      {c.fields && c.fields.length > 0 && (
        <details className="cite-record" open={alone}>
          <summary>
            <Icon name="chevron" className="chev" />
            学校库的记录，{c.fields.length} 项
          </summary>
          <dl>
            {c.fields.map((row, index) => (
              <div key={index}>
                <dt>{row.label}</dt>
                <dd>
                  {row.value}
                  {row.quote && (
                    <q className="cite-quote" lang="en">
                      {row.quote}
                    </q>
                  )}
                  {isWeb(row.url) && (
                    <a className="link cite-page" href={row.url} target="_blank" rel="noreferrer">
                      这一项的出处
                    </a>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        </details>
      )}
      <p className="cite-source">
        {isWeb(c.url) ? (
          <a className="cite-link" href={c.url} target="_blank" rel="noreferrer">
            <Icon name="external" />
            <span className="link">{c.title}</span>
          </a>
        ) : (
          <span>{c.title}</span>
        )}
        {fetched && <span className="num">抓取于 {fetched}</span>}
      </p>
    </figure>
  );
}

const SETTLED: Record<Exclude<ConfirmBlock["state"], "pending">, string> = {
  approved: "你已确认",
  declined: "已取消，没有改动",
  void: "没有等到确认，这个改动没有执行",
  gone: "这个改动已经不在等待确认",
};

/** A change waiting for the applicant: what it replaces and what it becomes, before anything is written. */
function Confirm({ card, line, busy, onAnswer }: { card: ConfirmBlock; line?: Line; busy: boolean; onAnswer: (approved: boolean) => void }) {
  const pending = card.state === "pending";
  const sending = card.answer !== undefined;
  const name = [card.target?.school, card.target?.program].filter(Boolean).join(" · ");
  return (
    <section className={`confirm${pending ? "" : " is-settled"}${card.state === "approved" || pending ? "" : " is-void"}`} aria-label={pending ? "等待确认的改动" : "已处理的改动"}>
      <h3 className="confirm-head">{pending ? "写入前请你确认" : SETTLED[card.state as keyof typeof SETTLED]}</h3>
      {name && (
        <p className={`confirm-what${line ? ` line-${line.colour}` : ""}`}>
          {line && <span className="bullet">{line.code}</span>}
          <span>{name}</span>
        </p>
      )}
      {card.changes && card.changes.length > 0 ? (
        <dl className="changes">
          {card.changes.map((change, index) => (
            <div key={index}>
              <dt>{change.label}</dt>
              <dd>
                {change.before !== null && (
                  <>
                    <del>{change.before}</del>
                    <Icon name="arrow" className="to" />
                  </>
                )}
                <ins>{change.after}</ins>
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="confirm-summary">{card.summary}</p>
      )}
      {pending && (
        <div className="confirm-foot">
          <button type="button" className="btn btn-primary" disabled={busy} aria-busy={sending && card.answer === true} onClick={() => onAnswer(true)}>
            {sending && card.answer ? "正在写入…" : "确认写入"}
          </button>
          <button type="button" className="btn btn-secondary" disabled={busy} aria-busy={sending && card.answer === false} onClick={() => onAnswer(false)}>
            {sending && card.answer === false ? "正在取消…" : "取消"}
          </button>
        </div>
      )}
    </section>
  );
}

function Answer({ text, refused, streaming, cited, turnId }: { text: string; refused: boolean; streaming: boolean; cited: ReadonlySet<number>; turnId: string }) {
  const blocks = useMemo(() => parseAnswer(text), [text]);
  const inline = (parts: Inline[]): ReactNode =>
    parts.map((part, index) => {
      switch (part.type) {
        case "strong":
          return <strong key={index}>{part.text}</strong>;
        case "code":
          return <code key={index}>{part.text}</code>;
        case "link":
          return (
            <a key={index} className="link" href={part.href} target="_blank" rel="noreferrer">
              {part.text}
            </a>
          );
        case "cite":
          // A number with no card behind it stays as the model wrote it.
          return cited.has(part.n) ? (
            <button
              key={index}
              type="button"
              className="cite-ref num"
              aria-label={`看来源 ${part.n}`}
              onClick={() => {
                const card = document.getElementById(sourceId(turnId, part.n));
                card?.scrollIntoView({ block: "nearest" });
                card?.focus({ preventScroll: true });
              }}
            >
              {part.n}
            </button>
          ) : (
            <Fragment key={index}>[{part.n}]</Fragment>
          );
        default:
          return <Fragment key={index}>{part.text}</Fragment>;
      }
    });
  return (
    <div className={`answer${refused ? " is-refusal" : ""}`}>
      {refused && <p className="refusal-label">没有回答：查不到可引用的官方来源</p>}
      {blocks.map((block, index) => {
        const caret = streaming && index === blocks.length - 1 && <span className="caret" aria-hidden="true" />;
        if (block.type === "heading") {
          return (
            <p className="answer-heading" key={index}>
              {inline(block.content)}
              {caret}
            </p>
          );
        }
        if (block.type === "list") {
          const List = block.ordered ? "ol" : "ul";
          return (
            <List key={index}>
              {block.items.map((item, at) => (
                <li key={at}>
                  {inline(item)}
                  {at === block.items.length - 1 && caret}
                </li>
              ))}
            </List>
          );
        }
        return (
          <p key={index}>
            {block.lines.map((line, at) => (
              <Fragment key={at}>
                {at > 0 && <br />}
                {inline(line)}
              </Fragment>
            ))}
            {caret}
          </p>
        );
      })}
    </div>
  );
}

/**
 * A turn that did not finish. The server's sentence says what happened; a fault is written in red,
 * and a limit or a wait (nothing is broken, the applicant only has to wait) is said without it.
 */
const QUIET = new Set([
  "rate_limited",
  "daily_tokens_subject",
  "daily_tokens_ip",
  "daily_tokens_site",
  "limits_unavailable",
  "busy",
  "unauthorized",
  "nothing_pending",
  "confirm_in_progress",
]);

function Problem({ error }: { error: ErrorBlock }) {
  return (
    <div className={`problem${QUIET.has(error.code ?? "") ? " is-quiet" : ""}`} role="alert">
      {/* The provider's outage reads the same as any other in the server's words; say which it is. */}
      {error.code === "model_unavailable" && <b>模型现在连不上</b>}
      <span>{error.message}</span>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  return (
    <button
      type="button"
      className="btn-quiet"
      onClick={() => {
        const settle = (next: "copied" | "failed") => {
          setState(next);
          window.setTimeout(() => setState("idle"), 2000);
        };
        navigator.clipboard?.writeText(text).then(
          () => settle("copied"),
          () => settle("failed"),
        ) ?? settle("failed");
      }}
    >
      <Icon name={state === "copied" ? "check" : "copy"} />
      <span aria-live="polite">{state === "copied" ? "已复制" : state === "failed" ? "没能复制" : "复制回答"}</span>
    </button>
  );
}
