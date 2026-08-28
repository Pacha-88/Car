import pytest

from car_tracker.analysis.trend import binned_median_trend, linear_slope


def test_binned_median_trend_groups_by_bin_and_takes_median():
    points = [
        (1_000, 50_000),  # bin 0
        (5_000, 48_000),  # bin 0
        (9_000, 100_000),  # bin 0, outlier - median should shrug this off
        (12_000, 44_000),  # bin 1
        (18_000, 42_000),  # bin 1
    ]
    result = binned_median_trend(points, bin_width_km=10_000)
    assert result == [(5_000, 50_000), (15_000, 43_000)]


def test_binned_median_trend_empty_input():
    assert binned_median_trend([], bin_width_km=10_000) == []


def test_linear_slope_exact_fit():
    # price = -0.05 * km + 50_000, exactly, no noise
    points = [(0, 50_000), (10_000, 49_500), (20_000, 49_000), (40_000, 48_000)]
    slope, intercept = linear_slope(points)
    assert slope == pytest.approx(-0.05)
    assert intercept == pytest.approx(50_000)


def test_linear_slope_needs_at_least_two_points():
    with pytest.raises(ValueError):
        linear_slope([(1_000, 40_000)])


def test_linear_slope_needs_mileage_variance():
    with pytest.raises(ValueError):
        linear_slope([(50_000, 40_000), (50_000, 41_000), (50_000, 39_000)])
