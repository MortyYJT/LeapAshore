// The primitives that carry the visual tokens (design D7). Thin on purpose: the classes in
// app/globals.css hold the look, and these keep the markup and the accessibility attributes consistent.

import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "text";

export function Button({
  variant = "secondary",
  small = false,
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; small?: boolean }) {
  return <button type="button" className={`btn btn-${variant}${small ? " btn-small" : ""} ${className}`.trim()} {...rest} />;
}

export function LinkButton({
  href,
  variant = "secondary",
  small = false,
  children,
}: {
  href: string;
  variant?: Variant;
  small?: boolean;
  children: ReactNode;
}) {
  return (
    <Link href={href} className={`btn btn-${variant}${small ? " btn-small" : ""}`}>
      {children}
    </Link>
  );
}

export function Field({
  label,
  htmlFor,
  required = false,
  hint,
  error,
  wide = false,
  errorId,
  children,
}: {
  label: string;
  htmlFor?: string;
  /** The control's id when it is not a labelled input (a radio group), so its error can be described. */
  errorId?: string;
  required?: boolean;
  hint?: ReactNode;
  error?: string | null;
  wide?: boolean;
  children: ReactNode;
}) {
  const labelEl = htmlFor ? (
    <label htmlFor={htmlFor}>
      {label}
      {required && <span className="req">必填</span>}
    </label>
  ) : (
    <span className="label">
      {label}
      {required && <span className="req">必填</span>}
    </span>
  );
  return (
    <div className="field" style={wide ? { gridColumn: "1 / -1" } : undefined}>
      {labelEl}
      {children}
      {error ? (
        <span className="error" id={errorId ?? htmlFor ? `${errorId ?? htmlFor}-error` : undefined} role="alert">
          {error}
        </span>
      ) : hint ? (
        <span className="hint">{hint}</span>
      ) : null}
    </div>
  );
}

export function Pill({ kind = "neutral", children }: { kind?: "neutral" | "sample" | "tier" | "outline"; children: ReactNode }) {
  return <span className={`pill pill-${kind}`}>{children}</span>;
}

/** The PRD §7.7 rule 4 marker for any sample value still on screen. */
export function Sample() {
  return <Pill kind="sample">示例</Pill>;
}

export function Panel({
  label,
  className = "",
  children,
  as: Tag = "section",
}: {
  label?: string;
  className?: string;
  children: ReactNode;
  as?: "section" | "div" | "aside";
}) {
  return (
    <Tag className={`panel ${className}`.trim()} aria-label={label}>
      {children}
    </Tag>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Notice({ error = false, children }: { error?: boolean; children: ReactNode }) {
  return (
    <div className={`notice${error ? " notice-error" : ""}`} role={error ? "alert" : "status"}>
      {children}
    </div>
  );
}

/** A school's mark: its logo, or the first character of its name. Logos identify, they imply no tie. */
export function SchoolMark({ logo, name }: { logo?: string | null; name: string }) {
  return logo ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img className="logo" src={`/logos/${logo}`} alt="" loading="lazy" width={28} height={28} />
  ) : (
    <span className="mono-mark" aria-hidden="true">
      {Array.from(name)[0] ?? "?"}
    </span>
  );
}

/**
 * Loading, for any block whose data is still on its way: grey bars where the content will be, so the page
 * keeps its layout instead of flashing a line of text. The words are kept for screen readers.
 */
export function Loading({ what = "内容", lines = 3 }: { what?: string; lines?: number }) {
  return (
    <div className="skeleton" role="status">
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="skeleton-line" />
      ))}
      <span className="sr-only">正在读取{what}…</span>
    </div>
  );
}

/** A panel of loading bars, for a page section whose data has not arrived. */
export function LoadingPanel({ what }: { what?: string }) {
  return (
    <section className="panel panel-pad section" aria-busy="true">
      <Loading what={what} />
    </section>
  );
}
