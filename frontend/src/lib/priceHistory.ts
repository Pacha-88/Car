import type { Listing, PricePoint } from "../types";

/** How one seller's asking price has moved since the ad went up. */
export interface PriceChange {
  firstEur: number;
  /** The same first price in the seller's own currency. Kept separately
   * because a forint ad shown in forints must quote its own number - the
   * euro figure formatted as Ft would be off by the exchange rate. */
  firstOriginal: number;
  currentEur: number;
  /** Negative when the price came down. In euros, for comparing cars. */
  deltaEur: number;
  /** The same move in the seller's own currency, for showing on the ad's card. */
  deltaOriginal: number;
  /** deltaEur / firstEur — negative when the price came down. */
  pct: number;
  /** How many times the seller moved the number. */
  changes: number;
  /** ISO date the current price started. */
  since: string;
}

/** null when the price has never moved — which is most cars, most of the time. */
export function priceChange(listing: Listing): PriceChange | null {
  const history: PricePoint[] | null | undefined = listing.priceHistory;
  if (!history || history.length < 2) return null;
  const [firstDate, firstEur, firstOriginal] = history[0];
  const [lastDate, currentEur, currentOriginal] = history[history.length - 1];
  if (!(firstEur > 0)) return null;
  void firstDate;
  return {
    firstEur,
    firstOriginal,
    currentEur,
    deltaEur: currentEur - firstEur,
    deltaOriginal: currentOriginal - firstOriginal,
    pct: (currentEur - firstEur) / firstEur,
    changes: history.length - 1,
    since: lastDate,
  };
}

/** A drop worth pointing at.
 *
 * Not every downward move: the export carries a point for every change, and
 * a seller shaving 200 EUR off a 40.000 EUR car is noise on a card that has
 * to earn its space. One percent is roughly the smallest move a person
 * reads as "they dropped the price".
 */
export const MEANINGFUL_DROP = -0.01;

export function isPriceDrop(change: PriceChange | null): boolean {
  return change !== null && change.pct <= MEANINGFUL_DROP;
}
