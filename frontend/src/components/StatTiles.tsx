import { median } from "../lib/trend";
import { formatKm, formatNumber } from "../lib/format";
import { useMoney } from "../lib/moneyContext";
import type { Listing } from "../types";

interface StatTilesProps {
  listings: Listing[];
  eurPer10kKm: number | null;
}

function Tile({ value, label }: { value: string; label: string }) {
  return (
    <div className="text-right">
      <div className="text-lg font-semibold text-primary tabular">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
    </div>
  );
}

export function StatTiles({ listings, eurPer10kKm }: StatTilesProps) {
  const money = useMoney();
  const prices = listings.map((l) => l.priceEur);
  const mileages = listings.map((l) => l.mileageKm).filter((m): m is number => m !== null);

  return (
    <div className="flex flex-wrap items-start gap-6">
      <Tile value={formatNumber(listings.length)} label="Listings" />
      <Tile value={prices.length ? money.format(median(prices)) : "—"} label="Median price" />
      <Tile value={mileages.length ? formatKm(median(mileages)) : "—"} label="Median mileage" />
      <Tile value={eurPer10kKm !== null ? money.formatSigned(eurPer10kKm) : "—"} label="Per 10k km" />
    </div>
  );
}
