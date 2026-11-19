/**
 * The product mark: a leap that lands on a station of the line below it. The station is filled with
 * the surface the mark sits on (`--mark-ground`, the rail by default), so it reads as a hollow stop.
 */
export function Mark({ size = 28 }: { size?: number }) {
  return (
    <svg
      className="mark"
      width={size}
      height={size}
      viewBox="0 0 28 28"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M3.5 22C4 10.5 13 5 19.5 12.8" />
      <path d="M11 22.5h14" />
      <circle cx="20.5" cy="16.2" r="3.1" fill="var(--mark-ground, var(--rail))" />
    </svg>
  );
}
