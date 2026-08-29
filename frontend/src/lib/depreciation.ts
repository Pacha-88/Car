/**
 * Depreciation-by-model-year: mileage-normalized price by age bucket, plus
 * the auto-computed insight cards.
 *
 * TypeScript port of car_tracker/analysis/depreciation.py - see that
 * module's docstring for the reasoning behind the defaults
 * (reference_km=60_000, min_bucket_size=10, whole-year buckets capped at a
 * "Nyr_plus" catch-all). Keep the two in sync if the method changes.
 *
 * Known gap, not solved here: no "new list price" reference point or
 * "versus buying new" card - both need Tesla's new-car pricing, which none
 * of the four sources (all used-listing sources) provide.
 */

import { type Point, linearSlope, median } from "./trend";

export interface DepreciationInput {
  firstRegistration: Date;
  mileageKm: number;
  priceEur: number;
}

export interface DepreciationBucket {
  label: string;
  bucketIndex: number;
  n: number;
  medianPriceEur: number;
  isThin: boolean;
  /** Interquartile range of the normalized prices - the chart's spread
   * band. For n=1 both collapse to the single price (a zero-width band
   * draws as no band, which is honest for a bucket that thin). */
  p25PriceEur: number;
  p75PriceEur: number;
}

/** Quartiles matching Python's statistics.quantiles(n=4, method="inclusive")
 * so the port stays numerically in step with analysis/depreciation.py. */
function iqr(sortedAsc: number[]): [number, number] {
  const n = sortedAsc.length;
  if (n < 2) return [sortedAsc[0], sortedAsc[0]];
  const at = (p: number) => {
    const pos = (n - 1) * p;
    const lo = Math.floor(pos);
    const frac = pos - lo;
    return lo + 1 < n ? sortedAsc[lo] * (1 - frac) + sortedAsc[lo + 1] * frac : sortedAsc[lo];
  };
  return [at(0.25), at(0.75)];
}

export function ageInYears(firstRegistration: Date, asOf: Date): number {
  const msPerDay = 1000 * 60 * 60 * 24;
  return (asOf.getTime() - firstRegistration.getTime()) / msPerDay / 365.25;
}

export function ageBucketIndex(ageYears: number, maxBucket = 7): number {
  // Clamped below at 0: a slightly future-dated registration (the
  // plausibility guard deliberately allows one day of slack for
  // month-granularity sources and a UTC runner) has a negative age, and
  // Math.floor would give it bucket -1 - which ageBucketLabel renders as a
  // literal "-1yr", a bucket that was never designed to exist. A car
  // registered "tomorrow" is an under-1-year car. (The Python prototype
  // agreed by accident: int() truncates toward zero.)
  return Math.min(Math.max(Math.floor(ageYears), 0), maxBucket);
}

export function ageBucketLabel(bucketIndex: number, maxBucket = 7): string {
  if (bucketIndex === 0) return "under_1yr";
  if (bucketIndex >= maxBucket) return `${maxBucket}yr_plus`;
  return `${bucketIndex}yr`;
}

export function normalizePrice(
  priceEur: number,
  mileageKm: number,
  referenceKm: number,
  slopeEurPerKm: number,
): number {
  return priceEur + slopeEurPerKm * (referenceKm - mileageKm);
}

export function computeDepreciationCurve(
  listings: DepreciationInput[],
  asOf: Date,
  { referenceKm = 60_000, minBucketSize = 10, maxBucket = 7 } = {},
): DepreciationBucket[] {
  if (listings.length < 2) return [];

  const points: Point[] = listings.map((l) => [l.mileageKm, l.priceEur]);
  const { slope } = linearSlope(points);

  const byBucket = new Map<number, number[]>();
  for (const listing of listings) {
    const bucketIndex = ageBucketIndex(ageInYears(listing.firstRegistration, asOf), maxBucket);
    const adjusted = normalizePrice(listing.priceEur, listing.mileageKm, referenceKm, slope);
    const bucket = byBucket.get(bucketIndex);
    if (bucket) bucket.push(adjusted);
    else byBucket.set(bucketIndex, [adjusted]);
  }

  return [...byBucket.entries()]
    .sort(([a], [b]) => a - b)
    .map(([bucketIndex, prices]) => {
      const sorted = [...prices].sort((a, b) => a - b);
      const [p25, p75] = iqr(sorted);
      return {
        label: ageBucketLabel(bucketIndex, maxBucket),
        bucketIndex,
        n: prices.length,
        medianPriceEur: median(prices),
        isThin: prices.length < minBucketSize,
        p25PriceEur: p25,
        p75PriceEur: p75,
      };
    });
}

export interface BucketTransition {
  fromLabel: string;
  toLabel: string;
  deltaEur: number; // negative = price dropped
}

export function bucketTransitions(buckets: DepreciationBucket[]): BucketTransition[] {
  const usable = buckets.filter((b) => !b.isThin).sort((a, b) => a.bucketIndex - b.bucketIndex);
  const transitions: BucketTransition[] = [];
  for (let i = 1; i < usable.length; i++) {
    transitions.push({
      fromLabel: usable[i - 1].label,
      toLabel: usable[i].label,
      deltaEur: usable[i].medianPriceEur - usable[i - 1].medianPriceEur,
    });
  }
  return transitions;
}

export function steepestDrop(transitions: BucketTransition[]): BucketTransition | null {
  if (transitions.length === 0) return null;
  return transitions.reduce((min, t) => (t.deltaEur < min.deltaEur ? t : min));
}

export function curveFlattensAt(transitions: BucketTransition[]): BucketTransition | null {
  if (transitions.length === 0) return null;
  return transitions.reduce((max, t) => (t.deltaEur > max.deltaEur ? t : max));
}

export interface CheapestToOwn {
  buyAtLabel: string;
  buyPriceEur: number;
  annualCostEur: number;
  horizonYears: number;
}

export function cheapestToOwn(buckets: DepreciationBucket[], horizonYears = 3): CheapestToOwn | null {
  const usable = new Map(buckets.filter((b) => !b.isThin).map((b) => [b.bucketIndex, b]));
  const horizonBucket = usable.get(horizonYears);
  if (!horizonBucket) return null;

  let best: { bucket: DepreciationBucket; annualCost: number } | null = null;
  for (const [bucketIndex, bucket] of usable) {
    if (bucketIndex >= horizonYears) continue;
    const annualCost = (bucket.medianPriceEur - horizonBucket.medianPriceEur) / (horizonYears - bucketIndex);
    if (!best || annualCost < best.annualCost) best = { bucket, annualCost };
  }
  if (!best) return null;

  return {
    buyAtLabel: best.bucket.label,
    buyPriceEur: best.bucket.medianPriceEur,
    annualCostEur: best.annualCost,
    horizonYears,
  };
}
