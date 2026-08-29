import type { Listing, SaleTime } from "../types";

/** Days this tracker has seen the ad, against the DATA's own clock.
 *
 * `latestScrapeDate` rather than the reader's wall clock: a week-old
 * export opened on Friday must not claim every car gained a week of
 * market time nobody observed. Null when the export predates the field.
 *
 * This is a lower bound on the ad's true age - the tracker cannot know
 * about the weeks before it started watching - which is why the wording
 * everywhere is "listed N+ days", never "N days old".
 */
export function daysListed(listing: Listing, latestScrapeDate: string | null): number | null {
  if (!latestScrapeDate) return null;
  const first = new Date(`${listing.firstSeenAt.slice(0, 10)}T12:00:00`).getTime();
  const latest = new Date(`${latestScrapeDate}T12:00:00`).getTime();
  const days = Math.round((latest - first) / 86_400_000);
  return days >= 0 ? days : null;
}

/** The sale-time median this car should be read against: its own variant's
 * when enough of those sold, the whole model's otherwise. */
export function saleTimeFor(saleTimes: SaleTime[], listing: Listing): SaleTime | null {
  return (
    saleTimes.find((s) => s.model === listing.model && s.variant === listing.variant) ??
    saleTimes.find((s) => s.model === listing.model && s.variant === null) ??
    null
  );
}

/** Sat at least two weeks AND half again the median for its peers: the
 * seller is having trouble, which is exactly when an offer lands. Never
 * claimed without a median to compare against. */
export function isSlowSeller(days: number | null, typical: SaleTime | null): boolean {
  return days !== null && typical !== null && days >= 14 && days >= typical.medianDays * 1.5;
}
