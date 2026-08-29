"""normalize/registration.py — dates that cannot be true."""

from datetime import date

import pytest

from car_tracker.normalize.registration import FIRST_DELIVERY_YEAR, plausible_registration

TODAY = date(2026, 8, 29)


def check(model, first_registration=None, model_year=None):
    return plausible_registration(
        model, first_registration=first_registration, model_year=model_year, today=TODAY
    )


def test_the_typo_that_prompted_this():
    """A real listing: right price, right mileage, "Certified Pre-Owned",
    dated 12/2002 instead of 12/2022. It stretched the dashboard's year
    filter from 2017-2026 to 2002-2026 and entered the depreciation curve
    as a 23-year-old car worth 34.600 EUR."""
    assert check("model_y", date(2002, 12, 1), 2002) == (None, None)


@pytest.mark.parametrize(
    ("model", "day"),
    [("model_y", date(2020, 6, 1)), ("model_y", date(2022, 3, 1)), ("model_3", date(2017, 7, 1))],
)
def test_real_dates_are_left_alone(model, day):
    """Only the impossible is refused, never the merely surprising - an
    early US-built Model 3 imported to Europe is unusual, not wrong."""
    assert check(model, day, day.year) == (day, day.year)


def test_a_car_cannot_predate_its_own_model():
    assert check("model_y", date(2019, 12, 1), 2019) == (None, None)  # Y deliveries began 2020
    assert check("model_3", date(2016, 7, 1), 2016) == (None, None)  # 3 deliveries began 2017


def test_a_registration_cannot_be_in_the_future_but_a_model_year_label_can():
    """Cars are sold as "2027 models" during 2026; they are not registered
    in 2027 during 2026."""
    assert check("model_y", date(2027, 1, 1), 2027) == (None, 2027)


def test_missing_values_stay_missing():
    assert check("model_y", None, None) == (None, None)


def test_an_unknown_model_is_left_untouched():
    """Adding a model without adding its delivery year must not silently
    blank every date that model has."""
    assert check("model_x", date(2005, 1, 1), 2005) == (date(2005, 1, 1), 2005)


def test_every_tracked_model_has_a_delivery_year():
    from car_tracker.cli import MODELS

    assert set(MODELS) <= set(FIRST_DELIVERY_YEAR)


def test_a_registration_this_month_survives_a_runner_clock_behind_the_market():
    """"Today" is the runner's date; the registration is the market's. The
    scheduled run is UTC while these cars are European, and the sources give
    month granularity (parsed to the 1st) - so at 00:30 UTC on the 1st, a
    car registered that very month must not lose its date."""
    at_month_end = plausible_registration(
        "model_y", first_registration=date(2026, 9, 1), model_year=2026, today=date(2026, 8, 31)
    )
    assert at_month_end == (date(2026, 9, 1), 2026)


def test_the_slack_is_a_day_not_a_licence():
    """Still no cars registered months from now."""
    assert check("model_y", date(2026, 12, 1), 2026)[0] is None
