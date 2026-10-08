"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { assessAll } from "@/lib/eligibility";
import { UNKNOWN, toPortfolioProgram } from "@/lib/programs-source";
import type { PortfolioItem, PortfolioTier, Profile, Program } from "@/lib/types";

const TIER_LABEL: Record<PortfolioTier, string> = {
  冲: "冲刺",
  稳: "匹配",
  保: "稳妥",
};

const TIER_CLASS: Record<PortfolioTier, string> = {
  冲: "tag-chong",
  稳: "tag-wen",
  保: "tag-bao",
};

interface Props {
  profile: Profile;
  /**
   * The catalogue as `GET /api/programs` served it, or `null` while that read is in flight or after it
   * failed.
   *
   * `null` is a distinct state rather than an empty list: "the catalogue could not be read" is not the
   * claim "there are no programs", and rendering an empty screen for it would say the applicant's
   * target has no matches. The failed read is reported instead, and the confirm button stays disabled
   * because there is nothing to confirm from.
   */
  programs: Program[] | null;
  /** The portfolio the server currently holds, so a reopened picker opens on what the applicant has. */
  portfolio: PortfolioItem[];
  /** Why reading the catalogue failed, if it did. Shown instead of the list. */
  programsError: string | null;
  /**
   * Store the chosen portfolio on the server. Resolves to `null` when the write landed, or to the
   * transport's own message when it did not.
   *
   * The message rather than a boolean, because the failure has to be shown here: a confirmation the
   * server did not take must not advance the flow to a screen that renders a portfolio the database
   * never stored, and the picker is the only place the applicant can still do something about it. The
   * message carries the status the route answered with, so a 422 naming a broken list reads
   * differently from a server that was never reachable.
   */
  onConfirm: (items: PortfolioItem[]) => Promise<string | null>;
  onBack: () => void;
}

/**
 * The five catalogue fields the route may leave null, as the copy the applicant reads.
 *
 * The rule this exists for: an unknown stays unknown. A `null` rendered as `""` would say the program
 * has no city, no duration and no recorded language requirement, which is a claim the catalogue did
 * not make; `null` rendered raw would print the word "null". So one marker, in one place.
 */
function orUnknown(value: string | null): string {
  return value ?? UNKNOWN;
}

export default function PortfolioPicker({
  profile,
  programs,
  portfolio,
  programsError,
  onConfirm,
  onBack,
}: Props) {
  const assessments = useMemo(
    () => assessAll(programs ?? [], profile),
    [programs, profile],
  );
  /**
   * Which programs are ticked, as a map keyed by slug.
   *
   * It starts empty and is seeded by the effect below once the catalogue has arrived. An initializer
   * cannot do it: the catalogue is fetched, so on the first render `programs` is `null`, every
   * assessment has no suggested tier, and a `useState` initializer runs exactly once — a page that
   * seeded there spent the rest of its life with nothing ticked while every card rendered a tier.
   * Measured in a browser against the running server: six cards, every one of them "稳妥" or similar,
   * and a confirm button reading 确认组合（0 个） with no way to advance.
   *
   * `touched` is what keeps the seeding from fighting the applicant. It is set by the first toggle, and
   * after that their ticks are the answer — otherwise a catalogue that answered late, or a re-render
   * of any kind, would put back a program they had just removed.
   *
   * The seeding waits for a catalogue with something in it rather than merely for one that has
   * arrived. An empty list would seed an empty selection and mark itself done, which is the same
   * unusable screen by a different route.
   */
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const touched = useRef(false);
  const seeded = useRef(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  /**
   * Tick the recommended combination plus whatever the applicant already holds, once, when the
   * catalogue arrives.
   *
   * Two sources, and both are needed. The system's own suggestions are ticked by default, which is
   * what makes "confirm the recommended combination" one click. The programs the server already holds
   * are ticked as well, so reopening the picker shows the applicant's actual portfolio rather than the
   * recommendation over again — without that, confirming again would silently drop the stored rows the
   * filter admits. `carriedItems` is what covers the ones it does not: a tick can only be drawn for a
   * card, and a stored row outside the filter has no card.
   *
   * It is deliberately not written as a `useMemo` over the assessments that the render reads: a value
   * derived on every render cannot be un-ticked. This runs once, and only while nothing has been
   * touched.
   */
  useEffect(() => {
    if (programs === null || programs.length === 0 || seeded.current || touched.current) return;
    seeded.current = true;
    const suggested = assessments
      .filter((a) => a.suggestedTier !== null)
      .map((a) => [a.program.slug, true] as const);
    setPicked({
      ...Object.fromEntries(suggested),
      ...Object.fromEntries(portfolio.map((item) => [item.programSlug, true])),
    });
  }, [programs, assessments, portfolio]);

  /**
   * The rows the server already holds that this screen cannot draw, because the assessment list is
   * filtered by the profile's target degree and field (`assessAll`) and these rows' programs fall
   * outside that filter.
   *
   * They are not deleted, and that is the whole point of collecting them: the confirmation sends the
   * whole portfolio and the server removes every row the payload does not name, so a row left out of
   * the payload is destroyed permanently, with a `removed` audit entry and nothing on screen to say
   * it happened. The comment that used to sit in `chosenItems` claimed the picker protected "whatever
   * they had added by hand"; it protected only the rows the filter admits.
   *
   * Not reachable with the current catalogue — all six seeded programs share one degree and one field
   * — but it becomes reachable with the first second field or degree, which is where the design is
   * going. Measured in a real browser with `GET /api/programs` stubbed to add one 研究型硕士 program and
   * the profile moved to that degree: the picker drew the injected card, held a stored 授课型硕士 row it
   * could not draw, and the confirmation's payload — on the version without this — named only the
   * card. The stored row was removed from the server by that call and would have stayed gone.
   *
   * These travel through the payload untouched rather than being refused, and the reason is the
   * applicant's: the rows are their own decisions, they are stored, and a confirmation of the cards on
   * screen is not a statement about a program this screen never showed. Refusing instead would block
   * every confirmation while a hidden row exists, with no way out from inside the picker, and the flow
   * would be stuck on a filter the applicant cannot see. The notice below says the rest is kept.
   *
   * One consequence worth stating rather than discovering: `chosenCount` counts the keys in `picked`,
   * and the seeding effect ticks every stored row by its slug whether or not that row has a card, so a
   * carried row keeps the confirm button enabled. That is the right side of the line — the portfolio
   * being confirmed is not empty — but the number on the button is then not a count of the cards, nor
   * of the rows that will be stored: it is the count of stored rows, carried ones included.
   */
  const carriedItems = useMemo(() => {
    const shown = new Set(assessments.map((a) => a.program.slug));
    return portfolio.filter((item) => !shown.has(item.programSlug));
  }, [assessments, portfolio]);

  const chosenCount = Object.values(picked).filter(Boolean).length;

  function toggle(slug: string) {
    touched.current = true;
    setPicked((prev) => ({ ...prev, [slug]: !prev[slug] }));
  }

  /**
   * The chosen rows as the server stores them: the visible ticks, plus every stored row this screen
   * could not show.
   *
   * `isPrimary` for a visible row is read back from the portfolio the server served: a whole
   * replacement restates the first choice, and an omitted `isPrimary` reads as `false` (a controller
   * ruling recorded in `api/app/services/applications.py`), so a row that was the applicant's 首选 has
   * to carry the flag back or this call would release it.
   *
   * A carried row is sent exactly as it was stored, `isPrimary` included, and neither of the two
   * fields is recomputed from an assessment — there is no assessment for a program that is not on
   * screen. `needsReview` on a visible row is the system's own admission that it could not tier the
   * program, and it is derived from the assessment and never from the served portfolio: set when
   * `suggestedTier` is null, so that the interface never presents an unmatchable program as a
   * recommendation. A carried row is not re-assessed, so its stored `needsReview` is what travels.
   *
   * `program` travels with a visible row too, taken from the catalogue entry the card was drawn from.
   * These items are not only a payload: `handlePortfolioConfirm` puts them on screen as the portfolio
   * when the re-read that follows the write fails, and the two views print the institution and the name
   * from them. Without this the fallback path carried no program at all, and both views rendered
   * `未知 · 未知` for the six programs the applicant had just confirmed — measured with the re-read
   * stubbed to fail.
   */
  function chosenItems(): PortfolioItem[] {
    const stored = new Map(portfolio.map((item) => [item.programSlug, item]));
    const visible: PortfolioItem[] = assessments
      .filter((a) => picked[a.program.slug])
      .map((a) => ({
        programSlug: a.program.slug,
        // The catalogue entry this card was drawn from, in the two fields the portfolio views read.
        // `Program.name` is the served English name (§3.6), which is the field they call `nameEn`; the
        // wire's Chinese name is not held here and is not something these screens print.
        program: toPortfolioProgram(a.program),
        // When the system cannot tier a program, fall back to 'steady' but flag it, so the
        // interface never presents it as a system recommendation.
        tier: (a.suggestedTier ?? stored.get(a.program.slug)?.tier ?? "稳") as PortfolioTier,
        confirmed: true,
        needsReview: a.suggestedTier === null,
        isPrimary: stored.get(a.program.slug)?.isPrimary === true,
      }));
    return [...visible, ...carriedItems];
  }

  /**
   * Store the portfolio. The flow advances only if the server took it.
   *
   * A failed write is said out loud and the applicant stays on this screen with their ticks, which is
   * the whole point: the stage used to change first, so a confirmation the server never stored left
   * them looking at an application flow built on a portfolio that did not exist, with nothing on
   * screen to say so. The button is disabled while the request is in flight so a second click cannot
   * race the first, and it is re-enabled on failure so the retry is one click away.
   */
  async function confirm() {
    const items = chosenItems();
    setSaving(true);
    setSaveError(null);
    const failure = await onConfirm(items);
    setSaving(false);
    if (failure !== null) setSaveError(`申请组合没有保存到服务器（${failure}），请重试。`);
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-5 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-extrabold">为你筛出的申请组合</h1>
        <p className="mt-2 text-sm leading-relaxed text-[var(--color-ink-soft)]">
          勾掉不想申的，确认后进入申请流程。
        </p>
      </header>

      {programsError !== null && (
        <div className="mb-4 rounded-xl border-2 border-[var(--color-danger)] bg-[var(--color-danger-soft)] p-3">
          <p className="text-sm leading-relaxed text-[var(--color-danger)]">
            项目目录没能从服务器读取，这里是空的（{programsError}）。
          </p>
        </div>
      )}

      {saveError !== null && (
        <div className="mb-4 rounded-xl border-2 border-[var(--color-danger)] bg-[var(--color-danger-soft)] p-3">
          <p className="text-sm leading-relaxed text-[var(--color-danger)]">{saveError}</p>
        </div>
      )}

      {carriedItems.length > 0 && (
        <div className="mb-4 rounded-xl border-2 border-[var(--color-line)] bg-[var(--color-surface)] p-3">
          <p className="text-sm leading-relaxed text-[var(--color-ink-soft)]">
            另有 {carriedItems.length} 个已保存的项目不在当前筛选范围内（目标学位或方向不同），
            这里看不到，但它们会原样保留，不会被删掉。
          </p>
        </div>
      )}

      {programs === null && programsError === null && (
        <p className="text-sm text-[var(--color-ink-soft)]">正在读取项目目录…</p>
      )}
      <div className="grid gap-4">
        {assessments.map((a) => {
          const tier = a.suggestedTier;
          return (
            <article
              key={a.program.slug}
              className="card"
              style={{ borderColor: picked[a.program.slug] ? "var(--color-brand)" : undefined }}
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-extrabold">{a.program.university}</h2>
                    {tier ? (
                      <span className={`tag ${TIER_CLASS[tier]}`}>{TIER_LABEL[tier]}</span>
                    ) : a.gapStatus === "存在门槛缺口" ? (
                      <span className="tag tag-muted">暂不推荐</span>
                    ) : (
                      <span className="tag tag-warn">待人工核验</span>
                    )}
                    <span
                      className={`tag ${
                        a.gapStatus === "满足基础门槛"
                          ? "tag-ok"
                          : a.gapStatus === "存在门槛缺口"
                            ? "tag-gap"
                            : "tag-warn"
                      }`}
                    >
                      {a.gapStatus}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-[var(--color-ink-soft)]">
                    {orUnknown(a.program.name)} · {orUnknown(a.program.city)} ·{" "}
                    {orUnknown(a.program.duration)}
                  </p>
                </div>
                <button
                  className={`btn ${picked[a.program.slug] ? "btn-primary" : "btn-ghost"}`}
                  onClick={() => toggle(a.program.slug)}
                  disabled={a.gapStatus === "存在门槛缺口"}
                >
                  {picked[a.program.slug] ? "已加入" : tier === null ? "仍然加入" : "加入组合"}
                </button>
              </div>

              <ul className="mt-4 grid gap-1.5 text-sm text-[var(--color-ink-soft)]">
                {a.reasons.map((r) => (
                  <li key={r}>· {r}</li>
                ))}
              </ul>

              {a.risks.length > 0 && (
                <div className="mt-3 rounded-xl bg-[var(--color-surface)] p-3">
                  <div className="text-xs font-bold text-[var(--color-ink-soft)]">需要继续确认</div>
                  <ul className="mt-1 grid gap-1 text-sm">
                    {a.risks.map((r) => (
                      <li key={r}>! {r}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="mt-3 text-xs">
                <a
                  className="text-[var(--color-brand-dark)] underline"
                  href={a.program.source.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {a.program.source.title} ↗
                </a>
              </div>
            </article>
          );
        })}
      </div>

      <footer className="sticky bottom-0 mt-8 flex items-center justify-between gap-4 border-t-2 border-[var(--color-line)] bg-[var(--color-surface)] py-4">
        <button className="btn btn-ghost" onClick={onBack}>
          返回修改背景
        </button>
        <button
          className="btn btn-primary min-w-[200px]"
          onClick={confirm}
          disabled={chosenCount === 0 || saving}
        >
          {saving ? "正在保存…" : `确认组合（${chosenCount} 个）并进入流程`}
        </button>
      </footer>
    </div>
  );
}
