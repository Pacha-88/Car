// Mirrors the --year-N custom properties in index.css. Duplicated on
// purpose: an ordinal color scale needs plain values to compute with in
// JS, not CSS custom properties, and this ramp is small and stable (see
// the dataviz skill: light no lighter than step 250, dark no darker than
// step 600 - this range clears both surfaces without a separate dark set).
export const YEAR_RAMP = ["#86b6ef", "#6da7ec", "#3987e5", "#2a78d6", "#1c5cab", "#184f95"];

export function yearColor(year: number, minYear: number, maxYear: number): string {
  if (maxYear === minYear) return YEAR_RAMP[Math.floor(YEAR_RAMP.length / 2)];
  const t = (year - minYear) / (maxYear - minYear);
  const index = Math.round(t * (YEAR_RAMP.length - 1));
  return YEAR_RAMP[Math.min(Math.max(index, 0), YEAR_RAMP.length - 1)];
}
