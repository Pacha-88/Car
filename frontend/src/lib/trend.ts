/**
 * Price-vs-mileage trend: a smoothed curve for the scatter chart, and a
 * single linear rate (EUR per km) for the "price per 10k km" stat tile and
 * for mileage-normalizing prices in the depreciation module.
 *
 * TypeScript port of car_tracker/analysis/trend.py - same algorithm,
 * same reasoning (binned median over LOESS/polynomial: no extra
 * dependency, robust to outlier listings, computed client-side so it can
 * re-run on every filter change without a server round-trip). Keep the two
 * in sync if the method changes on one side.
 */

export type Point = [mileageKm: number, priceEur: number];

export function binnedMedianTrend(points: Point[], binWidthKm = 10_000): Point[] {
  const bins = new Map<number, number[]>();
  for (const [km, price] of points) {
    const binIndex = Math.floor(km / binWidthKm);
    const bucket = bins.get(binIndex);
    if (bucket) bucket.push(price);
    else bins.set(binIndex, [price]);
  }
  return [...bins.entries()]
    .sort(([a], [b]) => a - b)
    .map(([binIndex, prices]) => [binIndex * binWidthKm + binWidthKm / 2, median(prices)]);
}

export function linearSlope(points: Point[]): { slope: number; intercept: number } {
  const n = points.length;
  if (n < 2) throw new Error("need at least 2 points for a linear fit");

  let sumX = 0;
  let sumY = 0;
  let sumXX = 0;
  let sumXY = 0;
  for (const [x, y] of points) {
    sumX += x;
    sumY += y;
    sumXX += x * x;
    sumXY += x * y;
  }

  const denominator = n * sumXX - sumX * sumX;
  if (denominator === 0) throw new Error("all points share the same mileage, cannot fit a slope");

  const slope = (n * sumXY - sumX * sumY) / denominator;
  const intercept = (sumY - slope * sumX) / n;
  return { slope, intercept };
}

export function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}
