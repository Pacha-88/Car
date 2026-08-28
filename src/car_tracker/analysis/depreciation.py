"""Depreciation-by-model-year: mileage-normalized price by age bucket, plus
the auto-computed insight cards from DASHBOARD_SPEC.md.

Reasonable defaults chosen for a first pass, all easy to override per call:
- `reference_km=60_000` and `min_bucket_size=10` match the numbers seen in
  the reference screenshots (the "thin" cutoff there was implicit —
  n=3/n=9 got excluded, n=57 didn't — 10 is a round number in that gap).
- Age buckets are whole years (0 = "under 1yr", 1 = "1yr", ...), capped at
  `max_bucket` with a catch-all "Nyr_plus" bucket, since sample size trails
  off for old cars and finer buckets there would mostly be thin anyway.

Known gap, not solved here: there's no "new list price" reference point
(DASHBOARD_SPEC's "new list price" column and "versus buying new" insight
card both need Tesla's *new*-car pricing, which none of the four sources —
all used-listing sources — provide). Both are left out rather than faked
with a stand-in.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import median, quantiles

from car_tracker.analysis.trend import Point, linear_slope

# (first_registration, mileage_km, price_eur) - one tuple per listing.
DepreciationInput = tuple[date, int, float]


def age_in_years(first_registration: date, *, as_of: date) -> float:
    return (as_of - first_registration).days / 365.25


def age_bucket_index(age_years: float, *, max_bucket: int = 7) -> int:
    """0 = under 1yr, 1 = 1yr, ..., max_bucket = the max_bucket+ catch-all."""
    return min(int(age_years), max_bucket)


def age_bucket_label(bucket_index: int, *, max_bucket: int = 7) -> str:
    if bucket_index == 0:
        return "under_1yr"
    if bucket_index >= max_bucket:
        return f"{max_bucket}yr_plus"
    return f"{bucket_index}yr"


def normalize_price(price_eur: float, mileage_km: float, *, reference_km: float, slope_eur_per_km: float) -> float:
    """Shift `price_eur` to what it would "be" at `reference_km`, using a
    single global €/km rate rather than each listing's own trajectory
    (there isn't one — this is cross-sectional, one snapshot per car)."""
    return price_eur + slope_eur_per_km * (reference_km - mileage_km)


@dataclass(frozen=True)
class DepreciationBucket:
    label: str
    bucket_index: int
    n: int
    median_price_eur: float
    is_thin: bool
    # Interquartile range of the normalized prices - the chart's spread
    # band. For n=1 both collapse to the single price (quartiles of one
    # point aren't defined; a zero-width band draws as no band, which is
    # honest for a bucket that thin).
    p25_price_eur: float
    p75_price_eur: float


def _iqr(prices: list[float]) -> tuple[float, float]:
    if len(prices) < 2:
        return prices[0], prices[0]
    q = quantiles(prices, n=4, method="inclusive")
    return q[0], q[2]


def compute_depreciation_curve(
    listings: list[DepreciationInput],
    *,
    as_of: date,
    reference_km: float = 60_000,
    min_bucket_size: int = 10,
    max_bucket: int = 7,
) -> list[DepreciationBucket]:
    if len(listings) < 2:
        raise ValueError("need at least 2 listings to fit the mileage-normalization slope")

    slope, _ = linear_slope([(km, price) for _, km, price in listings])

    by_bucket: dict[int, list[float]] = defaultdict(list)
    for first_registration, mileage_km, price_eur in listings:
        bucket_index = age_bucket_index(age_in_years(first_registration, as_of=as_of), max_bucket=max_bucket)
        adjusted = normalize_price(price_eur, mileage_km, reference_km=reference_km, slope_eur_per_km=slope)
        by_bucket[bucket_index].append(adjusted)

    buckets = []
    for bucket_index, prices in sorted(by_bucket.items()):
        p25, p75 = _iqr(prices)
        buckets.append(
            DepreciationBucket(
                label=age_bucket_label(bucket_index, max_bucket=max_bucket),
                bucket_index=bucket_index,
                n=len(prices),
                median_price_eur=median(prices),
                is_thin=len(prices) < min_bucket_size,
                p25_price_eur=p25,
                p75_price_eur=p75,
            )
        )
    return buckets


@dataclass(frozen=True)
class BucketTransition:
    from_label: str
    to_label: str
    delta_eur: float  # negative = price dropped from from_label to to_label


def bucket_transitions(buckets: list[DepreciationBucket]) -> list[BucketTransition]:
    """Year-over-year deltas between consecutive non-thin buckets, in age order."""
    usable = sorted((b for b in buckets if not b.is_thin), key=lambda b: b.bucket_index)
    return [
        BucketTransition(prev.label, curr.label, curr.median_price_eur - prev.median_price_eur)
        for prev, curr in zip(usable, usable[1:])
    ]


def steepest_drop(transitions: list[BucketTransition]) -> BucketTransition | None:
    return min(transitions, key=lambda t: t.delta_eur) if transitions else None


def curve_flattens_at(transitions: list[BucketTransition]) -> BucketTransition | None:
    """The transition with the smallest price drop (or, if it happens, a rise)."""
    return max(transitions, key=lambda t: t.delta_eur) if transitions else None


@dataclass(frozen=True)
class CheapestToOwn:
    buy_at_label: str
    buy_price_eur: float
    annual_cost_eur: float
    horizon_years: int


def cheapest_to_own(buckets: list[DepreciationBucket], *, horizon_years: int = 3) -> CheapestToOwn | None:
    """Cheapest entry age for a fixed `horizon_years`-year ownership window
    ending at the `horizon_years` bucket: for each earlier non-thin bucket,
    the annualized cost is (buy-in price - price at the horizon) / years
    held. Returns whichever entry age minimizes that. None if there's no
    usable data at the horizon bucket itself, or no earlier bucket to
    compare against.
    """
    usable = {b.bucket_index: b for b in buckets if not b.is_thin}
    if horizon_years not in usable:
        return None

    horizon_price = usable[horizon_years].median_price_eur
    best: tuple[DepreciationBucket, float] | None = None
    for bucket_index, bucket in usable.items():
        if bucket_index >= horizon_years:
            continue
        annual_cost = (bucket.median_price_eur - horizon_price) / (horizon_years - bucket_index)
        if best is None or annual_cost < best[1]:
            best = (bucket, annual_cost)

    if best is None:
        return None
    bucket, annual_cost = best
    return CheapestToOwn(
        buy_at_label=bucket.label,
        buy_price_eur=bucket.median_price_eur,
        annual_cost_eur=annual_cost,
        horizon_years=horizon_years,
    )
