export type Model = "model_y" | "model_3";
export type ChassisGen = "legacy" | "highland" | "juniper" | null;
export type Variant = "long_range_awd" | "long_range_rwd" | "performance" | "rwd" | "other" | null;
export type SellerType = "dealer" | "private" | "tesla" | null;

/** [ISO date, price in EUR, price in the seller's own currency] */
export type PricePoint = [string, number, number];

export interface Listing {
  id: string;
  source: string;
  model: Model;
  chassisGen: ChassisGen;
  variant: Variant;
  country: string;
  modelYear: number | null;
  firstRegistration: string | null; // ISO date
  url: string;
  titleRaw: string | null;
  photoUrls: string[];
  sellerType: SellerType;
  location: string | null;
  powerKw: number | null;
  color: string | null;
  firstSeenAt: string; // ISO datetime
  priceEur: number;
  /** What the ad itself says, in the currency it says it in. Optional: an
   * export written before this field existed simply has no original. */
  priceOriginal?: number | null;
  currencyOriginal?: string | null;
  mileageKm: number | null;
  daysAtCurrentPrice: number;
  isNew: boolean;
  /** One entry per price the seller actually set: [ISO date, EUR, original].
   * A car listed a month has thirty snapshots behind it and usually one
   * entry here. Optional - an export written before this has none. */
  priceHistory?: PricePoint[] | null;
  /** The ad says Full Self-Driving is already on the car - not Autopilot,
   * not Enhanced Autopilot, and not rented by the month. */
  hasFsd?: boolean;
}

export interface ExportPayload {
  generatedAt: string;
  latestScrapeDate: string | null;
  /** The same moment to the second, UTC-marked ("...Z"). Optional - an
   * export written before this field has only the date. */
  latestScrapeAt?: string | null;
  /** Per-source versions of the same moment - the headline stamp is the
   * newest of ANY source, which overstates the two home-run-only sites. */
  sourceScrapedAt?: Record<string, string> | null;
  /** Forints per euro at the last scrape. null until a run has stored a
   * rate, in which case the dashboard stays in euros rather than guessing. */
  hufPerEur: number | null;
  /** The market's own movement, one row per day per model, oldest first. */
  marketHistory?: MarketDay[] | null;
  /** Median days a car sits before its ad disappears - only sales whose
   * arrival was witnessed too, so the numbers start empty and every one
   * has a true span. variant null = the whole model together. */
  saleTimes?: SaleTime[] | null;
  listings: Listing[];
}

export interface SaleTime {
  model: Model;
  variant: string | null;
  medianDays: number;
  n: number;
}

export interface MarketDay {
  date: string; // ISO date
  model: Model;
  medianEur: number;
  p25Eur: number;
  p75Eur: number;
  /** Cars believed on sale that day - between two scrapes of its source a
   * car keeps its last asked price, so sources on different cadences
   * cannot sawtooth the median. */
  n: number;
  /** 100 on the first day, moved only by the price changes of cars listed
   * on both that day and the one before. Unlike the median, it cannot be
   * moved by cheap cars arriving or expensive ones selling. */
  index: number;
  /** How many cars backed the step into this day. Zero means the index was
   * HELD for want of overlap, not that these cars sat still - a window of
   * nothing but zeroes has no measurement in it, however flat it looks.
   * Optional: an export written before this field has none. */
  matchedPairs?: number;
}

export const SOURCE_LABELS: Record<string, string> = {
  autoscout24: "AutoScout24",
  kleinanzeigen: "Kleinanzeigen",
  hasznaltauto: "Használtautó.hu",
  tesla: "Tesla.com",
};

// Fixed order/hue per source - never re-assigned based on which sources are
// present in a given filter slice (dataviz skill: "color follows the
// entity, never its rank").
export const SOURCE_COLOR_VAR: Record<string, string> = {
  autoscout24: "var(--series-1)",
  kleinanzeigen: "var(--series-2)",
  hasznaltauto: "var(--series-3)",
  tesla: "var(--series-4)",
};

export const VARIANT_LABELS: Record<string, string> = {
  long_range_awd: "Long Range AWD",
  long_range_rwd: "Long Range RWD",
  performance: "Performance",
  rwd: "RWD",
  other: "Other",
};

export const MODEL_LABELS: Record<string, string> = {
  model_3: "Tesla Model 3",
  model_y: "Tesla Model Y",
};

/** What to show when an ad carries no words of its own. The backend already
 * guarantees a title, so this only catches rows stored before it did - but a
 * card reading "Untitled" is exactly what that guarantee exists to prevent,
 * and those rows are only repaired when the site serves them again. */
export function listingTitle(listing: { titleRaw: string | null; model: string }): string {
  return listing.titleRaw?.trim() || MODEL_LABELS[listing.model] || "Tesla";
}

export const CHASSIS_LABELS: Record<string, string> = {
  legacy: "Legacy",
  highland: "Highland",
  juniper: "Juniper",
};
