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
  /** How much the SELLER moved their own number, as a fraction —
   * negative when the price came down.
   *
   * Measured in the ad's own currency, not in euros. A forint ad's euro
   * figure drifts with the ECB rate between the two dates, so a euro
   * ratio mixes the seller's decision with the exchange rate: a seller
   * who took 10.000 Ft off a 15,9M Ft car (0,06%) across a three-month
   * span in which the forint weakened 2,5% comes out at −2,6% in euros,
   * clearing the badge threshold on rate drift alone and printing a
   * "▼ 3% · 10.000 Ft" whose two halves contradict each other. The
   * backend's market index avoids the same trap the same way. */
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
  // A listing's currency comes from its country and so never changes over
  // its life, which is what makes the two originals comparable. Euros are
  // the fallback for a row stored before originals were kept.
  const base = firstOriginal > 0 ? firstOriginal : firstEur;
  const moved = firstOriginal > 0 ? currentOriginal - firstOriginal : currentEur - firstEur;
  return {
    firstEur,
    firstOriginal,
    currentEur,
    deltaEur: currentEur - firstEur,
    deltaOriginal: currentOriginal - firstOriginal,
    pct: moved / base,
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
