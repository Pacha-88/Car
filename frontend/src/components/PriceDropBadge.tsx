import { useMoney } from "../lib/moneyContext";
import { isPriceDrop, priceChange } from "../lib/priceHistory";
import type { Listing } from "../types";

/**
 * What this seller has done with their own price since the ad went up.
 *
 * Shown only when they came down, and only by enough to mean something -
 * a card has to earn its space, and "−200 EUR" on a 40.000 EUR car is
 * noise. A seller who has cut twice is saying something a seller who cut
 * once is not, so the count is there when there is one.
 */
export function PriceDropBadge({ listing, compact = false }: { listing: Listing; compact?: boolean }) {
  const money = useMoney();
  const change = priceChange(listing);
  if (!isPriceDrop(change) || !change) return null;

  const pct = Math.round(Math.abs(change.pct) * 100);
  const amount = money.formatListingAmount(listing, { eur: change.deltaEur, original: change.deltaOriginal });
  // Converted the same way the amount above it is, so the tooltip and the
  // badge are in one unit. `change.firstEur` is the euro figure at the rate
  // of the day the ad went up, which for a forint ad is a different euro
  // from the one the card is priced in today - quoting it here would put
  // two exchange rates on one card and stop the arithmetic closing.
  const asked = money.formatListingAmount(listing, { eur: change.firstEur, original: change.firstOriginal });
  const title =
    `Asked ${asked} when it was listed · ${change.changes} price change${change.changes === 1 ? "" : "s"}` +
    ` · at this price since ${change.since}`;

  return (
    <span
      title={title}
      className={`numeral inline-flex shrink-0 items-center gap-1 rounded-md bg-status-good/15 font-semibold text-status-good ${
        compact ? "px-1 py-px text-[10px]" : "px-1.5 py-0.5 text-[11px]"
      }`}
    >
      <span aria-hidden>▼</span>
      {pct}%
      <span className="opacity-65">·</span>
      <span className="opacity-80">{amount}</span>
      {change.changes > 1 && !compact && (
        <>
          <span className="opacity-65">·</span>
          <span className="opacity-80">{change.changes}×</span>
        </>
      )}
    </span>
  );
}
