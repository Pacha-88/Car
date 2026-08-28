/**
 * Deal score: how a listing's asking price compares to the market for a
 * genuinely similar car, so real bargains surface instead of just cheap-
 * because-old ones.
 *
 * For each variant separately (a Performance shouldn't read as "expensive"
 * just for being a Performance), we fit a plane
 *
 *     price ≈ a + b·mileage + c·age
 *
 * by ordinary least squares, then score each listing by how far its actual
 * price sits below or above what that plane predicts for its own mileage
 * and age. Both axes a buyer already reasons about are thus controlled for:
 * a low price only counts as a deal once mileage and age are accounted for.
 *
 * The baseline is fit over the whole current model's listings, not the
 * filtered subset, so a car's score doesn't drift as you move the filters.
 *
 * Thresholds (share below the predicted price) are deliberate defaults, easy
 * to retune: a car ~15%+ under its predicted price is a strong signal, ~7%
 * a mild one. Fits need a minimum sample or they overreact to noise; a
 * variant with too few comparable listings simply gets no score rather than
 * a made-up one.
 */

import { registrationYear } from "./filters";
import type { Listing } from "../types";

export type DealTier = "great" | "good" | "fair" | "above";

export interface DealInfo {
  expectedEur: number;
  deltaEur: number; // actual − expected; negative = below market = good
  pct: number; // deltaEur / expected
  tier: DealTier;
}

const MIN_FIT = 12; // fewer comparable cars than this → no score for that variant
const GREAT = -0.15;
const GOOD = -0.07;
const ABOVE = 0.07;

// Data-quality guards. Marketplaces carry placeholder/deposit listings
// ("1 €", a car with a digit missing) - these are not deals, they're
// errors, and left in they both top the "best deals" sort and drag the
// fitted plane down for every real car. So a price below a plausible floor
// is excluded from the fit and never scored, and a price that comes out
// more than this far under its predicted value is treated as an anomaly
// (a genuine bargain simply isn't 55% below the market for its peers).
const MIN_PLAUSIBLE_EUR = 3000;
const ANOMALY_FLOOR = -0.55;

export const DEAL_TIER_LABEL: Record<DealTier, string> = {
  great: "Great deal",
  good: "Good deal",
  fair: "Fair price",
  above: "Above market",
};

export const DEAL_TIER_COLOR: Record<DealTier, string> = {
  great: "var(--status-good)",
  good: "var(--status-good)",
  fair: "var(--text-muted)",
  above: "var(--status-warning)",
};

function ageYears(listing: Listing, asOf: Date): number | null {
  if (listing.firstRegistration) {
    const ms = asOf.getTime() - new Date(listing.firstRegistration).getTime();
    return ms / (1000 * 60 * 60 * 24 * 365.25);
  }
  const year = registrationYear(listing);
  return year === null ? null : asOf.getFullYear() - year;
}

interface Row {
  mileage: number;
  age: number;
  price: number;
}

/** Solve a 3×3 system by Gaussian elimination with partial pivoting.
 * Returns null when the matrix is singular (degenerate data). */
function solve3(a: number[][], b: number[]): number[] | null {
  const m = a.map((row, i) => [...row, b[i]]);
  for (let col = 0; col < 3; col++) {
    let pivot = col;
    for (let r = col + 1; r < 3; r++) if (Math.abs(m[r][col]) > Math.abs(m[pivot][col])) pivot = r;
    if (Math.abs(m[pivot][col]) < 1e-9) return null;
    [m[col], m[pivot]] = [m[pivot], m[col]];
    for (let r = 0; r < 3; r++) {
      if (r === col) continue;
      const factor = m[r][col] / m[col][col];
      for (let c = col; c < 4; c++) m[r][c] -= factor * m[col][c];
    }
  }
  return [m[0][3] / m[0][0], m[1][3] / m[1][1], m[2][3] / m[2][2]];
}

/** OLS fit of price ≈ a + b·mileage + c·age. null if underdetermined. */
function fitPlane(rows: Row[]): ((mileage: number, age: number) => number) | null {
  if (rows.length < MIN_FIT) return null;
  // Normal equations XᵀX · β = Xᵀy for X = [1, mileage, age].
  let s1 = 0;
  let sM = 0;
  let sA = 0;
  let sMM = 0;
  let sAA = 0;
  let sMA = 0;
  let sY = 0;
  let sMY = 0;
  let sAY = 0;
  for (const { mileage, age, price } of rows) {
    s1 += 1;
    sM += mileage;
    sA += age;
    sMM += mileage * mileage;
    sAA += age * age;
    sMA += mileage * age;
    sY += price;
    sMY += mileage * price;
    sAY += age * price;
  }
  const beta = solve3(
    [
      [s1, sM, sA],
      [sM, sMM, sMA],
      [sA, sMA, sAA],
    ],
    [sY, sMY, sAY],
  );
  if (!beta) return null;
  const [a, b, c] = beta;
  return (mileage, age) => a + b * mileage + c * age;
}

function tierFor(pct: number): DealTier {
  if (pct <= GREAT) return "great";
  if (pct <= GOOD) return "good";
  if (pct <= ABOVE) return "fair";
  return "above";
}

/** Deal info per listing id. A listing is scored only when its variant had
 * enough comparable cars to fit a stable market plane and its own mileage
 * and age are known. */
export function computeDealScores(listings: Listing[], asOf: Date = new Date()): Map<string, DealInfo> {
  const byVariant = new Map<string, { listing: Listing; row: Row }[]>();
  for (const listing of listings) {
    const age = ageYears(listing, asOf);
    if (listing.mileageKm === null || age === null) continue;
    if (listing.priceEur < MIN_PLAUSIBLE_EUR) continue; // placeholder/deposit, not a car
    const key = listing.variant ?? "other";
    const row: Row = { mileage: listing.mileageKm, age, price: listing.priceEur };
    const group = byVariant.get(key);
    if (group) group.push({ listing, row });
    else byVariant.set(key, [{ listing, row }]);
  }

  const scores = new Map<string, DealInfo>();
  for (const group of byVariant.values()) {
    const predict = fitPlane(group.map((g) => g.row));
    if (!predict) continue;
    for (const { listing, row } of group) {
      const expected = predict(row.mileage, row.age);
      if (expected <= 0) continue; // implausible fit for this point; skip it
      const deltaEur = listing.priceEur - expected;
      const pct = deltaEur / expected;
      if (pct < ANOMALY_FLOOR) continue; // "too good" to be real - a data error, not a deal
      scores.set(listing.id, { expectedEur: expected, deltaEur, pct, tier: tierFor(pct) });
    }
  }
  return scores;
}
