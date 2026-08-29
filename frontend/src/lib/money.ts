/** Prices are stored and compared in euros — the market spans six eurozone
 * countries — but this dashboard is read by someone shopping in Hungary,
 * who thinks in millions of forints. So EUR is the unit of record and the
 * display currency is a view on top of it, converted at the rate the last
 * scrape used (it travels in the export as `hufPerEur`).
 *
 * Nothing here rounds before it has to: a converted price is derived at
 * render time from the euro figure, never stored, so a rate change is one
 * number changing rather than every listing going stale.
 */

export type Currency = "EUR" | "HUF";

const MILLION = 1_000_000;

// de-DE, not hu-HU: dot for thousands, comma for decimals. That is correct
// Hungarian for decimals and it is what the euro prices on the same screen
// already use, so one screen never mixes "35.000" and "35 000".
const eurFormat = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const twoDecimals = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const oneDecimal = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 });
const whole = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });

/** A price for reading: "35.000 €" or "13,65 millió Ft". */
export function formatMoney(eurValue: number, currency: Currency, hufPerEur: number | null): string {
  if (currency === "EUR" || hufPerEur === null) return eurFormat.format(eurValue);
  const ft = eurValue * hufPerEur;
  // Millions are the unit a car is discussed in; a slope or a price delta
  // is often far smaller, and "0,08 millió Ft" tells nobody anything.
  if (Math.abs(ft) >= MILLION) return `${twoDecimals.format(ft / MILLION)} millió Ft`;
  return `${whole.format(ft)} Ft`;
}

/** A price already denominated in `currency` — no conversion, no round trip.
 *
 * `formatMoney` takes euros because euros are the unit of record for
 * everything derived (medians, slopes, the depreciation curve). A single
 * car's asking price is different: when the ad is written in the currency
 * being displayed, the honest thing to show is the ad's own number.
 */
export function formatAmount(value: number, currency: Currency): string {
  if (currency === "EUR") return eurFormat.format(value);
  if (Math.abs(value) >= MILLION) return `${twoDecimals.format(value / MILLION)} millió Ft`;
  return `${whole.format(value)} Ft`;
}

/** Same, but a positive number keeps its plus sign — for deltas. */
export function formatMoneySigned(eurValue: number, currency: Currency, hufPerEur: number | null): string {
  return (eurValue > 0 ? "+" : "") + formatMoney(eurValue, currency, hufPerEur);
}

/** A price for an axis tick, where space is short: "€45k" or "17,5M Ft". */
export function formatMoneyTick(eurValue: number, currency: Currency, hufPerEur: number | null): string {
  if (eurValue === 0) return "0"; // "€0k" and "0M Ft" both read as noise
  if (currency === "EUR" || hufPerEur === null) return `€${Math.round(eurValue / 1000)}k`;
  return `${oneDecimal.format((eurValue * hufPerEur) / MILLION)}M Ft`;
}

/** How much room a y-axis must leave for those ticks. Lives here, beside
 * the function that decides how long they get: "21,9M Ft" needs half as
 * much again as "€45k", and a too-narrow axis wraps every label onto two
 * lines rather than clipping, which is easy to miss until you look. */
export function axisWidthFor(currency: Currency, hufPerEur: number | null): number {
  return currency === "EUR" || hufPerEur === null ? 56 : 76;
}
