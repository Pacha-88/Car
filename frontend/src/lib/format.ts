// Money formatting lives in lib/money.ts, which has to know the display
// currency; leaving a second euro-only formatter here would be an easy way
// to reintroduce a price the currency toggle silently doesn't reach.

const numberFormatter = new Intl.NumberFormat("de-DE");

export function formatNumber(value: number): string {
  return numberFormatter.format(Math.round(value));
}

export function formatKm(value: number): string {
  return `${numberFormatter.format(Math.round(value))} km`;
}

export function formatYearMonth(iso: string | null): string | null {
  if (!iso) return null;
  // Textual, not through Date: parsed as UTC midnight and read with local
  // getters, every first-of-month date (which is all of them here) showed
  // the previous month to anyone west of UTC.
  return `${iso.slice(0, 4)}/${iso.slice(5, 7)}`;
}

/** A signed percentage from a ratio: 0.12 → "+12%", -0.083 → "−8%". */
export function formatPctSigned(ratio: number): string {
  const pct = Math.round(ratio * 100);
  if (pct > 0) return `+${pct}%`;
  if (pct < 0) return `−${Math.abs(pct)}%`; // U+2212 minus, matches formatEurSigned's typography
  return "0%";
}
