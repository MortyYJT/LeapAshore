/** The product mark: an arc leaping over a line, in the accent (design D7). */
export function Mark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 22 22" aria-hidden="true">
      <path d="M2 16.5h18" stroke="var(--color-accent)" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M4.5 14c2.4-6.6 9.6-8.2 12.6-2.2" fill="none" stroke="var(--color-accent)" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="17.4" cy="12.2" r="1.5" fill="var(--color-accent)" />
    </svg>
  );
}
