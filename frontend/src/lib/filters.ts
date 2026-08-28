import type { Listing, Model } from "../types";

export const NAMED_COUNTRIES = ["DE", "AT", "HU"] as const;
export const REST_OF_EU = "ROW";

export function countryGroup(country: string): string {
  return (NAMED_COUNTRIES as readonly string[]).includes(country) ? country : REST_OF_EU;
}

export interface FilterState {
  model: Model;
  countries: Set<string>; // DE | AT | HU | ROW
  sources: Set<string>;
  sellerTypes: Set<string>; // "dealer" | "private" (source's "tesla" seller_type counts as dealer)
  variants: Set<string>;
  chassisGens: Set<string>; // includes "unknown" for null
  colors: Set<string>; // includes "unknown" for null
  yearRange: [number, number];
  priceRange: [number, number];
  mileageRange: [number, number];
  highlightNew: boolean;
  watchlistOnly: boolean;
  dealsOnly: boolean; // keep only cars priced below market for their variant/mileage/age
  showTrendLine: boolean;
  showExcluded: boolean;
}

export function sellerGroup(sellerType: Listing["sellerType"]): string {
  return sellerType === "private" ? "private" : "dealer";
}

export function registrationYear(listing: Listing): number | null {
  if (listing.firstRegistration) return new Date(listing.firstRegistration).getFullYear();
  return listing.modelYear;
}

export function dataBounds(listings: Listing[]) {
  const years = listings.map(registrationYear).filter((y): y is number => y !== null);
  const prices = listings.map((l) => l.priceEur);
  const mileages = listings.map((l) => l.mileageKm).filter((m): m is number => m !== null);
  return {
    yearRange: [years.length ? Math.min(...years) : 2018, years.length ? Math.max(...years) : new Date().getFullYear()] as [
      number,
      number,
    ],
    priceRange: [prices.length ? Math.min(...prices) : 0, prices.length ? Math.max(...prices) : 100_000] as [
      number,
      number,
    ],
    mileageRange: [0, mileages.length ? Math.max(...mileages) : 300_000] as [number, number],
  };
}

export function defaultFilterState(listings: Listing[], model: Model): FilterState {
  const bounds = dataBounds(listings.filter((l) => l.model === model));
  return {
    model,
    countries: new Set([...NAMED_COUNTRIES, REST_OF_EU]),
    sources: new Set(Object.keys(SOURCE_KEYS)),
    sellerTypes: new Set(["dealer", "private"]),
    variants: new Set(["long_range_awd", "performance", "rwd", "other"]),
    chassisGens: new Set(["legacy", "highland", "juniper", "unknown"]),
    colors: new Set(),
    ...bounds,
    highlightNew: false,
    watchlistOnly: false,
    dealsOnly: false,
    showTrendLine: true,
    showExcluded: false,
  };
}

// Kept separate from types.ts's SOURCE_LABELS so filters.ts doesn't need
// the display-label map, just the set of valid keys.
const SOURCE_KEYS: Record<string, true> = {
  autoscout24: true,
  kleinanzeigen: true,
  hasznaltauto: true,
  tesla: true,
};

export function applyFilters(listings: Listing[], f: FilterState, watchlist: Set<string>): Listing[] {
  return listings.filter((l) => {
    if (l.model !== f.model) return false;
    if (!f.countries.has(countryGroup(l.country))) return false;
    if (!f.sources.has(l.source)) return false;
    if (!f.sellerTypes.has(sellerGroup(l.sellerType))) return false;
    if (l.variant && !f.variants.has(l.variant)) return false;
    if (!l.variant && !f.variants.has("other")) return false;
    const chassisKey = l.chassisGen ?? "unknown";
    if (!f.chassisGens.has(chassisKey)) return false;
    if (f.colors.size > 0) {
      const colorKey = l.color ?? "unknown";
      if (!f.colors.has(colorKey)) return false;
    }
    const year = registrationYear(l);
    if (year !== null && (year < f.yearRange[0] || year > f.yearRange[1])) return false;
    if (l.priceEur < f.priceRange[0] || l.priceEur > f.priceRange[1]) return false;
    if (l.mileageKm !== null && (l.mileageKm < f.mileageRange[0] || l.mileageKm > f.mileageRange[1])) return false;
    if (f.watchlistOnly && !watchlist.has(l.id)) return false;
    return true;
  });
}
