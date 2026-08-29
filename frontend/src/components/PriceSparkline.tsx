import { useMoney } from "../lib/moneyContext";
import type { Listing } from "../types";

/**
 * The shape of one seller's pricing, in 52x16 pixels.
 *
 * A STEP line, not a slope: an asking price is held and then moved, and a
 * diagonal between two prices draws a glide nobody asked. The x axis is
 * real time - a cut yesterday and a cut two months ago are different
 * stories - and the last price extends to the latest scrape, so the flat
 * tail says "still asking this".
 *
 * Ink only, no colour: the green drop badge beside it already carries the
 * verdict, and this carries the shape. Nothing renders for a car whose
 * seller never moved - most cars - so the mark is information the moment
 * it appears.
 */
const W = 52;
const H = 16;
const PAD = 2.5;

export function PriceSparkline({
  listing,
  latestScrapeDate,
}: {
  listing: Listing;
  latestScrapeDate: string | null;
}) {
  const money = useMoney();
  const history = listing.priceHistory;
  if (!history || history.length < 2) return null;

  const at = (iso: string) => new Date(`${iso.slice(0, 10)}T12:00:00`).getTime();
  const t0 = at(history[0][0]);
  const tLast = at(history[history.length - 1][0]);
  const tEnd = Math.max(latestScrapeDate ? at(latestScrapeDate) : tLast, tLast);
  const span = Math.max(tEnd - t0, 1);

  // The seller's own numbers, not the euro conversions. A forint ad's
  // euro figures carry the day's exchange rate on top of the seller's
  // decisions, so a shape drawn from them is tilted by rate drift - and a
  // tooltip that converts them back at TODAY's rate quotes prices the ad
  // never asked (15,9M Ft came out as 14,87M, off by 6,5% of pure
  // exchange rate). Same trap the drop badge already avoids. The euro
  // figure is only the fallback for a point stored without an original.
  const own = (point: (typeof history)[number]) => point[2] || point[1];
  const prices = history.map(own);
  const lo = Math.min(...prices);
  const hi = Math.max(...prices);

  const x = (t: number) => PAD + ((t - t0) / span) * (W - 2 * PAD);
  const y = (p: number) => H - PAD - ((p - lo) / (hi - lo)) * (H - 2 * PAD);

  let d = `M ${x(t0).toFixed(1)} ${y(own(history[0])).toFixed(1)}`;
  for (let i = 1; i < history.length; i++) {
    d += ` H ${x(at(history[i][0])).toFixed(1)} V ${y(own(history[i])).toFixed(1)}`;
  }
  d += ` H ${(W - PAD).toFixed(1)}`;

  const told = history
    .map(([date, eur, original]) => `${money.formatListingAmount(listing, { eur, original })} (${date})`)
    .join(" → ");
  const endY = y(own(history[history.length - 1]));

  return (
    <span className="inline-flex shrink-0 text-muted" title={`Asking price: ${told}`}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
        <path d={d} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={W - PAD} cy={endY} r="1.75" fill="currentColor" />
      </svg>
    </span>
  );
}
