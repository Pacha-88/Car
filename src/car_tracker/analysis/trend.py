"""Price-vs-mileage trend: a smoothed curve for the scatter chart, and a
single linear rate (€ per km) for the "price per 10k km" stat tile and for
mileage-normalizing prices in the depreciation module.

Deliberately not LOESS/polynomial regression: those need either a stats
dependency (statsmodels) or careful tuning to avoid overfitting at the
sparse ends of the mileage range, for a "reasonable default, refine later"
first pass. A binned median is simple, needs no dependency beyond the
stdlib, and is robust to the outlier listings every one of these sources
has (badly-priced or mis-described cars).
"""

from __future__ import annotations

from collections import defaultdict
from statistics import median

Point = tuple[float, float]  # (mileage_km, price_eur)


def binned_median_trend(points: list[Point], *, bin_width_km: float = 10_000) -> list[Point]:
    """One (bin_center_km, median_price_eur) point per non-empty mileage bin,
    ordered by mileage — meant to be rendered as a connected line."""
    bins: dict[int, list[float]] = defaultdict(list)
    for km, price in points:
        bins[int(km // bin_width_km)].append(price)
    return [(bin_index * bin_width_km + bin_width_km / 2, median(prices)) for bin_index, prices in sorted(bins.items())]


def linear_slope(points: list[Point]) -> tuple[float, float]:
    """Least-squares (mileage_km -> price_eur) slope and intercept.

    A plain closed-form OLS fit — no dependency needed for two numbers.
    Expected to come out negative (price falls as mileage rises); used as
    a single global rate, not as the trend line itself.
    """
    n = len(points)
    if n < 2:
        raise ValueError("need at least 2 points for a linear fit")

    sum_x = sum(x for x, _ in points)
    sum_y = sum(y for _, y in points)
    sum_xx = sum(x * x for x, _ in points)
    sum_xy = sum(x * y for x, y in points)

    denominator = n * sum_xx - sum_x * sum_x
    if denominator == 0:
        raise ValueError("all points share the same mileage, cannot fit a slope")

    slope = (n * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / n
    return slope, intercept
