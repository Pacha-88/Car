from datetime import date

import pytest

from statistics import median as statistics_median

from car_tracker.analysis.depreciation import (
    BucketTransition,
    DepreciationBucket,
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


def test_steepest_drop_never_reports_a_rise():
    """A curve that only goes up has no drop to name.

    Thin buckets in a narrow selection routinely produce an all-rising
    curve; before this, the smallest rise was printed under a "steepest
    drop" heading as a positive number.
    """
    rising = [
        BucketTransition(from_label="1yr", to_label="2yr", delta_eur=1_989.0),
        BucketTransition(from_label="2yr", to_label="3yr", delta_eur=412.0),
    ]
    assert steepest_drop(rising) is None

    mixed = [*rising, BucketTransition(from_label="3yr", to_label="4yr", delta_eur=-300.0)]
    drop = steepest_drop(mixed)
    assert drop is not None
    assert drop.delta_eur == pytest.approx(-300.0)

    # A perfectly flat step is not a drop either, though it does count as
    # the curve flattening.
    flat = [BucketTransition(from_label="1yr", to_label="2yr", delta_eur=0.0)]
    assert steepest_drop(flat) is None
    assert curve_flattens_at(flat) is not None


def test_cheapest_to_own_picks_lowest_annualized_cost():
    buckets = compute_depreciation_curve(_synthetic_listings(), as_of=AS_OF, min_bucket_size=10)
    by_index = {b.bucket_index: b for b in buckets if not b.is_thin}

    # Derive the expected winner from the buckets actually returned (their
    # medians already include the real, small mileage-normalization
    # adjustment - see the module comment above) rather than from raw
    # synthetic prices, so this test only exercises cheapest_to_own's own
    # argmin logic, not a hand-guessed slope. Every candidate is held the
    # same three years: buy at i, sell at i + 3.
    candidates = {
        idx: (by_index[idx].median_price_eur - by_index[idx + 3].median_price_eur) / 3
        for idx in by_index
        if idx + 3 in by_index and not by_index[idx + 3].label.endswith("_plus")
    }
    expected_index = min(candidates, key=candidates.__getitem__)

    result = cheapest_to_own(buckets, horizon_years=3)
    assert result is not None
    assert result.buy_at_label == by_index[expected_index].label
    assert result.sell_at_label == by_index[expected_index + 3].label
    assert result.buy_price_eur == pytest.approx(by_index[expected_index].median_price_eur)
    assert result.annual_cost_eur == pytest.approx(candidates[expected_index])
    assert result.horizon_years == 3
    # This fixture spans four usable ages, so exactly one buy/sell pair fits
    # a three-year hold. The multi-candidate choice - and the older entry
    # winning it - is covered by test_every_candidate_is_held_for_the_same_span.
    assert len(candidates) == 1


def test_cheapest_to_own_none_when_no_candidate_has_a_priced_exit():
    buckets = compute_depreciation_curve(_synthetic_listings(), as_of=AS_OF, min_bucket_size=10)
    assert cheapest_to_own(buckets, horizon_years=99) is None


def test_every_candidate_is_held_for_the_same_span():
    """The bug this replaced: the horizon was an exit AGE, so candidates were
    held 3, 2 and 1 years under one "· 3yr" label, and any car at or past
    that age was excluded - on the real Model 3 data the genuinely cheapest
    three-year hold (buy at 4yr) was never a candidate at all."""
    buckets = [
        DepreciationBucket(label="under_1yr", bucket_index=0, n=20, median_price_eur=46_000, is_thin=False, p25_price_eur=45_000, p75_price_eur=47_000),
        DepreciationBucket(label="2yr", bucket_index=2, n=20, median_price_eur=35_000, is_thin=False, p25_price_eur=34_000, p75_price_eur=36_000),
        DepreciationBucket(label="3yr", bucket_index=3, n=20, median_price_eur=34_000, is_thin=False, p25_price_eur=33_000, p75_price_eur=35_000),
        DepreciationBucket(label="4yr", bucket_index=4, n=20, median_price_eur=33_600, is_thin=False, p25_price_eur=33_000, p75_price_eur=34_000),
        DepreciationBucket(label="5yr", bucket_index=5, n=20, median_price_eur=33_400, is_thin=False, p25_price_eur=33_000, p75_price_eur=34_000),
    ]
    result = cheapest_to_own(buckets, horizon_years=3)
    assert result is not None
    # under_1yr -> 3yr costs (46000-34000)/3 = 4000/yr; 2yr -> 5yr costs
    # (35000-33400)/3 = 533/yr. The older entry wins, and could not even be
    # considered before.
    assert (result.buy_at_label, result.sell_at_label) == ("2yr", "5yr")
    assert result.annual_cost_eur == pytest.approx(533.33, rel=1e-3)


def test_the_catch_all_bucket_cannot_price_an_exit():
    """Its median blends every age above the cap - not the price of any
    particular car three years from now."""
    buckets = [
        DepreciationBucket(label="4yr", bucket_index=4, n=20, median_price_eur=33_000, is_thin=False, p25_price_eur=32_000, p75_price_eur=34_000),
        DepreciationBucket(label="7yr_plus", bucket_index=7, n=20, median_price_eur=20_000, is_thin=False, p25_price_eur=18_000, p75_price_eur=22_000),
    ]
    assert cheapest_to_own(buckets, horizon_years=3) is None


def test_curve_flattens_at_never_reports_a_price_rise():
    """A rise is thin-bucket noise, not flattening. Real case: the Model 3
    6yr -> 7yr+ step is +1.373 EUR."""
    rise = BucketTransition(from_label="6yr", to_label="7yr_plus", delta_eur=1_373)
    gentle = BucketTransition(from_label="4yr", to_label="5yr", delta_eur=-142)
    steep = BucketTransition(from_label="1yr", to_label="2yr", delta_eur=-4_000)

    assert curve_flattens_at([steep, gentle, rise]) is gentle
    assert curve_flattens_at([rise]) is None, "nothing declined - the card has nothing honest to say"


def test_buckets_carry_interquartile_range():
    buckets = compute_depreciation_curve(_synthetic_listings(), as_of=AS_OF, min_bucket_size=10)
    for bucket in buckets:
        # The band must bracket the median and never invert.
        assert bucket.p25_price_eur <= bucket.median_price_eur <= bucket.p75_price_eur
    # And on real multi-listing buckets it must have actual width (the
    # synthetic data spreads prices within each bucket).
    wide = [b for b in buckets if b.n >= 10]
    assert wide, "synthetic data should produce at least one non-thin bucket"
    assert any(b.p75_price_eur > b.p25_price_eur for b in wide)


def test_single_listing_bucket_collapses_band_to_the_point():
    from datetime import date

    listings = [
        (date(2025, 6, 1), 10_000, 40_000.0),
        (date(2019, 6, 1), 90_000, 20_000.0),
    ]
    buckets = compute_depreciation_curve(listings, as_of=AS_OF, min_bucket_size=10)
    for bucket in buckets:
        assert bucket.n == 1
        assert bucket.p25_price_eur == bucket.median_price_eur == bucket.p75_price_eur


def test_a_future_dated_registration_lands_in_the_under_1yr_bucket_not_a_negative_one():
    """The plausibility guard deliberately lets a registration date run one
    day ahead (month-granularity sources, UTC runner). A negative age must
    clamp to bucket 0: the TS copy's Math.floor gave it bucket -1, which
    the label function rendered as a literal "-1yr" tab on the dashboard.
    Pinned here on the reference copy; a numeric parity harness holds the
    two implementations together."""
    assert age_bucket_index(-0.003) == 0
    assert age_bucket_index(-1.5) == 0
    assert age_bucket_index(0.0) == 0
    assert age_bucket_index(0.99) == 0
    assert age_bucket_index(1.0) == 1
