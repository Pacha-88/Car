export type Model = "model_y" | "model_3";
export type ChassisGen = "legacy" | "highland" | "juniper" | null;
export type Variant = "long_range_awd" | "long_range_rwd" | "performance" | "rwd" | "other" | null;
export type SellerType = "dealer" | "private" | "tesla" | null;

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
  mileageKm: number | null;
  daysAtCurrentPrice: number;
  isNew: boolean;
}

export interface ExportPayload {
  generatedAt: string;
  latestScrapeDate: string | null;
  /** Forints per euro at the last scrape. null until a run has stored a
   * rate, in which case the dashboard stays in euros rather than guessing. */
  hufPerEur: number | null;
  listings: Listing[];
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
