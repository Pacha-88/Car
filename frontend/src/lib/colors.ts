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

/** Whether a year falls in the lumped "everything older" bucket.
 *
 * That bucket is drawn as a hollow ring rather than a filled dot, and this
 * is what decides. Colour alone could not carry it: run the dataviz
 * validator over the five year hues plus a neutral with `--pairs all` -
 * which is the right pairlist for a scatter, since any two colours can
 * land side by side - and the neutral is ΔE 5.2 from the green under
 * protanopia and 13.3 under normal vision, against floors of 8 and 15. No
 * neutral inside the palette's lightness band clears them, because a grey
 * has no hue to be separated on. Shape does, for every kind of vision. */
export function isOlderBucket(year: number, maxYear: number): boolean {
  return maxYear - year >= DISTINCT_YEAR_SLOTS;
}

export function yearColor(year: number, maxYear: number): string {
  const age = maxYear - year;
  if (age < 0) return "var(--year-5)"; // future-dated listing: treat as newest
  if (age >= DISTINCT_YEAR_SLOTS) return "var(--year-older)";
  return `var(--year-${DISTINCT_YEAR_SLOTS - age})`;
}

/** Legend entries for the years present, oldest first. Years older than
 * the five distinct slots collapse into one "<= year" entry. */
export function yearLegendEntries(years: number[], maxYear: number): { label: string; color: string; older: boolean }[] {
  const distinct = years.filter((y) => maxYear - y < DISTINCT_YEAR_SLOTS).sort((a, b) => a - b);
  const hasOlder = years.some((y) => maxYear - y >= DISTINCT_YEAR_SLOTS);
  const entries: { label: string; color: string; older: boolean }[] = [];
  if (hasOlder) {
    entries.push({ label: `≤ ${maxYear - DISTINCT_YEAR_SLOTS}`, color: "var(--year-older)", older: true });
  }
  for (const y of distinct) entries.push({ label: String(y), color: yearColor(y, maxYear), older: false });
  return entries;
}
