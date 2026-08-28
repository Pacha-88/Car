from datetime import date

import pytest

from car_tracker.normalize.chassis import detect_chassis


def test_model_3_legacy_by_registration_date():
    assert detect_chassis("model_3", first_registration=date(2022, 5, 1)) == "legacy"


def test_model_3_highland_by_registration_date():
    assert detect_chassis("model_3", first_registration=date(2024, 1, 15)) == "highland"


def test_model_y_legacy_by_model_year():
    assert detect_chassis("model_y", model_year=2023) == "legacy"


def test_model_y_juniper_by_model_year():
    assert detect_chassis("model_y", model_year=2025) == "juniper"


def test_title_hint_wins_over_date():
    # A source occasionally spells the generation out; trust that over a
    # date that would otherwise say "legacy".
    assert detect_chassis("model_y", first_registration=date(2022, 1, 1), title="Tesla Model Y Juniper Facelift") == "juniper"


def test_no_signal_returns_none():
    assert detect_chassis("model_3") is None


def test_unknown_model_raises():
    with pytest.raises(ValueError):
        detect_chassis("model_s")
