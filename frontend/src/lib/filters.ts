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
  newOnly: boolean; // keep only cars first seen in the latest scrape
  watchlistOnly: boolean;
  dealsOnly: boolean; // keep only cars priced below market for their variant/mileage/age
  fsdOnly: boolean; // keep only cars whose ad says FSD is already on them
  priceDropsOnly: boolean; // keep only cars whose seller has come down since listing
  showTrendLine: boolean;
  showExcluded: boolean;
}

/**
 * One click model for every facet row, whichever way its set is stored.
 *
 * The two storage shapes are historical and stay as they are (an
 * all-selected set means "no country filter"; an EMPTY colour set means "no
 * colour filter"), but from the user's side they now behave identically:
 *
 *   nothing narrowed  -> a click isolates that one value
 *   already narrowed  -> a click adds or removes it
 *   removed the last  -> back to nothing narrowed
 *
 * Before this, clicking a country chip EXCLUDED it while clicking a colour
 * chip INCLUDED it - two opposite meanings behind identical-looking pills,
 * which is what "the colour filter doesn't work" actually was.
 */
export type FacetMode = "all-selected" | "opt-in";

export function isFacetNarrowed(current: Set<string>, options: string[], mode: FacetMode): boolean {
  return mode === "opt-in" ? current.size > 0 : options.some((o) => !current.has(o));
}

export function toggleFacet(
  current: Set<string>,
  value: string,
  options: string[],
  mode: FacetMode,
): Set<string> {
  if (!isFacetNarrowed(current, options, mode)) return new Set([value]);
  const next = new Set(current);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  if (next.size === 0) return mode === "opt-in" ? new Set() : new Set(options);
  return next;
}

/** "Clear this group" - back to the shape that means "no filter here". */
export function clearFacet(options: string[], mode: FacetMode): Set<string> {
  return mode === "opt-in" ? new Set() : new Set(options);
}

export function sellerGroup(sellerType: Listing["sellerType"]): string {
  return sellerType === "private" ? "private" : "dealer";
}

export function registrationYear(listing: Listing): number | null {
  // Read off the string, not through Date. new Date("2023-01-01") is UTC
  // midnight, and a LOCAL getter west of UTC lands on 2022-12-31: every
  // registration date this project stores is a first-of-month, so for an
  // American viewer every car shifted a month back and the January ones a
  // whole year - year filter, palette and deal age alike.
  if (listing.firstRegistration) return Number(listing.firstRegistration.slice(0, 4));
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
    // Every key normalize_variant can produce. A bucket missing here is not
    // "unfiltered" - the filter check treats absence as deselected, so its
    // listings silently vanish from every view.
    variants: new Set(["long_range_awd", "long_range_rwd", "performance", "rwd", "other"]),
    chassisGens: new Set(["legacy", "highland", "juniper", "unknown"]),
    colors: new Set(),
    ...bounds,
    newOnly: false,
    watchlistOnly: false,
    dealsOnly: false,
    fsdOnly: false,
    priceDropsOnly: false,
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
    if (f.fsdOnly && !l.hasFsd) return false;
    return true;
  });
}
