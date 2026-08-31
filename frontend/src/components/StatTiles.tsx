import { median } from "../lib/trend";
import { formatKm, formatNumber } from "../lib/format";
import { formatMoney } from "../lib/money";
import { useMoney } from "../lib/moneyContext";
import type { Listing } from "../types";

interface StatTilesProps {
  listings: Listing[];
  eurPer10kKm: number | null;
}

function Tile({ value, label, hint, sub }: { value: string; label: string; hint?: string; sub?: string | null }) {
  return (
    <div title={hint} className="bg-surface-1 px-3 pb-3 pt-2.5 sm:px-4">
      <div className="eyebrow mb-2">{label}</div>
      {/* These four numbers are the page's own headline, and at card-title
          size they read as one more label - size carries the hierarchy so
          colour does not have to. Two constraints bound it: nowrap is
          non-negotiable (a price on two lines is worse than a smaller one),
          and the strip's overflow-hidden turns any excess into a SILENT
          clip. Measured, not assumed: a fixed 19px rendered "12,77 millió
          F" with the t gone at 375px, and the old sm:grid-cols-4 sliced up
          to 90px off the same number at 640-1024. Hence the clamp on
          phones, and the four-across layout waiting for xl (the strip is
          2x2 on tablets), where a quarter tile genuinely fits 30px money. */}
      <div className="numeral whitespace-nowrap text-[clamp(12px,4.4vw,19px)] font-semibold leading-none tracking-tight text-primary sm:text-[26px] xl:text-[30px]">
        {value}
      </div>
      {/* Reserved even when empty, so the four baselines stay level - one
          taller tile would make the strip read as four separate cards. */}
      <div className="numeral mt-1.5 h-[13px] text-[11px] leading-none text-muted">{sub}</div>
    </div>
  );
}

export function StatTiles({ listings, eurPer10kKm }: StatTilesProps) {
  const money = useMoney();
  const prices = listings.map((l) => l.priceEur);
  const mileages = listings.map((l) => l.mileageKm).filter((m): m is number => m !== null);

  // The same median in the OTHER currency, small, under the big number.
  // The reader thinks in forints while the market prices in euros (or the
  // reverse, one toggle later) - both figures already live in the payload,
  // and showing the pair saves the one mental conversion this page is
  // otherwise constantly asking for. "≈" because the pair is only as exact
  // as the stored daily rate.
  const other: "EUR" | "HUF" = money.currency === "HUF" ? "EUR" : "HUF";
  const counterMedian =
    prices.length && money.hufPerEur !== null ? `≈ ${formatMoney(median(prices), other, money.hufPerEur)}` : null;

  return (
    // One strip rather than four floating cards: the hairline gaps are the
    // container's own background showing through, so the measures read as
    // one summary of the current selection.
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border shadow-[var(--shadow-1)] xl:grid-cols-4">
      <Tile value={formatNumber(listings.length)} label="Listings" hint="Cars matching the filters below" />
      <Tile value={prices.length ? money.format(median(prices)) : "—"} label="Median price" sub={counterMedian} />
      <Tile value={mileages.length ? formatKm(median(mileages)) : "—"} label="Median mileage" />
      <Tile
        value={eurPer10kKm !== null ? money.formatSigned(eurPer10kKm) : "—"}
        label="Per 10k km"
        hint="How much the asking price moves per 10.000 km, fit across the current selection"
      />
    </div>
  );
}
