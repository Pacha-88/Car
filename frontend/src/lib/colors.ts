/** Registration-year color assignment.
 *
 * The five newest years each get a distinct hue; everything older shares
 * one muted "older" color. Colors live only in index.css (--year-*), and
 * this returns CSS var() references, so the light/dark swap happens at
 * paint time with no duplicated hex values in JS.
 *
 * Anchored to the newest year in the current view: the newest year is
 * always --year-5 (blue), the one before --year-4, and so on. A single
 * ancient outlier therefore can't compress the whole scale (a real bug
 * with the previous interpolated ramp: one junk "2002" listing pushed
 * every real year into the top of the ramp).
 */

export const DISTINCT_YEAR_SLOTS = 5;

export function yearColor(year: number, maxYear: number): string {
  const age = maxYear - year;
  if (age < 0) return "var(--year-5)"; // future-dated listing: treat as newest
  if (age >= DISTINCT_YEAR_SLOTS) return "var(--year-older)";
  return `var(--year-${DISTINCT_YEAR_SLOTS - age})`;
}

/** Legend entries for the years present, oldest first. Years older than
 * the five distinct slots collapse into one "<= year" entry. */
export function yearLegendEntries(years: number[], maxYear: number): { label: string; color: string }[] {
  const distinct = years.filter((y) => maxYear - y < DISTINCT_YEAR_SLOTS).sort((a, b) => a - b);
  const hasOlder = years.some((y) => maxYear - y >= DISTINCT_YEAR_SLOTS);
  const entries: { label: string; color: string }[] = [];
  if (hasOlder) {
    entries.push({ label: `≤ ${maxYear - DISTINCT_YEAR_SLOTS}`, color: "var(--year-older)" });
  }
  for (const y of distinct) entries.push({ label: String(y), color: yearColor(y, maxYear) });
  return entries;
}
