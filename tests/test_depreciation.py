from datetime import date

import pytest

from statistics import median as statistics_median

from car_tracker.analysis.depreciation import (
    DepreciationInput,
    age_bucket_index,
    age_bucket_label,
    age_in_years,
    bucket_transitions,
    cheapest_to_own,
    compute_depreciation_curve,
    curve_flattens_at,
    normalize_price,
    steepest_drop,
)
from car_tracker.analysis.trend import linear_slope

AS_OF = date(2026, 1, 1)

# One synthetic (first_registration, mileage_km, price_eur) per bucket-year,
# 12 listings each (>= the default min_bucket_size=10) so none are thin,
# plus a 5-listing "4yr" bucket that should come out thin. Price is held
# constant within a bucket while mileage varies 55_000..66_000 (median
# 60_500 for the 12-listing buckets) - this does NOT make the fitted
# mileage slope exactly 0: the pooled dataset still has a small real
# correlation (the thin bucket's low price is concentrated at the low end
# of that mileage range, since it only has 5 points there), so tests below
# derive expected adjusted medians from the actual fitted slope rather
# than assuming raw prices pass through unchanged. The slope's own
# correctness is trend.py's job to test, not this file's.
BUCKET_PRICES = {0: 45_000, 1: 40_000, 2: 36_000, 3: 34_000}
BUCKET_FIRST_REG = {0: date(2025, 6, 1), 1: date(2024, 6, 1), 2: date(2023, 6, 1), 3: date(2022, 6, 1)}
BUCKET_KM = [55_000 + i * 1_000 for i in range(12)]


def _synthetic_listings() -> list[DepreciationInput]:
    listings: list[DepreciationInput] = []
    for bucket_index, price in BUCKET_PRICES.items():
        first_reg = BUCKET_FIRST_REG[bucket_index]
        for km in BUCKET_KM:
            listings.append((first_reg, km, float(price)))
    # A thin bucket: only 5 listings at ~4yr old.
    for km in BUCKET_KM[:5]:
        listings.append((date(2021, 6, 1), km, 32_000.0))
    return listings


def test_age_in_years():
    assert age_in_years(date(2024, 1, 1), as_of=date(2026, 1, 1)) == pytest.approx(2.0, abs=0.01)


@pytest.mark.parametrize(
    ("age", "expected_index"),
    [(0.3, 0), (0.99, 0), (1.0, 1), (2.5, 2), (6.9, 6), (7.0, 7), (12.0, 7)],
)
def test_age_bucket_index_caps_at_max_bucket(age, expected_index):
    assert age_bucket_index(age, max_bucket=7) == expected_index


@pytest.mark.parametrize(
    ("index", "label"), [(0, "under_1yr"), (1, "1yr"), (3, "3yr"), (7, "7yr_plus")]
)
def test_age_bucket_label(index, label):
    assert age_bucket_label(index, max_bucket=7) == label


def test_normalize_price_shifts_toward_reference_mileage():
    # Car has fewer km than the reference -> normalizing "up" to the
    # reference mileage should lower the estimated price (slope is negative).
    adjusted = normalize_price(40_000, mileage_km=40_000, reference_km=60_000, slope_eur_per_km=-0.05)
    assert adjusted == pytest.approx(39_000)


def test_compute_depreciation_curve_buckets_and_thin_flag():
    listings = _synthetic_listings()
    slope, _ = linear_slope([(km, price) for _, km, price in listings])
    median_km = statistics_median(BUCKET_KM)

    buckets = compute_depreciation_curve(listings, as_of=AS_OF, reference_km=60_000, min_bucket_size=10)
    by_label = {b.label: b for b in buckets}

    assert by_label["under_1yr"].n == 12
    assert by_label["under_1yr"].median_price_eur == pytest.approx(
        BUCKET_PRICES[0] + slope * (60_000 - median_km)
    )
    assert by_label["under_1yr"].is_thin is False

    assert by_label["3yr"].n == 12
    assert by_label["3yr"].median_price_eur == pytest.approx(BUCKET_PRICES[3] + slope * (60_000 - median_km))

    assert by_label["4yr"].n == 5
    assert by_label["4yr"].is_thin is True


def test_compute_depreciation_curve_needs_at_least_two_listings():
    with pytest.raises(ValueError):
        compute_depreciation_curve([(date(2024, 1, 1), 50_000, 40_000.0)], as_of=AS_OF)


def test_bucket_transitions_excludes_thin_buckets():
    buckets = compute_depreciation_curve(_synthetic_listings(), as_of=AS_OF, min_bucket_size=10)
    transitions = bucket_transitions(buckets)
    # under_1yr -> 1yr -> 2yr -> 3yr, but NOT -> 4yr (thin, excluded)
    labels = [(t.from_label, t.to_label) for t in transitions]
    assert labels == [("under_1yr", "1yr"), ("1yr", "2yr"), ("2yr", "3yr")]


def test_steepest_drop_and_curve_flattens():
    buckets = compute_depreciation_curve(_synthetic_listings(), as_of=AS_OF, min_bucket_size=10)
    transitions = bucket_transitions(buckets)

    drop = steepest_drop(transitions)
    assert drop is not None
    assert (drop.from_label, drop.to_label) == ("under_1yr", "1yr")
    assert drop.delta_eur == pytest.approx(-5_000)

    flattest = curve_flattens_at(transitions)
    assert flattest is not None
    assert (flattest.from_label, flattest.to_label) == ("2yr", "3yr")
    assert flattest.delta_eur == pytest.approx(-2_000)


def test_steepest_drop_empty_transitions_returns_none():
    assert steepest_drop([]) is None
    assert curve_flattens_at([]) is None


def test_cheapest_to_own_picks_lowest_annualized_cost():
    buckets = compute_depreciation_curve(_synthetic_listings(), as_of=AS_OF, min_bucket_size=10)
    by_index = {b.bucket_index: b for b in buckets if not b.is_thin}
    horizon_price = by_index[3].median_price_eur

    # Derive the expected winner from the buckets actually returned (their
    # medians already include the real, small mileage-normalization
    # adjustment - see the module comment above) rather than from raw
    # synthetic prices, so this test only exercises cheapest_to_own's own
    # argmin logic, not a hand-guessed slope.
    expected_index = min(
        (idx for idx in by_index if idx < 3),
        key=lambda idx: (by_index[idx].median_price_eur - horizon_price) / (3 - idx),
    )
    expected_annual_cost = (by_index[expected_index].median_price_eur - horizon_price) / (3 - expected_index)

    result = cheapest_to_own(buckets, horizon_years=3)
    assert result is not None
    assert result.buy_at_label == by_index[expected_index].label
    assert result.buy_price_eur == pytest.approx(by_index[expected_index].median_price_eur)
    assert result.annual_cost_eur == pytest.approx(expected_annual_cost)
    assert result.horizon_years == 3
    # Sanity check this synthetic data still exercises the interesting
    # case (an earlier, cheaper-per-year entry point winning over horizon_years - 1).
    assert expected_index == 2


def test_cheapest_to_own_none_when_horizon_bucket_missing():
    buckets = compute_depreciation_curve(_synthetic_listings(), as_of=AS_OF, min_bucket_size=10)
    assert cheapest_to_own(buckets, horizon_years=99) is None
