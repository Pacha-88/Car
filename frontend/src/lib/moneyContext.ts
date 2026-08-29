import { createContext, useContext } from "react";
import type { Currency } from "./money";

export interface Money {
  currency: Currency;
  setCurrency: (c: Currency) => void;
  /** null when no scrape has ever stored a rate — the UI then stays in euros. */
  hufPerEur: number | null;
  format: (eurValue: number) => string;
  /** One car's asking price. Shows the ad's own number when the ad is
   * written in the currency being displayed, and the converted euro figure
   * otherwise. Use this for a listing; `format` for anything derived.
   *
   * Deliberately not the same number the price FILTER works on, which
   * stays in euros: "what does this ad say" and "how does this car compare
   * to a Berlin one" are different questions, and only the second can be
   * asked on one axis across six countries. The two answers differ by
   * whatever the rate moved between the scrape and the export - a fraction
   * of a percent - so a car within about 1% of a slider edge can sit just
   * outside a range its own card appears to be inside. That is the price of
   * both numbers being right about their own question. */
  formatListing: (listing: { priceEur: number; priceOriginal?: number | null; currencyOriginal?: string | null }) => string;
  /** How much a price MOVED on one car, in the same currency the price
   * itself is shown in, so "12,4 millió Ft" and "450.000 Ft" are the same
   * kind of number. Unsigned - the caller says which way it went, and a
   * "▼" beside a "−" says it twice.
   *
   * `original` is the move the seller actually made, in the ad's own
   * currency, and is what gets converted when the screen is in the other
   * one. `eur` is only the fallback for a row stored before originals were
   * kept: the difference between a forint ad's two euro figures carries
   * the exchange rate as well as the seller's decision, so a badge built
   * on it would print a percentage and an amount that disagree. */
  formatListingAmount: (
    listing: { currencyOriginal?: string | null },
    amount: { eur: number; original: number },
  ) => string;
  formatSigned: (eurValue: number) => string;
  formatTick: (eurValue: number) => string;
  /** Y-axis width the current currency's ticks need. */
  axisWidth: number;
}

export const MoneyContext = createContext<Money | null>(null);

/** Currency is a display choice that reaches almost every component — stat
 * tiles, both charts, the cards, the price slider. Threading it as a prop
 * through all of them would be five signatures changed to carry one
 * setting, so it travels in context instead. */
export function useMoney(): Money {
  const value = useContext(MoneyContext);
  if (!value) throw new Error("useMoney must be used inside <MoneyProvider>");
  return value;
}
