import { median } from "../lib/trend";
import { formatKm, formatNumber } from "../lib/format";
import { useMoney } from "../lib/moneyContext";
import type { Listing } from "../types";

interface StatTilesProps {
  listings: Listing[];
  eurPer10kKm: number | null;
}

function Tile({ value, label, hint }: { value: string; label: string; hint?: string }) {
  return (
    <div title={hint} className="bg-surface-1 px-4 pb-3 pt-2.5">
      <div className="eyebrow mb-2">{label}</div>
      {/* 26px from sm up, not 19: these four numbers are the page's own
          headline, and at card-title size they read as one more label. Size
          carries the hierarchy so colour does not have to. On a phone the
          tile is half the screen and 26px broke "12,77 millió Ft" onto two
          lines - there the numeral keeps its old size, whole. */}
      <div className="numeral whitespace-nowrap text-[19px] font-semibold leading-none tracking-tight text-primary sm:text-[26px]">
        {value}
      </div>
    </div>
  );
}

export function StatTiles({ listings, eurPer10kKm }: StatTilesProps) {
  const money = useMoney();
  const prices = listings.map((l) => l.priceEur);
  const mileages = listings.map((l) => l.mileageKm).filter((m): m is number => m !== null);

  return (
    // One strip rather than four floating cards: the hairline gaps are the
    // container's own background showing through, so the measures read as
    // one summary of the current selection.
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border shadow-[var(--shadow-1)] sm:grid-cols-4">
      <Tile value={formatNumber(listings.length)} label="Listings" hint="Cars matching the filters below" />
      <Tile value={prices.length ? money.format(median(prices)) : "—"} label="Median price" />
      <Tile value={mileages.length ? formatKm(median(mileages)) : "—"} label="Median mileage" />
      <Tile
        value={eurPer10kKm !== null ? money.formatSigned(eurPer10kKm) : "—"}
        label="Per 10k km"
        hint="How much the asking price moves per 10.000 km, fit across the current selection"
      />
    </div>
  );
}
