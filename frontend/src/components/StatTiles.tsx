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
    <div title={hint} className="bg-surface-1 px-4 py-2.5">
      <div className="eyebrow mb-1.5">{label}</div>
      <div className="numeral text-[19px] font-semibold leading-none text-primary">{value}</div>
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
